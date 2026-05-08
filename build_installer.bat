@echo off
REM ============================================================
REM  Pulsemail — Compilar a .exe + generar instalador
REM ============================================================
REM  Pre-requisitos (instalar UNA sola vez):
REM    1. Python 3.11+ con: pip install flet html2image plyer pillow
REM    2. Inno Setup 6 (gratis): https://jrsoftware.org/isdl.php
REM       (Asegurate de que iscc.exe esté en C:\Program Files (x86)\Inno Setup 6\)
REM
REM  Uso:
REM    Doble click en este .bat (o ejecutar desde cmd)
REM
REM  Resultado:
REM    installer_output\PulsemailSetup_v1.0.0.exe
REM ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo  PULSEMAIL - Build del instalador
echo ============================================================
echo.

REM === 1) Generar el icono .ico desde el .png si no existe ===
if not exist "logo-app.ico" (
    echo [1/4] Generando logo-app.ico desde logo-app.png...
    python -c "from PIL import Image; img = Image.open('logo-app.png').convert('RGBA'); img.save('logo-app.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
    if errorlevel 1 (
        echo  ERROR: no se pudo generar logo-app.ico
        echo  Asegurate de tener Pillow instalado: pip install Pillow
        pause
        exit /b 1
    )
) else (
    echo [1/4] logo-app.ico ya existe, saltando.
)

REM === 2) Limpiar build anterior ===
echo [2/4] Limpiando build anterior...
if exist "build" rmdir /s /q "build"
if exist "dist"  rmdir /s /q "dist"
if not exist "installer_output" mkdir "installer_output"

REM === 3) Compilar a .exe con flet pack ===
echo.
echo [3/4] Compilando con flet pack (esto tarda 1-3 minutos)...
echo.

flet pack interfaz.py ^
    --name "Pulsemail" ^
    --product-name "Pulsemail" ^
    --product-version "1.0.0" ^
    --file-version "1.0.0.0" ^
    --company-name "Pulsemail" ^
    --copyright "Pulsemail (c) 2026" ^
    --icon "logo-app.ico" ^
    --add-data "logo-app.png;." ^
    --add-data "logo-app.ico;." ^
    --add-data "ITH-logo.png;." ^
    --add-data "icon-process.svg;." ^
    --add-data "icon-cost.svg;." ^
    --add-data "icon-prod.svg;." ^
    --add-data "icon-solution.svg;." ^
    --add-data "icon-calendar.svg;." ^
    --add-data "icon-whatsapp.svg;." ^
    --add-data "enviar_correos.py;." ^
    --hidden-import "plyer.platforms.win.notification" ^
    --hidden-import "plyer.platforms.win" ^
    --hidden-import "plyer.platforms" ^
    --hidden-import "plyer"

if errorlevel 1 (
    echo.
    echo  ERROR: flet pack falló. Revisá los mensajes arriba.
    pause
    exit /b 1
)

REM flet pack genera "dist\Pulsemail.exe" (onefile). Inno Setup espera
REM una carpeta "dist\Pulsemail\" — la armamos.
if not exist "dist\Pulsemail" mkdir "dist\Pulsemail"
if exist "dist\Pulsemail.exe" move /y "dist\Pulsemail.exe" "dist\Pulsemail\Pulsemail.exe" >nul

REM === 4) Generar el instalador con Inno Setup ===
echo.
echo [4/4] Empaquetando instalador con Inno Setup...
echo.

set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"

if not exist "%ISCC%" (
    echo  ERROR: No se encontró Inno Setup en:
    echo    C:\Program Files ^(x86^)\Inno Setup 6\
    echo    C:\Program Files\Inno Setup 6\
    echo.
    echo  Descargalo gratis de: https://jrsoftware.org/isdl.php
    pause
    exit /b 1
)

"%ISCC%" "installer\pulsemail.iss"

if errorlevel 1 (
    echo.
    echo  ERROR: Inno Setup falló. Revisá los mensajes arriba.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  LISTO!
echo ============================================================
echo.
echo  Instalador generado en:
echo    %~dp0installer_output\PulsemailSetup_v1.0.0.exe
echo.
echo  Para distribuir, mandale ese .exe a tus usuarios.
echo  Al ejecutarlo:
echo    - Si es la primera vez: instala Pulsemail en %%LOCALAPPDATA%%\Pulsemail
echo    - Si ya estaba instalado: ofrece actualizar y recomienda backup
echo.
pause
