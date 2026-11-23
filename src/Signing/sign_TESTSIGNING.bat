@REM Modified for LambCrypt by the LambCrypt contributors. Changes from VeraCrypt are in the git history; see UPSTREAM.md.
PATH=%PATH%;%WSDK81%\bin\x86

set VC_VERSION=1.27.0
set VC_VERSION_NBRE=1.27.0
set SIGNINGPATH=%~dp0
cd %SIGNINGPATH%

rem sign using SHA-256
signtool sign /v /sha1 86E1D426731E79117452F090188A828426B29B5F /ac GlobalSign_SHA256_EV_CodeSigning_CA.cer /fd sha256 /tr http://timestamp.digicert.com /td SHA256 "..\Release\Setup Files\lambcrypt-x64.sys" "..\Release\Setup Files\lambcrypt-arm64.sys"

signtool sign /v /sha1 86E1D426731E79117452F090188A828426B29B5F /ac GlobalSign_SHA256_EV_CodeSigning_CA.cer /fd sha256 /tr http://timestamp.digicert.com /td SHA256 "..\Release\Setup Files\LambCrypt-x64.exe" "..\Release\Setup Files\LambCrypt Format-x64.exe" "..\Release\Setup Files\LambCryptExpander-x64.exe" "..\Release\Setup Files\LambCrypt-arm64.exe" "..\Release\Setup Files\LambCrypt Format-arm64.exe" "..\Release\Setup Files\LambCryptExpander-arm64.exe" "..\Release\Setup Files\LambCrypt COMReg.exe" "..\Release\Setup Files\LambCryptSetup.dll"

rem create setup and MSI
cd "..\Release\Setup Files\"
copy ..\..\LICENSE .
copy ..\..\License.txt .
copy ..\..\NOTICE .
copy ..\..\Resources\Texts\License.rtf .
copy ..\..\Common\LambCrypt.ico .
copy ..\..\Setup\LambCrypt_setup_background.bmp .
copy ..\..\Setup\LambCrypt_setup.bmp .
copy ..\..\Setup\Setup.ico .
del *.xml
rmdir /S /Q docs
mkdir docs\html\en
mkdir docs\EFI-DCS
xcopy /E /V /Y ..\..\..\doc\html\* docs\html\.
copy "..\..\..\doc\chm\LambCrypt User Guide*.chm" docs\.
copy "..\..\..\doc\EFI-DCS\*.pdf" docs\EFI-DCS\.
del docs.zip
tar -a -cf docs.zip docs
"LambCrypt Setup.exe" /p
"LambCrypt Portable.exe" /p

del LICENSE
del License.txt
del NOTICE
del License.rtf
del LambCrypt.ico
del LambCrypt_setup_background.bmp
del LambCrypt_setup.bmp
del Setup.ico
del "LambCrypt User Guide*.chm"
del docs.zip
rmdir /S /Q docs

cd %SIGNINGPATH%

rem sign Setup using SHA-256
signtool sign /v /sha1 86E1D426731E79117452F090188A828426B29B5F /ac GlobalSign_SHA256_EV_CodeSigning_CA.cer /fd sha256 /tr http://timestamp.digicert.com /td SHA256 "..\Release\Setup Files\LambCrypt Setup %VC_VERSION%.exe" "..\Release\Setup Files\LambCrypt Portable %VC_VERSION%.exe" 

pause
