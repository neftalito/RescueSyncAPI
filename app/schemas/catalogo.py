"""Alta administrativa de capacidades y consulta del catálogo fijo de unidades."""

from typing import Self

from pydantic import Field, field_validator, model_validator

from app.db.models import TipoRecurso
from app.schemas.inventario import Contrato, Nombre


class UnidadResponse(Contrato):
    codigo: str
    nombre: str


class CapacidadCreate(Contrato):
    codigo: str = Field(min_length=1, max_length=80, pattern=r"^[A-Z][A-Z0-9_-]*$")
    nombre: Nombre
    tipo: TipoRecurso
    unidad: str = Field(min_length=1, max_length=40)
    admite_fracciones: bool = Field(default=False, strict=True)

    @field_validator("codigo", "unidad", mode="before")
    @classmethod
    def recortar_texto(cls, valor: object) -> object:
        """Normaliza espacios sin cambiar la identidad canónica de la unidad."""
        return valor.strip() if isinstance(valor, str) else valor

    @model_validator(mode="after")
    def validar_cantidades_discretas(self) -> Self:
        """Personal y vehículos siempre se contabilizan como enteros."""
        if (
            self.tipo in {TipoRecurso.PERSONAL, TipoRecurso.VEHICULO}
            and self.admite_fracciones
        ):
            raise ValueError("Personal y vehículos no admiten cantidades fraccionadas.")
        return self
