import io
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import db, main
from app.config import ajustes


@pytest.fixture
def servidor(tmp_path, monkeypatch):
    monkeypatch.setattr(ajustes, "ruta_datos", tmp_path)
    monkeypatch.setattr(ajustes, "admin_usuario", "antonio")
    monkeypatch.setattr(ajustes, "admin_nombre", "Antonio")
    monkeypatch.setattr(ajustes, "admin_contrasena", "clave-admin")
    with TestClient(main.app, base_url="https://testserver") as c:
        yield c


def _entrar(cliente, usuario="antonio", contrasena="clave-admin"):
    r = cliente.post("/api/entrar", json={"usuario": usuario, "contrasena": contrasena})
    assert r.status_code == 200, r.text
    return r.json()


def _nuevo_cliente():
    return TestClient(main.app, base_url="https://testserver")


def _foto(ancho=3000, alto=2000) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (ancho, alto), "white").save(buffer, "JPEG")
    return buffer.getvalue()


def _crear_trabajo(cliente, titulo="Juan Pérez, C/ Mayor 3, puerta garaje"):
    trabajo_id = str(uuid.uuid4())
    r = cliente.put(
        f"/api/trabajos/{trabajo_id}",
        json={"titulo": titulo, "notas": "", "creado_en": "2026-10-22T09:00:00.000Z"},
    )
    assert r.status_code == 200, r.text
    return trabajo_id


def _subir_foto(cliente, trabajo_id, foto_id=None, contenido=None):
    foto_id = foto_id or str(uuid.uuid4())
    r = cliente.put(
        f"/api/trabajos/{trabajo_id}/fotos/{foto_id}",
        files={"foto": ("foto.jpg", contenido or _foto(), "image/jpeg")},
    )
    return foto_id, r


def test_sin_entrar_no_se_ve_nada(servidor):
    assert servidor.get("/api/trabajos").status_code == 401
    assert servidor.get("/api/yo").status_code == 401
    # La app en sí sí se carga, para poder mostrar la pantalla de entrar.
    assert servidor.get("/").status_code == 200
    assert servidor.get("/sw.js").status_code == 200


def test_contrasena_incorrecta(servidor):
    r = servidor.post("/api/entrar", json={"usuario": "antonio", "contrasena": "mala"})
    assert r.status_code == 401


def test_toma_de_medidas_completa(servidor):
    _entrar(servidor)
    trabajo_id = _crear_trabajo(servidor)
    foto_id, r = _subir_foto(servidor, trabajo_id)
    assert r.status_code == 200

    lista = servidor.get("/api/trabajos").json()
    assert len(lista) == 1
    assert lista[0]["titulo"] == "Juan Pérez, C/ Mayor 3, puerta garaje"
    assert lista[0]["autor"] == "Antonio"
    assert lista[0]["fotos"] == [foto_id]

    grande = servidor.get(f"/fotos/{foto_id}.jpg")
    miniatura = servidor.get(f"/fotos/{foto_id}_min.jpg")
    assert grande.status_code == miniatura.status_code == 200
    assert max(Image.open(io.BytesIO(grande.content)).size) == main.LADO_MAX_FOTO
    assert max(Image.open(io.BytesIO(miniatura.content)).size) == main.LADO_MINIATURA


def test_reintentos_del_movil_no_duplican(servidor):
    """Si se corta la conexión a mitad, el móvil repite el envío con los mismos identificadores."""
    _entrar(servidor)
    trabajo_id = _crear_trabajo(servidor)
    _crear_trabajo_otra_vez = servidor.put(
        f"/api/trabajos/{trabajo_id}",
        json={"titulo": "Juan Pérez, C/ Mayor 3, puerta garaje", "notas": "", "creado_en": "2026-10-22T09:00:00.000Z"},
    )
    assert _crear_trabajo_otra_vez.status_code == 200
    foto_id, _ = _subir_foto(servidor, trabajo_id)
    _, r = _subir_foto(servidor, trabajo_id, foto_id)
    assert r.status_code == 200
    lista = servidor.get("/api/trabajos").json()
    assert len(lista) == 1 and lista[0]["fotos"] == [foto_id]


def test_editar_terminar_y_borrar(servidor):
    _entrar(servidor)
    trabajo_id = _crear_trabajo(servidor)
    servidor.put(
        f"/api/trabajos/{trabajo_id}",
        json={"titulo": "Juan Pérez", "notas": "Llamar antes de ir", "creado_en": "2026-10-22T09:00:00.000Z"},
    )
    assert servidor.post(f"/api/trabajos/{trabajo_id}/terminado", json={"terminado": True}).status_code == 200
    t = servidor.get("/api/trabajos").json()[0]
    assert (t["titulo"], t["notas"], t["terminado"]) == ("Juan Pérez", "Llamar antes de ir", True)

    assert servidor.delete(f"/api/trabajos/{trabajo_id}").status_code == 200
    assert servidor.get("/api/trabajos").json() == []


def test_foto_no_valida(servidor):
    _entrar(servidor)
    trabajo_id = _crear_trabajo(servidor)
    _, r = _subir_foto(servidor, trabajo_id, contenido=b"esto no es una foto")
    assert r.status_code == 400


def test_identificadores_raros_rechazados(servidor):
    _entrar(servidor)
    datos = {"titulo": "x", "notas": "", "creado_en": "2026-10-22T09:00:00.000Z"}
    assert servidor.put("/api/trabajos/..%2F..%2Fetc", json=datos).status_code in (400, 404, 405)
    assert servidor.put("/api/trabajos/....medidas.db", json=datos).status_code == 400
    assert servidor.get("/fotos/....medidas.db").status_code == 400
    assert servidor.get("/fotos/..%2Fmedidas.db").status_code in (400, 404)


def test_usuarios_y_permisos(servidor):
    _entrar(servidor)
    r = servidor.post(
        "/api/usuarios", json={"usuario": "Pepe", "nombre": "Pepe", "contrasena": "clave-pepe"}
    )
    assert r.status_code == 200
    pepe_id = r.json()["id"]
    trabajo_admin = _crear_trabajo(servidor, "Trabajo de Antonio")
    assert servidor.post(
        "/api/usuarios", json={"usuario": "pepe", "nombre": "Otro", "contrasena": "123456"}
    ).status_code == 409

    with _nuevo_cliente() as pepe:
        _entrar(pepe, "pepe", "clave-pepe")
        # Ve todo lo del taller y puede añadir medidas y fotos
        assert len(pepe.get("/api/trabajos").json()) == 1
        _, r = _subir_foto(pepe, trabajo_admin)
        assert r.status_code == 200
        trabajo_pepe = _crear_trabajo(pepe, "Trabajo de Pepe")
        # Pero no borrar lo de otros ni gestionar usuarios
        assert pepe.delete(f"/api/trabajos/{trabajo_admin}").status_code == 403
        assert pepe.delete(f"/api/trabajos/{trabajo_pepe}").status_code == 200
        assert pepe.get("/api/usuarios").status_code == 403
        assert pepe.post(f"/api/usuarios/{pepe_id}/contrasena", json={"contrasena": "nueva-clave"}).status_code == 200
        assert pepe.post("/api/usuarios/1/contrasena", json={"contrasena": "nueva-clave"}).status_code == 403

        # Al darle de baja, su sesión deja de valer, pero lo que hizo se queda
        assert servidor.delete(f"/api/usuarios/{pepe_id}").status_code == 200
        assert pepe.get("/api/trabajos").status_code == 401
    assert servidor.get("/api/trabajos").json()[0]["titulo"] == "Trabajo de Antonio"
    # El nombre de usuario queda libre para otra persona
    assert servidor.post(
        "/api/usuarios", json={"usuario": "pepe", "nombre": "Pepe 2", "contrasena": "123456"}
    ).status_code == 200


def test_admin_no_se_puede_dar_de_baja_a_si_mismo(servidor):
    yo = _entrar(servidor)
    assert servidor.delete(f"/api/usuarios/{yo['id']}").status_code == 400


def test_contrasenas_guardadas_cifradas(servidor):
    with db.conexion() as con:
        guardado = con.execute("SELECT hash FROM usuarios WHERE usuario = 'antonio'").fetchone()["hash"]
    assert "clave-admin" not in guardado and guardado.startswith("scrypt$")
