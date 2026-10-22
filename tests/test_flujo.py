import base64

import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app import asistente, db, main
from app.asistente import Respuesta, _construir_mensajes
from app.config import ajustes

RESUMEN = {
    "titulo": "Presupuesto barandilla inox",
    "nombre": "Luis",
    "empresa": None,
    "telefono_contacto": None,
    "motivo": "presupuesto",
    "urgencia": "media",
    "resumen": "Quiere presupuesto para una barandilla de acero inoxidable de unos 6 metros.",
    "datos": ["Barandilla acero inoxidable", "Unos 6 metros", "Calle Mayor 3, Lorca"],
    "que_hacer": "Llamar para ir a medir.",
    "cuando_llamar": "Por la tarde",
}


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(ajustes, "ruta_bd", tmp_path / "prueba.db")
    monkeypatch.setattr(ajustes, "twilio_auth_token", "")
    monkeypatch.setattr(ajustes, "panel_contrasena", "secreta")
    monkeypatch.setattr(ajustes, "telegram_token", "")
    monkeypatch.setattr(asistente, "resumir", lambda turnos, numero, inicio: dict(RESUMEN))
    with TestClient(main.app) as c:
        yield c


def _auth(clave="secreta"):
    token = base64.b64encode(f"admin:{clave}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _llamar(cliente, ruta, **datos):
    datos.setdefault("CallSid", "CA123")
    datos.setdefault("From", "+34600111222")
    return cliente.post(ruta, data=datos)


def test_llamada_completa_queda_resumida_en_el_panel(cliente, monkeypatch):
    respuestas = iter(
        [
            Respuesta("¿Me dice su nombre, por favor?", False),
            Respuesta("Apuntado, Luis. Antonio le llamará. Hasta luego.", True),
        ]
    )
    monkeypatch.setattr(asistente, "responder", lambda turnos, numero: next(respuestas))

    r = _llamar(cliente, "/voz/entrante")
    assert r.status_code == 200
    assert "<Gather" in r.text and 'input="speech"' in r.text
    assert ajustes.nombre_negocio in r.text

    r = _llamar(cliente, "/voz/turno", SpeechResult="Quería un presupuesto para una barandilla")
    assert "¿Me dice su nombre" in r.text and "<Gather" in r.text

    r = _llamar(cliente, "/voz/turno", SpeechResult="Luis")
    assert "<Hangup" in r.text

    llamada = db.obtener("CA123")
    assert llamada["estado"] == "lista"
    assert llamada["resumen"]["titulo"] == RESUMEN["titulo"]
    assert [t["quien"] for t in llamada["turnos"]] == [
        "asistente", "cliente", "asistente", "cliente", "asistente"
    ]

    # El aviso de fin de llamada de Twilio no vuelve a resumir.
    monkeypatch.setattr(asistente, "resumir", lambda *a: pytest.fail("resumida dos veces"))
    assert _llamar(cliente, "/voz/estado", CallStatus="completed").status_code == 204

    panel = cliente.get("/", headers=_auth())
    assert panel.status_code == 200
    assert RESUMEN["titulo"] in panel.text
    assert 'href="tel:+34600111222"' in panel.text
    assert "https://wa.me/34600111222" in panel.text


def test_si_cuelga_a_mitad_se_resume_igual(cliente, monkeypatch):
    monkeypatch.setattr(asistente, "responder", lambda t, n: Respuesta("¿Para cuándo lo necesita?", False))
    _llamar(cliente, "/voz/entrante")
    _llamar(cliente, "/voz/turno", SpeechResult="Se me ha roto el motor de la puerta del garaje")
    assert db.obtener("CA123")["estado"] == "en_curso"

    _llamar(cliente, "/voz/estado", CallStatus="completed")
    assert db.obtener("CA123")["resumen"]["titulo"] == RESUMEN["titulo"]


def test_cuelga_sin_hablar(cliente, monkeypatch):
    monkeypatch.setattr(asistente, "resumir", lambda *a: pytest.fail("no hay nada que resumir"))
    _llamar(cliente, "/voz/entrante")
    _llamar(cliente, "/voz/estado", CallStatus="completed")
    assert db.obtener("CA123")["resumen"]["titulo"] == "Colgó sin dejar recado"


def test_silencios(cliente):
    _llamar(cliente, "/voz/entrante")
    r = _llamar(cliente, "/voz/turno", SpeechResult="")
    assert "¿Sigue ahí?" in r.text and "<Gather" in r.text
    r = _llamar(cliente, "/voz/turno", SpeechResult="")
    assert "<Hangup" in r.text


def test_si_falla_claude_cuelga_con_educacion_y_guarda_el_recado(cliente, monkeypatch):
    def falla(turnos, numero):
        raise TimeoutError("sin respuesta")

    monkeypatch.setattr(asistente, "responder", falla)
    _llamar(cliente, "/voz/entrante")
    r = _llamar(cliente, "/voz/turno", SpeechResult="Soy Pepe, llámame")
    assert "problema técnico" in r.text and "<Hangup" in r.text
    assert db.obtener("CA123")["estado"] == "lista"


def test_si_falla_el_resumen_queda_la_conversacion(cliente, monkeypatch):
    def falla(*a):
        raise RuntimeError("caído")

    monkeypatch.setattr(asistente, "resumir", falla)
    monkeypatch.setattr(asistente, "responder", lambda t, n: Respuesta("Hasta luego.", True))
    _llamar(cliente, "/voz/entrante")
    _llamar(cliente, "/voz/turno", SpeechResult="Soy Pepe")
    llamada = db.obtener("CA123")
    assert llamada["estado"] == "error"
    assert "sin resumir" in llamada["resumen"]["titulo"]


def test_panel_pide_contrasena(cliente):
    assert cliente.get("/").status_code == 401
    assert cliente.get("/", headers=_auth("mala")).status_code == 401


def test_marcar_hecha(cliente):
    _llamar(cliente, "/voz/entrante")
    _llamar(cliente, "/voz/estado", CallStatus="completed")
    r = cliente.post("/llamada/CA123/hecha", headers=_auth(), follow_redirects=False)
    assert r.status_code == 303
    assert db.obtener("CA123")["hecha"] is True


def test_urgentes_primero_en_el_panel(cliente, monkeypatch):
    for sid, urgencia, titulo in [("CA1", "alta", "Avería urgente"), ("CA2", "baja", "Recado normal")]:
        monkeypatch.setattr(
            asistente, "resumir", lambda *a, u=urgencia, t=titulo: {**RESUMEN, "urgencia": u, "titulo": t}
        )
        _llamar(cliente, "/voz/entrante", CallSid=sid)
        _llamar(cliente, "/voz/turno", CallSid=sid, SpeechResult="Hola")
        _llamar(cliente, "/voz/estado", CallSid=sid, CallStatus="completed")
    panel = cliente.get("/", headers=_auth()).text
    assert panel.index("Avería urgente") < panel.index("Recado normal")


def test_rechaza_peticiones_sin_firma_de_twilio(cliente, monkeypatch):
    monkeypatch.setattr(ajustes, "twilio_auth_token", "token-de-prueba")
    monkeypatch.setattr(ajustes, "url_publica", "https://recados.ejemplo.es")
    datos = {"CallSid": "CA999", "From": "+34600111222"}

    assert cliente.post("/voz/entrante", data=datos).status_code == 403

    firma = RequestValidator("token-de-prueba").compute_signature(
        "https://recados.ejemplo.es/voz/entrante", datos
    )
    r = cliente.post("/voz/entrante", data=datos, headers={"X-Twilio-Signature": firma})
    assert r.status_code == 200


def test_construir_mensajes_empieza_por_el_cliente_y_alterna():
    turnos = [
        {"quien": "asistente", "texto": "Hola, dígame"},
        {"quien": "cliente", "texto": "Hola"},
        {"quien": "cliente", "texto": "quería un presupuesto"},
        {"quien": "asistente", "texto": "¿De qué?"},
        {"quien": "cliente", "texto": "Una reja"},
    ]
    mensajes = _construir_mensajes(turnos)
    assert [m["role"] for m in mensajes] == ["user", "assistant", "user"]
    assert mensajes[0]["content"] == "Hola\nquería un presupuesto"
    assert '"texto": "¿De qué?"' in mensajes[1]["content"]


def test_info_negocio_quita_comentarios(tmp_path, monkeypatch):
    archivo = tmp_path / "negocio.md"
    archivo.write_text("<!-- nota para mí -->\nHacemos rejas.", encoding="utf-8")
    monkeypatch.setattr(ajustes, "archivo_negocio", archivo)
    assert ajustes.info_negocio() == "Hacemos rejas."
