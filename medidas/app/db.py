"""Base de datos SQLite: usuarios, trabajos (tomas de medidas) y sus fotos."""

import hashlib
import hmac
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import ajustes

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id        INTEGER PRIMARY KEY,
    usuario   TEXT NOT NULL UNIQUE,
    nombre    TEXT NOT NULL,
    hash      TEXT NOT NULL,
    es_admin  INTEGER NOT NULL DEFAULT 0,
    activo    INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS trabajos (
    id              TEXT PRIMARY KEY,   -- lo genera el móvil, para poder guardar sin cobertura
    titulo          TEXT NOT NULL,
    notas           TEXT NOT NULL DEFAULT '',
    autor_id        INTEGER NOT NULL REFERENCES usuarios(id),
    creado_en       TEXT NOT NULL,
    actualizado_en  TEXT NOT NULL,
    terminado       INTEGER NOT NULL DEFAULT 0,
    borrado         INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fotos (
    id          TEXT PRIMARY KEY,
    trabajo_id  TEXT NOT NULL REFERENCES trabajos(id),
    autor_id    INTEGER NOT NULL REFERENCES usuarios(id),
    creado_en   TEXT NOT NULL,
    borrada     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_fotos_trabajo ON fotos (trabajo_id);
"""


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def conexion():
    ajustes.ruta_datos.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ajustes.ruta_bd, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def iniciar() -> None:
    with conexion() as con:
        con.executescript(ESQUEMA)
        hay_usuarios = con.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone()
    if not hay_usuarios and ajustes.admin_usuario and ajustes.admin_contrasena:
        crear_usuario(
            ajustes.admin_usuario,
            ajustes.admin_nombre or ajustes.admin_usuario,
            ajustes.admin_contrasena,
            es_admin=True,
        )


# --------------------------------------------------------------------------- Usuarios


def hash_contrasena(contrasena: str) -> str:
    sal = os.urandom(16)
    h = hashlib.scrypt(contrasena.encode(), salt=sal, n=2**14, r=8, p=1)
    return f"scrypt${sal.hex()}${h.hex()}"


def _contrasena_ok(contrasena: str, guardado: str) -> bool:
    _, sal, h = guardado.split("$")
    calculado = hashlib.scrypt(contrasena.encode(), salt=bytes.fromhex(sal), n=2**14, r=8, p=1)
    return hmac.compare_digest(calculado.hex(), h)


def _usuario_publico(fila: sqlite3.Row | None) -> dict | None:
    if fila is None:
        return None
    return {
        "id": fila["id"],
        "usuario": fila["usuario"],
        "nombre": fila["nombre"],
        "es_admin": bool(fila["es_admin"]),
    }


def crear_usuario(usuario: str, nombre: str, contrasena: str, es_admin: bool = False) -> dict:
    with conexion() as con:
        cur = con.execute(
            "INSERT INTO usuarios (usuario, nombre, hash, es_admin) VALUES (?, ?, ?, ?)",
            (usuario.strip().lower(), nombre.strip(), hash_contrasena(contrasena), int(es_admin)),
        )
        fila = con.execute("SELECT * FROM usuarios WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _usuario_publico(fila)


def comprobar_usuario(usuario: str, contrasena: str) -> dict | None:
    with conexion() as con:
        fila = con.execute(
            "SELECT * FROM usuarios WHERE usuario = ? AND activo = 1", (usuario.strip().lower(),)
        ).fetchone()
    if fila is None or not _contrasena_ok(contrasena, fila["hash"]):
        return None
    return _usuario_publico(fila)


def obtener_usuario(usuario_id: int) -> dict | None:
    with conexion() as con:
        fila = con.execute(
            "SELECT * FROM usuarios WHERE id = ? AND activo = 1", (usuario_id,)
        ).fetchone()
    return _usuario_publico(fila)


def listar_usuarios() -> list[dict]:
    with conexion() as con:
        filas = con.execute("SELECT * FROM usuarios WHERE activo = 1 ORDER BY nombre").fetchall()
    return [_usuario_publico(f) for f in filas]


def cambiar_contrasena(usuario_id: int, contrasena: str) -> None:
    with conexion() as con:
        con.execute("UPDATE usuarios SET hash = ? WHERE id = ?", (hash_contrasena(contrasena), usuario_id))


def dar_de_baja(usuario_id: int) -> None:
    """No se borra para que sus trabajos sigan diciendo quién tomó las medidas."""
    with conexion() as con:
        con.execute(
            "UPDATE usuarios SET activo = 0, usuario = usuario || '#baja' || id WHERE id = ?",
            (usuario_id,),
        )


# --------------------------------------------------------------------------- Trabajos


def obtener_trabajo(trabajo_id: str) -> dict | None:
    with conexion() as con:
        fila = con.execute(
            "SELECT * FROM trabajos WHERE id = ? AND borrado = 0", (trabajo_id,)
        ).fetchone()
    return dict(fila) if fila else None


def guardar_trabajo(trabajo_id: str, titulo: str, notas: str, creado_en: str, autor_id: int) -> None:
    """Crea el trabajo o, si ya existe, actualiza el texto. Repetirlo no duplica nada."""
    with conexion() as con:
        con.execute(
            "INSERT INTO trabajos (id, titulo, notas, autor_id, creado_en, actualizado_en) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET titulo = excluded.titulo, notas = excluded.notas, "
            "actualizado_en = excluded.actualizado_en",
            (trabajo_id, titulo, notas, autor_id, creado_en, ahora()),
        )


def marcar_terminado(trabajo_id: str, terminado: bool) -> None:
    with conexion() as con:
        con.execute(
            "UPDATE trabajos SET terminado = ?, actualizado_en = ? WHERE id = ?",
            (int(terminado), ahora(), trabajo_id),
        )


def borrar_trabajo(trabajo_id: str) -> None:
    """Se marca como borrado; las fotos se quedan en el disco por si acaso."""
    with conexion() as con:
        con.execute("UPDATE trabajos SET borrado = 1, actualizado_en = ? WHERE id = ?", (ahora(), trabajo_id))


def listar_trabajos() -> list[dict]:
    with conexion() as con:
        trabajos = con.execute(
            "SELECT t.*, u.nombre AS autor FROM trabajos t JOIN usuarios u ON u.id = t.autor_id "
            "WHERE t.borrado = 0 ORDER BY t.creado_en DESC"
        ).fetchall()
        fotos = con.execute(
            "SELECT id, trabajo_id FROM fotos WHERE borrada = 0 ORDER BY creado_en"
        ).fetchall()
    por_trabajo: dict[str, list[str]] = {}
    for f in fotos:
        por_trabajo.setdefault(f["trabajo_id"], []).append(f["id"])
    return [
        {
            "id": t["id"],
            "titulo": t["titulo"],
            "notas": t["notas"],
            "autor": t["autor"],
            "autor_id": t["autor_id"],
            "creado_en": t["creado_en"],
            "terminado": bool(t["terminado"]),
            "fotos": por_trabajo.get(t["id"], []),
        }
        for t in trabajos
    ]


# --------------------------------------------------------------------------- Fotos


def obtener_foto(foto_id: str) -> dict | None:
    with conexion() as con:
        fila = con.execute(
            "SELECT f.* FROM fotos f JOIN trabajos t ON t.id = f.trabajo_id "
            "WHERE f.id = ? AND f.borrada = 0 AND t.borrado = 0",
            (foto_id,),
        ).fetchone()
    return dict(fila) if fila else None


def foto_existe(foto_id: str) -> bool:
    with conexion() as con:
        return con.execute("SELECT 1 FROM fotos WHERE id = ?", (foto_id,)).fetchone() is not None


def guardar_foto(foto_id: str, trabajo_id: str, autor_id: int) -> None:
    with conexion() as con:
        con.execute(
            "INSERT OR IGNORE INTO fotos (id, trabajo_id, autor_id, creado_en) VALUES (?, ?, ?, ?)",
            (foto_id, trabajo_id, autor_id, ahora()),
        )


def borrar_foto(foto_id: str) -> None:
    with conexion() as con:
        con.execute("UPDATE fotos SET borrada = 1 WHERE id = ?", (foto_id,))
