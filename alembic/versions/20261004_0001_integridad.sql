-- Snapshot de integridad de 20261004_0001. No cambiar tras aplicar la revisión.

CREATE FUNCTION nacional_certificacion_completa() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    referencia uuid;
BEGIN
    IF TG_TABLE_NAME = 'certificacion' THEN
        referencia := NEW.id;
    ELSIF TG_OP = 'DELETE' THEN
        referencia := OLD.certificacion_id;
    ELSE
        referencia := NEW.certificacion_id;
    END IF;
    IF (EXISTS (SELECT 1 FROM certificacion WHERE id = referencia AND activa)
        OR EXISTS (SELECT 1 FROM ong_certificacion WHERE certificacion_id = referencia))
       AND NOT EXISTS (
           SELECT 1 FROM certificacion_capacidad WHERE certificacion_id = referencia
       ) THEN
        RAISE EXCEPTION 'Una certificacion activa requiere alcances'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_certificacion_con_alcances';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER ct_certificacion_completa
AFTER INSERT OR UPDATE ON certificacion DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION nacional_certificacion_completa();

CREATE CONSTRAINT TRIGGER ct_alcances_completos
AFTER INSERT OR UPDATE OR DELETE ON certificacion_capacidad
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION nacional_certificacion_completa();

CREATE FUNCTION nacional_proteger_alcance() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    referencia uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND
       ROW(NEW.certificacion_id, NEW.capacidad_id, NEW.creado_en) IS DISTINCT FROM
       ROW(OLD.certificacion_id, OLD.capacidad_id, OLD.creado_en) THEN
        RAISE EXCEPTION 'La identidad del alcance es inmutable'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_alcance_identidad';
    END IF;
    IF TG_OP = 'DELETE' THEN
        referencia := OLD.certificacion_id;
    ELSE
        referencia := NEW.certificacion_id;
        PERFORM 1 FROM capacidad WHERE id = NEW.capacidad_id FOR SHARE;
    END IF;
    -- El otorgamiento toma este mismo lock para serializar emisión y cambios.
    PERFORM 1 FROM certificacion WHERE id = referencia FOR UPDATE;
    IF EXISTS (SELECT 1 FROM ong_certificacion WHERE certificacion_id = referencia) THEN
        RAISE EXCEPTION 'Los alcances de una certificacion otorgada son inmutables'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_alcance_otorgado_inmutable';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_proteger_alcance
BEFORE INSERT OR UPDATE OR DELETE ON certificacion_capacidad
FOR EACH ROW EXECUTE FUNCTION nacional_proteger_alcance();

CREATE FUNCTION nacional_proteger_capacidad() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id OR
       (ROW(NEW.codigo, NEW.tipo, NEW.unidad, NEW.admite_fracciones) IS DISTINCT FROM
        ROW(OLD.codigo, OLD.tipo, OLD.unidad, OLD.admite_fracciones)
        AND (EXISTS (SELECT 1 FROM recurso WHERE capacidad_id = OLD.id)
             OR EXISTS (SELECT 1 FROM certificacion_capacidad WHERE capacidad_id = OLD.id))) THEN
        RAISE EXCEPTION 'La semantica de una capacidad referenciada es inmutable'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_capacidad_semantica_inmutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_proteger_capacidad BEFORE UPDATE ON capacidad
FOR EACH ROW EXECUTE FUNCTION nacional_proteger_capacidad();

CREATE FUNCTION nacional_proteger_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id OR
       (ROW(NEW.codigo, NEW.revision, NEW.creado_en) IS DISTINCT FROM
        ROW(OLD.codigo, OLD.revision, OLD.creado_en) AND
        EXISTS (SELECT 1 FROM ong_certificacion WHERE certificacion_id = OLD.id)) THEN
        RAISE EXCEPTION 'Una revision otorgada conserva su identidad'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_revision_otorgada_inmutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_proteger_revision BEFORE UPDATE ON certificacion
FOR EACH ROW EXECUTE FUNCTION nacional_proteger_revision();

CREATE FUNCTION nacional_cantidad_discreta() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    fraccionable boolean;
    valor numeric;
BEGIN
    IF TG_TABLE_NAME = 'recurso' THEN
        IF TG_OP = 'UPDATE' AND
           ROW(NEW.id, NEW.ong_id, NEW.capacidad_id, NEW.creado_en) IS DISTINCT FROM
           ROW(OLD.id, OLD.ong_id, OLD.capacidad_id, OLD.creado_en) THEN
            RAISE EXCEPTION 'El propietario y capacidad del recurso son inmutables'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_recurso_identidad';
        END IF;
        SELECT admite_fracciones INTO fraccionable FROM capacidad
            WHERE id = NEW.capacidad_id FOR SHARE;
        valor := NEW.cantidad_total;
    ELSE
        SELECT c.admite_fracciones INTO fraccionable
            FROM recurso r JOIN capacidad c ON c.id = r.capacidad_id
            WHERE r.id = NEW.recurso_id FOR SHARE OF c;
        valor := NEW.cantidad;
    END IF;
    IF fraccionable = false AND valor <> trunc(valor) THEN
        RAISE EXCEPTION 'Esta capacidad requiere cantidades enteras'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_cantidad_discreta';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_recurso_discreto BEFORE INSERT OR UPDATE ON recurso
FOR EACH ROW EXECUTE FUNCTION nacional_cantidad_discreta();
CREATE TRIGGER trg_item_discreto BEFORE INSERT ON compromiso_item
FOR EACH ROW EXECUTE FUNCTION nacional_cantidad_discreta();

CREATE FUNCTION nacional_validar_acreditacion() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    autor uuid;
BEGIN
    IF TG_OP = 'INSERT' THEN
        autor := NEW.registrada_por_id;
    ELSIF NEW.estado IS DISTINCT FROM OLD.estado THEN
        autor := NEW.revocada_por_id;
    ELSE
        RETURN NEW;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM cuenta WHERE id = autor AND rol = 'ADMIN_NACIONAL' AND activa
    ) THEN
        RAISE EXCEPTION 'Solo la administracion registra o revoca acreditaciones'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_acreditacion_autor_admin';
    END IF;
    PERFORM 1 FROM ong WHERE id = NEW.ong_id FOR UPDATE;
    PERFORM 1 FROM certificacion WHERE id = NEW.certificacion_id FOR UPDATE;
    IF TG_OP = 'INSERT' AND NOT EXISTS (
        SELECT 1 FROM certificacion WHERE id = NEW.certificacion_id AND activa
    ) THEN
        RAISE EXCEPTION 'La certificacion debe estar activa para otorgarse'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_acreditacion_catalogo_activo';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validar_acreditacion BEFORE INSERT OR UPDATE ON ong_certificacion
FOR EACH ROW EXECUTE FUNCTION nacional_validar_acreditacion();

CREATE FUNCTION nacional_compromiso_completo() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    actual compromiso%ROWTYPE;
BEGIN
    SELECT * INTO actual FROM compromiso WHERE id = NEW.id;
    IF NOT FOUND THEN RETURN NULL; END IF;
    IF NOT EXISTS (SELECT 1 FROM compromiso_item WHERE compromiso_id = actual.id) THEN
        RAISE EXCEPTION 'Un compromiso requiere items'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_compromiso_con_items';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM operacion_idempotente
        WHERE id = actual.operacion_creacion_id AND operacion = 'COMPROMETER'
    ) THEN
        RAISE EXCEPTION 'El compromiso requiere una operacion de creacion'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_compromiso_tipo_operacion';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER ct_compromiso_completo
AFTER INSERT OR UPDATE ON compromiso DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION nacional_compromiso_completo();

CREATE FUNCTION nacional_operacion_completa() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    actual operacion_idempotente%ROWTYPE;
BEGIN
    SELECT * INTO actual FROM operacion_idempotente WHERE id = NEW.id;
    IF NOT FOUND THEN RETURN NULL; END IF;
    IF actual.proyecto_id IS NULL OR actual.codigo_http IS NULL
       OR actual.respuesta_minima IS NULL THEN
        RAISE EXCEPTION 'No confirmar un reclamo idempotente incompleto'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_operacion_resultado_completo';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM cuenta WHERE id = actual.cuenta_id AND
        (rol = 'ADMIN_NACIONAL' OR
         (rol = 'INTEGRACION' AND sistema_origen_id = actual.sistema_origen_id))
    ) THEN
        RAISE EXCEPTION 'La cuenta no pertenece al emisor de la operacion'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_operacion_cuenta_emisor';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER ct_operacion_completa
AFTER INSERT OR UPDATE ON operacion_idempotente DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION nacional_operacion_completa();

CREATE FUNCTION nacional_proteger_historial() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Conservar el historial nacional mediante estados'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_historial_sin_borrado';
    END IF;
    IF TG_TABLE_NAME = 'compromiso_item' THEN
        RAISE EXCEPTION 'Los items adjudicados son inmutables'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_item_inmutable';
    ELSIF TG_TABLE_NAME = 'operacion_idempotente' THEN
        IF OLD.codigo_http IS NOT NULL OR
           ROW(NEW.id, NEW.sistema_origen_id, NEW.cuenta_id, NEW.operacion,
               NEW.clave, NEW.huella_sha256, NEW.creado_en) IS DISTINCT FROM
           ROW(OLD.id, OLD.sistema_origen_id, OLD.cuenta_id, OLD.operacion,
               OLD.clave, OLD.huella_sha256, OLD.creado_en) OR
           (OLD.proyecto_id IS NOT NULL AND NEW.proyecto_id IS DISTINCT FROM OLD.proyecto_id) THEN
            RAISE EXCEPTION 'La identidad y el resultado confirmado son inmutables'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_operacion_inmutable';
        END IF;
    ELSIF TG_TABLE_NAME = 'ong_certificacion' THEN
        IF OLD.estado = 'REVOCADA' OR
           ROW(NEW.id, NEW.ong_id, NEW.certificacion_id, NEW.emisor,
               NEW.numero_credencial, NEW.vigente_desde, NEW.vigente_hasta,
               NEW.registrada_por_id, NEW.creado_en) IS DISTINCT FROM
           ROW(OLD.id, OLD.ong_id, OLD.certificacion_id, OLD.emisor,
               OLD.numero_credencial, OLD.vigente_desde, OLD.vigente_hasta,
               OLD.registrada_por_id, OLD.creado_en) THEN
            RAISE EXCEPTION 'Renovar requiere otra acreditacion'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_acreditacion_inmutable';
        END IF;
    ELSIF TG_TABLE_NAME = 'compromiso' THEN
        IF ROW(NEW.id, NEW.proyecto_id, NEW.ong_id, NEW.operacion_creacion_id,
               NEW.adjudicacion_ref, NEW.creado_en) IS DISTINCT FROM
           ROW(OLD.id, OLD.proyecto_id, OLD.ong_id, OLD.operacion_creacion_id,
               OLD.adjudicacion_ref, OLD.creado_en) OR
           (OLD.estado = 'LIBERADO' AND
            ROW(NEW.estado, NEW.liberado_en, NEW.liberado_por_id) IS DISTINCT FROM
            ROW(OLD.estado, OLD.liberado_en, OLD.liberado_por_id)) THEN
            RAISE EXCEPTION 'El compromiso no puede reescribirse o reactivarse'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_compromiso_inmutable';
        END IF;
    ELSIF TG_TABLE_NAME = 'proyecto' THEN
        IF ROW(NEW.id, NEW.sistema_origen_id, NEW.emergencia_ref, NEW.case_ref, NEW.creado_en)
           IS DISTINCT FROM
           ROW(OLD.id, OLD.sistema_origen_id, OLD.emergencia_ref, OLD.case_ref, OLD.creado_en)
           OR (OLD.estado = 'TERMINADO' AND
               ROW(NEW.estado, NEW.cerrado_en, NEW.cerrado_por_id) IS DISTINCT FROM
               ROW(OLD.estado, OLD.cerrado_en, OLD.cerrado_por_id)) THEN
            RAISE EXCEPTION 'El proyecto conserva su identidad y cierre terminal'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_proyecto_inmutable';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_historial_item BEFORE UPDATE OR DELETE ON compromiso_item
FOR EACH ROW EXECUTE FUNCTION nacional_proteger_historial();
CREATE TRIGGER trg_historial_operacion BEFORE UPDATE OR DELETE ON operacion_idempotente
FOR EACH ROW EXECUTE FUNCTION nacional_proteger_historial();
CREATE TRIGGER trg_historial_acreditacion BEFORE UPDATE OR DELETE ON ong_certificacion
FOR EACH ROW EXECUTE FUNCTION nacional_proteger_historial();
CREATE TRIGGER trg_historial_compromiso BEFORE UPDATE OR DELETE ON compromiso
FOR EACH ROW EXECUTE FUNCTION nacional_proteger_historial();
CREATE TRIGGER trg_historial_proyecto BEFORE UPDATE OR DELETE ON proyecto
FOR EACH ROW EXECUTE FUNCTION nacional_proteger_historial();
