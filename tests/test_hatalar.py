from plaza.hatalar import bekleme_aciklamasi, gecici_mi, onerilen_bekleme, turkce_mesaj

DAKIKALIK_429 = (
    "429 RESOURCE_EXHAUSTED. You exceeded your current quota, please check your plan and billing details. "
    "Quota exceeded for metric: generate_content_free_tier_requests, limit: 15, model: gemini-3.5-flash-lite, "
    "description: Generate content requests per minute limit exceeded on Free Tier. Please retry in 53.55s."
)
KOTA_SIFIR = (
    "429 RESOURCE_EXHAUSTED. Quota exceeded for metric: generate_content_free_tier_requests, limit: 0, "
    "model: gemini-4-argon, description: Generate content requests per day limit exceeded on Free Tier."
)


def test_dakikalik_sinir_gecicidir_ve_onerilen_sure_kullanilir():
    e = Exception(DAKIKALIK_429)
    assert gecici_mi(e)  # 'billing' kelimesi kalıcı saydırmamalı (yaşanan hata)
    assert 54 <= onerilen_bekleme(e, 5) <= 55
    assert bekleme_aciklamasi(e, 55, 1, 3).startswith("Dakikalık istek sınırı doldu")
    assert "İstek sınırı" in turkce_mesaj(e)


def test_kalici_hatalar_yeniden_denenmez():
    for metin in (KOTA_SIFIR, "Your credit balance is too low", "API key not valid. Please pass a valid API key.",
                  "MissingAPIKeyError: DEEPSEEK_API_KEY is required"):
        assert not gecici_mi(Exception(metin)), metin


def test_gecici_hatalar():
    for metin in ("503 UNAVAILABLE. This model is currently experiencing high demand.",
                  "APIConnectionError: Connection error.", "529 overloaded_error"):
        assert gecici_mi(Exception(metin)), metin


def test_turkce_mesajlar():
    assert "ücretsiz katmanında" in turkce_mesaj(Exception(KOTA_SIFIR))
    assert "kredi" in turkce_mesaj(Exception("Your credit balance is too low"))
    assert "yoğun" in turkce_mesaj(Exception("503 UNAVAILABLE high demand"))


def test_bekleme_ust_siniri():
    assert onerilen_bekleme(Exception("Please retry in 500s."), 5) == 60
    assert onerilen_bekleme(Exception("bir hata"), 7) == 7


def test_zincirlenmis_hata_metni_okunur():
    try:
        try:
            raise Exception(DAKIKALIK_429)
        except Exception as ic:
            raise RuntimeError("ajan hatası") from ic
    except RuntimeError as dis:
        assert gecici_mi(dis)
