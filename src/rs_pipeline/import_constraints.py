"""Replace a region's CORINE/OSM exclusions and build its agricultural mask."""
import argparse
import os
from pathlib import Path

import geopandas as gpd
import pyogrio
from psycopg2 import Binary, connect
from psycopg2.extras import Json, execute_values
from shapely import force_2d, make_valid, union_all
from shapely.geometry import MultiPolygon


def polygonal(geometry):
    if geometry is None or geometry.is_empty:
        return MultiPolygon()
    geometry = make_valid(force_2d(geometry))

    def polygons(item):
        if item.geom_type == "Polygon":
            yield item
        elif item.geom_type in {"GeometryCollection", "MultiPolygon"}:
            for part in item.geoms:
                yield from polygons(part)

    merged = union_all(list(polygons(geometry)))
    if merged.is_empty:
        return MultiPolygon()
    return MultiPolygon([merged]) if merged.geom_type == "Polygon" else merged


def corine_category(value):
    code = str(value).strip().removesuffix(".0")
    if len(code) != 3 or not code.isdecimal():
        return None
    if code.startswith("1"):
        return "settlement"
    if code in {"311", "312", "313"}:
        return "forest"
    if code.startswith("4"):
        return "wetland"
    if code.startswith("5"):
        return "water"
    return None


def osm_categories(tags):
    categories = []
    if tags.get("landuse") in {"residential", "commercial", "industrial", "retail"}:
        categories.append("settlement")
    if tags.get("landuse") == "forest" or tags.get("natural") == "wood":
        categories.append("forest")
    if tags.get("natural") == "wetland" or tags.get("wetland") in {
        "marsh", "swamp", "bog", "reedbed", "saltmarsh", "wet_meadow", "tidalflat",
    }:
        categories.append("wetland")
    if tags.get("boundary") in {"protected_area", "national_park"} or tags.get("leisure") == "nature_reserve":
        categories.append("protected_area")
    if tags.get("natural") == "water":
        categories.append("water")
    return categories


def read_polygons(path, layer, area):
    info = pyogrio.read_info(path, layer=layer)
    if not info["crs"]:
        raise ValueError(f"{path} has no declared CRS")
    bbox = tuple(gpd.GeoSeries([area], crs=4326).to_crs(info["crs"]).total_bounds)
    return pyogrio.read_dataframe(path, layer=layer, bbox=bbox).to_crs(4326)


def source_rows(frame, area, dataset, source_label, code_column):
    if dataset == "CORINE" and code_column not in frame.columns:
        raise ValueError(f"CORINE class column {code_column!r} not found")
    osm_columns = {"landuse", "natural", "wetland", "boundary", "leisure"}
    if dataset == "OSM" and not osm_columns.intersection(frame.columns):
        raise ValueError("OSM input must expose tags as attribute columns")
    for _, item in frame.iterrows():
        if dataset == "CORINE":
            category = corine_category(item[code_column])
            categories = [category] if category else []
        else:
            categories = osm_categories(item)
        if not categories:
            continue
        clipped = polygonal(polygonal(item[frame.geometry.name]).intersection(area))
        if not clipped.is_empty:
            name = item.get("name")
            for category in categories:
                yield (category, name if isinstance(name, str) and name.strip() else category,
                       source_label, Binary(clipped.wkb), Json({"import_dataset": dataset}))


def load_region(args):
    region = gpd.read_file(args.boundary)
    if region.crs is None:
        raise ValueError("Boundary must declare its CRS")
    area = polygonal(union_all([polygonal(g) for g in region.to_crs(4326).geometry]))
    if area.is_empty:
        raise ValueError("Boundary has no polygonal area")
    corine = read_polygons(args.corine, args.corine_layer, area)
    osm = read_polygons(args.osm, args.osm_layer, area)
    rows = []
    for dataset, frame, path in (("CORINE", corine, args.corine), ("OSM", osm, args.osm)):
        rows.extend(source_rows(frame, area, dataset, f"{dataset}: {Path(path).name}", args.corine_code))

    with connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cursor:
        cursor.execute("LOCK TABLE public.land_constraints IN SHARE ROW EXCLUSIVE MODE")
        cursor.execute("""
            INSERT INTO public.regions (code, name, region_type, geom)
            VALUES (%s, %s, %s, ST_GeomFromWKB(%s, 4326))
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name,
                region_type = EXCLUDED.region_type, geom = EXCLUDED.geom
            RETURNING id
        """, (args.region_code, args.region_name, args.region_type, Binary(area.wkb)))
        region_id = cursor.fetchone()[0]
        cursor.execute("""
            DELETE FROM public.land_constraints WHERE region_id = %s
            AND properties->>'import_dataset' IN ('CORINE', 'OSM')
        """, (region_id,))
        execute_values(cursor, """
            INSERT INTO public.land_constraints
            (region_id, constraint_type, name, source, geom, properties) VALUES %s
        """, [(region_id, *row) for row in rows],
            template="(%s,%s,%s,%s,ST_GeomFromWKB(%s, 4326),%s)", page_size=500)
        cursor.execute("SELECT public.refresh_agriculture_mask(%s)", (args.region_code,))
    print(f"{args.region_code}: imported {len(rows)} exclusions and refreshed mask")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boundary", required=True)
    parser.add_argument("--region-code", required=True)
    parser.add_argument("--region-name", required=True)
    parser.add_argument("--region-type", default="study_area",
                        choices=["study_area", "district", "province"])
    parser.add_argument("--corine", required=True)
    parser.add_argument("--corine-layer")
    parser.add_argument("--corine-code", default="Code_18")
    parser.add_argument("--osm", required=True)
    parser.add_argument("--osm-layer")
    load_region(parser.parse_args())


if __name__ == "__main__":
    main()
