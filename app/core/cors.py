"""Orígenes explícitos y CORS aplicado también a errores no controlados."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import AnyHttpUrl
from starlette.types import ASGIApp


def normalizar_origenes(origenes: list[str]) -> list[str]:
    """Valida orígenes HTTP completos y normaliza host, puerto y barra final."""
    resultado: list[str] = []
    for origen in origenes:
        valor = origen.strip()
        if (
            not valor.lower().startswith(("http://", "https://"))
            or any(c.isspace() for c in valor)
            or "*" in valor
            or "\\" in valor
        ):
            raise ValueError("CORS_ORIGINS requiere orígenes HTTP/HTTPS explícitos")
        url = AnyHttpUrl(valor)
        if (
            url.username is not None
            or url.password is not None
            or url.path not in {None, "/"}
            or url.query is not None
            or url.fragment is not None
        ):
            raise ValueError(
                "CORS_ORIGINS no admite credenciales, rutas, query ni fragmentos"
            )
        normalizado = str(url).rstrip("/")
        if normalizado not in resultado:
            resultado.append(normalizado)
    return resultado


class AplicacionConCORS(FastAPI):
    """Conserva la interfaz FastAPI y envuelve toda la cadena, incluidos los 500."""

    origenes_cors: tuple[str, ...] = ()
    credenciales_cors: bool = False

    def build_middleware_stack(self) -> ASGIApp:
        return CORSMiddleware(
            app=super().build_middleware_stack(),
            allow_origins=self.origenes_cors,
            allow_credentials=self.credenciales_cors,
            allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "X-CSRF-Token",
                "Idempotency-Key",
                "X-Bonita-Root-Process-Instance-Id",
                "X-DB-Maintenance-Password",
            ],
        )
