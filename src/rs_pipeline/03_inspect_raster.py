import rasterio
import numpy as np

BAND_NAMES = [
    "1. Elevation_m (Rakim)",
    "2. Slope_deg (Egim)",
    "3. Aspect_deg (Baki)",
    "4. Annual_Temp_C (Yillik Sicaklik)",
    "5. Annual_Precip_mm (Yillik Yagis)",
    "6. NDVI_Winter (Kis NDVI)",
    "7. NDVI_Spring (Ilkbahar NDVI)",
    "8. NDVI_Summer (Yaz NDVI)",
    "9. NDMI_Summer (Yaz Nem Indeksi)",
    "10. LST_Summer_C (Yaz Yuzey Sicakligi)"
]

with rasterio.open("data/sample/manisa_preview_500m.tif") as src:
    print(f"CRS (Koordinat Sistemi): {src.crs}")
    print(f"Boyut (Yukseklik x Genislik): {src.height} x {src.width} piksel")
    print(f"Toplam Bant Sayisi: {src.count}\n")
    print(f"{'Bant Adi':<38} | {'Min':>8} | {'Ortalama':>8} | {'Max':>8}")
    print("-" * 72)

    for idx, name in enumerate(BAND_NAMES, start=1):
        band = src.read(idx)
        valid = band[(band > -9000) & (~np.isnan(band))]
        if valid.size > 0:
            print(f"{name:<38} | {valid.min():>8.2f} | {valid.mean():>8.2f} | {valid.max():>8.2f}")