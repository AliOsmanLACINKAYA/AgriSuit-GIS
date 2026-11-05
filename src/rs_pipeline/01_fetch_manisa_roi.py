import os
import ee
import requests

# Kendi Google Cloud / Earth Engine Project ID'nizi buraya yazın
GEE_PROJECT_ID = "agrisuit-gis"

def init_gee():
    try:
        ee.Initialize(project=GEE_PROJECT_ID)
        print(f"[OK] Google Earth Engine basariyla baslatildi ({GEE_PROJECT_ID}).")
    except Exception as e:
        print("[BILGI] Yetkilendirme gerekiyor, tarayici aciliyor...")
        ee.Authenticate()
        ee.Initialize(project=GEE_PROJECT_ID)

def download_manisa_boundaries():
    os.makedirs("data/sample", exist_ok=True)

    # 1. Manisa İl Sınırı (ADM1)
    admin1 = ee.FeatureCollection("FAO/GAUL/2015/level1")
    manisa_prov = admin1.filter(
        ee.Filter.And(
            ee.Filter.eq("ADM0_NAME", "Turkey"),
            ee.Filter.eq("ADM1_NAME", "Manisa")
        )
    )

    prov_url = manisa_prov.getDownloadURL(filetype="geojson", filename="manisa_boundary")
    r_prov = requests.get(prov_url, timeout=60)
    prov_path = "data/sample/manisa_boundary.geojson"
    with open(prov_path, "wb") as f:
        f.write(r_prov.content)
    print(f"[OK] Manisa il siniri kaydedildi: {prov_path}")

    # 2. Manisa İlçe Sınırları (ADM2)
    admin2 = ee.FeatureCollection("FAO/GAUL/2015/level2")
    manisa_districts = admin2.filter(
        ee.Filter.And(
            ee.Filter.eq("ADM0_NAME", "Turkey"),
            ee.Filter.eq("ADM1_NAME", "Manisa")
        )
    )

    dist_url = manisa_districts.getDownloadURL(filetype="geojson", filename="manisa_districts")
    r_dist = requests.get(dist_url, timeout=60)
    dist_path = "data/sample/manisa_districts.geojson"
    with open(dist_path, "wb") as f:
        f.write(r_dist.content)
    print(f"[OK] Manisa ilce sinirlari kaydedildi: {dist_path}")

if __name__ == "__main__":
    init_gee()
    download_manisa_boundaries()