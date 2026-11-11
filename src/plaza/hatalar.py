"""Yapay zekâ sağlayıcılarından gelen hataları sınıflandırır ve Türkçeleştirir.

- Geçici hatalar (sunucu yoğun, dakikalık istek sınırı, bağlantı kopması) birkaç kez
  yeniden denenir.
- Kalıcı hatalar (günlük kota bitti, model ücretsiz katmanda yok, anahtar geçersiz,
  kredi yok) beklemeden işi durdurur; kullanıcıya ne yapması gerektiği söylenir.
"""

from __future__ import annotations

import re


class Durduruldu(Exception):
    """Kullanıcı işi durdurdu."""

# Bekledikçe düzelebilecek durumlar
_GECICI = re.compile(
    r"\b(429|500|502|503|504|529)\b|UNAVAILABLE|overloaded|high demand|try again later|"
    r"rate.?limit|RESOURCE_EXHAUSTED|timed? ?out|timeout|connection (error|reset|aborted)|"
    r"APIConnectionError|ReadError|RemoteProtocolError",
    re.I,
)
# Beklemekle düzelmeyecek durumlar (geçici kalıplardan önce kontrol edilir)
_KALICI = re.compile(
    r"limit: 0\b|per ?day|PerDay|credit balance|insufficient.?(balance|quota)|"
    r"api.?key (not valid|invalid)|invalid.{0,20}api.?key|PERMISSION_DENIED|\b401\b|\b403\b|"
    r"not.?found|\b404\b|does not support|MissingAPIKey",
    re.I,
)
_TEKRAR_SURESI = re.compile(r"retry (?:in|after) ([\d.]+)\s*s\b", re.I)


def _metin(e: BaseException) -> str:
    parcalar, simdiki, gorulen = [], e, set()
    while simdiki is not None and id(simdiki) not in gorulen:  # zincirlenmiş hatalar dahil
        gorulen.add(id(simdiki))
        parcalar.append(f"{type(simdiki).__name__}: {simdiki}")
        simdiki = simdiki.__cause__ or simdiki.__context__
    return " | ".join(parcalar)


def gecici_mi(e: BaseException) -> bool:
    m = _metin(e)
    return bool(_GECICI.search(m)) and not _KALICI.search(m)


def onerilen_bekleme(e: BaseException, varsayilan: float) -> float:
    """Sağlayıcı 'retry in 34s' diyorsa ona uyar (en fazla 60 sn)."""
    m = _TEKRAR_SURESI.search(_metin(e))
    if m:
        try:
            return min(60.0, max(varsayilan, float(m.group(1)) + 1))
        except ValueError:
            pass
    return varsayilan


def bekleme_aciklamasi(e: BaseException, saniye: float, deneme: int, toplam: int) -> str:
    """Masada beklerken gösterilecek kısa açıklama."""
    m = _metin(e)
    if re.search(r"\b429\b|rate.?limit|RESOURCE_EXHAUSTED", m, re.I):
        neden = "Dakikalık istek sınırı doldu"
    elif re.search(r"connection|timed? ?out|timeout", m, re.I):
        neden = "Bağlantı koptu"
    else:
        neden = "Sunucu yoğun"
    return f"{neden}, {saniye:.0f} sn sonra tekrar deneniyor ({deneme}/{toplam})"


def turkce_mesaj(e: BaseException) -> str:
    m = _metin(e)
    if re.search(r"limit: 0\b", m):
        return ("Bu model API hesabınızın ücretsiz katmanında kullanılamıyor (kota sıfır). "
                "Masanın modelini değiştirin ya da sağlayıcı hesabında faturalandırmayı açın.")
    if re.search(r"per ?day|PerDay", m) and re.search(r"quota|RESOURCE_EXHAUSTED|429", m, re.I):
        return "Günlük ücretsiz kota doldu. Yarın tekrar deneyin ya da masanın modelini değiştirin."
    if re.search(r"credit balance|insufficient.?(balance|quota)", m, re.I):
        return "API hesabında kredi/bakiye yok. Sağlayıcının faturalandırma sayfasından yükleme yapın."
    if re.search(r"MissingAPIKey|api.?key (not valid|invalid)|invalid.{0,20}api.?key|\b401\b", m, re.I):
        return "API anahtarı eksik ya da geçersiz. .env dosyasındaki anahtarı kontrol edin."
    if re.search(r"PERMISSION_DENIED|\b403\b", m):
        return "Bu API anahtarının bu modele erişim izni yok."
    if re.search(r"not.?found|\b404\b", m, re.I) and re.search(r"model", m, re.I):
        return "Model bulunamadı. Model kimliğini kontrol edin (yerel modelse 'ollama pull' ile indirin)."
    if re.search(r"\b(503|529)\b|UNAVAILABLE|overloaded|high demand", m, re.I):
        return "Yapay zekâ sunucusu şu an çok yoğun ve birkaç denemede de yanıt vermedi. Birkaç dakika sonra tekrar deneyin."
    if re.search(r"\b429\b|rate.?limit|RESOURCE_EXHAUSTED", m, re.I):
        return "İstek sınırı aşıldı (kısa sürede çok fazla istek). Biraz bekleyip tekrar deneyin."
    if re.search(r"\b(500|502|504)\b", m):
        return "Yapay zekâ sunucusunda bir hata oluştu. Birkaç dakika sonra tekrar deneyin."
    if re.search(r"connection|ConnectError|timed? ?out|timeout", m, re.I):
        return "Yapay zekâ sunucusuna bağlanılamadı. İnternet bağlantınızı (yerel modelse Ollama'nın çalıştığını) kontrol edin."
    return str(e) or type(e).__name__
