# Compilar Pulsemail a `.exe` instalable

Esta guía explica cómo generar el instalador profesional `.exe` de
Pulsemail listo para distribuir.

---

## Resultado final

Un solo archivo: **`installer_output\PulsemailSetup_v1.0.0.exe`**.

Lo que hace al ejecutarlo:

- **Primera instalación**: instala Pulsemail en `%LOCALAPPDATA%\Pulsemail\`
  (sin pedir permisos de administrador), crea acceso directo en el
  escritorio y en el menú inicio, aparece en "Agregar/quitar programas"
  con el logo y nombre.
- **Actualización**: detecta la versión previa, muestra un mensaje
  profesional recomendando backup, y reemplaza el `.exe` sin tocar los
  datos del usuario (config, contactos, historial, rechazados,
  respuestas, firma, tema).
- **Desinstalación**: pregunta antes de borrar y deja los datos del
  usuario intactos por si reinstala más tarde.

---

## Pre-requisitos (instalar UNA sola vez en tu PC de desarrollo)

### 1. Python 3.11+ con dependencias

Ya las tenés instaladas si la app corre con `py interfaz.py`. Asegurate
de tener también Pillow (para generar el `.ico`):

```bat
pip install flet html2image plyer pillow
```

### 2. Inno Setup 6 (gratis)

Descargá de: https://jrsoftware.org/isdl.php

Durante la instalación dejá la ruta por defecto:
`C:\Program Files (x86)\Inno Setup 6\`

---

## Cómo compilar

Doble click en **`build_installer.bat`** (o ejecutalo desde una terminal
en la carpeta del proyecto).

El script hace 4 pasos automáticos:

1. **Genera `logo-app.ico`** desde `logo-app.png` con Pillow (sólo si
   no existe ya).
2. **Limpia builds anteriores** (`build/`, `dist/`).
3. **Compila a `.exe`** con `flet pack`. Esto tarda 1-3 minutos.
4. **Empaqueta el instalador** con Inno Setup leyendo
   `installer/pulsemail.iss`.

Resultado: `installer_output\PulsemailSetup_v1.0.0.exe`

---

## Qué hace el instalador para el usuario final

### Instalación nueva

1. Doble click en `PulsemailSetup_v1.0.0.exe`.
2. Wizard en español: elige carpeta (default `%LOCALAPPDATA%\Pulsemail`),
   elige si crear acceso directo en escritorio.
3. Instala los archivos.
4. Pregunta si quiere abrir Pulsemail al terminar.

### Actualización (cuando publicás v1.0.1, v1.1.0, etc.)

1. El usuario ejecuta el nuevo `PulsemailSetup_v1.X.X.exe`.
2. Inno Setup detecta la versión previa via su `AppId` fijo.
3. Aparece un diálogo:
   > **Detectamos una instalación previa de Pulsemail (v1.0.0).**
   > Esta versión: v1.0.1.
   >
   > ¿Querés ACTUALIZAR a la nueva versión?
   >
   > **IMPORTANTE: Antes de actualizar te recomendamos hacer un BACKUP de
   > tu configuración. Para hacerlo:**
   >  1. Abrí Pulsemail (versión actual)
   >  2. Andá a Configuración → Datos
   >  3. Apretá "Exportar configuración completa"
   >  4. Guardá el ZIP en un lugar seguro
   >
   > La actualización NO borra tus datos, pero el backup es la
   > práctica recomendada por si algo falla.
4. Si dice **Sí**: reemplaza el `.exe` y archivos del bundle. Los
   datos del usuario (config.json, contactos.csv, registros, historial)
   quedan intactos porque viven al lado del `.exe` y NO están en la
   lista de archivos del bundle (no son sobrescritos).

### Desinstalación

El usuario va a "Agregar/quitar programas" y elige Pulsemail. Aparece:

> ¿Querés desinstalar Pulsemail?
>
> Tus datos (configuración, contactos, historial, etc.) NO se van a
> borrar — quedan en la carpeta de instalación por si reinstalás más
> tarde.
>
> Si querés borrar TODO incluyendo tus datos, exportá primero un
> backup desde Configuración → Datos.

---

## Cómo subir la versión (cuando publicás un update)

Editá dos archivos:

1. **`build_installer.bat`** → buscá:
   ```
   --product-version "1.0.0"
   --file-version "1.0.0.0"
   ```
   y subí los números (ej: `1.0.1` y `1.0.1.0`).

2. **`installer/pulsemail.iss`** → buscá:
   ```
   #define MyAppVersion    "1.0.0"
   ```
   y subí a `1.0.1`.

Después corré `build_installer.bat` de nuevo. Te genera
`PulsemailSetup_v1.0.1.exe`.

> **NO cambies el `AppId`** del `.iss`. Ese GUID es lo que permite a
> Inno Setup detectar instalaciones previas. Si lo cambiás, los
> usuarios verían dos Pulsemail distintos en "Agregar/quitar
> programas".

---

## Estructura de carpetas durante el build

```
Correo masivo/
  interfaz.py              ← código fuente
  enviar_correos.py        ← código fuente
  logo-app.png             ← logo (lo provee el usuario)
  logo-app.ico             ← se genera auto desde el .png
  ITH-logo.png
  icon-*.svg
  build_installer.bat      ← script de build
  COMPILAR.md              ← este archivo

  installer/
    pulsemail.iss          ← script Inno Setup

  build/                   ← intermedio (lo borra el bat al iniciar)
  dist/                    ← intermedio (lo borra el bat al iniciar)
    Pulsemail/
      Pulsemail.exe        ← bundle de flet pack

  installer_output/        ← OUTPUT FINAL
    PulsemailSetup_v1.0.0.exe   ← lo que distribuís a los usuarios
```

---

## Dónde quedan los datos del usuario instalado

Después de la primera ejecución del `.exe`, en
`%LOCALAPPDATA%\Pulsemail\` van a aparecer:

```
%LOCALAPPDATA%\Pulsemail\
  Pulsemail.exe              ← binario (lo reemplaza la actualización)
  config.json                ← configuración del usuario
  contactos.csv              ← CSV con contactos
  registro_envios.json       ← progreso del día
  registro_rechazados.json
  registro_depurados.json
  registro_respuestas.json
  registro_vistos.json
  sistema_errores.log
  historial/
    2026/
      05/
        2026-05-03.json
        ...
```

Los archivos de datos (todo lo que NO es `Pulsemail.exe`) son lo que el
usuario debe respaldar con "Exportar configuración completa" desde
**Configuración → Datos**.

---

## Resolución de problemas

### `flet pack` falla con "comando no encontrado"

Asegurate de tener `flet` instalado:
```bat
pip install --upgrade flet
```

### Inno Setup no encuentra `dist\Pulsemail\Pulsemail.exe`

Significa que `flet pack` falló en el paso 3. Mirá el log de error
en la terminal y ejecutá:
```bat
flet pack interfaz.py --icon logo-app.ico
```
para ver el mensaje de error real.

### El usuario instala pero el `.exe` no abre

Probable causa: faltan assets en el bundle. Revisá que en
`build_installer.bat` estén todos los `--add-data` para los archivos
que usa la app (íconos SVG, logos PNG).

### La actualización borra los datos del usuario

NO debería pasar — los datos están al lado del `.exe`, no adentro
del bundle. Si pasa, revisá `[Files]` del `.iss`: NO debe incluir
patterns que matcheen `config.json`, `contactos.csv`, `registro_*.json`
ni la carpeta `historial/`.
