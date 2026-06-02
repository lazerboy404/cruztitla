from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
STATIC_DIR = BASE_DIR / "static"
STORAGE_DIR = BASE_DIR / "storage"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

TEMPLATE_PATH = Path(os.getenv("TEMPLATE_PATH", str(STATIC_DIR / "plantilla.png")))
FORMAT_TEMPLATE_PATH = Path(
    os.getenv("FORMAT_TEMPLATE_PATH", str(PROJECT_ROOT / "formato credencial.docx"))
)
APP_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "America/Mexico_City"))

TEAMS = [
    "Dvo. AMISTAD",
    "Atl\u00e9tico Cruztitla",
    "Real Tultitl\u00e1n",
    "Deportivo M\u00e9xico",
    "Uni\u00f3n Familiar",
    "Halcones FC",
]

CATEGORIES = [
    "Primera 'A' Dominical",
    "Primera 'B' Dominical",
    "Segunda Fuerza",
    "Veteranos",
    "Juvenil",
    "Femenil",
]


def ensure_directories() -> None:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
