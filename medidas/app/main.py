"""Servidor de la app de medidas: API para el móvil, fotos y la propia app."""

import io
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from . import db
from .config import RAIZ, ajustes

ESTATICOS = RAIZ / "static"
MAX_FOTO_BYTES = 25 * 1024 * 1024
LADO_MAX_FOTO = 2400
LADO_MINIATURA = 400
# Los identificadores los genera el móvil; solo se aceptan letras, números y guiones.
ID_VALIDO = re.compile(r"^[A-Za-z0-9-]{8,64}$")


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    db.iniciar()
    yield


app = FastAPI(title="Medidas", lifespan=ciclo_de_vida)
app.add_middleware(
    SessionMiddleware,
    secret_key=ajustes.clave_sesiones(),
    session_cookie="medidas_sesion",
    max_age=365 * 24 * 3600,  # que no haya que volver a entrar cada dos por tres
    same_site="lax",
    https_only=ajustes.cookie_segura,
)


# --------------------------------------------------------------------------- Sesión


def usuario_actual(request: Request) -> dict:
    usuario_id = request.session.get("usuario_id")
    usuario = db.obtener_usuario(usuario_id) if usuario_id else None
    if usuario is None:
        request.session.clear()
        raise HTTPException(401, "Tienes que entrar con tu usuario")
    return usuario


def admin_actual(usuario: dict = Depends(usuario_actual)) -> dict:
    if not usuario["es_admin"]:
        raise HTTPException(403, "Solo el administrador puede hacer esto")
    return usuario


def _validar_id(valor: str) -> str:
    if not ID_VALIDO.match(valor):
        raise HTTPException(400, "Identificador no válido")
    return valor


class Entrada(BaseModel):
    usuario: str
    contrasena: str


@app.post("/api/entrar")
def entrar(datos: Entrada, request: Request):
    usuario = db.comprobar_usuario(datos.usuario, datos.contrasena)
    if usuario is None:
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    request.session["usuario_id"] = usuario["id"]
    return usuario


@app.post("/api/salir")
def salir(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/yo")
def yo(usuario: dict = Depends(usuario_actual)):
    return {**usuario, "negocio": ajustes.nombre_negocio}


# --------------------------------------------------------------------------- Trabajos


class DatosTrabajo(BaseModel):
    titulo: str = Field(min_length=1, max_length=300)
    notas: str = Field(default="", max_length=5000)
    creado_en: str = Field(min_length=10, max_length=40)


class DatosTerminado(BaseModel):
    terminado: bool


def _trabajo_o_404(trabajo_id: str) -> dict:
    trabajo = db.obtener_trabajo(_validar_id(trabajo_id))
    if trabajo is None:
        raise HTTPException(404, "No existe ese trabajo")
    return trabajo


def _puede_borrar(usuario: dict, autor_id: int) -> None:
    if not (usuario["es_admin"] or usuario["id"] == autor_id):
        raise HTTPException(403, "Solo quien lo creó o el administrador puede borrarlo")


@app.get("/api/trabajos")
def listar_trabajos(_usuario: dict = Depends(usuario_actual)):
    return db.listar_trabajos()


@app.put("/api/trabajos/{trabajo_id}")
def guardar_trabajo(trabajo_id: str, datos: DatosTrabajo, usuario: dict = Depends(usuario_actual)):
    db.guardar_trabajo(
        _validar_id(trabajo_id), datos.titulo.strip(), datos.notas.strip(), datos.creado_en, usuario["id"]
    )
    return {"ok": True}


@app.post("/api/trabajos/{trabajo_id}/terminado")
def marcar_terminado(trabajo_id: str, datos: DatosTerminado, _usuario: dict = Depends(usuario_actual)):
    _trabajo_o_404(trabajo_id)
    db.marcar_terminado(trabajo_id, datos.terminado)
    return {"ok": True}


@app.delete("/api/trabajos/{trabajo_id}")
def borrar_trabajo(trabajo_id: str, usuario: dict = Depends(usuario_actual)):
    trabajo = _trabajo_o_404(trabajo_id)
    _puede_borrar(usuario, trabajo["autor_id"])
    db.borrar_trabajo(trabajo_id)
    return {"ok": True}


# --------------------------------------------------------------------------- Fotos


def _rutas_foto(foto_id: str):
    carpeta = ajustes.ruta_fotos / foto_id[:2]
    return carpeta, carpeta / f"{foto_id}.jpg", carpeta / f"{foto_id}_min.jpg"


def _guardar_imagen(contenido: bytes, foto_id: str) -> None:
    try:
        imagen = Image.open(io.BytesIO(contenido))
        imagen = ImageOps.exif_transpose(imagen).convert("RGB")  # gira según el móvil y quita metadatos
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise HTTPException(400, "El archivo no es una foto válida")
    carpeta, ruta, ruta_min = _rutas_foto(foto_id)
    carpeta.mkdir(parents=True, exist_ok=True)
    imagen.thumbnail((LADO_MAX_FOTO, LADO_MAX_FOTO))
    imagen.save(ruta, "JPEG", quality=88)
    imagen.thumbnail((LADO_MINIATURA, LADO_MINIATURA))
    imagen.save(ruta_min, "JPEG", quality=80)


@app.put("/api/trabajos/{trabajo_id}/fotos/{foto_id}")
async def subir_foto(
    trabajo_id: str, foto_id: str, foto: UploadFile, usuario: dict = Depends(usuario_actual)
):
    _trabajo_o_404(trabajo_id)
    _validar_id(foto_id)
    if db.foto_existe(foto_id):  # el móvil la reintenta si se cortó la conexión
        return {"ok": True}
    contenido = await foto.read(MAX_FOTO_BYTES + 1)
    if len(contenido) > MAX_FOTO_BYTES:
        raise HTTPException(413, "La foto es demasiado grande")
    _guardar_imagen(contenido, foto_id)
    db.guardar_foto(foto_id, trabajo_id, usuario["id"])
    return {"ok": True}


@app.delete("/api/trabajos/{trabajo_id}/fotos/{foto_id}")
def borrar_foto(trabajo_id: str, foto_id: str, usuario: dict = Depends(usuario_actual)):
    foto = db.obtener_foto(_validar_id(foto_id))
    if foto is None or foto["trabajo_id"] != trabajo_id:
        raise HTTPException(404, "No existe esa foto")
    _puede_borrar(usuario, foto["autor_id"])
    db.borrar_foto(foto_id)
    return {"ok": True}


@app.get("/fotos/{nombre}")
def ver_foto(nombre: str, _usuario: dict = Depends(usuario_actual)):
    miniatura = nombre.endswith("_min.jpg")
    foto_id = _validar_id(nombre.removesuffix(".jpg").removesuffix("_min"))
    if db.obtener_foto(foto_id) is None:
        raise HTTPException(404, "No existe esa foto")
    _, ruta, ruta_min = _rutas_foto(foto_id)
    return FileResponse(
        ruta_min if miniatura else ruta,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


# --------------------------------------------------------------------------- Usuarios


class NuevoUsuario(BaseModel):
    usuario: str = Field(pattern=r"^[A-Za-z0-9._-]{2,40}$")
    nombre: str = Field(min_length=1, max_length=80)
    contrasena: str = Field(min_length=6, max_length=200)
    es_admin: bool = False


class NuevaContrasena(BaseModel):
    contrasena: str = Field(min_length=6, max_length=200)


@app.get("/api/usuarios")
def listar_usuarios(_admin: dict = Depends(admin_actual)):
    return db.listar_usuarios()


@app.post("/api/usuarios")
def crear_usuario(datos: NuevoUsuario, _admin: dict = Depends(admin_actual)):
    if any(u["usuario"] == datos.usuario.lower() for u in db.listar_usuarios()):
        raise HTTPException(409, "Ya existe un usuario con ese nombre")
    return db.crear_usuario(datos.usuario, datos.nombre, datos.contrasena, datos.es_admin)


@app.post("/api/usuarios/{usuario_id}/contrasena")
def cambiar_contrasena(usuario_id: int, datos: NuevaContrasena, usuario: dict = Depends(usuario_actual)):
    if not (usuario["es_admin"] or usuario["id"] == usuario_id):
        raise HTTPException(403, "Solo puedes cambiar tu propia contraseña")
    if db.obtener_usuario(usuario_id) is None:
        raise HTTPException(404, "No existe ese usuario")
    db.cambiar_contrasena(usuario_id, datos.contrasena)
    return {"ok": True}


@app.delete("/api/usuarios/{usuario_id}")
def dar_de_baja(usuario_id: int, admin: dict = Depends(admin_actual)):
    if usuario_id == admin["id"]:
        raise HTTPException(400, "No te puedes dar de baja a ti mismo")
    db.dar_de_baja(usuario_id)
    return {"ok": True}


# --------------------------------------------------------------------------- La app


@app.get("/sw.js")
def service_worker():
    # Tiene que servirse desde la raíz para poder funcionar sin conexión en toda la app.
    return FileResponse(
        ESTATICOS / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"}
    )


@app.get("/salud")
def salud():
    return {"ok": True}


app.mount("/", StaticFiles(directory=ESTATICOS, html=True), name="app")
