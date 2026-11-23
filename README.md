<!-- Modified for LambCrypt by the LambCrypt contributors. Changes from VeraCrypt are in the git history; see UPSTREAM.md. -->
# LambCrypt

> **LambCrypt is not VeraCrypt.** It is an independently maintained derivative
> of [VeraCrypt](https://github.com/veracrypt/VeraCrypt). It is not affiliated
> with or endorsed by IDRIX, AM Crypto or the VeraCrypt project. Report LambCrypt
> problems to the [LambCrypt issue tracker](https://github.com/e3742526/LambCrypt/issues),
> not to VeraCrypt.

LambCrypt focuses on disk encryption for Apple silicon Macs running macOS 26
(Tahoe) and later. It reads and writes the VeraCrypt volume format, so
**existing VeraCrypt volumes open in LambCrypt without conversion, and volumes
created in LambCrypt open in VeraCrypt.**

Based on TrueCrypt, freely available at [http://www.truecrypt.org/](http://www.truecrypt.org/).

The Unix command is `lambcrypt`. The macOS application is `LambCrypt.app`.
The application, installers and bundled documentation are English only.

[Bundled guide](doc/html/en/Documentation.html) · [Upstream and compatibility](UPSTREAM.md) · [Bug log](BUGLOG.md) · [Report an issue](https://github.com/e3742526/LambCrypt/issues) · [License](License.txt)

# Contents

- [Why the name changed](#why-the-name-changed)
- [Compatibility with VeraCrypt](#compatibility-with-veracrypt)
- [How LambCrypt differs from VeraCrypt](#how-lambcrypt-differs-from-veracrypt)
- [Project status](#project-status)
- [Installing LambCrypt](#installing-lambcrypt)
- [Building from source](#building-from-source)
- [Contributing](#contributing)
- [Legal information](#legal-information)
- [Further information](#further-information)

# Why the name changed

LambCrypt was renamed to comply with the licenses it inherits. VeraCrypt is
distributed under the Apache License 2.0 and the TrueCrypt License 3.0
([License.txt](License.txt)):

- The VeraCrypt License grants no right to use the VeraCrypt name, logo or
  trademarks, or any confusingly similar name such as "VeraCrypt+" or
  "Vera Crypt".
- The TrueCrypt License 3.0 forbids a modified version from containing the
  name TrueCrypt and requires removing that name wherever it would identify
  the modified product.
- Neither license allows the original authors' names to be used to endorse
  or promote a derived product.

A modified version therefore cannot be distributed as "VeraCrypt". The
rename changes product names, icons, links and bundle identities only. It
does not change the volume format, the encryption or the on-disk layout.

The remaining references to VeraCrypt and TrueCrypt in this repository
describe where the code came from, as both licenses require. Some identifiers
keep the name `veracrypt` because changing them would break compatibility;
[UPSTREAM.md](UPSTREAM.md) lists them.

# Compatibility with VeraCrypt

Backward compatibility with VeraCrypt volumes is a fixed requirement of this
project.

- **Volumes:** LambCrypt uses the VeraCrypt volume format and the `.hc`
  extension. It opens file containers, partitions and devices created by
  VeraCrypt, including hidden volumes, with the same password, PIM, keyfiles
  and security tokens. It never converts or upgrades a volume.
- **Both directions:** a volume created by LambCrypt opens in VeraCrypt. If
  you choose Argon2id, the volume needs VeraCrypt 1.26.29 or later, which
  added Argon2id.
- **Algorithms:** LambCrypt offers the same ciphers, cascades, hash
  algorithms and key derivation functions as VeraCrypt.
- **Header backups:** header backup files are interchangeable between the
  two programs.
- **Existing mounts:** on Linux, BSD and macOS, LambCrypt keeps VeraCrypt's
  mount-tracking and lock identifiers, so it recognizes volumes that
  VeraCrypt already mounted. The Linux and BSD default mount directories and the
  `VERACRYPT_MOUNT_PREFIX` variable work as before.
- **File association:** on macOS, LambCrypt claims `.hc` files under
  VeraCrypt's type identifier `org.idrix.veracrypt.hc` and MIME type
  `application/veracrypt`.
- **Not carried over:** preferences, favorites and the command name. See
  [Moving from VeraCrypt](#moving-from-veracrypt).

Compatibility is checked against VeraCrypt itself. In the FSKit trials, an
upstream VeraCrypt build opened a fresh LambCrypt container and matched its
full decrypted image, and LambCrypt opened older VeraCrypt test containers,
including one from 2015. See [FSKIT-MIGRATION.md](FSKIT-MIGRATION.md).

# How LambCrypt differs from VeraCrypt

LambCrypt started from upstream commit
[f38c8090](https://github.com/veracrypt/VeraCrypt/commit/f38c80905e0adb484fb32cb9d188c07bbc10c2ad)
(18 November 2026, after VeraCrypt 1.26.31).

| Area | VeraCrypt | LambCrypt |
| --- | --- | --- |
| Primary platform | Windows, Linux, macOS and BSD | Apple silicon Macs on macOS 26 (Tahoe) and later. Linux and BSD build from source. |
| macOS mount backends | macFUSE or FUSE-T | macFUSE (default) or FUSE-T, plus an experimental opt-in **FSKit** build that needs no third-party file system driver |
| macOS build target | macOS 12 and later, universal binary | macOS 26.0 deployment target |
| Languages | Many translations | English only |
| Names | `veracrypt`, `VeraCrypt.app`, `mount.veracrypt` | `lambcrypt`, `LambCrypt.app`, `mount.lambcrypt`, and `LambCrypt-FSKit.app` for the FSKit build |
| Preferences | `VeraCrypt` folder | Separate `LambCrypt` folder |
| Windows | Maintained and released | Inherited source only. No Windows release. |
| Fixes | VeraCrypt releases | VeraCrypt's code at the fork point, plus the durability and security fixes in [BUGLOG.md](BUGLOG.md) |

## FSKit

[FSKit](https://developer.apple.com/documentation/fskit) is Apple's framework
for file systems that run as app extensions in user space. The FSKit build of
LambCrypt decrypts the volume in a worker process and serves the decrypted
image through a sandboxed FSKit module. macOS attaches that image with Disk
Images and mounts it without macFUSE or FUSE-T. Unpartitioned FAT volumes use
Apple's own `msdos` driver.

The FSKit build is a separate app, `LambCrypt-FSKit.app`, with its own bundle
identifier. It requires an Apple Developer signing identity and a provisioning
profile with the FSKit Module capability. Signed development builds have
passed read-only and read-write trials with HFS+ and FAT12/16/32 volumes on
macOS 26 (arm64). Notarized release packaging and the macFUSE performance
comparison are still open. The [FSKit migration plan](FSKIT-MIGRATION.md)
records each stage and its evidence.

## Fixes beyond upstream

Fixes made in LambCrypt so far include:

- **Header durability:** volume headers are flushed to stable storage
  (`F_FULLFSYNC` on macOS) before the backup header is written. Header
  backup export writes a new file, syncs it and renames it into place, so it
  never truncates an existing backup first.
- **Volume expansion:** a failure during expansion no longer leaves a
  container whose size and headers disagree.
- **Privilege boundaries:** stricter checks on the Unix elevated service,
  the executables it runs, its temporary directories and AppImage elevation,
  plus private auxiliary mount directories for FUSE-T.
- **Key derivation and input:** an out-of-range PIM is rejected instead of
  overflowing, a cancelled key derivation is reported as cancelled, and the
  text-mode password prompt has a length limit.
- **macOS mount lifecycle:** fixes to mount discovery, dismount and cleanup
  for all three backends.

Most of these defects are also present in upstream VeraCrypt. Each entry in
[BUGLOG.md](BUGLOG.md) names the location, the symptom, the fix and its
regression check.

# Project status

- **There are no LambCrypt binary releases yet.** Build LambCrypt from source
  as described below.
- macFUSE remains the default macOS backend. The FSKit build is experimental:
  use it with disposable volumes and keep backups.
- LambCrypt does not build or test the inherited Windows code. Windows
  changes in [BUGLOG.md](BUGLOG.md) are marked as not compiled. On Windows,
  use [VeraCrypt](https://veracrypt.io/).
- Third-party audits of this fork are recorded in the repository root, for
  example [SOURCE-AUDIT-2026-11-21.md](SOURCE-AUDIT-2026-11-21.md).

# Installing LambCrypt

## macOS

You need an Apple silicon Mac running macOS 26 or later.

1. Install the Xcode Command Line Tools and [Homebrew](https://brew.sh), then
   the build dependencies:

   ```sh
   xcode-select --install
   brew install pkg-config yasm wxwidgets
   ```

2. Install one FUSE backend:

   - **macFUSE** (default): `brew install --cask macfuse`, then follow
     macFUSE's prompts to allow its system extension in System Settings.
   - **FUSE-T**: install it from [fuse-t.org](https://www.fuse-t.org/). FUSE-T
     does not need a system extension.

   The experimental FSKit build needs neither. See
   [The FSKit build](#the-fskit-build).

3. Build the app:

   ```sh
   git clone https://github.com/e3742526/LambCrypt.git
   cd LambCrypt
   ./src/Build/build_lambcrypt_macosx.sh -b      # macFUSE
   ./src/Build/build_lambcrypt_macosx.sh -b -f   # or FUSE-T
   ```

   The app is written to `src/Main/LambCrypt.app`. A `-b` build links to
   Homebrew's wxWidgets, so keep that package installed.

4. Install the app and the `lambcrypt` command:

   ```sh
   cp -R src/Main/LambCrypt.app /Applications/
   chmod -R go-w /Applications/LambCrypt.app
   sudo mkdir -p /usr/local/bin
   sudo ln -s /Applications/LambCrypt.app/Contents/MacOS/LambCrypt /usr/local/bin/lambcrypt
   ```

   To build an installer package instead, install
   [Packages](https://github.com/idrassi/packages/releases)
   (`brew install --cask packages`) and add `-p` to the build command. The
   package installs the app and the `lambcrypt` link.

5. Check the build: `lambcrypt --text --test` runs the built-in algorithm
   self-tests.

### The FSKit build

The FSKit build needs a paid Apple Developer Program membership, an App ID
with the FSKit Module capability and a matching provisioning profile.
Follow the [integrator checklist](FSKIT-MIGRATION.md#integrator-checklist) to
sign it, then:

1. Copy `src/Main/LambCrypt-FSKit.app` to `/Applications`.
2. Open System Settings → General → Login Items & Extensions → By Category →
   File System Extensions, and turn on **LambCrypt FSKit**.

`LambCrypt-FSKit.app` and `LambCrypt.app` can be installed side by side.

## Linux

Use the [Linux build guide](./doc/html/en/CompilingGuidelineLinux.html) for
your distribution's dependencies, then:

```sh
git clone https://github.com/e3742526/LambCrypt.git
cd LambCrypt/src
make                 # or: make NOGUI=1 for a console-only build
sudo make install
```

`sudo make install` copies the program to `/usr/bin/lambcrypt` and the mount
helper to `/usr/sbin/mount.lambcrypt`. To build `.deb` or `.rpm` packages
named `lambcrypt` and `lambcrypt-console`, use the scripts in
[Building from source](#linux-and-bsd). On Arch Linux, use the
[Arch package build](#arch-linux-package-build).

An AppImage or a user-local build can only perform privileged operations
through a matching LambCrypt installed in a trusted, root-owned system
directory.

## FreeBSD and OpenBSD

FreeBSD 14 and later and OpenBSD 7.8 and later build as Linux does, with
`gmake` instead of `make`.

## Windows

LambCrypt has no Windows release. The Windows source keeps VeraCrypt's
driver, installer and boot loader identities, so a Windows build from this
tree would collide with an installed VeraCrypt. Use VeraCrypt on Windows.
Volumes are compatible either way.

Don't distribute Windows binaries built from this tree. They still carry the
VeraCrypt name, which the license does not allow on a modified version.

## Moving from VeraCrypt

LambCrypt and VeraCrypt can be installed on the same system. They use
different command names, app names and preferences folders.

1. Dismount all volumes in VeraCrypt before mounting them in LambCrypt.
   Don't mount the same volume in both programs at once.
2. Optional: to keep your settings, quit both programs and copy the XML files
   (`Configuration.xml`, `Favorite Volumes.xml`, `Default Keyfiles.xml` and
   any others) from VeraCrypt's folder to LambCrypt's:

   | System | VeraCrypt folder | LambCrypt folder |
   | --- | --- | --- |
   | macOS | `~/Library/Application Support/VeraCrypt` | `~/Library/Application Support/LambCrypt` |
   | Linux and BSD | `~/.config/VeraCrypt` | `~/.config/LambCrypt` |

3. Update scripts and `fstab` entries that call `veracrypt` or
   `mount.veracrypt` to use `lambcrypt` and `mount.lambcrypt`.

Your volumes stay as they are, and VeraCrypt can still open them.

## Uninstalling

Uninstalling LambCrypt leaves your volumes untouched.

- **macOS:** dismount all volumes and quit LambCrypt. Delete
  `/Applications/LambCrypt.app` and run `sudo rm /usr/local/bin/lambcrypt`.
  For the FSKit build, turn off LambCrypt FSKit in System Settings, then
  delete `/Applications/LambCrypt-FSKit.app`. Preferences are in
  `~/Library/Application Support/LambCrypt`.
- **Linux:** remove the package with your package manager, or run
  `sudo lambcrypt-uninstall.sh` if you used the standalone installer.

# Building from source

## macOS

Build with the macOS SDK from the active Xcode installation. macFUSE,
FUSE-T and FSKit builds default to a macOS 26.0 deployment target even when
Xcode provides a newer SDK.

[build_lambcrypt_macosx.sh](./src/Build/build_lambcrypt_macosx.sh) options:

| Option | Effect |
| --- | --- |
| `-b` | Use Homebrew's wxWidgets and build for the local architecture |
| `-f` | Build for FUSE-T instead of macFUSE |
| `-p` | Also build the installer package (needs Packages) |
| `-l` | Use a local wxWidgets build and skip universal binaries |
| `-t <target>` | Set the deployment target (default 26.0) |
| `-v <version>` | Set the wxWidgets version |

Without `-b` or `-l`, the script builds wxWidgets statically from source. It
expects the wxWidgets sources next to the checkout: if `src` is
`/Users/joe/Projects/LambCrypt/src`, wxWidgets goes in
`/Users/joe/Projects/wxWidgets-3.2.10` by default.

To build without Homebrew, install pkg-config from
https://pkgconfig.freedesktop.org/releases/pkg-config-0.29.2.tar.gz:

`$ CFLAGS="-Wno-int-conversion" CXXFLAGS="-Wno-int-conversion" ./configure --with-internal-glib`

`$ make`

`$ sudo make install`

Then install macFUSE from https://macfuse.github.io/ or FUSE-T from
https://www.fuse-t.org/.

Use the [local signing template](src/Setup/MacOSX/signing.env.example) to set
signing values outside the checkout. Keep certificates and their private keys
in Keychain. The experimental FSKit build supports Apple Development signing
with a matching FSKit Module provisioning profile. The [FSKit migration
plan](FSKIT-MIGRATION.md#integrator-checklist) covers setup and verification.

The macOS package build uses the upstream-maintained [Packages tool](https://github.com/idrassi/packages/releases).

Test instructions are in [Tests/README-macos-lifecycle.md](Tests/README-macos-lifecycle.md).

## Linux and BSD

See the [Linux build guide](./doc/html/en/CompilingGuidelineLinux.html) for dependencies and build commands.

### Requirements

- GNU Make
- GNU C++ Compiler 4.0 or compatible
- YASM 1.3.0 or newer (x86/x64 architecture only)
- pkg-config
- wxWidgets 3.0 shared library and header files installed or
  wxWidgets 3.0 library source code (available at https://www.wxwidgets.org)
- FUSE library and header files (available at https://github.com/libfuse/libfuse)
- PCSC-lite library and header files (available at https://github.com/LudovicRousseau/PCSC)

### Instructions

1. Run `cd src` from the checkout root.

2. If you have no wxWidgets shared library installed, run the following
   command to configure the wxWidgets static library for LambCrypt and to
   build it:

   `$ make WXSTATIC=1 WX_ROOT=/usr/src/wxWidgets wxbuild`

   The variable `WX_ROOT` must point to the location of the source code of the
   wxWidgets library. Output files will be placed in the './wxrelease/'
   directory.

3. To build LambCrypt, run the following command:

   `$ make`

   or if you have no wxWidgets shared library installed:

   `$ make WXSTATIC=1`

4. If successful, the LambCrypt executable should be located in the directory
   `src/Main` as `lambcrypt` on Linux and BSD.

FreeBSD (14 and later) and OpenBSD (7.8 and later) use the same requirements
and instructions, with `gmake` instead of `make`.

Reproducible build note: when `SOURCE_DATE_EPOCH` is not set, a build from a
git checkout uses the HEAD commit timestamp, while a build from a release
tarball uses the release date in `src/Common/Tcdefs.h` at 00:00 UTC. To
reproduce official release artifacts from a git checkout, set
`SOURCE_DATE_EPOCH` explicitly or build from the release tarball. Vendored
LambCrypt sources tracked in another git checkout are treated the same way and
use that checkout's HEAD timestamp.

Both the generated `.deb` and `.rpm` packages are reproducible, including with
older RPM versions that lack the `SOURCE_DATE_EPOCH`/`_buildhost` build macros.

By default, a universal executable supporting both graphical and text user
interface (through the switch --text) is built.
On Linux, a console-only executable, which requires no GUI library, can be
built using the 'NOGUI' parameter:

`$ make NOGUI=1 WXSTATIC=1 WX_ROOT=/usr/src/wxWidgets wxbuild`

`$ make NOGUI=1 WXSTATIC=1`

On macOS, building a console-only executable is not supported.

On Linux, an AppImage or a user-local build needs a matching LambCrypt
installation in a trusted system directory for operations that require
elevation. The elevated service executable and its path components must be
root-owned and protected from group and other-user writes.

### Arch Linux package build

Arch Linux users can build and install a package from the current checkout with
makepkg:

`$ cd src/Build/Packaging/arch`

`$ makepkg -si`

AppIndicator support is disabled by default. To enable it, set `INDICATOR=1`
in the environment when running makepkg:

`$ INDICATOR=1 makepkg -si`

This adds `libayatana-appindicator` to the package dependencies and passes
`INDICATOR=1` to the LambCrypt build. Leave the variable unset or set it to `0`
to disable support. If a package has already been built, add `-f` to rebuild it.
The [Ayatana package](https://archlinux.org/packages/extra/x86_64/libayatana-appindicator/)
provides both the development files and the runtime library.

For release builds, follow the [Arch packaging instructions](./src/Build/Packaging/arch/README.md)
to generate `PKGBUILD.release` and set its source checksum, then run:

`$ INDICATOR=1 makepkg -p PKGBUILD.release -si`

Use the same `INDICATOR` setting when generating `.SRCINFO` so that the
dependency metadata matches the package.

### DEB and RPM packages

`src/Build/build_cmake_deb.sh` builds `.deb` packages.
`src/Build/build_cmake_rpm.sh` and `src/Build/build_cmake_opensuse.sh` build
`.rpm` packages. Each builds a GUI package, `lambcrypt`, and a console
package, `lambcrypt-console`, with static wxWidgets libraries. The scripts
expect the wxWidgets 3.2.5 sources in a directory named `wxWidgets-3.2.5`
next to the LambCrypt checkout or in `/tmp`, along with the usual build
dependencies, CMake and `dpkg` or `rpmbuild`.

AppIndicator support is disabled by default. Pass `INDICATOR` to
the RPM scripts to enable Ayatana AppIndicator support in the GUI package:

```sh
./src/Build/build_cmake_rpm.sh INDICATOR
# To also use FUSE3:
./src/Build/build_cmake_rpm.sh INDICATOR FUSE3
```

The build selects GTK3 when `pkg-config` finds `gtk+-3.0`, and GTK2 otherwise.
Install the GTK development files and the corresponding Ayatana development
package:

| Distribution | GTK3 development package | GTK2 development package (where available) |
| --- | --- | --- |
| Fedora / CentOS / RHEL and compatible distributions | `libayatana-appindicator-gtk3-devel` | `libayatana-appindicator-gtk2-devel` |
| openSUSE | `libayatana-appindicator3-devel` | `libayatana-appindicator-devel` |

The Ayatana package must provide `ayatana-appindicator3-0.1` for GTK3 or
`ayatana-appindicator-0.1` for GTK2 through `pkg-config`.

The scripts reuse an existing `wxBuildGui` without checking its GTK version.
Rebuild wxWidgets if the selected GTK version has changed.

For distribution-provided Ayatana packages, the minimum releases are Fedora
38, Enterprise Linux 9 (with EPEL) and openSUSE Leap 15.0; openSUSE Tumbleweed
also provides them. Install the GTK3 development packages if your distribution
does not provide GTK2. See [Fedora/EPEL packages](https://packages.fedoraproject.org/pkgs/libayatana-appindicator/)
and [openSUSE package](https://build.opensuse.org/package/show/openSUSE:Factory/libayatana-appindicator).

With `INDICATOR`, the scripts check for these development files using
`pkg-config` and stop before building if they are missing. Builds without
`INDICATOR` do not require Ayatana.

With AppIndicator enabled, the GUI RPM requires
`libayatana-appindicator-gtk3` (or `libayatana-appindicator-gtk2`) on Fedora,
CentOS, RHEL and compatible distributions, and `libayatana-appindicator3-1`
(or `libayatana-appindicator1`) on openSUSE. Console packages do not require it.
When packaging a GUI built with `make INDICATOR=1` through CMake directly, pass
`-DVC_WITH_INDICATOR=TRUE` to record the matching RPM dependency.

## Windows (inherited, not maintained)

LambCrypt does not build, sign or release the Windows code. Binaries built
from it are named VeraCrypt, so they must not be distributed until the Windows
code is renamed. These notes come from upstream VeraCrypt and are kept for
reference. See the
[upstream Windows build guide](./doc/html/en/CompilingGuidelineWin.html) for
the toolchain.

The 64-bit editions of Windows require a digital signature on kernel drivers.
Official VeraCrypt `.sys` files are signed with IDRIX's certificate, so a
locally built, unsigned driver differs from the official binaries and will
not load on a standard Windows installation.

The folder "Signing" contains a batch file (sign.bat) that signs all
components with a code signing certificate from the certificate store and
builds the installer and MSI package. It assumes a GlobalSign-issued
certificate. Set the environment variable `WSDK81` to the Windows SDK for
Windows 8.1 installation directory first. To generate MSI packages, WiX
Toolset v3.11 must be installed.

Release Setup and Portable packages verify Authenticode against the release
certificate fingerprint compiled into `src/Common/Dlgcode.c`. When using a
different release certificate, update the fingerprint and verify the final
signed packages in Windows.

The repository contains upstream pre-built EFI boot loader binaries under
`src\Boot\EFI`. The EFI boot loader source is licensed under LGPL and is
available at https://github.com/veracrypt/VeraCrypt-DCS. For build
instructions, see `src\Boot\EFI\Readme.txt`.

# Contributing

Use the [LambCrypt issue tracker](https://github.com/e3742526/LambCrypt/issues)
to report bugs or discuss changes, and submit pull requests against `main`.
Please don't send LambCrypt reports to the VeraCrypt project. If a bug is
also present in upstream VeraCrypt, report it there separately.

# Legal information

LambCrypt is distributed under the same terms as VeraCrypt: the
[VeraCrypt License](License.txt), which combines the Apache License 2.0 and
the TrueCrypt License 3.0, together with the third-party licenses it contains.

- **LambCrypt's own changes and additions** are licensed under the Apache
  License 2.0. Portions derived from TrueCrypt remain under the TrueCrypt
  License 3.0. LambCrypt adds no other license terms.
- **Notices:** [src/NOTICE](src/NOTICE) holds the required attribution
  notices, including LambCrypt's. Every package and the macOS app include
  `License.txt` and `NOTICE`, and Help → Legal Notices in the app shows the
  license.
- **Changed files:** files changed from VeraCrypt carry a "Modified for
  LambCrypt" notice. [MODIFICATIONS.md](MODIFICATIONS.md) lists the changed
  files that can't hold one. Run `python3 Tests/check_modification_notices.py`
  before a release.
- **Source code:** the complete source is available free of charge from this
  repository. The About window links to it.
- **Names and logos:** LambCrypt doesn't use the VeraCrypt or TrueCrypt names
  or logos to identify itself, and isn't endorsed by their authors.
- **Before distributing binaries:** keep `License.txt`, `NOTICE`, the
  "Based on TrueCrypt" line in the About window and the source code link
  intact.

## Copyright information

Upstream VeraCrypt copyright notice

Copyright (c) 2026 AM Crypto. All rights reserved.  

Portions of this software:  
Copyright (c) 2026 AM Crypto. All rights reserved.  
Copyright (c) 2013-2025 IDRIX. All rights reserved.  
Copyright (c) 2003-2012 TrueCrypt Developers Association. All rights reserved.  
Copyright (c) 1998-2000 Paul Le Roux. All rights reserved.  
Copyright (c) 1998-2008 Brian Gladman, Worcester, UK. All rights reserved.  
Copyright (c) 1995-2023 Jean-loup Gailly and Mark Adler.  
Copyright (c) 2016 Disk Cryptography Services for EFI (DCS), Alex Kolotnikov  
Copyright (c) 1999-2023 Dieter Baron and Thomas Klausner.  
Copyright (c) 2013, Alexey Degtyarev. All rights reserved.  
Copyright (c) 1999-2016 Jack Lloyd. All rights reserved.  
Copyright (c) 2013-2019 Stephan Mueller <smueller@chronox.de>  
Copyright (c) 1999-2023 Igor Pavlov  

For more information, please see the legal notices attached to parts of the
source code.

## Trademark information

LambCrypt uses the names VeraCrypt and TrueCrypt only to describe the origin
of its code. Any trademarks contained in the source code, binaries and
documentation are the property of their respective owners.

# Further information

- [Upstream attribution and compatibility](UPSTREAM.md)
- [FSKit migration plan and evidence](FSKIT-MIGRATION.md)
- [LambCrypt bug log](BUGLOG.md)
- [LambCrypt releases](https://github.com/e3742526/LambCrypt/releases)
- [Upstream VeraCrypt documentation](https://veracrypt.io/en/Documentation.html)
