# Changelog

Todos los cambios notables de Pulsemail se documentan en este archivo.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el versionado, [SemVer](https://semver.org/lang/es/).

## [Unreleased]

### Added

- Batería de pruebas automatizadas (`tests/`) con `unittest`: armado de mensajes en texto y
  HTML, firma de texto e imagen, lectura de contactos, lista negra, rechazados, historial,
  detección de bajas, respuestas automáticas y rebotes, versionado y una campaña completa
  enviada contra un servidor SMTP falso en `127.0.0.1`.
- Integración continua en GitHub Actions (Ubuntu y Windows, Python 3.11 y 3.12).
- `README.md` con capturas de cada pantalla, `INSTALL.md`, `CONTRIBUTING.md`,
  `SECURITY.md`, `LICENSE`, `requirements.txt`, `.gitattributes` y `.editorconfig`.

### Changed

- La firma de texto precargada es genérica (Equipo Intellihelp, datos de la empresa) y ya no incluye datos personales.
- La documentación de usuario y la técnica pasan a `md/`; `COMPILAR.md` se integra en
  `INSTALL.md`.
- `bump_version.py` escribe las entradas nuevas con el formato de este archivo, debajo de
  `[Unreleased]`.

## [1.4.7] - 2026-08-24

### Changed

- La firma de texto viene precargada con la firma comercial de la empresa (nombre, cargo,
  teléfonos, web y dirección) y se agrega separada del mensaje por una línea en blanco, como
  una firma real.
- La firma de imagen se reduce a 400 px de ancho; antes salía desproporcionada.

## [1.4.6] - 2026-08-24

### Fixed

- Modo texto: si la firma es de tipo imagen, el correo vuelve a salir como HTML con la imagen
  incrustada al cierre (se había roto en 1.4.5). Si la firma es de texto, sale texto puro con
  esa firma. La firma siempre la pone la aplicación: Gmail no agrega la suya en envíos por SMTP.

## [1.4.5] - 2026-08-24

### Changed

- Modo texto plano 100 % puro: no adjunta la firma de imagen; sólo agrega la firma si es de
  tipo texto. La firma de imagen queda para el modo HTML.

## [1.4.4] - 2026-08-24

### Added

- Modo texto: si la firma es de imagen, se adjunta como alternativa HTML con el mensaje y la
  imagen al cierre.

### Changed

- Correo de prueba: el nombre se deriva de la dirección de prueba (la parte antes de la `@`:
  `ana.gomez` pasa a «Ana Gomez»). Se quita el campo manual de nombre.

## [1.4.3] - 2026-08-24

### Fixed

- El botón «Enviar correo de prueba» usaba un icono inexistente
  (`ft.Icons.OUTGOING_MAIL_ROUNDED`) y la aplicación mostraba un error al abrir
  Configuración → Mensaje. Se reemplaza por `FORWARD_TO_INBOX_ROUNDED` y se verificaron los
  94 iconos de la interfaz.

## [1.4.2] - 2026-08-24

### Changed

- El correo de prueba usa el nombre real del primer contacto de la base para verificar la
  personalización con `@nombre`, e informa qué nombre usó. Sin base cargada, saluda sin nombre
  y lo aclara.

## [1.4.1] - 2026-08-24

### Added

- Botón «Enviar correo de prueba» en Configuración → Mensaje: manda un correo armado igual que
  la campaña (formato y mensaje editado, sin copiar a los CC) a la dirección elegida.

### Changed

- Asunto por defecto del modo texto sin «Fwd:»: «Retomando el contacto».

## [1.4.0] - 2026-08-24

### Added

- Modo de campaña en texto plano, con el formato de un correo personal uno a uno (mejor
  entregabilidad en frío). En Configuración → Mensaje se elige Texto plano o HTML, con asunto y
  cuerpo editables; `@nombre` se reemplaza por el nombre del contacto. Es `text/plain` puro,
  sin el nombre en el asunto y con la firma de texto al cierre. El modo HTML sigue disponible;
  el formato por defecto pasa a ser texto plano.

## [1.3.3] - 2026-07-28

### Fixed

- El `.exe` empaqueta el cliente de Flet (la ventana). Antes, al primer arranque intentaba
  descargarlo de GitHub y fallaba en equipos sin internet o con certificados interceptados
  (`SSL: CERTIFICATE_VERIFY_FAILED`). Ahora la aplicación se instala y abre sin descargar nada:
  `_build_helper.py` baja el cliente una vez y lo incluye en `flet_desktop/app`.

## [1.3.2] - 2026-07-28

### Fixed

- Al borrar el historial, los escaneos vuelven a cargar los rebotes (antes quedaban marcados
  como vistos y no se agregaban de nuevo). El escaneo forzado ignora lo visto y reprocesa todo;
  cada rebote se carga en rechazados y en la lista negra de forma idempotente.

### Changed

- Botones de escaneo con ventana de 60 días y detección por `postmaster` y `mailer-daemon`.
- `revisar_rebotes_recientes` pasa a ser aditivo (no borra). Nuevo `agregar_a_rechazados`.

## [1.3.1] - 2026-07-28

### Fixed

- Detección de respuestas automáticas ampliada: «Ausencia», «cuenta no operativa / account no
  longer available», «de licencia», «fuera de oficina», cuenta cerrada o inexistente, buzón
  lleno, etc. Antes se colaban como respuestas reales. La clasificación se recalcula en cada
  escaneo y el filtro «Reales» la evalúa al vuelo.

## [1.3.0] - 2026-07-28

### Added

- Filtro «Reales / Automáticas» en Respuestas (por defecto, Reales).
- Auto-envío programado en Configuración → Cuenta: la aplicación lanza la campaña cada día a
  la hora elegida, envía hasta el límite diario y sigue al día siguiente donde quedó, hasta
  terminar la base. Se reanuda al cargar una base nueva.

### Changed

- El panel Rechazados incluye los rebotes que se agregaron automáticamente a la lista negra.
- Los pedidos de baja ya no se muestran en Respuestas: van sólo a la lista negra.

## [1.2.2] - 2026-07-14

### Changed

- Los rebotes (`postmaster`, `mailer-daemon`) ya no aparecen en Respuestas: se detectan por
  remitente y por asunto de notificación de no entrega, y la dirección afectada va a la lista
  negra. Se limpian los que se habían colado.

## [1.2.1] - 2026-07-14

### Changed

- Todo correo que rebota se agrega a la lista negra y el envío excluye lista negra y
  rechazados previos: nunca se reenvía a una casilla que ya rebotó.
- Alta en lote a la lista negra con una sola escritura.

## [1.2.0] - 2026-07-13

### Added

- Plantilla HTML con diseño profesional (encabezado, pilares, tipografía Saira, botones con
  respaldo VML para Outlook), configurable por completo: botones de WhatsApp y de reunión
  según la configuración, firma configurada y datos de la empresa en Configuración → Empresa.
- Cabecera `List-Unsubscribe` atada a la respuesta «BAJA».

### Fixed

- Respaldos: los diálogos de tkinter fallaban en el `.exe` (Tcl/Tk no empaquetado). Se
  reemplazan por el diálogo nativo de Windows (`comdlg32`).

## [1.1.4] - 2026-05-21

### Fixed

- La aplicación fallaba al construir el selector «Items por página» de Lista negra: en
  Flet 0.84, `Dropdown` no acepta `on_change` en el constructor y se asigna después. Una
  prueba de humo con una `Page` simulada confirmó que no quedan otros parámetros inválidos.

## [1.1.3] - 2026-05-21

### Changed

- «Escanear bandeja» entre 10 y 50 veces más rápido: cabeceras en lotes de 500 y cuerpos en
  lotes de 100, sólo para los mensajes que hace falta analizar. De unos 5.000 pedidos IMAP en
  30 días a unos 10.
- Espera de 10 s en «Escanear respuestas viejas» para no repetir registros idénticos.
- Sin registros cuando no hay nada nuevo que analizar.
- Lista negra: selector de 200, 500 o 1000 elementos por página y tabla a todo el ancho.

## [1.1.2] - 2026-05-21

### Fixed

- El `.bat` de compilación se cerraba sin compilar porque `python -m flet` no funciona en
  Flet 0.84. Nuevo `_build_helper.py` que invoca `flet_cli.cli.main`, portable a cualquier
  instalación de Python. Se quitaron construcciones del `.bat` que lo cerraban en silencio y
  se garantiza una pausa antes de salir ante un error.

## [1.1.1] - 2026-05-21

### Removed

- Iconos sin uso de la plantilla anterior, artefactos de compilación (`build/`, `dist/`,
  `__pycache__/`, `Pulsemail.spec`) e instaladores previos (`installer_output/`).

## [1.1.0] - 2026-05-20

### Added

- Detección de respuestas por `Message-ID` propio e `In-Reply-To` / `References`: llegan
  aunque el remitente no esté en la base o haya cambiado el asunto.
- «Escanear bandeja» fuerza un escaneo completo e informa las novedades.
- Versionado automático: archivo `VERSION`, `bump_version.py` y este `CHANGELOG.md`.

### Changed

- Consulta frecuente (2,5 s) en Respuestas para detectar casi al instante.
- «Mostrar ignorados» muestra sólo los ignorados.
- Reescaneo retroactivo de bajas: de más de 10 minutos a menos de 30 segundos.
- Contactos e Historial: cambio de pestaña y de página inmediatos (caché de renderizado y
  tope de 200 eventos por día).
- Lista negra con etiquetas legibles en tema claro y oscuro.
