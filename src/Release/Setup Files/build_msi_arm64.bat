::------------------------------------
::Define search paths here for Wix ToolSet and SDK (and SignTool optionnally)
::------------------------------------

@set SEARCH_WIX_PATH=C:\Program Files (x86)\WiX Toolset v3.14\bin

@set SEARCH_VC_DIR_PLATFORMSDK_1=C:\Program Files (x86)\Windows Kits\10\bin\10.0.19041.0\x86
@set SEARCH_VC_DIR_PLATFORMSDK_2=C:\Program Files (x86)\Windows Kits\10\bin\10.0.17763.0\x86
@set SEARCH_VC_DIR_PLATFORMSDK_3=C:\Program Files (x86)\Windows Kits\10\bin\10.0.17134.0\x86
@set SEARCH_VC_DIR_PLATFORMSDK_4=C:\Program Files (x86)\Windows Kits\10\bin\x86
@set SEARCH_VC_DIR_PLATFORMSDK_5=C:\Program Files\Microsoft Platform SDK\bin
@set SEARCH_VC_DIR_PLATFORMSDK_6=C:\Program Files (x86)\Windows Kits\8.1\bin\x86
@set SEARCH_VC_DIR_PLATFORMSDK_7=C:\Program Files (x86)\Windows Kits\8.0\bin\x86
@set SEARCH_VC_DIR_PLATFORMSDK_8=C:\Program Files (x86)\Microsoft SDKs\Windows\v7.1A\bin

::end of search paths

cd /d "%~dp0" || exit /b 1

::------------------------------------
:: Look for MsiInfo.exe
::------------------------------------

@echo [INFO] Define default value for VC_DIR_PLATFORMSDK if not defined yet
@echo [INFO] Input VC_DIR_PLATFORMSDK=%VC_DIR_PLATFORMSDK%
@set FILE_TO_FIND="MsiInfo.exe"
@echo [INFO] Looking for files: %FILE_TO_FIND%

@set FILE_NOT_FOUND=
@for %%i in (%FILE_TO_FIND%) do @if not exist "%VC_DIR_PLATFORMSDK%\%%~i" set FILE_NOT_FOUND=%%~i
@if "%FILE_NOT_FOUND%"=="" goto found_mssdk
@echo        Not found in "%VC_DIR_PLATFORMSDK%"

@set VC_DIR_PLATFORMSDK=%SEARCH_VC_DIR_PLATFORMSDK_1%
@set FILE_NOT_FOUND=
@for %%i in (%FILE_TO_FIND%) do @if not exist "%VC_DIR_PLATFORMSDK%\%%~i" set FILE_NOT_FOUND=%%~i
@if "%FILE_NOT_FOUND%"=="" goto found_mssdk
@echo        Not found in "%VC_DIR_PLATFORMSDK%"

@set VC_DIR_PLATFORMSDK=%SEARCH_VC_DIR_PLATFORMSDK_2%
@set FILE_NOT_FOUND=
@for %%i in (%FILE_TO_FIND%) do @if not exist "%VC_DIR_PLATFORMSDK%\%%~i" set FILE_NOT_FOUND=%%~i
@if "%FILE_NOT_FOUND%"=="" goto found_mssdk
@echo        Not found in "%VC_DIR_PLATFORMSDK%"

@set VC_DIR_PLATFORMSDK=%SEARCH_VC_DIR_PLATFORMSDK_3%
@set FILE_NOT_FOUND=
@for %%i in (%FILE_TO_FIND%) do @if not exist "%VC_DIR_PLATFORMSDK%\%%~i" set FILE_NOT_FOUND=%%~i
@if "%FILE_NOT_FOUND%"=="" goto found_mssdk
@echo        Not found in "%VC_DIR_PLATFORMSDK%"

@set VC_DIR_PLATFORMSDK=%SEARCH_VC_DIR_PLATFORMSDK_4%
@set FILE_NOT_FOUND=
@for %%i in (%FILE_TO_FIND%) do @if not exist "%VC_DIR_PLATFORMSDK%\%%~i" set FILE_NOT_FOUND=%%~i
@if "%FILE_NOT_FOUND%"=="" goto found_mssdk
@echo        Not found in "%VC_DIR_PLATFORMSDK%"

@set VC_DIR_PLATFORMSDK=%SEARCH_VC_DIR_PLATFORMSDK_5%
@set FILE_NOT_FOUND=
@for %%i in (%FILE_TO_FIND%) do @if not exist "%VC_DIR_PLATFORMSDK%\%%~i" set FILE_NOT_FOUND=%%~i
@if "%FILE_NOT_FOUND%"=="" goto found_mssdk
@echo        Not found in "%VC_DIR_PLATFORMSDK%"

@set VC_DIR_PLATFORMSDK=%SEARCH_VC_DIR_PLATFORMSDK_6%
@set FILE_NOT_FOUND=
@for %%i in (%FILE_TO_FIND%) do @if not exist "%VC_DIR_PLATFORMSDK%\%%~i" set FILE_NOT_FOUND=%%~i
@if "%FILE_NOT_FOUND%"=="" goto found_mssdk
@echo        Not found in "%VC_DIR_PLATFORMSDK%"

@echo [ERROR] MS Platform SDK 2008, Windows SDK v7.1, or Windows SDK 8.0/8.1/10 could not be found
@echo         If the path is not any of the above,
@echo         please define VC_DIR_PLATFORMSDK environment variable.
@exit /B 1

:found_mssdk
@echo        Found in "%VC_DIR_PLATFORMSDK%"

::------------------------------------
:: Look for the WiX compiler and linker
::------------------------------------

@echo [INFO] Check if WiX is installed
@echo [INFO] Default value for VC_DIR_WIX is set to %WIX%
@set VC_DIR_WIX=%WIX%
@set FILE_TO_FIND="candle.exe" "light.exe"
@echo [INFO] Looking for files: %FILE_TO_FIND%

@set FILE_NOT_FOUND=
@for %%i in (%FILE_TO_FIND%) do @if not exist "%VC_DIR_WIX%\%%~i" set FILE_NOT_FOUND=%%~i
@if "%FILE_NOT_FOUND%"=="" goto found_wix
@echo        Not found in "%VC_DIR_WIX%"

@set VC_DIR_WIX=%SEARCH_WIX_PATH%
@set FILE_NOT_FOUND=
@for %%i in (%FILE_TO_FIND%) do @if not exist "%VC_DIR_WIX%\%%~i" set FILE_NOT_FOUND=%%~i
@if "%FILE_NOT_FOUND%"=="" goto found_wix
@echo        Not found in "%VC_DIR_WIX%"

@echo [ERROR] WiX could not be found
@echo         Please install Wix3
@exit /B 1

:found_wix
@echo        Found in "%VC_DIR_WIX%"

::------------------------------------
:: Create the English Arm64 MSI installer
:: We make use of -sice:ICE09 to silence ICE09 warnings generated because we install non-permanent elements to 'SystemFolder'
::------------------------------------
@echo [INFO] Creating msi ARM64 installers

@echo [INFO] Making the en-us version in %cd%\out\arm64\en-us\
"%VC_DIR_WIX%\candle.exe" -dLang=en -arch arm64 -ext WixUIExtension -ext WiXUtilExtension ProductARM64.wxs -out out\arm64\en-us\Product.wixobj
@if NOT "%ERRORLEVEL%" == "0" goto msi_failed
"%VC_DIR_WIX%\candle.exe" -dLang=en -arch arm64 -ext WixUIExtension -ext WiXUtilExtension Custom_InstallDir.wxs -out out\arm64\en-us\Custom_InstallDir.wixobj
@if NOT "%ERRORLEVEL%" == "0" goto msi_failed
"%VC_DIR_WIX%\candle.exe" -dLang=en -arch arm64 -ext WixUIExtension -ext WiXUtilExtension Custom_InstallDirDlg.wxs -out out\arm64\en-us\Custom_InstallDirDlg.wixobj
@if NOT "%ERRORLEVEL%" == "0" goto msi_failed
"%VC_DIR_WIX%\Light.exe" -ext WixUIExtension -ext WiXUtilExtension -cultures:en-us -loc Strings-en.wxl out\arm64\en-us\Product.wixobj out\arm64\en-us\Custom_InstallDirDlg.wixobj out\arm64\en-us\Custom_InstallDir.wixobj -out out\arm64\en-us\VeraCrypt_Setup_%1_en-us.msi -pdbout out\arm64\en-us\VeraCrypt_Setup_%1_en-us.wixpdb -sice:ICE09
@if NOT "%ERRORLEVEL%" == "0" goto msi_failed

::------------------------------------
:: Keep the established default and en-us package filenames.
::------------------------------------

@set OUT_PATH=%cd%\out\arm64\
@echo [INFO] OUT_PATH=%OUT_PATH%

@set MSI_FILE_IN=VeraCrypt_Setup_%1
@set MSI_FILE_OUT=VeraCrypt_Setup_arm64_%1

:: Check that the English MSI was built
@set LANG=en-us
@IF NOT EXIST "%OUT_PATH%\%LANG%\%MSI_FILE_IN%_%LANG%.msi" goto msi_missing

@copy /Y "%OUT_PATH%\%LANG%\%MSI_FILE_IN%_%LANG%.msi" "%OUT_PATH%\%MSI_FILE_OUT%.msi" || goto msi_copy_failed

::------------------------------------
:: Set the default package's platform and English language ID
::------------------------------------
"%VC_DIR_PLATFORMSDK%\MsiInfo.Exe" "%OUT_PATH%\%MSI_FILE_OUT%.msi" /p Arm64;1033
@if NOT "%ERRORLEVEL%" == "0" goto msi_summary_failed

::------------------------------------
:: Copy to bin and remove out
::------------------------------------
if not exist bin mkdir bin
@copy /Y "%OUT_PATH%\%MSI_FILE_OUT%.msi" "%cd%\bin\%MSI_FILE_OUT%.msi" || goto msi_copy_failed
@copy /Y "%OUT_PATH%\%LANG%\%MSI_FILE_IN%_%LANG%.msi" "%cd%\bin\%MSI_FILE_OUT%_%LANG%.msi" || goto msi_copy_failed
@rmdir /S /Q "%cd%\out\arm64"

goto END

:msi_failed
@echo [ERR ] failed to create the MSI
@exit /B 1

:msi_summary_failed
@echo [ERR ] failed to set the English MSI summary information
@exit /B 1

:msi_copy_failed
@echo [ERR ] failed to copy the English MSI
@exit /B 1

:msi_missing
@echo [ERR ] Missing file '%OUT_PATH%\%LANG%\%MSI_FILE_IN%_%LANG%.msi'
@exit /B 1

:END
@echo end
@exit /B 0
