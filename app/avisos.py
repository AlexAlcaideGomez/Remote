"""Aviso opcional al móvil por Telegram cuando llega un recado nuevo."""

import logging

import httpx

from .asistente import MOTIVOS
from .config import ajustes

log = logging.getLogger(__name__)

ICONO_URGENCIA = {"alta": "🔴", "media": "🟠", "baja": "🟢"}


def activos() -> bool:
    return bool(ajustes.telegram_token and ajustes.telegram_chat_id)


def texto_aviso(llamada: dict) -> str:
    r = llamada["resumen"] or {}
    quien = r.get("nombre") or "Sin nombre"
    if r.get("empresa"):
        quien += f" ({r['empresa']})"
    lineas = [
        f"{ICONO_URGENCIA.get(r.get('urgencia'), '⚪')} {r.get('titulo', 'Llamada nueva')}",
        f"👤 {quien}",
        f"📞 {r.get('telefono_contacto') or llamada['numero'] or 'número oculto'}",
        f"🏷️ {MOTIVOS.get(r.get('motivo'), 'Otro')}",
        "",
        r.get("resumen", ""),
    ]
    if r.get("que_hacer"):
        lineas += ["", f"👉 {r['que_hacer']}"]
    if r.get("cuando_llamar"):
        lineas.append(f"🕒 {r['cuando_llamar']}")
    if ajustes.url_publica:
        lineas += ["", f"{ajustes.url_publica}/llamada/{llamada['call_sid']}"]
    return "\n".join(lineas)


def enviar(llamada: dict) -> None:
    if not activos():
        return
    urgencia = (llamada["resumen"] or {}).get("urgencia")
    if ajustes.avisar_solo_urgentes and urgencia != "alta":
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{ajustes.telegram_token}/sendMessage",
            json={"chat_id": ajustes.telegram_chat_id, "text": texto_aviso(llamada)},
            timeout=10,
        ).raise_for_status()
    except httpx.HTTPError:
        log.exception("No se pudo enviar el aviso por Telegram")
