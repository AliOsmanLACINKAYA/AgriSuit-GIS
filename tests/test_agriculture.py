"""End-to-end checks against the Compose PostGIS instance (synthetic vectors)."""
import json
import os
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from fastapi.testclient import TestClient
from psycopg2 import connect

from src.backend.main import app
from src.rs_pipeline.import_constraints import load_region


def square(x0, y0, x1, y1):
    return {"type": "Polygon",
            "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def write_geojson(path, records):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": geom, "properties": properties}
        for geom, properties in records
    ]}), encoding="utf-8")
    return path


class AgricultureIntegration(TestCase):
    def test_import_and_eligibility(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = Namespace(
                boundary=write_geojson(root / "area.geojson", [(square(27, 38, 28, 39), {})]),
                corine=write_geojson(root / "corine.geojson", [
                    (square(26.9, 38.1, 27.3, 38.4), {"Code_18": "112"}),
                    (square(27.5, 38.5, 27.6, 38.6), {"Code_18": "211"}),
                    (square(27.6, 38.7, 27.7, 38.8), {"Code_18": "311"}),
                    (square(27.7, 38.7, 27.8, 38.8), {"Code_18": "411"}),
                ]),
                osm=write_geojson(root / "osm.geojson", [
                    (square(27.2, 38.3, 27.4, 38.5), {"boundary": "protected_area"}),
                ]),
                region_code="TEST-AGRICULTURE", region_name="Synthetic region",
                region_type="study_area", corine_layer=None, osm_layer=None, corine_code="Code_18",
            )
            load_region(args)
            load_region(args)
        with connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cursor:
            cursor.execute("""
                SELECT array_agg(c.constraint_type ORDER BY c.constraint_type),
                       bool_and(ST_CoveredBy(c.geom, r.geom))
                FROM public.land_constraints c JOIN public.regions r ON r.id = c.region_id
                WHERE r.code = %s
            """, (args.region_code,))
            self.assertEqual(cursor.fetchone(), (["forest", "protected_area", "settlement", "wetland"], True))
            cursor.execute("""
                SELECT ST_IsValid(m.closed_geom), ST_IsValid(m.open_geom),
                       abs(ST_Area(m.closed_geom) + ST_Area(m.open_geom) - ST_Area(r.geom)) < 1e-8
                FROM public.agriculture_masks m JOIN public.regions r ON r.id = m.region_id
                WHERE r.code = %s
            """, (args.region_code,))
            self.assertEqual(cursor.fetchone(), (True, True, True))
            cursor.execute("""
                EXPLAIN (ANALYZE, TIMING OFF)
                SELECT public.agriculture_point_status(%s, 27.3, 38.4) FROM generate_series(1, 100)
            """, (args.region_code,))
            print("\n".join(row[0] for row in cursor.fetchall()))

        url = f"/regions/{args.region_code}/eligibility"
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            for lon, lat, status in [(27.1, 38.2, "closed"), (27.35, 38.45, "closed"),
                                     (27.65, 38.75, "closed"), (27.75, 38.75, "closed"),
                                     (27.55, 38.55, "open"), (28.1, 38.5, "outside_region")]:
                response = client.get(f"{url}/point", params={"lon": lon, "lat": lat})
                self.assertEqual(response.json(), {"status": status, "is_open": status == "open"})
            for geom, status in [(square(27.2, 38.25, 27.5, 38.35), "closed"),
                                 (square(27.5, 38.5, 27.6, 38.6), "open"),
                                 (square(27.9, 38.9, 28.1, 39.1), "outside_region")]:
                self.assertEqual(client.post(f"{url}/polygon", json=geom).json()["status"], status)
            invalid = {"type": "Polygon", "coordinates": [
                [[27.5, 38.5], [27.6, 38.6], [27.6, 38.5], [27.5, 38.6], [27.5, 38.5]]
            ]}
            self.assertEqual(client.post(f"{url}/polygon", json=invalid).status_code, 422)
            self.assertEqual(client.get("/regions/UNKNOWN/eligibility/point?lon=27&lat=38").status_code, 404)
            with connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE public.land_constraints SET valid_to = CURRENT_DATE - 1
                    WHERE region_id = (SELECT id FROM public.regions WHERE code = %s)
                """, (args.region_code,))
            self.assertEqual(client.get(f"{url}/point?lon=27.1&lat=38.2").status_code, 503)
            with connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cursor:
                cursor.execute("SELECT public.refresh_agriculture_mask(%s)", (args.region_code,))
            self.assertEqual(client.get(f"{url}/point?lon=27.1&lat=38.2").json()["status"], "open")
