<p align="center">
  <img src="docs/banner.svg" alt="Pulsemail" width="100%">
</p>

<p align="center">
  <b>Aplicación de escritorio para campañas de correo en frío: envío por lotes, respuestas, reuniones, rebotes y bajas en un solo lugar.</b><br>
  Corre en la PC del equipo comercial con la cuenta de Gmail o Google Workspace de la empresa, sin servicios externos ni licencias por usuario.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/Flet-0.84-0175C2?logo=flutter&logoColor=white" alt="Flet 0.84">
  <img src="https://img.shields.io/badge/Windows-instalador%20Inno%20Setup-0078D4?logo=windows&logoColor=white" alt="Windows, instalador Inno Setup">
  <img src="https://img.shields.io/badge/SMTP%20%2B%20IMAP-Gmail%20%2F%20Workspace-EA4335?logo=gmail&logoColor=white" alt="SMTP e IMAP">
  <img src="https://img.shields.io/badge/tests-84%20comprobaciones-663399" alt="Tests">
  <img src="https://img.shields.io/badge/licencia-propietaria-663399" alt="Licencia propietaria">
</p>

---

## Índice

- [Descripción](#descripción)
- [La aplicación por dentro](#la-aplicación-por-dentro)
- [Características](#características)
- [Arquitectura](#arquitectura)
- [Motor de envío](#motor-de-envío)
- [Seguridad](#seguridad)
- [Stack técnico](#stack-técnico)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Instalación y compilación del instalador](#instalación-y-compilación-del-instalador)
- [Tests](#tests)
- [Documentación](#documentación)
- [Licencia](#licencia)
- [Autor](#autor)

## Descripción

**Pulsemail** es la herramienta con la que Intellihelp hace prospección comercial por correo.
Toma una base de contactos en CSV y la envía de a un correo por vez desde la cuenta de la
empresa, con una pausa aleatoria entre envíos y un límite diario, para que el ritmo sea el de
una persona y no el de un robot. Después sigue el resultado: lee la casilla por IMAP, separa las
respuestas reales de las automáticas, detecta las reuniones agendadas en Calendly o Cal.com,
manda a la lista negra a quien pide la baja y a las direcciones que rebotan, y no vuelve a
escribirles.

Todo corre en la PC de quien la usa: no hay servidor, no hay suscripción y los datos de los
contactos no salen del equipo. Se instala con un instalador propio, sin permisos de
administrador, y una actualización nunca toca la configuración ni la base.

### Relación con el CRM

Pulsemail es la herramienta de envío que Intellihelp usó antes de tener su CRM propio y la que
sigue mandando las campañas hoy. Su motor de envío se está llevando al
[CRM INTELLIHELP](https://github.com/bsierra4262/crm-intellihelp), donde primero se valida en la
instalación de pruebas y después pasa a producción. Cuando esa migración termine, las campañas
se van a manejar desde el CRM y Pulsemail queda como antecedente.

## La aplicación por dentro

Identidad visual de Intellihelp: tipografía Saira y paleta `#663399` · `#9CC930`, con tema
claro, oscuro o el del sistema operativo.

> Las capturas salen de la aplicación real corriendo con **datos ficticios**: una empresa y
> destinatarios inventados, con dominios `.example`, y un servidor SMTP de prueba en la propia
> PC (por eso el panel lateral dice «LOCALHOST SMTP activo»). Ningún correo salió a internet.

### Dashboard

<p align="center"><img src="docs/screenshots/dashboard.png" alt="Dashboard" width="100%"></p>

### Campaña en curso

Cada envío queda en la línea de tiempo con su hora; entre correo y correo, la pausa aleatoria.
El botón pasa a «Detener campaña» y responde en menos de un segundo, aun durante la pausa.

<p align="center"><img src="docs/screenshots/envio-en-curso.png" alt="Campaña en curso" width="100%"></p>

### Base y seguimiento

<table>
  <tr>
    <td width="50%"><b>Contactos</b><br><img src="docs/screenshots/contactos.png" alt="Contactos"></td>
    <td width="50%"><b>Respuestas y reuniones</b><br><img src="docs/screenshots/respuestas.png" alt="Respuestas y reuniones"></td>
  </tr>
  <tr>
    <td width="50%"><b>Rechazados</b><br><img src="docs/screenshots/rechazados.png" alt="Rechazados"></td>
    <td width="50%"><b>Lista negra</b><br><img src="docs/screenshots/lista-negra.png" alt="Lista negra"></td>
  </tr>
  <tr>
    <td width="50%"><b>Estadísticas</b><br><img src="docs/screenshots/estadisticas.png" alt="Estadísticas"></td>
    <td width="50%"><b>Historial por día</b><br><img src="docs/screenshots/historial.png" alt="Historial"></td>
  </tr>
</table>

### Configuración

<table>
  <tr>
    <td width="50%"><b>Cuenta y auto-envío programado</b><br><img src="docs/screenshots/config-cuenta.png" alt="Configuración, cuenta"></td>
    <td width="50%"><b>Mensaje: texto plano o HTML</b><br><img src="docs/screenshots/config-mensaje.png" alt="Configuración, mensaje"></td>
  </tr>
  <tr>
    <td width="50%"><b>Reuniones: Calendly o Cal.com</b><br><img src="docs/screenshots/config-reuniones.png" alt="Configuración, reuniones"></td>
    <td width="50%"><b>WhatsApp</b><br><img src="docs/screenshots/config-whatsapp.png" alt="Configuración, WhatsApp"></td>
  </tr>
  <tr>
    <td width="50%"><b>Datos de la empresa</b><br><img src="docs/screenshots/config-empresa.png" alt="Configuración, empresa"></td>
    <td width="50%"><b>Firma de texto o de imagen</b><br><img src="docs/screenshots/config-firma.png" alt="Configuración, firma"></td>
  </tr>
  <tr>
    <td width="50%"><b>Servidores SMTP e IMAP</b><br><img src="docs/screenshots/config-servidores.png" alt="Configuración, servidores"></td>
    <td width="50%"><b>Apariencia y logo</b><br><img src="docs/screenshots/config-apariencia.png" alt="Configuración, apariencia"></td>
  </tr>
  <tr>
    <td width="50%"><b>Datos: respaldo y migración</b><br><img src="docs/screenshots/config-datos.png" alt="Configuración, datos"></td>
    <td width="50%"></td>
  </tr>
</table>

### Tema oscuro

<p align="center">
  <img src="docs/screenshots/dashboard-oscuro.png" alt="Dashboard en tema oscuro" width="32%">
  &nbsp;
  <img src="docs/screenshots/respuestas-oscuro.png" alt="Respuestas en tema oscuro" width="32%">
  &nbsp;
  <img src="docs/screenshots/estadisticas-oscuro.png" alt="Estadísticas en tema oscuro" width="32%">
</p>

### Lo que recibe el destinatario

<table>
  <tr>
    <td width="50%" valign="top"><b>Texto plano (formato por defecto)</b><br><br>
      Un correo personal, uno a uno, sin imágenes ni enlaces de seguimiento: es el que mejor
      llega a la bandeja principal en frío. El asunto no lleva el nombre del contacto y la firma
      va al cierre, separada.

<pre>
Asunto: Retomando el contacto
Para:   tomas.paz@agrosur.example

¡Hola Tomás!
Hace un tiempo nos pusimos en contacto para
presentarte Nexo Consultores y nuestros servicios.
Me gustaría robarte unos minutos para conversar
y ver si podemos ayudarte con alguna necesidad
del equipo.
Desde ya, muchas gracias por tu tiempo.
Saludos,

Laura Méndez
Gerente comercial
Nexo Consultores
</pre>
    </td>
    <td width="50%"><b>HTML (plantilla con diseño)</b><br><img src="docs/screenshots/correo-html.png" alt="Correo HTML"></td>
  </tr>
</table>

## Características

- **Envío con ritmo humano.** Un correo por vez, pausa aleatoria de 25 a 45 segundos y límite
  diario configurable. Al día siguiente la campaña sigue exactamente donde quedó.
- **Dos formatos.** Texto plano personal, con `@nombre` reemplazado por el nombre de pila, o una
  plantilla HTML maquetada con tablas, CSS en línea y botones con respaldo VML para Outlook.
  Los botones de WhatsApp y de reunión, los datos de la empresa y la firma salen de la
  configuración: si un campo está vacío, esa línea no aparece.
- **Correo de prueba.** Antes de lanzar, un envío a la dirección elegida, armado igual que la
  campaña y sin copiar a los CC.
- **Resistente a cortes de red.** Si se cae internet, reintenta cada 10 segundos hasta 1.000
  veces (casi tres horas) y deja el correo pendiente en disco: aunque se cierre la aplicación,
  al volver retoma ese correo primero.
- **Respuestas y reuniones.** Lectura de la casilla por IMAP con cruce por `Message-ID`,
  `In-Reply-To` y `References`: la respuesta se reconoce aunque venga de otra dirección o con
  otro asunto. Las confirmaciones de Calendly y Cal.com se listan como reuniones.
- **Respuestas automáticas separadas.** «Fuera de la oficina», licencias, casillas cerradas o
  llenas, en español y en inglés, quedan en un filtro aparte para no confundirse con interés
  real.
- **Bajas y rebotes, sin intervención.** Quien responde «BAJA» o pide no recibir más pasa a la
  lista negra; las direcciones que rebotan, también, y además a Rechazados. La campaña las
  saltea siempre. Cada correo lleva `List-Unsubscribe`.
- **Auto-envío programado.** Con la aplicación abierta, lanza la campaña sola todos los días a
  la hora elegida hasta terminar la base.
- **Estadísticas e historial.** Enviados, rechazados y tasa de entrega histórica en torta,
  barras o serie diaria, y la línea de tiempo completa de cada día de campaña.
- **Respaldo en un clic.** Configuración, base, registros e historial en un ZIP que se importa
  en otra PC para continuar la campaña.
- **Notificaciones de Windows** cuando llega una respuesta nueva.

## Arquitectura

Dos módulos: la interfaz y el motor. El motor no depende de la interfaz ni de ninguna librería
externa —sólo de la biblioteca estándar de Python—, lo que permite probarlo por separado.

```mermaid
flowchart LR
    U([Equipo comercial]) --> UI[interfaz.py<br/>Flet · escritorio]
    UI <--> M[enviar_correos.py<br/>motor de envío y lectura]
    M <--> D[(Carpeta de datos del usuario<br/>config · contactos · registros · historial)]
    M -- SMTP + STARTTLS --> G([Gmail / Google Workspace])
    G -- IMAP SSL<br/>respuestas, rebotes, reuniones --> M
    UI -. renderiza el HTML del hilo .-> CH[[Chrome headless]]
    UI -. avisos .-> N[[Notificaciones de Windows]]
```

## Motor de envío

```mermaid
flowchart TD
    CSV[(contactos.csv)] --> L{Recorrer la base}
    EST[(registro_envios.json<br/>último enviado y cuenta del día)] --> L
    PEN[(registro_pendiente.json)] -->|si quedó uno| S
    L -->|ya enviado| AV[Avanzar hasta donde quedó]
    L -->|lista negra o rebote previo| SK[Saltear]
    L -->|límite diario alcanzado| FIN[Pausar hasta mañana]
    L --> P[Armar el correo<br/>texto plano o HTML + firma]
    P --> S[Enviar por SMTP]
    S -->|enviado| OK[Message-ID registrado<br/>+ evento en el historial]
    S -->|550 destinatario| RE[Rechazado · se sigue]
    S -->|535 credenciales| AU[Campaña detenida]
    S -->|sin red| RT[Reintento cada 10 s<br/>hasta 1.000 veces]
    RT --> S
    OK --> ES[Pausa aleatoria 25–45 s] --> L
    IM[[Lectura IMAP]] --> C{Clasificar}
    C -->|pedido de baja| LN[(Lista negra)]
    C -->|rebote| LN
    C -->|rebote| RC[(Rechazados)]
    C -->|respuesta| RS[(Respuestas · reales o automáticas)]
    C -->|Calendly / Cal.com| RU[(Reuniones)]
    LN --> L
    RC --> L
```

**Por qué así:**

- **Pausa aleatoria de 25 a 45 segundos.** Un ritmo regular y rápido es la señal más clara de
  envío automatizado; este rango da unos 80 a 100 correos por hora.
- **Texto plano por defecto.** En frío, un correo sin diseño ni imágenes se parece a uno escrito
  a mano y entra mucho menos a spam.
- **`Message-ID` propio y guardado.** Es lo único que permite cruzar una respuesta con el envío
  que la originó, aunque cambien el remitente o el asunto.
- **El estado se guarda después de cada correo.** Cerrar la aplicación, cortar la luz o perder la
  red no hace volver a empezar la base: la campaña sigue desde el último enviado.
- **Ante la duda, no se reenvía.** Una dirección que rebotó o pidió la baja queda excluida para
  siempre, aunque vuelva a aparecer en una base nueva.

## Seguridad

- **El código no contiene credenciales.** La cuenta y la contraseña empiezan vacías y se cargan
  desde la aplicación (Configuración → Cuenta). Se guardan en `config.json`, en la carpeta de
  datos del usuario: `%LOCALAPPDATA%\Pulsemail\` en la versión instalada, o junto a
  `interfaz.py` al ejecutar desde el código.
- `config.json`, la base de contactos, los registros y el historial están **excluidos por
  `.gitignore`**, y la integración continua falla si alguno llega al repositorio.
- Se usa una **contraseña de aplicación** de Google, no la de la cuenta: requiere verificación
  en dos pasos, sirve sólo para correo y se revoca sin tocar nada más.
- SMTP cifrado con **STARTTLS** antes de autenticar; IMAP sobre **SSL**.
- El respaldo completo incluye `config.json`: el ZIP se guarda como cualquier documento con
  credenciales.
- Política completa en [SECURITY.md](SECURITY.md).

## Stack técnico

| Capa | Tecnología |
| --- | --- |
| Lenguaje | Python 3.11+ |
| Interfaz | Flet 0.84 (Flutter), controles propios para gráficos y pestañas |
| Envío y lectura | `smtplib` e `imaplib` de la biblioteca estándar |
| Persistencia | Archivos JSON y CSV locales, con caché por fecha de modificación |
| Vista de conversaciones | `html2image` sobre Chrome headless |
| Integración con Windows | `ctypes` (diálogos nativos, portapapeles, icono), `plyer` para notificaciones |
| Empaquetado | `flet pack` (PyInstaller) + Inno Setup, instalación por usuario |
| Pruebas | `unittest` + servidor SMTP falso propio, GitHub Actions en Windows y Ubuntu |

## Estructura del proyecto

```
enviar_correos.py      # motor: armado, envío SMTP, lectura IMAP, clasificación, persistencia
interfaz.py            # interfaz Flet: vistas, configuración, hilos de trabajo
bump_version.py        # versionado: VERSION + CHANGELOG.md
build_installer.bat    # compila el .exe y el instalador
_build_helper.py       # invoca flet pack y empaqueta el cliente de escritorio
installer/             # pulsemail.iss (Inno Setup)
tests/                 # pruebas y servidor SMTP falso (smtp_falso.py)
md/                    # manual de usuario y documentación técnica
docs/                  # banner y capturas
```

## Instalación y compilación del instalador

Resumen; el detalle está en [INSTALL.md](INSTALL.md).

**Usar la aplicación:** ejecutar `PulsemailSetup_vX.Y.Z.exe` (no pide permisos de
administrador), cargar la cuenta con su contraseña de aplicación en Configuración → Cuenta,
importar el CSV de contactos y lanzar la campaña desde el Dashboard.

**Desde el código:**

```bash
python -m pip install -r requirements.txt
python interfaz.py
```

**Compilar el instalador** (requiere Inno Setup 6 o 7):

```bat
python bump_version.py patch --notes "Descripción del cambio"
build_installer.bat
```

Genera `installer_output\PulsemailSetup_vX.Y.Z.exe`. La versión vive sólo en `VERSION`; el
`AppId` fijo del instalador permite actualizar sin tocar los datos del usuario.

## Tests

```bash
python -m unittest discover -s tests -v
```

**84 comprobaciones**, sólo con la biblioteca estándar y sin red. Corren en cada push en
GitHub Actions, en Windows y Ubuntu con Python 3.11 y 3.12.

| Archivo | Qué cubre |
| --- | --- |
| `test_mensajes.py` | Armado del correo: asunto, `List-Unsubscribe`, `@nombre` y saludo sin nombre, firma de texto separada y sin duplicar, firma de imagen incrustada por `cid`, CC, plantilla HTML con botones condicionales y logo |
| `test_envio.py` | Envío real por SMTP contra el servidor falso: éxito con `Message-ID` registrado, destinatario rechazado, credenciales inválidas, detención con correo pendiente, correo de prueba sin CC, verificación de cuenta y una **campaña completa**: exclusión por lista negra y por rebote previo, correo secundario, límite diario, reanudación y fin de la base |
| `test_deteccion.py` | Pedidos de baja (sin falsos positivos por «bajas de personal» ni por la cita del correo original), respuestas automáticas en español e inglés, rebotes por remitente y asunto, dirección rebotada, cabeceras codificadas, plataforma de reuniones |
| `test_datos.py` | Configuración por defecto y dañada, contactos, lista negra, rechazados, depurados, progreso diario, historial y estadísticas, `Message-ID` con rotación, respaldo e importación en otra carpeta |
| `test_version.py` | `VERSION` en SemVer, changelog ordenado y al día, instalador leyendo `VERSION`, `bump_version.py` |
| `test_seguridad.py` | Sin credenciales en el código, `.gitignore` con los datos del usuario y ningún dato privado versionado |

`tests/smtp_falso.py` es un servidor SMTP mínimo que **sólo escucha en `127.0.0.1`**, acepta la
conversación completa (autenticación, destinatarios, datos) y guarda los mensajes en memoria.
Puede responder `550` o `535` a pedido para ejercitar los caminos de error, y ofrecer STARTTLS si
se le da un certificado. Las capturas de este README se tomaron con ese mismo servidor.

## Documentación

- [Manual de usuario](md/DOCS_USUARIO.md): cada pantalla, buenas prácticas para no caer en
  spam y solución de problemas.
- [Documentación técnica](md/DOCS_DESARROLLADORES.md): módulos, archivos de datos, hilos,
  detección por IMAP y limitaciones de Flet 0.84.
- [Instalación y compilación](INSTALL.md) · [Contribución](CONTRIBUTING.md) ·
  [Seguridad](SECURITY.md) · [Cambios](CHANGELOG.md)

## Licencia

Software **propietario**, desarrollado **íntegramente por Brian Sierra**. Todos los derechos
reservados. Uso interno de la organización; se prohíbe su redistribución o uso fuera de ese
marco sin autorización expresa y por escrito del autor. El autor conserva su derecho moral de
reconocimiento de autoría (Ley 11.723 art. 52; Convenio de Berna art. 6 bis). Ver
[LICENSE](LICENSE).

## Autor

**Brian Sierra** — Intellihelp. Diseño, desarrollo e implementación completos: motor de envío
SMTP, lectura y clasificación por IMAP, interfaz de escritorio, empaquetado e instalador para
Windows, y pruebas.
