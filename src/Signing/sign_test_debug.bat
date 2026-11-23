@REM Modified for LambCrypt by the LambCrypt contributors. Changes from VeraCrypt are in the git history; see UPSTREAM.md.
PATH=%PATH%;%WSDK81%\bin\x86
set VC_VERSION=1.27.0
set VC_VERSION_NBRE=1.27.0
set PFXNAME=TestCertificate\idrix_codeSign.pfx
set PFXPASSWORD=idrix
set PFXCA=TestCertificate\idrix_TestRootCA.crt
set SHA256PFXNAME=TestCertificate\idrix_Sha256CodeSign.pfx
set SHA256PFXPASSWORD=idrix
set SHA256PFXCA=TestCertificate\idrix_SHA256TestRootCA.crt

set SIGNINGPATH=%~dp0
cd %SIGNINGPATH%

call "..\..\doc\chm\create_chm.bat"

cd %SIGNINGPATH%


rem sign using SHA-256
signtool sign /v /a /f %SHA256PFXNAME% /p %SHA256PFXPASSWORD% /ac %SHA256PFXCA% /fd sha256 /tr http://rfc3161timestamp.globalsign.com/advanced /td SHA256 "..\Debug\Setup Files\lambcrypt-x64.sys" "..\Debug\Setup Files\lambcrypt-arm64.sys" "..\Debug\Setup Files\LambCrypt-x64.exe" "..\Debug\Setup Files\LambCrypt Format-x64.exe" "..\Debug\Setup Files\LambCryptExpander-x64.exe" "..\Debug\Setup Files\LambCrypt-arm64.exe" "..\Debug\Setup Files\LambCrypt Format-arm64.exe" "..\Debug\Setup Files\LambCryptExpander-arm64.exe" "..\Debug\Setup Files\LambCrypt COMReg.exe"

rem create setup and MSI
cd "..\Debug\Setup Files\"
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
copy "..\..\Release\Setup Files\*.cat" .
copy "..\..\Release\Setup Files\lambcrypt.inf" .
del docs.zip
tar -a -cf docs.zip docs
"LambCrypt Setup.exe" /p
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

rem Can't dual-sign MSI files when using signtool (only jsign / osslsigncode can do that)

rem sign using SHA-1
signtool sign /v /a /f %PFXNAME% /p %PFXPASSWORD% /ac %PFXCA% /fd sha1 /t http://timestamp.digicert.com "..\Debug\Setup Files\LambCrypt Setup %VC_VERSION%.exe"

timeout /t 10

rem dual-sign Setup using SHA-256
signtool sign /v /a /f %SHA256PFXNAME% /p %SHA256PFXPASSWORD% /ac %SHA256PFXCA% /as /fd sha256 /tr http://rfc3161timestamp.globalsign.com/advanced /td SHA256 "..\Debug\Setup Files\LambCrypt Setup %VC_VERSION%.exe"

rem single sign MSI using SHA-256
signtool sign /v /a /f %SHA256PFXNAME% /p %SHA256PFXPASSWORD% /ac %SHA256PFXCA% /fd sha256 /tr http://rfc3161timestamp.globalsign.com/advanced /td SHA256 "..\Debug\Setup Files\bin\LambCrypt_Setup_x64_%VC_VERSION_NBRE%.msi" "..\Debug\Setup Files\bin\LambCrypt_Setup_x64_%VC_VERSION_NBRE%_en-us.msi" 

pause