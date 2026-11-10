# Plaza

Claude modelleriyle çalışan, departmanlardan oluşan bir ajan ofisi. [CrewAI](https://github.com/crewAIInc/crewAI) üzerine kurulu.

## Organizasyon

| Departman (anahtar) | Çalışanlar |
|---|---|
| `urun` | Ürün Yöneticisi |
| `yazilim` | Kıdemli Yazılımcı |
| `kalite` | Kalite Kontrol (QA) Uzmanı |
| `arastirma` | Araştırmacı Analist |
| `icerik` | İçerik Yazarı, Editör |

Bunların üstünde, tüm işlerin önce geldiği ve işi dağıtan bir **CEO** var.
Departman eklemek ya da değiştirmek için `src/plaza/config/departments.yaml` dosyasını düzenleyin.

## Kurulum

```bash
uv sync
cp .env.example .env   # ardından ANTHROPIC_API_KEY değerini yazın
```

## Ofis arayüzü (grafik)

```bash
uv run plaza-ofis        # http://127.0.0.1:8770 açılır (--port, --tarayici-acma)
```

Kuşbakışı bir ofis açılır: ortada **CEO Odası**, çevresinde departman odaları, her odada
masasında çalışan personel.

- **Görev akışı:** Görevler her zaman önce CEO'ya verilir. CEO talebi inceler, hangi çalışanın
  hangi sırayla ne yapacağını planlar; görev kâğıtları masalara uçar. Her çalışan kendisinden
  önceki çıktıları değerlendirip kendi katkısını ekler. CEO sonuçları değerlendirir, gerekirse
  revizyon ister (0–2 tur), sonra nihai teslimatı yazar.
- **Masaya tıklayınca:** o masada çalışacak yapay zekâ modeli (Opus / Sonnet / Haiku / Fable ya da
  özel model kimliği), isim, rol, hedef, karakter/talimatlar, araçlar ve masanın aktifliği
  ayarlanır; o işte masaya verilen görevler ve çıktıları görülür. Ayarlar `ofis.json` dosyasına
  yazılır (YAML değişmez; "Varsayılana dön" ile silinir).
- **Ofis düzeni:** Bir odanın etiketine ya da boş zeminine tıklayınca departman paneli açılır:
  departmanı yeniden adlandırın, yeni masa (çalışan) ekleyin (odada en fazla 6 masa) ya da
  departmanı kaldırın. Etiketteki **+** düğmesi doğrudan masa ekler. Boş hücredeki
  **Yeni departman** alanı (ya da paneldeki "+ Departman ekle") yeni oda açar. Masa panelindeki
  "Masayı kaldır" çalışanı ofisten çıkarır. Tüm bunlar `ofis.json`'a yazılır; "Ofisi varsayılana
  döndür" her şeyi YAML'daki haline getirir. (Komut satırı `plaza` yalnızca YAML'ı kullanır.)
- **Simülasyon:** Claude çağırmadan tüm akışı sahte çıktılarla dener (API anahtarı yoksa zorunlu).
- Her iş `cikti/<tarih-saat>/` klasörüne kaydedilir (`SONUC.md`, ajanların dosyaları, `is.json`);
  "Geçmiş işler" listesinden tekrar açılabilir.

## Komut satırı

```bash
# Hiyerarşik (varsayılan): Genel Müdür işi uygun çalışanlara dağıtır ve denetler
uv run plaza "Python ile basit bir yapılacaklar listesi CLI uygulaması yap"

# Sıralı: seçilen departmanlar verilen sırayla, birbirinin çıktısını alarak çalışır
uv run plaza -s sirali -d urun -d yazilim -d kalite "Yapılacaklar listesi CLI uygulaması"

# Araştırma + içerik ekibiyle rapor hazırlama
uv run plaza -d arastirma -d icerik "Küçük işletmeler için yapay zekâ kullanım alanları raporu"

uv run plaza --liste    # departmanları göster
uv run plaza --kuru "…" # ekibi kur, Claude'u çağırma
```

Ajanlar dosyalarını `cikti/` klasörüne yazar (`-o` ile değiştirilebilir); nihai sonuç `cikti/SONUC.md` dosyasına kaydedilir.
Araçlar bu klasörün dışına erişemez.

## Model

Varsayılan model `anthropic/claude-opus-5-5`. `.env` içinde `PLAZA_MODEL`, ya da ayrı ayrı
`PLAZA_MANAGER_MODEL` / `PLAZA_STAFF_MODEL` ile değiştirilebilir (ör. çalışanlar için `anthropic/claude-sonnet-5-5`).
