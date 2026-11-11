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
- **Paralel aşamalar:** CEO planı aşamalara böler. Aynı aşamadaki görevler aynı anda çalışır ve
  yalnızca önceki aşamaların çıktılarını görür; bağımlı işler sonraki aşamalara konur.
- **Planı önce bana göster:** İşaretlenirse CEO'nun planı departmanlara gitmeden önce panelde
  açılır; çalışanı, görevi ve aşamayı değiştirebilir, adım ekleyip silebilir, sonra onaylarsınız.
- **Görev kuyruğu:** CEO çalışırken verilen görevler sıraya girer ve sırayla başlar; sıradaki bir
  görev listeden çıkarılabilir.
- **Ek dosyalar:** 📎 ile metin dosyaları (en fazla 10 dosya, her biri 200.000 karakter) eklenir.
  `girdi/` klasörüne kaydedilir; CEO ve çalışanlar içeriklerini görür.
- **Devam görevi:** Bir iş sonucunda ya da geçmişte "Bu işin üzerine devam et" denirse yeni
  görev önceki işin sonucunu bağlam olarak alır; önceki dosyalar `onceki/` altına kopyalanır.
- **İstatistikler:** Her adımın süresi ve token kullanımı, işin toplamı ve masa panelinde o
  masanın tüm zamanlar toplamı (simülasyonlar hariç) gösterilir.
- **ZIP indir:** Bir işin tüm dosyaları tek tıkla indirilebilir.
- **Tema ve bildirim:** Üst çubuktaki ◐ ile açık/koyu tema; sekme arka plandayken iş bitince,
  hata olunca ya da plan onay beklerken tarayıcı bildirimi.
- **Masaya tıklayınca:** o masada çalışacak yapay zekâ modeli — Anthropic (Claude Opus / Sonnet /
  Haiku / Fable), Google (Gemini 4 Carbon / 4 Argon / 3.8 Flash / 3.5 Flash-Lite), DeepSeek (V4 Pro /
  Flash) ya da özel bir model kimliği, isim, rol, hedef, karakter/talimatlar, araçlar ve masanın aktifliği
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

Her masa farklı bir sağlayıcının modelini kullanabilir. Gereken anahtarlar (`.env`):

| Sağlayıcı | Anahtar | Model kimliği örneği |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | `anthropic/claude-opus-5-5` |
| Google | `GOOGLE_API_KEY` ya da `GEMINI_API_KEY` | `gemini/gemini-4-argon` |
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek/deepseek-v4-pro` |
| Yerel (Ollama) | gerekmez | `ollama/deepseek-r1:8b` |

### API'siz yerel DeepSeek (Ollama)

DeepSeek R1 modelleri bu bilgisayarda [Ollama](https://ollama.com) ile, API anahtarı ve ücret olmadan
çalışır. 8B modeli (5.2 GB) 8 GB ekran kartına sığar; 14B (9 GB) daha yavaş çalışır.

```bash
sudo pacman -S ollama-cuda          # NVIDIA ekran kartı için
sudo systemctl enable --now ollama
ollama pull deepseek-r1:8b          # ya da deepseek-r1:14b
```

Ardından masada "Yerel — Ollama" grubundan modeli seçin. Ollama'da kurulu başka modeller de
listede otomatik görünür. Not: DeepSeek R1 araç çağırmayı desteklemez; bu masalar dosya yazamaz,
dosya içeriklerini çıktılarında verir. Modelin `<think>` düşünce bölümleri çıktıdan temizlenir.

Anahtarı olmayan sağlayıcılar seçim listesinde işaretlenir; gerçek bir görev başlatılırken eksik
anahtar varsa hangi masanın neye ihtiyaç duyduğu söylenir.


Varsayılan model `anthropic/claude-opus-5-5`. `.env` içinde `PLAZA_MODEL`, ya da ayrı ayrı
`PLAZA_MANAGER_MODEL` / `PLAZA_STAFF_MODEL` ile değiştirilebilir (ör. çalışanlar için `anthropic/claude-sonnet-5-5`).
