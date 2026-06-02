from __future__ import annotations

from pydantic import BaseModel, Field


class GenerateCredentialRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)
    nombre_completo: str = Field(default="", max_length=120)
    fecha_nacimiento: str = Field(default="", max_length=24)
    equipo: str = Field(max_length=80)
    categoria: str = Field(max_length=80)
    numero_jugador: str | int | None = Field(default="")
    lugar_fecha: str | None = Field(default=None, max_length=120)
    temporada_suffix: str = Field(default="26", pattern=r"^\d{2}$")


class GenerateCredentialResponse(BaseModel):
    session_id: str
    credential_url: str
    download_url: str
    format_url: str
    format_download_url: str
    lugar_fecha: str
    temporada_suffix: str
