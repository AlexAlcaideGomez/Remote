"""Configuración: se lee de variables de entorno (o del archivo .env)."""

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent

load_dotenv(RAIZ / ".env")


def _bool(nombre: str, por_defecto: bool) -> bool:
    valor = os.getenv(nombre, "").strip().lower()
    if not valor:
        return por_defecto
    return valor in ("1", "si", "sí", "true", "yes", "on")


@dataclass
class Ajustes:
    nombre_negocio: str = field(default_factory=lambda: os.getenv("NOMBRE_NEGOCIO", "Carpintería Metálica"))
    admin_usuario: str = field(default_factory=lambda: os.getenv("ADMIN_USUARIO", "").strip().lower())
    admin_nombre: str = field(default_factory=lambda: os.getenv("ADMIN_NOMBRE", "").strip())
    admin_contrasena: str = field(default_factory=lambda: os.getenv("ADMIN_CONTRASENA", ""))
    cookie_segura: bool = field(default_factory=lambda: _bool("COOKIE_SEGURA", True))
    ruta_datos: Path = field(default_factory=lambda: Path(os.getenv("RUTA_DATOS", str(RAIZ / "datos"))))

    @property
    def ruta_bd(self) -> Path:
        return self.ruta_datos / "medidas.db"

    @property
    def ruta_fotos(self) -> Path:
        return self.ruta_datos / "fotos"

    def clave_sesiones(self) -> str:
        """Clave para firmar las sesiones. Se genera una vez y se guarda junto a los datos."""
        archivo = self.ruta_datos / "clave_sesiones"
        if not archivo.exists():
            self.ruta_datos.mkdir(parents=True, exist_ok=True)
            archivo.write_text(secrets.token_hex(32))
        return archivo.read_text().strip()


ajustes = Ajustes()
