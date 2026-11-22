#!/bin/sh
V="$(mount | grep veracrypt_aux_mnt)"
[ "$V" ] && echo "Error: All volumes must be dismounted first." 1>&2 && exit 1

removal_failed() {
	echo "Error: File removal failed, please run the script with elevated privileges." 1>&2 && exit 1
}

update_system_caches() {
	if command -v update-mime-database >/dev/null 2>&1; then
		update-mime-database /usr/share/mime >/dev/null 2>&1
	fi
	if command -v update-desktop-database >/dev/null 2>&1; then
		update-desktop-database -q >/dev/null 2>&1
	fi
	return 0
}

rm -f /usr/bin/lambcrypt || removal_failed
rm -f /usr/sbin/mount.lambcrypt || removal_failed
rm -f /usr/share/applications/lambcrypt.desktop || removal_failed
rm -f /usr/share/pixmaps/lambcrypt.xpm || removal_failed
rm -f /usr/share/mime/packages/lambcrypt.xml || removal_failed
rm -fr /usr/share/lambcrypt || removal_failed
rm -fr /usr/share/doc/lambcrypt || removal_failed
rm -f /usr/share/icons/hicolor/scalable/apps/lambcrypt.svg || removal_failed
rm -f /usr/share/icons/hicolor/symbolic/apps/lambcrypt-symbolic.svg || removal_failed
for res in 16 22 24 32 48 64 128 256 512 1024; do \
		rm -f /usr/share/icons/hicolor/${res}x${res}/apps/lambcrypt.png || removal_failed ;\
done
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor >/dev/null 2>&1 || true

rm -f /usr/bin/lambcrypt-uninstall.sh || removal_failed
update_system_caches

echo LambCrypt uninstalled.
