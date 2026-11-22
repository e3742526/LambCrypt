# Upstream and compatibility

LambCrypt is independently maintained from [VeraCrypt](https://github.com/veracrypt/VeraCrypt).
The rebrand started from upstream commit [f38c8090](https://github.com/veracrypt/VeraCrypt/commit/f38c80905e0adb484fb32cb9d188c07bbc10c2ad)
from November 18, 2026, plus the fork’s subsequent Unix and CI changes.

Based on TrueCrypt, freely available at [http://www.truecrypt.org/](http://www.truecrypt.org/).

The original [VeraCrypt license, Apache License 2.0 and TrueCrypt License 3.0](License.txt)
and [upstream notices](src/NOTICE) apply. Inherited platform and release
reference pages credit VeraCrypt, and screenshots may show its interface.

The rebrand changed the documentation, project links, interface, Unix build
and packaging names, and macOS bundle and installer identities. The Unix
command is now `lambcrypt`, and the Linux mount helper is `mount.lambcrypt`.
Update scripts and any `fstab` entries that use the old helper name.
The macOS app is `LambCrypt.app`. The Unix app uses its own preferences
directory. Recreate your preferences and favorites there as needed.

LambCrypt retains the VeraCrypt volume format and `.hc` extension. The Unix
mount backend retains its inherited device, mount tracking and lock identifiers
so both builds can recognize existing mounts. The default mount path and
`VERACRYPT_MOUNT_PREFIX` on Linux and BSD remain valid.

The Windows source retains its inherited installer, driver, boot and recovery
identities. Its documentation describes the upstream Windows build. The fork’s
renamed Unix packages and macOS app do not apply to an existing Windows system
encryption installation.
