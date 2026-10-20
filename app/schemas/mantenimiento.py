"""Contratos para cargas de demostración y vaciado de la base nacional."""

from typing import Literal, Self

from pydantic import Field, model_validator

from app.schemas.inventario import Contrato


class SeedMasivoRequest(Contrato):
    seed: int = Field(default=2026, ge=0, le=2_147_483_647, strict=True)
    ongs: int = Field(default=1000, ge=1, le=10_000, strict=True)
    recursos_por_ong: int = Field(default=20, ge=4, le=1000, strict=True)
    batch_size: int = Field(default=250, ge=1, le=1000, strict=True)

    @model_validator(mode="after")
    def limitar_volumen(self) -> Self:
        """Acota el trabajo sincrónico de una petición a 200.000 recursos."""
        if self.ongs * self.recursos_por_ong > 200_000:
            raise ValueError("La carga HTTP admite hasta 200.000 recursos.")
        return self


class MantenimientoResponse(Contrato):
    operacion: Literal["seed", "seed-masivo", "flush"]
    mensaje: str


class SeedMasivoResponse(MantenimientoResponse):
    ongs: int
    cuentas: int
    recursos: int
