# Plaza

Yapay zekâ çalışanlarından oluşan, CEO'nun yönettiği çok departmanlı bir ajan ofisi.
[CrewAI](https://github.com/crewAIInc/crewAI) üzerine kurulu; Claude, Gemini, DeepSeek ve
bilgisayarınızda çalışan yerel modellerle (Ollama) çalışır.

## Organizasyon

| Departman (anahtar) | Çalışanlar |
|---|---|
| `urun` | Ürün Yöneticisi |
| `yazilim` | Kıdemli Yazılımcı |
| `kalite` | Kalite Kontrol (QA) Uzmanı |
| `arastirma` | Araştırmacı Analist |
| `icerik` | İçerik Yazarı, Editör |

Bunların üstünde, tüm işlerin önce geldiği ve işi dağıtan bir **CEO** var. Varsayılan düzen
`src/plaza/config/departments.yaml` dosyasındadır; arayüzden yapılan değişiklikler `ofis.json`'a yazılır.

## Kurulum

```bash
uv sync
cp .env.example .env   # en az bir sağlayıcının anahtarını yazın (ya da yerel model kullanın)
```

## Ofis arayüzü

```bash
uv run plaza-ofis        # http://127.0.0.1:8770 açılır (--port, --tarayici-acma)
```

Kuşbakışı bir ofis açılır: ortada **CEO Odası**, çevresinde departman odaları, her odada masasında
çalışan personel.

### Görev akışı
- **CEO önce:** Görevler her zaman önce CEO'ya verilir. CEO talebi inceler ve aşamalı bir plan
  çıkarır; basit işlerde 1-2 çalışanla yetinir. Görev kâğıtları masalara uçar.
- **Paralel aşamalar:** Aynı aşamadaki görevler aynı anda çalışır ve yalnızca önceki aşamaların
  çıktılarını görür; bağımlı işler sonraki aşamalara konur.
- **Değerlendirme:** CEO sonuçları değerlendirir, gerekirse revizyon ister (0–2 tur), sonra nihai
  teslimatı yazar.
- **Planı önce bana göster:** CEO'nun planı departmanlara gitmeden önce panelde açılır; çalışanı,
  görevi ve aşamayı değiştirebilir, adım ekleyip silebilirsiniz.
- **Canlı çıktı:** Çalışanların yazdıkları, onlar yazarken iş akışında ve masa panelinde görünür.

### Sağlamlık
- **Kaldığı yerden devam:** Hata veren ya da durdurulan bir iş "↻ Kaldığı yerden devam et" ile
  sürdürülür; biten adımlar yeniden yapılmaz, dosyalar korunur. Geçmiş işlerden de yapılabilir.
- **Yeniden deneme:** Geçici hatalarda (sunucu yoğun, dakikalık istek sınırı, bağlantı kopması)
  adım 3 kez yeniden denenir; kalıcı hatalarda (kota sıfır, kredi yok, geçersiz anahtar) beklemeden
  durulur ve Türkçe açıklama verilir.
- **İstek hızı sınırı:** Sağlayıcı başına "dakikada en fazla X istek" (Ayarlar). Sınır dolunca
  Plaza hata almak yerine bekler. Google için varsayılan 12/dk (ücretsiz katman 15/dk).
- **Yedek model:** Her masaya isteğe bağlı bir yedek yapay zekâ seçilir; ana model kalıcı hata
  verirse yedek devralır (ör. Gemini kotası biterse yerel DeepSeek).

### Masalar ve ofis düzeni
- **Masaya tıklayınca:** yapay zekâ modeli ve yedeği, isim, rol, hedef, karakter/talimatlar,
  araçlar ve aktiflik ayarlanır; o işteki görevleri, canlı çıktısı ve tüm zamanlar istatistiği
  görülür. **Sohbet** bölümünden çalışana CEO akışı dışında doğrudan soru sorulabilir.
- **Araçlar:** dosya okuma/yazma/listeleme, **Web'de arama** ve **Web sayfası okuma** (yerel ağ
  adresleri engellenir), **Python çalıştırma** (kod çalışma klasöründe, 30 sn sınırıyla ve API
  anahtarları olmadan çalışır; kod bu bilgisayarda çalıştığı için varsayılan olarak kapalıdır).
- **Departmanlar:** Oda etiketine ya da zeminine tıklayıp yeniden adlandırın, masa ekleyin (en fazla
  6), kaldırın. **Şablonlar** ile tek tıkla Web Ajansı, Pazarlama, Hukuk ya da Muhasebe ve Finans
  departmanı kurulur. "Ofisi varsayılana döndür" her şeyi YAML'daki hâline getirir.
- **🏆 Proje sayısı:** Her oda etiketinde o departmanın başarıyla bitirdiği proje sayısı; tıklayınca
  projeler listelenir.

### Görevler ve sonuçlar
- **Görev şablonları:** Web sayfası, araştırma raporu, sosyal medya, kod inceleme, e-posta, özet.
- **Görev kuyruğu:** CEO çalışırken verilen görevler sıraya girer.
- **Zamanlanmış görevler:** Belirli saatte (isteğe bağlı belirli günlerde) CEO'ya kendiliğinden görev
  verilir. Plaza Ofis açık olmalıdır; kapalıyken kaçan görevler sonradan çalıştırılmaz.
- **Ek dosyalar:** 📎 ile metin dosyaları eklenir (`girdi/`); **Devam görevi** önceki işin sonucunu
  ve dosyalarını (`onceki/`) bağlam olarak alır.
- **Sonuçlar:** Her iş `cikti/<tarih-saat>/` klasörüne kaydedilir (`SONUC.md`, ajanların dosyaları,
  `is.json`). HTML dosyaları güvenli bir çerçevede **canlı önizlenir**; tüm dosyalar ZIP olarak indirilir.
- **Maliyet:** Her adımın ve işin süresi, token'ı ve tahmini maliyeti; "Ayarlar ve harcama"
  bölümünde aylık harcama. Claude fiyatları resmîdir; Gemini ve DeepSeek fiyatları üçüncü taraf
  kaynaklardan tahminidir ve arayüzden düzeltilebilir. Yerel modeller ücretsizdir.
- **Simülasyon:** Yapay zekâ çağırmadan tüm akışı sahte çıktılarla dener.

## Komut satırı

Arayüzle aynı ayarları (`ofis.json`) ve aynı CEO akışını kullanır.

```bash
uv run plaza "Küçük işletmeler için yapay zekâ kullanım alanları raporu"
uv run plaza -d arastirma -d icerik -r 0 "…"   # yalnızca bu departmanlar, revizyon yok
uv run plaza --liste                            # departmanlar, çalışanlar ve modelleri
uv run plaza --kuru "…"                         # simülasyon
```

## Modeller

| Sağlayıcı | Anahtar (`.env`) | Model kimliği örneği |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | `anthropic/claude-opus-5-5` |
| Google | `GOOGLE_API_KEY` ya da `GEMINI_API_KEY` | `gemini/gemini-3.5-flash-lite` |
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek/deepseek-v4-pro` |
| Yerel (Ollama) | gerekmez | `ollama/deepseek-r1:8b` |

Anahtarı olmayan sağlayıcılar seçim listesinde işaretlenir; gerçek bir görev başlatılırken eksik
anahtar varsa hangi masanın neye ihtiyaç duyduğu söylenir. Google'ın ücretsiz katmanında bazı
modellerin (ör. Gemini 4 Argon) kotası sıfırdır.

### API'siz yerel DeepSeek (Ollama)

DeepSeek R1 modelleri bu bilgisayarda [Ollama](https://ollama.com) ile, API anahtarı ve ücret olmadan
çalışır. 8B modeli (5.2 GB) 8 GB ekran kartına sığar; 14B (9 GB) daha yavaş çalışır.

```bash
sudo pacman -S ollama-cuda          # NVIDIA ekran kartı için
sudo systemctl enable --now ollama
ollama pull deepseek-r1:8b          # ya da deepseek-r1:14b
```

Ollama'da kurulu diğer modeller de listede kendiliğinden görünür. Araç çağırmayı desteklemeyen
yerel modellerde dosya araçları kapatılır; modelin `<think>` düşünce bölümleri çıktıdan temizlenir.
Uzun işler için metin penceresini büyütmek isterseniz (`OLLAMA_CONTEXT_LENGTH`, ör. 8192) Ollama
servisine ayar ekleyin.

Masa ayarı yapılmamış çalışanların varsayılan modeli `anthropic/claude-opus-5-5`'tir; `.env` içinde
`PLAZA_MODEL` ya da ayrı ayrı `PLAZA_MANAGER_MODEL` / `PLAZA_STAFF_MODEL` ile değiştirilebilir.

## Geliştirme

```bash
uv run pytest          # testler; gerçek ayarlara ve API anahtarlarına dokunmaz
```
