from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import (
    CATEGORIES,
    FORMAT_TEMPLATE_PATH,
    FRONTEND_DIR,
    STATIC_DIR,
    STORAGE_DIR,
    TEAMS,
    TEMPLATE_PATH,
    ensure_directories,
)
from credential_composer import (
    DEFAULT_SEASON_SUFFIX,
    compose_credential,
    current_credential_date_iso,
    current_place_date,
    current_place_date_parts,
)
from docx_formatter import compose_word_format
from image_pipeline import process_identification
from ocr_clients import extract_player_data
from schemas import GenerateCredentialRequest, GenerateCredentialResponse


ensure_directories()

app = FastAPI(title="Credenciales Liga de Futbol Soccer Cruztitla", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if FRONTEND_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")


@app.get("/")
def index() -> FileResponse:
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="No se encontró frontend/index.html")
    return FileResponse(index_path, headers={"Cache-Control": "no-store"})


@app.get("/api/health")
def health() -> dict[str, str | bool]:
    return {
        "ok": True,
        "template_found": TEMPLATE_PATH.exists(),
        "template_path": str(TEMPLATE_PATH),
        "format_template_found": FORMAT_TEMPLATE_PATH.exists(),
        "format_template_path": str(FORMAT_TEMPLATE_PATH),
    }


@app.get("/api/options")
def options() -> dict[str, object]:
    return {
        "teams": TEAMS,
        "categories": CATEGORIES,
        "lugar_fecha": current_place_date(),
        "place_date": current_place_date_parts(),
        "credential_date_iso": current_credential_date_iso(),
        "default_temporada_suffix": DEFAULT_SEASON_SUFFIX,
        "season_suffixes": [f"{year:02d}" for year in range(20, 41)],
        "template_url": "/static/plantilla.png",
    }


@app.post("/api/process-id")
async def process_id(file: UploadFile = File(...)) -> dict[str, object]:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Sube un archivo de imagen.")

    session_id = uuid.uuid4().hex
    session_dir = STORAGE_DIR / session_id
    try:
        file_bytes = await file.read()
        processed = process_identification(file_bytes, session_dir)
        extracted, ocr_warnings = extract_player_data(processed.warped_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo procesar la identificación: {exc}") from exc

    warnings = [*processed.warnings, *ocr_warnings]
    return {
        "session_id": session_id,
        "extracted": extracted,
        "lugar_fecha": current_place_date(),
        "place_date": current_place_date_parts(),
        "credential_date_iso": current_credential_date_iso(),
        "images": {
            "raw": f"/api/files/{session_id}/raw",
            "warped": f"/api/files/{session_id}/warped",
            "face": f"/api/files/{session_id}/face",
        },
        "document_corners": processed.document_corners,
        "face_box": processed.face_box,
        "restoration_method": processed.restoration_method,
        "warnings": warnings,
    }


@app.post("/api/generate-credential", response_model=GenerateCredentialResponse)
def generate_credential(payload: GenerateCredentialRequest) -> GenerateCredentialResponse:
    session_dir = _safe_session_dir(payload.session_id)
    face_path = session_dir / "face_enhanced.jpg"
    raw_path = session_dir / "raw.jpg"
    document_path = session_dir / "warped.jpg"
    if not face_path.exists():
        raise HTTPException(status_code=404, detail="No se encontró el rostro procesado para esta sesión.")
    if not raw_path.exists():
        raise HTTPException(status_code=404, detail="No se encontró la identificación original para esta sesión.")

    output_path = session_dir / "credential.png"
    format_path = session_dir / "formato_credencial.docx"
    lugar_fecha = (payload.lugar_fecha or "").strip() or current_place_date()
    try:
        compose_credential(
            face_path,
            output_path,
            nombre_completo=payload.nombre_completo,
            equipo=payload.equipo,
            categoria=payload.categoria,
            numero_jugador=payload.numero_jugador if payload.numero_jugador is not None else "",
            fecha_nacimiento=payload.fecha_nacimiento,
            lugar_fecha=lugar_fecha,
            temporada_suffix=payload.temporada_suffix,
        )
        compose_word_format(
            FORMAT_TEMPLATE_PATH,
            output_path,
            document_path if document_path.exists() else raw_path,
            format_path,
        )
        (session_dir / "credential_meta.json").write_text(
            json.dumps({"nombre_completo": payload.nombre_completo}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo componer la credencial/formato: {exc}") from exc

    url = f"/api/files/{payload.session_id}/credential"
    format_url = f"/api/files/{payload.session_id}/format"
    return GenerateCredentialResponse(
        session_id=payload.session_id,
        credential_url=url,
        download_url=f"{url}?download=1",
        format_url=format_url,
        format_download_url=f"{format_url}?download=1",
        lugar_fecha=lugar_fecha,
        temporada_suffix=payload.temporada_suffix,
    )


@app.get("/api/files/{session_id}/{kind}")
def get_file(session_id: str, kind: str, download: int = 0) -> FileResponse:
    session_dir = _safe_session_dir(session_id)
    files = {
        "raw": ("raw.jpg", "image/jpeg"),
        "warped": ("warped.jpg", "image/jpeg"),
        "face": ("face_enhanced.jpg", "image/jpeg"),
        "face-raw": ("face_raw.jpg", "image/jpeg"),
        "credential": ("credential.png", "image/png"),
        "format": (
            "formato_credencial.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    }
    if kind not in files:
        raise HTTPException(status_code=404, detail="Archivo no soportado.")

    filename, media_type = files[kind]
    path = session_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")

    response_names = {
        "credential": "credencial-cruztitla.png",
        "format": _format_download_name(session_dir),
    }
    response_name = response_names.get(kind, filename)
    return FileResponse(path, media_type=media_type, filename=response_name if download else None)


def _safe_session_dir(session_id: str) -> Path:
    if not re.fullmatch(r"[a-fA-F0-9]{32}", session_id):
        raise HTTPException(status_code=400, detail="session_id inválido.")
    session_dir = STORAGE_DIR / session_id
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="Sesión no encontrada.")
    return session_dir


def _format_download_name(session_dir: Path) -> str:
    meta_path = session_dir / "credential_meta.json"
    if not meta_path.exists():
        return "formato-credencial-cruztitla.docx"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return "formato-credencial-cruztitla.docx"

    stem = _safe_download_stem(str(meta.get("nombre_completo") or ""))
    return f"{stem or 'formato-credencial-cruztitla'}.docx"


def _safe_download_stem(value: str) -> str:
    clean = " ".join(value.strip().split())
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", clean)
    clean = clean.strip(" .")
    return clean[:120]
