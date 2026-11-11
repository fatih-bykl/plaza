import threading
import time
from datetime import datetime

import pytest

from plaza import zamanlayici as z
from plaza.hatalar import Durduruldu
from plaza.llm import CanliTampon, HizSiniri
from plaza.tools import _guvenli_url, build_tools


# ------------------------------------------------------------------ araçlar
def test_dosya_araclari_klasor_disina_cikamaz(tmp_path):
    oku, yaz = build_tools(["file_read", "file_write"], tmp_path)
    assert "Yazıldı" in yaz._run("alt/a.txt", "merhaba")
    assert oku._run("alt/a.txt") == "merhaba"
    assert oku._run("../../etc/passwd").startswith("HATA")
    assert yaz._run("../disari.txt", "x").startswith("HATA")


@pytest.mark.parametrize("url", ["http://127.0.0.1:8770/api/ofis", "http://localhost/", "http://192.168.1.1/",
                                 "file:///etc/passwd", "ftp://ornek.com/"])
def test_web_oku_yerel_adresleri_engeller(url):
    with pytest.raises(ValueError):
        _guvenli_url(url)


def test_python_calistir_anahtar_gormez_ve_zaman_asimi(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "gizli-anahtar")
    (py,) = build_tools(["python_calistir"], tmp_path)
    cikti = py._run("import os\nprint(6*7, os.environ.get('GOOGLE_API_KEY'))")
    assert "42 None" in cikti
    assert not (tmp_path / "_plaza_calistir.py").exists()


def test_bilinmeyen_arac():
    with pytest.raises(ValueError):
        build_tools(["sihir"], None)


# ------------------------------------------------------------------ hız sınırı ve canlı akış
def test_hiz_siniri_bekletir_ve_durdurulabilir():
    h = HizSiniri()
    assert h.bekle("a", 2) == 0 and h.bekle("a", 2) == 0
    iptal, bildirimler = threading.Event(), []
    threading.Timer(0.1, iptal.set).start()
    with pytest.raises(Durduruldu):
        h.bekle("a", 2, iptal, bildirimler.append)
    assert bildirimler and 59 <= bildirimler[0] <= 61
    assert h.bekle("b", 0) == 0  # sınırsız


def test_canli_tampon_sirayi_korur():
    gelen = []
    with CanliTampon(gelen.append) as t:
        for sira, parca in [(3, "c"), (1, "a"), (2, "b")]:
            t.ekle(sira, parca)
    assert "".join(gelen) == "abc"


# ------------------------------------------------------------------ zamanlayıcı
def test_zamanlanmis_gorev_dogrulama(tmp_path):
    dosya = tmp_path / "z.json"
    with pytest.raises(ValueError):
        z.ekle({"talep": "x", "saat": "24:00"}, dosya)
    with pytest.raises(ValueError):
        z.ekle({"talep": " ", "saat": "09:00"}, dosya)
    k = z.ekle({"talep": "Rapor", "saat": "09:30", "gunler": [0, 4, 9]}, dosya)
    assert k["gunler"] == [0, 4] and z.listele(dosya)[0]["id"] == k["id"]


def test_zamanlanmis_gorev_bir_kez_calisir(tmp_path):
    dosya = tmp_path / "z.json"
    z.ekle({"talep": "Pazartesi raporu", "saat": "09:00", "gunler": [0]}, dosya)
    pazartesi = datetime(2026, 11, 9, 9, 3)  # 9 Kasım 2026 Pazartesi
    calisanlar = []
    assert z.kontrol_et(lambda k: calisanlar.append(k["talep"]) or "ok", dosya, pazartesi)
    assert not z.kontrol_et(lambda k: "ok", dosya, pazartesi)                       # aynı gün tekrar yok
    assert not z.kontrol_et(lambda k: "ok", dosya, datetime(2026, 11, 10, 9, 3))   # salı değil
    assert not z.kontrol_et(lambda k: "ok", dosya, datetime(2026, 11, 16, 8, 59))  # saat gelmedi
    assert z.kontrol_et(lambda k: "ok", dosya, datetime(2026, 11, 16, 9, 1))       # sonraki pazartesi
    assert not z.kontrol_et(lambda k: "ok", dosya, datetime(2026, 11, 23, 11, 0))  # 10 dk penceresi geçti
    assert calisanlar == ["Pazartesi raporu"] and "ok" in z.listele(dosya)[0]["son_sonuc"]
