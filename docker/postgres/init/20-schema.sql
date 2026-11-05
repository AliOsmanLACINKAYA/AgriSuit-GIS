BEGIN;

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE public.regions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE CHECK (btrim(code) <> ''),
    name text NOT NULL CHECK (btrim(name) <> ''),
    region_type text NOT NULL CHECK (region_type IN ('province', 'district', 'study_area')),
    parent_id bigint REFERENCES public.regions(id) ON DELETE RESTRICT,
    geom geometry(MultiPolygon, 4326) NOT NULL,
    properties jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(properties) = 'object'),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT regions_not_self_parent CHECK (parent_id IS DISTINCT FROM id),
    CONSTRAINT regions_valid_geom CHECK (NOT ST_IsEmpty(geom) AND ST_IsValid(geom))
);

CREATE TABLE public.land_constraints (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    region_id bigint NOT NULL REFERENCES public.regions(id) ON DELETE RESTRICT,
    constraint_type text NOT NULL CHECK (btrim(constraint_type) <> ''),
    name text NOT NULL CHECK (btrim(name) <> ''),
    source text NOT NULL CHECK (btrim(source) <> ''),
    is_exclusion boolean NOT NULL DEFAULT true,
    severity numeric(5,4) NOT NULL DEFAULT 1 CHECK (severity BETWEEN 0 AND 1),
    valid_from date,
    valid_to date,
    geom geometry(MultiPolygon, 4326) NOT NULL,
    properties jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(properties) = 'object'),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT land_constraints_dates CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CONSTRAINT land_constraints_valid_geom CHECK (NOT ST_IsEmpty(geom) AND ST_IsValid(geom))
);

CREATE TABLE public.crop_predictions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    region_id bigint NOT NULL REFERENCES public.regions(id) ON DELETE RESTRICT,
    crop_type text NOT NULL CHECK (btrim(crop_type) <> ''),
    prediction_year smallint NOT NULL CHECK (prediction_year BETWEEN 1900 AND 2200),
    model_version text NOT NULL CHECK (btrim(model_version) <> ''),
    run_id uuid NOT NULL,
    suitability_score numeric(5,4) NOT NULL CHECK (suitability_score BETWEEN 0 AND 1),
    confidence numeric(5,4) CHECK (confidence BETWEEN 0 AND 1),
    geom geometry(MultiPolygon, 4326) NOT NULL,
    properties jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(properties) = 'object'),
    predicted_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT crop_predictions_valid_geom CHECK (NOT ST_IsEmpty(geom) AND ST_IsValid(geom))
);

CREATE INDEX regions_geom_idx ON public.regions USING gist (geom);
CREATE INDEX regions_parent_idx ON public.regions (parent_id);
CREATE INDEX land_constraints_geom_idx ON public.land_constraints USING gist (geom);
CREATE INDEX land_constraints_region_type_idx ON public.land_constraints (region_id, constraint_type);
CREATE INDEX crop_predictions_geom_idx ON public.crop_predictions USING gist (geom);
CREATE INDEX crop_predictions_region_crop_year_idx ON public.crop_predictions (region_id, crop_type, prediction_year);
CREATE INDEX crop_predictions_run_idx ON public.crop_predictions (run_id);

CREATE FUNCTION public.set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = clock_timestamp();
    RETURN NEW;
END;
$$;

CREATE TRIGGER regions_updated_at BEFORE UPDATE ON public.regions
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER land_constraints_updated_at BEFORE UPDATE ON public.land_constraints
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER crop_predictions_updated_at BEFORE UPDATE ON public.crop_predictions
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

COMMENT ON COLUMN public.crop_predictions.geom IS 'Prediction cell or parcel footprint; WGS84 longitude/latitude.';
COMMENT ON COLUMN public.crop_predictions.suitability_score IS 'Normalized suitability: 0 unsuitable, 1 most suitable.';
COMMENT ON COLUMN public.crop_predictions.run_id IS 'Shared UUID for all footprints produced by one model execution.';
COMMENT ON COLUMN public.land_constraints.severity IS 'Normalized constraint strength: 0 none, 1 maximum.';

COMMIT;
