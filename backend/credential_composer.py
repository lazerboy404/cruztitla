from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import APP_TIMEZONE, TEMPLATE_PATH
from text_utils import normalize_display_text


TEXT_COLOR = (14, 56, 36)

# Coordinates calibrated for plantilla.png at 1601x982.
PHOTO_BOX = (73, 484, 294, 330)  # x, y, width, height
TEXT_FIELDS = {
    "temporada_suffix": {"x": 1411, "line_y": 316, "width": 92, "max_size": 34},
    "nombre_completo": {"x": 742, "line_y": 416, "width": 760, "max_size": 38},
    "equipo": {"x": 747, "line_y": 501, "width": 755, "max_size": 38},
    "categoria": {"x": 758, "line_y": 583, "width": 745, "max_size": 36},
    "numero_jugador": {"x": 844, "line_y": 661, "width": 660, "max_size": 38},
    "fecha_nacimiento": {"x": 870, "line_y": 744, "width": 635, "max_size": 36},
    "lugar_fecha": {"x": 820, "line_y": 821, "width": 690, "max_size": 34},
}

SPANISH_MONTHS = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]
DEFAULT_CREDENTIAL_DATE = date(2026, 5, 29)
DEFAULT_SEASON_SUFFIX = "26"


def format_place_date(value: date | datetime | str | None = None) -> str:
    if value is None:
        selected = DEFAULT_CREDENTIAL_DATE
    elif isinstance(value, datetime):
        selected = value.date()
    elif isinstance(value, date):
        selected = value
    else:
        selected = datetime.strptime(value, "%Y-%m-%d").date()

    month = SPANISH_MONTHS[selected.month - 1]
    return f"Tultitl\u00e1n, M\u00e9x. {selected.day:02d} de {month} de {selected.year}"


def current_place_date() -> str:
    return format_place_date()


def current_credential_date_iso() -> str:
    return DEFAULT_CREDENTIAL_DATE.isoformat()


def current_place_date_parts() -> dict[str, int]:
    today = DEFAULT_CREDENTIAL_DATE
    return {"day": today.day, "month": today.month, "year": today.year}


def _font_candidates() -> list[Path]:
    win_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    return [
        win_fonts / "arialbd.ttf",
        win_fonts / "Arialbd.ttf",
        win_fonts / "segoeuib.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/local/share/fonts/DejaVuSans-Bold.ttf"),
    ]


def load_bold_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in _font_candidates():
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def fit_cover(image: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    target_w, target_h = target_size
    src_w, src_h = image.size
    scale = max(target_w / src_w, target_h / src_h)
    resized = image.resize((round(src_w * scale), round(src_h * scale)), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def paste_rounded(base: Image.Image, portrait: Image.Image, box: tuple[int, int, int, int]) -> None:
    x, y, w, h = box
    portrait = fit_cover(portrait.convert("RGB"), (w, h))
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, w, h), radius=24, fill=255)
    base.paste(portrait, (x, y), mask)


def draw_autofit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    field: dict[str, int],
    fill: tuple[int, int, int] = TEXT_COLOR,
) -> None:
    x = field["x"]
    line_y = field["line_y"]
    width = field["width"]
    max_size = field["max_size"]
    clean = " ".join(normalize_display_text(text).strip().split()).upper()
    if not clean:
        return

    font = load_bold_font(max_size)
    for size in range(max_size, 15, -1):
        candidate = load_bold_font(size)
        bbox = draw.textbbox((0, 0), clean, font=candidate)
        text_w = bbox[2] - bbox[0]
        if text_w <= width:
            font = candidate
            break

    bbox = draw.textbbox((0, 0), clean, font=font)
    y = int(round(line_y - bbox[3] - 2))
    draw.text((x, y), clean, font=font, fill=fill)


def compose_credential(
    face_image_path: Path,
    output_path: Path,
    *,
    nombre_completo: str,
    equipo: str,
    categoria: str,
    numero_jugador: str | int,
    fecha_nacimiento: str,
    lugar_fecha: str | None = None,
    temporada_suffix: str = DEFAULT_SEASON_SUFFIX,
    template_path: Path = TEMPLATE_PATH,
) -> Path:
    if not template_path.exists():
        raise FileNotFoundError(f"No se encontró la plantilla: {template_path}")
    if not face_image_path.exists():
        raise FileNotFoundError(f"No se encontró el rostro procesado: {face_image_path}")

    base = Image.open(template_path).convert("RGB")
    face = Image.open(face_image_path).convert("RGB")
    paste_rounded(base, face, PHOTO_BOX)

    draw = ImageDraw.Draw(base)
    season_clean = "".join(ch for ch in str(temporada_suffix or DEFAULT_SEASON_SUFFIX) if ch.isdigit())[-2:]
    values = {
        "temporada_suffix": season_clean.zfill(2),
        "nombre_completo": nombre_completo,
        "equipo": equipo,
        "categoria": categoria,
        "numero_jugador": str(numero_jugador),
        "fecha_nacimiento": fecha_nacimiento,
        "lugar_fecha": lugar_fecha or current_place_date(),
    }
    for key, value in values.items():
        draw_autofit_text(draw, value, TEXT_FIELDS[key])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    base.save(output_path, format="PNG", optimize=True)
    return output_path
