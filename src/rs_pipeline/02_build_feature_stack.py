import os
import ee
import requests

GEE_PROJECT_ID = "agrisuit-gis"

def init_gee():
    ee.Initialize(project=GEE_PROJECT_ID)

def get_manisa_roi():
    admin1 = ee.FeatureCollection("FAO/GAUL/2015/level1")
    return admin1.filter(
        ee.Filter.And(
            ee.Filter.eq("ADM0_NAME", "Turkey"),
            ee.Filter.eq("ADM1_NAME", "Manisa")
        )
    ).geometry()

def mask_landsat_sr(image):
    """Landsat 8/9 Collection 2 Level 2 bulut maskelemesi ve ölçeklendirme."""
    qa = image.select("QA_PIXEL")
    mask = qa.bitwiseAnd(1 << 4).eq(0).And(qa.bitwiseAnd(1 << 3).eq(0))

    optical = image.select("SR_B.*").multiply(0.0000275).add(-0.2)
    thermal_c = (
        image.select("ST_B10")
        .multiply(0.00341802)
        .add(149.0)
        .subtract(273.15)
        .rename("LST_C")
    )
    return image.addBands(optical, None, True).addBands(thermal_c).updateMask(mask)

def create_manisa_stack(roi):
    # 1. Topografik Analiz (SRTM 30m)
    dem = ee.Image("USGS/SRTMGL1_003").clip(roi).rename("Elevation_m")
    terrain = ee.Terrain.products(dem)
    slope = terrain.select("slope").rename("Slope_deg")
    aspect = terrain.select("aspect").rename("Aspect_deg")

    # 2. İklimsel Parametreler (WorldClim BIO)
    bioclim = ee.Image("WORLDCLIM/V1/BIO").clip(roi)
    annual_temp = bioclim.select("bio01").multiply(0.1).rename("Annual_Temp_C")
    annual_precip = bioclim.select("bio12").rename("Annual_Precip_mm")

    # 3. Zamansal Landsat 8/9 Analizi (2023-2025)
    l8_l9 = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        .merge(ee.ImageCollection("LANDSAT/LC09/C02/T1_L2"))
        .filterBounds(roi)
        .filterDate("2023-01-01", "2025-12-31")
        .map(mask_landsat_sr)
    )

    def add_spectral_indices(img):
        ndvi = img.normalizedDifference(["SR_B5", "SR_B4"]).rename("NDVI")
        ndmi = img.normalizedDifference(["SR_B5", "SR_B6"]).rename("NDMI")
        return img.addBands([ndvi, ndmi])

    col = l8_l9.map(add_spectral_indices)

    # 5 Ürünü (Buğday, Üzüm, Zeytin, Ayçiçeği, Nohut) ayıran mevsimsel medyanlar
    ndvi_winter = col.filter(ee.Filter.calendarRange(1, 2, "month")).select("NDVI").median().rename("NDVI_Winter")
    ndvi_spring = col.filter(ee.Filter.calendarRange(4, 5, "month")).select("NDVI").median().rename("NDVI_Spring")
    ndvi_summer = col.filter(ee.Filter.calendarRange(7, 8, "month")).select("NDVI").median().rename("NDVI_Summer")
    ndmi_summer = col.filter(ee.Filter.calendarRange(7, 8, "month")).select("NDMI").median().rename("NDMI_Summer")
    lst_summer = col.filter(ee.Filter.calendarRange(7, 8, "month")).select("LST_C").median().rename("LST_Summer_C")

    stack = (
        ee.Image.cat([
            dem, slope, aspect,
            annual_temp, annual_precip,
            ndvi_winter, ndvi_spring, ndvi_summer,
            ndmi_summer, lst_summer
        ])
        .clip(roi)
        .unmask(-9999)
        .toFloat()
    )
    return stack

def download_preview_geotiff(stack, roi):
    """Doğrudan yerel diske 500m çözünürlüklü hızlı test GeoTIFF'i indirir."""
    os.makedirs("data/sample", exist_ok=True)
    print("[BILGI] Manisa 10 bantli onizleme GeoTIFF'i indiriliyor (yaklasik 15-30 sn)...")
    url = stack.getDownloadURL({
        "name": "manisa_preview_500m",
        "scale": 500,
        "crs": "EPSG:4326",
        "region": roi,
        "format": "GEO_TIFF"
    })
    resp = requests.get(url, timeout=180)
    out_path = "data/sample/manisa_preview_500m.tif"
    with open(out_path, "wb") as f:
        f.write(resp.content)
    print(f"[OK] Cok bantli GeoTIFF kaydedildi: {out_path}")

if __name__ == "__main__":
    init_gee()
    manisa_roi = get_manisa_roi()
    feature_stack = create_manisa_stack(manisa_roi)
    print("[OK] Bant Listesi:", feature_stack.bandNames().getInfo())
    download_preview_geotiff(feature_stack, manisa_roi)