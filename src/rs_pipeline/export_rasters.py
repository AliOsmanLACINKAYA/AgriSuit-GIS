"""Export terrain, annual ERA5-Land and Landsat composites on a shared grid."""
import argparse
import calendar
import json
from datetime import date
from pathlib import Path

import ee

LANDSAT_BANDS = ["red", "nir", "swir1", "ndvi", "ndmi", "lst_c"]
CLIMATE_BANDS = ["temperature_2m", "temperature_2m_min", "total_precipitation_sum"]
NODATA = -9999


def read_boundary(path):
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document["type"] == "FeatureCollection":
        geometries = [f["geometry"] for f in document["features"]]
    elif document["type"] == "Feature":
        geometries = [document["geometry"]]
    else:
        geometries = [document]
    if not geometries or any(g is None or g["type"] not in {"Polygon", "MultiPolygon"}
                            for g in geometries):
        raise ValueError("Provide a WGS84 polygon, multipolygon or polygon feature collection")
    return ee.FeatureCollection([ee.Feature(ee.Geometry(g, geodesic=False)) for g in geometries]).geometry()


def terrain():
    return ee.Terrain.products(ee.Image("USGS/SRTMGL1_003")).select(
        ["elevation", "slope", "aspect"], ["elevation_m", "slope_deg", "aspect_deg"]
    )


def climate(roi, year):
    start, end = f"{year}-01-01", f"{year + 1}-01-01"
    daily = ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR").filterDate(start, end)
    expected = 366 if calendar.isleap(year) else 365
    available = daily.size().getInfo()
    if available != expected:
        raise ValueError(f"ERA5-Land {year}: {available}/{expected} days; use complete years")
    projection = ee.Image(daily.first()).select("temperature_2m").projection()
    complete = daily.select(CLIMATE_BANDS).count().reduce(ee.Reducer.min()).eq(expected)
    temperature = (daily.select("temperature_2m").mean().subtract(273.15)
                   .rename("annual_mean_temp_c").setDefaultProjection(projection).resample("bilinear"))
    frost = daily.map(lambda image: image.select("temperature_2m_min").lt(273.15)).sum()
    frost = frost.rename("frost_days").setDefaultProjection(projection)
    precipitation = daily.map(
        lambda image: image.select("total_precipitation_sum").max(0)
    ).sum().multiply(1000).rename("annual_precip_mm")
    precipitation = precipitation.setDefaultProjection(projection).resample("bilinear")
    return temperature.addBands([frost, precipitation]).updateMask(complete).clip(roi)


def landsat_scene(image):
    # Fill, dilated cloud, cirrus, cloud, shadow and snow.
    clear = image.select("QA_PIXEL").bitwiseAnd(63).eq(0).And(image.select("QA_RADSAT").eq(0))
    optical = (image.select(["SR_B4", "SR_B5", "SR_B6"], ["red", "nir", "swir1"])
               .multiply(0.0000275).add(-0.2))

    def index(a, b, name):
        first, second = optical.select(a), optical.select(b)
        denom = first.add(second)
        return first.subtract(second).divide(denom).updateMask(
            denom.gt(0).And(first.gte(0)).And(second.gte(0))
        ).rename(name)

    # ST_B10 is fully masked in L2SR scenes. Keep their optical observations.
    lst = image.select("ST_B10").multiply(0.00341802).add(149).subtract(273.15).rename("lst_c")
    lst = lst.updateMask(image.select("ST_QA").lte(300)).updateMask(image.select("ST_CDIST").gte(100))
    return optical.addBands([index("nir", "red", "ndvi"), index("nir", "swir1", "ndmi"), lst]).updateMask(clear)


def season_collection(roi, year):
    return (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
            .merge(ee.ImageCollection("LANDSAT/LC09/C02/T1_L2"))
            .filterBounds(roi).filterDate(f"{year}-04-01", f"{year}-10-01").map(landsat_scene))


def composite(collection):
    # A masked fallback preserves band names even in windows without scenes.
    empty = ee.Image.constant([0] * len(LANDSAT_BANDS)).rename(LANDSAT_BANDS).toFloat()
    scenes = collection.merge(ee.ImageCollection([empty.updateMask(ee.Image.constant(0))]))
    counts = scenes.select(["nir", "ndvi", "ndmi", "lst_c"]).count().unmask(0).rename(
        ["optical_observations", "ndvi_observations", "ndmi_observations", "lst_observations"]
    )
    return scenes.median().addBands(counts)


def export(image, name, roi, args):
    image = image.toFloat().clip(roi).unmask(NODATA, sameFootprint=False)
    task = ee.batch.Export.image.toDrive(
        image=image, description=name, fileNamePrefix=name, folder=args.folder,
        region=roi, crs=args.crs, crsTransform=[args.resolution, 0, 0, 0, -args.resolution, 0],
        maxPixels=1e10, fileFormat="GeoTIFF",
        formatOptions={"cloudOptimized": True, "noData": NODATA},
    )
    task.start()
    print(f"{name}: {task.id}", flush=True)
    return task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Earth Engine-enabled Google Cloud project")
    parser.add_argument("--boundary", required=True)
    parser.add_argument("--crs", default="EPSG:32635", help="Metric CRS; default UTM 35N for Manisa")
    parser.add_argument("--resolution", type=float, default=30)
    parser.add_argument("--end-year", type=int, default=date.today().year - 1)
    parser.add_argument("--years", type=int, choices=[3, 4, 5], default=3)
    parser.add_argument("--folder", default="AgriSuit-GIS")
    parser.add_argument("--season-only", action="store_true", help="Skip monthly composites")
    args = parser.parse_args()
    if not 0 < args.resolution <= 1000 or not 2014 <= args.end_year - args.years + 1 <= args.end_year < date.today().year:
        parser.error("Use a positive metric resolution up to 1000 m and full Landsat 8 years since 2014")
    ee.Initialize(project=args.project)
    roi = read_boundary(args.boundary)
    years = range(args.end_year - args.years + 1, args.end_year + 1)
    # Check climate coverage before submitting any exports.
    climate_by_year = {year: climate(roi, year) for year in years}
    export(terrain(), "terrain", roi, args)
    for year in years:
        export(climate_by_year[year], f"era5_land_{year}", roi, args)
        scenes = season_collection(roi, year)
        export(composite(scenes), f"landsat_{year}_apr_sep", roi, args)
        if not args.season_only:
            for month in range(4, 10):
                subset = scenes.filterDate(f"{year}-{month:02}-01", f"{year}-{month + 1:02}-01")
                export(composite(subset), f"landsat_{year}_{month:02}", roi, args)


if __name__ == "__main__":
    main()
