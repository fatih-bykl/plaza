"""Sunucu uç noktaları: gerçek bir simülasyon işini baştan sona çalıştırır."""

import time

import pytest
from fastapi.testclient import TestClient

from plaza import server


@pytest.fixture
def istemci(hizli):
    with TestClient(server.app) as c:
        yield c


def _bitmesini_bekle(c, sure=20):
    son = time.time() + sure
    while time.time() < son:
        if not (server.yayin.is_ and server.yayin.is_.calisiyor) and not server.yayin.kuyruk:
            return c.get("/api/gecmis").json()
        time.sleep(0.05)
    raise AssertionError("iş bitmedi")


def test_ofis_bilgisi(istemci):
    o = istemci.get("/api/ofis").json()
    assert o["ceo"]["key"] == "ceo" and "yerel" in o["saglayicilar"] and o["sablonlar"]
    assert {"web_ara", "python_calistir"} <= set(o["araclar"])


def test_anahtar_yoksa_gercek_gorev_reddedilir(istemci):
    r = istemci.post("/api/gorev", json={"talep": "x", "simulasyon": False})
    assert r.status_code == 400 and "hazır değil" in r.json()["detail"]


def test_simulasyon_isi_kuyruk_ve_proje_sayaci(istemci):
    r1 = istemci.post("/api/gorev", json={"talep": "Birinci iş", "simulasyon": True, "max_revizyon": 0,
                                          "ekler": [{"ad": "not.txt", "icerik": "ek içerik"}]}).json()
    assert "is_id" in r1
    gecmis = _bitmesini_bekle(istemci)
    assert gecmis[0]["durum"] == "is_bitti"
    d = istemci.get(f"/api/is/{r1['is_id']}").json()
    assert "girdi/not.txt" in d["dosyalar"] and "SONUC.md" in d["dosyalar"]
    assert istemci.get(f"/api/is/{r1['is_id']}/zip").headers["content-type"] == "application/zip"
    # biten işler sürdürülemez
    assert istemci.post(f"/api/is/{r1['is_id']}/devam").status_code == 400
    # simülasyonlar proje sayacına girmez
    assert istemci.get("/api/istatistik").json()["projeler"]["ceo"] == []


def test_genel_ayarlar_ve_sablon(istemci):
    o = istemci.put("/api/genel", json={"hiz": {"google": 3}}).json()
    assert o["genel"]["hiz"]["google"] == 3
    o = istemci.post("/api/sablon/pazarlama").json()
    assert any(d["name"] == "Pazarlama Departmanı" for d in o["departmanlar"])
    assert istemci.post("/api/sablon/olmayan").status_code == 404


def test_zamanlanmis_uc_noktalari(istemci):
    liste = istemci.post("/api/zamanlanmis", json={"talep": "Günlük özet", "saat": "08:15"}).json()
    zid = liste[-1]["id"]
    assert istemci.put(f"/api/zamanlanmis/{zid}", json={"aktif": False}).json()[-1]["aktif"] is False
    assert istemci.delete(f"/api/zamanlanmis/{zid}").status_code == 200
    assert istemci.post("/api/zamanlanmis", json={"talep": "x", "saat": "99:99"}).status_code == 400


def test_dosya_yolu_disari_cikamaz(istemci):
    assert istemci.get("/api/dosya", params={"yol": "../ofis.json"}).status_code == 404
