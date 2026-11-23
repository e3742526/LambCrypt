# Upstream and compatibility

LambCrypt is not VeraCrypt. It is an independently maintained derivative of
[VeraCrypt](https://github.com/veracrypt/VeraCrypt), not affiliated with or
endorsed by IDRIX, AM Crypto or the VeraCrypt project.

The fork started from upstream commit [f38c8090](https://github.com/veracrypt/VeraCrypt/commit/f38c80905e0adb484fb32cb9d188c07bbc10c2ad)
from November 18, 2026, after VeraCrypt 1.26.31, plus the fork's subsequent
Unix and CI changes.

Based on TrueCrypt, freely available at [http://www.truecrypt.org/](http://www.truecrypt.org/).

## Licensing and the rename

The original [VeraCrypt license, Apache License 2.0 and TrueCrypt License 3.0](License.txt)
and [upstream notices](src/NOTICE) apply to LambCrypt unchanged. LambCrypt's
own changes and additions are licensed under the Apache License 2.0, and
[MODIFICATIONS.md](MODIFICATIONS.md) explains how changed files are marked.

The project was renamed to comply with those licenses. The VeraCrypt License
grants no right to use the VeraCrypt name or a confusingly similar one. The
TrueCrypt License 3.0 forbids a modified version from carrying the TrueCrypt
name. Both forbid using the original authors' names to endorse a derived
product. A modified build therefore needs its own name.

Inherited platform and release reference pages credit VeraCrypt, and
screenshots may show its interface. These references describe where the code
came from.

## What the rename changed

The rebrand changed the documentation, project links, interface, Unix build
and packaging names, and macOS bundle and installer identities. The Unix
command is now `lambcrypt`, and the Linux mount helper is `mount.lambcrypt`.
Update scripts and any `fstab` entries that use the old helper name.
The macOS app is `LambCrypt.app`, and the experimental FSKit build is
`LambCrypt-FSKit.app`. Bundle identifiers use the `io.github.e3742526`
prefix.

The app keeps its preferences in its own folder:
`~/Library/Application Support/LambCrypt` on macOS and `~/.config/LambCrypt`
on Linux and BSD. It does not read VeraCrypt's preferences. To keep your
settings and favorites, quit both programs and copy the XML files from
VeraCrypt's folder.

## What stays compatible

Backward compatibility with VeraCrypt volumes is a fixed requirement.

LambCrypt retains the VeraCrypt volume format and `.hc` extension. VeraCrypt
volumes open in LambCrypt without conversion, and LambCrypt volumes open in
VeraCrypt. Argon2id volumes need VeraCrypt 1.26.29 or later. Header backup
files are interchangeable.

These identifiers keep the `veracrypt` name on purpose:

| Identifier | Why it is kept |
| --- | --- |
| macOS type identifier `org.idrix.veracrypt.hc` and MIME type `application/veracrypt` | Preserves the existing `.hc` file association |
| Unix mount backend device, mount-tracking and lock identifiers (for example `veracrypt_aux_mnt`) | Both programs recognize existing mounts |
| Linux and BSD default mount path and `VERACRYPT_MOUNT_PREFIX` | Existing mount points and scripts keep working |
| Windows installer, driver, boot loader and recovery identities | Existing Windows system encryption keeps booting |

The Windows source retains its inherited installer, driver, boot and recovery
identities. Its documentation describes the upstream Windows build.
LambCrypt does not build or release Windows binaries. Binaries built from
this tree are still named VeraCrypt, which the license does not allow on a
modified version, so they must not be distributed. The fork's renamed Unix
packages and macOS app do not apply to an existing Windows system encryption
installation.
