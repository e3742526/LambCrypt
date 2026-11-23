#!/bin/sh
# Modified for LambCrypt by the LambCrypt contributors. Changes from VeraCrypt are in the git history; see UPSTREAM.md.

rm -f \
	/usr/share/doc/lambcrypt/HTML/en/Donation_Bank.html \
	/usr/share/doc/lambcrypt/HTML/en/bank_30x30.png \
	/usr/share/doc/lambcrypt/HTML/ru/Donation_Bank.html \
	/usr/share/doc/lambcrypt/HTML/ru/bank_30x30.png \
	/usr/share/doc/lambcrypt/HTML/zh-cn/Donation_Bank.html \
	/usr/share/doc/lambcrypt/HTML/zh-cn/bank_30x30.png \
	/usr/share/icons/hicolor/symbolic/apps/lambcrypt-symbolic.svg || true

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
	gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi

exit 0
