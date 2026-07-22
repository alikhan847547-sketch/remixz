@echo off
REM Lanza Cleaner X sin mostrar CMD (usa VBS + pythonw)
cd /d "%~dp0"
wscript.exe "%~dp0ejecutar_Cleaner_X.vbs"
exit /b 0
