@echo off
REM ============================================================
REM  Pulsemail - Compilar a .exe + generar instalador
REM ============================================================
REM  Pre-requisitos (instalar UNA sola vez):
REM    1. Python 3.11+ con: pip install flet html2image plyer pillow pyinstaller
REM    2. Inno Setup 6 (gratis): https://jrsoftware.org/isdl.php
REM
REM  Uso: doble click en este .bat
REM
REM  Versionado: la version vive en el archivo VERSION (raiz).
REM    python bump_version.py patch
REM ============================================================

cd /d "%~dp0"

REM === 0) Leer version desde el archivo VERSION ===
if not exist "VERSION" (
    echo  ERROR: No se encontro el archivo VERSION en la raiz del proyecto.
    echo  Ejecuta: python bump_version.py set 1.0.0
    goto :error
)
set "APP_VERSION="
set /p APP_VERSION=<VERSION
if "%APP_VERSION%"=="" (
    echo  ERROR: El archivo VERSION esta vacio.
    goto :error
)
set "APP_FILE_VERSION=%APP_VERSION%.0"

echo.
echo ============================================================
echo  PULSEMAIL v%APP_VERSION% - Build del instalador
echo ============================================================
echo.

REM === 1) Generar el icono .ico desde el .png si no existe ===
if not exist "logo-app.ico" (
    echo [1/4] Generando logo-app.ico desde logo-app.png...
    python -c "from PIL import Image; img = Image.open('logo-app.png').convert('RGBA'); img.save('logo-app.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
    if errorlevel 1 (
        echo  ERROR: no se pudo generar logo-app.ico
        echo  Asegurate de tener Pillow instalado: pip install Pillow
        goto :error
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
echo [3/4] Compilando con flet pack (tarda 1-3 minutos)...
echo.

REM Usamos _build_helper.py en vez de invocar flet directamente porque:
REM   - python -m flet NO funciona en flet 0.84
REM   - flet.exe no siempre esta en PATH (Windows Store Python)
REM   - El helper importa flet_cli.cli.main y lo invoca con sys.argv,
REM     lo cual es portable a cualquier instalacion de Python
python _build_helper.py "%APP_VERSION%"
if errorlevel 1 (
    echo.
    echo  ERROR: flet pack fallo. Revisa los mensajes arriba.
    goto :error
)

REM flet pack genera "dist\Pulsemail.exe" (onefile). Inno Setup espera
REM una carpeta "dist\Pulsemail\" - la armamos.
if not exist "dist\Pulsemail" mkdir "dist\Pulsemail"
if exist "dist\Pulsemail.exe" move /y "dist\Pulsemail.exe" "dist\Pulsemail\Pulsemail.exe" >nul

REM === 4) Generar el instalador con Inno Setup ===
echo.
echo [4/4] Empaquetando instalador con Inno Setup...
echo.

REM Buscar ISCC.exe en las ubicaciones habituales (v7 y v6, sistema y
REM per-usuario de winget en %LOCALAPPDATA%\Programs). Toma el primero.
set "ISCC="
for %%P in (
    "%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe"
    "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
    "C:\Program Files (x86)\Inno Setup 7\ISCC.exe"
    "C:\Program Files\Inno Setup 7\ISCC.exe"
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    "C:\Program Files\Inno Setup 6\ISCC.exe"
) do if not defined ISCC if exist "%%~P" set "ISCC=%%~P"

if not defined ISCC (
    echo  ERROR: No se encontro Inno Setup (ISCC.exe).
    echo  Instalalo con:  winget install JRSoftware.InnoSetup.7
    echo  o descargalo de: https://jrsoftware.org/isdl.php
    goto :error
)
echo  Inno Setup: "%ISCC%"

"%ISCC%" "installer\pulsemail.iss"
if errorlevel 1 (
    echo.
    echo  ERROR: Inno Setup fallo. Revisa los mensajes arriba.
    goto :error
)

echo.
echo ============================================================
echo  LISTO!
echo ============================================================
echo.
echo  Instalador generado en:
echo    %~dp0installer_output\PulsemailSetup_v%APP_VERSION%.exe
echo.
echo  Para distribuir, mandaselo a tus usuarios.
echo.
pause
exit /b 0

:error
echo.
echo ============================================================
echo  Build cancelada por error.
echo ============================================================
pause
exit /b 1
