@REM Modified for LambCrypt by the LambCrypt contributors. Changes from VeraCrypt are in the git history; see UPSTREAM.md.
PATH=%PATH%;C:\Program Files (x86)\HTML Help Workshop

set CHMBUILDPATH=%~dp0
cd %CHMBUILDPATH%\en

xcopy /E ..\..\html\en\* .

hhc VeraCrypt.hhp

del /F /Q *.html *.css *.jpg *.gif *.png *.svg *.js
rmdir /s /Q CompilingGuidelineWin

move /Y "VeraCrypt User Guide.chm" "..\VeraCrypt User Guide.chm"

cd /d "%CHMBUILDPATH%"
