# AgriSuit-GIS
Manisa için tarıma kapalı alanları belirlemek ve ürün uygunluğu çalışmalarına
girdi hazırlamak üzere bir CBS altyapısı kurdum. Arazi, iklim ve uydu katmanları
için raster üretim akışını; vektör veriler için PostGIS maskesini ve sorgu
API’sini hazırladım.

## İlk çalışma ve örnek veriler

Çalışma alanı olarak Manisa’yı seçtim. Earth Engine’den Manisa il sınırını
ve ilçe sınırlarını GeoJSON olarak aldım. İl sınırını sonraki raster ve
vektör işlemlerinde çalışma alanı olarak kullanıyorum:
[il sınırı](data/sample/manisa_boundary.geojson) ve
[ilçe sınırları](data/sample/manisa_districts.geojson).

İlk uzaktan algılama çalışmasından depoda
[500 m çözünürlüklü Manisa önizlemesi](data/sample/manisa_preview_500m.tif)
bulunuyor. Bu dosyanın 435 × 300 piksel ve 10 bant olduğunu kontrol ettim.
Yükseklik, eğim, bakı, yıllık sıcaklık ve yağış, üç mevsim için NDVI ve
yaz dönemi için NDMI ile yüzey sıcaklığı içeriyor. Önizlemenin bant
istatistiklerine `python src/rs_pipeline/03_inspect_raster.py` ile bakıyorum
(`rasterio` ve `numpy` gerekiyor). Bu dosya ilk çalışmanın örneği; aşağıdaki
30 m üretim akışının yıllık ve aylık çıktıları ayrı dosyalar.

## Yerel CBS altyapısı

PostgreSQL/PostGIS ve GeoServer’ı Docker Compose ile ayağa kaldıracak şekilde
yapılandırdım. Yerel kurulum için Docker Engine veya Docker Desktop
(Linux konteynerleri) ve Docker Compose v2 gerekiyor. PowerShell’de proje
klasöründen başlatma adımlarım şöyle:

```powershell
Copy-Item .env.example .env
# .env içindeki iki boş parola alanını farklı, güçlü parolalarla dolduruyorum.
docker compose config --quiet
docker compose up -d --wait --wait-timeout 480
docker compose ps
```

Parola alanları boşsa Compose başlamaz. `.env` Git tarafından yok sayılır.
İmajlar: PostgreSQL 17 / PostGIS 3.6 ve GeoServer 2.28.2.
Servis portlarını yalnızca yerel bilgisayara açtım. Port çakışması olduğunda
`.env` içindeki `POSTGRES_PORT` veya `GEOSERVER_PORT` değerini değiştiriyorum.

GeoServer: http://localhost:8080/geoserver (kullanıcı ve parola `.env` içindedir).
PostgreSQL: `localhost:5432`, varsayılan veritabanı/kullanıcı: `agrisuit`.
Konteynerler arasındaki veritabanı adresi `postgis:5432` olarak kullanılır.

### GeoServer PostGIS bağlantısı

GeoServer bağlantısını manuel bıraktım. Bağlantı adımı, arayüzde
`agrisuit` workspace’ini oluşturup **Stores → Add new Store → PostGIS**
altına şu ayarları girmekten oluşuyor:

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

Bağlantı kaydedilip veri yüklendikten sonra `regions`, `land_constraints`
ve `crop_predictions` tabloları **Publish** ile `EPSG:4326` katmanları
olarak yayımlanabiliyor. Bu, kurulum adımı; Manisa katmanlarını henüz
yayımlamadım.
Yerel geliştirme hesabı veritabanı sahibi. Herkese açık bir kurulum için
GeoServer’a yalnızca `SELECT` yetkili ayrı bir hesap ayırırım.

### Veritabanı tasarımı

Şema: [20-schema.sql](docker/postgres/init/20-schema.sql).

| Tablo | Amaç | Temel alanlar |
| --- | --- | --- |
| regions | İl, ilçe veya çalışma alanı sınırları | code (benzersiz), name, region_type, parent_id, geom |
| land_constraints | Koruma alanları ve arazi kullanım kısıtları | region_id, constraint_type, source, is_exclusion, severity, valid_from/to, geom |
| crop_predictions | Bir model çalışmasının parsel/hücre bazlı ürün uygunluğu | region_id, crop_type, prediction_year, model_version, run_id, suitability_score, confidence, geom |

Geometrileri geçerli ve boş olmayan `MultiPolygon` olarak, SRID 4326
(boylam/enlem) ile saklıyorum. Poligon içe aktarımında `ST_Multi`, farklı bir
projeksiyondan dönüştürürken `ST_Transform(..., 4326)` kullanıyorum. Alanı
metrekare cinsinden hesaplamak için `ST_Area(geom::geography)` kullanıyorum.

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
yapar; örnek kayıtlar saklanmaz. Test komutundaki `-U` ve `-d`, yerel
veritabanı kullanıcı ve veritabanı adlarıyla eşleşmeli.
GitHub Actions aynı testi temiz volume üzerinde çalıştırır ve GeoServer
REST kimlik doğrulamasını kontrol eder.

`docker compose down` konteynerleri kaldırır; PostgreSQL ve GeoServer
verileri named volume'larda kalır. `docker compose down -v` **tüm yerel
verileri siler**. Başlangıç SQL dosyaları yalnızca boş veritabanı volume'u
oluşturulurken çalışır; mevcut veritabanına değişiklikler ayrı migration
olarak uygulanmalıdır. `.env` kullanıcı/parolasını değiştirmek mevcut
PostgreSQL hesabını değiştirmez. GeoServer başlangıçta `.env` yönetici
bilgilerini uygular; kullanıcı yönetimi arayüzden değiştirilecekse sonraki
açılışta üzerine yazılmaması için Compose ortam ayarlarının da güncellenmesi
gerekiyor.

İmaj belgeleri: [PostGIS](https://github.com/postgis/docker-postgis),
[GeoServer](https://github.com/geoserver/docker).

## Manisa: rasterlar, tarıma kapalı alanlar ve sorgu API'si

Bağımlılıkları Python 3.12 ortamına `python -m pip install -r requirements-pipeline.txt`
ile kuruyorum. Yalnızca API için `requirements-api.txt` yeterli.

### Çalışmanın durumu

PostgreSQL/PostGIS ve GeoServer’ın Docker ile başladığını, veritabanı şemasını
ve GeoServer REST girişini GitHub Actions üzerinde doğruladım. Bu kontrolü
yerel bilgisayarda değil, Actions’ın test ortamında yaptım. Raster üretim
grafiklerini çevrimdışı test ettim. Sentetik CORINE/OSM verileriyle içe
aktarım, kapalı/açık alan maskesi ve FastAPI nokta/poligon sorgularını gerçek
PostGIS üzerinde sınadım; [testler geçti](https://github.com/AliOsmanLACINKAYA/AgriSuit-GIS/actions/runs/42924965232).
Bu test verisinde 100 nokta sorgusu SQL tarafında toplam yaklaşık 2,58 ms sürdü.

Manisa’nın gerçek CORINE ve OSM dosyalarını yerelde `data/raw` altına
indirdim. İl sınırıyla kesişen 5.552 CORINE ve 3.838 OSM poligonu buldum.
Bu ham dosyalar Git’e dahil değil. Gerçek veriyle iki işim kaldı:

- Çalışan bir PostGIS örneğinde CORINE ve OSM dosyalarını içe aktarıp
  Manisa maskesini üretmek; nokta ve poligon sonuçlarını ve sorgu sürelerini
  bu maske üzerinde ölçmek.
- Earth Engine hesabını yetkilendirip Manisa’nın gerçek 30 m SRTM, ERA5-Land
  ve Landsat 8/9 GeoTIFF’lerini üretmek ve dosyaları kontrol etmek.

### Raster üretimi

Raster üretimi için Earth Engine erişimi etkin bir Google Cloud projesi ve
yetkili bir hesap gerekiyor. Hazırladığım akışın ilk adımı
`earthengine authenticate` ile oturum açmak; ardından aşağıdaki komutta
`PROJE_KIMLIGI` yerine yetkili projenin kimliği geliyor:

```powershell
python -m src.rs_pipeline.export_rasters --project PROJE_KIMLIGI --boundary data/sample/manisa_boundary.geojson --end-year 2025 --years 3
```

Komut Google Drive `AgriSuit-GIS` klasörüne GeoTIFF işlerini gönderir ve iş
kimliklerini yazdırır. Bu kimliklerle sonuçları Earth Engine Tasks ekranından
takip edebilirim.
`--years` 3–5 yıl seçer; `--season-only` aylık dosyaları atlar. Tüm katmanlar
aynı AOI'ye kırpılır, 30 m EPSG:32635 gridine oturur, NoData değeri `-9999` olur.
Başka çalışma alanlarında `--crs` ile metre birimli bir projeksiyon seçiyorum.

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

Yeni bir Compose volume’unda şema ilk başlatmada kurulur. Mevcut volume’u
silmeden yükseltmek için aşağıdaki komutu kullanıyorum. Komuttaki kullanıcı
ve veritabanı adları kurulumla eşleşmeli:

```powershell
Get-Content docker/postgres/init/30-agriculture.sql -Raw | docker compose exec -T postgis psql -U agrisuit -d agrisuit -v ON_ERROR_STOP=1
```

Çalışma alanını kapsayan [CORINE](https://land.copernicus.eu/en/products/corine-land-cover)
ve [OpenStreetMap](https://www.openstreetmap.org/copyright) poligon dosyalarını
`data/raw` altında tutuyorum. İçe aktarıcı GeoPackage ve GeoJSON gibi CRS
bilgili vektör dosyalarını destekliyor. `--corine-layer`, `--osm-layer` ve
`--corine-code` ile katman ve sütun seçilebiliyor. CORINE varsayılan kod
sütunu `Code_18`; OSM'de `landuse`, `natural`,
`wetland`, `boundary`, `leisure` etiketleri varsa ayrı sütunlar olarak dışa aktarılmalıdır.

```powershell
$env:DATABASE_URL = 'postgresql://agrisuit:PAROLA@127.0.0.1:5432/agrisuit'
python -m src.rs_pipeline.import_constraints --boundary data/sample/manisa_boundary.geojson --region-code TR-45 --region-name Manisa --region-type province --corine data/raw/corine_manisa.geojson --osm data/raw/osm_manisa.geojson
python -m uvicorn src.backend.main:app
```

Bağlantı adresindeki `PAROLA` ve portu `.env` ayarlarına göre belirliyorum;
paroladaki URL özel karakterlerini yüzde kodluyorum. İçe aktarma bölge sınırını
ve o bölge için önceki CORINE/OSM kayıtlarını tek işlemde değiştirir. Yerleşim
ve diğer yapay yüzeyler, ormanlar, sulak alanlar, su ve koruma alanları
bölgeye kırpılır ve `land_constraints` tablosuna yazılır. `ST_Union` kapalı
maskeyi, `ST_Difference` ise bölgenin kalan kısmını üretir. GeoServer'da
`agriculture_masks` tablosu, gerçek maske üretildikten sonra
`closed_geom` veya `open_geom` alanıyla yayımlanabiliyor. İki ayrı katman
gerektiğinde her geometri için ayrı bir SQL View tanımlanabilir.

Maske bölge geometrisi veya kısıt kayıtları değiştiğinde geçersizleşir.
Sorgular yalnızca bugünün maskesini kabul ettiği için günlük yenileme gerekir:
`SELECT public.refresh_agriculture_mask('TR-45');`. Eksik veya eski maske
API'de 503 döner. İçe aktarıcı bölgeyle kesişmeyen CORINE girdisini veya bölge
içindeki geçersiz CORINE sınıf kodlarını reddeder. Kaynakların çalışma alanını
kapsayıp kapsamadığını ayrıca kontrol ediyorum; OSM kayıtlarının yokluğu
koruma alanının bulunmadığını kanıtlamaz.
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
