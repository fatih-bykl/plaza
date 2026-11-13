#!/usr/bin/env bash
# FTP bilgilerini ~/.netrc dosyasına yazar (yalnızca sizin okuyabileceğiniz şekilde).
# Şifre ekranda görünmez ve hiçbir yere gönderilmez.
set -euo pipefail

echo "=== Plaza sayfası için FTP ayarı ==="
echo "Bu bilgiler barındırma panelinizin (cPanel vb.) FTP bölümünde yazar."
echo
read -rp "FTP sunucu adresi (ör. ftp.internetsihirbazi.com): " SUNUCU
read -rp "FTP kullanıcı adı: " KULLANICI
read -rsp "FTP şifresi (yazarken görünmez): " SIFRE
echo
if [[ -z "$SUNUCU" || -z "$KULLANICI" || -z "$SIFRE" ]]; then
  echo "Bilgilerden biri boş kaldı; hiçbir şey kaydedilmedi." >&2
  exit 1
fi

NETRC="$HOME/.netrc"
touch "$NETRC"
chmod 600 "$NETRC"
# Aynı sunucu için eski bir satır varsa çıkar, yenisini ekle
grep -v "^machine $SUNUCU " "$NETRC" > "$NETRC.yeni" || true
printf 'machine %s login %s password %s\n' "$SUNUCU" "$KULLANICI" "$SIFRE" >> "$NETRC.yeni"
mv "$NETRC.yeni" "$NETRC"
chmod 600 "$NETRC"
unset SIFRE

echo
echo "Kaydedildi: $NETRC (yalnızca siz okuyabilirsiniz)."
echo "Bağlantı deneniyor..."
if curl -s --netrc --max-time 20 "ftp://$SUNUCU/" -l > /dev/null; then
  echo "✓ Bağlantı başarılı. Claude'a sunucu adresini ($SUNUCU) yazabilirsiniz."
else
  echo "✗ Bağlanılamadı. Adresi, kullanıcı adını ya da şifreyi kontrol edip betiği yeniden çalıştırın."
fi
