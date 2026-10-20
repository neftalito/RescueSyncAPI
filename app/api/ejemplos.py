"""Ejemplos ficticios correlacionados; no contienen credenciales utilizables.

Los IDs locales y nacionales son independientes. El snapshot coincide con la
fixture T34 y las cantidades nacionales se transportan como strings decimales.
"""

ONG_ID = "00000000-0000-4000-8000-000000000101"
CAPACIDAD_ID = "00000000-0000-4000-8000-000000000102"
RECURSO_ID = "00000000-0000-4000-8000-000000000103"
CUENTA_ID = "00000000-0000-4000-8000-000000000104"
PROYECTO_ID = "00000000-0000-4000-8000-000000000105"
COMPROMISO_ID = "00000000-0000-4000-8000-000000000106"
OPERACION_ID = "00000000-0000-4000-8000-000000000107"
FECHA = "2026-10-14T18:01:00Z"

LOGIN = {
    "identificadorLogin": "ong@example.org",
    "password": "Ejemplo-no-utilizable-123",
}
TOKEN = {
    "access_token": "JWT_DE_EJEMPLO_NO_UTILIZABLE",
    "token_type": "bearer",
    "expires_in": 1800,
}
CUENTA = {"id": CUENTA_ID, "rol": "ONG", "ongId": ONG_ID, "proposito": "PERSONAL"}
ALTA_ONG = {
    **LOGIN,
    "nombre": "Rescate de ejemplo",
    "identificadorInstitucional": "ong-ejemplo",
    "emailContacto": "ong@example.org",
}
ONG = {"id": ONG_ID, "nombre": "Rescate de ejemplo", "estado": "HABILITADA"}
UNIDADES = [{"codigo": "persona", "nombre": "Personas"}]
ALTA_CAPACIDAD = {
    "codigo": "ATENCION",
    "nombre": "Atención prehospitalaria",
    "tipo": "PERSONAL",
    "unidad": "persona",
    "admiteFracciones": False,
}
CAPACIDAD = {"id": CAPACIDAD_ID, **ALTA_CAPACIDAD}
ALTA_RECURSO = {
    "capacidadId": CAPACIDAD_ID,
    "codigoInterno": "PARAM-01",
    "nombre": "Paramédicos sede 1",
    "cantidadTotal": "10.000",
}
EDICION_RECURSO = {"cantidadTotal": "12.000", "actualizadoEn": FECHA}
RECURSO = {
    "id": RECURSO_ID,
    "ongId": ONG_ID,
    **ALTA_RECURSO,
    "capacidad": "ATENCION",
    "unidad": "persona",
    "admiteFracciones": False,
    "cantidadComprometida": "0.000",
    "cantidadDisponible": "10.000",
    "activo": True,
    "actualizadoEn": FECHA,
}
RECURSO_EDITADO = {
    **RECURSO,
    "cantidadTotal": "12.000",
    "cantidadDisponible": "12.000",
    "actualizadoEn": "2026-10-14T18:02:00Z",
}
CANTIDADES = {
    "cantidadTotal": "10.000",
    "cantidadComprometida": "0.000",
    "cantidadDisponible": "10.000",
}
DISPONIBILIDAD = {
    "consultadoEn": FECHA,
    "recursos": [
        {
            "capacidadId": CAPACIDAD_ID,
            **ALTA_CAPACIDAD,
            **CANTIDADES,
            "ongs": [
                {
                    "ongId": ONG_ID,
                    "nombre": "Rescate de ejemplo",
                    "estadoOng": "HABILITADA",
                    **CANTIDADES,
                }
            ],
        }
    ],
}
PERFIL_COMPETENCIA = {
    "ongId": ONG_ID,
    "nombre": "ONG de ejemplo",
    "estadoOng": "HABILITADA",
    "evaluadoEn": FECHA,
    "capacidadesDeclaradas": [
        {
            "capacidadId": CAPACIDAD_ID,
            "codigo": "ATENCION",
            "nombre": "Atención prehospitalaria",
            "tipo": "PERSONAL",
            "unidad": "persona",
            "admiteFracciones": False,
            "cantidadTotal": "10.000",
            "cantidadComprometida": "0.000",
            "cantidadDisponible": "10.000",
        }
    ],
}
DIRECTORIO_ONGS = {"evaluadoEn": FECHA, "ongs": [PERFIL_COMPETENCIA]}
SNAPSHOT_CERRADO = {
    "contratoVersion": 2,
    "sistemaOrigen": "instalacion-prueba",
    "idEmergencia": 101,
    "caseId": "100",
    "convocatoriaId": 20,
    "numero": 1,
    "gravedad": "ALTA",
    "cerradaEn": "2026-10-14T18:00:00Z",
    "lotesCubiertos": True,
    "referenciasNacionalesCompletas": True,
    "motivosIntegracion": [],
    "lotes": [
        {
            "loteId": 40,
            "tipoNecesidad": "Paramédicos",
            "cantidadPublicada": 6,
            "cantidadOfrecida": 6,
            "cantidadPublicadaExacta": "6.000",
            "cantidadOfrecidaExacta": "6.000",
            "unidad": "persona",
            "cubierto": True,
            "capacidadNacionalId": CAPACIDAD_ID,
            "codigoCapacidad": "ATENCION",
            "riesgoRequerido": "MEDIA",
        }
    ],
    "ofertas": [
        {
            "ofertaId": 30,
            "ongId": 1,
            "ongNacionalId": ONG_ID,
            "estado": "PRESENTADA",
            "version": 1,
            "presentadaEn": "2026-10-14T17:00:00Z",
            "referenciasNacionalesCompletas": True,
            "motivosIntegracion": [],
            "participantes": [
                {
                    "ongId": 1,
                    "ongNacionalId": ONG_ID,
                    "rol": "LIDER",
                }
            ],
            "items": [
                {
                    "itemId": 41,
                    "loteId": 40,
                    "tipo": "PERSONAL",
                    "descripcion": "Paramédicos sede 1",
                    "cantidadOfrecida": 6,
                    "cantidadOfrecidaExacta": "6.000",
                    "unidad": "persona",
                    "aportes": [
                        {
                            "aporteId": 50,
                            "ongId": 1,
                            "ongNacionalId": ONG_ID,
                            "recursoNacionalId": RECURSO_ID,
                            "capacidadNacionalId": CAPACIDAD_ID,
                            "cantidad": "6.000",
                            "unidad": "persona",
                        }
                    ],
                }
            ],
        }
    ],
}

VALIDACION = {
    "contratoVersion": 3,
    "sistemaOrigen": "instalacion-prueba",
    "idEmergencia": 101,
    "caseId": "100",
    "convocatoriaId": 20,
    "numero": 1,
    "evaluadoEn": FECHA,
    "aportes": [
        {
            "ofertaId": 30,
            "version": 1,
            "itemId": 41,
            "loteId": 40,
            "aporteId": 50,
            "ongId": 1,
            "ongNacionalId": ONG_ID,
            "recursoNacionalId": RECURSO_ID,
            "cantidadOfrecida": "6.000",
            "unidad": "persona",
            "perfilCompetencia": PERFIL_COMPETENCIA,
            "cantidadDisponibleConsultada": "10.000",
            "motivos": [],
        }
    ],
    "recursosConsultados": [
        {
            "recursoNacionalId": RECURSO_ID,
            "ongNacionalId": ONG_ID,
            "capacidadNacionalId": CAPACIDAD_ID,
            "unidad": "persona",
            "cantidadDisponible": "10.000",
            "cantidadSolicitadaSnapshot": "6.000",
        }
    ],
}
APORTE = {
    "ofertaId": "30",
    "version": 1,
    "loteId": "40",
    "aporteId": "50",
    "ongNacionalId": ONG_ID,
    "recursoNacionalId": RECURSO_ID,
    "capacidadNacionalId": CAPACIDAD_ID,
    "riesgoRequerido": "MEDIA",
    "cantidad": "6.000",
    "unidad": "persona",
}
ADJUDICACION = {
    "sistemaOrigen": "instalacion-prueba",
    "idEmergencia": "101",
    "caseId": "100",
    "convocatoriaId": "20",
    "adjudicacionId": "seleccion-101-1",
    "aportes": [APORTE],
}
CONFIRMACION = {
    "operacionId": OPERACION_ID,
    "proyectoId": PROYECTO_ID,
    "compromisoIds": [COMPROMISO_ID],
    "registradoEn": FECHA,
}
COMPROMISO = {
    "id": COMPROMISO_ID,
    "proyectoId": PROYECTO_ID,
    "sistemaOrigen": "instalacion-prueba",
    "idEmergencia": "101",
    "caseId": "100",
    "adjudicacionId": "seleccion-101-1",
    "ongNacionalId": ONG_ID,
    "estado": "LIBERADO",
    "creadoEn": FECHA,
    "liberadoEn": "2026-10-14T19:00:00Z",
    "liberadoPorId": "00000000-0000-4000-8000-000000000114",
    "items": [
        {"id": "00000000-0000-4000-8000-000000000110", "convocatoriaId": "20", **APORTE}
    ],
}
FINALIZACION = {"caseId": "100"}
LIBERACION = {
    "operacionId": "00000000-0000-4000-8000-000000000111",
    "proyectoId": PROYECTO_ID,
    "compromisoId": COMPROMISO_ID,
    "ongNacionalId": ONG_ID,
    "liberadoEn": "2026-10-14T19:00:00Z",
}
CIERRE = {
    "operacionId": "00000000-0000-4000-8000-000000000112",
    "proyectoId": PROYECTO_ID,
    "cerradoEn": "2026-10-14T19:01:00Z",
}
APROVISIONAMIENTO = {
    "nombre": "Rescate de ejemplo",
    "emailContacto": "ong@example.org",
    "password": "SECRETO-FICTICIO-DE-EJEMPLO-32-CARACTERES",
}
ONG_APROVISIONADA = {
    "ong": ONG,
    "cuentaId": CUENTA_ID,
    "identificadorLogin": "ong-ejemplo-generado-por-el-emisor",
}
HEALTH = {"status": "ok", "service": "national-api"}
