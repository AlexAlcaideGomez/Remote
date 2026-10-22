"""Configuración: se lee de variables de entorno (o del archivo .env)."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent

load_dotenv(RAIZ / ".env")


def _bool(nombre: str, por_defecto: bool = False) -> bool:
    valor = os.getenv(nombre)
    if valor is None or valor.strip() == "":
        return por_defecto
    return valor.strip().lower() in ("1", "si", "sí", "true", "yes", "on")


def _int(nombre: str, por_defecto: int) -> int:
    valor = os.getenv(nombre, "").strip()
    return int(valor) if valor else por_defecto


@dataclass
class Ajustes:
    # Negocio
    nombre_negocio: str = field(default_factory=lambda: os.getenv("NOMBRE_NEGOCIO", "Carpintería Metálica"))
    nombre_dueno: str = field(default_factory=lambda: os.getenv("NOMBRE_DUENO", "el encargado"))
    archivo_negocio: Path = field(
        default_factory=lambda: Path(os.getenv("ARCHIVO_NEGOCIO", str(RAIZ / "negocio.md")))
    )
    saludo: str = field(default_factory=lambda: os.getenv("SALUDO", ""))
    zona_horaria: str = field(default_factory=lambda: os.getenv("ZONA_HORARIA", "Europe/Madrid"))

    # Claude
    modelo: str = field(default_factory=lambda: os.getenv("MODELO_CLAUDE", "claude-opus-5-5"))
    esfuerzo_conversacion: str = field(default_factory=lambda: os.getenv("ESFUERZO_CONVERSACION", "low"))
    esfuerzo_resumen: str = field(default_factory=lambda: os.getenv("ESFUERZO_RESUMEN", "medium"))

    # Teléfono (Twilio)
    twilio_auth_token: str = field(default_factory=lambda: os.getenv("TWILIO_AUTH_TOKEN", ""))
    url_publica: str = field(default_factory=lambda: os.getenv("URL_PUBLICA", "").rstrip("/"))
    voz: str = field(default_factory=lambda: os.getenv("VOZ", "Polly.Lucia-Neural"))
    idioma: str = field(default_factory=lambda: os.getenv("IDIOMA", "es-ES"))
    max_turnos: int = field(default_factory=lambda: _int("MAX_TURNOS", 14))

    # Panel web
    panel_usuario: str = field(default_factory=lambda: os.getenv("PANEL_USUARIO", "admin"))
    panel_contrasena: str = field(default_factory=lambda: os.getenv("PANEL_CONTRASENA", ""))

    # Avisos por Telegram (opcional)
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    avisar_solo_urgentes: bool = field(default_factory=lambda: _bool("AVISAR_SOLO_URGENTES"))

    # Datos
    ruta_bd: Path = field(default_factory=lambda: Path(os.getenv("RUTA_BD", str(RAIZ / "datos" / "llamadas.db"))))

    @property
    def texto_saludo(self) -> str:
        if self.saludo:
            return self.saludo
        return (
            f"Hola, ha llamado a {self.nombre_negocio}. Le atiende el asistente automático de "
            f"{self.nombre_dueno}, que ahora está trabajando y no puede ponerse. "
            "Cuénteme qué necesita y se lo apunto."
        )

    def info_negocio(self) -> str:
        try:
            texto = self.archivo_negocio.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
        # Los comentarios <!-- ... --> son instrucciones para quien edita el archivo, no para el asistente.
        return re.sub(r"<!--.*?-->", "", texto, flags=re.DOTALL).strip()


ajustes = Ajustes()
