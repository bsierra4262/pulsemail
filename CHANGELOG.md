# Changelog — Pulsemail

Formato basado en [Keep a Changelog](https://keepachangelog.com/) y [SemVer](https://semver.org/).

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

