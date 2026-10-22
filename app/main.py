"""Servidor web: atiende las llamadas que manda Twilio y muestra el panel de recados."""

import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import Gather, VoiceResponse

from . import asistente, avisos, db
from .config import RAIZ, ajustes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("asistente_llamadas")

# Palabras del oficio para que el reconocedor de voz las entienda mejor.
PISTAS_VOZ = (
    "presupuesto, barandilla, reja, puerta corredera, puerta basculante, cancela, persiana, "
    "cerrajería, soldadura, acero inoxidable, hierro, aluminio, galvanizado, lacado, forja, "
    "escalera, estructura, cerramiento, pérgola, toldo, vallado, motor, mando, avería"
)

FRASE_SILENCIO = "¿Sigue ahí? Cuénteme en qué le puedo ayudar."
FRASE_DESPEDIDA_SILENCIO = (
    "No le oigo bien. Le dejo apuntado su número para que {dueno} le llame. Hasta luego."
)
FRASE_FALLO = (
    "Perdone, estoy teniendo un problema técnico. Ya he apuntado su número y lo que me ha contado, "
    "y {dueno} le llamará lo antes posible. Disculpe las molestias."
)
FRASE_LIMITE = (
    "Muchas gracias, ya lo tengo todo apuntado. {dueno} le llamará lo antes posible. Hasta luego."
)
ESTADOS_FINALES = {"completed", "busy", "failed", "no-answer", "canceled"}


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    db.iniciar()
    if not ajustes.twilio_auth_token:
        log.warning("TWILIO_AUTH_TOKEN vacío: no se comprueba que las llamadas vengan de Twilio.")
    yield


app = FastAPI(title="Asistente de llamadas", lifespan=ciclo_de_vida)
plantillas = Jinja2Templates(directory=RAIZ / "app" / "templates")


# --------------------------------------------------------------------------- Twilio


async def formulario_twilio(request: Request) -> dict:
    """Lee los datos que manda Twilio y comprueba la firma para que nadie más pueda usar el servidor."""
    datos = {k: str(v) for k, v in (await request.form()).items()}
    if ajustes.twilio_auth_token:
        url = str(request.url)
        if ajustes.url_publica:
            url = ajustes.url_publica + request.url.path
            if request.url.query:
                url += "?" + request.url.query
        firma = request.headers.get("X-Twilio-Signature", "")
        if not RequestValidator(ajustes.twilio_auth_token).validate(url, datos, firma):
            raise HTTPException(status_code=403, detail="Firma de Twilio no válida")
    return datos


def _twiml(respuesta: VoiceResponse) -> Response:
    return Response(content=str(respuesta), media_type="application/xml")


def _decir(destino, texto: str) -> None:
    destino.say(texto, voice=ajustes.voz, language=ajustes.idioma)


def _escuchar(texto: str) -> Response:
    """Dice el texto y espera a que la persona hable."""
    respuesta = VoiceResponse()
    gather = Gather(
        input="speech",
        language=ajustes.idioma,
        action="/voz/turno",
        method="POST",
        speech_timeout="auto",
        timeout=6,
        hints=PISTAS_VOZ,
        action_on_empty_result=True,
    )
    _decir(gather, texto)
    respuesta.append(gather)
    return _twiml(respuesta)


def _colgar(texto: str) -> Response:
    respuesta = VoiceResponse()
    _decir(respuesta, texto)
    respuesta.hangup()
    return _twiml(respuesta)


def procesar_fin_de_llamada(call_sid: str) -> None:
    """Resume la llamada, la deja en el panel y avisa. Solo se ejecuta una vez por llamada."""
    if not db.reclamar_para_resumen(call_sid):
        return
    llamada = db.obtener(call_sid)
    if any(t["quien"] == "cliente" for t in llamada["turnos"]):
        try:
            resumen = asistente.resumir(llamada["turnos"], llamada["numero"], llamada["inicio"])
            estado = "lista"
        except Exception:
            log.exception("No se pudo resumir la llamada %s", call_sid)
            resumen = {
                "titulo": "Recado sin resumir (mira la conversación)",
                "motivo": "otro",
                "urgencia": "media",
                "resumen": "No se pudo generar el resumen automático. Abre la llamada para leer lo que dijo.",
                "datos": [],
                "que_hacer": "Leer la conversación y devolver la llamada.",
            }
            estado = "error"
    else:
        resumen = {
            "titulo": "Colgó sin dejar recado",
            "motivo": "otro",
            "urgencia": "baja",
            "resumen": "La persona colgó o no dijo nada.",
            "datos": [],
            "que_hacer": "Devolver la llamada si el número te suena.",
        }
        estado = "lista"
    db.guardar_resumen(call_sid, resumen, estado)
    avisos.enviar(db.obtener(call_sid))


@app.post("/voz/entrante")
async def voz_entrante(datos: dict = Depends(formulario_twilio)):
    call_sid = datos["CallSid"]
    db.crear_llamada(call_sid, datos.get("From") or None)
    if not db.obtener(call_sid)["turnos"]:
        db.anadir_turno(call_sid, "asistente", ajustes.texto_saludo)
    return _escuchar(ajustes.texto_saludo)


@app.post("/voz/turno")
async def voz_turno(background: BackgroundTasks, datos: dict = Depends(formulario_twilio)):
    call_sid = datos["CallSid"]
    llamada = db.obtener(call_sid)
    if llamada is None:  # por si se pierde el aviso de llamada entrante
        db.crear_llamada(call_sid, datos.get("From") or None)
        llamada = db.obtener(call_sid)
    dueno = ajustes.nombre_dueno

    dicho = datos.get("SpeechResult", "").strip()
    if not dicho:
        if db.sumar_silencio(call_sid) >= 2:
            background.add_task(procesar_fin_de_llamada, call_sid)
            return _colgar(FRASE_DESPEDIDA_SILENCIO.format(dueno=dueno))
        return _escuchar(FRASE_SILENCIO)

    db.reiniciar_silencios(call_sid)
    turnos = db.anadir_turno(call_sid, "cliente", dicho)

    if sum(t["quien"] == "cliente" for t in turnos) > ajustes.max_turnos:
        db.anadir_turno(call_sid, "asistente", FRASE_LIMITE.format(dueno=dueno))
        background.add_task(procesar_fin_de_llamada, call_sid)
        return _colgar(FRASE_LIMITE.format(dueno=dueno))

    try:
        respuesta = await run_in_threadpool(asistente.responder, turnos, llamada["numero"])
    except Exception:
        log.exception("Fallo al generar la respuesta de la llamada %s", call_sid)
        texto = FRASE_FALLO.format(dueno=dueno)
        db.anadir_turno(call_sid, "asistente", texto)
        background.add_task(procesar_fin_de_llamada, call_sid)
        return _colgar(texto)

    db.anadir_turno(call_sid, "asistente", respuesta.texto)
    if respuesta.colgar:
        background.add_task(procesar_fin_de_llamada, call_sid)
        return _colgar(respuesta.texto)
    return _escuchar(respuesta.texto)


@app.post("/voz/estado")
async def voz_estado(background: BackgroundTasks, datos: dict = Depends(formulario_twilio)):
    """Twilio avisa aquí cuando la llamada termina (también si la persona cuelga a mitad)."""
    if datos.get("CallStatus") in ESTADOS_FINALES:
        call_sid = datos["CallSid"]
        db.crear_llamada(call_sid, datos.get("From") or None)
        background.add_task(procesar_fin_de_llamada, call_sid)
    return Response(status_code=204)


# --------------------------------------------------------------------------- Panel

seguridad = HTTPBasic(realm="Recados")


def usuario_panel(credenciales: HTTPBasicCredentials = Depends(seguridad)) -> str:
    if not ajustes.panel_contrasena:
        raise HTTPException(503, "Falta poner PANEL_CONTRASENA en la configuración")
    ok_usuario = secrets.compare_digest(credenciales.username.encode(), ajustes.panel_usuario.encode())
    ok_clave = secrets.compare_digest(credenciales.password.encode(), ajustes.panel_contrasena.encode())
    if not (ok_usuario and ok_clave):
        raise HTTPException(401, "Usuario o contraseña incorrectos", headers={"WWW-Authenticate": "Basic"})
    return credenciales.username


def _hora_local(iso: str | None) -> str:
    if not iso:
        return ""
    momento = datetime.fromisoformat(iso).astimezone(ZoneInfo(ajustes.zona_horaria))
    hoy = datetime.now(ZoneInfo(ajustes.zona_horaria)).date()
    if momento.date() == hoy:
        return f"hoy {momento:%H:%M}"
    if (hoy - momento.date()).days == 1:
        return f"ayer {momento:%H:%M}"
    return f"{momento:%d/%m %H:%M}"


def _solo_digitos(numero: str | None) -> str:
    return "".join(c for c in (numero or "") if c.isdigit())


plantillas.env.filters["hora"] = _hora_local
plantillas.env.filters["digitos"] = _solo_digitos
plantillas.env.globals["MOTIVOS"] = asistente.MOTIVOS
plantillas.env.globals["ajustes"] = ajustes


@app.get("/")
def panel(request: Request, _usuario: str = Depends(usuario_panel)):
    # Los urgentes primero; dentro de cada grupo, los más recientes arriba.
    pendientes = sorted(
        db.listar(hecha=False), key=lambda ll: (ll["resumen"] or {}).get("urgencia") != "alta"
    )
    return plantillas.TemplateResponse(
        request,
        "panel.html",
        {"pendientes": pendientes, "hechas": db.listar(hecha=True, limite=30)},
    )


@app.get("/llamada/{call_sid}")
def ver_llamada(request: Request, call_sid: str, _usuario: str = Depends(usuario_panel)):
    llamada = db.obtener(call_sid)
    if llamada is None:
        raise HTTPException(404, "No existe esa llamada")
    return plantillas.TemplateResponse(request, "llamada.html", {"llamada": llamada})


@app.post("/llamada/{call_sid}/hecha")
def cambiar_hecha(call_sid: str, _usuario: str = Depends(usuario_panel)):
    llamada = db.obtener(call_sid)
    if llamada is None:
        raise HTTPException(404, "No existe esa llamada")
    db.marcar_hecha(call_sid, not llamada["hecha"])
    return RedirectResponse("/", status_code=303)


@app.get("/salud")
def salud():
    return {"ok": True}
