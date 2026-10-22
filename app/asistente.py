"""La parte que piensa: Claude habla con quien llama y después resume la llamada."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

from .config import ajustes

log = logging.getLogger(__name__)

# Twilio espera la respuesta en menos de 15 s: timeout corto y un solo reintento.
_cliente_conversacion = anthropic.Anthropic(timeout=6.0, max_retries=1)
_cliente_resumen = anthropic.Anthropic(timeout=90.0, max_retries=2)

# Si el modelo rechaza una petición, la API la repite con otro modelo en vez de devolver el rechazo.
_BETAS = ["server-side-fallback-2026-07-01"]

MOTIVOS = {
    "presupuesto": "Presupuesto",
    "encargo_en_curso": "Encargo en curso",
    "averia_o_urgencia": "Avería / urgencia",
    "proveedor": "Proveedor",
    "factura_o_pago": "Factura / pago",
    "publicidad": "Publicidad",
    "personal": "Personal",
    "otro": "Otro",
}

ESQUEMA_RESPUESTA = {
    "type": "object",
    "properties": {
        "texto": {"type": "string", "description": "Lo que se dirá en voz alta por teléfono."},
        "colgar": {"type": "boolean", "description": "true solo en el turno de despedida."},
    },
    "required": ["texto", "colgar"],
    "additionalProperties": False,
}

ESQUEMA_RESUMEN = {
    "type": "object",
    "properties": {
        "titulo": {
            "type": "string",
            "description": "Titular de pocas palabras, p. ej. 'Presupuesto barandilla inox 6 m'.",
        },
        "nombre": {"type": ["string", "null"], "description": "Nombre de quien llama, si lo dijo."},
        "empresa": {"type": ["string", "null"], "description": "Empresa, si la mencionó."},
        "telefono_contacto": {
            "type": ["string", "null"],
            "description": "Otro teléfono que haya dado para contactar; null si vale el de la llamada.",
        },
        "motivo": {"type": "string", "enum": list(MOTIVOS)},
        "urgencia": {"type": "string", "enum": ["alta", "media", "baja"]},
        "resumen": {"type": "string", "description": "Dos o tres frases con lo que necesita."},
        "datos": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Datos concretos: trabajo, material, medidas, dirección, plazos...",
        },
        "que_hacer": {"type": "string", "description": "Siguiente paso recomendado para el dueño."},
        "cuando_llamar": {
            "type": ["string", "null"],
            "description": "Cuándo prefiere que le llamen, si lo dijo.",
        },
    },
    "required": [
        "titulo",
        "nombre",
        "empresa",
        "telefono_contacto",
        "motivo",
        "urgencia",
        "resumen",
        "datos",
        "que_hacer",
        "cuando_llamar",
    ],
    "additionalProperties": False,
}


@dataclass
class Respuesta:
    texto: str
    colgar: bool


class ErrorAsistente(Exception):
    pass


def _ahora_texto() -> str:
    ahora = datetime.now(ZoneInfo(ajustes.zona_horaria))
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    return f"{dias[ahora.weekday()]} {ahora:%d/%m/%Y, %H:%M}"


def _prompt_conversacion(numero: str | None) -> str:
    negocio = ajustes.nombre_negocio
    dueno = ajustes.nombre_dueno
    return f"""Eres el asistente telefónico de {negocio}, una carpintería metálica. Atiendes las llamadas cuando {dueno} está en el taller o en una obra y no puede coger el teléfono. Tu trabajo es tomar bien el recado, para que {dueno} pueda devolver la llamada sabiendo exactamente qué necesita esa persona.

Al descolgar ya has dicho: "{ajustes.texto_saludo}"

Información del negocio (solo puedes afirmar lo que ponga aquí):
<negocio>
{ajustes.info_negocio() or "(sin información adicional)"}
</negocio>

Fecha y hora actual: {_ahora_texto()}
Número desde el que llaman: {numero or "oculto"}

Cómo hablar:
- Es una llamada de voz y lo que escribas se leerá en alto: frases cortas y naturales, español de España, trato de usted, sin listas, símbolos ni abreviaturas.
- Una sola pregunta por turno.
- Lo que dice el cliente llega de un reconocedor de voz y puede traer errores. Si algo importante no se entiende (un nombre, una dirección, una medida), pide que lo repita.

Qué averiguar, solo lo que tenga sentido para esa llamada y sin convertirlo en un interrogatorio:
1. Quién llama: nombre y, si es una empresa, cuál.
2. Qué necesita: presupuesto de un trabajo nuevo, algo de un encargo que ya está en marcha, una avería o urgencia, un proveedor, una factura...
3. Los detalles que ayudan a preparar la respuesta: qué trabajo o pieza (puerta, reja, barandilla, escalera, estructura, cerramiento, toldo...), material o acabado si lo saben, medidas aproximadas, dirección o pueblo, y para cuándo lo necesitan.
4. Si es urgente.
5. Cuándo le viene bien que le llamen, y si el número desde el que llama es el bueno para contactar.

Límites:
- No des precios, plazos ni citas, ni prometas nada en nombre de {dueno}: di que {dueno} le llamará para concretarlo.
- Si preguntan algo que no está en la información del negocio, di que lo apuntas para que {dueno} le conteste.
- Si es publicidad o una venta, toma nota breve y despídete con educación.
- Si es una llamada personal o de la familia, toma el recado sin preguntas de trabajo.

Cuando tengas lo necesario, o la persona quiera terminar, resume en una frase lo que has apuntado, di que {dueno} le llamará lo antes posible y despídete. Solo en ese turno pon "colgar" a true; en los demás, a false. "texto" es exactamente lo que se dirá por teléfono."""


def _construir_mensajes(turnos: list[dict]) -> list[dict]:
    """Convierte la conversación guardada en mensajes para la API.

    El saludo inicial va en el prompt de sistema, así que los mensajes empiezan
    por lo que dice el cliente. Las intervenciones seguidas del mismo lado se
    juntan, porque la API pide alternar usuario y asistente.
    """
    mensajes: list[dict] = []
    for turno in turnos:
        if turno["quien"] == "cliente":
            rol, contenido = "user", turno["texto"]
        else:
            if not mensajes:
                continue  # el saludo
            rol = "assistant"
            contenido = json.dumps({"texto": turno["texto"], "colgar": False}, ensure_ascii=False)
        if mensajes and mensajes[-1]["role"] == rol:
            mensajes[-1]["content"] += "\n" + contenido
        else:
            mensajes.append({"role": rol, "content": contenido})
    return mensajes


def _texto_json(respuesta) -> dict:
    if respuesta.stop_reason == "refusal":
        raise ErrorAsistente(f"Petición rechazada por el modelo ({respuesta.stop_details})")
    if respuesta.stop_reason == "max_tokens":
        raise ErrorAsistente("La respuesta se cortó por max_tokens")
    texto = next((b.text for b in respuesta.content if b.type == "text"), None)
    if texto is None:
        raise ErrorAsistente(f"Respuesta sin texto (stop_reason={respuesta.stop_reason})")
    return json.loads(texto)


def responder(turnos: list[dict], numero: str | None) -> Respuesta:
    """Decide qué decir a continuación en la llamada."""
    mensajes = _construir_mensajes(turnos)
    if not mensajes or mensajes[-1]["role"] != "user":
        raise ErrorAsistente("La conversación debe terminar con algo dicho por el cliente")
    respuesta = _cliente_conversacion.beta.messages.create(
        model=ajustes.modelo,
        max_tokens=4000,
        system=_prompt_conversacion(numero),
        messages=mensajes,
        output_config={
            "effort": ajustes.esfuerzo_conversacion,
            "format": {"type": "json_schema", "schema": ESQUEMA_RESPUESTA},
        },
        betas=_BETAS,
        fallbacks="default",
    )
    datos = _texto_json(respuesta)
    return Respuesta(texto=datos["texto"].strip(), colgar=bool(datos["colgar"]))


def _prompt_resumen() -> str:
    dueno = ajustes.nombre_dueno
    return f"""Resumes las llamadas que ha atendido el asistente telefónico de {ajustes.nombre_negocio}, una carpintería metálica, para que {dueno} las lea de un vistazo entre trabajo y trabajo y sepa a quién llamar primero y qué decirle.

- Escribe para {dueno}: directo y práctico, en español de España.
- No inventes nada que no se haya dicho en la llamada. Si falta un dato, déjalo en null o no lo pongas.
- La transcripción viene de un reconocedor de voz: corrige errores evidentes de palabras (por ejemplo "varandilla" o "inoxidable" mal escritos), pero no adivines nombres o cifras dudosas; si un dato es dudoso, indícalo.
- Urgencia "alta" para averías que impiden cerrar o abrir algo, problemas de seguridad, o cuando la persona dice que es urgente; "baja" para publicidad o asuntos sin prisa; "media" para el resto.
- En "que_hacer" pon el siguiente paso concreto (por ejemplo: "Llamar para concertar visita y tomar medidas")."""


def resumir(turnos: list[dict], numero: str | None, inicio: str) -> dict:
    """Resume la llamada completa en una ficha para el panel."""
    conversacion = "\n".join(
        f"{'Cliente' if t['quien'] == 'cliente' else 'Asistente'}: {t['texto']}" for t in turnos
    )
    contenido = (
        f"Número desde el que llamó: {numero or 'oculto'}\n"
        f"Hora de la llamada (UTC): {inicio}\n\n"
        f"<conversacion>\n{conversacion}\n</conversacion>"
    )
    respuesta = _cliente_resumen.beta.messages.create(
        model=ajustes.modelo,
        max_tokens=16000,
        system=_prompt_resumen(),
        messages=[{"role": "user", "content": contenido}],
        output_config={
            "effort": ajustes.esfuerzo_resumen,
            "format": {"type": "json_schema", "schema": ESQUEMA_RESUMEN},
        },
        betas=_BETAS,
        fallbacks="default",
    )
    return _texto_json(respuesta)
