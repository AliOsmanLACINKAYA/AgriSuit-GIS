\set ON_ERROR_STOP on
BEGIN;

DO $$
DECLARE
    region_key bigint;
    prediction_key bigint;
    old_updated_at timestamptz;
    footprint geometry := ST_Multi(ST_GeomFromText('POLYGON((27 38,28 38,28 39,27 39,27 38))', 4326));
BEGIN
    INSERT INTO public.regions (code, name, region_type, geom)
    VALUES ('TEST-45', 'Test region', 'province', footprint) RETURNING id INTO region_key;

    INSERT INTO public.land_constraints (region_id, constraint_type, name, source, geom)
    VALUES (region_key, 'protected_area', 'Test exclusion', 'Synthetic test fixture', footprint);

    INSERT INTO public.crop_predictions
        (region_id, crop_type, prediction_year, model_version, run_id, suitability_score, geom)
    VALUES (region_key, 'wheat', 2026, 'test-v1', '00000000-0000-0000-0000-000000000001', 0.85, footprint)
    RETURNING id, updated_at INTO prediction_key, old_updated_at;

    IF NOT EXISTS (SELECT 1 FROM public.crop_predictions p JOIN public.land_constraints c
                   ON p.region_id = c.region_id AND ST_Intersects(p.geom, c.geom)
                   WHERE p.id = prediction_key) THEN
        RAISE EXCEPTION 'Spatial join failed';
    END IF;

    UPDATE public.crop_predictions SET confidence = 0.9 WHERE id = prediction_key;
    IF (SELECT updated_at FROM public.crop_predictions WHERE id = prediction_key) <= old_updated_at THEN
        RAISE EXCEPTION 'Timestamp trigger failed';
    END IF;

    BEGIN
        UPDATE public.crop_predictions SET suitability_score = 1.1 WHERE id = prediction_key;
        RAISE EXCEPTION 'Out-of-range score accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        UPDATE public.crop_predictions SET region_id = -1 WHERE id = prediction_key;
        RAISE EXCEPTION 'Missing region accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        UPDATE public.regions SET geom = ST_GeomFromText('MULTIPOLYGON EMPTY', 4326) WHERE id = region_key;
        RAISE EXCEPTION 'Empty geometry accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        UPDATE public.regions SET geom = ST_Multi(ST_GeomFromText('POLYGON((27 38,28 39,28 38,27 39,27 38))', 4326)) WHERE id = region_key;
        RAISE EXCEPTION 'Invalid geometry accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        UPDATE public.land_constraints SET valid_from = '2026-12-31', valid_to = '2026-01-01' WHERE region_id = region_key;
        RAISE EXCEPTION 'Reversed validity dates accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        DELETE FROM public.regions WHERE id = region_key;
        RAISE EXCEPTION 'Referenced region deleted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
END;
$$;

ROLLBACK;
