BEGIN;

CREATE TABLE public.agriculture_masks (
    region_id bigint PRIMARY KEY REFERENCES public.regions(id) ON DELETE CASCADE,
    closed_geom geometry(MultiPolygon, 4326) NOT NULL,
    open_geom geometry(MultiPolygon, 4326) NOT NULL,
    as_of date NOT NULL
);

CREATE TABLE public.agriculture_closed_parts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    region_id bigint NOT NULL REFERENCES public.agriculture_masks(region_id) ON DELETE CASCADE,
    geom geometry(Polygon, 4326) NOT NULL
);
CREATE INDEX agriculture_closed_parts_geom_idx ON public.agriculture_closed_parts USING gist (geom);
CREATE INDEX agriculture_closed_parts_region_idx ON public.agriculture_closed_parts (region_id);

CREATE FUNCTION public.invalidate_agriculture_mask() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'regions' THEN
        DELETE FROM public.agriculture_masks WHERE region_id = NEW.id;
    ELSE
        IF TG_OP <> 'INSERT' THEN
            DELETE FROM public.agriculture_masks WHERE region_id = OLD.region_id;
        END IF;
        IF TG_OP <> 'DELETE' THEN
            DELETE FROM public.agriculture_masks WHERE region_id = NEW.region_id;
        END IF;
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER agriculture_region_invalidate AFTER UPDATE OF geom ON public.regions
FOR EACH ROW EXECUTE FUNCTION public.invalidate_agriculture_mask();
CREATE TRIGGER agriculture_constraint_invalidate AFTER INSERT OR UPDATE OR DELETE ON public.land_constraints
FOR EACH ROW EXECUTE FUNCTION public.invalidate_agriculture_mask();

CREATE FUNCTION public.refresh_agriculture_mask(target_code text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    region_key bigint;
    boundary geometry;
    closed geometry;
    empty_multipolygon geometry := ST_GeomFromText('MULTIPOLYGON EMPTY', 4326);
BEGIN
    LOCK TABLE public.land_constraints IN SHARE ROW EXCLUSIVE MODE;
    SELECT id, geom INTO STRICT region_key, boundary
    FROM public.regions WHERE code = target_code FOR NO KEY UPDATE;

    SELECT COALESCE(
        ST_Multi(ST_CollectionExtract(ST_Union(ST_Intersection(c.geom, boundary)), 3)),
        empty_multipolygon
    ) INTO closed
    FROM public.land_constraints c
    WHERE c.region_id = region_key AND c.is_exclusion
        AND (c.valid_from IS NULL OR c.valid_from <= CURRENT_DATE)
        AND (c.valid_to IS NULL OR c.valid_to >= CURRENT_DATE)
        AND ST_Intersects(c.geom, boundary);

    DELETE FROM public.agriculture_masks WHERE region_id = region_key;
    INSERT INTO public.agriculture_masks (region_id, closed_geom, open_geom, as_of)
    VALUES (region_key, closed,
        ST_Multi(ST_CollectionExtract(ST_Difference(boundary, closed), 3)), CURRENT_DATE);

    INSERT INTO public.agriculture_closed_parts (region_id, geom)
    SELECT region_key, part.geom
    FROM ST_Dump(closed) AS polygon
    CROSS JOIN LATERAL ST_Subdivide(polygon.geom, 256) AS part(geom);
END;
$$;

CREATE FUNCTION public.agriculture_status(target_code text, target geometry) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE
    region_key bigint;
    boundary geometry;
    mask_date date;
BEGIN
    IF target IS NULL OR ST_IsEmpty(target) OR ST_SRID(target) <> 4326
        OR ST_NDims(target) <> 2 OR GeometryType(target) NOT IN ('POINT', 'POLYGON', 'MULTIPOLYGON')
        OR NOT ST_IsValid(target)
        OR NOT ST_CoveredBy(target, ST_MakeEnvelope(-180, -90, 180, 90, 4326)) THEN
        RETURN 'invalid_geometry';
    END IF;

    SELECT r.id, r.geom, m.as_of INTO region_key, boundary, mask_date
    FROM public.regions r LEFT JOIN public.agriculture_masks m ON m.region_id = r.id
    WHERE r.code = target_code;

    IF NOT FOUND THEN RETURN 'unknown_region'; END IF;
    IF NOT ST_Covers(boundary, target) THEN RETURN 'outside_region'; END IF;
    IF mask_date IS DISTINCT FROM CURRENT_DATE THEN RETURN 'mask_unavailable'; END IF;
    IF EXISTS (
        SELECT 1 FROM public.agriculture_closed_parts c
        WHERE c.region_id = region_key AND ST_Intersects(c.geom, target)
    ) THEN RETURN 'closed'; END IF;
    RETURN 'open';
END;
$$;

CREATE FUNCTION public.agriculture_point_status(target_code text, lon double precision, lat double precision)
RETURNS text LANGUAGE sql STABLE AS $$
    SELECT public.agriculture_status(target_code, ST_SetSRID(ST_MakePoint(lon, lat), 4326));
$$;

COMMIT;
