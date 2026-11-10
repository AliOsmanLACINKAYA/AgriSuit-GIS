"""Validate real Earth Engine client graphs without cloud credentials."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import ee
from ee.apitestcase import ApiTestCase

from src.rs_pipeline import export_rasters as raster


class RasterGraphTest(ApiTestCase):
    def test_manisa_exports_and_incomplete_year(self):
        roi = raster.read_boundary(Path("data/sample/manisa_boundary.geojson"))
        with patch.object(ee.Number, "getInfo", return_value=365):
            climate = raster.climate(roi, 2025)
            with self.assertRaisesRegex(ValueError, "365/366 days"):
                raster.climate(roi, 2024)
        season = raster.season_collection(roi, 2025)
        april = season.filterDate("2025-04-01", "2025-05-01")
        self.assertIn("system:time_start", april.serialize())
        args = SimpleNamespace(crs="EPSG:32635", resolution=30, folder="test")
        for image in (raster.terrain(), climate, raster.composite(season),
                      raster.composite(april), raster.composite(ee.ImageCollection([]))):
            with patch.object(ee.batch.Task, "start"):
                task = raster.export(image, "test", roi, args)
            options = task.config["fileExportOptions"]
            self.assertEqual(options["fileFormat"], "GEO_TIFF")
            self.assertEqual(options["geoTiffOptions"]["noData"]["floatValue"], -9999)
            graph = task.config["expression"].serialize()
            self.assertIn("EPSG:32635", graph)
            self.assertIn("Image.clip", graph)
