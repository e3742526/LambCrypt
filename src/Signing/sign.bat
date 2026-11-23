@REM Modified for LambCrypt by the LambCrypt contributors. Changes from VeraCrypt are in the git history; see UPSTREAM.md.
PATH=%PATH%;%WSDK81%\bin\x86;C:\Program Files (x86)\Windows Kits\10\bin\10.0.19041.0\x86

set VC_VERSION=1.27.0
set VC_VERSION_NBRE=1.27.0
set SIGNINGPATH=%~dp0
cd %SIGNINGPATH%

rem call "..\..\doc\chm\create_chm.bat"

cd %SIGNINGPATH%

rem sign using SHA-256
signtool sign /v /sha1 86E1D426731E79117452F090188A828426B29B5F /ac GlobalSign_SHA256_EV_CodeSigning_CA.cer /fd sha256 /tr http://timestamp.digicert.com /td SHA256 "..\Release\Setup Files\LambCrypt-x64.exe" "..\Release\Setup Files\LambCrypt Format-x64.exe" "..\Release\Setup Files\LambCryptExpander-x64.exe" "..\Release\Setup Files\LambCrypt-arm64.exe" "..\Release\Setup Files\LambCrypt Format-arm64.exe" "..\Release\Setup Files\LambCryptExpander-arm64.exe" "..\Release\Setup Files\LambCryptSetup.dll" "..\Release\SDK Files\x64\LambCryptFormat.dll" "..\Release\SDK Files\arm64\LambCryptFormat.dll"

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
mkdir docs\html
mkdir docs\EFI-DCS
xcopy /E /V /Y ..\..\..\doc\html\* docs\html\.
copy "..\..\..\doc\chm\LambCrypt User Guide*.chm" docs\.
copy "..\..\..\doc\EFI-DCS\*.pdf" docs\EFI-DCS\.
del docs.zip
tar -a -cf docs.zip docs
"LambCrypt Setup.exe" /p
"LambCrypt Portable.exe" /p
LambCryptCOMRegBase.exe /p

cd %SIGNINGPATH%
signtool sign /v /sha1 86E1D426731E79117452F090188A828426B29B5F /ac GlobalSign_SHA256_EV_CodeSigning_CA.cer /fd sha256 /tr http://timestamp.digicert.com /td SHA256 "..\Release\Setup Files\LambCrypt COMReg.exe"

cd "..\Release\Setup Files\"
call build_msi_x64.bat %VC_VERSION_NBRE%
if errorlevel 1 exit /b 1
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
signtool sign /v /sha1 86E1D426731E79117452F090188A828426B29B5F /ac GlobalSign_SHA256_EV_CodeSigning_CA.cer /fd sha256 /tr http://timestamp.digicert.com /td SHA256 "..\Release\Setup Files\LambCrypt Setup %VC_VERSION%.exe" "..\Release\Setup Files\LambCrypt Portable %VC_VERSION%.exe" "..\Release\Setup Files\bin\LambCrypt_Setup_x64_%VC_VERSION_NBRE%.msi" "..\Release\Setup Files\bin\LambCrypt_Setup_x64_%VC_VERSION_NBRE%_en-us.msi"

pause
