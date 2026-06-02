from __future__ import annotations

import base64
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from text_utils import normalize_player_name, repair_text_encoding


EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "nombre_completo": {"type": "string"},
        "fecha_nacimiento": {
            "type": "string",
            "description": "Fecha en formato DD/MM/AAAA. Si no es visible, cadena vacía.",
        },
    },
    "required": ["nombre_completo", "fecha_nacimiento"],
}

PROMPT = """
Lee la identificación mexicana o pasaporte de la imagen. Extrae únicamente:
1. nombre_completo
2. fecha_nacimiento

Reglas:
- Responde JSON estricto, sin markdown.
- Usa DD/MM/AAAA para fecha_nacimiento.
- Si un campo no se ve con confianza, usa cadena vacía.
- No inventes datos.
""".strip()

_RAPIDOCR_ENGINE: Any | None = None

KNOWN_NAME_FIXES = {
    "BENITOALBERTO": "BENITO ALBERTO",
    "DIEGOEDUARDO": "DIEGO EDUARDO",
    "ERICKBRANDON": "ERICK BRANDON",
    "JESUSSALVADOR": "JESUS SALVADOR",
    "STEVENJOSUE": "STEVEN JOSUE",
    "VICTORMANUEL": "VICTOR MANUEL",
}


@dataclass
class OcrToken:
    text: str
    norm: str
    score: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2


def extract_player_data(image_path: Path) -> tuple[dict[str, str], list[str]]:
    warnings: list[str] = []
    provider = os.getenv("OCR_PROVIDER", "auto").lower()
    api_attempted = False
    local_ocr_enabled = provider not in {"api", "api_only", "cloud", "disabled", "none", "manual"}

    if provider in {"auto", "api", "api_only", "cloud", "openai"} and os.getenv("OPENAI_API_KEY"):
        api_attempted = True
        try:
            return _extract_with_openai(image_path), warnings
        except Exception as exc:
            warnings.append(f"OCR OpenAI falló: {exc}")

    if provider in {"auto", "api", "api_only", "cloud", "gemini"} and os.getenv("GEMINI_API_KEY"):
        api_attempted = True
        try:
            return _extract_with_gemini(image_path), warnings
        except Exception as exc:
            warnings.append(f"OCR Gemini falló: {exc}")

    if local_ocr_enabled:
        try:
            local_result = _extract_with_rapidocr(image_path)
            if local_result["nombre_completo"] or local_result["fecha_nacimiento"]:
                if not local_result["nombre_completo"]:
                    warnings.append("OCR local encontró fecha, pero no nombre. Revisa el campo manualmente.")
                if not local_result["fecha_nacimiento"]:
                    warnings.append("OCR local encontró nombre, pero no fecha. Revisa el campo manualmente.")
                return local_result, warnings
        except Exception as exc:
            warnings.append(f"OCR local RapidOCR no disponible o falló: {exc}")

    if api_attempted:
        warnings.append("No se pudo extraer texto con API ni OCR local.")
    elif not local_ocr_enabled:
        warnings.append(
            "OCR automatico no configurado en Render. Agrega OPENAI_API_KEY o GEMINI_API_KEY "
            "para extraer nombre y fecha automaticamente; mientras tanto captura los datos manualmente."
        )
    else:
        warnings.append("No hay OCR multimodal configurado y el OCR local no pudo extraer datos.")
    return _empty_result(), warnings


def _empty_result() -> dict[str, str]:
    return {"nombre_completo": "", "fecha_nacimiento": ""}


def _extract_with_openai(image_path: Path) -> dict[str, str]:
    from openai import OpenAI

    client = OpenAI()
    image_url = _as_data_url(image_path)
    response = client.responses.create(
        model=os.getenv("OPENAI_VISION_MODEL", "gpt-4o"),
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": PROMPT},
                    {"type": "input_image", "image_url": image_url},
                ],
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "identificacion_jugador",
                "schema": EXTRACTION_SCHEMA,
                "strict": True,
            }
        },
    )
    return _normalize_result(_parse_json(_response_text(response)))


def _extract_with_gemini(image_path: Path) -> dict[str, str]:
    import google.generativeai as genai

    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")
    model = genai.GenerativeModel(model_name)
    image = Image.open(image_path)
    response = model.generate_content(
        [PROMPT, image],
        generation_config={"response_mime_type": "application/json"},
    )
    return _normalize_result(_parse_json(response.text))


def _extract_with_rapidocr(image_path: Path) -> dict[str, str]:
    global _RAPIDOCR_ENGINE
    if _RAPIDOCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _RAPIDOCR_ENGINE = RapidOCR()

    result, _ = _RAPIDOCR_ENGINE(str(image_path))
    tokens = _rapidocr_tokens(result or [])
    if not tokens:
        return _empty_result()

    with Image.open(image_path) as image:
        image_w, image_h = image.size

    nombre = _extract_ine_name(tokens, image_w, image_h)
    fecha = _extract_birth_date(tokens)
    return {"nombre_completo": nombre, "fecha_nacimiento": fecha}


def _rapidocr_tokens(result: list[Any]) -> list[OcrToken]:
    tokens: list[OcrToken] = []
    for item in result:
        if len(item) < 3:
            continue
        box, text, score = item
        if not text:
            continue
        clean_text = repair_text_encoding(str(text).strip())
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        tokens.append(
            OcrToken(
                text=clean_text,
                norm=_norm_text(clean_text),
                score=float(score),
                x1=min(xs),
                y1=min(ys),
                x2=max(xs),
                y2=max(ys),
            )
        )
    return tokens


def _extract_ine_name(tokens: list[OcrToken], image_w: int, image_h: int) -> str:
    labels = [
        token
        for token in tokens
        if token.norm in {"NOMBRE", "NOMBRES"} and 0.12 * image_h <= token.cy <= 0.55 * image_h
    ]
    if not labels:
        return ""

    label = min(labels, key=lambda token: (token.cy, token.x1))
    stop_candidates = [
        token
        for token in tokens
        if token.cy > label.cy and token.norm.startswith(("DOMICILIO", "CLAVEDEELECTOR", "CURP", "FECHADENACIMIENTO"))
    ]
    stop_y = min((token.y1 for token in stop_candidates), default=label.y2 + image_h * 0.2)

    raw_lines = [
        token
        for token in tokens
        if token.y1 >= label.y2 - 10
        and token.cy > label.cy
        and token.y1 < stop_y
        and token.x1 >= label.x1 - image_w * 0.04
        and token.x1 <= label.x1 + image_w * 0.42
        and _looks_like_name_line(token.norm)
    ]
    raw_lines = sorted(raw_lines, key=lambda token: (token.y1, token.x1))[:4]
    parts = [_clean_name_part(token.text) for token in raw_lines]
    return " ".join(part for part in parts if part).strip()


def _looks_like_name_line(text: str) -> bool:
    if not text or len(text) < 3:
        return False
    blocked = {
        "NOMBRE",
        "NOMBRES",
        "DOMICILIO",
        "SEXO",
        "SEXOH",
        "SECCION",
        "VIGENCIA",
        "MEXICO",
        "CREDENCIALPARAVOTAR",
        "INSTITUTONACIONALELECTORAL",
    }
    if text in blocked or text.startswith(("CLAVE", "CURP", "FECHA", "ANO")):
        return False
    return bool(re.fullmatch(r"[A-ZÑÁÉÍÓÚÜ]+", text))


def _clean_name_part(text: str) -> str:
    text = repair_text_encoding(text)
    cleaned = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", text).upper()
    cleaned = _restore_known_name_spaces(cleaned)
    return normalize_player_name(cleaned).upper()


def _restore_known_name_spaces(text: str) -> str:
    if text in KNOWN_NAME_FIXES:
        return KNOWN_NAME_FIXES[text]
    return text


def _extract_birth_date(tokens: list[OcrToken]) -> str:
    labels = [token for token in tokens if token.norm.startswith("FECHADENACIMIENTO")]
    candidates = _date_candidates(tokens)
    if candidates:
        if labels:
            label = min(labels, key=lambda token: token.cy)
            candidates.sort(key=lambda item: abs(item[0].cy - label.cy) + abs(item[0].cx - label.cx) * 0.12)
        return candidates[0][1]

    curp_date = _date_from_curp(tokens)
    if curp_date:
        return curp_date
    return ""


def _date_candidates(tokens: list[OcrToken]) -> list[tuple[OcrToken, str]]:
    candidates: list[tuple[OcrToken, str]] = []
    for token in tokens:
        compact = token.norm
        for match in re.finditer(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", compact):
            normalized = _normalize_date_parts(match.group(1), match.group(2), match.group(3))
            if normalized:
                candidates.append((token, normalized))

        broken = re.fullmatch(r"(\d{1,2})/(\d{5})", token.text.strip())
        if broken:
            tail = broken.group(2)
            normalized = _normalize_date_parts(broken.group(1), tail[:2], tail[2:])
            if normalized:
                candidates.append((token, normalized))
    return candidates


def _date_from_curp(tokens: list[OcrToken]) -> str:
    joined = " ".join(token.norm for token in sorted(tokens, key=lambda token: (token.y1, token.x1)))
    match = re.search(r"[A-ZÑ]{4}(\d{2})(\d{2})(\d{2})[HM]", joined)
    if not match:
        return ""
    yy, month, day = match.groups()
    return _normalize_date_parts(day, month, yy)


def _normalize_date_parts(day: str, month: str, year: str) -> str:
    try:
        d = int(day)
        m = int(month)
        y = int(year)
    except ValueError:
        return ""
    if y < 100:
        y += 2000 if y <= 26 else 1900
    if not (1900 <= y <= 2026 and 1 <= m <= 12 and 1 <= d <= 31):
        return ""
    return f"{d:02d}/{m:02d}/{y:04d}"


def _norm_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.upper().replace("Ñ", "Ñ")
    return re.sub(r"[^A-ZÑ0-9/.\-]", "", text)


def _as_data_url(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _response_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return text
    if hasattr(response, "model_dump"):
        payload = response.model_dump()
        chunks: list[str] = []
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if "text" in content:
                    chunks.append(content["text"])
        if chunks:
            return "\n".join(chunks)
    return str(response)


def _parse_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def _normalize_result(data: dict[str, Any]) -> dict[str, str]:
    return {
        "nombre_completo": normalize_player_name(data.get("nombre_completo", "")),
        "fecha_nacimiento": repair_text_encoding(data.get("fecha_nacimiento", "")).strip(),
    }
