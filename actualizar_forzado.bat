@echo off
setlocal EnableExtensions
chcp 65001 >nul
title RemixZ — Actualizacion forzada
cd /d "%~dp0"

echo ============================================
echo  RemixZ Cleaner X — Update forzado
echo  (cierra la app y aplica la version de GitHub)
echo ============================================
echo.

REM Cerrar procesos que bloquean archivos (WinError 32)
echo [1/5] Cerrando RemixZ / Python de esta carpeta…
taskkill /IM "RemixZ_Cleaner_X.exe" /F >nul 2>&1
ping -n 2 127.0.0.1 >nul

set "ZIP=%TEMP%\remixz_force_update.zip"
set "EXTRACT=%TEMP%\remixz_force_extract"
set "REPO=SMPROJECT115/remixz"
set "URL=https://codeload.github.com/%REPO%/zip/refs/heads/main"

echo [2/5] Descargando %REPO% …
if exist "%ZIP%" del /f /q "%ZIP%" >nul 2>&1
if exist "%EXTRACT%" rmdir /s /q "%EXTRACT%" >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIP%' -UseBasicParsing -Headers @{'User-Agent'='RemixZ-ForceUpdate'} ; exit 0 } catch { Write-Host $_.Exception.Message ; exit 1 }"
if errorlevel 1 (
  echo ERROR: no se pudo descargar el update.
  echo Revisa internet o el repo: https://github.com/%REPO%
  pause
  exit /b 1
)

echo [3/5] Extrayendo…
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%EXTRACT%' -Force"
if errorlevel 1 (
  echo ERROR: no se pudo extraer el ZIP.
  pause
  exit /b 1
)

REM Carpeta raiz del zip de GitHub: repo-main\
for /d %%D in ("%EXTRACT%\*") do set "SRC=%%~fD"
if not defined SRC (
  echo ERROR: ZIP vacio o estructura inesperada.
  pause
  exit /b 1
)

echo [4/5] Copiando archivos a:
echo   %CD%
robocopy "%SRC%" "%CD%" /E /IS /IT /R:4 /W:2 /XD .git __pycache__ logs _pending_update /XF boot_error.log *.pyc *.log
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
  echo ERROR: robocopy fallo con codigo %RC%
  pause
  exit /b 1
)

REM Limpiar basura de updates a medias
if exist "_pending_update" rmdir /s /q "_pending_update" >nul 2>&1
if exist "_finish_update.cmd" del /f /q "_finish_update.cmd" >nul 2>&1
del /f /q "%ZIP%" >nul 2>&1
rmdir /s /q "%EXTRACT%" >nul 2>&1

echo [5/5] Listo. Iniciando RemixZ…
if exist "RemixZ_Cleaner_X.exe" (
  start "" "%CD%\RemixZ_Cleaner_X.exe"
) else if exist "ejecutar_Cleaner_X.vbs" (
  wscript.exe "%CD%\ejecutar_Cleaner_X.vbs"
) else if exist "RemixZ_Cleaner_X_App.py" (
  start "" pythonw "%CD%\RemixZ_Cleaner_X_App.py"
) else (
  echo No se encontro el ejecutable. Abre la app manualmente.
  pause
  exit /b 0
)

echo.
echo Actualizacion forzada completada.
ping -n 2 127.0.0.1 >nul
exit /b 0
