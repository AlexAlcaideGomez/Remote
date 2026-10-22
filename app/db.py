"""Base de datos SQLite con las llamadas, lo que se habló y su resumen."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import ajustes

ESQUEMA = """
CREATE TABLE IF NOT EXISTS llamadas (
    call_sid   TEXT PRIMARY KEY,
    numero     TEXT,
    inicio     TEXT NOT NULL,
    fin        TEXT,
    estado     TEXT NOT NULL DEFAULT 'en_curso',  -- en_curso | resumiendo | lista | error
    turnos     TEXT NOT NULL DEFAULT '[]',
    silencios  INTEGER NOT NULL DEFAULT 0,
    resumen    TEXT,
    hecha      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_llamadas_inicio ON llamadas (inicio);
"""


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _conexion():
    ajustes.ruta_bd.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ajustes.ruta_bd, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def iniciar() -> None:
    with _conexion() as con:
        con.executescript(ESQUEMA)


def _a_dict(fila: sqlite3.Row | None) -> dict | None:
    if fila is None:
        return None
    d = dict(fila)
    d["turnos"] = json.loads(d["turnos"])
    d["resumen"] = json.loads(d["resumen"]) if d["resumen"] else None
    d["hecha"] = bool(d["hecha"])
    return d


def crear_llamada(call_sid: str, numero: str | None) -> None:
    with _conexion() as con:
        con.execute(
            "INSERT OR IGNORE INTO llamadas (call_sid, numero, inicio) VALUES (?, ?, ?)",
            (call_sid, numero, _ahora()),
        )


def obtener(call_sid: str) -> dict | None:
    with _conexion() as con:
        fila = con.execute("SELECT * FROM llamadas WHERE call_sid = ?", (call_sid,)).fetchone()
    return _a_dict(fila)


def anadir_turno(call_sid: str, quien: str, texto: str) -> list[dict]:
    """Añade una intervención ('cliente' o 'asistente') y devuelve la conversación completa."""
    with _conexion() as con:
        fila = con.execute("SELECT turnos FROM llamadas WHERE call_sid = ?", (call_sid,)).fetchone()
        turnos = json.loads(fila["turnos"]) if fila else []
        turnos.append({"quien": quien, "texto": texto})
        con.execute(
            "UPDATE llamadas SET turnos = ? WHERE call_sid = ?",
            (json.dumps(turnos, ensure_ascii=False), call_sid),
        )
    return turnos


def sumar_silencio(call_sid: str) -> int:
    with _conexion() as con:
        con.execute("UPDATE llamadas SET silencios = silencios + 1 WHERE call_sid = ?", (call_sid,))
        fila = con.execute("SELECT silencios FROM llamadas WHERE call_sid = ?", (call_sid,)).fetchone()
    return fila["silencios"] if fila else 0


def reiniciar_silencios(call_sid: str) -> None:
    with _conexion() as con:
        con.execute("UPDATE llamadas SET silencios = 0 WHERE call_sid = ?", (call_sid,))


def reclamar_para_resumen(call_sid: str) -> bool:
    """Marca la llamada como terminada. Devuelve True solo la primera vez, para no resumirla dos veces."""
    with _conexion() as con:
        cur = con.execute(
            "UPDATE llamadas SET estado = 'resumiendo', fin = COALESCE(fin, ?) "
            "WHERE call_sid = ? AND estado = 'en_curso'",
            (_ahora(), call_sid),
        )
    return cur.rowcount == 1


def guardar_resumen(call_sid: str, resumen: dict, estado: str = "lista") -> None:
    with _conexion() as con:
        con.execute(
            "UPDATE llamadas SET resumen = ?, estado = ? WHERE call_sid = ?",
            (json.dumps(resumen, ensure_ascii=False), estado, call_sid),
        )


def marcar_hecha(call_sid: str, hecha: bool) -> None:
    with _conexion() as con:
        con.execute("UPDATE llamadas SET hecha = ? WHERE call_sid = ?", (int(hecha), call_sid))


def listar(hecha: bool, limite: int = 100) -> list[dict]:
    with _conexion() as con:
        filas = con.execute(
            "SELECT * FROM llamadas WHERE hecha = ? ORDER BY inicio DESC LIMIT ?",
            (int(hecha), limite),
        ).fetchall()
    return [_a_dict(f) for f in filas]
