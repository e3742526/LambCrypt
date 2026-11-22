# LambCrypt

LambCrypt is an independently maintained [VeraCrypt](https://github.com/veracrypt/VeraCrypt)
derivative focused on optimizing disk encryption for Apple silicon Macs running
macOS 26 (Tahoe) and later.

LambCrypt maintains backward compatibility with VeraCrypt volumes. It uses the
VeraCrypt volume format and `.hc` extension, so existing volumes can be mounted
without conversion.
See [Upstream and compatibility](UPSTREAM.md) for platform-specific details and inherited identifiers.

Based on TrueCrypt, freely available at [http://www.truecrypt.org/](http://www.truecrypt.org/).

The Unix command is `lambcrypt`. The macOS application is `LambCrypt.app`.
English is the only supported language for the application, installers, and bundled documentation.

[Documentation](doc/html/en/Documentation.html) · [Report an issue](https://github.com/e3742526/LambCrypt/issues) · [License](License.txt)

# Contents

[I. Windows](#i-windows)

[II. Linux and Mac OS X](#ii-linux-and-mac-os-x)

[III. FreeBSD and OpenBSD](#iii-freebsd-and-openbsd)

[IV. Third-Party Developers (Contributors)](#iv-third-party-developers-contributors)

[V. Legal Information](#v-legal-information)

[VI. Further Information](#vi-further-information)

# I. Windows

## Inherited Windows build and signing instructions

The Windows source includes inherited VeraCrypt driver, installer and boot
components. See the [upstream Windows build guide](./doc/html/en/CompilingGuidelineWin.html)
for the original toolchain and signing requirements.

IMPORTANT:

The 64-bit editions of Windows Vista and later versions of Windows, and in
some cases (e.g. playback of HD DVD content) also the 32-bit editions do not
allow the VeraCrypt driver to run without an appropriate digital signature.
Therefore, all .sys files in official VeraCrypt binary packages are digitally
signed with the digital certificate of the IDRIX, which was issued by
GlobalSign certification authority. At the end of each official .exe and
.sys file, there are embedded digital signatures and all related certificates
(i.e. all certificates in the relevant certification chain, such as the
certification authority certificates, CA-MS cross-certificate, and the
IDRIX certificate).

Keep this in mind if you compile VeraCrypt and compare your binaries with the
official binaries. If your binaries are unsigned, the sizes of the official
binaries will usually be approximately 10 KiB greater than the sizes of your
binaries (there may be further differences if you use a different version of
the compiler, or if you install a different or no service pack for Visual
Studio, or different hotfixes for it, or if you use different versions of
the required SDKs).

## Upstream Windows signing and packaging

First, create an environment variable 'WSDK81' pointing to the Windows SDK
for Windows 8.1 installation directory.

The folder "Signing" contains a batch file (sign.bat) that will sign all
VeraCrypt components using a code signing certificate present on the
certificate store and build the final installation setup and MSI package.
The batch file assumes that the code signing certificate is issued by
GlobalSign. This is the case for IDRIX's certificate. If yours is issued by
another CA, then you should put its intermediate certificates in the "Signing"
folder and modify sign.bat accordingly.

To generate MSI packages, WiX Toolset v3.11 must be installed.

## VeraCrypt EFI Boot Loader:

This repository contains upstream pre-built EFI binaries under src\Boot\EFI.
The source code of VeraCrypt EFI Boot Loader is licensed under LGPL and
it is available at https://github.com/veracrypt/VeraCrypt-DCS.
For build instructions, please refer to the file src\Boot\EFI\Readme.txt.

# II. Linux and Mac OS X

See the [Linux build guide](./doc/html/en/CompilingGuidelineLinux.html) for dependencies and build commands.

## Requirements for Building LambCrypt for Linux and Mac OS X:

- GNU Make
- GNU C++ Compiler 4.0 or compatible
- Apple Xcode or Xcode command line tools (Mac OS X only)
- YASM 1.3.0 or newer (Linux only, x86/x64 architecture only)
- pkg-config
- wxWidgets 3.0 shared library and header files installed or
  wxWidgets 3.0 library source code (available at https://www.wxwidgets.org)
- FUSE library and header files (available at https://github.com/libfuse/libfuse
  and https://macfuse.github.io/)
- PCSC-lite library and header files (available at https://github.com/LudovicRousseau/PCSC)

## Instructions for Building LambCrypt for Linux and Mac OS X:

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
   `src/Main` as `lambcrypt` on Linux and BSD or `LambCrypt` on macOS.

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

On MacOSX, building a console-only executable is not supported.

## Arch Linux package build:

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

## RPM packages with AppIndicator support:

AppIndicator support is disabled by default. Pass `INDICATOR` to
`src/Build/build_cmake_rpm.sh` or `src/Build/build_cmake_opensuse.sh` to enable
Ayatana AppIndicator support in the GUI package:

```sh
./src/Build/build_cmake_rpm.sh INDICATOR
# To also use FUSE3:
./src/Build/build_cmake_rpm.sh INDICATOR FUSE3
```

Both scripts accept the same options and build GUI and console packages with
static wxWidgets libraries. They expect the wxWidgets 3.2.5 sources in a
directory named `wxWidgets-3.2.5` next to the LambCrypt checkout or in `/tmp`,
along with the usual build dependencies, CMake and `rpmbuild`.

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

## Mac OS X specifics:

Under MacOSX, the latest installed SDK is used by default. To use a different version
of the SDK when building using make, you can export the environment variable VC_OSX_SDK:

`$ export VC_OSX_SDK=13.0`

For development dependencies management, you can use [homebrew](https://brew.sh).

`$ brew install pkg-config yasm wxwidgets`

You also need system dependencies

`$ brew install --cask macfuse packages`

After installing dependencies via brew, you can build a local development build

`$ ./src/Build/build_lambcrypt_macosx.sh -b`

If you want to build the package, you must pass `-p` to the build script above. The app bundle is written to `src/Main/LambCrypt.app`.

If you prefer to build from sources, or without homebrew, pkg-config and packages must be installed.

Get pkg-config from https://pkgconfig.freedesktop.org/releases/pkg-config-0.29.2.tar.gz and
compile using the following commands:

`$ CFLAGS="-Wno-int-conversion" CXXFLAGS="-Wno-int-conversion" ./configure --with-internal-glib`

`$ make`

`$ sudo make install`

After making sure pkg-config is available, download and install macFUSE from
https://macfuse.github.io/

The [build_lambcrypt_macosx.sh](./src/Build/build_lambcrypt_macosx.sh) script performs the
full build of LambCrypt including the creation of the installer pkg. It expects
to find the wxWidgets sources at the same level as where you put
LambCrypt sources (i.e. if "src" path is "/Users/joe/Projects/LambCrypt/src"
then wxWidgets should be at "/Users/joe/Projects/wxWidgets-3.2.10" by default)

Use the [local signing template](src/Setup/MacOSX/signing.env.example) to set
signing values outside the checkout. Keep certificates and their private keys
in Keychain. The experimental FSKit build supports Apple Development signing
with a matching FSKit Module provisioning profile. The [FSKit migration
plan](FSKIT-MIGRATION.md#integrator-checklist) covers setup and verification.

Because of incompatibility issues with macFUSE, the SDK 10.9 generates a
LambCrypt binary that has issues communicating with the macFUSE kernel extension.
Thus, we recommend using a different macOS SDK version for building LambCrypt.

The macOS Package build can use the upstream-maintained [Packages tool](https://github.com/idrassi/packages/releases).

# III. FreeBSD and OpenBSD

FreeBSD is supported starting from version 14.
OpenBSD is supported starting from version 7.8.
The build requirements and instructions are the same as Linux except that gmake
should be used instead of make.

# IV. Third-Party Developers (Contributors)

Use the [LambCrypt issue tracker](https://github.com/e3742526/LambCrypt/issues) to report bugs or discuss changes.
Submit pull requests against `main`.

# V. Legal Information

## Copyright Information

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

## Trademark Information

Any trademarks contained in the source code, binaries, and/or in the
documentation, are the sole property of their respective owners.

# VI. Further Information

- [LambCrypt releases](https://github.com/e3742526/LambCrypt/releases)
- [Upstream VeraCrypt documentation](https://veracrypt.jp/en/Documentation.html)
- [Upstream attribution and compatibility](UPSTREAM.md)
