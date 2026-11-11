import json

import pytest

from plaza import settings as st


def test_varsayilan_ofis(ayar_dosyasi):
    o = st.load_office(ayar_dosyasi=ayar_dosyasi)
    assert o.ceo.key == "ceo"
    assert {d.key for d in o.departments} >= {"urun", "yazilim", "kalite", "arastirma", "icerik"}
    arastirmaci = o.desk("arastirmaci")
    assert {"web_ara", "web_oku"} <= set(arastirmaci.tools)


def test_masa_ayari_kaydet_ve_sifirla(ayar_dosyasi):
    st.masa_ayari_kaydet("yazilimci", {"model": "ollama/deepseek-r1:8b", "yedek_model": "gemini/gemini-3.8-flash",
                                       "bilinmeyen": 1}, ayar_dosyasi)
    d = st.load_office(ayar_dosyasi=ayar_dosyasi).desk("yazilimci")
    assert d.model == "ollama/deepseek-r1:8b" and d.yedek_model == "gemini/gemini-3.8-flash" and d.ozel
    assert "bilinmeyen" not in json.loads(ayar_dosyasi.read_text())["yazilimci"]
    st.masa_ayarini_sil("yazilimci", ayar_dosyasi)
    assert not st.load_office(ayar_dosyasi=ayar_dosyasi).desk("yazilimci").ozel


def test_bilinmeyen_arac_reddedilir(ayar_dosyasi):
    with pytest.raises(ValueError):
        st.masa_ayari_kaydet("qa", {"tools": ["uzaydan_veri"]}, ayar_dosyasi)


def test_departman_ekle_kaldir_ve_turkce_anahtar(ayar_dosyasi):
    key = st.departman_ekle("İnsan Kaynakları", ayar_dosyasi)
    assert key == "insan_kaynaklari"
    m = st.masa_ekle(key, {"isim": "Selin", "role": "İK Uzmanı"}, ayar_dosyasi)
    o = st.load_office(ayar_dosyasi=ayar_dosyasi)
    assert [s.key for d in o.departments if d.key == key for s in d.staff] == [m]
    st.departman_kaldir(key, ayar_dosyasi)
    assert key not in {d.key for d in st.load_office(ayar_dosyasi=ayar_dosyasi).departments}


def test_yaml_departmani_gizlenir_ve_sifirlanir(ayar_dosyasi):
    st.departman_kaldir("arastirma", ayar_dosyasi)
    st.masa_kaldir("qa", ayar_dosyasi)
    o = st.load_office(ayar_dosyasi=ayar_dosyasi)
    assert "arastirma" not in {d.key for d in o.departments}
    with pytest.raises(KeyError):
        o.desk("qa")
    st.ofisi_sifirla(ayar_dosyasi)
    assert "arastirma" in {d.key for d in st.load_office(ayar_dosyasi=ayar_dosyasi).departments}


def test_oda_kapasitesi(ayar_dosyasi):
    key = st.departman_ekle("Dolu Oda", ayar_dosyasi)
    for i in range(st.MAX_MASA):
        st.masa_ekle(key, {"role": f"Rol {i}"}, ayar_dosyasi)
    with pytest.raises(ValueError):
        st.masa_ekle(key, {"role": "Fazla"}, ayar_dosyasi)


@pytest.mark.parametrize("sablon", sorted(st.DEPARTMAN_SABLONLARI))
def test_departman_sablonlari(ayar_dosyasi, sablon):
    key = st.sablon_uygula(sablon, ayar_dosyasi)
    dep = next(d for d in st.load_office(ayar_dosyasi=ayar_dosyasi).departments if d.key == key)
    assert len(dep.staff) == len(st.DEPARTMAN_SABLONLARI[sablon]["calisanlar"])


def test_genel_ayarlar_ve_maliyet(ayar_dosyasi):
    g = st.genel_ayarlar(ayar_dosyasi)
    assert g["hiz"]["google"] == 12 and g["canli_akis"] is True
    g = st.genel_ayarlari_kaydet({"hiz": {"google": 5, "olmayan": 9}, "fiyatlar": {"gemini/gemini-3.5-flash-lite": [0.1, 0.4]},
                                  "canli_akis": False}, ayar_dosyasi)
    assert g["hiz"]["google"] == 5 and "olmayan" not in g["hiz"] and g["canli_akis"] is False
    assert st.maliyet("gemini/gemini-3.5-flash-lite", 1_000_000, 1_000_000, g) == pytest.approx(0.5)
    assert st.maliyet("anthropic/claude-opus-5-5", 1000, 500, g) == pytest.approx(0.014)
    assert st.maliyet("ollama/deepseek-r1:8b", 10**6, 10**6, g) == 0
    assert st.maliyet("gemini/gemini-4-carbon", 1, 1, g) is None


def test_saglayici_tanima():
    assert st.saglayici("anthropic/claude-opus-5-5") == "anthropic"
    assert st.saglayici("gemini/gemini-4-argon") == "google"
    assert st.saglayici("deepseek/deepseek-flash") == "deepseek"
    assert st.saglayici("ollama/deepseek-r1:8b") == "yerel"
    assert st.saglayici("bilinmeyen/model") is None
