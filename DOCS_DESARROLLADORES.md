# Pulsemail — Documentación técnica para desarrolladores

> Suite de outreach automation construida en Python + Flet. Este documento explica la arquitectura, decisiones de diseño y cada bloque del código fuente.

---

## Índice

1. [Visión general y arquitectura](#1-visión-general-y-arquitectura)
2. [Stack tecnológico](#2-stack-tecnológico)
3. [Estructura del proyecto](#3-estructura-del-proyecto)
4. [Módulo `enviar_correos.py` (backend)](#4-módulo-enviar_correospy-backend)
5. [Módulo `interfaz.py` (frontend Flet)](#5-módulo-interfazpy-frontend-flet)
6. [Sistema de caché TTL](#6-sistema-de-caché-ttl)
7. [Integración IMAP / Gmail](#7-integración-imap--gmail)
8. [Renderizado HTML → PNG](#8-renderizado-html--png-de-correos)
9. [Reintentos y persistencia](#9-reintentos-de-red-y-persistencia)
10. [Compilación e instalador](#10-compilación-e-instalador)
11. [Convenciones y limitaciones](#11-convenciones-de-código-y-limitaciones-de-flet-084)

---

## 1. Visión general y arquitectura

Pulsemail es una aplicación de escritorio Windows que automatiza campañas de email en frío para outreach comercial. Combina:

- **Motor de envío** SMTP con templates HTML, reintentos resilientes a microcortes y persistencia del estado de campaña.
- **Lectura IMAP** para detectar respuestas, rebotes (bounces) y confirmaciones de Calendly.
- **Interfaz gráfica** tipo CRM con dashboard, tabla de contactos paginada, hilo de conversación renderizado idéntico a Gmail, estadísticas y configuración.

La arquitectura es deliberadamente **monolítica de dos archivos**:

```
┌─────────────────────────────────────────────────────────┐
│   interfaz.py   ←  UI Flet, threading, render HTML→PNG  │
│        ↓                                                 │
│   enviar_correos.py  ←  SMTP, IMAP, persistencia JSON   │
└─────────────────────────────────────────────────────────┘
```

`interfaz.py` importa `enviar_correos.py` y nunca al revés. La UI llama funciones del backend y registra **callbacks/hooks** para recibir notificaciones (estados de red, eventos de borrado IMAP). El backend no conoce nada de Flet — esto permite testear el motor de envío sin la UI y mantener el acoplamiento bajo.

**Decisión de mantener todo en dos archivos:** la cantidad de funciones es manejable (~70 en backend, ~60 en frontend) y partir el código en módulos pequeños complicaría la navegación porque hay muchas dependencias cruzadas entre helpers UI. Se prefiere la cohesión por archivo.

---

## 2. Stack tecnológico

| Tecnología | Versión | Propósito |
|---|---|---|
| Python | 3.11+ | Lenguaje base |
| Flet | 0.84.0 | UI multiplataforma (estricto: ver sección 11) |
| Pillow | reciente | PNG↔ICO, recorte de PNG, redimensionado de logos/firmas |
| html2image | reciente | Renderiza HTML del correo como PNG vía Chrome headless |
| plyer | reciente (opcional) | Toasts nativos Windows 10/11 |
| imaplib / smtplib / email | stdlib | Protocolos de correo |
| ctypes | stdlib | Win32 API directo (clipboard, AppUserModelID, icono ventana) |
| tkinter | stdlib | Diálogos `filedialog` (Flet 0.84 desktop no soporta `FilePicker`) |
| PyInstaller | reciente | Compilar a `.exe` (vía `flet pack`) |
| Inno Setup 6 | gratuita | Empaquetar instalador profesional |

Por qué Flet 0.84 y no una versión más nueva: 0.84 es la última que mantiene la API que el código usa (`ft.ControlState`, `ft.Padding`, etc.). Versiones posteriores rompieron compatibilidad y los workarounds documentados en este código están afinados para 0.84. Una migración a una versión más nueva implica revisar cada `ft.*` reference.

---

## 3. Estructura del proyecto

```
Correo masivo/
├── enviar_correos.py        ← Backend: SMTP, IMAP, persistencia, lógica
├── interfaz.py              ← Frontend Flet: UI, threading, render
├── build_installer.bat      ← Script de build para .exe + instalador
├── dependencias.txt         ← Lista comentada de pip installs
├── COMPILAR.md              ← Guía paso a paso para compilar
├── DOCS_DESARROLLADORES.md  ← Este documento
├── DOCS_USUARIO.md          ← Documentación de funcionalidades
│
├── logo-app.png/.ico        ← Ícono de la aplicación
├── ITH-logo.png             ← Logo cliente por defecto (sustituible)
├── icon-*.svg               ← Íconos del template HTML del correo
│
├── installer/
│   └── pulsemail.iss        ← Script Inno Setup
│
├── build/   dist/           ← (generados) Intermedios de PyInstaller
└── installer_output/        ← (generado) PulsemailSetup_v*.exe
```

### Archivos de datos del usuario (runtime, NO van en el bundle)

| Archivo | Contenido |
|---|---|
| `config.json` | Credenciales, servidores, firma, logo, URLs configurables, etc. |
| `contactos.csv` | Base de contactos para la campaña |
| `registro_envios.json` | Último correo enviado y conteo del día (para retomar) |
| `registro_pendiente.json` | Correo en cola de reintentos por caída de red |
| `registro_rechazados.json` | Bounces detectados |
| `registro_depurados.json` | Bounces que el usuario marcó como "depurados" |
| `registro_respuestas.json` | Respuestas de clientes + reuniones Calendly |
| `registro_vistos.json` | Hilos/respuestas que el usuario ya vio (para badges) |
| `registro_ignorados.json` | Hilos que el usuario ocultó del listado |
| `sistema_errores.log` | Log rotativo de errores (5 MB max, 3 backups) |
| `historial/AAAA/MM/AAAA-MM-DD.json` | Eventos por día (línea de tiempo) |

Estos archivos viven al lado del `.exe` (o de `interfaz.py` en modo desarrollo). El instalador NUNCA los toca durante una actualización — esto está garantizado en `installer/pulsemail.iss`, ver `[Files]` que sólo incluye `Pulsemail.exe` y assets, no archivos de datos.

---

## 4. Módulo `enviar_correos.py` (backend)

### 4.1 Resolución de carpetas (líneas 10-30)

```python
def _carpeta_app():
def _carpeta_assets():
```

**Por qué dos carpetas distintas:**
- `CARPETA_ACTUAL`: dónde viven los datos del usuario (`config.json`, etc). En modo desarrollo es `os.getcwd()`. Compilado, es la carpeta donde está el `.exe` (vía `os.path.dirname(sys.executable)`). Si pusiéramos los datos dentro del bundle de PyInstaller, una actualización los borraría.
- `CARPETA_ASSETS`: dónde viven los recursos read-only (logos, íconos SVG, plantillas). Compilado es `sys._MEIPASS` — la carpeta temporal que PyInstaller crea al ejecutar el bundle. Estos sí se reemplazan en una actualización (es lo deseable: nuevo logo, nuevos íconos).

Esta separación es la base de la "actualización segura" del instalador.

### 4.2 Constantes de campaña (líneas 50-69)

```python
ASUNTO       = "TECNOLOGÍA PARA EMPRESAS: ..."
URL_WHATSAPP = "https://wa.me/..."
URL_CALENDLY = "https://calendly.com/..."
TIEMPO_MINIMO, TIEMPO_MAXIMO = 25, 45
ACTIVOS_MULTIMEDIA = [...]
```

`TIEMPO_MINIMO/MAXIMO`: pausa aleatoria entre correos (`random.randint(25, 45)` segundos). **Este rango no es arbitrario:** valores menores activan los filtros anti-spam de Gmail (envíos demasiado rápidos = comportamiento robótico). Valores mayores hacen las campañas excesivamente lentas. 25-45 s da ~80-100 correos/hora, dentro del rango "humano".

`URL_*` y `ASUNTO` son los **defaults**. Las URLs son sobreescribibles desde Configuración (campos `url_calendly`, `url_whatsapp` en `config.json`). Quedan como constantes para retrocompatibilidad y como fallback si el usuario no las configuró.

`ACTIVOS_MULTIMEDIA` es una lista de tuplas `(archivo, content_id)` que se incrustan inline en cada correo. Los SVG se embeben con `Content-ID` (RFC 2392), no como adjuntos visibles. Gmail los renderiza dentro del cuerpo del mensaje.

### 4.3 Control de campaña (líneas 60-135)

```python
_STOP_CAMPANA = _t_mod.Event()
_RED_HOOK     = [None]
MAX_REINTENTOS_RED  = 1000
INTERVALO_REINTENTO = 10
```

**`_STOP_CAMPANA` es un `threading.Event`** y no un simple `bool` porque la UI corre en un thread y el motor de envío en otro. `Event` es thread-safe sin necesidad de Lock.

**`_RED_HOOK[0]`** es una lista de un elemento (no una variable simple) porque las funciones internas la mutan vía `_RED_HOOK[0] = cb`. En Python, `nonlocal` es alternativa pero requiere closure; con la lista, cualquier función puede leer/escribir sin declararse interior.

**`MAX_REINTENTOS_RED = 1000` × `INTERVALO_REINTENTO = 10s` = 2h 47min.** Este número se calculó así: queremos cubrir un corte de internet de oficina típico (1-3 horas en el peor caso), pero no infinito (si el usuario se va y queda corriendo días, gasta cuota Gmail al volver y manda emails atrasados que el destinatario ya no espera).

### 4.4 Pendiente de reintento (líneas 87-112)

```python
def cargar_pendiente() / guardar_pendiente() / borrar_pendiente()
```

`registro_pendiente.json` guarda el correo que **estaba intentándose** cuando se cortó internet o el usuario apretó Detener. Estructura:

```json
{
  "destino":  "cliente@empresa.com",
  "nombre":   "Juan Pérez",
  "intentos": 230,
  "fecha":    "2026-05-08 14:32:11"
}
```

`intentos` es el contador acumulado de reintentos a lo largo de TODAS las sesiones para ese correo. Cuando se reanuda con `intentos_previos=230`, le quedan 770 reintentos antes del tope global. Este diseño evita que un correo problemático consuma reintentos infinitos cada vez que el usuario abre la app.

Se guarda **cada 10 intentos** durante reintentos sucesivos. No cada uno: optimización de IO. Sobrevive a un crash perdiendo a lo sumo 100 segundos de progreso.

### 4.5 Configuración (líneas 140-240)

```python
_CONFIG_DEFAULTS = { ... }
def cargar_config() / guardar_config() / get_config_value()
def URL_CALENDLY_CFG() / URL_WHATSAPP_CFG() / _parsear_cc()
```

**`_CONFIG_DEFAULTS` como diccionario único** evita que nuevos campos rompan instalaciones viejas: `cfg = dict(_CONFIG_DEFAULTS); cfg.update(json.load(f))` agrega los defaults si el JSON del usuario es de una versión vieja.

**`_parsear_cc`** acepta separadores `,`, `;` o espacios. La razón: usuarios técnicos copian de hojas de cálculo donde el separador varía. Filtra entradas sin `@` para silenciosamente ignorar basura.

**`URL_*_CFG()` como funciones** y no constantes globales: se evalúan en runtime, así un cambio en Configuración se aplica sin reiniciar la app.

### 4.6 Verificación SMTP (líneas 246-280)

```python
def verificar_smtp(...):
```

Conecta + login y devuelve `(ok, mensaje)`. Acepta credenciales como parámetro **antes de guardarlas**, para que la UI valide al teclear sin persistir si fallan. Devuelve nombre humano del host (`"GMAIL SMTP activo"`) extraído del segundo segmento DNS — heurística simple que sirve para Gmail, Outlook, Yahoo, etc.

### 4.7 Estado y progreso del día (líneas 287-308)

```python
def cargar_estado() / guardar_estado() / estado_de_hoy()
```

`registro_envios.json` tiene `{ultimo_email, fecha, enviados_hoy}`. Si la fecha guardada es hoy → seguir contando; si es ayer → resetear contador. **No usa modificación del archivo**, usa fecha calendario explícita: el usuario puede haber cerrado la app a las 23:59 y abrirla a las 00:01 — el contador debe resetear aunque "hayan pasado 2 minutos".

### 4.8 Historial por día (líneas 312-360)

```python
def _ruta_historial_dia() / cargar_historial_dia() / guardar_evento_historial() / listar_dias_historial()
```

Estructura en disco: `historial/AAAA/MM/AAAA-MM-DD.json`. Anidado por año/mes para que `os.listdir()` no devuelva 365+ archivos al cabo de un año (Windows Explorer también lo agradece).

Cada evento tiene `{hora, tipo, mensaje}`. El campo `tipo` es uno de `info|warning|error|success` — la UI lo mapea a colores en `TIPOS_LOG`.

### 4.9 Armado del correo (líneas 366-460)

```python
def preparar_correo(nombre, destino):
```

Construye un `EmailMessage` con `set_content` (texto plano) + `add_alternative(html, subtype="html")` (HTML). Esta dualidad es **obligatoria** para evitar el filtro de spam: clientes muy viejos o reglas anti-spam descartan correos sólo-HTML.

El HTML usa **inline styles** (no `<link>` ni `<style>` externos) porque Gmail/Outlook ignoran las hojas externas. La `@import` del Google Font se incluye de adorno (Gmail la borra, Outlook desktop también) — el `font-family` con fallback `Arial, sans-serif` es lo que efectivamente renderiza.

**Logo personalizado:** la lógica del bucle `for ruta, id_imagen, es_absoluto in activos:` reemplaza el `ITH-logo.png` por el logo del usuario si lo configuró. El `cid:logo_intellihelp` del template HTML queda apuntando al mismo content-ID, así no hay que tocar el HTML.

**CC desde config:** si `correos_copia` está vacío no se agrega cabecera `Cc`. Gmail interpreta `Cc:` (vacío) como copia, lo cual es incorrecto — por eso la condición.

### 4.10 Envío con reintentos (líneas 466-570)

```python
def enviar_correo(msg, destino, intentos_previos=0, nombre=""):
```

Función central. Devuelve uno de cinco estados (no `True/False`):

| Estado | Significado | Acción del caller |
|---|---|---|
| `"enviado"` | Éxito | Avanzar al siguiente |
| `"rechazado"` | Destinatario inválido (`SMTPRecipientsRefused`) | Avanzar |
| `"auth"` | Credenciales rotas | Abortar campaña |
| `"agotado"` | 1000 reintentos sin éxito | Abortar, queda pendiente |
| `"detenido"` | Usuario apretó Detener | Abortar, queda pendiente |

Por qué strings y no enum: simplicidad y debugging — los strings aparecen literales en logs sin necesidad de `enum.value`.

**Notificaciones escalonadas vía `_emit_red()`:**
- intento 1 → `"caido"` (acaba de cortarse)
- intento 30 (~5 min) → `"inestable"` (microcortes prolongados)
- cada 100 → `"reintentando"` (progreso periódico, sólo log, sin toast)

Anti-spam de toasts implementado del lado UI (`_red_avisada` flags), no acá: queremos que el backend siga emitiendo eventos para que la UI decida — separación de responsabilidades.

**Espera interrumpible:** en vez de `time.sleep(10)`, hace `for _ in range(10): if campana_detenida(): return; time.sleep(1)`. Granularidad de 1 segundo permite que el botón Detener responda casi instantáneamente sin pegar al CPU.

### 4.11 Revisión de rebotes (líneas 575-670)

```python
def revisar_rebotes(fecha_actual, enviados_hoy):
```

Conecta a IMAP, busca el INBOX desde la fecha de hoy. Por cada bounce: parsea el cuerpo extrayendo el email destinatario que falló (regex), lo agrega a `registro_rechazados.json` filtrando por `contactos_set` (sólo cuentan los rebotes de NUESTRA campaña, no de correos personales del usuario que comparten cuenta Gmail).

**Remitentes que reconoce como bounces** — la búsqueda itera tres patrones en `FROM`:

```python
("mailer-daemon@googlemail.com", "mailer-daemon", "postmaster")
```

- `mailer-daemon@googlemail.com` → bounce explícito de Gmail.
- `mailer-daemon` → cualquier dominio que use ese local-part (Outlook, Yahoo, hosts custom).
- `postmaster` → estándar RFC 5321; lo usan Microsoft Exchange, Office 365, muchos hosts corporativos.

Dentro de la app la lista canónica vive en `_REMITENTES_REBOTE` ([enviar_correos.py:1040-1044](enviar_correos.py#L1040)) y se reutiliza en:

| Función | Archivo:línea | Para qué |
| --- | --- | --- |
| `revisar_rebotes` | enviar_correos.py:592 | Escaneo del día corriente al final de cada campaña |
| `revisar_rebotes_recientes` | enviar_correos.py:1092 | Re-escaneo de últimos 7 días disparado desde la UI |
| `borrar_correo_rebote_gmail` | enviar_correos.py:1228 | Mueve a papelera el bounce específico de un email |
| `_gmail_delete_worker` | enviar_correos.py:1452 | Cola batch — valida que el correo a borrar sea bounce real |
| `restaurar_correo_rebote_gmail` | enviar_correos.py:1607 | Busca el bounce en Trash para restaurarlo |
| `detectar_respuestas_y_calendly` | enviar_correos.py:2451 | Excluye bounces de la bandeja de respuestas |

**Match por substring (no exact match):** la búsqueda IMAP `FROM "postmaster"` matchea cualquier header que CONTENGA "postmaster" como substring del local-part o display name. Eso significa que entran:

- `MAILER-DAEMON@empresa.com` (mayúsculas, Yahoo histórico)
- `postmaster@cliente.es`
- `Mail Delivery Subsystem <postmaster@server.com>`
- `mail-daemon@dominio.com` (variante con guión usada por sendmail)
- `noreply-daemon@hostmonster.com` (algunos hosts compartidos)

Esto se complementa con un segundo filtro **del lado cliente** después del FETCH: comparamos `from_hdr.lower()` contra `"daemon"`, `"postmaster"` y `"mail-daemon"` ([enviar_correos.py:1452-1453](enviar_correos.py#L1452)). Esa redundancia de cinturón + tirantes evita falsos positivos cuando un servidor incluye "postmaster" en un encabezado distinto al `From`.

**Heurística de subject como fallback** ([enviar_correos.py:1103](enviar_correos.py#L1103)): algunos servers no firman como `mailer-daemon` pero sí ponen subjects característicos (`"Delivery Status Notification"`, `"Undelivered Mail Returned to Sender"`, `"Mail Delivery Failure"`). `revisar_rebotes_recientes` también busca por SUBJECT con esos patrones para captar bounces emitidos por servidores no estándar.

### 4.12 `main()` — loop principal de campaña (líneas 677-848)

```python
def main():
    reset_stop_campana()
    ...
    pendiente = cargar_pendiente()
    if pendiente:
        # retomar primero el correo en cola
    ...
    for fila in lista_clientes:
        if campana_detenida(): return
        if enviados >= limite: break
        ...
        resultado = enviar_correo(...)
        # match resultado
```

Diseño en tres fases:
1. **Reset de stop event** — por si quedó seteado de una corrida anterior.
2. **Retomar pendiente** — si hay un correo en `registro_pendiente.json`, lo procesa con `intentos_previos`. Esto garantiza que retomar nunca duplica correos: el pendiente era el que NO se envió, así que reenvíarlo no es duplicación.
3. **Loop del CSV** — itera contactos, salta hasta `ultimo_email` si existe (resume desde el último confirmado), y por cada uno llama `enviar_correo`.

**Salto hasta `ultimo_email`:** después de procesar pendiente recargo `cargar_estado()` por si el pendiente actualizó el último — esto evita que la primera iteración del CSV repita el correo recién enviado.

**Pausa entre correos también interrumpible** — mismo patrón que en `enviar_correo`.

### 4.13 Sistema de rechazados, depurados, vistos, ignorados (líneas 852-1030)

Cuatro conjuntos persistidos como JSON (no como sets, porque JSON no soporta `set` nativo — se serializa como `list` y al cargar se convierte a `set`).

- **Rechazados**: detectados por `revisar_rebotes`. Read-only desde la UI (la UI los lee pero no escribe; sólo el backend los detecta).
- **Depurados**: el usuario marca rechazados como "ya gestionados" para que dejen de aparecer. La UI puede mover estos correos a la papelera de Gmail vía cola IMAP.
- **Vistos**: hilos/respuestas ya leídos por el usuario. Sirve para badges de "no leído".
- **Ignorados**: hilos que el usuario eligió ocultar del listado.

Cada conjunto tiene `cargar_X()` y `marcar_X(item)`. Los `cargar_X` están **cacheados con TTL** (sección 6).

### 4.14 Cola de borrado IMAP en batch (líneas 1321-1540)

```python
def encolar_borrado_gmail(email_rechazado, callback=None):
def _gmail_delete_worker():
```

Diseño productor-consumidor con una sola conexión IMAP. La UI llama `encolar_borrado_gmail(email)` por cada email a depurar, lo cual:
1. Encola en `_GMAIL_DEL_QUEUE` (lista bajo `_GMAIL_DEL_LOCK`).
2. Si el worker no está corriendo, lo arranca en thread daemon.

El worker:
1. Login IMAP una sola vez.
2. Itera la cola. Por cada email:
   - Busca el bounce en INBOX por `BODY contains email_obj`.
   - Verifica que sea bounce real (FROM contiene `daemon`/`postmaster`).
   - Extrae el `In-Reply-To` del bounce → Message-ID original.
   - Mueve el bounce a Trash con `UID MOVE` (RFC 6851, atómico).
   - Busca en Sent / Inbox / All Mail el correo original con ese Message-ID exacto y lo mueve a Trash también.

**Por qué `UID MOVE` y no `COPY + STORE \Deleted + EXPUNGE`:** el segundo método sufre race conditions cuando hay varios items en cola — un `EXPUNGE` puede matar mensajes con `\Deleted` flag puestos por otro item. `UID MOVE` es atómico del lado del servidor.

**Por qué buscar en Inbox/All Mail además de Sent:** si el usuario restauró un correo previamente depurado, el original puede estar en Inbox (no en Sent). Sin esto, la re-depuración perdería el original.

**Por qué match por Message-ID exacto:** búsquedas tipo `TO email_obj` matchearían cualquier correo legítimo enviado a ese destinatario en cualquier campaña previa. Match por Message-ID garantiza que sólo se mueve el correo que efectivamente generó este bounce específico.

### 4.15 Restauración desde papelera (líneas 1542-1660)

```python
def restaurar_correo_rebote_gmail(email_rechazado):
```

Operación inversa al worker: busca en Trash bounces y correos originales matcheando el email rechazado, los mueve de vuelta a INBOX con `UID MOVE`.

Diseñado para la UI cuando el usuario decide "deshacer" una depuración.

### 4.16 Estadísticas globales (líneas 1664-1696)

```python
def obtener_estadisticas_globales():
```

Itera `historial/AAAA/MM/AAAA-MM-DD.json`, suma `enviados` y `rebotes` de cada día y devuelve también una serie temporal para graficar. La iteración usa `os.listdir` ordenado (no `glob` recursivo) por performance — el primer requiere parsing por archivo.

### 4.17 Renderizado de hilo de conversación (líneas 1900-2360)

```python
def obtener_hilo(remitente, asunto=None, dias=180):
```

Conecta IMAP. Estrategia primaria: select `[Gmail]/All Mail` y busca por `FROM`/`TO`/`CC` el remitente. Esto cubre todos los correos sin importar etiquetas o si están archivados/movidos a Importantes.

**Fetch en batch:** `mail.fetch(b"1,5,9,...", "(RFC822)")` con todos los UIDs separados por coma, una sola llamada. Es 5-10× más rápido que un fetch por mensaje porque ahorra round-trips IMAP.

Para servidores no-Gmail: fallback a buscar en INBOX + Sent por separado.

### 4.18 Detección de respuestas y Calendly (líneas 2364-2520)

```python
def detectar_respuestas_y_calendly(dias=30):
```

Optimizado para polling frecuente:

1. **Tracking de `_last_uid`** dentro de `respuestas` JSON. Primer scan recorre 30 días; los siguientes sólo bajan UIDs > último visto. Hace que el polling sea casi instantáneo después del primer scan.
2. **Sólo headers** (`BODY.PEEK[HEADER]`) por defecto. Sólo descarga RFC822 completo si el correo es de Calendly (necesita el cuerpo para extraer email del invitado).
3. **Filtros**:
   - From contiene `daemon` → bounce, ignorar.
   - From == nuestra propia cuenta → propio envío, ignorar.
   - From en `_DOMINIOS_CALENDLY` → es Calendly.
   - From en `contactos` (CSV) → es respuesta de cliente.

### 4.19 Backups completos (líneas 2573-2696)

```python
def exportar_backup_completo(destino_zip):
def importar_backup_completo(origen_zip):
```

ZIP con **todos** los archivos JSON + CSV + carpeta `historial/`. Permite migrar entre PCs o respaldar antes de actualizar. Excluye la `firma_imagen` y el `logo_personalizado` por defecto (paths absolutos del cliente que no aplican en otra PC).

---

## 5. Módulo `interfaz.py` (frontend Flet)

### 5.1 AppUserModelID (líneas 14-22)

```python
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Pulsemail.OutreachSuite.1")
```

Windows usa este string para agrupar ventanas en la barra de tareas y mostrar el ícono correcto. Sin esto, los toasts de plyer aparecen como "Python 3.11" y la barra de tareas usa el ícono Python por defecto.

### 5.2 Detección de WebView (líneas 27-44)

Flet 0.84 desktop NO soporta WebView (sólo móvil/web). La detección es conservadora: si la importación funciona pero `WebView` no es callable, asumimos que no está disponible. Toda la funcionalidad WebView cae a fallback (render PNG vía html2image).

### 5.3 Notificaciones del SO (líneas 79-139)

```python
def _resolver_icono_notif():
def notificar_sistema(titulo, mensaje):
```

Resuelve un `.ico` (Windows toast lo prefiere) usando `logo-app.png` → conversión a `.ico` con PIL si no existe el `.ico`. Cachea el `.ico` en disco después de la primera conversión.

`notificar_sistema` intenta plyer; si falla, fallback a `winsound.MessageBeep`. La función nunca lanza excepciones — el caller asume que "puede haber notificación o no", no es flujo crítico.

### 5.4 Renderizado HTML → PNG con Chrome (líneas 141-326)

```python
_HTI_LOCK     = threading.Lock()
_HTI_INSTANCE = [None]

def _hti_init():
def _html_a_imagen(html_str, message_id):
```

Usa `html2image` (Chrome headless). El `Lock` es porque html2image **no es thread-safe** — si dos threads llaman a la vez, Chrome devuelve PNG corrupto.

**Flags de Chrome (líneas 169-188):** la lista parece exagerada pero cada flag tiene una razón:
- `--disable-gpu --use-gl=swiftshader --in-process-gpu --disable-gpu-compositing` → en PCs con tarjeta gráfica vieja, virtualizada o sin drivers actualizados, Chrome falla con `Failed to create shared context for virtualization`. Estos flags fuerzan software rendering.
- `--disable-dev-shm-usage` → evita "Out of disk space" en shm.
- `--disable-javascript --disable-extensions --disable-background-networking` → los HTML de correo no necesitan JS y JS lento ralentiza el render.
- `--virtual-time-budget=2500` → Chrome no espera infinito por recursos remotos (Google Fonts).
- `--blink-settings=imagesEnabled=true` → asegura que las imágenes inline se rendericen.

**Override CSS:** `style_override` se inyecta en el `<head>` para forzar `margin:0; padding:0; background:#ffffff; max-width:900px`. Esto:
- Elimina el margin/padding del body (Chrome lo agrega por defecto).
- Garantiza fondo blanco aunque el correo no lo declare.
- Limita el ancho — sin esto, en pantallas de alto DPI el body se estira y aparece franja blanca enorme a la derecha.

**Trim del whitespace con `ImageChops.difference + getbbox`** (líneas 269-300):
1. Cuantizamos pixels casi-blancos (todos los canales ≥ 245) a blanco puro `#ffffff`. Compensa anti-aliasing/sombras que confunden detectores ingenuos.
2. Restamos contra una imagen totalmente blanca → todo lo que no es contenido queda en negro.
3. `getbbox()` devuelve el rectángulo exacto que contiene pixels no-cero = bounding box del contenido real.
4. Recortamos con margen de 6 px para no comer bordes de elementos.

Esta es la única técnica que funciona en todos los correos sin importar viewport, DPI o tamaño de contenido.

### 5.5 Cache de PNG renderizados

`_HTML_CACHE_DIR` en temp (`%TEMP%\ith_mail_render_cache`). Cada PNG se nombra por `{message_id}_{hash(html_str)}.png`. El hash incluye el HTML completo, así si cambia (firma editada, etc) se re-renderiza; si es el mismo, hit instantáneo del caché.

### 5.6 Sistema de tema claro/oscuro (líneas 348-460)

```python
def es_dark_so() / resolver_tema() / aplicar_tema()
```

`es_dark_so` lee el registry `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize\AppsUseLightTheme`. La preferencia del usuario es `claro`/`oscuro`/`sistema`; `sistema` resuelve al valor del registry.

`aplicar_tema(modo)` muta los colores globales (`C_BLANCO`, `C_FONDO`, `C_TEXTO_*`, etc) en el namespace del módulo. Después llama a `page.update()` para forzar re-render. Esto funciona porque Flet evalúa los colores en cada update — no necesitamos rebuildear la UI.

### 5.7 Función `main(page)` — punto de entrada UI

Construye toda la UI en una sola función (~5000 líneas). Estructura aproximada:

```
def main(page):
    1. Setup de page (título, icono, theme)
    2. Helpers de update thread-safe (safe_update)
    3. Estados compartidos (campana_activa, vista_actual, etc.)
    4. Builders de cada panel:
       - Dashboard
       - Contactos
       - Rechazados
       - Respuestas / Calendly
       - Hilo de conversación
       - Estadísticas
       - Historial
       - Configuración (4 tabs: Cuenta, Firma, Servidores, Apariencia)
    5. Sidebar navegacional
    6. Watcher de respuestas (thread)
    7. Inicializaciones finales (cargar contactos en background, etc.)
```

**Decisión de tener todo en `main(page)` y no en clases:** Flet 0.84 funciona bien con closures pero el wrapper en clases agrega boilerplate sin beneficio claro. Las funciones helper (callbacks, refrescos) acceden por closure a los controles que necesitan.

### 5.8 Threading y `safe_update`

```python
def safe_update(*controles):
    try:
        if controles:
            for c in controles: c.update()
        else:
            page.update()
    except Exception:
        pass
```

Flet permite `update()` desde otros threads pero a veces falla silenciosamente si la página fue cerrada. El `try/except` evita crashes durante shutdown.

### 5.9 Botón Iniciar/Detener campaña (líneas 967-1145)

Toggle en `arrancar(e)`:
- Si `campana_activa[0]` es True → llama `enviar_correos.detener_campana()` (setea el `_STOP_CAMPANA`), cambia el botón a "Deteniendo..." y vuelve.
- Si False → resetea flags anti-spam, llama `reset_stop_campana()`, cambia el botón a rojo "Detener campaña" y arranca el thread `trabajador()` que ejecuta `enviar_correos.main()`.

El `trabajador()` en su `finally` restaura el botón a verde "Iniciar campaña".

### 5.10 Hook de red (`_on_red_estado`)

Registrado vía `enviar_correos.set_red_hook(_on_red_estado)`. Recibe `(estado, intento, maximo, destino)` y:
- Convierte cada estado en un toast (`notificar_sistema`).
- Agrega línea en el historial de eventos del dashboard.
- Usa `_red_avisada` flags para anti-spam: cada estado se notifica una sola vez por corrida (no 30 toasts iguales).

### 5.11 Tabla de contactos paginada

`tabla_contactos_rows` es un `ft.DataTable` sin `expand=True`. Sin `expand`, la tabla toma su ancho natural y el `Row` contenedor (con `scroll=AUTO`) hace scroll horizontal para emails largos en pantallas chicas. Con `expand=True` la tabla se trunca y el scroll horizontal nunca aparece.

Paginación manual con `pagina_contactos[0]` y `TAM_PAGINA` constantes — Flet 0.84 no tiene paginación nativa de DataTable.

### 5.12 Panel Rechazados con dedupe forzado

`refrescar_rechazados()` carga la lista y aplica dedupe usando un `set` de keys normalizadas (`email.lower().strip()` + filtro `isprintable`). El `isprintable` filtra emails con caracteres invisibles que de otra forma se ven duplicados pero técnicamente son strings distintos.

Está envuelto en un `threading.Lock` (`_REFRESH_RECH_LOCK`) para evitar que dos refrescos simultáneos (auto-polling + click manual) inserten duplicados.

### 5.13 Configuración: 4 sub-pestañas

Reimplementadas como `Container` clickeable porque `ft.Tabs` en Flet 0.84 tenía bugs con `tab_content`. La sub-pestaña activa se persiste en `_CFG_TAB_INICIAL[0]` para que al rebuildear la UI (cambio de tema) el usuario quede en la misma sub-pestaña.

### 5.14 Selectores de archivo (`tkinter.filedialog`)

Flet 0.84 desktop no soporta `ft.FilePicker`. Workaround: invocar `tkinter.filedialog` en un thread daemon. Crear el `Tk()` con `withdraw()` y `attributes("-topmost", True)` para que aparezca arriba de la ventana Flet sin mostrar la ventana root de tkinter.

---

## 6. Sistema de caché TTL

```python
_CACHE = {}        # key -> (mtime_archivo, ts_cache, valor)
_CACHE_TTL = 3.0   # segundos

def _cached_read(clave, archivo, loader):
def _cache_invalidate(clave=None):
```

Cada lectura JSON pasa por este caché. Devuelve valor cacheado si:
- Está en caché.
- El `mtime` del archivo no cambió.
- Han pasado < 3 segundos desde la última lectura.

**Por qué TTL Y mtime:** mtime detecta cambios externos (otra app modificó el archivo, sincronizador en la nube, etc). TTL evita reads excesivos en el mismo segundo cuando la UI cambia rápido entre tabs.

Cada `guardar_X()` llama `_cache_invalidate("X")` para que el siguiente `cargar_X()` no devuelva data stale.

---

## 7. Integración IMAP / Gmail

### Buzones especiales de Gmail

```python
_BUZONES_ALL_MAIL = ['"[Gmail]/All Mail"', '"[Gmail]/Todos"', ...]
_BUZONES_SENT     = ['"[Gmail]/Sent Mail"', '"[Gmail]/Enviados"', ...]
```

Lista de fallbacks porque Gmail traduce los nombres según idioma de la cuenta. Comillas escapadas porque IMAP requiere quoting de mailboxes con espacios o caracteres especiales.

### Por qué `[Gmail]/All Mail` para hilo

Gmail usa labels, no carpetas. Un correo con label `Important` y sin label `Inbox` no aparece en INBOX, pero sí en `All Mail`. Para reconstruir un hilo completo es la única carpeta confiable.

### Por qué `UID MOVE` para borrar

Tres ventajas frente a `COPY + STORE \Deleted + EXPUNGE`:
1. **Atómico:** una sola operación del servidor.
2. **No requiere `EXPUNGE`:** evita race conditions con otros mensajes flagged.
3. **Soportado por Gmail:** Gmail implementa RFC 6851.

Fallback a `COPY + UID STORE \Deleted + UID EXPUNGE` (no `EXPUNGE` total) para servidores que no soportan MOVE. `UID EXPUNGE` borra puntualmente el UID indicado, no toda la carpeta.

### `BODY.PEEK[HEADER]` vs `RFC822`

`PEEK[HEADER]` baja sólo headers (~2 KB) sin marcar el correo como leído. `RFC822` baja headers + body + adjuntos (puede ser MB). Usar el primero por defecto y el segundo sólo cuando se necesita el cuerpo (Calendly invitado, render del hilo).

---

## 8. Renderizado HTML → PNG de correos

Ver sección 5.4 para detalles de implementación. Resumen del pipeline:

```
HTML correo
  ↓ inyectar style_override (margin 0, fondo blanco, max-width 900)
  ↓ html2image.screenshot() → PNG en _HTML_CACHE_DIR
  ↓ PIL: ImageChops.difference + getbbox
  ↓ crop con margen 6 px
PNG final mostrado en panel Hilo
```

Cache hit por `{message_id}_{hash(html_str)}.png`. Hit ratio en uso normal: ~95% (sólo se re-renderiza al cambiar firma o si el correo se editó).

---

## 9. Reintentos de red y persistencia

Ver sección 4.10 y 4.4. Diagrama de flujo:

```
enviar_correo(msg, destino, intentos_previos=0)
  │
  ├── Loop while intento < 1000
  │     ├── ¿campana_detenida()? → guardar_pendiente() → "detenido"
  │     ├── Try SMTP
  │     │     ├── Éxito → borrar_pendiente() → "enviado"
  │     │     ├── SMTPRecipientsRefused → borrar_pendiente() → "rechazado"
  │     │     ├── SMTPAuthenticationError → borrar_pendiente() → "auth"
  │     │     └── Network err
  │     │           ├── intento==1 → emit "caido"
  │     │           ├── intento==30 → emit "inestable"
  │     │           ├── intento%100==0 → emit "reintentando"
  │     │           ├── intento%10==0 → guardar_pendiente()
  │     │           └── sleep 10s interrumpible
  │
  └── Salida del while → guardar_pendiente() → emit "agotado" → "agotado"
```

Resultado del retomar:
```
main()
  │
  ├── reset_stop_campana()
  ├── Cargar pendiente
  │     ├── Si existe → enviar_correo(intentos_previos=N)
  │     └── Si no existe → continuar
  ├── Cargar CSV
  ├── Loop sobre contactos
  │     ├── ¿campana_detenida()? → return
  │     ├── ¿enviados >= limite? → break
  │     ├── Saltar hasta ultimo_email (resume)
  │     └── enviar_correo() → match resultado
  └── revisar_rebotes()
```

---

## 10. Compilación e instalador

### Build chain

```
Python source
  ↓ flet pack (PyInstaller wrapper)
  ↓
dist/Pulsemail.exe (onefile, ~80 MB)
  ↓ mover a dist/Pulsemail/
  ↓ Inno Setup compila installer/pulsemail.iss
  ↓
installer_output/PulsemailSetup_v1.0.0.exe
```

Ver `COMPILAR.md` para instrucciones paso a paso.

### Hidden imports

PyInstaller no detecta automáticamente módulos cargados dinámicamente. `build_installer.bat` agrega `--hidden-import` para los módulos de plyer (cargados según OS en runtime). Sin esto, las notificaciones fallan en la versión compilada con `ModuleNotFoundError: plyer.platforms`.

### Add-data

Cada asset (PNG, SVG, ICO, .py) debe declararse con `--add-data "archivo;."` para que PyInstaller lo incluya en el bundle. Sin esto, en runtime `os.path.join(CARPETA_ASSETS, "ITH-logo.png")` no encuentra el archivo.

### Inno Setup `[Files]`

NUNCA debe incluir `config.json`, `contactos.csv`, `registro_*.json` ni `historial/`. Eso garantiza que una actualización no sobreescriba los datos del usuario.

---

## 11. Convenciones de código y limitaciones de Flet 0.84

### Convenciones

- **Nombres en español** para funciones de dominio (`enviar_correo`, `cargar_estado`, `marcar_visto`). El usuario y el dominio del problema están en español; los nombres técnicos (`safe_update`, `_cached_read`) en inglés cuando son patrones genéricos.
- **Prefijo `_`** para funciones internas/privadas del módulo.
- **Listas de un elemento** (`_RED_HOOK = [None]`) como hack para mutar desde funciones internas sin `nonlocal`/`global`.
- **Strings literales para estados** (`"enviado"`, `"caido"`) en vez de enum: simplicidad para debugging y logging.
- **`try/except Exception: pass`** en los hooks de UI: la UI nunca debe crashear por un toast fallido o un update de control viejo.
- **Comentarios en español** explicando el "por qué", no el "qué" obvio del código.

### Limitaciones de Flet 0.84 (workarounds aplicados)

| Feature Flet | Status 0.84 | Workaround |
|---|---|---|
| `ft.FilePicker` desktop | NO disponible | `tkinter.filedialog` en thread |
| `ft.Tab(tab_content=...)` | Bug | Custom tabs con `Container` clickeable |
| `ft.alignment.center` | NO existe | `ft.Alignment(0, 0)` |
| `ft.ImageFit.SCALE_DOWN` | Removido | String literal `"scaleDown"` o `"fitWidth"` |
| `page.set_clipboard` | Removido | Win32 API con ctypes (argtypes correctos para 64-bit) |
| `ft.PieChart` / `ft.BarChart` | NO en core | Render manual con `Container` y math |
| `ft.WebView` | Sólo móvil/web | Fallback a `html2image` PNG |

Estas limitaciones quedaron documentadas en este mismo archivo y en los comentarios del código fuente para no re-descubrir bugs ya resueltos al actualizar Flet.

### Anti-patrones evitados

- **No** usamos `time.sleep` largos sin chequeo de stop event — todo sleep > 1s se descompone en bucle con check.
- **No** hacemos IMAP fetch por cada correo en bucles — siempre batch (`fetch(b"1,5,9,...", ...)`)
- **No** marcamos correos como `\Deleted` y `EXPUNGE`-amos sin necesidad — preferimos `UID MOVE` para evitar permadelete por race.
- **No** confiamos en `BODY` search para identificar correos — usamos `Message-ID` exacto cuando disponible.

---

## Apéndice: cómo testear cambios

1. **Backend aislado:** importar `enviar_correos` desde un script de prueba, configurar credenciales de test, llamar `main()` con un CSV pequeño (2-3 contactos a tu propia cuenta).
2. **UI con datos reales:** copiar `config.json` y `contactos.csv` reales a la carpeta del repo, correr `py interfaz.py`.
3. **Build completo:** seguir `COMPILAR.md`. Probar en una segunda PC (idealmente sin Python instalado) para verificar que el `.exe` es self-contained.
4. **Probar reintentos:** durante una campaña, desactivar wifi → ver toast "Sin conexión", verificar que `registro_pendiente.json` se cree, esperar al menos 30 intentos para ver toast "Inestable", reactivar → ver toast "Recuperada".
5. **Probar Detener:** durante la pausa entre correos, apretar Detener → debe responder en < 1s y guardar pendiente con el siguiente correo a intentar.

---

*Documento mantenido por el equipo Pulsemail. Última actualización: mayo 2026.*
