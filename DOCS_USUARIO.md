# Pulsemail — Manual de usuario

> Suite profesional de outreach automation para Windows. Envío masivo de correos personalizados, detección de respuestas y rebotes, gestión de Calendly y administración integrada de campañas.

---

## Índice

1. [¿Qué es Pulsemail?](#1-qué-es-pulsemail)
2. [Funcionalidades principales](#2-funcionalidades-principales)
3. [Requisitos del sistema](#3-requisitos-del-sistema)
4. [Instalación](#4-instalación)
5. [Configuración inicial](#5-configuración-inicial)
6. [Guía de uso por panel](#6-guía-de-uso-por-panel)
7. [Buenas prácticas: cómo evitar baneos y filtros de spam](#7-buenas-prácticas-cómo-evitar-baneos-y-filtros-de-spam)
8. [Límites de envío: Gmail vs Google Workspace](#8-límites-de-envío-gmail-vs-google-workspace)
9. [Resolución de problemas](#9-resolución-de-problemas)
10. [Glosario](#10-glosario)

---

## 1. ¿Qué es Pulsemail?

Pulsemail es una aplicación de escritorio para Windows pensada para equipos comerciales que necesitan:

- **Enviar campañas masivas de correo** con plantillas HTML personalizadas, sin recurrir a plataformas SaaS de terceros (Mailchimp, SendGrid).
- **Trabajar con su propia cuenta de Gmail / Google Workspace**: las campañas salen desde tu dirección, no desde un dominio compartido. Esto mejora la reputación y la entregabilidad.
- **Detectar respuestas automáticamente** y mostrarlas en una bandeja unificada estilo CRM.
- **Detectar rebotes** (correos no entregados) y depurar la lista para que la próxima campaña no incluya direcciones inválidas.
- **Gestionar reuniones de Calendly** desde la misma interfaz.
- **Mantener un historial completo** de cada día de campaña para auditoría y métricas.

Es una herramienta **profesional pero simple**: una vez configurada, abrís la app, apretás "Iniciar campaña" y se encarga de todo el resto.

---

## 2. Funcionalidades principales

### Dashboard
- Vista en tiempo real de la campaña en curso.
- Métricas: enviados hoy, límite diario, rechazados, tasa de éxito.
- Barra de progreso de la campaña.
- Historial de eventos del día con códigos de color (info, éxito, advertencia, error).
- Botón **Iniciar / Detener campaña** que se transforma según el estado.

### Contactos
- Tabla paginada que soporta **30.000+ contactos** sin congelarse.
- Buscador con filtro instantáneo.
- Importación desde `contactos.csv` (formato HubSpot estándar).
- Scroll horizontal automático para emails largos.

### Rechazados

- Listado de todos los correos que rebotaron, detectados desde **dos tipos de remitentes**:
  - **`mailer-daemon`** (Gmail, Yahoo, hosts genéricos): notifica fallos como "dirección no existe", "buzón lleno", "dominio inválido".
  - **`postmaster`** (Microsoft Exchange, Office 365, servidores corporativos): mismo propósito pero usado por servers que siguen RFC 5321 estricto.
  - También captura variantes como `mail-daemon` (sendmail viejo) y bounces que vienen con subjects característicos como *"Delivery Status Notification"* o *"Mail Delivery Failure"*.
- El reconocimiento es **case-insensitive** y por substring, así que `MAILER-DAEMON@empresa.com` o `Mail Delivery Subsystem <postmaster@server.com>` también entran.
- Sólo cuentan los rebotes de contactos que están en tu `contactos.csv` — los rebotes de correos personales que comparten cuenta Gmail se ignoran.
- **Botón "Depurar"** que mueve a la papelera de Gmail tanto el correo de rebote como el correo original que lo causó.
- Reconoce micro-cortes y reintenta sin perder progreso.
- Botón "Restaurar" para deshacer una depuración.

### Respuestas y reuniones
- Detecta automáticamente respuestas de clientes (filtradas por tu lista de contactos).
- Detecta confirmaciones de Calendly y muestra el invitado.
- Badge con cantidad de no leídos.
- Click → abre el hilo completo de conversación.

### Hilo de conversación
- Reconstruye el thread completo del cliente (búsqueda en `[Gmail]/All Mail` para no perder correos archivados o en Importantes).
- **Renderiza cada correo idéntico a Gmail** usando Chrome headless para preservar logos, gradientes, firmas con imágenes, SVGs.
- Campo "Tu respuesta" con envío directo manteniendo `In-Reply-To` y `References` (Gmail lo agrupa al hilo correctamente).
- Modo "Responder a todos" que recolecta To+Cc de todos los mensajes anteriores.

### Estadísticas
- Suma global de enviados / rebotes / tasa de éxito.
- Serie temporal por día (últimos 30 días).

### Historial
- Línea de tiempo navegable por día.
- Cada día muestra resumen (enviados, rebotes) y eventos detallados.

### Configuración
- **Cuenta**: correo, contraseña de aplicación de Google, límite diario, CC opcional, URLs de Calendly y WhatsApp.
- **Firma**: texto plano o imagen (con preview).
- **Servidores**: SMTP/IMAP (defaults Gmail).
- **Apariencia**: tema claro/oscuro/sistema, logo personalizado.
- **Datos**: exportar/importar backup completo en ZIP.

### Notificaciones nativas
- Toast Windows 10/11 cuando llega una respuesta nueva.
- Toast cuando se cae internet o cuando se recupera.
- Toast cuando se agotan los reintentos automáticos.

### Sistema de reintentos resilientes
- Si se cae internet durante un envío, reintenta hasta 1000 veces (1 cada 10 segundos = ~3 horas).
- Notifica al usuario cuando detecta inestabilidad.
- Si no vuelve la conexión en 3 horas, detiene automáticamente la campaña.
- Cuando se reanuda la campaña, retoma exactamente desde el correo que quedó pendiente.

---

## 3. Requisitos del sistema

### Mínimos

| Componente | Requisito mínimo |
|---|---|
| **Sistema operativo** | Windows 10 (64-bit) versión 1809 o superior |
| **CPU** | Dual-core 1.5 GHz |
| **RAM** | 4 GB |
| **Disco** | 250 MB libres (instalación) + 100 MB para datos del usuario |
| **Resolución de pantalla** | 1280 × 720 |
| **Internet** | Conexión estable (puede tolerar microcortes de hasta 3 horas) |
| **Cuenta de correo** | Gmail o Google Workspace con verificación en 2 pasos activada |
| **Chrome o Chromium instalado** | Requerido para renderizar correos en el panel Hilo |

> **Nota:** Microsoft Edge **NO** funciona como reemplazo de Chrome para el render de correos. Chrome o Chromium deben estar presentes en una ruta estándar (`C:\Program Files\Google\Chrome\` o equivalente).

### Recomendados

| Componente | Recomendado |
|---|---|
| **Sistema operativo** | Windows 11 (64-bit) última versión |
| **CPU** | Quad-core 2.5 GHz o superior |
| **RAM** | 8 GB o más |
| **Disco** | SSD con 1 GB libres |
| **Resolución de pantalla** | 1920 × 1080 (Full HD) |
| **Internet** | Conexión por cable o WiFi 5 GHz, latencia < 50 ms a Google |
| **Cuenta de correo** | Google Workspace con dominio propio verificado |

### Por qué estos requisitos

- **Windows 10 1809+**: necesario para soporte completo de toasts nativos del sistema operativo.
- **64-bit**: Pulsemail se compila en 64-bit; no hay versión 32-bit disponible.
- **Chrome instalado**: el panel "Hilo de conversación" usa Chrome headless para renderizar cada correo idéntico a como se ve en Gmail. Sin Chrome, el panel cae a un modo Markdown plano (funcional pero sin diseño).
- **Verificación en 2 pasos**: Google **exige** contraseñas de aplicación para acceso SMTP/IMAP de terceros desde 2022. Sin 2FA activada no podés generar la contraseña de aplicación.

---

## 4. Instalación

### Opción A: Instalador (recomendada)

1. Descargá `PulsemailSetup_v1.X.X.exe` (~80 MB).
2. Doble click. El wizard te guía en español.
3. Elegí carpeta de instalación (default: `%LOCALAPPDATA%\Pulsemail\` — no requiere permisos de administrador).
4. Marcá "Crear acceso directo en el escritorio" si querés.
5. Al terminar, podés abrir Pulsemail directamente.

**Actualización a una versión nueva:**
- Descargá el `.exe` de la nueva versión y ejecutalo.
- El instalador detecta la versión previa y muestra un mensaje recomendando hacer backup desde **Configuración → Datos → Exportar configuración completa**.
- La actualización reemplaza el `.exe` pero **NO toca tus datos** (config, contactos, historial, rechazados, etc).

**Desinstalación:**
- Panel de Control → Programas y características → Pulsemail → Desinstalar.
- Tus datos quedan intactos en la carpeta de instalación por si querés reinstalar más adelante.

### Opción B: Modo desarrollo (desde código fuente)

Para desarrolladores o usuarios avanzados que quieran modificar el código:

1. Instalar [Python 3.11+](https://www.python.org/) marcando "Add Python to PATH".
2. Abrir terminal en la carpeta del proyecto y correr:
   ```
   pip install flet==0.84.0
   pip install Pillow
   pip install html2image
   pip install plyer
   ```
3. Ejecutar:
   ```
   py interfaz.py
   ```

---

## 5. Configuración inicial

Al abrir la app por primera vez, ir a **Configuración → Cuenta**:

### Paso 1: Activar verificación en 2 pasos en Google

1. Ir a [myaccount.google.com](https://myaccount.google.com/) → Seguridad.
2. En "Iniciar sesión en Google" → activar "Verificación en 2 pasos".
3. Seguir el wizard (registrar tu teléfono).

### Paso 2: Generar contraseña de aplicación

1. Ir a [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) (sólo aparece si tenés 2FA activada).
2. Seleccionar app "Mail" y dispositivo "Otra (nombre personalizado)" → escribir "Pulsemail" → "Generar".
3. Google muestra una contraseña de 16 caracteres tipo `xxxx xxxx xxxx xxxx`. **Copiala — sólo la vas a ver una vez.**

### Paso 3: Cargar credenciales en Pulsemail

| Campo | Qué poner |
|---|---|
| **Correo electrónico** | Tu Gmail o Workspace (`tunombre@gmail.com` o `tunombre@tudominio.com`) |
| **Contraseña de aplicación** | Los 16 caracteres del paso 2 (con o sin espacios) |
| **Límite diario de envíos** | 250 (Gmail) o 1500 (Workspace) — ver [sección 8](#8-límites-de-envío-gmail-vs-google-workspace) |
| **Correos en copia (CC)** | Opcional. Direcciones separadas por coma que reciben copia de cada envío |

Apretar **Guardar configuración**. El indicador del sidebar debería pasar a verde "GMAIL SMTP activo" o "WORKSPACE SMTP activo".

### Paso 4: Configurar firma

Ir a **Configuración → Firma**. Dos modos:

- **Texto**: tu firma como texto plano (nombre, cargo, teléfono, email).
- **Imagen**: subir un PNG/JPG con tu firma diseñada (logo + datos). Se rescala automáticamente a 600 px de ancho.

### Paso 5: Botones del template (opcional)

En **Configuración → Cuenta** hay dos campos al final:

- **URL del botón Calendly**: link a tu agenda (`https://calendly.com/tu-usuario/30min`).
- **URL del botón WhatsApp**: link `wa.me` con tu número y mensaje pre-cargado.

Si los dejás vacíos, se usan los defaults del template (los originales de IntelliHelp).

### Paso 6: Logo del cliente

En **Configuración → Apariencia**, sección "Logo del cliente":

- Subí tu logo (PNG/JPG/WebP).
- Aparece en el sidebar de la app y se incrusta en cada correo que envíes.
- Si no subís ninguno, se usa el logo por defecto.

### Paso 7: Cargar lista de contactos

Copiá tu archivo `contactos.csv` a la carpeta de instalación de Pulsemail (`%LOCALAPPDATA%\Pulsemail\` por default).

Formato esperado del CSV (HubSpot estándar):

```csv
Nombre,Apellidos,Nombre de Cuenta,Correo electrónico,Correo electrónico secundario,Correo electrónico terciario
Juan,Pérez,ACME SA,juan@acme.com,juan.perez@acme.com,
María,García,Beta SRL,maria@beta.com,,
```

Mínimo necesario: una columna `Correo electrónico` o `Correo electrónico secundario` o `Correo electrónico terciario`. La app usa la primera columna no vacía. Las columnas `Nombre` y `Apellidos` se concatenan para personalizar el saludo "Estimado/a [Nombre]".

Reabrir Pulsemail para que detecte el CSV.

---

## 6. Guía de uso por panel

### Iniciar una campaña

1. Apretar **Iniciar campaña** en el dashboard.
2. El botón cambia a rojo **Detener campaña**.
3. Empiezan los envíos: 1 cada 25-45 segundos (pausa aleatoria para parecer humano).
4. El historial de eventos se va llenando en tiempo real.
5. Al terminar (límite alcanzado o lista completa), el botón vuelve a verde.

### Detener una campaña en curso

- Apretar **Detener campaña** → cambia a "Deteniendo..."
- En menos de 1 segundo la campaña se aborta.
- El correo que estaba intentándose queda guardado en `registro_pendiente.json`.
- La próxima vez que iniciés campaña, retoma desde ese correo automáticamente.

### Manejo de cortes de internet

- Si se cae internet durante un envío, aparece toast **"Sin conexión"**.
- La app reintenta automáticamente cada 10 segundos.
- Si los cortes son intermitentes (microcortes de unos minutos), aparece toast **"Conexión inestable"**.
- Cuando vuelve, aparece toast **"Conexión recuperada"** y la campaña continúa.
- Si no vuelve después de 1000 intentos (~3 horas), aparece toast **"Campaña detenida automáticamente"** y la campaña se pausa con el correo guardado para retomar después.

### Depurar rebotes

1. Ir al panel **Rechazados**.
2. Marcar los emails que querés depurar.
3. Apretar **Depurar seleccionados**.
4. La app:
   - Identifica el bounce en tu INBOX. Reconoce los tres remitentes estándar: `mailer-daemon` (Gmail/Yahoo/genérico), `postmaster` (Exchange/Office 365) y `mail-daemon` (sendmail). Sin importar qué proveedor del destinatario lo emitió, el correo entra.
   - Mueve ese bounce a la papelera de Gmail.
   - Identifica el correo original que enviaste **matcheando por Message-ID exacto** (extraído del header `In-Reply-To` del bounce). Esto garantiza que NO toca otros correos legítimos enviados a ese mismo destinatario en campañas previas o hilos de soporte.
   - Mueve el correo original a la papelera también.
   - **Sólo toca esos dos correos**, nada más.
5. Si te equivocaste, apretar **Restaurar** y vuelven al INBOX.

### Ver respuestas de clientes

1. Ir al panel **Respuestas y reuniones**.
2. Listado de respuestas no leídas en negrita.
3. Click en una respuesta → abre el hilo completo de conversación con el cliente.
4. Podés responder directamente desde la app — Gmail agrupa la respuesta al hilo automáticamente.

### Hacer backup

1. Ir a **Configuración → Datos**.
2. Apretar **Exportar configuración completa**.
3. Elegí dónde guardar el ZIP. Incluye config, contactos, historial, rechazados, respuestas — todo.
4. Para restaurar en otra PC: instalar Pulsemail, ir a Datos → **Importar configuración completa** → seleccionar el ZIP.

---

## 7. Buenas prácticas: cómo evitar baneos y filtros de spam

Esta sección es **crítica**. Una cuenta de Gmail/Workspace baneada por enviar spam pierde acceso a toda Google (Drive, Docs, etc), no solo a Gmail. Hay que tomarse en serio estos consejos.

### 7.1 Antes de tu primera campaña

- **Calentá la cuenta gradualmente**: si tu cuenta es nueva o nunca envió campañas, empezá con 30-50 correos por día durante la primera semana, luego 100, luego 200, hasta llegar al límite. Saltar de 0 a 250 correos en un día activa alarmas anti-spam.
- **Asegurate de que tu dominio tenga SPF, DKIM y DMARC configurados** (válido para Workspace; Gmail personal ya los tiene). Sin estos, los correos van a spam masivamente.
- **Tu firma debe incluir contacto real**: nombre completo, teléfono, dirección física opcional, link a la web. Esto cumple con CAN-SPAM Act y GDPR.

### 7.2 Calidad de la lista de contactos

- **NO uses listas compradas**. Las listas vendidas en internet contienen spam-traps (direcciones plantadas para detectar spammers). Un solo email a un spam-trap puede banear tu dominio.
- **Tus contactos deben tener relación previa contigo**: clientes anteriores, leads que llenaron un formulario, asistentes a un evento, contactos LinkedIn.
- **Limpiá los rebotes**: usá la función Depurar de Pulsemail después de cada campaña. Una tasa de rebote > 5% es señal roja para Google.
- **No envíes a la misma persona más de 1 correo por mes** sin que haya respondido. Múltiples correos sin respuesta = comportamiento de spam.

### 7.3 Calidad del contenido

- **Asunto realista, no clickbait**. "Reunión disponible esta semana" funciona; "🔥 OFERTA IMPERDIBLE 🔥" va a spam.
- **No abuses de mayúsculas, signos !!!, emojis** en el asunto.
- **El cuerpo debe parecer un correo real**, no publicidad. Pulsemail incluye un template balanceado: saludo personalizado, propuesta clara, dos botones de acción.
- **Personalización con `{nombre}`**: Pulsemail ya lo hace automáticamente. Esto baja la tasa de spam significativamente.
- **Evitá palabras "gatillo"**: "GRATIS", "GANASTE", "CRYPTO", "VIAGRA", "URGENTE" en el cuerpo o asunto activan filtros bayesianos.
- **No uses link shorteners** (bit.ly, tinyurl). Usá URLs completas.
- **Incluí una opción de baja**: aunque no es obligatoria por Gmail, está bien tener "Si no querés recibir más correos, respondé STOP" al final.

### 7.4 Ritmo de envío

Pulsemail ya implementa pausas aleatorias de 25-45 segundos entre correos. **No bajes este intervalo** sin entender las consecuencias:

- Pausas < 20 segundos = comportamiento robótico → flag.
- Pausas > 60 segundos = campañas excesivamente lentas (no más seguras, sólo más lentas).
- El default 25-45s da ~80-100 correos/hora, dentro del rango "humano".

### 7.5 Reputación del dominio

- **Configurá DKIM**: en Google Workspace Admin → Apps → Gmail → Authenticate email. Activala y publicá el TXT en tu DNS.
- **Configurá SPF**: agregá TXT `v=spf1 include:_spf.google.com ~all` a tu DNS.
- **Configurá DMARC** después de tener SPF y DKIM funcionando: TXT `_dmarc.tudominio.com` con `v=DMARC1; p=quarantine; rua=mailto:tu@email.com`.
- **Monitoreá Postmaster Tools**: [postmaster.google.com](https://postmaster.google.com/) te da métricas de tu reputación con Gmail.

### 7.6 Señales rojas a vigilar

- **Tasa de rebote > 5%**: limpiá la lista urgente.
- **Tasa de quejas (spam reports) > 0.1%**: revisá tu contenido y a quién se lo mandás.
- **Caída de open rate**: las personas no abren = están marcando como spam.
- **Aviso de Google**: "Detectamos actividad inusual" → reducí volumen al 30% durante una semana.

### 7.7 Si te bloquean temporalmente

- Google a veces emite **bloqueos temporales** (24-48 hs) cuando detecta volumen sospechoso. Pulsemail lo verás como `SMTPDataError 421 4.7.0`.
- Detené todas las campañas inmediatamente.
- Esperá 48 horas sin enviar nada.
- Reanudá con volumen reducido (30 correos/día).
- Si después de 3 advertencias seguís enviando agresivamente, Google **banea permanentemente** la cuenta.

---

## 8. Límites de envío: Gmail vs Google Workspace

### Gmail personal (cuenta gratuita `@gmail.com`)

| Límite | Valor |
|---|---|
| **Envíos diarios** | **500 destinatarios / día** (incluye CC y BCC) |
| **Recomendado en Pulsemail** | **250** |
| **Máximo de destinatarios por correo** | 100 (To + Cc + Bcc combinados) |
| **Tamaño máximo del correo** | 25 MB |
| **Reseteo del límite** | Diario rolling window 24 hs |

> **Por qué recomendar 250 y no 500**: Google cuenta cada destinatario como un envío. Si pones 1 destinatario en `To` y 1 en `Cc`, es 2 envíos. Quedarse en 250 da margen para CC, reenvíos manuales tuyos durante el día y errores temporales sin agotar la cuota.

### Google Workspace (cuenta de pago con dominio propio)

| Plan | Envíos diarios |
|---|---|
| **Business Starter** ($6/usuario/mes) | 2.000 destinatarios externos / día |
| **Business Standard** ($12) | 2.000 destinatarios externos / día |
| **Business Plus** ($18) | 2.000 destinatarios externos / día |
| **Enterprise** | 10.000 destinatarios externos / día |

| Límite | Valor |
|---|---|
| **Recomendado en Pulsemail** | **1.500** (deja margen para correos manuales) |
| **Máximo de destinatarios por correo** | 2.000 (To + Cc + Bcc) |
| **Tamaño máximo del correo** | 25 MB |

### Cómo cambiar el límite en Pulsemail

**Configuración → Cuenta → Límite diario de envíos** → poner el número.

La app respeta el límite estrictamente: cuando llegás al límite, pausa la campaña y muestra "Llegamos al máximo por hoy". Al día siguiente reseteás el contador automáticamente al iniciar la campaña.

### Reglas adicionales de Google que Pulsemail respeta

- **Pausa entre envíos** (25-45s) — no bajamos esto para no parecer bot.
- **Conexión SMTP single-shot** — abrimos y cerramos conexión por correo. Mantener una conexión SMTP abierta enviando 100 correos seguidos también es flag.
- **Reintentos exponencialmente espaciados** — 10s × 1000 con notificación al usuario, no spam de retries cada 100ms.

---

## 9. Resolución de problemas

### El indicador del sidebar dice "Credenciales inválidas"

- Revisá que el correo esté escrito sin espacios.
- Revisá que la contraseña de aplicación sea la correcta (16 caracteres, sin espacios o con ellos — ambos funcionan).
- Verificá que la verificación en 2 pasos esté activada en tu cuenta de Google.
- Generá una nueva contraseña de aplicación si la actual fue revocada.

### Los correos llegan a SPAM

Ver [Sección 7](#7-buenas-prácticas-cómo-evitar-baneos-y-filtros-de-spam). Causas comunes:
- Dominio nuevo sin reputación.
- SPF/DKIM/DMARC mal configurados.
- Contenido con palabras "gatillo".
- Lista de contactos comprada o vieja.

### El panel "Hilo de conversación" muestra texto plano sin diseño

- Falta Chrome o Chromium instalado.
- Instalalo desde [google.com/chrome](https://www.google.com/chrome/) (versión gratuita).
- Reabrí Pulsemail.

### El panel "Hilo" tarda mucho en cargar la primera vez

- Es Chrome inicializándose. La primera carga toma 2-3 segundos.
- Las siguientes son instantáneas (PNG cacheado).

### Las notificaciones del sistema no aparecen

- Verificá que en Windows: **Configuración → Sistema → Notificaciones** estén activadas.
- Verificá que Pulsemail tenga permiso individual.
- Si compilaste vos mismo y falla con `ModuleNotFoundError: plyer.platforms`: revisá `build_installer.bat` que tenga los `--hidden-import` para plyer.

### "Campaña detenida automáticamente" después de un corte largo

- Funcionó el sistema: agotó los 1000 reintentos sin que volviera internet.
- Verificá tu conexión.
- Reapretá **Iniciar campaña** — retoma desde el correo que quedó pendiente.

### Las direcciones rechazadas aparecen duplicadas

- Cerrá y reabrí la app — el dedupe se aplica al cargar.
- Si persiste, borrá `registro_rechazados.json` y dejá que el próximo `Revisando rebotes` lo regenere.

### "No se pudo abrir el selector de archivos" al subir firma o logo

- Tkinter no está disponible. Reinstalá Python marcando "tcl/tk and IDLE" en el instalador.

### La depuración borra correos que no debería

- Versiones antes de mayo 2026 podían matchear correos legítimos al mismo destinatario. Actualizá a la última versión.

### Quiero cambiar la lista de contactos a mitad de campaña

- Detené la campaña.
- Reemplazá `contactos.csv`.
- Borrá `registro_envios.json` (el contador del día) si querés empezar contando desde 0.
- Reapretá Iniciar campaña.

---

## 10. Glosario

| Término | Significado |
|---|---|
| **Bounce / Rebote** | Correo que el servidor del destinatario rechazó. Llega a tu INBOX desde un bot del servidor remoto con el detalle del fallo. Pulsemail los detecta automáticamente. |
| **Mailer-daemon** | Bot estándar de Gmail, Yahoo y la mayoría de proveedores. Su FROM contiene "mailer-daemon" (o variantes como "mail-daemon" en sendmail histórico). |
| **Postmaster** | Bot definido por RFC 5321, usado por Microsoft Exchange, Office 365 y muchos servidores corporativos. Cumple la misma función que mailer-daemon. Pulsemail captura ambos sin distinción. |
| **SMTP** | Protocolo de envío de correo (TCP 587 con STARTTLS). |
| **IMAP** | Protocolo de lectura de correo (TCP 993 con SSL). |
| **Contraseña de aplicación** | Token de 16 caracteres generado por Google para apps que necesitan acceder a Gmail por SMTP/IMAP sin OAuth. Requiere verificación en 2 pasos. |
| **SPF** | Registro DNS que autoriza qué servidores pueden enviar email desde tu dominio. |
| **DKIM** | Firma criptográfica de cada correo para verificar que viene realmente de tu dominio. |
| **DMARC** | Política que dice qué hacer con correos que fallan SPF/DKIM (rechazar, cuarentena, ignorar). |
| **Spam-trap** | Email plantado por proveedores de antispam para detectar listas compradas. Enviar a uno = blacklist. |
| **Open rate** | Porcentaje de destinatarios que abrieron el correo. Métrica de calidad. |
| **Tasa de quejas** | Porcentaje de destinatarios que marcaron como spam. Por encima de 0.1% es problema. |
| **CC / BCC** | Carbon Copy (todos lo ven) / Blind Carbon Copy (oculto). Pulsemail soporta CC desde Configuración. |
| **Calendly** | Plataforma de booking de reuniones. Pulsemail detecta sus emails de confirmación. |
| **Workspace** | Versión paga de Gmail con dominio propio. Mayor reputación y mayores límites. |
| **Pendiente de reintento** | Correo que estaba intentándose cuando se cortó internet o el usuario apretó Detener. Queda guardado en `registro_pendiente.json` y se retoma al iniciar campaña. |
| **Header X-GM-LABELS** | Extensión IMAP de Gmail para manipular etiquetas. Pulsemail la usa para mover a papelera sin riesgo de borrado permanente. |
| **UID MOVE** | Operación IMAP atómica para mover mensajes entre carpetas (RFC 6851). Soportada por Gmail. |

---

## Soporte

- **Issues / sugerencias / preguntas**: contactá al equipo de soporte de tu proveedor.
- **Documentación técnica**: ver `DOCS_DESARROLLADORES.md` en la carpeta del programa.
- **Backup antes de cualquier cosa**: Configuración → Datos → Exportar configuración completa.

---

*Pulsemail — Outreach automation suite. Manual versión mayo 2026.*
