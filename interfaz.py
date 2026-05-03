import flet as ft
import threading
import os
import sys
import re
import csv
import json
import atexit
import tempfile
import webbrowser
import enviar_correos
from datetime import datetime

# ── Detección de WebView ──
# NOTA: Flet 0.84 NO soporta WebView en desktop (Windows/macOS/Linux).
# Sólo funciona en mobile (iOS/Android) y web. En desktop el control se
# crea pero al renderizarse muestra "Webview is not yet supported on this
# Platform". Por eso lo deshabilitamos explícitamente en desktop y caemos
# al fallback (Markdown + botón "Ver en navegador" para fidelidad 100%).
_WEBVIEW_CLASS = None
if sys.platform not in ("win32", "linux", "linux2", "darwin"):
    try:
        import flet_webview as _fwv
        _WEBVIEW_CLASS = getattr(_fwv, "WebView", None)
    except Exception:
        pass
    if _WEBVIEW_CLASS is None:
        _WEBVIEW_CLASS = getattr(ft, "WebView", None)

# Archivos temporales de HTML para WebView (se borran al cerrar la app)
_html_temp_files = []

def _html_a_archivo_temp(html_str):
    """Guarda el HTML del correo en un archivo temporal y devuelve URL file://."""
    if not html_str:
        return None
    try:
        f = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                          suffix=".html", delete=False,
                                          prefix="ith_mail_")
        # Wrap mínimo para que el HTML se renderice bien aunque venga sin <html>
        if "<html" not in html_str.lower():
            html_str = (
                "<!doctype html><html><head><meta charset='utf-8'/>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'/>"
                "<style>body{font-family:Arial,sans-serif;margin:8px;}</style>"
                "</head><body>" + html_str + "</body></html>"
            )
        f.write(html_str)
        f.close()
        _html_temp_files.append(f.name)
        return "file:///" + f.name.replace("\\", "/")
    except Exception:
        return None

def _cleanup_html_temps():
    for path in _html_temp_files:
        try:
            os.remove(path)
        except Exception:
            pass

atexit.register(_cleanup_html_temps)


# ── Notificación del sistema operativo ──
# Intenta primero `plyer.notification` (toast nativo Windows 10/11),
# si no está disponible cae a un beep + flash de la ventana. La
# notificación lleva el logo de Pulsemail (Windows requiere .ico).
_NOTIF_ICON_PATH = [None]   # cache del path al .ico una vez generado

def _resolver_icono_notif():
    """Devuelve un path absoluto al ícono que Windows acepta para toasts.
    Convierte logo-app.png → logo-app.ico con PIL si hace falta."""
    if _NOTIF_ICON_PATH[0] and os.path.exists(_NOTIF_ICON_PATH[0]):
        return _NOTIF_ICON_PATH[0]
    ico_path = os.path.join(CARPETA_ACTUAL, "logo-app.ico")
    if os.path.exists(ico_path):
        _NOTIF_ICON_PATH[0] = ico_path
        return ico_path
    png_path = os.path.join(CARPETA_ACTUAL, "logo-app.png")
    if not os.path.exists(png_path):
        png_path = os.path.join(CARPETA_ACTUAL, "ITH-logo.png")
    if not os.path.exists(png_path):
        return None
    # Convertir PNG → ICO (Windows toast lo prefiere así)
    try:
        from PIL import Image as _PILImg
        img = _PILImg.open(png_path).convert("RGBA")
        img.save(
            ico_path,
            sizes=[(16, 16), (32, 32), (48, 48),
                   (64, 64), (128, 128), (256, 256)],
        )
        _NOTIF_ICON_PATH[0] = ico_path
        return ico_path
    except Exception:
        # Si no hay PIL o falla, devolvemos el PNG (algunos backends
        # de plyer lo aceptan también)
        _NOTIF_ICON_PATH[0] = png_path
        return png_path

def notificar_sistema(titulo, mensaje):
    icono = _resolver_icono_notif()
    try:
        from plyer import notification as _plyer_notif
        kwargs = dict(
            title=str(titulo)[:64],
            message=str(mensaje)[:256],
            app_name="Pulsemail",
            timeout=8,
        )
        if icono:
            kwargs["app_icon"] = icono
        _plyer_notif.notify(**kwargs)
        return True
    except Exception:
        pass
    # Fallback: beep del sistema. No es notificación visual pero al menos
    # hace ruido para que el usuario sepa que pasó algo.
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        pass
    return False

# ── Renderizado HTML→PNG con Chrome headless (html2image) ──
# Esto permite que cada correo se vea idéntico a Gmail dentro de la app,
# sin necesidad de un botón externo. La primera renderización tarda 1-2s,
# las siguientes son instantáneas porque cacheamos el PNG por message_id.
_HTI_LOCK     = threading.Lock()
_HTI_INSTANCE = [None]
_HTI_DISPONIBLE = [None]   # None = no probado, True/False = resultado

_HTML_CACHE_DIR = os.path.join(tempfile.gettempdir(), "ith_mail_render_cache")
try:
    os.makedirs(_HTML_CACHE_DIR, exist_ok=True)
except Exception:
    pass

def _hti_init():
    if _HTI_DISPONIBLE[0] is not None:
        return _HTI_DISPONIBLE[0]
    try:
        from html2image import Html2Image
        _HTI_INSTANCE[0] = Html2Image(
            output_path=_HTML_CACHE_DIR,
            size=(900, 3500),
            custom_flags=[
                "--default-background-color=FFFFFF",
                "--hide-scrollbars",
                # virtual-time-budget bajo = Chrome no espera tanto a recursos
                "--virtual-time-budget=2500",
                "--disable-gpu",
                "--no-sandbox",
                # JS deshabilitado: los HTML de correo no lo necesitan y
                # ahorra bastante tiempo de "waiting for ready"
                "--disable-javascript",
                "--disable-extensions",
                "--disable-software-rasterizer",
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-sync",
                "--disable-translate",
                "--disable-features=Translate,BackForwardCache",
                "--no-first-run",
                "--no-default-browser-check",
                "--mute-audio",
                "--blink-settings=imagesEnabled=true",
            ],
        )
        _HTI_DISPONIBLE[0] = True
    except Exception:
        _HTI_DISPONIBLE[0] = False
    return _HTI_DISPONIBLE[0]

def _html_a_imagen(html_str, message_id):
    """Genera (o reusa de caché) un PNG del HTML. Devuelve path o None si falla."""
    if not html_str:
        return None
    if not _hti_init():
        return None

    safe_id = re.sub(r"[^a-zA-Z0-9]", "_", message_id or "")[:80] or "anon"
    fingerprint = abs(hash(html_str)) % (10 ** 10)
    nombre = f"{safe_id}_{fingerprint}.png"
    path   = os.path.join(_HTML_CACHE_DIR, nombre)

    if os.path.exists(path):
        return path

    # Override de margin/padding para que el render no quede con borde
    # blanco gigante alrededor del contenido. Inyectamos un <style> que
    # gana por especificidad/orden.
    style_override = (
        "<style>"
        "html,body{margin:0!important;padding:0!important;"
        "background:#ffffff!important;}"
        "body{font-family:Arial,sans-serif;}"
        "table{border-collapse:collapse;}"
        "img{max-width:100%;height:auto;}"
        "</style>"
    )
    if "<html" in html_str.lower():
        if re.search(r"</head>", html_str, flags=re.IGNORECASE):
            html_str = re.sub(
                r"</head>", style_override + "</head>",
                html_str, count=1, flags=re.IGNORECASE,
            )
        else:
            html_str = re.sub(
                r"<html[^>]*>",
                lambda m: m.group(0) + "<head>" + style_override + "</head>",
                html_str, count=1, flags=re.IGNORECASE,
            )
    else:
        html_str = (
            "<!doctype html><html><head><meta charset='utf-8'/>"
            "<meta name='viewport' content='width=760'/>"
            + style_override
            + "</head><body>" + html_str + "</body></html>"
        )

    try:
        with _HTI_LOCK:
            _HTI_INSTANCE[0].screenshot(html_str=html_str, save_as=nombre)
    except Exception:
        return None

    if not os.path.exists(path):
        return None

    # Recortar el whitespace blanco al rededor del PNG (arriba/abajo y
    # también lateral). Esto evita las "tarjetas blancas" gigantes que
    # quedaban cuando el HTML del correo tenía padding grande o cuando
    # el contenido no llenaba todo el viewport.
    try:
        from PIL import Image as _PIL_Image, ImageChops as _PIL_ImageChops
        img = _PIL_Image.open(path).convert("RGB")
        bg  = _PIL_Image.new("RGB", img.size, (255, 255, 255))
        diff = _PIL_ImageChops.difference(img, bg)
        bbox = diff.getbbox()
        if bbox:
            left   = max(0, bbox[0] - 4)
            top    = max(0, bbox[1] - 4)
            right  = min(img.width,  bbox[2] + 4)
            bottom = min(img.height, bbox[3] + 8)
            cropped = img.crop((left, top, right, bottom))
            cropped.save(path)
    except Exception:
        pass

    return path

# ==========================================
# 1. PALETA DE COLORES CORPORATIVOS
# ==========================================
C_MORADO        = "#663399"
C_MORADO_DARK   = "#4d2673"
C_MORADO_LIGHT  = "#f0e8f8"
C_VERDE         = "#9BCB31"
C_VERDE_DARK    = "#7aaa1f"
C_VERDE_LIGHT   = "#f1f9e4"
C_BLANCO        = "#FFFFFF"
C_FONDO         = "#f7f5fc"
C_TEXTO_1       = "#1a1025"
C_TEXTO_2       = "#5a4d6e"
C_TEXTO_3       = "#9b8fb0"
C_BORDE         = "#e8e0f0"
C_ROJO          = "#e05474"
C_ROJO_LIGHT    = "#fdedf1"
C_NARANJA       = "#f0922b"
C_NARANJA_LIGHT = "#fff3e6"
C_AZUL          = "#4a90d9"
C_AZUL_LIGHT    = "#eaf3fb"
C_EXITO         = "#2ecc71"
C_EXITO_LIGHT   = "#edfaf0"

CARPETA_ACTUAL = os.path.dirname(os.path.abspath(__file__))


# ==========================================
# 1B. SOPORTE DE TEMA CLARO / OSCURO
# ==========================================
def es_dark_so():
    """Detecta si Windows está en modo oscuro leyendo el registry."""
    try:
        import winreg
        registry = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
        key = winreg.OpenKey(
            registry,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return value == 0   # 0 = oscuro, 1 = claro
    except Exception:
        return False


def resolver_tema(pref):
    """pref: 'claro' | 'oscuro' | 'sistema'. Devuelve 'claro' u 'oscuro'."""
    pref = (pref or "sistema").lower()
    if pref == "claro":
        return "claro"
    if pref == "oscuro":
        return "oscuro"
    return "oscuro" if es_dark_so() else "claro"


# Flag para que los watchers daemon se inicien sólo una vez,
# aunque se haga rebuild de la UI al cambiar de tema.
_INIT_HECHO = [False]

# Cache global de estado SMTP: (ok, mensaje, correo_mostrado).
# Se persiste entre rebuilds para no tener que re-validar IMAP/SMTP cada
# vez que el usuario cambia de tema.
_SMTP_CACHE = [None]

# Vista a la que navegar al construir la UI. Se setea desde
# `_cambiar_tema` para preservar la pestaña activa al cambiar tema.
_VISTA_INICIAL = ["dashboard"]

# Sub-pestaña activa de Configuración (cuenta | firma | servidores | apariencia)
# Persiste también entre rebuilds.
_CFG_TAB_INICIAL = ["cuenta"]


def aplicar_tema(modo):
    """Reasigna las constantes globales que dependen del tema. Llamar ANTES
    de construir la UI."""
    if modo == "oscuro":
        # Paleta basada en grises neutros (no violeta) para que el morado/verde
        # de la marca destaquen como acentos. Texto con contraste alto AA.
        # En oscuro subimos la luminosidad de los acentos (morado/verde/rojo)
        # para que se vean legibles sobre fondos oscuros y sobre los chips
        # de C_*_LIGHT (que son oscuros).
        nuevos = {
            "C_BLANCO":         "#1e2329",   # cards (gris muy oscuro azulado)
            "C_FONDO":          "#13171c",   # background general
            "C_TEXTO_1":        "#f0f4f8",   # texto principal (casi blanco)
            "C_TEXTO_2":        "#c2cbd6",   # texto secundario (gris claro legible)
            "C_TEXTO_3":        "#8a96a4",   # texto terciario (gris medio)
            "C_BORDE":          "#2d343d",
            # Acentos brillantes para legibilidad
            "C_MORADO":         "#a47cd9",
            "C_MORADO_DARK":    "#7a5cb8",
            "C_VERDE":          "#a8d440",
            "C_VERDE_DARK":     "#88b033",
            "C_ROJO":           "#e87a96",
            "C_NARANJA":        "#f0a85c",
            "C_AZUL":           "#6db1e8",
            "C_EXITO":          "#56d68a",
            # Fondos de chips/badges (oscuros con acento)
            "C_MORADO_LIGHT":   "#3a2856",
            "C_VERDE_LIGHT":    "#243a1f",
            "C_ROJO_LIGHT":     "#3d2129",
            "C_NARANJA_LIGHT":  "#3d2a1c",
            "C_AZUL_LIGHT":     "#1f2d40",
            "C_EXITO_LIGHT":    "#243a1f",
        }
    else:
        nuevos = {
            "C_BLANCO":         "#FFFFFF",
            "C_FONDO":          "#f7f5fc",
            "C_TEXTO_1":        "#1a1025",
            "C_TEXTO_2":        "#5a4d6e",
            "C_TEXTO_3":        "#9b8fb0",
            "C_BORDE":          "#e8e0f0",
            # Acentos clásicos (claro)
            "C_MORADO":         "#663399",
            "C_MORADO_DARK":    "#4d2673",
            "C_VERDE":          "#9BCB31",
            "C_VERDE_DARK":     "#7aaa1f",
            "C_ROJO":           "#e05474",
            "C_NARANJA":        "#f0922b",
            "C_AZUL":           "#4a90d9",
            "C_EXITO":          "#2ecc71",
            # Fondos pastel
            "C_MORADO_LIGHT":   "#f0e8f8",
            "C_VERDE_LIGHT":    "#f1f9e4",
            "C_ROJO_LIGHT":     "#fdedf1",
            "C_NARANJA_LIGHT":  "#fff3e6",
            "C_AZUL_LIGHT":     "#eaf3fb",
            "C_EXITO_LIGHT":    "#edfaf0",
        }
    g = globals()
    for k, v in nuevos.items():
        g[k] = v


# ==========================================
# 2. REDIRECCIONADOR DE CONSOLA
# ==========================================
class RedireccionConsola:
    def __init__(self, fn_agregar_log, fn_actualizar_metricas):
        self.fn_agregar_log         = fn_agregar_log
        self.fn_actualizar_metricas = fn_actualizar_metricas
        self.buffer                 = ""

    def write(self, texto):
        self.buffer += texto
        if "\n" in self.buffer:
            lineas = self.buffer.split("\n")
            for linea in lineas[:-1]:
                if linea.strip():
                    self._procesar_linea(linea.strip())
            self.buffer = lineas[-1]

    def _procesar_linea(self, linea):
        tipo  = "info"
        lower = linea.lower()
        if "éxito" in lower or "excelente" in lower or "finalizada" in lower or "enviado" in lower:
            tipo = "success"
        elif "advertencia" in lower or "atención" in lower or "máximo" in lower or "pausando" in lower or "atencion" in lower:
            tipo = "warning"
        elif "error" in lower or "problema" in lower or "falló" in lower or "no se encontró" in lower or "fallo" in lower:
            tipo = "error"

        self.fn_agregar_log(tipo, linea)

        match_envio = re.search(r"\(Van (\d+) de (\d+)\)", linea)
        if match_envio:
            self.fn_actualizar_metricas(match_envio.group(1), match_envio.group(2), None)

        match_rebote = re.search(r"(\d+) (?:rebotaron|rechazados?)", linea)
        if match_rebote:
            match_total = re.search(r"De (\d+) correos", linea)
            enviados = match_total.group(1) if match_total else "0"
            self.fn_actualizar_metricas(enviados, str(enviar_correos.LIMITE_DIARIO()), match_rebote.group(1))

    def flush(self):
        pass


# ==========================================
# 3. INTERFAZ GRÁFICA PRINCIPAL
# ==========================================
def main(page: ft.Page):
    # Resolver y aplicar tema ANTES de cualquier referencia a las constantes
    _cfg_inicial = enviar_correos.cargar_config()
    _pref_tema   = _cfg_inicial.get("tema", "sistema")
    _tema_efectivo = resolver_tema(_pref_tema)
    aplicar_tema(_tema_efectivo)

    page.title    = "Pulsemail — Outreach Suite"
    page.bgcolor  = C_FONDO
    page.theme_mode = (ft.ThemeMode.DARK if _tema_efectivo == "oscuro"
                       else ft.ThemeMode.LIGHT)

    # Tamaño/posición de la ventana sólo se setea la primera vez; al
    # rebuildear por cambio de tema mantenemos lo que el usuario haya
    # dejado (maximizado, redimensionado, etc.).
    if not _INIT_HECHO[0]:
        page.window.width      = 1200
        page.window.height     = 820
        page.window.min_width  = 960
        page.window.min_height = 660
        page.padding           = 0

    # ── Branding de la ventana ─────────────────────────────────────
    # Título de la ventana
    try:
        page.window.title = "Pulsemail — Outreach Suite"
    except Exception:
        pass

    # Ícono de la app: logo-app.png (creado por el usuario). NOTA: con
    # `py interfaz.py` Windows muestra en la barra de tareas el ícono del
    # runtime de Flet — esto recién se aplica al compilar con `flet pack`
    # (ver dependencias.txt). Igual seteamos page.window.icon por si
    # alguna versión de Flet lo respeta.
    _logo_app = os.path.join(CARPETA_ACTUAL, "logo-app.png")
    if not os.path.exists(_logo_app):
        # Fallback al logo del cliente si todavía no existe el de la app
        _logo_app = os.path.join(CARPETA_ACTUAL, "ITH-logo.png")
    if os.path.exists(_logo_app):
        for setter in (
            lambda v: setattr(page.window, "icon", v),
            lambda v: setattr(page, "window_icon", v),
        ):
            try:
                setter(_logo_app)
            except Exception:
                pass
    page.fonts = {
        "Saira": "https://fonts.gstatic.com/s/saira/v14/memXYa2wxmKQyPMrZX79wwYZQMhsyuShhKMjjbU9uXuA.woff2"
    }
    page.theme = ft.Theme(font_family="Saira")

    # ── Recuperar estado del día (si la app se cerró a mitad de campaña) ──
    _enviados_iniciales, _ultimo_email_inicial = enviar_correos.estado_de_hoy()
    _hoy = datetime.now().strftime("%Y-%m-%d")
    _hist_hoy = enviar_correos.cargar_historial_dia(_hoy)
    _rebotes_iniciales = int(_hist_hoy.get("rebotes", 0) or 0)
    _limite_inicial    = enviar_correos.LIMITE_DIARIO()

    # ── Estado global ──────────────────────────────────────────────
    enviados_val   = [_enviados_iniciales]
    limite_val     = [_limite_inicial]
    rebotes_val    = [_rebotes_iniciales]
    campana_activa = [False]
    vista_actual   = ["dashboard"]
    fecha_actual   = [_hoy]
    ir_a_vista     = [None]  # se setea más abajo cuando definimos nav_item
    respuestas_no_vistas = [0]  # contador para el badge del sidebar

    # ── Helper de refresco seguro (Flet 0.84 a veces no propaga desde threads) ──
    def safe_update(*controles):
        """Refresca la página y opcionalmente controles individuales, ignorando errores."""
        for c in controles:
            try:
                c.update()
            except Exception:
                pass
        try:
            page.update()
        except Exception:
            pass

    # ── Helper: portapapeles. En Flet 0.84 page.set_clipboard fue removido. ──
    def copiar_portapapeles(texto):
        if texto is None:
            return False
        texto = str(texto)
        # Intento 1: APIs nativas de Flet (varían entre versiones)
        for nombre in ("set_clipboard", "set_clipboard_async", "copy_to_clipboard"):
            fn = getattr(page, nombre, None)
            if callable(fn):
                try:
                    fn(texto)
                    return True
                except Exception:
                    pass
        # Intento 2: Tkinter (siempre disponible en Python estándar)
        try:
            import tkinter
            r = tkinter.Tk()
            r.withdraw()
            r.clipboard_clear()
            r.clipboard_append(texto)
            r.update()
            r.destroy()
            return True
        except Exception:
            pass
        # Intento 3: subprocess Windows
        try:
            import subprocess
            subprocess.run(["clip"], input=texto.encode("utf-16le"),
                           check=True, shell=False)
            return True
        except Exception:
            return False

    # ── Heartbeat asyncio: fuerza re-render desde el loop principal cada 0.4s. ──
    # En Flet 0.84 los page.update() desde threads daemon no propagan hasta que
    # ocurre una interacción. Este heartbeat dispara updates desde el event loop.
    async def _heartbeat_render():
        import asyncio as _aio
        while True:
            await _aio.sleep(0.4)
            try:
                page.update()
            except Exception:
                pass

    if not _INIT_HECHO[0]:
        try:
            page.run_task(_heartbeat_render)
        except Exception:
            pass

    # ── Borde helper ──────────────────────────────────────────────
    def borde_all(w, color):
        s = ft.BorderSide(w, color)
        return ft.Border(s, s, s, s)

    # ── KPI labels (con valores recuperados) ──────────────────────
    lbl_enviados = ft.Text(str(_enviados_iniciales), size=38, weight=ft.FontWeight.BOLD,
                            color=C_MORADO,  font_family="Saira")
    lbl_limite   = ft.Text(str(_limite_inicial), size=38, weight=ft.FontWeight.BOLD,
                            color=C_TEXTO_1, font_family="Saira")
    lbl_rebotes  = ft.Text(str(_rebotes_iniciales), size=38, weight=ft.FontWeight.BOLD,
                            color=C_ROJO, font_family="Saira")

    _tasa_inicial = max(0, (_enviados_iniciales - _rebotes_iniciales) / _enviados_iniciales * 100) \
                    if _enviados_iniciales > 0 else 0
    lbl_tasa = ft.Text(f"{_tasa_inicial:.1f}%", size=38, weight=ft.FontWeight.BOLD,
                       color=C_VERDE, font_family="Saira")

    barra_progreso = ft.ProgressBar(
        value=min(_enviados_iniciales / max(_limite_inicial, 1), 1.0),
        color=C_VERDE, bgcolor=C_BORDE, height=6,
        border_radius=ft.BorderRadius(4, 4, 4, 4),
    )
    lbl_progreso_pct = ft.Text(f"{_enviados_iniciales} / {_limite_inicial}",
                                size=12, color=C_TEXTO_3, font_family="Saira")

    # Estado inicial visible si hay sesión recuperada
    if _enviados_iniciales > 0:
        texto_estado_inicial = f"Sesión retomada: {_enviados_iniciales} ya enviados hoy."
    else:
        texto_estado_inicial = "Listo para iniciar"

    # Historial con auto_scroll configurable
    historial_ascendente = [True]
    lista_actividad = ft.ListView(
        expand=True, spacing=8,
        padding=ft.Padding(16, 12, 16, 12),
        auto_scroll=True,
    )
    texto_estado = ft.Text(texto_estado_inicial, size=13, color=C_TEXTO_3,
                           italic=True, font_family="Saira")
    ring_estado  = ft.ProgressRing(color=C_VERDE, width=22, height=22,
                                   stroke_width=2.5, visible=False)

    # ── KPI card ──────────────────────────────────────────────────
    def kpi_card(titulo, widget_valor, subtitulo, color_acento, bg_acento,
                 on_click=None):
        return ft.Container(
            expand=True,
            bgcolor=C_BLANCO,
            border_radius=ft.BorderRadius(14, 14, 14, 14),
            border=borde_all(1, C_BORDE),
            padding=ft.Padding(24, 20, 24, 20),
            on_click=on_click,
            ink=on_click is not None,
            tooltip="Ver detalle de rechazados" if on_click else None,
            content=ft.Column(
                spacing=6,
                controls=[
                    ft.Text(titulo.upper(), size=10, weight=ft.FontWeight.BOLD,
                            color=C_TEXTO_3, font_family="Saira"),
                    widget_valor,
                    ft.Container(
                        bgcolor=bg_acento,
                        border_radius=ft.BorderRadius(20, 20, 20, 20),
                        padding=ft.Padding(10, 3, 10, 3),
                        content=ft.Text(subtitulo, size=11, color=color_acento,
                                        weight=ft.FontWeight.W_500, font_family="Saira"),
                    ),
                ],
            ),
        )

    def _abrir_rechazados(e=None):
        if ir_a_vista[0]:
            ir_a_vista[0]("rechazados")

    card_enviados = kpi_card("Enviados hoy",  lbl_enviados, "correos salientes", C_MORADO,  C_MORADO_LIGHT)
    card_limite   = kpi_card("Límite diario", lbl_limite,   "cuota configurada", C_TEXTO_2, C_FONDO)
    card_rebotes  = kpi_card("Rechazados",    lbl_rebotes,  "ver detalle",       C_ROJO,    C_ROJO_LIGHT,
                              on_click=_abrir_rechazados)
    card_tasa     = kpi_card("Tasa de éxito", lbl_tasa,     "de entregas",       C_VERDE,   C_VERDE_LIGHT)

    # ── Actualizar métricas ───────────────────────────────────────
    def actualizar_metricas(enviados, limite, rebotes):
        if enviados is not None:
            enviados_val[0] = int(enviados)
            lbl_enviados.value = str(enviados)
        if limite is not None:
            limite_val[0] = int(limite)
            lbl_limite.value = str(limite)
        if rebotes is not None:
            rebotes_val[0] = int(rebotes)
            lbl_rebotes.value = str(rebotes)

        env = enviados_val[0]
        lim = limite_val[0] or 1
        reb = rebotes_val[0]

        barra_progreso.value   = min(env / lim, 1.0)
        lbl_progreso_pct.value = f"{env} / {lim}"
        tasa = max(0, (env - reb) / env * 100) if env > 0 else 0
        lbl_tasa.value = f"{tasa:.1f}%"
        safe_update()

    # ── Log de eventos ────────────────────────────────────────────
    TIPOS_LOG = {
        "success": (C_EXITO,   C_EXITO_LIGHT,   ft.Icons.CHECK_CIRCLE_ROUNDED,  "ÉXITO"),
        "warning": (C_NARANJA, C_NARANJA_LIGHT,  ft.Icons.WARNING_AMBER_ROUNDED, "AVISO"),
        "error":   (C_ROJO,    C_ROJO_LIGHT,     ft.Icons.ERROR_ROUNDED,         "ERROR"),
        "info":    (C_AZUL,    C_AZUL_LIGHT,     ft.Icons.INFO_ROUNDED,          "INFO"),
    }

    def agregar_log(tipo, mensaje):
        color, bg, icono, label = TIPOS_LOG.get(tipo, TIPOS_LOG["info"])
        hora = datetime.now().strftime("%H:%M:%S")

        fila = ft.Container(
            bgcolor=bg,
            border_radius=ft.BorderRadius(10, 10, 10, 10),
            padding=ft.Padding(14, 10, 14, 10),
            border=borde_all(1, color + "40"),
            content=ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=12,
                controls=[
                    ft.Container(
                        bgcolor=color + "25",
                        border_radius=ft.BorderRadius(8, 8, 8, 8),
                        padding=ft.Padding(6, 6, 6, 6),
                        content=ft.Icon(icono, color=color, size=16),
                    ),
                    ft.Container(
                        bgcolor=color,
                        border_radius=ft.BorderRadius(6, 6, 6, 6),
                        padding=ft.Padding(8, 2, 8, 2),
                        content=ft.Text(label, size=9, color=C_BLANCO,
                                        weight=ft.FontWeight.BOLD, font_family="Saira"),
                    ),
                    ft.Text(mensaje, size=13, color=C_TEXTO_1,
                            expand=True, font_family="Saira"),
                    ft.Text(hora, size=11, color=C_TEXTO_3, font_family="Saira"),
                ],
            ),
        )

        if historial_ascendente[0]:
            lista_actividad.controls.append(fila)
        else:
            lista_actividad.controls.insert(0, fila)
        safe_update()

    sys.stdout = RedireccionConsola(agregar_log, actualizar_metricas)

    # ── Botón iniciar ─────────────────────────────────────────────
    def _contenido_btn(label, icono):
        return ft.Row(
            [ft.Icon(icono, color=C_BLANCO, size=18),
             ft.Text(label, color=C_BLANCO, size=15,
                     weight=ft.FontWeight.BOLD, font_family="Saira")],
            alignment=ft.MainAxisAlignment.CENTER, spacing=8,
        )

    def arrancar(e):
        if campana_activa[0]:
            return
        cfg = enviar_correos.cargar_config()
        if not cfg.get("correo") or not cfg.get("password"):
            agregar_log("error", "No hay cuenta configurada. Ir a Configuración primero.")
            return
        campana_activa[0]    = True
        btn_iniciar.disabled = True
        ring_estado.visible  = True
        texto_estado.value   = "Campaña en ejecución..."
        btn_iniciar.content  = _contenido_btn("En proceso...", ft.Icons.HOURGLASS_TOP_ROUNDED)
        safe_update()

        def trabajador():
            try:
                enviar_correos.main()
            except Exception as ex:
                agregar_log("error", str(ex))
            finally:
                campana_activa[0]    = False
                btn_iniciar.disabled = False
                ring_estado.visible  = False
                texto_estado.value   = "Campaña finalizada."
                btn_iniciar.content  = _contenido_btn("Iniciar campaña", ft.Icons.SEND_ROUNDED)
                safe_update()

        threading.Thread(target=trabajador, daemon=True).start()

    btn_iniciar = ft.ElevatedButton(
        on_click=arrancar,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: C_VERDE,
                     ft.ControlState.HOVERED: C_VERDE_DARK},
            shape=ft.RoundedRectangleBorder(radius=10),
            elevation={ft.ControlState.DEFAULT: 0,
                       ft.ControlState.HOVERED: 4},
            animation_duration=200,
            padding=ft.Padding(28, 16, 28, 16),
        ),
        content=_contenido_btn("Iniciar campaña", ft.Icons.SEND_ROUNDED),
    )

    def limpiar_log(e):
        lista_actividad.controls.clear()
        safe_update()

    btn_limpiar = ft.TextButton(
        "Limpiar historial",
        on_click=limpiar_log,
        style=ft.ButtonStyle(color=C_TEXTO_3),
    )

    # ==========================================
    # PANEL DASHBOARD
    # ==========================================
    panel_kpis = ft.Row(
        spacing=16,
        controls=[card_enviados, card_limite, card_rebotes, card_tasa],
    )

    panel_progreso = ft.Container(
        bgcolor=C_BLANCO,
        border_radius=ft.BorderRadius(14, 14, 14, 14),
        border=borde_all(1, C_BORDE),
        padding=ft.Padding(24, 16, 24, 16),
        content=ft.Column(
            spacing=10,
            controls=[
                ft.Row(
                    controls=[
                        ft.Text("Progreso de campaña", size=13, weight=ft.FontWeight.BOLD,
                                color=C_TEXTO_1, font_family="Saira"),
                        ft.Container(expand=True),
                        lbl_progreso_pct,
                    ],
                ),
                barra_progreso,
            ],
        ),
    )

    # Toggle orden historial
    lbl_orden_btn = ft.Text("↑ Más nuevo abajo", size=12, color=C_TEXTO_3, font_family="Saira")
    def toggle_orden(e):
        historial_ascendente[0] = not historial_ascendente[0]
        lista_actividad.auto_scroll = historial_ascendente[0]
        if historial_ascendente[0]:
            lbl_orden_btn.value = "↑ Más nuevo abajo"
            lista_actividad.controls.sort(
                key=lambda c: c.content.controls[-1].value
            )
        else:
            lbl_orden_btn.value = "↓ Más nuevo arriba"
            lista_actividad.controls.sort(
                key=lambda c: c.content.controls[-1].value, reverse=True
            )
        safe_update()

    btn_orden = ft.TextButton(
        content=lbl_orden_btn,
        on_click=toggle_orden,
        style=ft.ButtonStyle(color=C_TEXTO_3),
    )

    panel_log = ft.Container(
        expand=True,
        bgcolor=C_BLANCO,
        border_radius=ft.BorderRadius(14, 14, 14, 14),
        border=borde_all(1, C_BORDE),
        content=ft.Column(
            expand=True,
            spacing=0,
            controls=[
                ft.Container(
                    padding=ft.Padding(20, 14, 20, 14),
                    border=ft.Border(
                        bottom=ft.BorderSide(1, C_BORDE),
                        top=ft.BorderSide(0, "transparent"),
                        left=ft.BorderSide(0, "transparent"),
                        right=ft.BorderSide(0, "transparent"),
                    ),
                    content=ft.Row(
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(ft.Icons.LIST_ALT_ROUNDED, color=C_MORADO, size=18),
                            ft.Text("Historial de eventos", size=14, weight=ft.FontWeight.BOLD,
                                    color=C_TEXTO_1, font_family="Saira", expand=True),
                            btn_orden,
                            btn_limpiar,
                        ],
                    ),
                ),
                ft.Container(expand=True, content=lista_actividad),
            ],
        ),
    )

    vista_dashboard = ft.Column(
        expand=True,
        spacing=20,
        controls=[panel_kpis, panel_progreso, panel_log],
    )

    # ==========================================
    # PANEL CONTACTOS — paginado, carga async, buscador
    # ==========================================
    contactos_data       = []   # dataset completo
    contactos_filtrados  = []   # subconjunto visible (después del filtro)
    pagina_contactos     = [0]
    TAM_PAGINA           = 200
    contactos_cargando   = [False]
    filtro_actual        = [""]

    lbl_contactos_total = ft.Text("", size=12, color=C_TEXTO_3, font_family="Saira")
    lbl_csv_path        = ft.Text("", size=11, color=C_TEXTO_3, font_family="Saira", italic=True)
    lbl_pagina          = ft.Text("", size=12, color=C_TEXTO_2, font_family="Saira")
    ring_contactos      = ft.ProgressRing(color=C_MORADO, width=18, height=18,
                                          stroke_width=2.5, visible=False)

    tabla_contactos_rows = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Nombre", font_family="Saira", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Apellido", font_family="Saira", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Empresa", font_family="Saira", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Correo Principal", font_family="Saira", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Correo 2", font_family="Saira", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Correo 3", font_family="Saira", weight=ft.FontWeight.BOLD)),
        ],
        rows=[],
        border=ft.border.all(1, C_BORDE),
        border_radius=10,
        heading_row_color=C_FONDO,
        heading_row_height=46,
        data_row_min_height=44,
        column_spacing=32,
        horizontal_lines=ft.BorderSide(1, C_BORDE),
        expand=True,
    )

    def _render_pagina_contactos():
        tabla_contactos_rows.rows.clear()
        total_filtrado = len(contactos_filtrados)
        if total_filtrado == 0:
            lbl_pagina.value = "Sin resultados"
            safe_update()
            return
        max_pag = max(0, (total_filtrado - 1) // TAM_PAGINA)
        if pagina_contactos[0] > max_pag:
            pagina_contactos[0] = max_pag
        if pagina_contactos[0] < 0:
            pagina_contactos[0] = 0
        ini = pagina_contactos[0] * TAM_PAGINA
        fin = min(ini + TAM_PAGINA, total_filtrado)
        for fila in contactos_filtrados[ini:fin]:
            tabla_contactos_rows.rows.append(
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(fila.get("Nombre", ""), font_family="Saira", size=13)),
                    ft.DataCell(ft.Text(fila.get("Apellidos", ""), font_family="Saira", size=13)),
                    ft.DataCell(ft.Text(fila.get("Nombre de Cuenta", ""), font_family="Saira", size=13)),
                    ft.DataCell(ft.Text(fila.get("Correo electrónico", ""), font_family="Saira", size=13)),
                    ft.DataCell(ft.Text(fila.get("Correo electrónico secundario", ""), font_family="Saira", size=13)),
                    ft.DataCell(ft.Text(fila.get("Correo electrónico terciario", ""), font_family="Saira", size=13)),
                ])
            )
        lbl_pagina.value = (
            f"Mostrando {ini + 1}–{fin} de {total_filtrado:,}".replace(",", ".")
            + f"  •  Página {pagina_contactos[0] + 1} / {max_pag + 1}"
        )
        safe_update()

    def _aplicar_filtro_contactos():
        nonlocal contactos_filtrados
        q = (filtro_actual[0] or "").strip().lower()
        if not q:
            contactos_filtrados = contactos_data
        else:
            contactos_filtrados = [
                f for f in contactos_data
                if q in (f.get("Nombre", "") or "").lower()
                or q in (f.get("Apellidos", "") or "").lower()
                or q in (f.get("Nombre de Cuenta", "") or "").lower()
                or q in (f.get("Correo electrónico", "") or "").lower()
                or q in (f.get("Correo electrónico secundario", "") or "").lower()
                or q in (f.get("Correo electrónico terciario", "") or "").lower()
            ]
        pagina_contactos[0] = 0
        _render_pagina_contactos()

    def cargar_contactos(forzar=False):
        if contactos_cargando[0]:
            return
        ruta = enviar_correos.ARCHIVO_CSV
        if not os.path.exists(ruta):
            lbl_contactos_total.value = "Archivo contactos.csv no encontrado"
            lbl_csv_path.value = ruta
            tabla_contactos_rows.rows.clear()
            safe_update()
            return
        if contactos_data and not forzar:
            _aplicar_filtro_contactos()
            return

        lbl_csv_path.value      = ruta
        ring_contactos.visible  = True
        lbl_contactos_total.value = "Cargando..."
        contactos_cargando[0]   = True
        tabla_contactos_rows.rows.clear()
        safe_update()

        def trabajador():
            nonlocal contactos_data, contactos_filtrados
            try:
                nuevos = []
                with open(ruta, "r", encoding="utf-8") as f:
                    for fila in csv.DictReader(f):
                        nuevos.append(fila)
                contactos_data       = nuevos
                contactos_filtrados  = nuevos
                pagina_contactos[0]  = 0
                lbl_contactos_total.value = (
                    f"{len(nuevos):,} contactos en total".replace(",", ".")
                )
                _render_pagina_contactos()
            except Exception as ex:
                lbl_contactos_total.value = f"Error al leer CSV: {ex}"
                safe_update()
            finally:
                ring_contactos.visible = False
                contactos_cargando[0]  = False
                safe_update()

        threading.Thread(target=trabajador, daemon=True).start()

    def _ir_pagina(delta):
        pagina_contactos[0] += delta
        _render_pagina_contactos()

    tf_buscar_contactos = ft.TextField(
        hint_text="Buscar por nombre, cuenta o correo...",
        prefix_icon=ft.Icons.SEARCH_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
        on_change=lambda e: (filtro_actual.__setitem__(0, e.control.value),
                             _aplicar_filtro_contactos()),
    )

    btn_pag_prev = ft.IconButton(
        icon=ft.Icons.CHEVRON_LEFT_ROUNDED,
        icon_color=C_MORADO,
        on_click=lambda e: _ir_pagina(-1),
        tooltip="Página anterior",
    )
    btn_pag_next = ft.IconButton(
        icon=ft.Icons.CHEVRON_RIGHT_ROUNDED,
        icon_color=C_MORADO,
        on_click=lambda e: _ir_pagina(1),
        tooltip="Página siguiente",
    )

    vista_contactos = ft.Column(
        expand=True,
        spacing=16,
        controls=[
            ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.PEOPLE_ALT_ROUNDED, color=C_MORADO, size=22),
                    ft.Text("Contactos", size=20, weight=ft.FontWeight.BOLD,
                            color=C_TEXTO_1, font_family="Saira", expand=True),
                    ring_contactos,
                    lbl_contactos_total,
                    ft.ElevatedButton(
                        "Recargar CSV",
                        icon=ft.Icons.REFRESH_ROUNDED,
                        on_click=lambda e: cargar_contactos(forzar=True),
                        style=ft.ButtonStyle(
                            bgcolor={ft.ControlState.DEFAULT: C_MORADO,
                                     ft.ControlState.HOVERED: C_MORADO_DARK},
                            color={ft.ControlState.DEFAULT: C_BLANCO},
                            shape=ft.RoundedRectangleBorder(radius=8),
                            padding=ft.Padding(16, 12, 16, 12),
                        ),
                    ),
                ],
            ),
            lbl_csv_path,
            ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=12,
                controls=[
                    tf_buscar_contactos,
                    btn_pag_prev,
                    lbl_pagina,
                    btn_pag_next,
                ],
            ),
            ft.Container(
                expand=True,
                bgcolor=C_BLANCO,
                border_radius=ft.BorderRadius(14, 14, 14, 14),
                border=borde_all(1, C_BORDE),
                padding=ft.Padding(8, 8, 8, 8),
                content=ft.Column(
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    controls=[
                        ft.Row(
                            scroll=ft.ScrollMode.AUTO,
                            controls=[tabla_contactos_rows],
                        ),
                    ],
                ),
            ),
        ],
    )

    # ==========================================
    # PANEL RECHAZADOS — listado, copiar, depurar
    # ==========================================
    lista_rechazados      = ft.ListView(expand=True, spacing=8,
                                         padding=ft.Padding(8, 8, 8, 8))
    lbl_rechazados_total  = ft.Text("", size=12, color=C_TEXTO_3, font_family="Saira")
    lbl_rechazados_estado = ft.Text("", size=11, color=C_AZUL, font_family="Saira",
                                     italic=True)
    chk_mostrar_depurados = ft.Checkbox(label="Mostrar depurados", value=False,
                                         active_color=C_MORADO,
                                         label_style=ft.TextStyle(font_family="Saira",
                                                                   size=12,
                                                                   color=C_TEXTO_2))

    def _flash(msg, color=C_AZUL, segundos=2):
        lbl_rechazados_estado.value = msg
        lbl_rechazados_estado.color = color
        safe_update()
        def _limpiar():
            import time as _t
            _t.sleep(segundos)
            if lbl_rechazados_estado.value == msg:
                lbl_rechazados_estado.value = ""
                safe_update()
        threading.Thread(target=_limpiar, daemon=True).start()

    def refrescar_rechazados():
        rechazados   = enviar_correos.cargar_rechazados_todos()
        depurados    = enviar_correos.cargar_depurados()
        mostrar_dep  = chk_mostrar_depurados.value

        # Dedupe defensivo por email (por si el JSON trae duplicados de algún backfill)
        vistos = set()
        unicos = []
        for r in rechazados:
            em = (r.get("email") or "").lower().strip()
            if em and em not in vistos:
                vistos.add(em)
                unicos.append(r)
        rechazados = unicos

        nuevos_controles = []
        visibles = 0
        for item in rechazados:
            es_dep = item["email"] in depurados
            if es_dep and not mostrar_dep:
                continue
            visibles += 1

            email_txt = ft.Text(item["email"], size=14, weight=ft.FontWeight.W_600,
                                color=C_TEXTO_1, font_family="Saira", selectable=True,
                                expand=True)
            fecha_txt = ft.Container(
                bgcolor=C_FONDO,
                border_radius=ft.BorderRadius(6, 6, 6, 6),
                padding=ft.Padding(8, 2, 8, 2),
                content=ft.Text(item["fecha"], size=11, color=C_TEXTO_3,
                                font_family="Saira"),
            )

            def _copiar(e, correo=item["email"]):
                if copiar_portapapeles(correo):
                    _flash(f"Copiado: {correo}", C_EXITO)
                else:
                    _flash("No se pudo copiar al portapapeles", C_ROJO, 3)

            def _toggle_dep(e, correo=item["email"], ya=es_dep):
                if ya:
                    enviar_correos.desmarcar_depurado(correo)
                    _flash(f"{correo} restaurado", C_AZUL)
                else:
                    enviar_correos.marcar_depurado(correo)
                    _flash(f"{correo} marcado como depurado", C_EXITO)
                refrescar_rechazados()

            btn_copiar = ft.IconButton(
                icon=ft.Icons.CONTENT_COPY_ROUNDED,
                icon_color=C_MORADO,
                tooltip="Copiar al portapapeles",
                on_click=_copiar,
            )
            btn_dep = ft.OutlinedButton(
                "Restaurar" if es_dep else "Marcar depurado",
                icon=ft.Icons.UNDO_ROUNDED if es_dep else ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED,
                on_click=_toggle_dep,
                style=ft.ButtonStyle(
                    color={ft.ControlState.DEFAULT: C_AZUL if es_dep else C_EXITO},
                    side={ft.ControlState.DEFAULT:
                          ft.BorderSide(1.2, C_AZUL if es_dep else C_EXITO)},
                    shape=ft.RoundedRectangleBorder(radius=8),
                    padding=ft.Padding(12, 8, 12, 8),
                ),
            )

            badge_dep = ft.Container(
                bgcolor=C_VERDE_LIGHT,
                border_radius=ft.BorderRadius(6, 6, 6, 6),
                padding=ft.Padding(8, 2, 8, 2),
                content=ft.Text("DEPURADO", size=9, color=C_VERDE_DARK,
                                weight=ft.FontWeight.BOLD, font_family="Saira"),
                visible=es_dep,
            )

            nuevos_controles.append(
                ft.Container(
                    bgcolor=C_BLANCO,
                    border_radius=ft.BorderRadius(10, 10, 10, 10),
                    border=borde_all(1, C_BORDE),
                    padding=ft.Padding(14, 10, 14, 10),
                    content=ft.Row(
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10,
                        controls=[
                            ft.Icon(ft.Icons.MAIL_OUTLINE_ROUNDED,
                                    color=C_ROJO, size=18),
                            email_txt,
                            badge_dep,
                            fecha_txt,
                            btn_copiar,
                            btn_dep,
                        ],
                    ),
                )
            )

        if not nuevos_controles:
            nuevos_controles.append(
                ft.Container(
                    padding=ft.Padding(20, 24, 20, 24),
                    content=ft.Text(
                        "Sin rechazados visibles. "
                        + ("Probá activar 'Mostrar depurados'."
                           if rechazados else
                           "Todavía no hay rechazos registrados."),
                        size=13, color=C_TEXTO_3, italic=True,
                        font_family="Saira"),
                )
            )

        lista_rechazados.controls = nuevos_controles

        ocultos = sum(1 for r in rechazados if r["email"] in depurados) \
                  if not mostrar_dep else 0
        partes = [f"{visibles} visibles"]
        if ocultos:
            partes.append(f"{ocultos} ocultos")
        partes.append(f"{len(rechazados)} totales")
        lbl_rechazados_total.value = "  •  ".join(partes)
        safe_update()

    chk_mostrar_depurados.on_change = lambda e: refrescar_rechazados()

    vista_rechazados = ft.Column(
        expand=True,
        spacing=16,
        controls=[
            ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.REPORT_GMAILERRORRED_ROUNDED, color=C_ROJO, size=22),
                    ft.Text("Rechazados", size=20, weight=ft.FontWeight.BOLD,
                            color=C_TEXTO_1, font_family="Saira", expand=True),
                    lbl_rechazados_estado,
                    lbl_rechazados_total,
                    ft.ElevatedButton(
                        "Refrescar",
                        icon=ft.Icons.REFRESH_ROUNDED,
                        on_click=lambda e: refrescar_rechazados(),
                        style=ft.ButtonStyle(
                            bgcolor={ft.ControlState.DEFAULT: C_MORADO,
                                     ft.ControlState.HOVERED: C_MORADO_DARK},
                            color={ft.ControlState.DEFAULT: C_BLANCO},
                            shape=ft.RoundedRectangleBorder(radius=8),
                            padding=ft.Padding(16, 12, 16, 12),
                        ),
                    ),
                ],
            ),
            ft.Row(
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    chk_mostrar_depurados,
                    ft.Container(expand=True),
                    ft.Text(
                        "Tip: Marcá como depurado los que ya pasaste a tu base externa. "
                        "Quedan ocultos pero no se borran.",
                        size=11, color=C_TEXTO_3, italic=True, font_family="Saira",
                    ),
                ],
            ),
            ft.Container(
                expand=True,
                bgcolor=C_BLANCO,
                border_radius=ft.BorderRadius(14, 14, 14, 14),
                border=borde_all(1, C_BORDE),
                padding=ft.Padding(0, 0, 0, 0),
                content=lista_rechazados,
            ),
        ],
    )

    # ==========================================
    # PANEL HISTORIAL
    # ==========================================
    lista_historial_dias = ft.ListView(expand=True, spacing=8,
                                       padding=ft.Padding(0, 0, 0, 0))
    lbl_hist_fecha = ft.Text("Seleccioná un día", size=14, weight=ft.FontWeight.BOLD,
                              color=C_TEXTO_1, font_family="Saira")
    lista_hist_eventos = ft.ListView(expand=True, spacing=6,
                                     padding=ft.Padding(8, 8, 8, 8))
    lbl_hist_stats = ft.Text("", size=12, color=C_TEXTO_3, font_family="Saira")

    def cargar_dia_historial(fecha_str):
        data = enviar_correos.cargar_historial_dia(fecha_str)
        lbl_hist_fecha.value = f"Historial del {fecha_str}"
        env = data.get("enviados", 0)
        reb = data.get("rebotes", 0)
        lbl_hist_stats.value = f"Enviados: {env}  •  Rechazados: {reb}"
        lista_hist_eventos.controls.clear()
        for ev in reversed(data.get("eventos", [])):
            color, bg, icono, label = TIPOS_LOG.get(ev.get("tipo", "info"), TIPOS_LOG["info"])
            lista_hist_eventos.controls.append(
                ft.Container(
                    bgcolor=bg,
                    border_radius=ft.BorderRadius(8, 8, 8, 8),
                    padding=ft.Padding(12, 8, 12, 8),
                    border=borde_all(1, color + "30"),
                    content=ft.Row(
                        spacing=10,
                        controls=[
                            ft.Container(
                                bgcolor=color + "22",
                                border_radius=ft.BorderRadius(6, 6, 6, 6),
                                padding=ft.Padding(4, 4, 4, 4),
                                content=ft.Icon(icono, color=color, size=14),
                            ),
                            ft.Text(ev.get("hora", ""), size=11, color=C_TEXTO_3, font_family="Saira"),
                            ft.Container(
                                bgcolor=color,
                                border_radius=ft.BorderRadius(4, 4, 4, 4),
                                padding=ft.Padding(6, 2, 6, 2),
                                content=ft.Text(label, size=9, color=C_BLANCO,
                                                weight=ft.FontWeight.BOLD, font_family="Saira"),
                            ),
                            ft.Text(ev.get("mensaje", ""), size=12, color=C_TEXTO_1,
                                    expand=True, font_family="Saira"),
                        ],
                    ),
                )
            )
        safe_update()

    def refrescar_dias_historial():
        lista_historial_dias.controls.clear()
        dias = enviar_correos.listar_dias_historial()
        if not dias:
            lista_historial_dias.controls.append(
                ft.Container(
                    padding=ft.Padding(16, 16, 16, 16),
                    content=ft.Text("Sin historial todavía.", size=13,
                                    color=C_TEXTO_3, font_family="Saira", italic=True),
                )
            )
        for d in dias:
            data = enviar_correos.cargar_historial_dia(d)
            env  = data.get("enviados", 0)
            reb  = data.get("rebotes", 0)
            dd   = d

            lista_historial_dias.controls.append(
                ft.Container(
                    bgcolor=C_BLANCO,
                    border_radius=ft.BorderRadius(10, 10, 10, 10),
                    border=borde_all(1, C_BORDE),
                    padding=ft.Padding(16, 12, 16, 12),
                    on_click=lambda e, fecha=dd: cargar_dia_historial(fecha),
                    ink=True,
                    content=ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.CALENDAR_TODAY_ROUNDED, color=C_MORADO, size=16),
                            ft.Text(dd, size=13, weight=ft.FontWeight.W_600,
                                    color=C_TEXTO_1, font_family="Saira", expand=True),
                            ft.Container(
                                bgcolor=C_MORADO_LIGHT,
                                border_radius=ft.BorderRadius(6, 6, 6, 6),
                                padding=ft.Padding(8, 2, 8, 2),
                                content=ft.Text(f"{env} env.", size=11, color=C_MORADO,
                                                font_family="Saira"),
                            ),
                            ft.Container(width=6),
                            ft.Container(
                                bgcolor=C_ROJO_LIGHT,
                                border_radius=ft.BorderRadius(6, 6, 6, 6),
                                padding=ft.Padding(8, 2, 8, 2),
                                content=ft.Text(f"{reb} rech.", size=11, color=C_ROJO,
                                                font_family="Saira"),
                            ),
                        ],
                    ),
                )
            )
        safe_update()

    vista_historial = ft.Column(
        expand=True,
        spacing=16,
        controls=[
            ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.HISTORY_ROUNDED, color=C_MORADO, size=22),
                    ft.Text("Historial por día", size=20, weight=ft.FontWeight.BOLD,
                            color=C_TEXTO_1, font_family="Saira", expand=True),
                    ft.ElevatedButton(
                        "Refrescar",
                        icon=ft.Icons.REFRESH_ROUNDED,
                        on_click=lambda e: refrescar_dias_historial(),
                        style=ft.ButtonStyle(
                            bgcolor={ft.ControlState.DEFAULT: C_MORADO,
                                     ft.ControlState.HOVERED: C_MORADO_DARK},
                            color={ft.ControlState.DEFAULT: C_BLANCO},
                            shape=ft.RoundedRectangleBorder(radius=8),
                            padding=ft.Padding(16, 12, 16, 12),
                        ),
                    ),
                ],
            ),
            ft.Row(
                expand=True,
                spacing=16,
                controls=[
                    ft.Container(
                        width=240,
                        bgcolor=C_BLANCO,
                        border_radius=ft.BorderRadius(14, 14, 14, 14),
                        border=borde_all(1, C_BORDE),
                        padding=ft.Padding(12, 12, 12, 12),
                        content=ft.Column(
                            expand=True,
                            spacing=8,
                            controls=[
                                ft.Text("Días de campaña", size=12, weight=ft.FontWeight.BOLD,
                                        color=C_TEXTO_3, font_family="Saira"),
                                ft.Divider(height=1, color=C_BORDE),
                                ft.Container(expand=True, content=lista_historial_dias),
                            ],
                        ),
                    ),
                    ft.Container(
                        expand=True,
                        bgcolor=C_BLANCO,
                        border_radius=ft.BorderRadius(14, 14, 14, 14),
                        border=borde_all(1, C_BORDE),
                        padding=ft.Padding(0, 0, 0, 0),
                        content=ft.Column(
                            expand=True,
                            spacing=0,
                            controls=[
                                ft.Container(
                                    padding=ft.Padding(20, 14, 20, 14),
                                    border=ft.Border(
                                        bottom=ft.BorderSide(1, C_BORDE),
                                        top=ft.BorderSide(0, "transparent"),
                                        left=ft.BorderSide(0, "transparent"),
                                        right=ft.BorderSide(0, "transparent"),
                                    ),
                                    content=ft.Row(
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        controls=[
                                            ft.Icon(ft.Icons.EVENT_NOTE_ROUNDED,
                                                    color=C_MORADO, size=18),
                                            ft.Column(
                                                spacing=2,
                                                expand=True,
                                                controls=[lbl_hist_fecha, lbl_hist_stats],
                                            ),
                                        ],
                                    ),
                                ),
                                ft.Container(expand=True, content=lista_hist_eventos),
                            ],
                        ),
                    ),
                ],
            ),
        ],
    )

    # ==========================================
    # PANEL ESTADÍSTICAS — torta / barra del histórico
    # ==========================================
    tipo_grafico = ["torta"]

    contenedor_grafico   = ft.Container(expand=True,
                                         alignment=ft.Alignment(0, 0),
                                         padding=ft.Padding(20, 20, 20, 20))
    lbl_stats_enviados   = ft.Text("0", size=32, weight=ft.FontWeight.BOLD,
                                    color=C_VERDE, font_family="Saira")
    lbl_stats_rechazados = ft.Text("0", size=32, weight=ft.FontWeight.BOLD,
                                    color=C_ROJO, font_family="Saira")
    lbl_stats_total      = ft.Text("0", size=32, weight=ft.FontWeight.BOLD,
                                    color=C_MORADO, font_family="Saira")
    lbl_stats_efectivo   = ft.Text("0%", size=32, weight=ft.FontWeight.BOLD,
                                    color=C_TEXTO_1, font_family="Saira")
    lbl_stats_resumen    = ft.Text("", size=13, color=C_TEXTO_2, font_family="Saira",
                                    italic=True)

    def _grafico_vacio(mensaje):
        return ft.Container(
            alignment=ft.Alignment(0, 0),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
                controls=[
                    ft.Icon(ft.Icons.INSERT_CHART_OUTLINED_ROUNDED,
                            color=C_TEXTO_3, size=48),
                    ft.Text(mensaje, size=13, color=C_TEXTO_3, italic=True,
                            font_family="Saira"),
                ],
            ),
        )

    def _leyenda_item(color, label, valor):
        return ft.Row(
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Container(width=14, height=14, bgcolor=color,
                              border_radius=ft.BorderRadius(4, 4, 4, 4)),
                ft.Text(label, size=13, color=C_TEXTO_2, font_family="Saira"),
                ft.Container(expand=True),
                ft.Text(f"{valor:,}".replace(",", "."), size=14,
                        weight=ft.FontWeight.BOLD, color=C_TEXTO_1, font_family="Saira"),
            ],
        )

    def _construir_grafico_torta(env, rech):
        if env + rech == 0:
            return _grafico_vacio("Sin datos para graficar todavía.")
        total = env + rech
        pct_env  = env  / total
        pct_rech = rech / total

        # Donut: ProgressRing con verde para "éxito" y bgcolor rojo para "rechazo"
        donut = ft.Stack(
            width=240, height=240,
            controls=[
                ft.ProgressRing(
                    value=pct_env,
                    color=C_VERDE,
                    bgcolor=C_ROJO,
                    stroke_width=28,
                    width=240, height=240,
                ),
                ft.Container(
                    width=240, height=240,
                    alignment=ft.Alignment(0, 0),
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=2,
                        controls=[
                            ft.Text(f"{pct_env*100:.1f}%",
                                    size=36, weight=ft.FontWeight.BOLD,
                                    color=C_VERDE_DARK, font_family="Saira"),
                            ft.Text("entregados", size=12,
                                    color=C_TEXTO_3, font_family="Saira"),
                        ],
                    ),
                ),
            ],
        )

        return ft.Row(
            spacing=40,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                donut,
                ft.Container(
                    width=320,
                    content=ft.Column(
                        spacing=14,
                        controls=[
                            _leyenda_item(C_VERDE, f"Entregados ({pct_env*100:.1f}%)", env),
                            _leyenda_item(C_ROJO,  f"Rechazados ({pct_rech*100:.1f}%)", rech),
                            ft.Divider(height=1, color=C_BORDE),
                            _leyenda_item(C_MORADO, "Total enviados", total),
                        ],
                    ),
                ),
            ],
        )

    def _barra_vertical(valor, max_valor, color, color_dark, label, alto_max=260):
        if max_valor <= 0:
            max_valor = 1
        alto = max(2, int(valor / max_valor * alto_max))
        return ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.END,
            spacing=8,
            controls=[
                ft.Text(f"{valor:,}".replace(",", "."), size=14,
                        weight=ft.FontWeight.BOLD, color=color_dark,
                        font_family="Saira"),
                ft.Container(
                    width=90, height=alto,
                    bgcolor=color,
                    border_radius=ft.BorderRadius(8, 8, 0, 0),
                    tooltip=f"{label}: {valor}",
                ),
                ft.Container(width=90, height=2, bgcolor=C_BORDE),
                ft.Text(label, size=12, color=C_TEXTO_2,
                        weight=ft.FontWeight.W_500, font_family="Saira"),
            ],
        )

    def _construir_grafico_barra(env, rech):
        if env + rech == 0:
            return _grafico_vacio("Sin datos para graficar todavía.")
        max_v = max(env, rech, 1)
        return ft.Container(
            alignment=ft.Alignment(0, 0),
            padding=ft.Padding(20, 20, 20, 20),
            content=ft.Row(
                spacing=80,
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.END,
                controls=[
                    _barra_vertical(env,  max_v, C_VERDE, C_VERDE_DARK, "Enviados"),
                    _barra_vertical(rech, max_v, C_ROJO,  C_ROJO,        "Rechazados"),
                ],
            ),
        )

    def _construir_grafico_serie(serie):
        if not serie:
            return _grafico_vacio("Sin datos para graficar todavía.")
        items = serie[-30:]
        max_v = 1
        for d in items:
            max_v = max(max_v, int(d.get("enviados", 0) or 0),
                                int(d.get("rechazados", 0) or 0))
        alto_max = 200

        columnas = []
        for d in items:
            env  = int(d.get("enviados", 0) or 0)
            rech = int(d.get("rechazados", 0) or 0)
            h_env  = max(2, int(env  / max_v * alto_max)) if env  else 0
            h_rech = max(2, int(rech / max_v * alto_max)) if rech else 0

            columnas.append(
                ft.Container(
                    tooltip=f"{d.get('fecha','')}\nEnviados: {env}\nRechazados: {rech}",
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        alignment=ft.MainAxisAlignment.END,
                        spacing=4,
                        controls=[
                            ft.Row(
                                spacing=2,
                                vertical_alignment=ft.CrossAxisAlignment.END,
                                controls=[
                                    ft.Container(width=8, height=h_env,
                                                  bgcolor=C_VERDE,
                                                  border_radius=ft.BorderRadius(3, 3, 0, 0)),
                                    ft.Container(width=8, height=h_rech,
                                                  bgcolor=C_ROJO,
                                                  border_radius=ft.BorderRadius(3, 3, 0, 0)),
                                ],
                            ),
                            ft.Container(width=20, height=1, bgcolor=C_BORDE),
                            ft.Text(d.get("fecha", "")[-5:], size=8,
                                    color=C_TEXTO_3, font_family="Saira"),
                        ],
                    ),
                )
            )

        return ft.Column(
            spacing=12,
            controls=[
                ft.Row(
                    spacing=20,
                    controls=[
                        _leyenda_item(C_VERDE, "Enviados",   sum(int(d.get("enviados", 0) or 0)   for d in items)),
                        _leyenda_item(C_ROJO,  "Rechazados", sum(int(d.get("rechazados", 0) or 0) for d in items)),
                    ],
                ),
                ft.Container(
                    expand=True,
                    bgcolor=C_FONDO,
                    border_radius=ft.BorderRadius(8, 8, 8, 8),
                    padding=ft.Padding(16, 16, 16, 16),
                    content=ft.Row(
                        scroll=ft.ScrollMode.AUTO,
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                        controls=columnas,
                    ),
                ),
            ],
        )

    def refrescar_estadisticas():
        # Lógica correcta: los rechazados son un SUBSET de los enviados
        # (el SMTP envió pero el destino rebotó). Entonces:
        #   - total enviados = env
        #   - entregados (efectivos) = env - rech
        #   - tasa de éxito = entregados / env * 100
        stats = enviar_correos.obtener_estadisticas_globales()
        env   = stats.get("total_enviados", 0)
        rech  = stats.get("total_rechazados", 0)
        entregados = max(0, env - rech)
        lbl_stats_enviados.value   = f"{env:,}".replace(",", ".")
        lbl_stats_rechazados.value = f"{rech:,}".replace(",", ".")
        lbl_stats_total.value      = f"{entregados:,}".replace(",", ".")

        # Cuántos rechazados todavía no fueron procesados/depurados
        try:
            rech_lista     = enviar_correos.cargar_rechazados_todos()
            depurados_set  = enviar_correos.cargar_depurados()
            no_depurados   = sum(
                1 for r in rech_lista
                if (r.get("email") or "").lower() not in depurados_set
            )
        except Exception:
            no_depurados = rech

        if env > 0:
            tasa = entregados / env * 100
            lbl_stats_efectivo.value = f"{tasa:.1f}%"
            if tasa >= 50:
                lbl_stats_resumen.value = (
                    f"Campaña positiva: {tasa:.1f}% de los correos llegaron sin rebotar."
                )
                lbl_stats_resumen.color = C_VERDE_DARK
            elif rech > 0 and no_depurados == 0:
                # Hay rechazos pero ya están todos depurados / procesados
                lbl_stats_resumen.value = (
                    f"Base depurada: los {rech} rechazos ya fueron procesados. "
                    f"Tasa de entrega: {tasa:.1f}%."
                )
                lbl_stats_resumen.color = C_AZUL
            else:
                lbl_stats_resumen.value = (
                    f"Campaña con problemas: solo el {tasa:.1f}% llegó. "
                    f"Quedan {no_depurados} rechazo{'s' if no_depurados != 1 else ''} "
                    f"sin depurar."
                )
                lbl_stats_resumen.color = C_ROJO
        else:
            lbl_stats_efectivo.value = "0%"
            lbl_stats_resumen.value  = "Todavía no hay envíos registrados."
            lbl_stats_resumen.color  = C_TEXTO_3

        # Los gráficos comparan entregados (verde) vs rechazados (rojo)
        if tipo_grafico[0] == "torta":
            contenedor_grafico.content = _construir_grafico_torta(entregados, rech)
        elif tipo_grafico[0] == "barra":
            contenedor_grafico.content = _construir_grafico_barra(entregados, rech)
        else:
            contenedor_grafico.content = _construir_grafico_serie(stats.get("serie", []))
        safe_update()

    def _set_tipo_grafico(tipo):
        tipo_grafico[0] = tipo
        for k, b in btns_grafico.items():
            activo = (k == tipo)
            b.style = ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: C_MORADO if activo else C_BLANCO},
                color={ft.ControlState.DEFAULT: C_BLANCO if activo else C_MORADO},
                side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, C_MORADO)},
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.Padding(14, 10, 14, 10),
            )
        refrescar_estadisticas()

    btns_grafico = {
        "torta": ft.ElevatedButton("Torta", icon=ft.Icons.PIE_CHART_ROUNDED,
                                    on_click=lambda e: _set_tipo_grafico("torta")),
        "barra": ft.ElevatedButton("Barras", icon=ft.Icons.BAR_CHART_ROUNDED,
                                    on_click=lambda e: _set_tipo_grafico("barra")),
        "serie": ft.ElevatedButton("Por día (últ. 30)", icon=ft.Icons.SHOW_CHART_ROUNDED,
                                    on_click=lambda e: _set_tipo_grafico("serie")),
    }
    # Estilo inicial
    for k, b in btns_grafico.items():
        activo = (k == "torta")
        b.style = ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: C_MORADO if activo else C_BLANCO},
            color={ft.ControlState.DEFAULT: C_BLANCO if activo else C_MORADO},
            side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, C_MORADO)},
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(14, 10, 14, 10),
        )

    def _stat_card(titulo, lbl_valor, color, bg):
        return ft.Container(
            expand=True,
            bgcolor=C_BLANCO,
            border_radius=ft.BorderRadius(14, 14, 14, 14),
            border=borde_all(1, C_BORDE),
            padding=ft.Padding(20, 16, 20, 16),
            content=ft.Column(
                spacing=4,
                controls=[
                    ft.Text(titulo.upper(), size=10, weight=ft.FontWeight.BOLD,
                            color=C_TEXTO_3, font_family="Saira"),
                    lbl_valor,
                    ft.Container(
                        bgcolor=bg,
                        border_radius=ft.BorderRadius(20, 20, 20, 20),
                        padding=ft.Padding(8, 2, 8, 2),
                        content=ft.Text("histórico", size=10, color=color,
                                        weight=ft.FontWeight.W_500, font_family="Saira"),
                    ),
                ],
            ),
        )

    vista_estadisticas = ft.Column(
        expand=True,
        spacing=16,
        controls=[
            ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.ANALYTICS_ROUNDED, color=C_MORADO, size=22),
                    ft.Text("Estadísticas", size=20, weight=ft.FontWeight.BOLD,
                            color=C_TEXTO_1, font_family="Saira", expand=True),
                    ft.ElevatedButton(
                        "Refrescar",
                        icon=ft.Icons.REFRESH_ROUNDED,
                        on_click=lambda e: refrescar_estadisticas(),
                        style=ft.ButtonStyle(
                            bgcolor={ft.ControlState.DEFAULT: C_MORADO,
                                     ft.ControlState.HOVERED: C_MORADO_DARK},
                            color={ft.ControlState.DEFAULT: C_BLANCO},
                            shape=ft.RoundedRectangleBorder(radius=8),
                            padding=ft.Padding(16, 12, 16, 12),
                        ),
                    ),
                ],
            ),
            ft.Row(spacing=16, controls=[
                _stat_card("Enviados",   lbl_stats_enviados,   C_VERDE_DARK, C_VERDE_LIGHT),
                _stat_card("Rechazados", lbl_stats_rechazados, C_ROJO,       C_ROJO_LIGHT),
                _stat_card("Entregados", lbl_stats_total,      C_MORADO,     C_MORADO_LIGHT),
                _stat_card("Tasa éxito", lbl_stats_efectivo,   C_TEXTO_2,    C_FONDO),
            ]),
            ft.Container(
                bgcolor=C_BLANCO,
                border_radius=ft.BorderRadius(14, 14, 14, 14),
                border=borde_all(1, C_BORDE),
                padding=ft.Padding(20, 16, 20, 16),
                content=ft.Column(
                    spacing=8,
                    controls=[
                        ft.Row(
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Text("Tipo de gráfico", size=12,
                                        weight=ft.FontWeight.BOLD,
                                        color=C_TEXTO_2, font_family="Saira"),
                                ft.Container(width=10),
                                btns_grafico["torta"],
                                btns_grafico["barra"],
                                btns_grafico["serie"],
                                ft.Container(expand=True),
                                lbl_stats_resumen,
                            ],
                        ),
                    ],
                ),
            ),
            ft.Container(
                expand=True,
                bgcolor=C_BLANCO,
                border_radius=ft.BorderRadius(14, 14, 14, 14),
                border=borde_all(1, C_BORDE),
                padding=ft.Padding(20, 20, 20, 20),
                content=contenedor_grafico,
            ),
        ],
    )

    # ==========================================
    # PANEL RESPUESTAS — IMAP scan + paginación + filtro asunto + redactor interno
    # ==========================================
    lista_respuestas      = ft.ListView(expand=True, spacing=8,
                                         padding=ft.Padding(8, 8, 8, 8))
    lbl_resp_total        = ft.Text("", size=12, color=C_TEXTO_3, font_family="Saira")
    lbl_resp_estado       = ft.Text("", size=11, color=C_AZUL, font_family="Saira",
                                      italic=True)
    lbl_resp_pagina       = ft.Text("", size=12, color=C_TEXTO_2, font_family="Saira")
    ring_resp             = ft.ProgressRing(color=C_MORADO, width=18, height=18,
                                             stroke_width=2.5, visible=False)
    filtro_respuestas     = ["todas"]                       # todas | respuestas | calendly
    filtro_asunto_resp    = [""]                            # texto libre
    solo_campana_resp     = [True]                          # sólo correos cuyo asunto matchee la campaña
    pagina_resp           = [0]
    TAM_PAGINA_RESP       = 15

    # Asunto base de la campaña (para detectar correos relacionados)
    _asunto_campana_lower = (enviar_correos.ASUNTO or "").lower().strip()

    def _flash_resp(msg, color=C_AZUL, segundos=2):
        lbl_resp_estado.value = msg
        lbl_resp_estado.color = color
        safe_update(lbl_resp_estado)
        def _limpiar():
            import time as _t
            _t.sleep(segundos)
            if lbl_resp_estado.value == msg:
                lbl_resp_estado.value = ""
                safe_update(lbl_resp_estado)
        threading.Thread(target=_limpiar, daemon=True).start()

    # ── Redactor interno (AlertDialog modal) ──────────────────────
    tf_redactor_to = ft.TextField(
        label="Para",
        prefix_icon=ft.Icons.MAIL_OUTLINE_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        text_style=ft.TextStyle(font_family="Saira"),
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
    )
    tf_redactor_subject = ft.TextField(
        label="Asunto",
        prefix_icon=ft.Icons.SUBJECT_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        text_style=ft.TextStyle(font_family="Saira"),
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
    )
    tf_redactor_body = ft.TextField(
        label="Mensaje",
        multiline=True,
        min_lines=10,
        max_lines=18,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        text_style=ft.TextStyle(font_family="Saira"),
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
    )
    lbl_redactor_estado = ft.Text("", size=12, font_family="Saira", italic=True)
    ring_redactor       = ft.ProgressRing(color=C_MORADO, width=16, height=16,
                                           stroke_width=2.5, visible=False)

    def _cerrar_redactor(e=None):
        try:
            page.close(dialog_redactor)
        except Exception:
            try:
                dialog_redactor.open = False
                safe_update()
            except Exception:
                pass

    def _enviar_desde_redactor(e=None):
        destino = (tf_redactor_to.value or "").strip()
        asunto  = (tf_redactor_subject.value or "").strip()
        cuerpo  = tf_redactor_body.value or ""

        if not destino:
            lbl_redactor_estado.value = "Falta el destinatario."
            lbl_redactor_estado.color = C_ROJO
            safe_update(lbl_redactor_estado)
            return
        if not asunto:
            lbl_redactor_estado.value = "Falta el asunto."
            lbl_redactor_estado.color = C_ROJO
            safe_update(lbl_redactor_estado)
            return

        ring_redactor.visible       = True
        lbl_redactor_estado.value   = "Enviando..."
        lbl_redactor_estado.color   = C_AZUL
        btn_enviar_redactor.disabled = True
        safe_update(ring_redactor, lbl_redactor_estado, btn_enviar_redactor)

        def trabajador():
            ok, mensaje = enviar_correos.enviar_respuesta(destino, asunto, cuerpo)
            ring_redactor.visible        = False
            btn_enviar_redactor.disabled = False
            lbl_redactor_estado.value    = mensaje
            lbl_redactor_estado.color    = C_EXITO if ok else C_ROJO
            safe_update(ring_redactor, lbl_redactor_estado, btn_enviar_redactor)
            if ok:
                _flash_resp(f"Respuesta enviada a {destino}", C_EXITO, 3)
                import time as _t
                _t.sleep(1.2)
                _cerrar_redactor()

        threading.Thread(target=trabajador, daemon=True).start()

    btn_enviar_redactor = ft.ElevatedButton(
        "Enviar",
        icon=ft.Icons.SEND_ROUNDED,
        on_click=_enviar_desde_redactor,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: C_MORADO,
                     ft.ControlState.HOVERED: C_MORADO_DARK},
            color={ft.ControlState.DEFAULT: C_BLANCO},
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(20, 12, 20, 12),
        ),
    )

    dialog_redactor = ft.AlertDialog(
        modal=True,
        title=ft.Row(
            spacing=8,
            controls=[
                ft.Icon(ft.Icons.EDIT_NOTE_ROUNDED, color=C_MORADO),
                ft.Text("Redactar respuesta", size=18, weight=ft.FontWeight.BOLD,
                        color=C_TEXTO_1, font_family="Saira"),
            ],
        ),
        content=ft.Container(
            width=640,
            content=ft.Column(
                tight=True,
                spacing=12,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    tf_redactor_to,
                    tf_redactor_subject,
                    tf_redactor_body,
                    ft.Row(spacing=8,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER,
                           controls=[ring_redactor, lbl_redactor_estado]),
                ],
            ),
        ),
        actions=[
            ft.TextButton("Cancelar", on_click=_cerrar_redactor,
                          style=ft.ButtonStyle(color=C_TEXTO_2)),
            btn_enviar_redactor,
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    def _abrir_redactor(destino, asunto):
        tf_redactor_to.value      = destino or ""
        asunto_limpio             = re.sub(r"^(Re:|Fwd?:)\s*", "",
                                            asunto or "", flags=re.IGNORECASE).strip()
        tf_redactor_subject.value = f"Re: {asunto_limpio}" if asunto_limpio else "Re: "
        tf_redactor_body.value    = ""
        lbl_redactor_estado.value = ""
        ring_redactor.visible     = False
        btn_enviar_redactor.disabled = False
        try:
            page.open(dialog_redactor)
        except Exception:
            page.dialog = dialog_redactor
            dialog_redactor.open = True
            safe_update()

    # ── Filtrado y paginación ─────────────────────────────────────
    def _clave_hilo(tipo, item):
        """Clave estable para agrupar mensajes del mismo hilo."""
        if tipo == "calendly":
            return f"cal::{item.get('uid','')}"
        from_email = (item.get("from") or "").lower().strip()
        sub = re.sub(r"^\s*(Re:|Fwd?:)\s*", "", item.get("subject", "") or "",
                     flags=re.IGNORECASE).strip().lower()
        return f"resp::{from_email}::{sub[:120]}"

    def _items_filtrados():
        data       = enviar_correos.cargar_respuestas()
        respuestas = data.get("respuestas", [])
        calendly   = data.get("calendly", [])

        items = []
        if filtro_respuestas[0] in ("todas", "respuestas"):
            for r in respuestas:
                items.append(("respuesta", r))
        if filtro_respuestas[0] in ("todas", "calendly"):
            for c in calendly:
                items.append(("calendly", c))

        # Solo de la campaña: el asunto debe contener parte del asunto base
        if solo_campana_resp[0] and _asunto_campana_lower:
            clave = _asunto_campana_lower[:40]
            items = [
                t for t in items
                if clave in (t[1].get("subject", "") or "").lower()
                or t[0] == "calendly"
            ]

        # Filtro por asunto libre
        q = (filtro_asunto_resp[0] or "").strip().lower()
        if q:
            items = [
                t for t in items
                if q in (t[1].get("subject", "") or "").lower()
                or q in (t[1].get("from", "")    or "").lower()
                or q in (t[1].get("invitado", "") or "").lower()
            ]

        # Agrupar por (remitente, asunto-base) para no duplicar el mismo hilo.
        # Calendly se mantiene por uid (cada reunión es independiente).
        grupos = {}   # clave -> {"tipo", "ultimo", "count", "claves_msg"}
        for tipo, item in items:
            clave = _clave_hilo(tipo, item)
            uid = item.get("uid") or item.get("message_id") or ""
            g = grupos.get(clave)
            if g is None:
                grupos[clave] = {
                    "tipo":   tipo,
                    "ultimo": item,
                    "count":  1,
                    "clave":  clave,
                    "uids":   [uid] if uid else [],
                }
            else:
                g["count"] += 1
                if uid and uid not in g["uids"]:
                    g["uids"].append(uid)
                # Quedarnos con el mensaje más reciente como "representante"
                if (item.get("date") or "") > (g["ultimo"].get("date") or ""):
                    g["ultimo"] = item

        agrupados = list(grupos.values())
        agrupados.sort(key=lambda g: g["ultimo"].get("date", ""), reverse=True)
        return agrupados, len(respuestas), len(calendly)

    def _render_respuestas():
        grupos, total_resp, total_cal = _items_filtrados()
        total_visibles = len(grupos)

        max_pag = max(0, (total_visibles - 1) // TAM_PAGINA_RESP) if total_visibles else 0
        if pagina_resp[0] > max_pag:
            pagina_resp[0] = max_pag
        if pagina_resp[0] < 0:
            pagina_resp[0] = 0
        ini = pagina_resp[0] * TAM_PAGINA_RESP
        fin = min(ini + TAM_PAGINA_RESP, total_visibles)

        vistos_set = enviar_correos.cargar_vistos()

        lista_respuestas.controls.clear()
        for grupo in grupos[ini:fin]:
            tipo  = grupo["tipo"]
            item  = grupo["ultimo"]
            count = grupo["count"]
            clave = grupo["clave"]
            uids  = grupo.get("uids", [])

            # ¿El hilo tiene mensajes nuevos sin que el usuario los abrió?
            hay_nuevos = any(u not in vistos_set for u in uids) if uids else (
                clave not in vistos_set
            )

            if tipo == "calendly":
                icono       = ft.Icons.EVENT_AVAILABLE_ROUNDED
                color       = C_VERDE_DARK
                bg          = C_VERDE_LIGHT
                etiq        = "REUNIÓN"
                principal   = item.get("invitado") or item.get("from", "")
                accion_email = item.get("invitado") or ""
                subtitulo   = item.get("subject", "(sin asunto)")
            else:
                icono       = ft.Icons.REPLY_ROUNDED
                color       = C_AZUL
                bg          = C_AZUL_LIGHT
                etiq        = "RESPUESTA"
                principal   = item.get("from", "")
                accion_email = item.get("from", "")
                subtitulo   = item.get("subject", "(sin asunto)")

            def _marcar_grupo_visto(uids_locales=tuple(uids), clave_loc=clave):
                if uids_locales:
                    enviar_correos.marcar_vistos(list(uids_locales))
                else:
                    enviar_correos.marcar_visto(clave_loc)

            def _abrir_resp(e, correo=accion_email, asunto=subtitulo,
                             marcar=_marcar_grupo_visto):
                if not correo:
                    _flash_resp("No hay correo del invitado para responder", C_NARANJA)
                    return
                marcar()
                if ir_a_vista[0]:
                    ir_a_vista[0]("hilo")
                cargar_hilo(correo, asunto)

            def _copiar_resp(e, correo=accion_email):
                if not correo:
                    _flash_resp("Sin correo para copiar", C_NARANJA)
                    return
                if copiar_portapapeles(correo):
                    _flash_resp(f"Copiado: {correo}", C_EXITO)
                else:
                    _flash_resp("No se pudo copiar al portapapeles", C_ROJO, 3)

            def _abrir_mailto_externo(e, correo=accion_email, asunto=subtitulo):
                if not correo:
                    _flash_resp("Sin correo del invitado para abrir mailto", C_NARANJA)
                    return
                asunto_q = re.sub(r"^(Re:|Fwd?:)\s*", "",
                                   asunto or "", flags=re.IGNORECASE)
                url = f"mailto:{correo}?subject=Re:%20{asunto_q.replace(' ', '%20')}"
                page.launch_url(url)

            # Badge "+N" si el hilo tiene varios mensajes
            badge_count = []
            if count > 1:
                badge_count.append(
                    ft.Container(
                        bgcolor=C_MORADO_LIGHT,
                        border_radius=ft.BorderRadius(10, 10, 10, 10),
                        padding=ft.Padding(8, 1, 8, 1),
                        content=ft.Text(f"+{count - 1}",
                                         size=10, color=C_MORADO,
                                         weight=ft.FontWeight.BOLD,
                                         font_family="Saira"),
                        tooltip=f"{count} mensajes en este hilo",
                    )
                )

            # Dot verde "nueva" si hay mensajes no vistos
            dot_nueva = []
            if hay_nuevos:
                dot_nueva.append(
                    ft.Container(
                        width=10, height=10,
                        bgcolor=C_EXITO,
                        border_radius=ft.BorderRadius(5, 5, 5, 5),
                        tooltip="Nueva respuesta",
                    )
                )

            lista_respuestas.controls.append(
                ft.Container(
                    bgcolor=C_BLANCO,
                    border_radius=ft.BorderRadius(10, 10, 10, 10),
                    border=borde_all(2 if hay_nuevos else 1,
                                      C_EXITO if hay_nuevos else C_BORDE),
                    padding=ft.Padding(14, 10, 14, 10),
                    content=ft.Row(
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=12,
                        controls=[
                            *dot_nueva,
                            ft.Container(
                                bgcolor=bg,
                                border_radius=ft.BorderRadius(8, 8, 8, 8),
                                padding=ft.Padding(8, 6, 8, 6),
                                content=ft.Icon(icono, color=color, size=18),
                            ),
                            ft.Column(
                                spacing=2,
                                expand=True,
                                controls=[
                                    ft.Row(
                                        spacing=8,
                                        controls=[
                                            ft.Container(
                                                bgcolor=color,
                                                border_radius=ft.BorderRadius(4, 4, 4, 4),
                                                padding=ft.Padding(6, 1, 6, 1),
                                                content=ft.Text(etiq, size=9,
                                                                color=C_BLANCO,
                                                                weight=ft.FontWeight.BOLD,
                                                                font_family="Saira"),
                                            ),
                                            ft.Text(principal, size=13,
                                                    weight=ft.FontWeight.W_600,
                                                    color=C_TEXTO_1,
                                                    font_family="Saira",
                                                    selectable=True),
                                            *badge_count,
                                        ],
                                    ),
                                    ft.Text(subtitulo, size=12, color=C_TEXTO_2,
                                            font_family="Saira", max_lines=1,
                                            overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Text(item.get("date", ""), size=10,
                                            color=C_TEXTO_3, font_family="Saira"),
                                ],
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CONTENT_COPY_ROUNDED,
                                icon_color=C_MORADO,
                                tooltip="Copiar correo",
                                on_click=_copiar_resp,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.OPEN_IN_NEW_ROUNDED,
                                icon_color=C_TEXTO_3,
                                tooltip="Abrir en cliente externo (mailto)",
                                on_click=_abrir_mailto_externo,
                            ),
                            ft.ElevatedButton(
                                "Responder",
                                icon=ft.Icons.SEND_ROUNDED,
                                on_click=_abrir_resp,
                                style=ft.ButtonStyle(
                                    bgcolor={ft.ControlState.DEFAULT: C_MORADO,
                                             ft.ControlState.HOVERED: C_MORADO_DARK},
                                    color={ft.ControlState.DEFAULT: C_BLANCO},
                                    shape=ft.RoundedRectangleBorder(radius=8),
                                    padding=ft.Padding(14, 10, 14, 10),
                                ),
                            ),
                        ],
                    ),
                )
            )

        if not lista_respuestas.controls:
            mensaje = "Sin respuestas detectadas todavía. Apretá 'Escanear bandeja'."
            if total_resp + total_cal > 0:
                mensaje = "Ningún correo coincide con el filtro actual."
            lista_respuestas.controls.append(
                ft.Container(
                    padding=ft.Padding(20, 24, 20, 24),
                    content=ft.Text(mensaje, size=13, color=C_TEXTO_3,
                                    italic=True, font_family="Saira"),
                )
            )

        lbl_resp_total.value = (
            f"{total_resp} respuestas  •  {total_cal} reuniones  •  "
            f"{total_visibles} hilos"
        )
        if total_visibles == 0:
            lbl_resp_pagina.value = ""
        else:
            lbl_resp_pagina.value = (
                f"Mostrando {ini + 1}–{fin} de {total_visibles}  •  "
                f"Página {pagina_resp[0] + 1} / {max_pag + 1}"
            )
        safe_update()

    def _ir_pagina_resp(delta):
        pagina_resp[0] += delta
        _render_respuestas()

    def escanear_respuestas():
        if ring_resp.visible:
            return
        cfg = enviar_correos.cargar_config()
        if not cfg.get("correo") or not cfg.get("password"):
            _flash_resp("Configurá la cuenta antes de escanear.", C_ROJO, 3)
            return
        ring_resp.visible = True
        safe_update(ring_resp)
        _flash_resp("Escaneando bandeja por IMAP...", C_AZUL, 60)

        def trabajador():
            try:
                enviar_correos.detectar_respuestas_y_calendly(dias=30)
                _flash_resp("Escaneo completo.", C_EXITO, 2)
            except Exception as ex:
                _flash_resp(f"Error escaneando: {ex}", C_ROJO, 4)
            finally:
                ring_resp.visible = False
                safe_update(ring_resp)
                _render_respuestas()

        threading.Thread(target=trabajador, daemon=True).start()

    def _set_filtro_respuestas(valor):
        filtro_respuestas[0] = valor
        pagina_resp[0]       = 0
        for k, b in btns_filtro_resp.items():
            activo = (k == valor)
            b.style = ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: C_MORADO if activo else C_BLANCO},
                color={ft.ControlState.DEFAULT: C_BLANCO if activo else C_MORADO},
                side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, C_MORADO)},
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.Padding(12, 8, 12, 8),
            )
        _render_respuestas()

    btns_filtro_resp = {
        "todas":      ft.ElevatedButton("Todas",
                                         on_click=lambda e: _set_filtro_respuestas("todas")),
        "respuestas": ft.ElevatedButton("Respuestas", icon=ft.Icons.REPLY_ROUNDED,
                                         on_click=lambda e: _set_filtro_respuestas("respuestas")),
        "calendly":   ft.ElevatedButton("Reuniones", icon=ft.Icons.EVENT_AVAILABLE_ROUNDED,
                                         on_click=lambda e: _set_filtro_respuestas("calendly")),
    }
    for k, b in btns_filtro_resp.items():
        activo = (k == "todas")
        b.style = ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: C_MORADO if activo else C_BLANCO},
            color={ft.ControlState.DEFAULT: C_BLANCO if activo else C_MORADO},
            side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, C_MORADO)},
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(12, 8, 12, 8),
        )

    tf_buscar_asunto = ft.TextField(
        hint_text="Filtrar por asunto, remitente o invitado...",
        prefix_icon=ft.Icons.SEARCH_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
        on_change=lambda e: (filtro_asunto_resp.__setitem__(0, e.control.value),
                             pagina_resp.__setitem__(0, 0),
                             _render_respuestas()),
    )

    chk_solo_campana = ft.Checkbox(
        label="Solo correos de esta campaña",
        value=True,
        active_color=C_MORADO,
        label_style=ft.TextStyle(font_family="Saira", size=12, color=C_TEXTO_2),
        on_change=lambda e: (solo_campana_resp.__setitem__(0, bool(e.control.value)),
                             pagina_resp.__setitem__(0, 0),
                             _render_respuestas()),
    )

    btn_resp_prev = ft.IconButton(
        icon=ft.Icons.CHEVRON_LEFT_ROUNDED,
        icon_color=C_MORADO,
        on_click=lambda e: _ir_pagina_resp(-1),
        tooltip="Página anterior",
    )
    btn_resp_next = ft.IconButton(
        icon=ft.Icons.CHEVRON_RIGHT_ROUNDED,
        icon_color=C_MORADO,
        on_click=lambda e: _ir_pagina_resp(1),
        tooltip="Página siguiente",
    )

    vista_respuestas = ft.Column(
        expand=True,
        spacing=14,
        controls=[
            ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.MARK_EMAIL_READ_ROUNDED, color=C_MORADO, size=22),
                    ft.Text("Respuestas y reuniones", size=20, weight=ft.FontWeight.BOLD,
                            color=C_TEXTO_1, font_family="Saira", expand=True),
                    ring_resp,
                    lbl_resp_estado,
                    lbl_resp_total,
                    ft.ElevatedButton(
                        "Escanear bandeja",
                        icon=ft.Icons.INBOX_ROUNDED,
                        on_click=lambda e: escanear_respuestas(),
                        style=ft.ButtonStyle(
                            bgcolor={ft.ControlState.DEFAULT: C_MORADO,
                                     ft.ControlState.HOVERED: C_MORADO_DARK},
                            color={ft.ControlState.DEFAULT: C_BLANCO},
                            shape=ft.RoundedRectangleBorder(radius=8),
                            padding=ft.Padding(16, 12, 16, 12),
                        ),
                    ),
                ],
            ),
            ft.Row(
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    btns_filtro_resp["todas"],
                    btns_filtro_resp["respuestas"],
                    btns_filtro_resp["calendly"],
                    ft.Container(width=10),
                    chk_solo_campana,
                ],
            ),
            ft.Row(
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    tf_buscar_asunto,
                    btn_resp_prev,
                    lbl_resp_pagina,
                    btn_resp_next,
                ],
            ),
            ft.Container(
                expand=True,
                bgcolor=C_BLANCO,
                border_radius=ft.BorderRadius(14, 14, 14, 14),
                border=borde_all(1, C_BORDE),
                padding=ft.Padding(0, 0, 0, 0),
                content=lista_respuestas,
            ),
        ],
    )

    # ==========================================
    # PANEL HILO — cadena completa de un correo + responder en línea
    # ==========================================
    hilo_email_actual    = [""]
    hilo_asunto_actual   = [""]
    hilo_mensajes        = [[]]   # lista de dicts cargados de IMAP
    ring_hilo            = ft.ProgressRing(color=C_MORADO, width=20, height=20,
                                            stroke_width=2.5, visible=False)
    lbl_hilo_titulo      = ft.Text("Hilo", size=18, weight=ft.FontWeight.BOLD,
                                    color=C_TEXTO_1, font_family="Saira")
    lbl_hilo_estado      = ft.Text("", size=11, color=C_AZUL, font_family="Saira",
                                    italic=True)
    lista_mensajes_hilo  = ft.ListView(expand=True, spacing=12,
                                        padding=ft.Padding(16, 16, 16, 16),
                                        auto_scroll=False)

    tf_hilo_respuesta = ft.TextField(
        label="Tu respuesta",
        hint_text="Escribí tu mensaje y apretá Enviar...",
        multiline=True,
        min_lines=4,
        max_lines=10,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        text_style=ft.TextStyle(font_family="Saira"),
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        expand=True,
    )

    def _flash_hilo(msg, color=C_AZUL, segundos=2):
        lbl_hilo_estado.value = msg
        lbl_hilo_estado.color = color
        safe_update(lbl_hilo_estado)
        def _limpiar():
            import time as _t
            _t.sleep(segundos)
            if lbl_hilo_estado.value == msg:
                lbl_hilo_estado.value = ""
                safe_update(lbl_hilo_estado)
        threading.Thread(target=_limpiar, daemon=True).start()

    def _render_hilo_mensajes():
        """Construye visualmente la cadena de mensajes del hilo."""
        msgs = hilo_mensajes[0]
        nuevos = []
        if not msgs:
            nuevos.append(
                ft.Container(
                    padding=ft.Padding(20, 30, 20, 30),
                    alignment=ft.Alignment(0, 0),
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                        controls=[
                            ft.Icon(ft.Icons.FORUM_ROUNDED, color=C_TEXTO_3, size=42),
                            ft.Text("Sin mensajes en este hilo todavía.", size=13,
                                    color=C_TEXTO_3, italic=True, font_family="Saira"),
                            ft.Text("Probá apretar 'Recargar hilo' o iniciar la conversación abajo.",
                                    size=11, color=C_TEXTO_3, font_family="Saira"),
                        ],
                    ),
                )
            )
        else:
            for m in msgs:
                saliente = (m.get("direccion") == "saliente")
                color    = C_MORADO if saliente else C_AZUL
                bg       = C_MORADO_LIGHT if saliente else C_AZUL_LIGHT
                etiq     = "ENVIADO" if saliente else "RECIBIDO"

                # Cuerpo: preferir markdown del HTML; fallback a texto plano
                cuerpo_raw = (m.get("body_md") or m.get("body") or "").strip()
                # Recortar quotes y bloques tipo "On ... wrote:" / "El ... escribió:"
                lineas = cuerpo_raw.split("\n")
                limpio = []
                for ln in lineas:
                    stripped = ln.lstrip()
                    if stripped.startswith(">"):
                        continue
                    if stripped.startswith("On ") and "wrote:" in stripped:
                        break
                    if stripped.startswith("El ") and "escribió:" in stripped:
                        break
                    limpio.append(ln)
                cuerpo_md = "\n".join(limpio).strip() or cuerpo_raw

                if m.get("has_html"):
                    html_crudo = m.get("body_html") or ""

                    # Render HTML como imagen renderizada por Chrome headless.
                    # `fit="contain"` + sin width fijo => llena el ancho del
                    # contenedor manteniendo aspect ratio. Así no queda
                    # centrada con bordes blancos a los lados.
                    img_render = ft.Image(
                        src="",
                        fit="contain",
                        visible=False,
                    )
                    placeholder = ft.Container(
                        height=120,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.CENTER,
                            spacing=10,
                            controls=[
                                ft.ProgressRing(color=C_MORADO,
                                                 width=18, height=18,
                                                 stroke_width=2.5),
                                ft.Text("Renderizando correo original...",
                                        size=12, color=C_TEXTO_3, italic=True,
                                        font_family="Saira"),
                            ],
                        ),
                    )
                    fallback_md = ft.Markdown(
                        cuerpo_md,
                        extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
                        selectable=True,
                        auto_follow_links=True,
                        on_tap_link=lambda e: page.launch_url(e.data),
                        visible=False,
                    )

                    # Stack: placeholder mientras renderiza, luego imagen
                    contenedor_img = ft.Container(
                        bgcolor=C_BLANCO,
                        border=borde_all(1, C_BORDE),
                        border_radius=ft.BorderRadius(8, 8, 8, 8),
                        padding=ft.Padding(0, 0, 0, 0),
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                        content=ft.Column(
                            spacing=0,
                            controls=[img_render, placeholder, fallback_md],
                        ),
                    )

                    def _renderizar_async(h=html_crudo,
                                           mid=m.get("message_id", ""),
                                           img=img_render,
                                           ph=placeholder,
                                           fb=fallback_md):
                        path = _html_a_imagen(h, mid)
                        if path:
                            img.src = path
                            img.visible = True
                            ph.visible = False
                        else:
                            # Sin Chrome / html2image: mostramos el Markdown
                            ph.visible = False
                            fb.visible = True
                        safe_update(img, ph, fb)

                    threading.Thread(target=_renderizar_async, daemon=True).start()
                    contenido_cuerpo = contenedor_img
                else:
                    contenido_cuerpo = ft.Text(
                        cuerpo_md, size=13, color=C_TEXTO_1,
                        font_family="Saira", selectable=True,
                    )

                burbuja = ft.Container(
                    bgcolor=bg,
                    border=borde_all(1, color + "40"),
                    border_radius=ft.BorderRadius(12, 12, 12, 12),
                    padding=ft.Padding(14, 12, 14, 12),
                    content=ft.Column(
                        spacing=6,
                        controls=[
                            ft.Row(
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Container(
                                        bgcolor=color,
                                        border_radius=ft.BorderRadius(4, 4, 4, 4),
                                        padding=ft.Padding(6, 1, 6, 1),
                                        content=ft.Text(etiq, size=9, color=C_BLANCO,
                                                        weight=ft.FontWeight.BOLD,
                                                        font_family="Saira"),
                                    ),
                                    ft.Text(m.get("from", ""), size=12,
                                            weight=ft.FontWeight.W_600,
                                            color=C_TEXTO_1, font_family="Saira",
                                            selectable=True, expand=True),
                                    ft.Text(m.get("date", ""), size=10,
                                            color=C_TEXTO_3, font_family="Saira"),
                                ],
                            ),
                            ft.Text(m.get("subject", ""), size=11, color=C_TEXTO_2,
                                    italic=True, font_family="Saira"),
                            ft.Divider(height=1, color=color + "30"),
                            contenido_cuerpo,
                        ],
                    ),
                )

                fila = ft.Row(
                    alignment=ft.MainAxisAlignment.END if saliente
                              else ft.MainAxisAlignment.START,
                    controls=[
                        ft.Container(width=80) if saliente else ft.Container(),
                        ft.Container(content=burbuja, expand=True),
                        ft.Container(width=80) if not saliente else ft.Container(),
                    ],
                )
                nuevos.append(fila)

        lista_mensajes_hilo.controls = nuevos
        safe_update()

    def cargar_hilo(email_dest, asunto):
        hilo_email_actual[0]  = email_dest or ""
        hilo_asunto_actual[0] = asunto or ""
        lbl_hilo_titulo.value = f"Hilo con {email_dest}" if email_dest else "Hilo"
        ring_hilo.visible     = True
        hilo_mensajes[0]      = []
        _render_hilo_mensajes()
        _flash_hilo("Trayendo conversación por IMAP...", C_AZUL, 60)

        def trabajador():
            try:
                msgs = enviar_correos.obtener_hilo(
                    email_dest, asunto=asunto, dias=180,
                )
                hilo_mensajes[0] = msgs
                if msgs:
                    _flash_hilo(f"{len(msgs)} mensajes en el hilo.", C_EXITO, 2)
                else:
                    msg_log = (
                        f"Sin mensajes con {email_dest} en los últimos 180 días. "
                        f"Verificá credenciales IMAP o probá con 'Recargar hilo'."
                    )
                    _flash_hilo(msg_log, C_NARANJA, 8)
                    agregar_log("warning",
                                f"Hilo vacío para {email_dest} (asunto: {asunto[:50]}...)")
            except Exception as ex:
                err_str = f"Error al traer el hilo: {ex}"
                _flash_hilo(err_str, C_ROJO, 10)
                agregar_log("error", err_str)
            finally:
                ring_hilo.visible = False
                _render_hilo_mensajes()

        threading.Thread(target=trabajador, daemon=True).start()

    def _enviar_respuesta_hilo(e=None):
        cuerpo = tf_hilo_respuesta.value or ""
        if not cuerpo.strip():
            _flash_hilo("Escribí algo antes de enviar.", C_NARANJA, 3)
            return
        destino = hilo_email_actual[0]
        if not destino:
            _flash_hilo("No hay destinatario en este hilo.", C_ROJO, 3)
            return

        # Asunto: Re: del original sin acumular Re:Re:Re:
        asunto_base = hilo_asunto_actual[0] or ""
        asunto_limpio = re.sub(r"^(Re:|Fwd?:)\s*", "", asunto_base,
                                flags=re.IGNORECASE).strip()
        asunto = f"Re: {asunto_limpio}" if asunto_limpio else "Re:"

        # Threading headers: usar el último mensaje del hilo
        in_reply_to = ""
        references  = ""
        cc_lista    = []
        if hilo_mensajes[0]:
            ultimo = hilo_mensajes[0][-1]
            in_reply_to = ultimo.get("message_id", "")
            ref_acum    = ultimo.get("references", "")
            references  = (ref_acum + " " + in_reply_to).strip() if ref_acum else in_reply_to

            # "Responder a todos": tomamos el último mensaje recibido
            # (entrante) y juntamos To + Cc, excluyendo nuestro propio
            # correo y el destinatario principal.
            ultimo_entrante = next(
                (m for m in reversed(hilo_mensajes[0])
                 if m.get("direccion") == "entrante"),
                None,
            )
            base = ultimo_entrante or ultimo
            mi_correo = (enviar_correos.MI_CORREO() or "").lower()
            destino_low = destino.lower()
            todos_emails = re.findall(
                r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
                f"{base.get('to','')} {base.get('cc','')}",
            )
            for em in todos_emails:
                em_low = em.lower()
                if em_low == mi_correo or em_low == destino_low:
                    continue
                if em_low in [c.lower() for c in cc_lista]:
                    continue
                cc_lista.append(em)

        cc_str = ", ".join(cc_lista) if cc_lista else None

        btn_enviar_hilo.disabled = True
        ring_hilo.visible        = True
        if cc_str:
            _flash_hilo(f"Enviando a {destino} + CC: {cc_str}", C_AZUL, 60)
        else:
            _flash_hilo("Enviando respuesta...", C_AZUL, 60)
        safe_update(btn_enviar_hilo, ring_hilo)

        def trabajador():
            ok, mensaje = enviar_correos.enviar_respuesta(
                destino, asunto, cuerpo,
                in_reply_to=in_reply_to or None,
                references=references or None,
                cc=cc_str,
            )
            ring_hilo.visible        = False
            btn_enviar_hilo.disabled = False
            safe_update(btn_enviar_hilo, ring_hilo)
            if ok:
                _flash_hilo("Respuesta enviada. Recargando hilo...", C_EXITO, 3)
                tf_hilo_respuesta.value = ""
                safe_update(tf_hilo_respuesta)
                import time as _t
                _t.sleep(1.0)
                cargar_hilo(destino, asunto_base)
            else:
                _flash_hilo(f"Falló: {mensaje}", C_ROJO, 5)

        threading.Thread(target=trabajador, daemon=True).start()

    def _volver_a_respuestas(e=None):
        if ir_a_vista[0]:
            ir_a_vista[0]("respuestas")

    btn_enviar_hilo = ft.ElevatedButton(
        "Enviar respuesta",
        icon=ft.Icons.SEND_ROUNDED,
        on_click=_enviar_respuesta_hilo,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: C_MORADO,
                     ft.ControlState.HOVERED: C_MORADO_DARK},
            color={ft.ControlState.DEFAULT: C_BLANCO},
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(20, 14, 20, 14),
        ),
    )

    btn_recargar_hilo = ft.OutlinedButton(
        "Recargar hilo",
        icon=ft.Icons.REFRESH_ROUNDED,
        on_click=lambda e: cargar_hilo(hilo_email_actual[0], hilo_asunto_actual[0]),
        style=ft.ButtonStyle(
            color={ft.ControlState.DEFAULT: C_MORADO},
            side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, C_MORADO)},
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(14, 10, 14, 10),
        ),
    )

    btn_volver_hilo = ft.TextButton(
        content=ft.Row(
            spacing=4,
            controls=[
                ft.Icon(ft.Icons.ARROW_BACK_ROUNDED, color=C_MORADO, size=18),
                ft.Text("Volver a Respuestas", size=13, color=C_MORADO,
                        weight=ft.FontWeight.W_500, font_family="Saira"),
            ],
        ),
        on_click=_volver_a_respuestas,
    )

    vista_hilo = ft.Column(
        expand=True,
        spacing=12,
        controls=[
            ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    btn_volver_hilo,
                    ft.Container(width=10),
                    ft.Icon(ft.Icons.FORUM_ROUNDED, color=C_MORADO, size=22),
                    ft.Column(
                        spacing=2,
                        expand=True,
                        controls=[
                            lbl_hilo_titulo,
                            ft.Row(spacing=8,
                                   controls=[ring_hilo, lbl_hilo_estado]),
                        ],
                    ),
                    btn_recargar_hilo,
                ],
            ),
            ft.Container(
                expand=True,
                bgcolor=C_FONDO,
                border_radius=ft.BorderRadius(14, 14, 14, 14),
                border=borde_all(1, C_BORDE),
                content=lista_mensajes_hilo,
            ),
            ft.Container(
                bgcolor=C_BLANCO,
                border_radius=ft.BorderRadius(14, 14, 14, 14),
                border=borde_all(1, C_BORDE),
                padding=ft.Padding(16, 14, 16, 14),
                content=ft.Column(
                    spacing=10,
                    controls=[
                        tf_hilo_respuesta,
                        ft.Row(
                            controls=[
                                ft.Text(
                                    "Se envía manteniendo el hilo (In-Reply-To/References).",
                                    size=11, color=C_TEXTO_3, italic=True,
                                    font_family="Saira", expand=True,
                                ),
                                btn_enviar_hilo,
                            ],
                        ),
                    ],
                ),
            ),
        ],
    )

    # ==========================================
    # PANEL CONFIGURACIÓN
    # ==========================================
    cfg_actual = enviar_correos.cargar_config()

    tf_correo   = ft.TextField(
        label="Correo electrónico",
        value=cfg_actual.get("correo", ""),
        hint_text="ejemplo@gmail.com",
        prefix_icon=ft.Icons.EMAIL_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
    )
    tf_password = ft.TextField(
        label="Contraseña de aplicación",
        value=cfg_actual.get("password", ""),
        hint_text="xxxx xxxx xxxx xxxx",
        password=True,
        can_reveal_password=True,
        prefix_icon=ft.Icons.LOCK_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
    )
    tf_limite = ft.TextField(
        label="Límite diario de envíos",
        value=str(cfg_actual.get("limite_diario", 250)),
        hint_text="250",
        prefix_icon=ft.Icons.SPEED_ROUNDED,
        keyboard_type=ft.KeyboardType.NUMBER,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
    )
    tf_smtp_host = ft.TextField(
        label="Servidor SMTP",
        value=cfg_actual.get("smtp_host", "smtp.gmail.com"),
        prefix_icon=ft.Icons.DNS_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
    )
    tf_smtp_port = ft.TextField(
        label="Puerto SMTP",
        value=str(cfg_actual.get("smtp_port", 587)),
        prefix_icon=ft.Icons.SETTINGS_ETHERNET_ROUNDED,
        keyboard_type=ft.KeyboardType.NUMBER,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        width=160,
    )
    tf_imap_host = ft.TextField(
        label="Servidor IMAP",
        value=cfg_actual.get("imap_host", "imap.gmail.com"),
        prefix_icon=ft.Icons.MOVE_TO_INBOX_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
    )
    tf_firma = ft.TextField(
        label="Firma para respuestas",
        value=cfg_actual.get("firma", ""),
        hint_text=("Ej:\nBrian Sierra\nIntelliHelp\n+54 11 7700-6868\n"
                   "soporte@intellihelp.tech"),
        multiline=True,
        min_lines=4,
        max_lines=10,
        prefix_icon=ft.Icons.DRAW_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
    )

    # ── Firma con imagen ─────────────────────────────────────────
    firma_tipo_actual   = [cfg_actual.get("firma_tipo", "texto")]
    firma_imagen_actual = [cfg_actual.get("firma_imagen", "")]

    img_firma_preview = ft.Image(
        src=firma_imagen_actual[0] if (firma_imagen_actual[0]
                                        and os.path.exists(firma_imagen_actual[0]))
                                    else "",
        fit="contain",
        width=420,
        visible=bool(firma_imagen_actual[0]
                     and os.path.exists(firma_imagen_actual[0])),
    )
    lbl_firma_imagen_path = ft.Text(
        firma_imagen_actual[0] or "(sin imagen seleccionada)",
        size=11, color=C_TEXTO_3, italic=True, font_family="Saira",
    )

    def _rescalar_firma_imagen(path, max_width=600):
        """Si la imagen es más ancha que max_width, la guarda rescalada al
        lado del archivo original. Devuelve el path final a usar."""
        try:
            from PIL import Image as _PILImg
            img = _PILImg.open(path)
            if img.width > max_width:
                ratio = max_width / float(img.width)
                new_h = max(1, int(img.height * ratio))
                resized = img.resize((max_width, new_h), _PILImg.LANCZOS)
                base, ext = os.path.splitext(path)
                nuevo = base + "_pulsemail_firma" + (ext or ".png")
                resized.save(nuevo)
                return nuevo
        except Exception:
            pass
        return path

    def _on_firma_imagen_path(original):
        """Aplica la imagen seleccionada (path absoluto) como firma."""
        if not original or not os.path.exists(original):
            return
        try:
            final_path = _rescalar_firma_imagen(original, 600)
        except Exception:
            final_path = original
        firma_imagen_actual[0] = final_path
        img_firma_preview.src       = final_path
        img_firma_preview.visible   = True
        lbl_firma_imagen_path.value = final_path
        # Persistir
        cfg_p = enviar_correos.cargar_config()
        cfg_p["firma_imagen"] = final_path
        cfg_p["firma_tipo"]   = "imagen"
        enviar_correos.guardar_config(cfg_p)
        firma_tipo_actual[0] = "imagen"
        _refrescar_botones_firma()
        safe_update(img_firma_preview, lbl_firma_imagen_path)

    def _abrir_dialogo_firma_imagen(e=None):
        """Abre un diálogo nativo de Windows con tkinter para elegir imagen.
        En Flet 0.84 desktop ft.FilePicker no está soportado todavía."""
        def _picker():
            try:
                import tkinter as _tk
                from tkinter import filedialog as _fd
                root = _tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                path = _fd.askopenfilename(
                    parent=root,
                    title="Seleccioná tu firma",
                    filetypes=[
                        ("Imágenes", "*.png *.jpg *.jpeg *.gif *.webp *.bmp"),
                        ("Todos los archivos", "*.*"),
                    ],
                )
                root.destroy()
                if path:
                    _on_firma_imagen_path(path)
            except Exception as ex:
                try:
                    agregar_log("error",
                                f"No se pudo abrir el selector de archivos: {ex}")
                except Exception:
                    pass
        # Tkinter en thread separado para no bloquear el event loop de Flet
        threading.Thread(target=_picker, daemon=True).start()

    def _quitar_firma_imagen(e=None):
        firma_imagen_actual[0] = ""
        img_firma_preview.src = ""
        img_firma_preview.visible = False
        lbl_firma_imagen_path.value = "(sin imagen seleccionada)"
        cfg_p = enviar_correos.cargar_config()
        cfg_p["firma_imagen"] = ""
        cfg_p["firma_tipo"]   = "texto"
        enviar_correos.guardar_config(cfg_p)
        firma_tipo_actual[0] = "texto"
        _refrescar_botones_firma()
        safe_update(img_firma_preview, lbl_firma_imagen_path)

    def _refrescar_botones_firma():
        for k, b in btns_firma_tipo.items():
            activo = (k == firma_tipo_actual[0])
            b.style = ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: C_MORADO if activo else C_BLANCO},
                color={ft.ControlState.DEFAULT: C_BLANCO if activo else C_MORADO},
                side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, C_MORADO)},
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.Padding(14, 8, 14, 8),
            )
        try:
            for b in btns_firma_tipo.values():
                b.update()
        except Exception:
            pass

    def _set_firma_tipo(t):
        firma_tipo_actual[0] = t
        cfg_p = enviar_correos.cargar_config()
        cfg_p["firma_tipo"] = t
        enviar_correos.guardar_config(cfg_p)
        _refrescar_botones_firma()

    btns_firma_tipo = {
        "texto":  ft.ElevatedButton("Texto", icon=ft.Icons.TEXT_FIELDS_ROUNDED,
                                    on_click=lambda e: _set_firma_tipo("texto")),
        "imagen": ft.ElevatedButton("Imagen", icon=ft.Icons.IMAGE_ROUNDED,
                                    on_click=lambda e: _set_firma_tipo("imagen")),
    }
    _refrescar_botones_firma()

    btn_subir_firma = ft.OutlinedButton(
        "Cargar imagen…",
        icon=ft.Icons.UPLOAD_FILE_ROUNDED,
        on_click=_abrir_dialogo_firma_imagen,
        style=ft.ButtonStyle(
            color={ft.ControlState.DEFAULT: C_MORADO},
            side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, C_MORADO)},
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(14, 10, 14, 10),
        ),
    )
    btn_quitar_firma = ft.TextButton(
        "Quitar imagen",
        icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
        on_click=_quitar_firma_imagen,
        style=ft.ButtonStyle(color=C_ROJO),
    )

    lbl_cfg_estado = ft.Text("", size=13, font_family="Saira")
    dot_cfg_estado = ft.Container(width=8, height=8, bgcolor=C_TEXTO_3,
                                  border_radius=ft.BorderRadius(4, 4, 4, 4))
    # Animación de carga visible mientras se valida SMTP/IMAP. Reemplaza
    # al texto de estado en la fila inferior — el indicador definitivo
    # vive en el sidebar.
    ring_cfg_verificando = ft.ProgressRing(
        color=C_MORADO, width=20, height=20, stroke_width=2.5, visible=False,
    )

    # Referencias del sidebar (se definen abajo, pero las usamos en callbacks)
    smtp_dot_sidebar   = ft.Container(width=8, height=8, bgcolor=C_TEXTO_3,
                                      border_radius=ft.BorderRadius(4, 4, 4, 4))
    smtp_label_sidebar = ft.Text("Verificando...", size=11, color=C_TEXTO_2, font_family="Saira")
    smtp_cuenta_label  = ft.Text(cfg_actual.get("correo") or "Sin cuenta", size=11,
                                  color=C_TEXTO_1, weight=ft.FontWeight.W_500, font_family="Saira")

    def _aplicar_estado_smtp(ok, msg, correo_mostrar):
        """Actualiza ambos: el panel de configuración Y el sidebar."""
        # Cachear para no re-validar al rebuildear por cambio de tema
        _SMTP_CACHE[0] = (ok, msg, correo_mostrar)
        lbl_cfg_estado.value      = msg
        lbl_cfg_estado.color      = C_EXITO if ok else C_ROJO
        dot_cfg_estado.bgcolor    = C_EXITO if ok else C_ROJO
        smtp_dot_sidebar.bgcolor  = C_EXITO if ok else C_ROJO
        smtp_label_sidebar.value  = msg
        smtp_cuenta_label.value   = correo_mostrar or "Sin cuenta"
        safe_update(lbl_cfg_estado, dot_cfg_estado, smtp_dot_sidebar,
                    smtp_label_sidebar, smtp_cuenta_label)

    def guardar_configuracion(e):
        # Merge con la config actual para no perder campos no editables
        # desde el formulario (ej: tema).
        cfg = enviar_correos.cargar_config()
        cfg.update({
            "correo":        tf_correo.value.strip(),
            "password":      tf_password.value.strip(),
            "limite_diario": int(tf_limite.value.strip() or 250),
            "smtp_host":     tf_smtp_host.value.strip(),
            "smtp_port":     int(tf_smtp_port.value.strip() or 587),
            "imap_host":     tf_imap_host.value.strip(),
            "firma":         (tf_firma.value or "").rstrip(),
        })
        enviar_correos.guardar_config(cfg)

        # Actualizar el límite en el dashboard inmediatamente
        lbl_limite.value       = str(cfg["limite_diario"])
        limite_val[0]          = cfg["limite_diario"]
        lbl_progreso_pct.value = f"{enviados_val[0]} / {cfg['limite_diario']}"
        barra_progreso.value   = min(enviados_val[0] / max(cfg["limite_diario"], 1), 1.0)

        # Sidebar muestra inmediatamente la cuenta nueva (antes de verificar)
        smtp_cuenta_label.value  = cfg["correo"] or "Sin cuenta"
        smtp_dot_sidebar.bgcolor = C_NARANJA
        smtp_label_sidebar.value = "Verificando..."
        ring_cfg_verificando.visible = True
        safe_update()

        def verificar():
            try:
                ok, msg = enviar_correos.verificar_smtp()
                _aplicar_estado_smtp(ok, msg, cfg["correo"])
            finally:
                ring_cfg_verificando.visible = False
                safe_update(ring_cfg_verificando)

        threading.Thread(target=verificar, daemon=True).start()

    def verificar_conexion(e):
        # Verifica usando los valores actuales del formulario, SIN guardar
        correo    = tf_correo.value.strip()
        password  = tf_password.value.strip()
        smtp_host = tf_smtp_host.value.strip()
        smtp_port = tf_smtp_port.value.strip() or "587"

        if not correo or not password:
            # Sin credenciales: lo mostramos en el sidebar (no en config)
            smtp_dot_sidebar.bgcolor = C_NARANJA
            smtp_label_sidebar.value = "Completá correo y contraseña"
            safe_update()
            return

        ring_cfg_verificando.visible = True
        smtp_dot_sidebar.bgcolor = C_NARANJA
        smtp_label_sidebar.value = "Verificando..."
        smtp_cuenta_label.value  = correo
        safe_update()

        def verificar():
            try:
                ok, msg = enviar_correos.verificar_smtp(
                    correo=correo, password=password,
                    smtp_host=smtp_host, smtp_port=smtp_port,
                )
                _aplicar_estado_smtp(ok, msg, correo)
            finally:
                ring_cfg_verificando.visible = False
                safe_update(ring_cfg_verificando)

        threading.Thread(target=verificar, daemon=True).start()

    # ── Selector de tema ──────────────────────────────────────────
    def _cambiar_tema(nuevo_pref):
        # Persistir preferencia
        cfg = enviar_correos.cargar_config()
        cfg["tema"] = nuevo_pref
        enviar_correos.guardar_config(cfg)

        # Recordar la vista actual para volver a ella tras el rebuild
        _VISTA_INICIAL[0] = vista_actual[0] or "dashboard"

        # Re-aplicar paleta y rebuildear la UI al instante
        modo = resolver_tema(nuevo_pref)
        aplicar_tema(modo)
        try:
            page.bgcolor = C_FONDO
            page.theme_mode = (ft.ThemeMode.DARK if modo == "oscuro"
                               else ft.ThemeMode.LIGHT)
            page.controls.clear()
            safe_update()
            # Re-llamar main para reconstruir todos los controles con la nueva paleta.
            # Los watchers daemon ya están corriendo (no se duplican gracias a _INIT_HECHO).
            main(page)
        except Exception as ex:
            agregar_log("error", f"Error al cambiar tema: {ex}")

    btns_tema = {
        "claro":   ft.ElevatedButton("Claro", icon=ft.Icons.LIGHT_MODE_ROUNDED,
                                      on_click=lambda e: _cambiar_tema("claro")),
        "oscuro":  ft.ElevatedButton("Oscuro", icon=ft.Icons.DARK_MODE_ROUNDED,
                                      on_click=lambda e: _cambiar_tema("oscuro")),
        "sistema": ft.ElevatedButton("Automático (SO)",
                                      icon=ft.Icons.AUTO_AWESOME_ROUNDED,
                                      on_click=lambda e: _cambiar_tema("sistema")),
    }
    for k, b in btns_tema.items():
        activo = (k == _pref_tema)
        b.style = ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: C_MORADO if activo else C_BLANCO},
            color={ft.ControlState.DEFAULT: C_BLANCO if activo else C_MORADO},
            side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, C_MORADO)},
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(16, 10, 16, 10),
        )

    # ── Tab "Cuenta" ──────────────────────────────────────────────
    tab_cuenta = ft.Container(
        padding=ft.Padding(0, 20, 0, 0),
        content=ft.Column(
            spacing=18,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Text(
                    "Usá una contraseña de aplicación de Google (no tu contraseña normal). "
                    "Activá la verificación en dos pasos y generala en: "
                    "Cuenta Google → Seguridad → Contraseñas de aplicaciones.",
                    size=12, color=C_TEXTO_3, font_family="Saira",
                ),
                ft.Row(spacing=12, controls=[tf_correo, tf_password]),
                ft.Row(spacing=12, controls=[tf_limite]),
            ],
        ),
    )

    # ── Tab "Firma" ──────────────────────────────────────────────
    tab_firma = ft.Container(
        padding=ft.Padding(0, 20, 0, 0),
        content=ft.Column(
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Text(
                    "Esta firma se agrega automáticamente al final de las "
                    "respuestas que envíes desde el hilo. Gmail no expone su "
                    "firma vía SMTP, así que la configurás acá.",
                    size=12, color=C_TEXTO_3, font_family="Saira",
                ),
                ft.Row(
                    spacing=10,
                    controls=[
                        ft.Text("Tipo:", size=12, color=C_TEXTO_2,
                                weight=ft.FontWeight.W_500, font_family="Saira"),
                        btns_firma_tipo["texto"],
                        btns_firma_tipo["imagen"],
                    ],
                ),
                tf_firma,
                ft.Divider(height=1, color=C_BORDE),
                ft.Text("Imagen de firma (opcional)",
                        size=12, weight=ft.FontWeight.BOLD,
                        color=C_TEXTO_2, font_family="Saira"),
                ft.Text(
                    "Si tu firma es una imagen (logo + datos), subila acá. "
                    "Se rescala a 600px de ancho y se embebe inline (CID) "
                    "en cada respuesta. Sólo se usa si elegís tipo \"Imagen\".",
                    size=11, color=C_TEXTO_3, font_family="Saira",
                ),
                ft.Row(
                    spacing=10,
                    controls=[btn_subir_firma, btn_quitar_firma,
                              lbl_firma_imagen_path],
                ),
                ft.Container(
                    bgcolor=C_FONDO,
                    border_radius=ft.BorderRadius(8, 8, 8, 8),
                    padding=ft.Padding(10, 10, 10, 10),
                    border=borde_all(1, C_BORDE),
                    content=img_firma_preview,
                ),
            ],
        ),
    )

    # ── Tab "Servidores" ──────────────────────────────────────────
    tab_servidores = ft.Container(
        padding=ft.Padding(0, 20, 0, 0),
        content=ft.Column(
            spacing=18,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Text(
                    "Servidores SMTP/IMAP para envío y lectura de respuestas. "
                    "Para Gmail dejá los valores por defecto.",
                    size=12, color=C_TEXTO_3, font_family="Saira",
                ),
                ft.Row(spacing=12, controls=[tf_smtp_host, tf_smtp_port]),
                ft.Row(spacing=12, controls=[tf_imap_host]),
            ],
        ),
    )

    # ── Tab "Apariencia" ──────────────────────────────────────────
    tab_apariencia = ft.Container(
        padding=ft.Padding(0, 20, 0, 0),
        content=ft.Column(
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Text(
                    f"Tema actual: {_tema_efectivo}  "
                    f"(preferencia guardada: {_pref_tema})",
                    size=12, color=C_TEXTO_3, font_family="Saira",
                ),
                ft.Row(
                    spacing=10,
                    controls=[btns_tema["claro"],
                              btns_tema["oscuro"],
                              btns_tema["sistema"]],
                ),
                ft.Text(
                    "El cambio se aplica al instante.",
                    size=11, color=C_TEXTO_3, italic=True,
                    font_family="Saira",
                ),
            ],
        ),
    )

    # ── Sub-pestañas custom (más confiable que ft.Tabs en Flet 0.84) ──
    cfg_tabs = [
        ("cuenta",     "Cuenta",      ft.Icons.ACCOUNT_CIRCLE_ROUNDED, tab_cuenta),
        ("firma",      "Firma",       ft.Icons.DRAW_ROUNDED,           tab_firma),
        ("servidores", "Servidores",  ft.Icons.DNS_ROUNDED,            tab_servidores),
        ("apariencia", "Apariencia",  ft.Icons.PALETTE_ROUNDED,        tab_apariencia),
    ]
    cfg_tab_actual = [_CFG_TAB_INICIAL[0]]
    cfg_tab_botones = {}
    # Inicializar el contenedor con el tab que corresponde
    _tab_inicial_content = tab_cuenta
    for _k, _, _, _content in cfg_tabs:
        if _k == _CFG_TAB_INICIAL[0]:
            _tab_inicial_content = _content
            break
    cfg_tab_contenido = ft.Container(expand=True, content=_tab_inicial_content)

    def _set_cfg_tab(key):
        cfg_tab_actual[0] = key
        _CFG_TAB_INICIAL[0] = key   # persistir entre rebuilds (cambio tema)
        for k, _, _, contenido in cfg_tabs:
            if k == key:
                cfg_tab_contenido.content = contenido
        for k, btn in cfg_tab_botones.items():
            activo = (k == key)
            btn.bgcolor = C_MORADO_LIGHT if activo else ft.Colors.TRANSPARENT
            btn.border = ft.Border(
                top=ft.BorderSide(0, "transparent"),
                left=ft.BorderSide(0, "transparent"),
                right=ft.BorderSide(0, "transparent"),
                bottom=ft.BorderSide(2.5 if activo else 0,
                                      C_MORADO if activo else "transparent"),
            )
            row = btn.content
            row.controls[0].color = C_MORADO if activo else C_TEXTO_3
            row.controls[1].color = C_MORADO if activo else C_TEXTO_2
            row.controls[1].weight = (ft.FontWeight.BOLD if activo
                                       else ft.FontWeight.W_500)
        safe_update()

    def _make_tab_btn(key, label, icono):
        cont = ft.Container(
            border_radius=ft.BorderRadius(8, 8, 0, 0),
            padding=ft.Padding(16, 12, 16, 12),
            on_click=lambda e, k=key: _set_cfg_tab(k),
            ink=True,
            content=ft.Row(
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(icono, size=16, color=C_TEXTO_3),
                    ft.Text(label, size=13, font_family="Saira",
                            color=C_TEXTO_2, weight=ft.FontWeight.W_500),
                ],
            ),
        )
        cfg_tab_botones[key] = cont
        return cont

    cfg_tabs_bar = ft.Container(
        border=ft.Border(
            top=ft.BorderSide(0, "transparent"),
            left=ft.BorderSide(0, "transparent"),
            right=ft.BorderSide(0, "transparent"),
            bottom=ft.BorderSide(1, C_BORDE),
        ),
        content=ft.Row(
            spacing=4,
            controls=[_make_tab_btn(k, lbl, ic) for k, lbl, ic, _ in cfg_tabs],
        ),
    )

    # Aplicamos el estilo del tab activo inicial (puede venir de un rebuild)
    _set_cfg_tab(_CFG_TAB_INICIAL[0])

    tabs_configuracion = ft.Column(
        expand=True,
        spacing=0,
        controls=[
            cfg_tabs_bar,
            cfg_tab_contenido,
        ],
    )

    vista_configuracion = ft.Column(
        expand=True,
        spacing=16,
        controls=[
            ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.SETTINGS_ROUNDED, color=C_MORADO, size=22),
                    ft.Text("Configuración", size=20, weight=ft.FontWeight.BOLD,
                            color=C_TEXTO_1, font_family="Saira"),
                ],
            ),
            ft.Container(
                expand=True,
                bgcolor=C_BLANCO,
                border_radius=ft.BorderRadius(14, 14, 14, 14),
                border=borde_all(1, C_BORDE),
                padding=ft.Padding(20, 8, 20, 20),
                content=tabs_configuracion,
            ),
            ft.Row(
                spacing=12,
                controls=[
                    ft.ElevatedButton(
                        "Guardar configuración",
                        icon=ft.Icons.SAVE_ROUNDED,
                        on_click=guardar_configuracion,
                        style=ft.ButtonStyle(
                            bgcolor={ft.ControlState.DEFAULT: C_MORADO,
                                     ft.ControlState.HOVERED: C_MORADO_DARK},
                            color={ft.ControlState.DEFAULT: C_BLANCO},
                            shape=ft.RoundedRectangleBorder(radius=8),
                            padding=ft.Padding(20, 14, 20, 14),
                        ),
                    ),
                    ft.OutlinedButton(
                        "Verificar conexión",
                        icon=ft.Icons.WIFI_TETHERING_ROUNDED,
                        on_click=verificar_conexion,
                        style=ft.ButtonStyle(
                            color={ft.ControlState.DEFAULT: C_MORADO},
                            side={ft.ControlState.DEFAULT: ft.BorderSide(1.5, C_MORADO)},
                            shape=ft.RoundedRectangleBorder(radius=8),
                            padding=ft.Padding(20, 14, 20, 14),
                        ),
                    ),
                    ft.Container(expand=True),
                    # Animación de carga durante verificación SMTP/IMAP.
                    # El estado final se ve en el sidebar (CUENTA ACTIVA).
                    ring_cfg_verificando,
                ],
            ),
        ],
    )

    # ==========================================
    # ÁREA DE CONTENIDO PRINCIPAL (switcher)
    # ==========================================
    contenedor_vista = ft.Container(
        expand=True,
        padding=ft.Padding(28, 28, 28, 28),
        content=vista_dashboard,
    )

    # ── Topbar ────────────────────────────────────────────────────
    lbl_topbar_titulo = ft.Text("Pulsemail", size=20,
                                weight=ft.FontWeight.BOLD, color=C_TEXTO_1,
                                font_family="Saira")

    topbar = ft.Container(
        bgcolor=C_BLANCO,
        border=ft.Border(
            bottom=ft.BorderSide(1, C_BORDE),
            top=ft.BorderSide(0, "transparent"),
            left=ft.BorderSide(0, "transparent"),
            right=ft.BorderSide(0, "transparent"),
        ),
        padding=ft.Padding(32, 14, 32, 14),
        content=ft.Row(
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Column(
                    spacing=2,
                    expand=True,
                    controls=[
                        lbl_topbar_titulo,
                        ft.Row(
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[ring_estado, texto_estado],
                        ),
                    ],
                ),
                btn_iniciar,
            ],
        ),
    )

    # ── Sidebar con navegación funcional ─────────────────────────
    nav_items_refs = {}

    def cambiar_vista(vista_key):
        for k, c in nav_items_refs.items():
            c.bgcolor = ft.Colors.TRANSPARENT
            c.content.controls[0].color = C_TEXTO_3
            c.content.controls[1].color = C_TEXTO_2
            c.content.controls[1].weight = ft.FontWeight.NORMAL
        if vista_key in nav_items_refs:
            nav_items_refs[vista_key].bgcolor = C_MORADO_LIGHT
            nav_items_refs[vista_key].content.controls[0].color = C_MORADO
            nav_items_refs[vista_key].content.controls[1].color = C_MORADO
            nav_items_refs[vista_key].content.controls[1].weight = ft.FontWeight.BOLD

        vista_actual[0] = vista_key
        if vista_key == "dashboard":
            contenedor_vista.content = vista_dashboard
            lbl_topbar_titulo.value  = "Pulsemail"
            btn_iniciar.visible      = True
        elif vista_key == "contactos":
            contenedor_vista.content = vista_contactos
            lbl_topbar_titulo.value  = "Contactos"
            btn_iniciar.visible      = False
            cargar_contactos()
        elif vista_key == "rechazados":
            contenedor_vista.content = vista_rechazados
            lbl_topbar_titulo.value  = "Rechazados"
            btn_iniciar.visible      = False
            refrescar_rechazados()
        elif vista_key == "estadisticas":
            contenedor_vista.content = vista_estadisticas
            lbl_topbar_titulo.value  = "Estadísticas"
            btn_iniciar.visible      = False
            refrescar_estadisticas()
        elif vista_key == "respuestas":
            contenedor_vista.content = vista_respuestas
            lbl_topbar_titulo.value  = "Respuestas y reuniones"
            btn_iniciar.visible      = False
            respuestas_no_vistas[0]  = 0
            _actualizar_badge_respuestas()
            _render_respuestas()
        elif vista_key == "hilo":
            contenedor_vista.content = vista_hilo
            lbl_topbar_titulo.value  = "Conversación"
            btn_iniciar.visible      = False
        elif vista_key == "historial":
            contenedor_vista.content = vista_historial
            lbl_topbar_titulo.value  = "Historial de campañas"
            btn_iniciar.visible      = False
            refrescar_dias_historial()
        elif vista_key == "configuracion":
            cfg_r = enviar_correos.cargar_config()
            tf_correo.value    = cfg_r.get("correo", "")
            tf_password.value  = cfg_r.get("password", "")
            tf_limite.value    = str(cfg_r.get("limite_diario", 250))
            tf_smtp_host.value = cfg_r.get("smtp_host", "smtp.gmail.com")
            tf_smtp_port.value = str(cfg_r.get("smtp_port", 587))
            tf_imap_host.value = cfg_r.get("imap_host", "imap.gmail.com")
            tf_firma.value     = cfg_r.get("firma", "")
            contenedor_vista.content = vista_configuracion
            lbl_topbar_titulo.value  = "Configuración"
            btn_iniciar.visible      = False
        safe_update()

    ir_a_vista[0] = cambiar_vista

    # Badge para "Respuestas" (cantidad de no leídas)
    lbl_badge_resp_text = ft.Text(
        "", size=10, color=C_BLANCO,
        weight=ft.FontWeight.BOLD, font_family="Saira",
    )
    lbl_badge_respuestas = ft.Container(
        bgcolor=C_ROJO,
        border_radius=ft.BorderRadius(10, 10, 10, 10),
        padding=ft.Padding(6, 1, 6, 1),
        content=lbl_badge_resp_text,
        visible=False,
    )

    def _actualizar_badge_respuestas():
        n = respuestas_no_vistas[0]
        if n > 0:
            lbl_badge_resp_text.value = str(n) if n <= 99 else "99+"
            lbl_badge_respuestas.visible = True
        else:
            lbl_badge_respuestas.visible = False
        safe_update(lbl_badge_resp_text, lbl_badge_respuestas)

    def nav_item(label, icono, vista_key, activo=False, badge=None):
        controles = [
            ft.Icon(icono,
                    color=C_MORADO if activo else C_TEXTO_3,
                    size=20),
            ft.Text(label,
                    color=C_MORADO if activo else C_TEXTO_2,
                    size=14,
                    weight=ft.FontWeight.BOLD if activo else ft.FontWeight.NORMAL,
                    font_family="Saira"),
        ]
        if badge is not None:
            controles.append(ft.Container(expand=True))
            controles.append(badge)

        cont = ft.Container(
            border_radius=ft.BorderRadius(10, 10, 10, 10),
            bgcolor=C_MORADO_LIGHT if activo else ft.Colors.TRANSPARENT,
            padding=ft.Padding(14, 11, 14, 11),
            on_click=lambda e, vk=vista_key: cambiar_vista(vk),
            ink=True,
            content=ft.Row(spacing=12, controls=controles),
        )
        nav_items_refs[vista_key] = cont
        return cont

    # Verificación inicial al arrancar (sólo la primera vez)
    def verificar_smtp_inicial():
        cfg_i = enviar_correos.cargar_config()
        if not cfg_i.get("correo") or not cfg_i.get("password"):
            smtp_dot_sidebar.bgcolor = C_ROJO
            smtp_label_sidebar.value = "Sin credenciales"
            smtp_cuenta_label.value  = "Sin cuenta"
            safe_update()
            return
        ok, msg = enviar_correos.verificar_smtp()
        _aplicar_estado_smtp(ok, msg, cfg_i.get("correo", ""))

    # Si hay cache (rebuild por cambio de tema), aplicarlo sin tocar la red.
    # Si no hay cache, disparar la verificación (cubre el primer arranque
    # y también el caso donde el rebuild ocurrió antes de que termine
    # la primera validación).
    if _SMTP_CACHE[0] is not None:
        ok_c, msg_c, correo_c = _SMTP_CACHE[0]
        smtp_dot_sidebar.bgcolor = C_EXITO if ok_c else C_ROJO
        smtp_label_sidebar.value = msg_c or ("GMAIL SMTP activo" if ok_c
                                              else "Sin conexión")
        smtp_cuenta_label.value  = correo_c or "Sin cuenta"
        # Forzamos un update por si Flet 0.84 no propaga al instante
        try:
            smtp_dot_sidebar.update()
            smtp_label_sidebar.update()
            smtp_cuenta_label.update()
        except Exception:
            pass
    else:
        threading.Thread(target=verificar_smtp_inicial, daemon=True).start()

    # ── Watcher de cambio de día ──────────────────────────────────
    def watcher_cambio_dia():
        import time as _time
        while True:
            _time.sleep(60)
            hoy_now = datetime.now().strftime("%Y-%m-%d")
            if hoy_now == fecha_actual[0]:
                continue
            fecha_actual[0] = hoy_now
            try:
                env_recup, _ = enviar_correos.estado_de_hoy()
                hist_recup   = enviar_correos.cargar_historial_dia(hoy_now)
                reb_recup    = int(hist_recup.get("rebotes", 0) or 0)
                lim_recup    = enviar_correos.LIMITE_DIARIO()
                actualizar_metricas(env_recup, lim_recup, reb_recup)
                agregar_log("info",
                            f"Día nuevo detectado: {hoy_now}. Contadores reiniciados.")
                if vista_actual[0] == "historial":
                    refrescar_dias_historial()
            except Exception as ex:
                agregar_log("error", f"Watcher de día falló: {ex}")

    if not _INIT_HECHO[0]:
        threading.Thread(target=watcher_cambio_dia, daemon=True).start()

    # ── Watcher del dashboard: polea estado en disco y refresca KPIs ──
    def watcher_dashboard():
        import time as _time
        ultimo = (-1, -1, -1)
        while True:
            _time.sleep(1.5)
            try:
                env_disco, _ = enviar_correos.estado_de_hoy()
                hoy_str      = datetime.now().strftime("%Y-%m-%d")
                hist         = enviar_correos.cargar_historial_dia(hoy_str)
                reb_disco    = int(hist.get("rebotes", 0) or 0)
                lim_disco    = enviar_correos.LIMITE_DIARIO()
                actual = (env_disco, reb_disco, lim_disco)
                if actual == ultimo:
                    continue
                ultimo = actual
                actualizar_metricas(env_disco, lim_disco, reb_disco)
            except Exception:
                pass

    if not _INIT_HECHO[0]:
        threading.Thread(target=watcher_dashboard, daemon=True).start()

    # ── Watcher de respuestas: polling IMAP cada 30s (rápido, dias=2) ──
    def watcher_respuestas():
        import time as _time
        _time.sleep(8)  # delay inicial para que arranque la UI tranquila
        while True:
            cfg = enviar_correos.cargar_config()
            if cfg.get("correo") and cfg.get("password"):
                try:
                    antes = enviar_correos.cargar_respuestas()
                    n_antes_resp = len(antes.get("respuestas", []))
                    n_antes_cal  = len(antes.get("calendly", []))

                    enviar_correos.detectar_respuestas_y_calendly(dias=2)

                    despues     = enviar_correos.cargar_respuestas()
                    n_desp_resp = len(despues.get("respuestas", []))
                    n_desp_cal  = len(despues.get("calendly", []))

                    nuevas_resp = max(0, n_desp_resp - n_antes_resp)
                    nuevas_cal  = max(0, n_desp_cal  - n_antes_cal)
                    total_nuevas = nuevas_resp + nuevas_cal

                    if total_nuevas > 0:
                        # Notificación del SO (toast Windows o fallback beep)
                        try:
                            if nuevas_resp > 0 and nuevas_cal > 0:
                                titulo = "Pulsemail — Bandeja"
                                cuerpo = (
                                    f"{nuevas_resp} respuesta"
                                    f"{'s' if nuevas_resp != 1 else ''} y "
                                    f"{nuevas_cal} reunión"
                                    f"{'es' if nuevas_cal != 1 else ''} de Calendly."
                                )
                            elif nuevas_resp > 0:
                                titulo = "Pulsemail — Nueva respuesta"
                                cuerpo = (
                                    f"{nuevas_resp} respuesta"
                                    f"{'s' if nuevas_resp != 1 else ''} de cliente"
                                    f"{'s' if nuevas_resp != 1 else ''}."
                                )
                            else:
                                titulo = "Pulsemail — Nueva reunión"
                                cuerpo = (
                                    f"{nuevas_cal} reunión"
                                    f"{'es' if nuevas_cal != 1 else ''} agendada"
                                    f"{'s' if nuevas_cal != 1 else ''} en Calendly."
                                )
                            notificar_sistema(titulo, cuerpo)
                        except Exception:
                            pass

                        if vista_actual[0] == "respuestas":
                            # El usuario está mirando: refrescamos la lista
                            # (el badge "nueva" sale solo gracias a registro_vistos)
                            _render_respuestas()
                        else:
                            respuestas_no_vistas[0] += total_nuevas
                            _actualizar_badge_respuestas()
                            agregar_log(
                                "info",
                                f"{total_nuevas} nueva(s) respuesta(s) detectada(s) por IMAP."
                            )
                except Exception:
                    pass
            # Polling más rápido cuando el usuario está mirando Respuestas;
            # un poco más lento si está en otra pestaña (ahorra red).
            _time.sleep(3 if vista_actual[0] == "respuestas" else 5)

    if not _INIT_HECHO[0]:
        threading.Thread(target=watcher_respuestas, daemon=True).start()
    _INIT_HECHO[0] = True

    # ── Header del sidebar: nombre del producto + logo del cliente ──
    logo_path = os.path.join(CARPETA_ACTUAL, "ITH-logo.png")
    sidebar_header = ft.Container(
        bgcolor=C_BLANCO,
        padding=ft.Padding(20, 22, 20, 22),
        border=ft.Border(
            top=ft.BorderSide(0, "transparent"),
            left=ft.BorderSide(0, "transparent"),
            right=ft.BorderSide(0, "transparent"),
            bottom=ft.BorderSide(1, C_BORDE),
        ),
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
            controls=[
                # Logo del cliente sobre fondo claro (no se confunde con el morado)
                ft.Container(
                    bgcolor=C_FONDO,
                    border_radius=ft.BorderRadius(12, 12, 12, 12),
                    padding=ft.Padding(14, 10, 14, 10),
                    content=ft.Image(
                        src="ITH-logo.png",
                        width=110,
                        height=46,
                        fit="contain",
                    ),
                ) if os.path.exists(logo_path) else ft.Container(),
                # Nombre del producto
                ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=6,
                    controls=[
                        ft.Container(
                            width=8, height=8,
                            bgcolor=C_VERDE,
                            border_radius=ft.BorderRadius(4, 4, 4, 4),
                        ),
                        ft.Text("Pulsemail", size=20,
                                weight=ft.FontWeight.BOLD,
                                color=C_MORADO, font_family="Saira"),
                    ],
                ),
                ft.Text("Outreach automation suite", size=10,
                        color=C_TEXTO_3, italic=True, font_family="Saira"),
            ],
        ),
    )

    sidebar = ft.Container(
        width=230,
        bgcolor=C_BLANCO,
        border=ft.Border(
            top=ft.BorderSide(0, "transparent"),
            bottom=ft.BorderSide(0, "transparent"),
            left=ft.BorderSide(0, "transparent"),
            right=ft.BorderSide(1, C_BORDE),
        ),
        padding=ft.Padding(0, 0, 0, 20),
        content=ft.Column(
            expand=True,
            spacing=0,
            controls=[
                sidebar_header,
                ft.Container(height=16),
                ft.Container(
                    padding=ft.Padding(14, 0, 14, 0),
                    content=ft.Column(
                        spacing=4,
                        controls=[
                            nav_item("Dashboard",      ft.Icons.DASHBOARD_ROUNDED,         "dashboard",     True),
                            nav_item("Contactos",      ft.Icons.PEOPLE_ALT_ROUNDED,        "contactos"),
                            nav_item("Rechazados",     ft.Icons.REPORT_GMAILERRORRED_ROUNDED, "rechazados"),
                            nav_item("Respuestas",     ft.Icons.MARK_EMAIL_READ_ROUNDED,   "respuestas",
                                     badge=lbl_badge_respuestas),
                            nav_item("Estadísticas",   ft.Icons.ANALYTICS_ROUNDED,         "estadisticas"),
                            nav_item("Historial",      ft.Icons.HISTORY_ROUNDED,           "historial"),
                            nav_item("Configuración",  ft.Icons.SETTINGS_ROUNDED,          "configuracion"),
                        ],
                    ),
                ),
                ft.Container(expand=True),
                ft.Container(
                    margin=ft.Margin(14, 0, 14, 0),
                    bgcolor=C_FONDO,
                    border_radius=ft.BorderRadius(12, 12, 12, 12),
                    padding=ft.Padding(14, 12, 14, 12),
                    border=borde_all(1, C_BORDE),
                    content=ft.Column(
                        spacing=4,
                        controls=[
                            ft.Text("CUENTA ACTIVA", size=10, color=C_TEXTO_3,
                                    weight=ft.FontWeight.BOLD, font_family="Saira"),
                            smtp_cuenta_label,
                            ft.Container(height=4),
                            ft.Row(
                                spacing=6,
                                controls=[smtp_dot_sidebar, smtp_label_sidebar],
                            ),
                        ],
                    ),
                ),
            ],
        ),
    )

    # ── Layout raíz ───────────────────────────────────────────────
    contenido_principal = ft.Column(
        expand=True,
        spacing=0,
        controls=[
            topbar,
            contenedor_vista,
        ],
    )

    page.add(
        ft.Row(
            expand=True,
            spacing=0,
            controls=[sidebar, contenido_principal],
        )
    )

    # Si había progreso recuperado, registrar un mensaje informativo en el log
    if _enviados_iniciales > 0:
        agregar_log(
            "info",
            f"Sesión retomada: {_enviados_iniciales} de {_limite_inicial} ya enviados hoy. "
            f"Último contacto: {_ultimo_email_inicial or 'desconocido'}."
        )

    # Re-aplicar el cache SMTP después de page.add() para garantizar que
    # los controles ya están en el árbol. Lo hacemos en VARIAS pasadas:
    #   (1) inmediato (sync, refleja en el render inicial)
    #   (2) tras delays escalonados desde threads (cubre el caso en que
    #       el primer update no propaga porque la sesión todavía no está
    #       lista para repintar)
    def _aplicar_cache_smtp_ahora():
        if _SMTP_CACHE[0] is None:
            return
        try:
            ok_c, msg_c, correo_c = _SMTP_CACHE[0]
            smtp_dot_sidebar.bgcolor = C_EXITO if ok_c else C_ROJO
            smtp_label_sidebar.value = msg_c or (
                "GMAIL SMTP activo" if ok_c else "Sin conexión"
            )
            smtp_cuenta_label.value  = correo_c or "Sin cuenta"
            try:
                smtp_dot_sidebar.update()
                smtp_label_sidebar.update()
                smtp_cuenta_label.update()
            except Exception:
                pass
            try:
                page.update()
            except Exception:
                pass
        except Exception:
            pass

    _aplicar_cache_smtp_ahora()

    def _aplicar_cache_smtp_diferido():
        import time as _t
        for delay in (0.1, 0.4, 1.0, 2.0):
            _t.sleep(delay)
            _aplicar_cache_smtp_ahora()

    if _SMTP_CACHE[0] is not None:
        threading.Thread(target=_aplicar_cache_smtp_diferido,
                         daemon=True).start()

    # Si veníamos de un rebuild (cambio de tema), restaurar la vista
    # donde estaba el usuario antes del cambio.
    _vista_destino = _VISTA_INICIAL[0]
    if _vista_destino and _vista_destino != "dashboard":
        try:
            cambiar_vista(_vista_destino)
        except Exception:
            pass
    _VISTA_INICIAL[0] = "dashboard"  # reset para próximos arranques


if __name__ == "__main__":
    ft.app(target=main, assets_dir=CARPETA_ACTUAL)
