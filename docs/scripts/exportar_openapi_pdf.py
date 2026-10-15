#!/usr/bin/env python3
"""Exporta OpenAPI con un diseño inspirado en Swagger UI.

Desde cualquier carpeta, sin iniciar el servidor ni conectar la base de datos:
    python /ruta/a/RescueSyncAPI/docs/scripts/exportar_openapi_pdf.py

Salida predeterminada: RescueSyncAPI/docs/generated/documentacion-api.pdf.
Requiere Python 3.13 y las dependencias de la API, además de ReportLab:
    python -m pip install -r requirements.txt reportlab

Se conservan las opciones --url, --archivo y --salida para otras especificaciones:
    python docs/scripts/exportar_openapi_pdf.py --url http://localhost:8001/openapi.json
    python docs/scripts/exportar_openapi_pdf.py --archivo openapi.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from collections import defaultdict
from contextlib import chdir
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import (
        Flowable,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    from reportlab.platypus.tableofcontents import TableOfContents
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Falta ReportLab. Instalalo con: python -m pip install reportlab"
    ) from exc

type ValorJSON = (
    dict[str, ValorJSON] | list[ValorJSON] | str | int | float | bool | None
)
type ObjetoJSON = dict[str, ValorJSON]

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]
SALIDA_PREDETERMINADA = RAIZ_PROYECTO / "docs/generated/documentacion-api.pdf"
# Colores de los bloques de operaciones en Swagger UI.
COLORES_HTTP = {
    "get": "#61affe",
    "post": "#49cc90",
    "put": "#fca130",
    "patch": "#50e3c2",
    "delete": "#f93e3e",
    "options": "#0d5aa7",
    "head": "#9012fe",
    "trace": "#555555",
}
METODOS_HTTP = set(COLORES_HTTP)
TINTA = colors.HexColor("#243247")
GRIS = colors.HexColor("#64748b")
FONDO = colors.HexColor("#f3f6fa")
VERDE = colors.HexColor("#24805a")
ANCHO = A4[0] - 36 * mm


def objeto(valor: ValorJSON) -> ObjetoJSON:
    return valor if isinstance(valor, dict) else {}


def lista(valor: ValorJSON) -> list[ValorJSON]:
    return valor if isinstance(valor, list) else []


def configurar_fuentes() -> tuple[str, str, str]:
    carpeta = Path("/usr/share/fonts/truetype/dejavu")
    archivos = ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSansMono.ttf")
    nombres = ("Texto", "TextoNegrita", "Codigo")
    if all((carpeta / archivo).is_file() for archivo in archivos):
        for nombre, archivo in zip(nombres, archivos, strict=True):
            pdfmetrics.registerFont(TTFont(nombre, str(carpeta / archivo)))
        pdfmetrics.registerFontFamily("Texto", normal="Texto", bold="TextoNegrita")
        return nombres
    return "Helvetica", "Helvetica-Bold", "Courier"


def obtener_openapi(url: str | None = None, archivo: Path | None = None) -> ObjetoJSON:
    """Genera el contrato local por defecto; no ejecuta el ciclo de vida de la API."""
    if archivo is not None:
        with archivo.open(encoding="utf-8") as entrada:
            esquema = json.load(entrada)
    elif url is not None:
        solicitud = Request(url, headers={"Accept": "application/json"})
        with urlopen(solicitud, timeout=30) as respuesta:
            esquema = json.load(respuesta)
    else:
        # Tanto los imports como la lectura del .env deben usar la raíz nacional,
        # incluso al invocar el script desde docs/scripts u otra carpeta.
        ruta_importacion = str(RAIZ_PROYECTO)
        sys.path.insert(0, ruta_importacion)
        try:
            with chdir(RAIZ_PROYECTO):
                from app.main import app

                esquema = app.openapi()
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Para generar el contrato local, instalá las dependencias de la API: "
                f'python -m pip install -r "{RAIZ_PROYECTO / "requirements.txt"}". '
                "También podés usar --url o --archivo."
            ) from exc
        finally:
            sys.path.remove(ruta_importacion)

    if not isinstance(esquema, dict) or "openapi" not in esquema:
        raise ValueError("La fuente no contiene una especificación OpenAPI válida.")
    return esquema


def destino_modelo(nombre: str) -> str:
    return f"modelo-{quote(nombre, safe='')}"


def tipo_esquema(esquema: ValorJSON) -> str:
    """Resume referencias y composiciones sin expandir modelos recursivos."""
    datos = objeto(esquema)
    if "$ref" in datos:
        return str(datos["$ref"]).rsplit("/", 1)[-1]
    for clave, separador in (("anyOf", " | "), ("oneOf", " | "), ("allOf", " & ")):
        if clave in datos:
            return separador.join(tipo_esquema(item) for item in lista(datos[clave]))
    tipo = datos.get("type", "object")
    if isinstance(tipo, list):
        return " | ".join(str(item) for item in tipo)
    if tipo == "array":
        return f"array[{tipo_esquema(datos.get('items'))}]"
    return f"{tipo} ({datos['format']})" if datos.get("format") else str(tipo)


class DocumentoOpenAPI(SimpleDocTemplate):
    def beforeDocument(self) -> None:
        self.seccion = 0

    def afterFlowable(self, elemento: Flowable) -> None:
        if isinstance(elemento, Paragraph) and elemento.style.name == "seccion":
            clave = f"seccion-{self.seccion}"
            self.seccion += 1
            titulo = elemento.getPlainText()
            self.canv.bookmarkPage(clave)
            self.canv.addOutlineEntry(titulo, clave, level=0)
            self.notify("TOCEntry", (0, escape(titulo), self.page, clave))


class ExportadorPDF:
    """Construye bloques legibles que pueden continuar entre páginas A4."""

    def __init__(self, esquema: ObjetoJSON) -> None:
        self.esquema = esquema
        self.elementos: list[Flowable] = []
        texto, negrita, codigo = configurar_fuentes()
        self.estilos = {
            "titulo": ParagraphStyle(
                "titulo",
                fontName=negrita,
                fontSize=25,
                leading=32,
                spaceAfter=15,
                textColor=TINTA,
            ),
            "seccion": ParagraphStyle(
                "seccion",
                fontName=negrita,
                fontSize=18,
                leading=24,
                spaceAfter=12,
                textColor=TINTA,
                keepWithNext=True,
            ),
            "subtitulo": ParagraphStyle(
                "subtitulo",
                fontName=negrita,
                fontSize=11,
                leading=16,
                spaceBefore=12,
                spaceAfter=7,
                textColor=TINTA,
                keepWithNext=True,
            ),
            "texto": ParagraphStyle(
                "texto",
                fontName=texto,
                fontSize=8.5,
                leading=13,
                spaceAfter=7,
                textColor=TINTA,
                splitLongWords=True,
            ),
            "celda": ParagraphStyle(
                "celda",
                fontName=texto,
                fontSize=7.5,
                leading=11,
                textColor=TINTA,
                splitLongWords=True,
            ),
            "cabecera": ParagraphStyle(
                "cabecera",
                fontName=negrita,
                fontSize=7.5,
                leading=11,
                textColor=colors.white,
            ),
            "codigo": ParagraphStyle(
                "codigo",
                fontName=codigo,
                fontSize=6.7,
                leading=10,
                leftIndent=8,
                rightIndent=8,
                backColor=FONDO,
                textColor=TINTA,
            ),
            "indice": ParagraphStyle(
                "indice",
                fontName=texto,
                fontSize=10,
                leading=22,
                textColor=TINTA,
            ),
        }

    def parrafo(self, valor: object, estilo: str = "texto") -> Paragraph:
        contenido = escape(str(valor)).replace("\n", "<br/>")
        return Paragraph(contenido or "&#160;", self.estilos[estilo])

    def texto(self, valor: object, estilo: str = "texto") -> None:
        self.elementos.append(self.parrafo(valor, estilo))

    def descripcion(self, valor: ValorJSON) -> None:
        if not valor:
            return
        contenido = escape(str(valor))
        contenido = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", contenido)
        contenido = re.sub(r"`([^`]+)`", r'<font color="#24805a">\1</font>', contenido)
        contenido = re.sub(r"(?m)^#{1,6}\s+(.+)$", r"<b>\1</b>", contenido)
        contenido = re.sub(r"(?m)^[-*]\s+", "• ", contenido)
        self.elementos.append(
            Paragraph(contenido.replace("\n", "<br/>"), self.estilos["texto"])
        )

    def tabla(
        self,
        cabeceras: list[str],
        filas: list[list[str | Paragraph]],
        anchos: list[float],
    ) -> None:
        if not filas:
            return
        contenido = [[self.parrafo(c, "cabecera") for c in cabeceras]]
        contenido.extend(
            [c if isinstance(c, Paragraph) else self.parrafo(c, "celda") for c in fila]
            for fila in filas
        )
        tabla = Table(
            contenido,
            colWidths=[ANCHO * a for a in anchos],
            repeatRows=1,
            hAlign="LEFT",
            splitByRow=1,
            splitInRow=1,
        )
        tabla.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), TINTA),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, FONDO]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.6, VERDE),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#dce3ec")),
                ]
            )
        )
        self.elementos.extend([tabla, Spacer(1, 3 * mm)])

    def mostrar_json(self, etiqueta: str, valor: ValorJSON) -> None:
        self.texto(etiqueta, "subtitulo")
        for renglon in json.dumps(valor, ensure_ascii=False, indent=2).splitlines():
            for parte in textwrap.wrap(
                renglon,
                width=95,
                subsequent_indent="  ",
                replace_whitespace=False,
                drop_whitespace=False,
                break_long_words=True,
                break_on_hyphens=False,
            ) or [""]:
                contenido = escape(parte).replace(" ", "&#160;") or "&#160;"
                self.elementos.append(Paragraph(contenido, self.estilos["codigo"]))
        self.elementos.append(Spacer(1, 3 * mm))

    def resolver(self, valor: ValorJSON) -> ObjetoJSON:
        """Resuelve referencias locales de parámetros, cuerpos y respuestas."""
        datos = objeto(valor)
        referencia = datos.get("$ref")
        if isinstance(referencia, str) and referencia.startswith("#/"):
            resultado: ValorJSON = self.esquema
            for segmento in referencia[2:].split("/"):
                resultado = objeto(resultado).get(
                    segmento.replace("~1", "/").replace("~0", "~")
                )
            return {
                **objeto(resultado),
                **{k: v for k, v in datos.items() if k != "$ref"},
            }
        return datos

    def modelo(self, valor: ValorJSON) -> Paragraph:
        datos = objeto(valor)
        referencia = str(datos.get("$ref", ""))
        modelos = objeto(objeto(self.esquema.get("components")).get("schemas"))
        nombre = referencia.rsplit("/", 1)[-1]
        contenido = escape(tipo_esquema(valor))
        if referencia.startswith("#/components/schemas/") and nombre in modelos:
            contenido = (
                f'<a href="#{destino_modelo(nombre)}" color="#24805a">'
                f"{escape(nombre)}</a>"
            )
        elif datos.get("type") == "array":
            contenido = f"array[{self.modelo(datos.get('items')).text}]"
        else:
            for clave, separador in (
                ("anyOf", " | "),
                ("oneOf", " | "),
                ("allOf", " &amp; "),
            ):
                if clave in datos:
                    contenido = separador.join(
                        self.modelo(item).text for item in lista(datos[clave])
                    )
                    break
        return Paragraph(contenido, self.estilos["celda"])

    def detalle_esquema(self, valor: ValorJSON) -> str:
        datos = objeto(valor)
        lineas = [str(datos["description"])] if datos.get("description") else []
        for clave, dato in datos.items():
            if clave not in {"title", "description", "type", "format", "$ref"}:
                lineas.append(f"{clave}: {json.dumps(dato, ensure_ascii=False)}")
        return "\n".join(lineas) or "—"

    def contenido(self, contenido: ValorJSON, *, resumen: bool = True) -> None:
        for medio, detalle in objeto(contenido).items():
            datos = objeto(detalle)
            esquema = objeto(datos.get("schema"))
            if resumen:
                self.tabla(
                    ["Tipo de contenido", "Modelo"],
                    [[medio, self.modelo(esquema)]],
                    [0.4, 0.6],
                )
            # Las referencias ya tienen un enlace al contrato completo del modelo.
            # Los esquemas inline y los ejemplos se muestran sin perder información.
            extras = {k: v for k, v in datos.items() if k != "schema"}
            if set(esquema) != {"$ref"}:
                extras["schema"] = esquema
            if extras:
                self.mostrar_json(f"Esquema y ejemplos · {medio}", extras)

    def operacion(
        self, ruta: str, metodo: str, operacion: ObjetoJSON, compartidos: ObjetoJSON
    ) -> None:
        color = colors.HexColor(COLORES_HTTP[metodo.lower()])
        estilo = ParagraphStyle(
            "ruta",
            parent=self.estilos["texto"],
            fontSize=10,
            leading=15,
            spaceAfter=0,
        )
        bloque = Table(
            [
                [
                    Paragraph(
                        f'<font color="#ffffff"><b>{metodo.upper()}</b></font>', estilo
                    ),
                    Paragraph(f"<b>{escape(ruta)}</b>", estilo),
                ],
            ],
            colWidths=[23 * mm, ANCHO - 23 * mm],
        )
        bloque.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, 0), color),
                    (
                        "BACKGROUND",
                        (1, 0),
                        (1, 0),
                        colors.linearlyInterpolatedColor(
                            color, colors.white, 0, 1, 0.92
                        ),
                    ),
                    ("BOX", (0, 0), (-1, -1), 0.8, color),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ]
            )
        )
        bloque.keepWithNext = True
        self.elementos.append(bloque)
        self.texto(operacion.get("summary", "Operación"), "subtitulo")
        self.descripcion(operacion.get("description"))
        if operacion.get("operationId"):
            self.texto(f"ID: {operacion['operationId']}")
        if len(lista(operacion.get("tags"))) > 1:
            self.texto(
                "Etiquetas: " + ", ".join(str(t) for t in lista(operacion["tags"]))
            )
        if operacion.get("deprecated"):
            self.texto("OBSOLETO · Este endpoint está marcado como deprecado.")
        seguridad = operacion.get("security", self.esquema.get("security", []))
        if seguridad:
            alternativas = [
                ", ".join(f"{k} {v}" if v else k for k, v in objeto(item).items())
                or "Acceso público"
                for item in lista(seguridad)
            ]
            self.texto(f"Autenticación: {' / '.join(alternativas)}")
        else:
            self.texto("Acceso público · Sin autenticación declarada en OpenAPI.")

        parametros: dict[tuple[str, str], ObjetoJSON] = {}
        for parametro in lista(compartidos.get("parameters")) + lista(
            operacion.get("parameters")
        ):
            datos = self.resolver(parametro)
            parametros[
                (str(datos.get("name", "Referencia")), str(datos.get("in", "")))
            ] = datos
        if parametros:
            self.texto("Parámetros", "subtitulo")
            filas: list[list[str | Paragraph]] = []
            for (nombre, ubicacion), datos in parametros.items():
                detalle = {
                    k: v
                    for k, v in datos.items()
                    if k not in {"name", "in", "required", "description", "schema"}
                }
                descripcion = str(datos.get("description", ""))
                restricciones = self.detalle_esquema(datos.get("schema"))
                if restricciones != "—":
                    descripcion += "\n" + restricciones
                if detalle:
                    descripcion += "\n" + json.dumps(detalle, ensure_ascii=False)
                filas.append(
                    [
                        nombre + (" *" if datos.get("required") else ""),
                        ubicacion,
                        self.modelo(datos.get("schema")),
                        descripcion or "—",
                    ]
                )
            self.tabla(
                ["Nombre (* obligatorio)", "En", "Tipo", "Descripción / restricciones"],
                filas,
                [0.25, 0.10, 0.23, 0.42],
            )
        if operacion.get("requestBody"):
            cuerpo = self.resolver(operacion["requestBody"])
            self.texto(
                "Cuerpo de la solicitud"
                + (" · obligatorio" if cuerpo.get("required") else " · opcional"),
                "subtitulo",
            )
            self.descripcion(cuerpo.get("description"))
            self.contenido(cuerpo.get("content"))
        self.texto("Respuestas", "subtitulo")
        filas_respuestas: list[list[str | Paragraph]] = []
        for codigo, respuesta in objeto(operacion.get("responses")).items():
            datos = self.resolver(respuesta)
            contenidos = objeto(datos.get("content"))
            for medio, contenido in (contenidos or {"Sin cuerpo": {}}).items():
                modelo = self.modelo(objeto(contenido).get("schema"))
                filas_respuestas.append(
                    [
                        codigo,
                        str(datos.get("description", "")),
                        Paragraph(
                            escape(medio) + "<br/>" + modelo.text
                            if contenidos
                            else "Sin cuerpo",
                            self.estilos["celda"],
                        ),
                    ]
                )
        self.tabla(
            ["Código", "Descripción", "Contenido / modelo"],
            filas_respuestas,
            [0.12, 0.40, 0.48],
        )
        for codigo, respuesta in objeto(operacion.get("responses")).items():
            datos = self.resolver(respuesta)
            self.contenido(datos.get("content"), resumen=False)
            extras = {
                k: v for k, v in datos.items() if k not in {"description", "content"}
            }
            if extras:
                self.mostrar_json(f"Cabeceras y metadatos · {codigo}", extras)
        extras = {
            k: v
            for k, v in operacion.items()
            if k
            not in {
                "summary",
                "description",
                "parameters",
                "requestBody",
                "responses",
                "operationId",
                "security",
                "deprecated",
                "tags",
            }
        }
        if extras:
            self.mostrar_json("Metadatos de la operación", extras)
        self.elementos.append(Spacer(1, 7 * mm))

    def construir(self, salida: Path) -> None:
        info = objeto(self.esquema.get("info"))
        rutas = objeto(self.esquema.get("paths"))
        componentes = objeto(self.esquema.get("components"))
        modelos = objeto(componentes.get("schemas"))
        grupos: dict[str, list[tuple[str, str, ObjetoJSON, ObjetoJSON]]] = defaultdict(
            list
        )
        for ruta, valor in rutas.items():
            datos = objeto(valor)
            for metodo, operacion in datos.items():
                if metodo.lower() in METODOS_HTTP:
                    tags = lista(objeto(operacion).get("tags"))
                    grupos[str(tags[0]) if tags else "General"].append(
                        (ruta, metodo, objeto(operacion), datos)
                    )

        nombre = str(info.get("title", "Documentación de API"))
        self.texto("RESCUESYNC  /  REFERENCIA DE API", "subtitulo")
        self.texto(nombre, "titulo")
        self.tabla(
            ["Versión de API", "OpenAPI", "Operaciones", "Modelos"],
            [
                [
                    str(info.get("version", "—")),
                    str(self.esquema.get("openapi", "—")),
                    str(sum(len(operaciones) for operaciones in grupos.values())),
                    str(len(modelos)),
                ]
            ],
            [0.25] * 4,
        )
        self.descripcion(info.get("description"))
        self.texto(f"Generado el {datetime.now(UTC):%d/%m/%Y %H:%M} UTC")
        self.texto("Guía de lectura", "subtitulo")
        self.texto(
            "Las operaciones se agrupan por etiqueta. Cada método HTTP tiene su color; "
            "los campos con * son obligatorios. El índice y los enlaces a modelos "
            "permiten navegar por el PDF."
        )
        generales = {
            k: v
            for k, v in self.esquema.items()
            if k not in {"openapi", "paths", "components", "tags"}
        }
        generales["info"] = {
            k: v
            for k, v in info.items()
            if k not in {"title", "version", "description"}
        }
        generales = {k: v for k, v in generales.items() if v}
        if generales:
            self.mostrar_json("Información general y configuración", generales)
        if componentes.get("securitySchemes"):
            self.mostrar_json(
                "Autenticación y esquemas de seguridad", componentes["securitySchemes"]
            )

        self.elementos.append(PageBreak())
        self.texto("Índice de recursos", "titulo")
        indice = TableOfContents()
        indice.levelStyles = [self.estilos["indice"]]
        indice.dotsMinLevel = 0
        self.elementos.append(indice)
        tags = {
            str(objeto(t).get("name")): objeto(t)
            for t in lista(self.esquema.get("tags"))
        }
        for grupo, operaciones in grupos.items():
            self.elementos.append(PageBreak())
            cantidad = len(operaciones)
            unidad = "operación" if cantidad == 1 else "operaciones"
            self.texto(f"{grupo} · {cantidad} {unidad}", "seccion")
            self.descripcion(tags.get(grupo, {}).get("description"))
            for ruta, metodo, operacion, compartidos in operaciones:
                campos = {
                    k: v
                    for k, v in compartidos.items()
                    if k.lower() not in METODOS_HTTP | {"parameters"}
                }
                if campos:
                    self.mostrar_json(f"Metadatos de {ruta}", campos)
                self.operacion(ruta, metodo, operacion, compartidos)
        if not grupos:
            self.texto("No hay endpoints declarados en la especificación.")

        self.elementos.append(PageBreak())
        self.texto(f"Modelos · {len(modelos)} esquemas", "seccion")
        for nombre_modelo, valor in modelos.items():
            datos = objeto(valor)
            self.elementos.append(
                Paragraph(
                    f'<a name="{destino_modelo(nombre_modelo)}"/>'
                    f"{escape(nombre_modelo)}",
                    self.estilos["subtitulo"],
                )
            )
            self.descripcion(datos.get("description"))
            requeridos = lista(datos.get("required"))
            filas: list[list[str | Paragraph]] = []
            for campo, propiedad in objeto(datos.get("properties")).items():
                filas.append(
                    [
                        campo + (" *" if campo in requeridos else ""),
                        self.modelo(propiedad),
                        self.detalle_esquema(propiedad),
                    ]
                )
            self.tabla(
                [
                    "Propiedad (* obligatoria)",
                    "Tipo / modelo",
                    "Descripción y restricciones",
                ],
                filas,
                [0.27, 0.25, 0.48],
            )
            extras = {
                k: v
                for k, v in datos.items()
                if k not in {"properties", "required", "description", "title", "type"}
            }
            if not filas:
                self.tabla(
                    ["Tipo / modelo", "Valores y restricciones"],
                    [[self.modelo(valor), self.detalle_esquema(valor)]],
                    [0.35, 0.65],
                )
            elif extras == {"additionalProperties": False}:
                self.texto("No admite propiedades adicionales.")
            elif extras:
                self.mostrar_json("Definición del esquema", extras)
        for tipo, definiciones in componentes.items():
            if tipo not in {"schemas", "securitySchemes"}:
                self.texto(tipo, "seccion")
                self.mostrar_json("Componentes reutilizables", definiciones)

        salida.parent.mkdir(parents=True, exist_ok=True)
        documento = DocumentoOpenAPI(
            str(salida),
            pagesize=A4,
            rightMargin=18 * mm,
            leftMargin=18 * mm,
            topMargin=21 * mm,
            bottomMargin=20 * mm,
            title=nombre,
            author="RescueSync · Documentación OpenAPI",
        )

        def decorar_pagina(lienzo: Canvas, documento: SimpleDocTemplate) -> None:
            lienzo.saveState()
            lienzo.setFillColor(VERDE)
            lienzo.rect(0, A4[1] - 4 * mm, A4[0], 4 * mm, fill=1, stroke=0)
            lienzo.setFont("Helvetica", 8)
            lienzo.setFillColor(GRIS)
            lienzo.drawString(18 * mm, A4[1] - 13 * mm, "RESCUESYNC / OPENAPI")
            lienzo.setStrokeColor(colors.HexColor("#dce3ec"))
            lienzo.line(18 * mm, 15 * mm, A4[0] - 18 * mm, 15 * mm)
            lienzo.drawString(18 * mm, 10 * mm, "Referencia de API")
            lienzo.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Página {documento.page}")
            lienzo.restoreState()

        documento.multiBuild(
            self.elementos, onFirstPage=decorar_pagina, onLaterPages=decorar_pagina
        )


def generar_pdf(esquema: ObjetoJSON, salida: Path = SALIDA_PREDETERMINADA) -> None:
    ExportadorPDF(esquema).construir(salida)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    fuentes = parser.add_mutually_exclusive_group()
    fuentes.add_argument("--url", help="URL OpenAPI alternativa al contrato local")
    fuentes.add_argument(
        "--archivo", type=Path, help="Archivo JSON OpenAPI alternativo"
    )
    parser.add_argument(
        "--salida",
        type=Path,
        default=SALIDA_PREDETERMINADA,
        help="Ruta alternativa del PDF",
    )
    args = parser.parse_args()
    try:
        esquema = obtener_openapi(args.url, args.archivo)
        generar_pdf(esquema, args.salida)
    except Exception as exc:
        print(f"Error al generar el PDF: {exc}", file=sys.stderr)
        return 1
    print(f"PDF generado: {args.salida.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
