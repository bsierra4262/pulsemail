# Instalación y compilación

Pulsemail se distribuye como un instalador de Windows (`PulsemailSetup_vX.Y.Z.exe`) generado
con **Inno Setup**. Esta guía cubre las tres formas de trabajar con el proyecto: instalarlo,
ejecutarlo desde el código fuente y compilar el instalador.

---

## 1. Requisitos

| Componente | Mínimo | Por qué |
| --- | --- | --- |
| Windows | 10 / 11 de 64 bits | El instalador, el diálogo de archivos y el icono de la ventana usan la API de Windows |
| Python | 3.11 | Sólo para ejecutar desde el código o compilar |
| Flet | 0.84.0 (fijado) | Interfaz de escritorio; versiones posteriores cambiaron la API |
| Chrome o Chromium | cualquiera reciente | Renderiza los correos HTML en la vista Conversación (opcional) |
| Inno Setup | 6 o 7 | Sólo para generar el instalador |
| Cuenta de correo | Gmail o Google Workspace con contraseña de aplicación | Envío por SMTP y lectura de respuestas por IMAP |

---

## 2. Instalar la aplicación

1. Ejecutar `PulsemailSetup_vX.Y.Z.exe`. **No pide permisos de administrador**: se instala en
   `%LOCALAPPDATA%\Pulsemail\`, con acceso directo en el escritorio y en el menú Inicio.
2. Abrir Pulsemail e ir a **Configuración → Cuenta**:
   - correo de la cuenta;
   - **contraseña de aplicación** de Google (Cuenta de Google → Seguridad → Verificación en
     dos pasos → Contraseñas de aplicaciones). No es la contraseña normal de la cuenta;
   - límite diario de envíos.
3. **Verificar conexión**: el panel lateral pasa a «SMTP activo».
4. En **Contactos → Importar CSV**, cargar la base con estas columnas:

   ```csv
   Nombre,Apellidos,Nombre de Cuenta,Correo electrónico,Correo electrónico secundario,Correo electrónico terciario
   Ana,Gómez,Andina Textil,ana.gomez@andinatextil.example,,
   ```

5. En **Configuración → Mensaje**, elegir el formato (texto plano o HTML), editar el asunto y
   el cuerpo (`@nombre` se reemplaza por el nombre de pila) y mandar un **correo de prueba**.
6. Desde el **Dashboard**, «Iniciar campaña».

El manual completo, con la explicación de cada pantalla y las buenas prácticas para no caer en
spam, está en [`md/DOCS_USUARIO.md`](md/DOCS_USUARIO.md).

### Actualizar

Ejecutar el instalador de la versión nueva. Inno Setup detecta la instalación anterior por su
`AppId` fijo, recomienda exportar un respaldo (Configuración → Datos → Exportar configuración
completa) y reemplaza sólo el ejecutable: **la configuración, los contactos, los registros y el
historial no se tocan**, porque no forman parte del paquete.

### Desinstalar

Desde «Agregar o quitar programas». Los datos del usuario se conservan en la carpeta de
instalación por si se vuelve a instalar.

---

## 3. Ejecutar desde el código fuente

```bash
git clone https://github.com/bsierra4262/pulsemail.git
cd pulsemail
python -m pip install -r requirements.txt
python interfaz.py
```

En este modo los datos del usuario (`config.json`, `contactos.csv`, `historial/`, …) se crean
junto a `interfaz.py` y están excluidos por `.gitignore`.

`dependencias.txt` tiene la misma lista con comentarios, en formato de script de Windows.

---

## 4. Compilar el instalador

### Requisitos de compilación (una sola vez)

```bat
python -m pip install -r requirements.txt
winget install JRSoftware.InnoSetup.7
```

### Compilar

Doble clic en **`build_installer.bat`** (o ejecutarlo desde una terminal en la raíz). Hace
cuatro pasos:

1. Genera `logo-app.ico` desde `logo-app.png` con Pillow, si no existe.
2. Limpia `build/` y `dist/`.
3. Compila el `.exe` con `flet pack` a través de `_build_helper.py`. El helper además
   **empaqueta el cliente de escritorio de Flet**: sin esto, el primer arranque intentaría
   descargarlo y fallaría en equipos sin internet o con certificados interceptados.
4. Arma el instalador con Inno Setup (`installer/pulsemail.iss`).

Resultado: `installer_output\PulsemailSetup_vX.Y.Z.exe`.

### Versión

La versión vive en un único lugar, el archivo `VERSION`, que leen tanto
`build_installer.bat` como `installer/pulsemail.iss`:

```bash
python bump_version.py patch --notes "Descripción del cambio"
```

Sube el número y agrega la entrada en `CHANGELOG.md`. **No cambiar el `AppId`** del `.iss`:
es lo que permite detectar la instalación previa y actualizarla.

### Estructura durante la compilación

```
pulsemail/
├─ interfaz.py · enviar_correos.py   código fuente
├─ logo-app.png · logo-app.ico       icono de la aplicación
├─ ITH-logo.png                      logo por defecto del correo HTML
├─ build_installer.bat               script de compilación
├─ _build_helper.py                  invoca flet pack y empaqueta el cliente
├─ installer/pulsemail.iss           script de Inno Setup
├─ build/ · dist/                    intermedios (no se versionan)
└─ installer_output/                 instalador final (no se versiona)
```

### Problemas frecuentes

| Síntoma | Causa y solución |
| --- | --- |
| `No module named 'PyInstaller'` | Falta `pip install pyinstaller` |
| Inno Setup no encuentra `dist\Pulsemail\Pulsemail.exe` | Falló `flet pack` en el paso 3; revisar el mensaje anterior |
| El `.exe` abre y se cierra | Falta un recurso en el paquete: revisar la lista de `--add-data` en `_build_helper.py` |
| `ISCC.exe` no encontrado | Instalar Inno Setup 6 o 7 en una de las rutas habituales |

---

## 5. Verificación

```bash
python -m unittest discover -s tests -v
```

Sale con código `0` si todo está bien. No necesita red ni dependencias externas, y no envía
ningún correo: el envío se prueba contra un servidor SMTP falso en `127.0.0.1`.
