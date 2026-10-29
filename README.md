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
