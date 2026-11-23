# Modifications to VeraCrypt

LambCrypt is a modified version of VeraCrypt, forked from upstream commit
[f38c8090](https://github.com/veracrypt/VeraCrypt/commit/f38c80905e0adb484fb32cb9d188c07bbc10c2ad).
This file is the modification notice that the Apache License 2.0, section
4(b), requires for changed files.

- Every upstream file that LambCrypt changed and that can hold a comment
  carries this notice near its top: "Modified for LambCrypt by the LambCrypt
  contributors."
- The files listed below were also changed but cannot carry an inline notice,
  because they are images, icons, compiled help, or XML catalogues and
  installer definitions read by strict parsers.
- Files that LambCrypt added are its own work. See [src/NOTICE](src/NOTICE)
  for their license.
- The git history records every individual change. [UPSTREAM.md](UPSTREAM.md)
  summarizes them.

`python3 Tests/check_modification_notices.py` checks this against upstream.
Run it with `--fix` after changing another upstream file.

## Changed files without an inline notice

<!-- BEGIN FILES WITHOUT INLINE NOTICE -->
- `doc/chm/VeraCrypt User Guide.chm`
- `doc/chm/en/VeraCrypt.hhc`
- `doc/chm/en/VeraCrypt.hhp`
- `src/Build/Resources/MacOSX/Info.plist.legacy.xml`
- `src/Build/Resources/MacOSX/Info.plist.xml`
- `src/Common/Language.xml`
- `src/Common/Textual_logo_288dpi.bmp`
- `src/Common/Textual_logo_96dpi.bmp`
- `src/Common/Textual_logo_background.bmp`
- `src/Common/VeraCrypt.ico`
- `src/Common/VeraCrypt_Volume.ico`
- `src/Common/VeraCrypt_mounted.ico`
- `src/ExpandVolume/Logo_288dpi.bmp`
- `src/ExpandVolume/Logo_96dpi.bmp`
- `src/Format/VeraCrypt_Wizard.bmp`
- `src/Main/Forms/TrueCrypt.fbp`
- `src/Mount/Logo_288dpi.bmp`
- `src/Mount/Logo_96dpi.bmp`
- `src/Release/Setup Files/Product64.wxs`
- `src/Release/Setup Files/ProductARM64.wxs`
- `src/Release/Setup Files/Strings-en.wxl`
- `src/Setup/FreeBSD/lambcrypt.xml`
- `src/Setup/Linux/lambcrypt.xml`
- `src/Setup/MacOSX/lambcrypt.pkgproj`
- `src/Setup/MacOSX/lambcrypt_Legacy.pkgproj`
- `src/Setup/MacOSX/lambcrypt_fuse-t.pkgproj`
- `src/Setup/Setup.ico`
- `src/Setup/VeraCrypt_setup.bmp`
- `src/Setup/VeraCrypt_setup_background.bmp`
- `src/SetupDLL/Setup.ico`
- `src/SetupDLL/VeraCrypt_setup.bmp`
- `src/SetupDLL/VeraCrypt_setup_background.bmp`
<!-- END FILES WITHOUT INLINE NOTICE -->
