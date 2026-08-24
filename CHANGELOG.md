# Changelog — Pulsemail

Formato basado en [Keep a Changelog](https://keepachangelog.com/) y [SemVer](https://semver.org/).

## [1.4.0] — 2026-08-24  _minor_

Nuevo modo de campaña en TEXTO PLANO (email personal 1-a-1, mejor entregabilidad en frio). Config -> Mensaje: toggle Texto plano / HTML, con asunto y cuerpo editables (default asunto 'Fwd: Retomando el contacto' y el mensaje de retomar contacto). @nombre se reemplaza por el nombre del contacto. text/plain puro, sin sufijo de nombre en el asunto, con firma de texto al cierre si esta configurada. El modo HTML profesional sigue disponible. Default: texto plano.

## [1.3.3] — 2026-07-28  _patch_

Fix critico de compilacion: el .exe ahora EMPAQUETA el cliente de Flet (la ventana) adentro. Antes flet pack no lo incluia y al primer arranque intentaba descargarlo de GitHub, fallando en PCs sin internet/certificados con 'SSL: CERTIFICATE_VERIFY_FAILED' y la app no abria. Ahora es 100% autonomo (se instala y abre solo, sin descargar nada). _build_helper baja el cliente una vez y lo empaqueta en flet_desktop/app.

## [1.3.2] — 2026-07-28  _patch_

Fix critico rechazados/lista negra: al borrar el historial, los escaneos ahora RE-CARGAN los rebotes (antes el tracking interno los marcaba como vistos y no los re-agregaba). Escaneo forzado (Escanear bandeja / Escanear rebotes) ignora 'vistos' y re-procesa todo; cada rebote se carga en AMBOS (rechazados + lista negra) idempotente. Botones de escaneo con ventana 60 dias y motor robusto (postmaster + mailer-daemon). revisar_rebotes_recientes ahora es aditivo (no borra). Nuevo helper agregar_a_rechazados.

## [1.3.1] — 2026-07-28  _patch_

Fix critico deteccion auto-replies: ampliado parece_auto_reply para cazar 'Ausencia', 'cuenta no operativa / account no longer available', 'de licencia', 'fuera de oficina', cuenta cerrada/inexistente, mailbox full, etc. (antes se colaban como respuestas reales). El cleanup re-clasifica es_auto en cada escaneo (Escanear bandeja corrige lo cacheado de antes y lo persiste); el filtro Reales tambien lo computa al vuelo, se corrige al instante.

## [1.3.0] — 2026-07-28  _minor_

Panel Rechazados ahora incluye los rebotes auto-agregados a la lista negra (existentes + futuros). Respuestas: las BAJA ya no se muestran (van solo a lista negra) y se limpian las que estaban. Nuevo filtro Reales/Automaticas en Respuestas (default Reales) para separar respuestas verdaderas de auto-replies (fuera de oficina, etc.); defensa en UI para no mostrar BAJA/rebotes aunque queden en el archivo. Nuevo Auto-envio programado en Configuracion -> Cuenta: la app lanza la campana sola cada dia a la hora elegida, envia hasta el limite diario y sigue al dia siguiente donde quedo, hasta terminar toda la base; se reanuda al cargar una base nueva.

## [1.2.2] — 2026-07-14  _patch_

Rebotes (postmaster/mailer-daemon) ya NO aparecen en el panel Respuestas: se detectan como bounce y el correo afectado va directo a lista negra. Limpia los rebotes que ya se habian colado en Respuestas. Deteccion por remitente (postmaster/daemon) y por asunto de NDR (Undeliverable/Delivery Status).

## [1.2.1] — 2026-07-14  _patch_

Rebotes no se repiten: todo correo que rebota (postmaster/mailer-daemon no entregable) se agrega automaticamente a la lista negra, y el envio ahora excluye lista negra + rechazados/depurados previos. Nunca se reenvia a una casilla que ya reboto. Helper de lista negra en lote (una sola escritura).

## [1.2.0] — 2026-07-13  _minor_

Fix critico backups: reemplazo dialogos tkinter (fallaban en el .exe por tcl/tk no empaquetado) por dialogo nativo Win32 comdlg32 -> importar/exportar funciona. Nueva campana de correo con diseno profesional (hero, pilares, Saira, botones VML anti-Outlook) y 100% config-driven: botones WhatsApp + Agendar reunion condicionales segun config, firma configurada sale en la campana, datos de empresa en nueva pestana Configuracion -> Empresa. Anti-spam: header List-Unsubscribe atado a BAJA. Nada hardcodeado salvo el asunto.

## [1.1.4] — 2026-05-21  _patch_

**Fix crítico**: la app crasheaba al construir el Dropdown 'Items por página' de Lista Negra con `Dropdown.__init__() got an unexpected keyword argument 'on_change'`. En Flet 0.84 el Dropdown NO acepta `on_change` en `__init__` — sólo se puede setear como atributo después de instanciar. Verificado por smoke test: el resto de widgets (Checkbox, IconButton, Container, ElevatedButton, TextField) sí aceptan callbacks en init, sólo Dropdown es la excepción. Agregué un smoke test transitorio que construye main(page) con un Page mockado para validar que no haya otros errores similares — pasó: cero kwargs inválidos en el resto del código.

## [1.1.3] — 2026-05-21  _patch_

**Escanear bandeja** ahora es 10-50x más rápido: batch fetch de headers (chunks de 500) + batch fetch de cuerpos (chunks de 100) sólo para los UIDs que necesitan análisis. De 5000 round-trips IMAP en una bandeja de 30 días a ~10. **Cooldown 10s** en botón 'Escanear respuestas viejas' (Lista negra) para evitar el spam de logs idénticos en el dashboard cuando se clickea repetidamente y el scan termina instantáneamente sin trabajo nuevo. **Logs silenciosos** cuando no hay nada que analizar — antes ensuciaba el historial con '0 analizadas, 0 nuevas bajas'. **Lista negra**: dropdown para elegir items por página (200/500/1000, default 200 vs 50), tabla envuelta en Row(expand=True) para que ocupe todo el ancho real del panel (antes quedaba colapsada al ancho mínimo de contenido).

## [1.1.2] — 2026-05-21  _patch_

**Fix build**: el .bat se cerraba sin compilar porque `python -m flet` no funciona en flet 0.84 (no expone __main__). Nuevo `_build_helper.py` que importa `flet_cli.cli.main` y lo invoca con sys.argv — portable a cualquier instalación de Python (Windows Store, system Python, venv). El .bat ahora llama al helper. También: saqué `setlocal enabledelayedexpansion` y los `for /f` de trim (causaban cierre silencioso ante caracteres especiales), agregué label `:error` único para garantizar pause antes de cerrar, y los `--add-data` para Flyer/firma son detectados dinámicamente por el helper (PNG primero, JPG fallback).

## [1.1.1] — 2026-05-21  _patch_

Limpieza del repo: removí iconos PNG del template viejo (icon-calendar/cost/process/prod/solution/whatsapp.png — sin referencias en el código actual), artefactos del compilador (build/, dist/, __pycache__/, Pulsemail.spec — se regeneran al compilar) y instaladores previos (installer_output/).

## [1.1.0] — 2026-05-20  _minor_

**Detección de respuestas robusta**: tracking de Message-IDs propios + matching por In-Reply-To/References. Las respuestas llegan aunque el remitente no esté en contactos.csv o hayan cambiado el asunto. **Botón 'Escanear bandeja' fuerza full scan** con reporte de nuevas. **Polling agresivo** (2.5s) en panel Respuestas para detección casi-instantánea. **'Mostrar ignorados' ahora es exclusivo** (sólo ignorados cuando está prendido). **Reescan retroactivo BAJA** en Lista Negra optimizado: 10+ min -> < 30 s (batch fetch IMAP). **Optimización Contactos** (cache de render + safe_update específico): cambiar de pestaña y de página al instante. **Optimización Historial** (cap 200 + cache día): días con 500+ eventos cargan sin lag. **Lista Negra UI**: chips con bg sólido + texto blanco para legibilidad en oscuro/claro; tabla ahora ocupa todo el ancho. **Versionado automático**: archivo VERSION + bump_version.py + CHANGELOG.md.

