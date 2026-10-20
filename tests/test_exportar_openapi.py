"""Verifica exportación reproducible sin servidor ni conexión a PostgreSQL."""

import json
import subprocess
import sys
from pathlib import Path

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs/scripts/exportar_openapi_pdf.py"


def test_exporta_json_y_pdf_desde_otro_directorio(tmp_path: Path) -> None:
    pdf = tmp_path / "entrega" / "api.pdf"
    contrato = tmp_path / "entrega" / "contrato.json"
    resultado = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--salida",
            str(pdf),
            "--salida-json",
            str(contrato),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "PDF generado" in resultado.stdout
    assert pdf.read_bytes().startswith(b"%PDF-")
    assert json.loads(contrato.read_text()) == app.openapi()


def test_exporta_archivo_alternativo_sin_generar_pdf(tmp_path: Path) -> None:
    fuente = tmp_path / "fuente.json"
    esquema = {
        "openapi": "3.1.0",
        "info": {"title": "Alternativo", "version": "1"},
        "paths": {},
    }
    fuente.write_text(json.dumps(esquema))
    salida = tmp_path / "salida.json"
    pdf = tmp_path / "omitido.pdf"
    resultado = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--archivo",
            str(fuente),
            "--solo-json",
            "--salida",
            str(pdf),
            "--salida-json",
            str(salida),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(salida.read_text()) == esquema
    assert "PDF generado" not in resultado.stdout
    assert not pdf.exists()
