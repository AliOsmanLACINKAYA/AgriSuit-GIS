# AgriSuit-GIS
The AgriSuit-GIS Project

## Yerel CBS altyapısı

Gereksinim: Docker Engine / Docker Desktop (Linux containers) ve Docker Compose v2.
PowerShell ile proje klasöründe:

```powershell
Copy-Item .env.example .env
# .env içindeki iki boş parola alanına farklı, güçlü parolalar yazın.
docker compose config --quiet
docker compose up -d --wait --wait-timeout 480
docker compose ps
```

Parola alanları boşsa Compose başlamaz. `.env` Git tarafından yok sayılır.
İmajlar: PostgreSQL 17 / PostGIS 3.6 ve GeoServer 2.28.2.
Servis portları yalnızca yerel bilgisayara açılır; port çakışmasında `.env`
içindeki `POSTGRES_PORT` / `GEOSERVER_PORT` değerlerini değiştirin.

GeoServer: http://localhost:8080/geoserver (kullanıcı ve parola `.env` içindedir).
PostgreSQL: `localhost:5432`, varsayılan veritabanı/kullanıcı: `agrisuit`.
Konteynerler arasındaki veritabanı adresi `postgis:5432` olarak kullanılır.

### GeoServer PostGIS bağlantısı

GeoServer arayüzünden bir `agrisuit` workspace oluşturun. **Stores → Add new
Store → PostGIS** ile aşağıdaki değerleri girin:

| Alan | Değer |
| --- | --- |
| Workspace | agrisuit |
| Data Source Name | agrisuit_postgis |
| host | postgis |
| port | 5432 |
| database | .env içindeki POSTGRES_DB (varsayılan agrisuit) |
| schema | public |
| user / passwd | .env içindeki POSTGRES_USER / POSTGRES_PASSWORD |
| Expose primary keys | true |

Kaydedip `regions`, `land_constraints`, `crop_predictions` tablolarını
**Publish** ile yayınlayın; SRS `EPSG:4326` seçin. Bounding box hesaplaması
için önce veri yükleyin. Store ve katman kurulumu bu ilk sürümde manueldir.
Yerel geliştirme hesabı veritabanı sahibidir; herkese açık bir kurulumda
GeoServer için yalnızca SELECT yetkili ayrı bir hesap kullanın.

### Veritabanı tasarımı

Şema: [20-schema.sql](docker/postgres/init/20-schema.sql).

| Tablo | Amaç | Temel alanlar |
| --- | --- | --- |
| regions | İl, ilçe veya çalışma alanı sınırları | code (benzersiz), name, region_type, parent_id, geom |
| land_constraints | Koruma alanları ve arazi kullanım kısıtları | region_id, constraint_type, source, is_exclusion, severity, valid_from/to, geom |
| crop_predictions | Bir model çalışmasının parsel/hücre bazlı ürün uygunluğu | region_id, crop_type, prediction_year, model_version, run_id, suitability_score, confidence, geom |

Tüm geometriler geçerli ve boş olmayan `MultiPolygon`, SRID 4326 (boylam/enlem)
olmalıdır. Polygon içe aktarımında `ST_Multi`, farklı projeksiyonda
`ST_Transform(..., 4326)` kullanın. Alan hesabını derece cinsinden yapmayın;
metrekare için `ST_Area(geom::geography)` kullanın.

Skorlar 0–1 aralığındadır. `crop_type` serbest ürün kodudur (ör. `wheat`,
`grape`, `olive`); `run_id` uygulamanın ürettiği UUID olup aynı çalışmadaki
tüm hücrelerde paylaşılır. Aynı ürün/yıl için farklı model çalışmaları
saklanabilir. Her tabloda ek metadata için JSON nesnesi `properties`,
oluşturulma ve otomatik güncellenme zamanı bulunur.

Foreign key'ler bölgenin ilişkili kayıtları varken silinmesini engeller.
Geometriler GiST, bölge/ürün/yıl ve ilişki alanları B-tree indekslidir.
`parent_id` hiyerarşisinde çok adımlı döngüleri ve geometrilerin bölge
sınırları içinde kalmasını veri yükleyen uygulama doğrulamalıdır.

### Doğrulama ve veri kalıcılığı

```powershell
Get-Content docker/postgres/tests/schema.sql -Raw | docker compose exec -T postgis psql -U agrisuit -d agrisuit -v ON_ERROR_STOP=1
docker compose logs --tail 100
docker compose stop
docker compose start
```

Test, örnek kayıtlar ve mekânsal join ile şemayı; hatalı skor, geometri,
tarih, foreign key ve güncelleme zamanını doğrular. Sonunda `ROLLBACK`
yapar; örnek kayıtlar saklanmaz. Kullanıcı/veritabanı adını değiştirdiyseniz
test komutundaki `-U` ve `-d` değerlerini de değiştirin.
GitHub Actions aynı testi temiz volume üzerinde çalıştırır ve GeoServer
REST kimlik doğrulamasını kontrol eder.

`docker compose down` konteynerleri kaldırır; PostgreSQL ve GeoServer
verileri named volume'larda kalır. `docker compose down -v` **tüm yerel
verileri siler**. Başlangıç SQL dosyaları yalnızca boş veritabanı volume'u
oluşturulurken çalışır; mevcut veritabanına değişiklikler ayrı migration
olarak uygulanmalıdır. `.env` kullanıcı/parolasını değiştirmek mevcut
PostgreSQL hesabını değiştirmez. GeoServer başlangıçta `.env` yönetici
bilgilerini uygular; kullanıcı yönetimi arayüzden değiştirilecekse sonraki
açılışta üzerine yazılmaması için Compose ortam ayarlarını da düzenleyin.

İmaj belgeleri: [PostGIS](https://github.com/postgis/docker-postgis),
[GeoServer](https://github.com/geoserver/docker).

## Manisa: rasterlar, tarıma kapalı alanlar ve sorgu API'si

Python 3.12 ile `python -m pip install -r requirements-pipeline.txt` çalıştırın.
Yalnızca API gerekiyorsa `requirements-api.txt` yeterli.

### Raster üretimi

Earth Engine'e erişimi etkin bir Google Cloud projesi ve yetkili bir hesap gerekir.
Bir kez `earthengine authenticate` çalıştırıp aşağıdaki komutta kendi proje adınızı yazın:

```powershell
python -m src.rs_pipeline.export_rasters --project PROJE_KIMLIGI --boundary data/sample/manisa_boundary.geojson --end-year 2025 --years 3
```

Komut Google Drive `AgriSuit-GIS` klasörüne GeoTIFF işlerini gönderir ve iş
kimliklerini yazdırır. Sonuçları Earth Engine Tasks ekranından takip edin.
`--years` 3–5 yıl seçer; `--season-only` aylık dosyaları atlar. Tüm katmanlar
aynı AOI'ye kırpılır, 30 m EPSG:32635 gridine oturur, NoData değeri `-9999` olur.
Başka çalışma alanları için `--crs` ile metre birimli bir projeksiyon seçin.

| Çıktı | Bantlar / yöntem |
| --- | --- |
| `terrain` | SRTM DEM'den yükseklik (m), eğim (°), bakı (°) |
| `era5_land_YIL` | Yıllık ortalama 2 m sıcaklık (°C), günlük minimumun 0 °C altına düştüğü gün sayısı, toplam yağış (mm); tam takvim yılı |
| `landsat_YIL_apr_sep` ve `landsat_YIL_AY` | Landsat 8/9 Nisan–Eylül veya aylık medyan: kırmızı, NIR, SWIR1, NDVI, NDMI, LST (°C), bant bazında geçerli gözlem sayıları |

ERA5-Land sıcaklık ve yağışta bilinear, don günü sayısında en yakın komşu
örneklemesi kullanılır. Yaklaşık 11 km iklim verisini 30 m gride yazmak yeni
mekânsal ayrıntı üretmez. Landsat bulut, gölge, kar ve doygun pikselleri eler;
gözlem olmayan yerler ve termal veri boşlukları NoData kalır.
Kaynaklar: [SRTM](https://developers.google.com/earth-engine/datasets/catalog/USGS_SRTMGL1_003),
[ERA5-Land](https://developers.google.com/earth-engine/datasets/catalog/ECMWF_ERA5_LAND_DAILY_AGGR),
[Landsat 8](https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LC08_C02_T1_L2),
[Landsat 9](https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LC09_C02_T1_L2).

### Vektör içe aktarma ve maske

Yeni bir Compose volume'unda şema ilk başlatmada kurulur. Var olan volume'u
silmeden yükseltmek için, aşağıdaki kullanıcı/veritabanı adlarını gerekirse değiştirin:

```powershell
Get-Content docker/postgres/init/30-agriculture.sql -Raw | docker compose exec -T postgis psql -U agrisuit -d agrisuit -v ON_ERROR_STOP=1
```

Çalışma alanını kapsayan [CORINE](https://land.copernicus.eu/en/products/corine-land-cover)
ve [OpenStreetMap](https://www.openstreetmap.org/copyright) poligon dosyalarını
`data/raw` altına koyun. GeoPackage/GeoJSON gibi CRS bilgili vektör dosyaları
kullanılabilir. `--corine-layer`, `--osm-layer` ve `--corine-code` ile katman/sütun
seçilebilir. CORINE varsayılan kod sütunu `Code_18`; OSM'de `landuse`, `natural`,
`wetland`, `boundary`, `leisure` etiketleri varsa ayrı sütunlar olarak dışa aktarılmalıdır.

```powershell
$env:DATABASE_URL = 'postgresql://agrisuit:PAROLA@127.0.0.1:5432/agrisuit'
python -m src.rs_pipeline.import_constraints --boundary data/sample/manisa_boundary.geojson --region-code TR-45 --region-name Manisa --region-type province --corine data/raw/corine.gpkg --osm data/raw/osm.geojson
python -m uvicorn src.backend.main:app
```

Bağlantı adresindeki `PAROLA` ve portu `.env` ayarlarınıza göre değiştirin;
paroladaki URL özel karakterlerini yüzde kodlayın. İçe aktarma bölge sınırını
ve o bölge için önceki CORINE/OSM kayıtlarını tek işlemde değiştirir. Yerleşim
ve diğer yapay yüzeyler, ormanlar, sulak alanlar, su ve koruma alanları
bölgeye kırpılır ve `land_constraints` tablosuna yazılır. `ST_Union` kapalı
maskeyi, `ST_Difference` ise bölgenin kalan kısmını üretir. GeoServer'da
`agriculture_masks` tablosunu yayınlarken `closed_geom` veya `open_geom`
alanını katmanın geometrisi olarak seçin (gerekirse SQL View kullanın).

Maske değişiklikte geçersizleşir; tarihli kısıtlar için günlük yenileme gerekir:
`SELECT public.refresh_agriculture_mask('TR-45');`. Eksik veya eski maske
API'de 503 döner. Kaynakların çalışma alanını kapsadığını kontrol edin.
Sonuç, bu girdilere göre tarıma açıklık ön değerlendirmesidir; ürün uygunluğu
skoru veya resmî imar/koruma kararı değildir.

### Nokta ve poligon sorguları

FastAPI: [Swagger](http://127.0.0.1:8000/docs). Koordinat sırası **boylam, enlem**.

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/regions/TR-45/eligibility/point?lon=27.43&lat=38.61'
$body = '{"type":"Polygon","coordinates":[[[27.43,38.61],[27.44,38.61],[27.44,38.62],[27.43,38.62],[27.43,38.61]]]}'
Invoke-RestMethod 'http://127.0.0.1:8000/regions/TR-45/eligibility/polygon' -Method Post -ContentType application/json -Body $body
```

SQL karşılıkları: `agriculture_point_status(kod, boylam, enlem)` ve
`agriculture_status(kod, EPSG_4326_geometri)`. Sorgu girdinin tamamının bölge
içinde kalmasını ister; kapalı alana temas eden poligonu da kapalı sayar.
Sorgu sırasında maske yeniden hesaplanmaz; bölünmüş maskede GiST indeksli
`ST_Intersects` uygulanır. Gecikme geometri boyutuna ve veriye bağlıdır.
GitHub Actions sentetik CORINE/OSM dosyalarıyla içe aktarma, maske, SQL ve
API'yi gerçek PostGIS'te doğrular ve 100 nokta sorgusunun süresini raporlar.
