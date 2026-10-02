from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Respuesta estable de los controles de salud."""

    status: Literal["ok"] = "ok"
    service: Literal["national-api"] = "national-api"
