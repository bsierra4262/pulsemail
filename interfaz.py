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

# ── AppUserModelID ──
# Sin esto, Windows trata la app como "Flet generic" y al anclarla a la
# barra de tareas, el acceso anclado apunta al runtime de Flet en vez de
# a Pulsemail. Setearlo permite anclar/agrupar correctamente con icono y
# nombre propios.
try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        u"Pulsemail.OutreachSuite.1.0"
    )
except Exception:
    pass

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


# ==========================================
# DIÁLOGO DE ARCHIVOS NATIVO (Win32)
# ==========================================
# En Flet 0.84 desktop `ft.FilePicker` no está soportado, y el patrón
# anterior (crear `tk.Tk()` dentro de un thread daemon por cada diálogo)
# es frágil en el .exe compilado:
#   - PyInstaller / `flet pack` no siempre empaqueta el runtime tcl/tk,
#     con lo cual `tk.Tk()` lanza `TclError: Can't find init.tcl` y el
#     diálogo NUNCA abre → el usuario ve "no importa ni exporta nada".
#   - Crear varias raíces Tk desde distintos hilos rompe la afinidad de
#     hilo del intérprete Tcl (el primero funciona, los siguientes cuelgan).
#
# Solución: usar el diálogo NATIVO de Windows vía comdlg32
# (GetOpenFileNameW / GetSaveFileNameW). No depende de tcl/tk, funciona
# desde cualquier hilo y va en línea con el uso de Win32 que ya hace la
# app (portapapeles). Si comdlg32 no está disponible (otro SO, dev),
# cae a tkinter como último recurso.
try:
    import ctypes as _ct_dlg
    from ctypes import wintypes as _wt_dlg

    class _OPENFILENAMEW(_ct_dlg.Structure):
        _fields_ = [
            ("lStructSize",       _wt_dlg.DWORD),
            ("hwndOwner",         _wt_dlg.HWND),
            ("hInstance",         _wt_dlg.HINSTANCE),
            ("lpstrFilter",       _wt_dlg.LPCWSTR),
            ("lpstrCustomFilter", _wt_dlg.LPWSTR),
            ("nMaxCustFilter",    _wt_dlg.DWORD),
            ("nFilterIndex",      _wt_dlg.DWORD),
            ("lpstrFile",         _wt_dlg.LPWSTR),
            ("nMaxFile",          _wt_dlg.DWORD),
            ("lpstrFileTitle",    _wt_dlg.LPWSTR),
            ("nMaxFileTitle",     _wt_dlg.DWORD),
            ("lpstrInitialDir",   _wt_dlg.LPCWSTR),
            ("lpstrTitle",        _wt_dlg.LPCWSTR),
            ("Flags",             _wt_dlg.DWORD),
            ("nFileOffset",       _wt_dlg.WORD),
            ("nFileExtension",    _wt_dlg.WORD),
            ("lpstrDefExt",       _wt_dlg.LPCWSTR),
            ("lCustData",         _wt_dlg.LPARAM),
            ("lpfnHook",          _wt_dlg.LPVOID),
            ("lpTemplateName",    _wt_dlg.LPCWSTR),
            ("pvReserved",        _wt_dlg.LPVOID),
            ("dwReserved",        _wt_dlg.DWORD),
            ("FlagsEx",           _wt_dlg.DWORD),
        ]

    _comdlg32 = _ct_dlg.windll.comdlg32
    _WIN32_DLG_OK = True
except Exception:
    _WIN32_DLG_OK = False

# Flags de OPENFILENAMEW
_OFN_OVERWRITEPROMPT = 0x00000002
_OFN_HIDEREADONLY    = 0x00000004
_OFN_NOCHANGEDIR     = 0x00000008
_OFN_PATHMUSTEXIST   = 0x00000800
_OFN_FILEMUSTEXIST   = 0x00001000
_OFN_EXPLORER        = 0x00080000


def _win32_build_filter(filtros):
    """Convierte [(etiqueta, "*.png *.jpg"), ...] al formato de comdlg32:
    pares etiqueta\\0patron\\0 ... \\0\\0. Win32 separa múltiples patrones
    con ';' (no con espacios como tkinter), así que normalizamos."""
    partes = []
    for etiqueta, patron in filtros:
        partes.append(str(etiqueta))
        partes.append(str(patron).replace(" ", ";"))
    return "\0".join(partes) + "\0\0"


def _dialogo_archivo_nativo(save, title, filtros, default_name="",
                            default_ext=""):
    """Diálogo nativo de Windows para abrir/guardar un archivo.

    `save`: True = guardar (GetSaveFileNameW), False = abrir.
    `filtros`: lista [(etiqueta, patron)] en formato tkinter
        ej [("Backup ZIP", "*.zip"), ("Todos los archivos", "*.*")].
    Devuelve la ruta absoluta elegida, o "" si el usuario canceló.

    Si comdlg32 no está disponible cae a tkinter (último recurso).
    """
    if _WIN32_DLG_OK:
        try:
            buf = _ct_dlg.create_unicode_buffer(default_name or "", 65536)
            ofn = _OPENFILENAMEW()
            ofn.lStructSize = _ct_dlg.sizeof(_OPENFILENAMEW)
            ofn.hwndOwner   = None
            ofn.lpstrFilter = _win32_build_filter(filtros)
            ofn.nFilterIndex = 1
            ofn.lpstrFile   = _ct_dlg.cast(buf, _wt_dlg.LPWSTR)
            ofn.nMaxFile    = 65536
            ext = (default_ext or "").lstrip("*").lstrip(".")
            ofn.lpstrDefExt = ext or None
            ofn.lpstrTitle  = title
            if save:
                ofn.Flags = (_OFN_EXPLORER | _OFN_OVERWRITEPROMPT
                             | _OFN_HIDEREADONLY | _OFN_NOCHANGEDIR)
                ok = _comdlg32.GetSaveFileNameW(_ct_dlg.byref(ofn))
            else:
                ofn.Flags = (_OFN_EXPLORER | _OFN_FILEMUSTEXIST
                             | _OFN_PATHMUSTEXIST | _OFN_HIDEREADONLY
                             | _OFN_NOCHANGEDIR)
                ok = _comdlg32.GetOpenFileNameW(_ct_dlg.byref(ofn))
            if not ok:
                return ""   # usuario canceló (o error → probamos fallback)
            return buf.value or ""
        except Exception:
            pass  # cae al fallback tkinter

    # ── Fallback tkinter (sólo si comdlg32 no está / falló) ──
    try:
        import tkinter as _tk
        from tkinter import filedialog as _fd
        root = _tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            if save:
                ext = (default_ext or "").lstrip("*")
                if ext and not ext.startswith("."):
                    ext = "." + ext
                ruta = _fd.asksaveasfilename(
                    parent=root, title=title, filetypes=filtros,
                    defaultextension=ext or None,
                    initialfile=default_name or None,
                )
            else:
                ruta = _fd.askopenfilename(
                    parent=root, title=title, filetypes=filtros,
                )
        finally:
            root.destroy()
        return ruta or ""
    except Exception:
        return ""


# ── Notificación del sistema operativo ──
# Intenta primero `plyer.notification` (toast nativo Windows 10/11),
# Intenta primero `plyer.notification` (toast nativo Windows 10/11),
# si no está disponible cae a un beep + flash de la ventana. La
# notificación lleva el logo de Pulsemail (Windows requiere .ico).
_NOTIF_ICON_PATH = [None]   # cache del path al .ico una vez generado

def _resolver_icono_notif():
    """Devuelve un path absoluto al ícono que Windows acepta para toasts.
    Convierte logo-app.png → logo-app.ico con PIL si hace falta."""
    if _NOTIF_ICON_PATH[0] and os.path.exists(_NOTIF_ICON_PATH[0]):
        return _NOTIF_ICON_PATH[0]
    ico_path = os.path.join(CARPETA_ASSETS, "logo-app.ico")
    if os.path.exists(ico_path):
        _NOTIF_ICON_PATH[0] = ico_path
        return ico_path
    png_path = os.path.join(CARPETA_ASSETS, "logo-app.png")
    if not os.path.exists(png_path):
        png_path = os.path.join(CARPETA_ASSETS, "ITH-logo.png")
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
            # Viewport más ancho → mejor calidad al escalar a pantallas 2K/4K
            size=(1400, 5000),
            custom_flags=[
                "--default-background-color=FFFFFF",
                "--hide-scrollbars",
                # virtual-time-budget bajo = Chrome no espera tanto a recursos
                "--virtual-time-budget=2500",
                # GPU OFF total — evita "Failed to create shared context for
                # virtualization" en PCs sin aceleración HW (VMs, Citrix,
                # equipos viejos). Forzamos software rendering vía SwiftShader
                # y aislamos el GPU process en el mismo proceso para que no
                # haga IPC fallida.
                "--disable-gpu",
                "--disable-gpu-compositing",
                "--disable-gpu-sandbox",
                "--disable-accelerated-2d-canvas",
                "--disable-accelerated-video-decode",
                "--use-gl=swiftshader",
                "--in-process-gpu",
                "--disable-dev-shm-usage",
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
    # No forzamos ancho fijo: dejamos que el contenido tome su tamaño
    # natural y luego el trim de PIL recorta el bbox exacto. Así el render
    # se adapta a cualquier correo (anchos, narrows, cortos, largos) sin
    # generar franjas blancas. El bgcolor blanco del html/body es lo que
    # permite a getbbox detectar dónde termina el contenido real.
    style_override = (
        "<style>"
        "html,body{margin:0!important;padding:0!important;"
        "background:#ffffff!important;}"
        "body{font-family:Arial,sans-serif;max-width:900px;}"
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
    #
    # En pantallas con DPI alto (2K/4K) Chrome aplica anti-aliasing y los
    # bordes del contenido tienen pixels casi-blancos (#fafafa, #f8f8f8
    # etc.) que bbox(255,255,255) no detecta. Usamos un threshold para
    # tratarlos también como "blanco" y recortar agresivamente.
    # Trim agresivo del whitespace alrededor del contenido real.
    # Estrategia:
    #   1) Cuantizamos los pixels casi-blancos (anti-aliasing, sombras
    #      muy claras tipo #fafafa) a blanco puro #ffffff.
    #   2) Restamos contra una imagen totalmente blanca → todo lo que
    #      NO es contenido queda en negro.
    #   3) PIL.getbbox() devuelve el rectángulo exacto que contiene
    #      pixels no-cero = bounding box del contenido real.
    # Esto es muchísimo más confiable que iterar pixel por pixel y
    # se adapta automáticamente a cualquier correo (corto, largo,
    # estrecho, ancho), sin importar DPI ni viewport de Chrome.
    try:
        from PIL import Image as _PIL_Image, ImageChops as _PIL_ImageChops
        img = _PIL_Image.open(path).convert("RGB")
        ancho, alto = img.size

        # Punto de quiebre: pixels con todos los canales >= 245 los
        # convertimos a blanco puro para que la diferencia los ignore.
        UMBRAL = 245
        def _quantize(c):
            return 255 if c >= UMBRAL else c
        tabla = bytes(_quantize(i) for i in range(256))
        img_q = img.point(lambda p: tabla[p])

        fondo = _PIL_Image.new("RGB", img_q.size, (255, 255, 255))
        diff  = _PIL_ImageChops.difference(img_q, fondo)
        bbox  = diff.getbbox()

        if bbox:
            l, t, r, b = bbox
            margen = 6
            l = max(0, l - margen)
            t = max(0, t - margen)
            r = min(ancho, r + margen)
            b = min(alto,  b + margen)
            cropped = img.crop((l, t, r, b))
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

# Datos del usuario (estable entre ejecuciones, incluso dentro del bundle)
CARPETA_ACTUAL = enviar_correos.CARPETA_ACTUAL
# Recursos empaquetados (logos, íconos) — en bundle: sys._MEIPASS
CARPETA_ASSETS = enviar_correos.CARPETA_ASSETS


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

# Timestamp de la última vez que el watcher detectó respuestas/calendly
# nuevos. Se usa para polling adaptativo: si hubo actividad reciente
# (< 5 min) polea más rápido; si la cuenta está quieta polea más lento.
_ULTIMA_ACTIVIDAD_RESPUESTA = [0.0]


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

    # Ícono de la app: logo-app.png/ico. Lo aplicamos por TRES vías:
    #  (1) page.window.icon (Flet)
    #  (2) page.window_icon (versiones viejas de Flet)
    #  (3) Win32 SendMessage WM_SETICON sobre las ventanas del proceso
    #      → ESTE es el que hace que aparezca el logo en la barra de
    #      tareas y la barra de título incluso al ejecutar `py interfaz.py`
    _logo_app = os.path.join(CARPETA_ASSETS, "logo-app.png")
    _logo_ico = os.path.join(CARPETA_ASSETS, "logo-app.ico")
    if not os.path.exists(_logo_app):
        _logo_app = os.path.join(CARPETA_ASSETS, "ITH-logo.png")

    # Generar el .ico en runtime si no existe (lo necesita Win32 LoadImage)
    if (not os.path.exists(_logo_ico)) and os.path.exists(_logo_app):
        try:
            from PIL import Image as _PILImg
            _PILImg.open(_logo_app).convert("RGBA").save(
                _logo_ico,
                sizes=[(16, 16), (32, 32), (48, 48),
                       (64, 64), (128, 128), (256, 256)],
            )
        except Exception:
            pass

    if os.path.exists(_logo_app):
        for setter in (
            lambda v: setattr(page.window, "icon", v),
            lambda v: setattr(page, "window_icon", v),
        ):
            try:
                setter(_logo_ico if os.path.exists(_logo_ico) else _logo_app)
            except Exception:
                pass

    # Forzar el ícono de la ventana via Win32 (funciona con `py interfaz.py`).
    # Lo hacemos en background con varios reintentos porque la ventana de
    # Flet puede tardar 1-2s en estar disponible para EnumWindows.
    def _aplicar_icono_win32():
        if not os.path.exists(_logo_ico):
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            IMAGE_ICON      = 1
            LR_LOADFROMFILE = 0x0010
            LR_DEFAULTSIZE  = 0x0040
            WM_SETICON      = 0x0080
            ICON_SMALL      = 0
            ICON_BIG        = 1

            # Cargar el ícono dos veces (small + big)
            h_small = user32.LoadImageW(
                None, _logo_ico, IMAGE_ICON, 16, 16,
                LR_LOADFROMFILE,
            )
            h_big = user32.LoadImageW(
                None, _logo_ico, IMAGE_ICON, 32, 32,
                LR_LOADFROMFILE,
            )
            if not h_small and not h_big:
                return

            # Buscar las ventanas top-level del proceso actual
            pid_actual = kernel32.GetCurrentProcessId()
            hwnds_propias = []

            EnumWindowsProc = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM,
            )

            def _callback(hwnd, _lparam):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == pid_actual:
                    if user32.IsWindowVisible(hwnd):
                        hwnds_propias.append(hwnd)
                return True

            import time as _t
            for _ in range(20):  # ~6 segundos
                hwnds_propias.clear()
                user32.EnumWindows(EnumWindowsProc(_callback), 0)
                if hwnds_propias:
                    break
                _t.sleep(0.3)

            for hwnd in hwnds_propias:
                if h_small:
                    user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_small)
                if h_big:
                    user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_big)
        except Exception:
            pass

    threading.Thread(target=_aplicar_icono_win32, daemon=True).start()
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
        """Refresca controles puntuales (rápido) o toda la página si no
        se pasan args. Antes hacía siempre `page.update()` además del
        update individual — eso obligaba a Flet a recorrer todo el árbol
        de controles innecesariamente. Ahora:
          - `safe_update(c1, c2)` → sólo actualiza esos controles.
          - `safe_update()`       → actualiza toda la página.
        Ahorra ~30% del tiempo de render en flujos con muchos updates
        (refrescar tabla, ticks del watcher, etc.)."""
        if controles:
            for c in controles:
                try:
                    c.update()
                except Exception:
                    pass
        else:
            try:
                page.update()
            except Exception:
                pass

    # ── Helper: portapapeles. En Flet 0.84 page.set_clipboard fue removido.
    # Usamos la API nativa de Windows (Win32) con declaración explícita
    # de tipos (CRÍTICO en 64-bit: sin esto los punteros HGLOBAL se
    # truncan a 32 bits y SetClipboardData falla silenciosamente).
    # Soporta cientos de copias por segundo sin delay ni race conditions.
    try:
        import ctypes as _ctypes_mod
        from ctypes import wintypes as _wintypes_mod
        _u32 = _ctypes_mod.windll.user32
        _k32 = _ctypes_mod.windll.kernel32

        # Tipos de retorno y argumentos (sin esto, en 64-bit los handles
        # de 64 bits se truncan a 32 → corrupción de memoria → falla)
        _u32.OpenClipboard.argtypes  = [_wintypes_mod.HWND]
        _u32.OpenClipboard.restype   = _wintypes_mod.BOOL
        _u32.CloseClipboard.restype  = _wintypes_mod.BOOL
        _u32.EmptyClipboard.restype  = _wintypes_mod.BOOL
        _u32.SetClipboardData.argtypes = [_wintypes_mod.UINT, _wintypes_mod.HANDLE]
        _u32.SetClipboardData.restype  = _wintypes_mod.HANDLE
        _u32.GetClipboardData.argtypes = [_wintypes_mod.UINT]
        _u32.GetClipboardData.restype  = _wintypes_mod.HANDLE

        _k32.GlobalAlloc.argtypes  = [_wintypes_mod.UINT, _ctypes_mod.c_size_t]
        _k32.GlobalAlloc.restype   = _wintypes_mod.HGLOBAL
        _k32.GlobalLock.argtypes   = [_wintypes_mod.HGLOBAL]
        _k32.GlobalLock.restype    = _wintypes_mod.LPVOID
        _k32.GlobalUnlock.argtypes = [_wintypes_mod.HGLOBAL]
        _k32.GlobalUnlock.restype  = _wintypes_mod.BOOL
        _k32.GlobalFree.argtypes   = [_wintypes_mod.HGLOBAL]
        _k32.GlobalFree.restype    = _wintypes_mod.HGLOBAL

        _CLIPBOARD_OK = True
    except Exception:
        _CLIPBOARD_OK = False

    def copiar_portapapeles(texto):
        if texto is None:
            return False
        texto = str(texto)

        if _CLIPBOARD_OK:
            try:
                CF_UNICODETEXT = 13
                GMEM_MOVEABLE  = 0x0002

                # Reintentos rápidos por si el clipboard está bloqueado
                # por otra app
                abierto = False
                for _ in range(20):
                    if _u32.OpenClipboard(None):
                        abierto = True
                        break
                    _k32.Sleep(2)
                if not abierto:
                    return False

                try:
                    _u32.EmptyClipboard()
                    data  = (texto + "\0").encode("utf-16-le")
                    h_mem = _k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                    if not h_mem:
                        return False
                    ptr = _k32.GlobalLock(h_mem)
                    if not ptr:
                        _k32.GlobalFree(h_mem)
                        return False
                    _ctypes_mod.memmove(ptr, data, len(data))
                    _k32.GlobalUnlock(h_mem)
                    if not _u32.SetClipboardData(CF_UNICODETEXT, h_mem):
                        _k32.GlobalFree(h_mem)
                        return False
                    return True
                finally:
                    _u32.CloseClipboard()
            except Exception:
                pass

        # Fallback: subprocess Windows clip
        try:
            import subprocess
            subprocess.run(
                ["clip"], input=texto.encode("utf-16-le"),
                check=True, shell=False,
                creationflags=0x08000000,   # CREATE_NO_WINDOW
            )
            return True
        except Exception:
            return False

    def leer_portapapeles():
        """Devuelve el contenido del portapapeles como string (Win32)."""
        if not _CLIPBOARD_OK:
            return ""
        try:
            CF_UNICODETEXT = 13
            for _ in range(20):
                if _u32.OpenClipboard(None):
                    break
                _k32.Sleep(2)
            else:
                return ""
            try:
                handle = _u32.GetClipboardData(CF_UNICODETEXT)
                if not handle:
                    return ""
                ptr = _k32.GlobalLock(handle)
                if not ptr:
                    return ""
                try:
                    return _ctypes_mod.c_wchar_p(ptr).value or ""
                finally:
                    _k32.GlobalUnlock(handle)
            finally:
                _u32.CloseClipboard()
        except Exception:
            return ""

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

    # Placeholder inicial del historial de eventos del dashboard.
    # Cuando empieza a llegar el primer evento (`agregar_log`), se
    # auto-remueve para dejar lugar a la lista real.
    _dashboard_placeholder = ft.Container(
        alignment=ft.Alignment(0, 0),
        padding=ft.Padding(40, 50, 40, 50),
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
            controls=[
                ft.Container(
                    width=56, height=56,
                    bgcolor=C_MORADO_LIGHT,
                    border_radius=ft.BorderRadius(28, 28, 28, 28),
                    alignment=ft.Alignment(0, 0),
                    content=ft.Icon(
                        ft.Icons.PLAY_CIRCLE_OUTLINE_ROUNDED,
                        color=C_MORADO, size=28,
                    ),
                ),
                ft.Text(
                    "Listo para empezar",
                    size=14, weight=ft.FontWeight.BOLD,
                    color=C_TEXTO_1, font_family="Saira",
                ),
                ft.Text(
                    "Apretá \"Iniciar campaña\" arriba a la derecha. "
                    "Cada envío, rebote o evento de la campaña va a "
                    "aparecer acá en tiempo real.",
                    size=11, color=C_TEXTO_3,
                    font_family="Saira",
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
        ),
    )
    lista_actividad.controls.append(_dashboard_placeholder)
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

        # Quitamos el placeholder en cuanto llega el primer evento real.
        # Después, las llamadas sucesivas no encuentran el placeholder y
        # el check es O(1).
        if (lista_actividad.controls
                and lista_actividad.controls[0] is _dashboard_placeholder):
            lista_actividad.controls.clear()

        if historial_ascendente[0]:
            lista_actividad.controls.append(fila)
        else:
            lista_actividad.controls.insert(0, fila)

        # Auto-clear del historial visual del dashboard. Mantenemos los
        # últimos 200 eventos para que la UI no se vuelva lenta cuando
        # corren campañas grandes (1500+ envíos = 1500+ líneas). Los
        # eventos viejos siguen en el historial DEL DÍA (json) — esto
        # sólo cappea lo que se muestra en pantalla.
        MAX_EVENTOS_VISIBLES = 200
        if len(lista_actividad.controls) > MAX_EVENTOS_VISIBLES:
            if historial_ascendente[0]:
                # eventos viejos arriba → recortamos por arriba
                del lista_actividad.controls[:-MAX_EVENTOS_VISIBLES]
            else:
                # eventos viejos abajo → recortamos por abajo
                del lista_actividad.controls[MAX_EVENTOS_VISIBLES:]

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

    # Anti-spam de notificaciones de red: marcamos qué estados ya
    # avisamos para no machacar al usuario con 30 toasts iguales.
    _red_avisada = {"caido": False, "inestable": False, "agotado": False}

    def _on_red_estado(estado, intento, maximo, destino):
        """Hook que recibe notificaciones del módulo de envío.
        Convierte cada cambio de estado de red en un toast +
        línea en el historial de eventos."""
        try:
            if estado == "caido" and not _red_avisada["caido"]:
                _red_avisada["caido"] = True
                titulo = "Pulsemail — Sin conexión"
                cuerpo = (f"Se cortó internet enviando a {destino}. "
                          f"Reintentando hasta {maximo} veces.")
                agregar_log("warning", cuerpo)
                notificar_sistema(titulo, cuerpo)
            elif estado == "inestable" and not _red_avisada["inestable"]:
                _red_avisada["inestable"] = True
                titulo = "Pulsemail — Conexión inestable"
                cuerpo = (f"Microcortes detectados en {destino}. "
                          f"Reintento {intento}/{maximo}. Si querés, "
                          f"detené la campaña y retomala más tarde.")
                agregar_log("warning", cuerpo)
                notificar_sistema(titulo, cuerpo)
            elif estado == "reintentando":
                # Sólo log discreto, sin toast (cada 100 intentos)
                agregar_log("info",
                             f"Reintento {intento}/{maximo} para {destino}.")
            elif estado == "recuperado":
                _red_avisada["caido"] = False
                _red_avisada["inestable"] = False
                _red_avisada["agotado"] = False
                titulo = "Pulsemail — Conexión recuperada"
                cuerpo = (f"Volvió la red. Enviado a {destino} en el "
                          f"intento {intento}.")
                agregar_log("success", cuerpo)
                notificar_sistema(titulo, cuerpo)
            elif estado == "agotado" and not _red_avisada["agotado"]:
                _red_avisada["agotado"] = True
                titulo = "Pulsemail — Campaña detenida"
                cuerpo = (f"Sin internet tras {maximo} reintentos para "
                          f"{destino}. La campaña se detuvo. Cuando "
                          f"vuelva la red, iniciala de nuevo: retoma "
                          f"desde el correo pendiente.")
                agregar_log("error", cuerpo)
                notificar_sistema(titulo, cuerpo)
            elif estado == "detenido":
                cuerpo = (f"Campaña detenida en {destino} (intento "
                          f"{intento}/{maximo}). Guardado para retomar.")
                agregar_log("warning", cuerpo)
        except Exception:
            pass

    enviar_correos.set_red_hook(_on_red_estado)

    def arrancar(e):
        # Si la campaña está corriendo, este mismo botón pasa a ser
        # "Detener". Le pedimos al módulo de envío que aborte; el thread
        # del trabajador chequeará el flag y guardará el correo en cola
        # (`registro_pendiente.json`) antes de salir.
        if campana_activa[0]:
            enviar_correos.detener_campana()
            btn_iniciar.disabled = True
            btn_iniciar.content  = _contenido_btn(
                "Deteniendo...", ft.Icons.HOURGLASS_TOP_ROUNDED
            )
            safe_update()
            return

        cfg = enviar_correos.cargar_config()
        if not cfg.get("correo") or not cfg.get("password"):
            agregar_log("error", "No hay cuenta configurada. Ir a Configuración primero.")
            return
        # Reset banderas anti-spam y stop event para esta nueva corrida
        for k in _red_avisada:
            _red_avisada[k] = False
        enviar_correos.reset_stop_campana()

        campana_activa[0]    = True
        btn_iniciar.disabled = False
        ring_estado.visible  = True
        texto_estado.value   = "Campaña en ejecución..."
        btn_iniciar.content  = _contenido_btn(
            "Detener campaña", ft.Icons.STOP_CIRCLE_ROUNDED
        )
        # En modo detener el botón es ROJO para que el usuario lo
        # identifique como "acción destructiva".
        btn_iniciar.style = ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: C_ROJO,
                     ft.ControlState.HOVERED: "#c34061"},
            shape=ft.RoundedRectangleBorder(radius=10),
            elevation={ft.ControlState.DEFAULT: 0,
                       ft.ControlState.HOVERED: 4},
            animation_duration=200,
            padding=ft.Padding(28, 16, 28, 16),
        )
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
                # Mensaje de estado dependiente de cómo terminó
                if enviar_correos.campana_detenida():
                    texto_estado.value = "Campaña detenida."
                else:
                    texto_estado.value = "Campaña finalizada."
                btn_iniciar.content  = _contenido_btn(
                    "Iniciar campaña", ft.Icons.SEND_ROUNDED
                )
                btn_iniciar.style = ft.ButtonStyle(
                    bgcolor={ft.ControlState.DEFAULT: C_VERDE,
                             ft.ControlState.HOVERED: C_VERDE_DARK},
                    shape=ft.RoundedRectangleBorder(radius=10),
                    elevation={ft.ControlState.DEFAULT: 0,
                               ft.ControlState.HOVERED: 4},
                    animation_duration=200,
                    padding=ft.Padding(28, 16, 28, 16),
                )
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
        # Reaparece el placeholder para que la sección no quede en blanco.
        lista_actividad.controls.append(_dashboard_placeholder)
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
        # NO expand=True: si el DataTable se estira al ancho del padre,
        # los emails largos quedan truncados y el scroll horizontal del
        # Row contenedor nunca se activa. Sin expand, la tabla toma su
        # ancho natural según contenido y la Row hace scroll en pantallas
        # chicas.
    )

    # ── Estructura optimizada de contactos ──
    # Cada contacto se guarda como TUPLA de 7 elementos:
    #   (nombre, apellido, cuenta, email1, email2, email3, blob_busqueda)
    # `blob_busqueda` es todos los campos concatenados en lowercase —
    # filtrar con `q in blob` es mucho más rápido que 6 `.get().lower()`
    # por fila, y evita re-bajar a minúsculas en cada keystroke del
    # buscador (con 30k contactos esto cortó el lag de filtrado).
    # Índices: 0=nombre, 1=apellido, 2=cuenta, 3=email1, 4=email2, 5=email3
    IDX_NOMBRE, IDX_APELLIDO, IDX_CUENTA = 0, 1, 2
    IDX_E1, IDX_E2, IDX_E3, IDX_BLOB     = 3, 4, 5, 6

    # Cache del último render: si nada cambió desde la última vez,
    # skippeamos toda la reconstrucción de DataRows.
    # Key: (id(contactos_filtrados), pagina_contactos[0])
    _ultimo_render_key = [None]

    def _render_pagina_contactos(forzar=False):
        total_filtrado = len(contactos_filtrados)

        # Short-circuit: si nada cambió, no re-rendereamos. Esto evita
        # que al volver a la pestaña Contactos (cambiar_vista → cargar →
        # _aplicar_filtro → render) se re-creen 50 DataRows que ya están
        # idénticos en pantalla — principal causa del lag al alternar
        # pestañas con 17k+ contactos.
        clave_render = (id(contactos_filtrados), pagina_contactos[0])
        if not forzar and _ultimo_render_key[0] == clave_render:
            return

        tabla_contactos_rows.rows.clear()
        if total_filtrado == 0:
            lbl_pagina.value = "Sin resultados"
            _ultimo_render_key[0] = clave_render
            safe_update(tabla_contactos_rows, lbl_pagina)
            return
        max_pag = max(0, (total_filtrado - 1) // TAM_PAGINA)
        if pagina_contactos[0] > max_pag:
            pagina_contactos[0] = max_pag
        if pagina_contactos[0] < 0:
            pagina_contactos[0] = 0
        ini = pagina_contactos[0] * TAM_PAGINA
        fin = min(ini + TAM_PAGINA, total_filtrado)

        # Construimos las filas referenciando por índice (más rápido que
        # .get()). El ancho de página típico es 50 filas — render < 5ms.
        _txt = lambda s: ft.Text(s, font_family="Saira", size=13)
        nuevas_rows = []
        for t in contactos_filtrados[ini:fin]:
            nuevas_rows.append(
                ft.DataRow(cells=[
                    ft.DataCell(_txt(t[IDX_NOMBRE])),
                    ft.DataCell(_txt(t[IDX_APELLIDO])),
                    ft.DataCell(_txt(t[IDX_CUENTA])),
                    ft.DataCell(_txt(t[IDX_E1])),
                    ft.DataCell(_txt(t[IDX_E2])),
                    ft.DataCell(_txt(t[IDX_E3])),
                ])
            )
        tabla_contactos_rows.rows.extend(nuevas_rows)

        lbl_pagina.value = (
            f"Mostrando {ini + 1}–{fin} de {total_filtrado:,}".replace(",", ".")
            + f"  •  Página {pagina_contactos[0] + 1} / {max_pag + 1}"
        )

        # safe_update con args específicos: actualiza SÓLO la tabla y
        # el label. Evita el page.update() global que recorre todo el
        # árbol de widgets de la app (que es lo que producía el lag al
        # cambiar de página con 17k contactos).
        _ultimo_render_key[0] = clave_render
        safe_update(tabla_contactos_rows, lbl_pagina)

    # Debounce del buscador: en vez de filtrar en cada keystroke,
    # esperamos 180ms desde el último cambio. Con 30k contactos eso
    # convierte un input típico de 10 caracteres en 1 filtrado en
    # lugar de 10. Cancelable: cada keystroke nuevo cancela el timer
    # anterior.
    _filtro_timer = [None]
    _FILTRO_DEBOUNCE_S = 0.18

    def _aplicar_filtro_contactos():
        nonlocal contactos_filtrados
        q = (filtro_actual[0] or "").strip().lower()
        if not q:
            contactos_filtrados = contactos_data
        else:
            # Lookup contra el blob pre-computado (índice IDX_BLOB).
            # Operación O(1) por fila en lugar de 6 lookups + lower().
            contactos_filtrados = [
                t for t in contactos_data
                if q in t[IDX_BLOB]
            ]
        pagina_contactos[0] = 0
        _render_pagina_contactos()

    def _aplicar_filtro_contactos_debounced():
        # Cancelamos timer pendiente si lo hay
        t_anterior = _filtro_timer[0]
        if t_anterior is not None:
            try:
                t_anterior.cancel()
            except Exception:
                pass

        def _ejecutar():
            try:
                _aplicar_filtro_contactos()
            except Exception:
                pass

        timer_nuevo = threading.Timer(_FILTRO_DEBOUNCE_S, _ejecutar)
        timer_nuevo.daemon = True
        _filtro_timer[0] = timer_nuevo
        timer_nuevo.start()

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
                    reader = csv.reader(f)
                    # Headers: identificamos por nombre qué índice
                    # tiene cada columna (HubSpot puede cambiar orden).
                    try:
                        headers = next(reader)
                    except StopIteration:
                        headers = []
                    h_lower = [(h or "").strip().lower() for h in headers]

                    def _idx(*nombres):
                        for n in nombres:
                            n = n.lower()
                            if n in h_lower:
                                return h_lower.index(n)
                        return -1

                    i_nombre   = _idx("nombre")
                    i_apellido = _idx("apellidos", "apellido")
                    i_cuenta   = _idx("nombre de cuenta", "cuenta", "empresa")
                    i_e1       = _idx("correo electrónico", "correo electronico", "email")
                    i_e2       = _idx("correo electrónico secundario", "correo electronico secundario", "email 2")
                    i_e3       = _idx("correo electrónico terciario", "correo electronico terciario", "email 3")

                    def _get(row, idx):
                        if idx < 0 or idx >= len(row):
                            return ""
                        return (row[idx] or "").strip()

                    # csv.reader es 2-3x más rápido que DictReader y
                    # devuelve listas en lugar de OrderedDicts (menos
                    # overhead de memoria con 30k+ filas). Construimos
                    # tuplas inmutables con un blob de búsqueda pre-
                    # computado para que el filtro sea O(1) por fila.
                    for row in reader:
                        nombre   = _get(row, i_nombre)
                        apellido = _get(row, i_apellido)
                        cuenta   = _get(row, i_cuenta)
                        e1       = _get(row, i_e1)
                        e2       = _get(row, i_e2)
                        e3       = _get(row, i_e3)
                        # Blob lowercase: filtro hace `q in blob` sin
                        # llamadas a .lower() en cada keystroke.
                        blob = (
                            f"{nombre} {apellido} {cuenta} {e1} {e2} {e3}"
                        ).lower()
                        nuevos.append(
                            (nombre, apellido, cuenta, e1, e2, e3, blob)
                        )

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
        # Guard: si ya estoy en página 0 y delta=-1, o estoy en la
        # última página y delta=+1, no hacer nada (evita re-render
        # innecesario que el cache después absorbería pero igual paga
        # el costo del check inicial).
        nueva = pagina_contactos[0] + delta
        total = len(contactos_filtrados)
        max_pag = max(0, (total - 1) // TAM_PAGINA) if total else 0
        if nueva < 0 or nueva > max_pag:
            return
        pagina_contactos[0] = nueva
        _render_pagina_contactos()

    def _importar_contactos_dialog(e=None):
        """Abre un diálogo nativo de Windows para elegir un CSV y lo importa
        como contactos.csv (sobrescribe haciendo .bak previo)."""
        def _picker():
            try:
                path = _dialogo_archivo_nativo(
                    save=False,
                    title="Seleccioná tu contactos.csv",
                    filtros=[("CSV", "*.csv"), ("Todos los archivos", "*.*")],
                )
                if not path:
                    return
                ok, msg = enviar_correos.importar_archivo_local(
                    path, "contactos.csv"
                )
                if ok:
                    agregar_log("info",
                                f"Contactos importados desde: {path}")
                    cargar_contactos(forzar=True)
                else:
                    agregar_log("error", f"No se pudo importar: {msg}")
            except Exception as ex:
                try:
                    agregar_log("error", f"Error abriendo diálogo: {ex}")
                except Exception:
                    pass
        threading.Thread(target=_picker, daemon=True).start()

    # ── Pegar contactos desde el portapapeles ─────────────────────
    tf_pegar_contactos = ft.TextField(
        label="Emails (uno por línea o separados por coma/espacio)",
        hint_text=("ejemplo1@empresa.com\nejemplo2@empresa.com\n"
                    "contacto@otra.com\n..."),
        multiline=True,
        min_lines=8,
        max_lines=15,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        text_style=ft.TextStyle(font_family="Saira"),
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        expand=True,
    )
    lbl_pegar_estado = ft.Text("", size=12, italic=True, font_family="Saira")

    def _pegar_del_portapapeles(e=None):
        contenido = leer_portapapeles()
        if contenido:
            tf_pegar_contactos.value = (
                (tf_pegar_contactos.value or "") + "\n" + contenido
            ).strip()
            safe_update(tf_pegar_contactos)
        else:
            lbl_pegar_estado.value = "Portapapeles vacío"
            lbl_pegar_estado.color = C_NARANJA
            safe_update(lbl_pegar_estado)

    def _agregar_contactos_pegados(e=None):
        texto = tf_pegar_contactos.value or ""
        # Parsear emails (acepta separados por línea, coma, ; o espacio)
        emails = re.findall(
            r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", texto
        )
        # Dedupe respetando orden
        vistos, nuevos = set(), []
        for em in emails:
            em_low = em.lower()
            if em_low not in vistos:
                vistos.add(em_low)
                nuevos.append(em)

        if not nuevos:
            lbl_pegar_estado.value = "No se encontraron emails válidos."
            lbl_pegar_estado.color = C_ROJO
            safe_update(lbl_pegar_estado)
            return

        # Cargar el CSV existente para no duplicar
        ruta_csv = enviar_correos.ARCHIVO_CSV
        existentes = set()
        filas_actuales = []
        cabeceras = ["Nombre de Cuenta", "Nombre", "Apellidos",
                     "Correo electrónico", "Correo electrónico secundario",
                     "Correo electrónico terciario"]
        if os.path.exists(ruta_csv):
            try:
                with open(ruta_csv, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    if reader.fieldnames:
                        cabeceras = reader.fieldnames
                    for fila in reader:
                        filas_actuales.append(fila)
                        for k in ("Correo electrónico",
                                  "Correo electrónico secundario",
                                  "Correo electrónico terciario"):
                            v = (fila.get(k) or "").strip().lower()
                            if v:
                                existentes.add(v)
            except Exception:
                pass

        agregados = 0
        omitidos = 0
        for em in nuevos:
            if em.lower() in existentes:
                omitidos += 1
                continue
            fila = {h: "" for h in cabeceras}
            fila["Nombre de Cuenta"] = "Sin nombre"
            fila["Nombre"]           = ""
            fila["Apellidos"]        = ""
            fila["Correo electrónico"] = em
            filas_actuales.append(fila)
            existentes.add(em.lower())
            agregados += 1

        # Hacer backup previo
        try:
            if os.path.exists(ruta_csv):
                import shutil as _sh
                _sh.copy2(ruta_csv, ruta_csv + ".bak")
        except Exception:
            pass

        # Escribir el CSV completo
        try:
            with open(ruta_csv, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=cabeceras)
                writer.writeheader()
                writer.writerows(filas_actuales)
        except Exception as ex:
            lbl_pegar_estado.value = f"Error al guardar: {ex}"
            lbl_pegar_estado.color = C_ROJO
            safe_update(lbl_pegar_estado)
            return

        msg_partes = [f"✓ {agregados} agregado{'s' if agregados != 1 else ''}"]
        if omitidos:
            msg_partes.append(f"{omitidos} ya existía{'n' if omitidos != 1 else ''}")
        lbl_pegar_estado.value = "  •  ".join(msg_partes)
        lbl_pegar_estado.color = C_EXITO
        safe_update(lbl_pegar_estado)

        agregar_log("info",
                    f"Contactos pegados: {agregados} agregados, "
                    f"{omitidos} duplicados omitidos")

        if agregados > 0:
            tf_pegar_contactos.value = ""
            safe_update(tf_pegar_contactos)
            cargar_contactos(forzar=True)

    btn_pegar_portapapeles = ft.OutlinedButton(
        "Pegar del portapapeles",
        icon=ft.Icons.CONTENT_PASTE_ROUNDED,
        on_click=_pegar_del_portapapeles,
        style=ft.ButtonStyle(
            color={ft.ControlState.DEFAULT: C_MORADO},
            side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, C_MORADO)},
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(14, 10, 14, 10),
        ),
    )
    btn_agregar_pegados = ft.ElevatedButton(
        "Agregar al CSV",
        icon=ft.Icons.PERSON_ADD_ROUNDED,
        on_click=_agregar_contactos_pegados,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: C_MORADO,
                     ft.ControlState.HOVERED: C_MORADO_DARK},
            color={ft.ControlState.DEFAULT: C_BLANCO},
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(20, 12, 20, 12),
        ),
    )

    dialog_pegar_contactos = ft.AlertDialog(
        modal=True,
        title=ft.Row(
            spacing=8,
            controls=[
                ft.Icon(ft.Icons.CONTENT_PASTE_ROUNDED, color=C_MORADO),
                ft.Text("Pegar contactos", size=18, weight=ft.FontWeight.BOLD,
                        color=C_TEXTO_1, font_family="Saira"),
            ],
        ),
        content=ft.Container(
            width=560,
            content=ft.Column(
                tight=True,
                spacing=12,
                controls=[
                    ft.Text(
                        "Pegá una lista de emails (uno por línea, "
                        "separados por coma, punto y coma o espacio). "
                        "Pulsemail extrae los emails y los agrega al "
                        "contactos.csv evitando duplicados.",
                        size=12, color=C_TEXTO_3, font_family="Saira",
                    ),
                    tf_pegar_contactos,
                    lbl_pegar_estado,
                ],
            ),
        ),
        actions=[
            btn_pegar_portapapeles,
            ft.TextButton(
                "Cerrar",
                on_click=lambda e: (
                    page.close(dialog_pegar_contactos)
                    if hasattr(page, "close")
                    else (setattr(dialog_pegar_contactos, "open", False),
                          safe_update())
                ),
                style=ft.ButtonStyle(color=C_TEXTO_2),
            ),
            btn_agregar_pegados,
        ],
        actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )

    def _abrir_dialog_pegar_contactos(e=None):
        tf_pegar_contactos.value  = ""
        lbl_pegar_estado.value    = ""
        try:
            page.open(dialog_pegar_contactos)
        except Exception:
            page.dialog = dialog_pegar_contactos
            dialog_pegar_contactos.open = True
            safe_update()

    # Banner que aparece cuando detectamos emails pegados en el buscador
    lbl_pegar_detect = ft.Text("", size=12, font_family="Saira",
                                color=C_MORADO, italic=True)
    btn_agregar_pegados_inline = ft.ElevatedButton(
        "Agregar al CSV",
        icon=ft.Icons.PERSON_ADD_ROUNDED,
        visible=False,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: C_MORADO,
                     ft.ControlState.HOVERED: C_MORADO_DARK},
            color={ft.ControlState.DEFAULT: C_BLANCO},
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(14, 8, 14, 8),
        ),
    )
    _emails_pendientes_pegar = [[]]

    def _agregar_emails_al_csv(emails_a_agregar):
        """Agrega los emails dados al contactos.csv (con .bak previo).
        Devuelve (agregados, omitidos)."""
        ruta_csv = enviar_correos.ARCHIVO_CSV
        existentes = set()
        filas_actuales = []
        cabeceras = ["Nombre de Cuenta", "Nombre", "Apellidos",
                     "Correo electrónico", "Correo electrónico secundario",
                     "Correo electrónico terciario"]
        if os.path.exists(ruta_csv):
            try:
                with open(ruta_csv, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    if reader.fieldnames:
                        cabeceras = reader.fieldnames
                    for fila in reader:
                        filas_actuales.append(fila)
                        for k in ("Correo electrónico",
                                  "Correo electrónico secundario",
                                  "Correo electrónico terciario"):
                            v = (fila.get(k) or "").strip().lower()
                            if v:
                                existentes.add(v)
            except Exception:
                pass

        agregados = 0
        omitidos = 0
        for em in emails_a_agregar:
            if em.lower() in existentes:
                omitidos += 1
                continue
            fila = {h: "" for h in cabeceras}
            fila["Nombre de Cuenta"]      = "Sin nombre"
            fila["Correo electrónico"]    = em
            filas_actuales.append(fila)
            existentes.add(em.lower())
            agregados += 1

        try:
            if os.path.exists(ruta_csv):
                import shutil as _sh
                _sh.copy2(ruta_csv, ruta_csv + ".bak")
        except Exception:
            pass
        try:
            with open(ruta_csv, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=cabeceras)
                writer.writeheader()
                writer.writerows(filas_actuales)
        except Exception:
            pass
        return agregados, omitidos

    def _on_buscar_change(e):
        valor = e.control.value or ""
        filtro_actual[0] = valor
        # Detectar si el contenido pegado tiene emails. Sólo activamos el
        # botón si hay 2+ (con uno solo, el comportamiento esperado es
        # filtrar normal).
        emails_detectados = re.findall(
            r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", valor
        )
        emails_unicos = []
        vistos = set()
        for em in emails_detectados:
            em_l = em.lower()
            if em_l not in vistos:
                vistos.add(em_l)
                emails_unicos.append(em)

        if len(emails_unicos) >= 2:
            _emails_pendientes_pegar[0] = emails_unicos
            lbl_pegar_detect.value = (
                f"Detectados {len(emails_unicos)} emails. "
                f"¿Querés agregarlos al CSV?"
            )
            btn_agregar_pegados_inline.visible = True
            btn_agregar_pegados_inline.text = (
                f"Agregar {len(emails_unicos)} al CSV"
            )
        else:
            _emails_pendientes_pegar[0] = []
            lbl_pegar_detect.value = ""
            btn_agregar_pegados_inline.visible = False

        # Usamos la versión debounced en el handler de keystrokes para
        # que filtrar 30k contactos no se ejecute con cada letra.
        _aplicar_filtro_contactos_debounced()
        safe_update(lbl_pegar_detect, btn_agregar_pegados_inline)

    def _accion_agregar_pegados(e=None):
        emails = _emails_pendientes_pegar[0]
        if not emails:
            return
        agregados, omitidos = _agregar_emails_al_csv(emails)
        msg = f"✓ {agregados} agregados"
        if omitidos:
            msg += f"  •  {omitidos} ya existían"
        lbl_pegar_detect.value = msg
        lbl_pegar_detect.color = C_EXITO
        # Limpiar el buscador y refrescar lista
        tf_buscar_contactos.value = ""
        filtro_actual[0] = ""
        _emails_pendientes_pegar[0] = []
        btn_agregar_pegados_inline.visible = False
        agregar_log("info",
                    f"Contactos agregados desde búsqueda: {agregados} nuevos, "
                    f"{omitidos} duplicados omitidos")
        cargar_contactos(forzar=True)
        safe_update()

    btn_agregar_pegados_inline.on_click = _accion_agregar_pegados

    tf_buscar_contactos = ft.TextField(
        hint_text=("Buscar por nombre, cuenta o correo... "
                    "(o pegá una lista de emails con Ctrl+V para agregarlos)"),
        prefix_icon=ft.Icons.SEARCH_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
        on_change=_on_buscar_change,
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
                    ft.OutlinedButton(
                        "Importar CSV…",
                        icon=ft.Icons.UPLOAD_FILE_ROUNDED,
                        on_click=_importar_contactos_dialog,
                        style=ft.ButtonStyle(
                            color={ft.ControlState.DEFAULT: C_MORADO},
                            side={ft.ControlState.DEFAULT:
                                  ft.BorderSide(1.2, C_MORADO)},
                            shape=ft.RoundedRectangleBorder(radius=8),
                            padding=ft.Padding(14, 12, 14, 12),
                        ),
                    ),
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
            ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=12,
                controls=[
                    lbl_pegar_detect,
                    ft.Container(expand=True),
                    btn_agregar_pegados_inline,
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
    # PANEL LISTA NEGRA — opt-outs (responden BAJA o piden no recibir)
    # ==========================================
    # Tres orígenes de un email en la lista:
    #   1. Auto: respondieron a una campaña con "BAJA" o frase opt-out.
    #   2. Manual: el usuario lo agregó desde este panel.
    #   3. Importado: vino de un CSV de campañas anteriores.
    # Cualquier email que esté en la lista se saltea silenciosamente
    # cuando arranca una campaña.
    lista_negra_data        = []   # cache local del JSON crudo
    lista_negra_filtrada    = []   # subset después del filtro de búsqueda
    pagina_negra            = [0]
    # Tamaño de página configurable por el usuario. Default 200 (vs 50
    # anterior) — con scroll vertical en la tabla evita estar paginando
    # constantemente. Si hay menos de 200 items se ven todos en una sola.
    TAMS_PAGINA_NEGRA       = [200, 500, 1000]
    TAM_PAGINA_NEGRA_DEFAULT = 200
    tam_pagina_negra        = [TAM_PAGINA_NEGRA_DEFAULT]

    lbl_negra_total = ft.Text("", size=12, color=C_TEXTO_3, font_family="Saira")
    lbl_negra_pagina = ft.Text("", size=12, color=C_TEXTO_2, font_family="Saira")

    # KPIs grandes arriba del panel: Total / Auto / Manual.
    # Los actualizamos en cada cargar_lista_negra_panel().
    kpi_negra_total  = ft.Text("0", size=32, weight=ft.FontWeight.BOLD,
                                color=C_TEXTO_1, font_family="Saira")
    kpi_negra_auto   = ft.Text("0", size=32, weight=ft.FontWeight.BOLD,
                                color=C_MORADO, font_family="Saira")
    kpi_negra_manual = ft.Text("0", size=32, weight=ft.FontWeight.BOLD,
                                color=C_VERDE_DARK, font_family="Saira")

    def _kpi_card(titulo, valor_widget, color_chip, label_chip, icon):
        # Chip con fondo SÓLIDO y texto BLANCO. Antes usábamos
        # `color_chip + "25"` (alpha 25%) con texto del mismo color —
        # en tema oscuro el bg quedaba casi negro y el texto color
        # quedaba ilegible. Bg sólido + texto blanco se ve igual de
        # bien en tema claro y oscuro.
        return ft.Container(
            expand=True,
            bgcolor=C_BLANCO,
            border_radius=ft.BorderRadius(14, 14, 14, 14),
            border=borde_all(1, C_BORDE),
            padding=ft.Padding(20, 18, 20, 18),
            content=ft.Column(
                spacing=6,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(titulo, size=11, color=C_TEXTO_3,
                                    weight=ft.FontWeight.BOLD,
                                    font_family="Saira"),
                            ft.Container(
                                bgcolor=color_chip,
                                border_radius=ft.BorderRadius(6, 6, 6, 6),
                                padding=ft.Padding(8, 3, 8, 3),
                                content=ft.Row(
                                    spacing=4,
                                    controls=[
                                        ft.Icon(icon, color=C_BLANCO,
                                                size=12),
                                        ft.Text(label_chip, size=10,
                                                color=C_BLANCO,
                                                weight=ft.FontWeight.BOLD,
                                                font_family="Saira"),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    valor_widget,
                ],
            ),
        )

    kpi_card_total = _kpi_card(
        "TOTAL BLOQUEADOS", kpi_negra_total,
        C_TEXTO_2, "lista negra", ft.Icons.BLOCK_ROUNDED,
    )
    kpi_card_auto = _kpi_card(
        "DETECCIÓN AUTOMÁTICA", kpi_negra_auto,
        C_MORADO, "respondieron BAJA", ft.Icons.SMART_TOY_ROUNDED,
    )
    kpi_card_manual = _kpi_card(
        "AGREGADOS MANUALMENTE", kpi_negra_manual,
        C_VERDE_DARK, "tu decisión", ft.Icons.PERSON_ROUNDED,
    )

    # Filtros tipo "chip": Todos / Auto / Manual.
    filtro_origen = ["todos"]   # 'todos' | 'auto' | 'manual'
    btns_filtro_origen = {}

    def _refrescar_chips_filtro():
        estilos = {
            "todos":  (C_MORADO,    "Todos",   ft.Icons.LIST_ALT_ROUNDED),
            "auto":   (C_MORADO,    "Auto",    ft.Icons.SMART_TOY_ROUNDED),
            "manual": (C_VERDE_DARK, "Manual", ft.Icons.PERSON_ROUNDED),
        }
        for k, b in btns_filtro_origen.items():
            activo = (k == filtro_origen[0])
            color  = estilos[k][0]
            b.style = ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: color if activo else C_BLANCO},
                color={ft.ControlState.DEFAULT: C_BLANCO if activo else color},
                side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, color)},
                shape=ft.RoundedRectangleBorder(radius=20),
                padding=ft.Padding(14, 8, 14, 8),
            )
        try:
            for b in btns_filtro_origen.values():
                b.update()
        except Exception:
            pass

    def _set_filtro_origen(k):
        filtro_origen[0] = k
        pagina_negra[0] = 0
        _refrescar_chips_filtro()
        _aplicar_filtro_negra()

    for key, (color_c, label_c, icon_c) in [
        ("todos",  (C_MORADO,     "Todos",  ft.Icons.LIST_ALT_ROUNDED)),
        ("auto",   (C_MORADO,     "Auto-baja", ft.Icons.SMART_TOY_ROUNDED)),
        ("manual", (C_VERDE_DARK, "Manuales",  ft.Icons.PERSON_ROUNDED)),
    ]:
        btns_filtro_origen[key] = ft.ElevatedButton(
            label_c, icon=icon_c,
            on_click=lambda e, k=key: _set_filtro_origen(k),
        )
    _refrescar_chips_filtro()

    tabla_negra = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Email", font_family="Saira",
                                  weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Fecha", font_family="Saira",
                                  weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Motivo", font_family="Saira",
                                  weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Origen", font_family="Saira",
                                  weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Acción", font_family="Saira",
                                  weight=ft.FontWeight.BOLD)),
        ],
        rows=[],
        border=ft.border.all(1, C_BORDE),
        border_radius=10,
        heading_row_color=C_FONDO,
        heading_row_height=46,
        data_row_min_height=44,
        column_spacing=24,
        horizontal_lines=ft.BorderSide(1, C_BORDE),
        # Que la tabla ocupe todo el ancho disponible — antes quedaba
        # achicada al ancho mínimo de su contenido y se veía pobre.
        expand=True,
    )

    # Contenedor que alternará entre la tabla (con datos) y el empty
    # state (cuando no hay nada). Lo definimos abajo en la vista; aquí
    # sólo lo declaramos para que el render lo pueda mutar.
    contenedor_tabla_negra = ft.Container(expand=True)

    def _render_pagina_negra():
        tabla_negra.rows.clear()
        total = len(lista_negra_filtrada)

        # Si no hay ningún email en la lista negra del usuario (no es un
        # filtro vacío, sino lista TOTALMENTE vacía), mostramos un empty
        # state amigable en vez de la tabla con headers solos.
        if not lista_negra_data:
            contenedor_tabla_negra.content = ft.Container(
                expand=True,
                bgcolor=C_BLANCO,
                border_radius=ft.BorderRadius(14, 14, 14, 14),
                border=borde_all(1, C_BORDE),
                alignment=ft.Alignment(0, 0),
                padding=ft.Padding(40, 60, 40, 60),
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=14,
                    controls=[
                        ft.Container(
                            width=72, height=72,
                            bgcolor=C_MORADO_LIGHT,
                            border_radius=ft.BorderRadius(36, 36, 36, 36),
                            alignment=ft.Alignment(0, 0),
                            content=ft.Icon(
                                ft.Icons.SHIELD_OUTLINED,
                                color=C_MORADO, size=36,
                            ),
                        ),
                        ft.Text(
                            "Tu lista negra está vacía",
                            size=18, weight=ft.FontWeight.BOLD,
                            color=C_TEXTO_1, font_family="Saira",
                        ),
                        ft.Text(
                            "Cuando alguien responda \"BAJA\" a una campaña "
                            "o pida no recibir más correos, va a aparecer "
                            "acá automáticamente y se va a saltear en las "
                            "próximas campañas.",
                            size=12, color=C_TEXTO_3, font_family="Saira",
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            "También podés agregar emails manualmente con "
                            "el formulario de arriba.",
                            size=11, color=C_TEXTO_3, italic=True,
                            font_family="Saira",
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                ),
            )
            lbl_negra_total.value  = "Total bloqueados: 0"
            lbl_negra_pagina.value = ""
            safe_update()
            return

        # Si hay emails pero el filtro/buscador devuelve 0, mostramos un
        # mensaje de "sin resultados" — distinto al empty state global.
        if total == 0:
            contenedor_tabla_negra.content = ft.Container(
                expand=True,
                bgcolor=C_BLANCO,
                border_radius=ft.BorderRadius(14, 14, 14, 14),
                border=borde_all(1, C_BORDE),
                alignment=ft.Alignment(0, 0),
                padding=ft.Padding(40, 50, 40, 50),
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                    controls=[
                        ft.Icon(ft.Icons.SEARCH_OFF_ROUNDED,
                                color=C_TEXTO_3, size=44),
                        ft.Text(
                            "Sin resultados con los filtros actuales",
                            size=14, color=C_TEXTO_2, font_family="Saira",
                        ),
                    ],
                ),
            )
            lbl_negra_total.value  = f"Total bloqueados: {len(lista_negra_data)}"
            lbl_negra_pagina.value = ""
            safe_update()
            return

        tam_pag = tam_pagina_negra[0]
        max_pag = max(0, (total - 1) // tam_pag)
        if pagina_negra[0] > max_pag:
            pagina_negra[0] = max_pag
        if pagina_negra[0] < 0:
            pagina_negra[0] = 0
        ini = pagina_negra[0] * tam_pag
        fin = ini + tam_pag

        # Tabla full-width con scroll vertical. Flet DataTable dentro
        # de un Column(scroll=AUTO) NO respeta `expand=True` porque la
        # column con scroll permite tamaño natural. Solución: envolver
        # con una Row(expand=True) — eso fuerza al DataTable a tomar
        # todo el ancho disponible. El scroll vertical lo da la Column
        # exterior cuando hay más filas que las visibles.
        contenedor_tabla_negra.content = ft.Container(
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
                        expand=True,
                        controls=[
                            ft.Container(expand=True, content=tabla_negra),
                        ],
                    ),
                ],
            ),
        )

        for entrada in lista_negra_filtrada[ini:fin]:
            email_addr = (entrada.get("email") or "").strip()
            fecha      = entrada.get("fecha", "")
            motivo     = entrada.get("motivo", "")
            es_auto    = entrada.get("auto", False)

            # Chips de origen con fondo SÓLIDO y texto blanco para que
            # se lean igual en tema claro y oscuro. Los chips "light +
            # texto color" antes quedaban casi invisibles en oscuro.
            chip_origen = ft.Container(
                bgcolor=(C_MORADO if es_auto else C_VERDE_DARK),
                border_radius=ft.BorderRadius(6, 6, 6, 6),
                padding=ft.Padding(8, 3, 8, 3),
                content=ft.Text(
                    "AUTO" if es_auto else "MANUAL",
                    size=10, weight=ft.FontWeight.BOLD,
                    color=C_BLANCO,
                    font_family="Saira",
                ),
            )

            def _hacer_quitar(em=email_addr):
                def _quitar(e):
                    enviar_correos.quitar_de_lista_negra(em)
                    cargar_lista_negra_panel()
                return _quitar

            btn_quitar = ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
                icon_color=C_ROJO,
                tooltip="Quitar de la lista negra",
                on_click=_hacer_quitar(),
            )

            tabla_negra.rows.append(
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(email_addr, size=13,
                                        font_family="Saira",
                                        color=C_TEXTO_1)),
                    ft.DataCell(ft.Text(fecha[:16] if fecha else "",
                                        size=12, font_family="Saira",
                                        color=C_TEXTO_3)),
                    ft.DataCell(ft.Text(motivo[:60], size=12,
                                        font_family="Saira",
                                        color=C_TEXTO_2)),
                    ft.DataCell(chip_origen),
                    ft.DataCell(btn_quitar),
                ])
            )

        lbl_negra_total.value = f"Total bloqueados: {len(lista_negra_data)}"
        lbl_negra_pagina.value = (
            f"Mostrando {ini + 1}-{min(fin, total)} de {total} "
            f"  •  Página {pagina_negra[0] + 1} / {max_pag + 1}"
        )
        safe_update()

    tf_buscar_negra = ft.TextField(
        hint_text="Buscar email...",
        prefix_icon=ft.Icons.SEARCH_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        text_style=ft.TextStyle(font_family="Saira"),
        on_change=lambda e: _aplicar_filtro_negra(),
        expand=True,
    )

    # Dropdown para elegir cuántos items por página. Reduce el tedio
    # de paginar cuando el usuario tiene 500+ entries en la lista negra.
    def _on_cambio_tam_pagina(e):
        try:
            tam_pagina_negra[0] = int(e.control.value)
        except Exception:
            tam_pagina_negra[0] = TAM_PAGINA_NEGRA_DEFAULT
        pagina_negra[0] = 0
        _render_pagina_negra()

    # En Flet 0.84 `ft.Dropdown.__init__()` NO acepta `on_change` como
    # kwarg (verificado por smoke test: tooltip/content_padding/etc.
    # sí pasan, on_change sólo se puede setear como atributo después).
    dropdown_tam_pagina = ft.Dropdown(
        value=str(TAM_PAGINA_NEGRA_DEFAULT),
        options=[ft.dropdown.Option(str(t)) for t in TAMS_PAGINA_NEGRA],
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        text_style=ft.TextStyle(font_family="Saira", size=13),
        width=110,
        content_padding=ft.Padding(12, 8, 12, 8),
        tooltip="Items por página",
    )
    dropdown_tam_pagina.on_change = _on_cambio_tam_pagina

    def _aplicar_filtro_negra():
        nonlocal lista_negra_filtrada
        q = (tf_buscar_negra.value or "").strip().lower()
        base = lista_negra_data
        if filtro_origen[0] == "auto":
            base = [e for e in base if e.get("auto")]
        elif filtro_origen[0] == "manual":
            base = [e for e in base if not e.get("auto")]
        if q:
            base = [
                e for e in base
                if q in (e.get("email") or "").lower()
                or q in (e.get("motivo") or "").lower()
            ]
        lista_negra_filtrada = base
        _render_pagina_negra()

    def cargar_lista_negra_panel():
        nonlocal lista_negra_data, lista_negra_filtrada
        try:
            data = enviar_correos.cargar_lista_negra()
            lista_negra_data = sorted(
                data.get("emails", []),
                key=lambda x: x.get("fecha", ""),
                reverse=True,
            )
        except Exception:
            lista_negra_data = []
        # KPIs
        total = len(lista_negra_data)
        autos = sum(1 for e in lista_negra_data if e.get("auto"))
        manuales = total - autos
        kpi_negra_total.value  = str(total)
        kpi_negra_auto.value   = str(autos)
        kpi_negra_manual.value = str(manuales)
        _aplicar_filtro_negra()

    # ── Diálogo "Agregar manualmente" ──────────────────────────────
    tf_nuevo_email = ft.TextField(
        label="Email a bloquear",
        hint_text="cliente@empresa.com",
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        text_style=ft.TextStyle(font_family="Saira"),
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        autofocus=True,
    )
    tf_nuevo_motivo = ft.TextField(
        label="Motivo (opcional)",
        hint_text="Ej: pidió no recibir más correos",
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        text_style=ft.TextStyle(font_family="Saira"),
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
    )

    def _agregar_email_manual(e=None):
        em = (tf_nuevo_email.value or "").strip()
        if not em or "@" not in em:
            return
        motivo = (tf_nuevo_motivo.value or "Agregado manualmente").strip()
        enviar_correos.agregar_a_lista_negra(em, motivo=motivo, auto=False)
        tf_nuevo_email.value = ""
        tf_nuevo_motivo.value = ""
        cargar_lista_negra_panel()

    btn_agregar_negra = ft.ElevatedButton(
        "Agregar a lista negra",
        icon=ft.Icons.ADD_ROUNDED,
        on_click=_agregar_email_manual,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: C_MORADO,
                     ft.ControlState.HOVERED: C_MORADO_DARK},
            color=C_BLANCO,
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(16, 10, 16, 10),
        ),
    )

    # ── Importar / exportar CSV ────────────────────────────────────
    def _exportar_negra_csv(e=None):
        def _picker():
            try:
                path = _dialogo_archivo_nativo(
                    save=True,
                    title="Guardar lista negra como CSV",
                    filtros=[("CSV", "*.csv"), ("Todos", "*.*")],
                    default_name="lista_negra.csv",
                    default_ext="csv",
                )
                if not path:
                    return
                import csv as _csv
                with open(path, "w", encoding="utf-8", newline="") as f:
                    w = _csv.writer(f)
                    w.writerow(["email", "fecha", "motivo", "auto"])
                    for entry in lista_negra_data:
                        w.writerow([
                            entry.get("email", ""),
                            entry.get("fecha", ""),
                            entry.get("motivo", ""),
                            "AUTO" if entry.get("auto") else "MANUAL",
                        ])
                agregar_log("success",
                            f"Lista negra exportada: {path}")
            except Exception as ex:
                agregar_log("error", f"No se pudo exportar: {ex}")
        threading.Thread(target=_picker, daemon=True).start()

    def _importar_negra_csv(e=None):
        def _picker():
            try:
                path = _dialogo_archivo_nativo(
                    save=False,
                    title="Importar emails a lista negra",
                    filtros=[("CSV / TXT", "*.csv *.txt"), ("Todos", "*.*")],
                )
                if not path:
                    return
                agregados = 0
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for linea in f:
                        # Tomamos lo primero que parezca un email en
                        # cada línea (soporta CSV, TXT plano, etc.).
                        m = re.search(
                            r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
                            linea,
                        )
                        if m:
                            if enviar_correos.agregar_a_lista_negra(
                                m.group(0),
                                motivo="Importado desde CSV",
                                auto=False,
                            ):
                                agregados += 1
                agregar_log(
                    "success",
                    f"Importados {agregados} email(s) a lista negra.",
                )
                cargar_lista_negra_panel()
            except Exception as ex:
                agregar_log("error", f"No se pudo importar: {ex}")
        threading.Thread(target=_picker, daemon=True).start()

    btn_exportar_negra = ft.OutlinedButton(
        "Exportar CSV",
        icon=ft.Icons.DOWNLOAD_ROUNDED,
        on_click=_exportar_negra_csv,
        style=ft.ButtonStyle(
            color={ft.ControlState.DEFAULT: C_MORADO},
            side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, C_MORADO)},
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(14, 10, 14, 10),
        ),
    )
    btn_importar_negra = ft.OutlinedButton(
        "Importar CSV",
        icon=ft.Icons.UPLOAD_ROUNDED,
        on_click=_importar_negra_csv,
        style=ft.ButtonStyle(
            color={ft.ControlState.DEFAULT: C_MORADO},
            side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, C_MORADO)},
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(14, 10, 14, 10),
        ),
    )

    # ── Botón "Escanear respuestas viejas" ──
    # Re-evalúa todas las respuestas históricas (`registro_respuestas.json`)
    # buscando pedidos de BAJA que no fueron detectados cuando llegaron
    # — útil después de actualizar la app, o como botón "barrer pasado"
    # cuando el usuario nota que se le pasaron bajas.
    ring_escan_baja = ft.ProgressRing(
        color=C_MORADO, width=16, height=16,
        stroke_width=2.5, visible=False,
    )

    # Throttle: si se llamó hace menos de 10 segundos, ignorar. Cuando
    # ya no hay respuestas pendientes de evaluar el scan termina en
    # milisegundos y el ring no llega a "verse" — sin throttle el
    # usuario clickeando rápido genera 10 logs idénticos en el dashboard.
    _ultimo_scan_baja_ts = [0.0]
    _SCAN_BAJA_COOLDOWN  = 10.0   # segundos

    def _escanear_bajas_retro(e=None):
        import time as _t
        ahora = _t.time()
        if ring_escan_baja.visible:
            return
        # Cooldown: si recién terminó, ignorar silenciosamente
        if (ahora - _ultimo_scan_baja_ts[0]) < _SCAN_BAJA_COOLDOWN:
            return
        cfg = enviar_correos.cargar_config()
        if not cfg.get("correo") or not cfg.get("password"):
            agregar_log("error",
                        "Configurá la cuenta antes de escanear respuestas.")
            return
        ring_escan_baja.visible = True
        safe_update(ring_escan_baja)

        def trabajador():
            try:
                resumen = enviar_correos.escanear_bajas_retroactivo()

                # Sólo logueamos si hubo algo interesante (cambios reales).
                # Si todas las respuestas ya estaban evaluadas y no hay
                # nuevas bajas, NO ensuciamos el historial del dashboard
                # — eso causaba el spam visible de "0 analizadas, 0 nuevas
                # bajas" que el usuario reportó.
                if resumen["nuevas_bajas"] > 0:
                    msg = (
                        f"Auto-baja retroactiva: "
                        f"{resumen['nuevas_bajas']} nueva(s) detectada(s) "
                        f"sobre {resumen['analizados']} respuestas analizadas."
                    )
                    agregar_log("success", msg)
                elif resumen["analizados"] > 0:
                    msg = (
                        f"Scan completo: {resumen['analizados']} "
                        f"respuestas analizadas, sin nuevas bajas."
                    )
                    agregar_log("info", msg)
                elif resumen["errores"] > 0:
                    agregar_log(
                        "error",
                        f"Scan falló con {resumen['errores']} errores.",
                    )
                # else: nada que analizar (todas ya evaluadas) → no log
                cargar_lista_negra_panel()
            except Exception as ex:
                agregar_log("error",
                            f"Scan retroactivo falló: {ex}")
            finally:
                _ultimo_scan_baja_ts[0] = _t.time()
                ring_escan_baja.visible = False
                safe_update(ring_escan_baja)

        threading.Thread(target=trabajador, daemon=True).start()

    btn_escanear_bajas = ft.ElevatedButton(
        "Escanear respuestas viejas",
        icon=ft.Icons.SAVED_SEARCH_ROUNDED,
        on_click=_escanear_bajas_retro,
        tooltip=("Re-analiza respuestas ya registradas para detectar "
                  "pedidos de BAJA que no fueron capturados al recibirlos. "
                  "Las que matcheen se agregan automáticamente a esta lista."),
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: C_MORADO,
                     ft.ControlState.HOVERED: C_MORADO_DARK},
            color={ft.ControlState.DEFAULT: C_BLANCO},
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(16, 10, 16, 10),
        ),
    )

    btn_negra_prev = ft.IconButton(
        icon=ft.Icons.ARROW_BACK_IOS_ROUNDED, icon_color=C_MORADO,
        on_click=lambda e: (pagina_negra.__setitem__(0, max(0, pagina_negra[0] - 1)),
                             _render_pagina_negra()),
    )
    btn_negra_next = ft.IconButton(
        icon=ft.Icons.ARROW_FORWARD_IOS_ROUNDED, icon_color=C_MORADO,
        on_click=lambda e: (pagina_negra.__setitem__(0, pagina_negra[0] + 1),
                             _render_pagina_negra()),
    )

    vista_lista_negra = ft.Container(
        padding=ft.Padding(20, 16, 20, 20),
        content=ft.Column(
            spacing=16,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                # ── KPIs arriba ───────────────────────────────────
                ft.Row(
                    spacing=14,
                    controls=[kpi_card_total, kpi_card_auto, kpi_card_manual],
                ),
                # ── Card "Agregar manualmente" — más prominente ───
                ft.Container(
                    bgcolor=C_BLANCO,
                    border_radius=ft.BorderRadius(14, 14, 14, 14),
                    border=borde_all(1, C_BORDE),
                    padding=ft.Padding(20, 18, 20, 18),
                    content=ft.Column(
                        spacing=12,
                        controls=[
                            ft.Row(
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=10,
                                controls=[
                                    ft.Container(
                                        width=36, height=36,
                                        bgcolor=C_MORADO_LIGHT,
                                        border_radius=ft.BorderRadius(10, 10, 10, 10),
                                        alignment=ft.Alignment(0, 0),
                                        content=ft.Icon(
                                            ft.Icons.PERSON_ADD_DISABLED_ROUNDED,
                                            color=C_MORADO, size=20,
                                        ),
                                    ),
                                    ft.Column(
                                        spacing=2,
                                        controls=[
                                            ft.Text("Bloquear un email",
                                                    size=14,
                                                    weight=ft.FontWeight.BOLD,
                                                    color=C_TEXTO_1,
                                                    font_family="Saira"),
                                            ft.Text(
                                                "Agregalo manualmente para "
                                                "saltearlo en todas las campañas.",
                                                size=11, color=C_TEXTO_3,
                                                font_family="Saira"),
                                        ],
                                    ),
                                ],
                            ),
                            ft.Row(spacing=10, controls=[
                                tf_nuevo_email, tf_nuevo_motivo,
                            ]),
                            ft.Row(
                                spacing=10,
                                controls=[
                                    btn_agregar_negra,
                                    ft.Container(expand=True),
                                    btn_escanear_bajas,
                                    ring_escan_baja,
                                    btn_importar_negra,
                                    btn_exportar_negra,
                                ],
                            ),
                        ],
                    ),
                ),
                # ── Toolbar: chips de filtro + buscador ───────────
                ft.Container(
                    bgcolor=C_BLANCO,
                    border_radius=ft.BorderRadius(14, 14, 14, 14),
                    border=borde_all(1, C_BORDE),
                    padding=ft.Padding(16, 12, 16, 12),
                    content=ft.Column(
                        spacing=12,
                        controls=[
                            ft.Row(
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=10,
                                controls=[
                                    ft.Text("Filtrar:", size=12,
                                            color=C_TEXTO_2,
                                            weight=ft.FontWeight.W_500,
                                            font_family="Saira"),
                                    btns_filtro_origen["todos"],
                                    btns_filtro_origen["auto"],
                                    btns_filtro_origen["manual"],
                                ],
                            ),
                            ft.Row(
                                spacing=10,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    tf_buscar_negra,
                                    ft.Text("Mostrar:", size=12,
                                            color=C_TEXTO_3,
                                            font_family="Saira"),
                                    dropdown_tam_pagina,
                                ],
                            ),
                        ],
                    ),
                ),
                # ── Tabla / Empty state ────────────────────────────
                # expand=True sin height fijo para que ocupe TODO el
                # alto disponible (antes estaba limitada a 420px y se
                # veía un cuadradito chico en pantallas grandes).
                contenedor_tabla_negra,
                # ── Paginación ─────────────────────────────────────
                ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=8,
                    controls=[btn_negra_prev, lbl_negra_pagina, btn_negra_next],
                ),
            ],
        ),
    )

    # ==========================================
    # PANEL RECHAZADOS — listado, copiar, depurar
    # ==========================================
    lista_rechazados      = ft.ListView(expand=True, spacing=8,
                                         padding=ft.Padding(8, 8, 8, 8))
    lbl_rechazados_total  = ft.Text("", size=12, color=C_TEXTO_3, font_family="Saira",
                                     no_wrap=True)
    lbl_rechazados_pagina = ft.Text("", size=12, color=C_TEXTO_2, font_family="Saira",
                                     no_wrap=True)
    lbl_rechazados_estado = ft.Text(
        "", size=11, color=C_AZUL, font_family="Saira", italic=True,
        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, no_wrap=True,
    )
    chk_mostrar_depurados = ft.Checkbox(
        label="Ver sólo depurados",
        value=False,
        active_color=C_MORADO,
        label_style=ft.TextStyle(font_family="Saira", size=12, color=C_TEXTO_2),
        tooltip="Activado: muestra SÓLO los rechazados ya depurados.\n"
                "Desactivado: muestra los pendientes de depurar.",
    )
    pagina_rechazados     = [0]
    filtro_rechazados     = [""]   # búsqueda por correo
    TAM_PAGINA_RECH       = 50

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

    # Ring para escaneo forzado IMAP (mailer-daemon + postmaster)
    ring_rechazados_scan = ft.ProgressRing(
        color=C_MORADO, width=18, height=18,
        stroke_width=2.5, visible=False,
    )
    chk_borrar_gmail = ft.Checkbox(
        label="También borrar de Gmail al depurar",
        value=True,
        active_color=C_MORADO,
        label_style=ft.TextStyle(font_family="Saira", size=12, color=C_TEXTO_2),
        tooltip="Mueve el correo de mailer-daemon a la papelera de Gmail "
                "cuando marcás un email como depurado.",
    )

    def _escanear_rebotes_forzado(e=None):
        """Escaneo FORZADO de rebotes en IMAP. Usa el mismo motor que
        'Escanear bandeja' (detectar_respuestas_y_calendly con forzar_full),
        que caza postmaster Y mailer-daemon y carga cada rebote en AMBOS:
        rechazados y lista negra — idempotente (si ya está, no duplica).
        También corre el re-escaneo clásico de mailer-daemon por las dudas.
        Re-carga todo aunque hayas borrado el historial."""
        if ring_rechazados_scan.visible:
            return
        cfg = enviar_correos.cargar_config()
        if not cfg.get("correo") or not cfg.get("password"):
            _flash("Configurá la cuenta antes de escanear.", C_ROJO, 3)
            return
        ring_rechazados_scan.visible = True
        _flash("Escaneando rebotes (bandeja completa, 60 días)...", C_AZUL, 90)
        safe_update(ring_rechazados_scan)

        def trabajador():
            try:
                antes = len(enviar_correos.cargar_rechazados_todos(
                    filtrar_por_contactos=False))
                # Motor principal: detecta postmaster/mailer-daemon y NDRs,
                # carga en rechazados + lista negra (idempotente, forzado).
                enviar_correos.detectar_respuestas_y_calendly(
                    dias=60, forzar_full=True,
                )
                # Complemento: mailer-daemon clásico (aditivo).
                try:
                    enviar_correos.revisar_rebotes_recientes(dias=60)
                except Exception:
                    pass
                despues = len(enviar_correos.cargar_rechazados_todos(
                    filtrar_por_contactos=False))
                nuevos = max(0, despues - antes)
                _flash(f"Escaneo completo. {despues} rechazados en total"
                       + (f" (+{nuevos} nuevos)" if nuevos else "") + ".",
                       C_EXITO, 5)
                agregar_log("info",
                            f"Re-escaneo de rebotes: {despues} en total, "
                            f"{nuevos} nuevos.")
            except Exception as ex:
                _flash(f"Falló: {ex}", C_ROJO, 6)
            finally:
                ring_rechazados_scan.visible = False
                safe_update(ring_rechazados_scan)
                refrescar_rechazados()

        threading.Thread(target=trabajador, daemon=True).start()

    # Lock para serializar refrescar_rechazados — evita duplicación visual
    # cuando dos threads (ej: render inicial + watcher daemon) llaman al
    # mismo tiempo
    _lock_refrescar_rech = threading.Lock()
    # Cache de dedupe: id del objeto crudo + lista deduplicada resultante.
    # Si la referencia del objeto crudo no cambió, reutilizamos el dedupe.
    _rechazados_cache_id     = [None]
    _rechazados_cache_dedupe = [None]

    def refrescar_rechazados():
        if not _lock_refrescar_rech.acquire(blocking=False):
            return  # ya hay otro refresh en curso, evitamos duplicar
        try:
            _refrescar_rechazados_inner()
        finally:
            _lock_refrescar_rech.release()

    def _refrescar_rechazados_inner():
        rechazados   = enviar_correos.cargar_rechazados_todos()
        depurados    = enviar_correos.cargar_depurados()
        mostrar_dep  = chk_mostrar_depurados.value

        # Dedupe defensivo cacheado: el cache invalida cuando la
        # referencia del objeto cambia (cargar_rechazados_todos devuelve
        # la misma instancia mientras el JSON no se modificó). Comparar
        # por `id()` es O(1) y evita rehacer normalización aggresiva
        # de 5000+ emails con `"".join(ch for ch in ...)` cada vez que
        # el usuario cambia de pestaña.
        if _rechazados_cache_id[0] is id(rechazados):
            rechazados = _rechazados_cache_dedupe[0]
        else:
            vistos = set()
            unicos = []
            for r in rechazados:
                em_raw = r.get("email") or ""
                em = "".join(ch for ch in em_raw.lower().strip()
                             if ch.isprintable())
                if em and em not in vistos:
                    vistos.add(em)
                    r_nuevo = dict(r)
                    r_nuevo["email"] = em
                    unicos.append(r_nuevo)
            rechazados = unicos
            _rechazados_cache_id[0]     = id(enviar_correos.cargar_rechazados_todos())
            _rechazados_cache_dedupe[0] = unicos

        # Filtrar primero (más rápido) y después paginar.
        # Lógica del checkbox:
        #   chk OFF (default) → muestra sólo PENDIENTES (no depurados)
        #   chk ON            → muestra sólo DEPURADOS (los ya procesados)
        q = (filtro_rechazados[0] or "").strip().lower()
        items_visibles = []
        for item in rechazados:
            es_dep = item["email"] in depurados
            if mostrar_dep and not es_dep:
                continue
            if (not mostrar_dep) and es_dep:
                continue
            if q and q not in item["email"]:
                continue
            items_visibles.append((item, es_dep))

        total_visibles = len(items_visibles)
        max_pag = max(0, (total_visibles - 1) // TAM_PAGINA_RECH) if total_visibles else 0
        if pagina_rechazados[0] > max_pag:
            pagina_rechazados[0] = max_pag
        if pagina_rechazados[0] < 0:
            pagina_rechazados[0] = 0
        ini = pagina_rechazados[0] * TAM_PAGINA_RECH
        fin = min(ini + TAM_PAGINA_RECH, total_visibles)

        nuevos_controles = []
        visibles = total_visibles  # contador para el header

        for item, es_dep in items_visibles[ini:fin]:
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
                    # Restaurar: sacar de depurados + mover correos de
                    # papelera a INBOX (si todavía están)
                    enviar_correos.desmarcar_depurado(correo)
                    _flash(f"Restaurando {correo}...", C_AZUL, 3)
                    refrescar_rechazados()
                    if bool(chk_borrar_gmail.value):
                        def _bg_restore():
                            try:
                                restaurados = enviar_correos.restaurar_correo_rebote_gmail(correo)
                                if restaurados:
                                    _flash(
                                        f"↺ {correo}: {restaurados} correo"
                                        f"{'s' if restaurados != 1 else ''} "
                                        "restaurado a INBOX desde la papelera.",
                                        C_AZUL, 4,
                                    )
                                # Si 0, el usuario ya los borró definitivamente —
                                # no podemos restaurar. Silencioso.
                            except Exception:
                                pass
                        threading.Thread(target=_bg_restore, daemon=True).start()
                    return

                # 1) Marcar depurado en JSON + refrescar UI AL INSTANTE
                #    (sin esperar el IMAP delete que tarda 5-10s).
                enviar_correos.marcar_depurado(correo)
                _flash(f"✓ {correo} depurado", C_EXITO, 3)
                refrescar_rechazados()

                # 2) Si está activado, encolar el borrado de Gmail.
                #    La cola usa UNA conexión IMAP para borrar varios
                #    rebotes seguidos → mucho más rápido que abrir IMAP
                #    cada vez (que tardaba ~5s por correo).
                if bool(chk_borrar_gmail.value):
                    def _on_done(em, movidos):
                        if movidos:
                            _flash(
                                f"🗑 {em}: {movidos} correo"
                                f"{'s' if movidos != 1 else ''} "
                                "movido a la papelera de Gmail.",
                                C_EXITO, 3,
                            )
                            try:
                                agregar_log(
                                    "info",
                                    f"Borrado de Gmail completado para {em} "
                                    f"({movidos} mensajes a papelera).",
                                )
                            except Exception:
                                pass

                    enviar_correos.encolar_borrado_gmail(correo, _on_done)

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
            # Empty state pulido — estilo Lista negra. Cambia el copy
            # según si NO hay rechazados todavía vs hay pero todos
            # están del otro lado del toggle (depurados/pendientes).
            if rechazados:
                icono_empty = ft.Icons.FILTER_ALT_OFF_ROUNDED
                titulo_empty = "Sin coincidencias con el filtro actual"
                msg_empty = (
                    "Tenés rechazados registrados pero ninguno coincide "
                    "con el toggle activo. Probá cambiar 'Ver sólo "
                    "depurados' para alternar entre pendientes y "
                    "depurados."
                )
            else:
                icono_empty = ft.Icons.MARK_EMAIL_READ_ROUNDED
                titulo_empty = "No hay rebotes registrados"
                msg_empty = (
                    "Cuando una campaña envíe correos a direcciones "
                    "inválidas, los rebotes que devuelva mailer-daemon "
                    "(Gmail) o postmaster (Outlook/Exchange) van a "
                    "aparecer acá automáticamente, junto con un botón "
                    "para depurarlos."
                )
            nuevos_controles.append(
                ft.Container(
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                    padding=ft.Padding(40, 60, 40, 60),
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=14,
                        controls=[
                            ft.Container(
                                width=72, height=72,
                                bgcolor=C_MORADO_LIGHT,
                                border_radius=ft.BorderRadius(36, 36, 36, 36),
                                alignment=ft.Alignment(0, 0),
                                content=ft.Icon(
                                    icono_empty,
                                    color=C_MORADO, size=36,
                                ),
                            ),
                            ft.Text(
                                titulo_empty,
                                size=18, weight=ft.FontWeight.BOLD,
                                color=C_TEXTO_1, font_family="Saira",
                            ),
                            ft.Text(
                                msg_empty,
                                size=12, color=C_TEXTO_3,
                                font_family="Saira",
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ],
                    ),
                )
            )

        lista_rechazados.controls = nuevos_controles

        total_dep    = sum(1 for r in rechazados if r["email"] in depurados)
        total_pend   = len(rechazados) - total_dep
        modo_label   = "depurados" if mostrar_dep else "pendientes"
        partes = [
            f"{visibles} {modo_label}",
            f"{total_pend} pendientes" if not mostrar_dep else f"{total_pend} pendientes",
            f"{total_dep} depurados",
            f"{len(rechazados)} totales",
        ]
        # Quitar el duplicado del modo_label que coincide con la línea siguiente
        partes_unicas = []
        vistos_lbl = set()
        for p in partes:
            if p not in vistos_lbl:
                vistos_lbl.add(p)
                partes_unicas.append(p)
        lbl_rechazados_total.value = "  •  ".join(partes_unicas)

        # Label de paginación
        if total_visibles == 0:
            lbl_rechazados_pagina.value = ""
        else:
            lbl_rechazados_pagina.value = (
                f"Mostrando {ini + 1}–{fin} de {total_visibles}  •  "
                f"Página {pagina_rechazados[0] + 1} / {max_pag + 1}"
            )
        safe_update()

    def _ir_pagina_rech(delta):
        pagina_rechazados[0] += delta
        refrescar_rechazados()

    def _on_mostrar_dep_change(e):
        pagina_rechazados[0] = 0
        refrescar_rechazados()
    chk_mostrar_depurados.on_change = _on_mostrar_dep_change

    btn_rech_prev = ft.IconButton(
        icon=ft.Icons.CHEVRON_LEFT_ROUNDED,
        icon_color=C_MORADO,
        on_click=lambda e: _ir_pagina_rech(-1),
        tooltip="Página anterior",
    )
    btn_rech_next = ft.IconButton(
        icon=ft.Icons.CHEVRON_RIGHT_ROUNDED,
        icon_color=C_MORADO,
        on_click=lambda e: _ir_pagina_rech(1),
        tooltip="Página siguiente",
    )

    tf_buscar_rech = ft.TextField(
        hint_text="Buscar correo específico...",
        prefix_icon=ft.Icons.SEARCH_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
        on_change=lambda e: (filtro_rechazados.__setitem__(0, e.control.value),
                             pagina_rechazados.__setitem__(0, 0),
                             refrescar_rechazados()),
    )

    vista_rechazados = ft.Column(
        expand=True,
        spacing=16,
        controls=[
            ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.REPORT_GMAILERRORRED_ROUNDED, color=C_ROJO, size=22),
                    ft.Text("Rechazados", size=20, weight=ft.FontWeight.BOLD,
                            color=C_TEXTO_1, font_family="Saira", no_wrap=True),
                    ring_rechazados_scan,
                    ft.Container(
                        expand=True,
                        content=lbl_rechazados_estado,
                        alignment=ft.Alignment(0, 0),
                    ),
                    lbl_rechazados_total,
                    ft.OutlinedButton(
                        "Recargar lista",
                        icon=ft.Icons.LIST_ALT_ROUNDED,
                        on_click=lambda e: refrescar_rechazados(),
                        style=ft.ButtonStyle(
                            color={ft.ControlState.DEFAULT: C_MORADO},
                            side={ft.ControlState.DEFAULT:
                                  ft.BorderSide(1.2, C_MORADO)},
                            shape=ft.RoundedRectangleBorder(radius=8),
                            padding=ft.Padding(14, 12, 14, 12),
                        ),
                    ),
                    ft.ElevatedButton(
                        "Re-escanear IMAP",
                        icon=ft.Icons.REFRESH_ROUNDED,
                        on_click=_escanear_rebotes_forzado,
                        tooltip="Vuelve a buscar rebotes (mailer-daemon + "
                                "postmaster) en la bandeja. Si el cliente "
                                "eliminó manualmente correos, se "
                                "restablecen las estadísticas.",
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
                controls=[tf_buscar_rech],
            ),
            ft.Row(
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    chk_mostrar_depurados,
                    chk_borrar_gmail,
                    ft.Container(expand=True),
                    btn_rech_prev,
                    lbl_rechazados_pagina,
                    btn_rech_next,
                ],
            ),
            ft.Text(
                "Marcá como depurado los que ya pasaste a tu base externa. "
                "Si activás 'Borrar de Gmail' también se elimina el correo "
                "de mailer-daemon.",
                size=11, color=C_TEXTO_3, italic=True, font_family="Saira",
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

    # Placeholder mientras no se eligió un día del historial.
    # Se reemplaza al hacer click en cualquier tarjeta de día.
    _hist_placeholder = ft.Container(
        expand=True,
        alignment=ft.Alignment(0, 0),
        padding=ft.Padding(40, 60, 40, 60),
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
            controls=[
                ft.Container(
                    width=64, height=64,
                    bgcolor=C_MORADO_LIGHT,
                    border_radius=ft.BorderRadius(32, 32, 32, 32),
                    alignment=ft.Alignment(0, 0),
                    content=ft.Icon(
                        ft.Icons.TODAY_ROUNDED,
                        color=C_MORADO, size=30,
                    ),
                ),
                ft.Text(
                    "Elegí un día de la lista",
                    size=15, weight=ft.FontWeight.BOLD,
                    color=C_TEXTO_1, font_family="Saira",
                ),
                ft.Text(
                    "Tocá una tarjeta del panel izquierdo para ver "
                    "el detalle de eventos, envíos y rebotes de ese día.",
                    size=11, color=C_TEXTO_3,
                    font_family="Saira",
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
        ),
    )
    lista_hist_eventos.controls.append(_hist_placeholder)

    # Cache del último día renderizado — si el usuario hace click en
    # el mismo día dos veces o se re-llama por refresh interno, no
    # reconstruimos todos los widgets de eventos (puede ser pesado
    # con 500+ eventos por día).
    _ultimo_dia_renderizado = [None]

    # Cap defensivo: por más que el JSON tenga 5000 eventos en un día,
    # mostramos sólo los 200 más recientes. Render de 200 widgets
    # complejos = ~80ms; render de 5000 = 2-3s. Si el usuario necesita
    # eventos viejos, el JSON sigue completo en disco.
    MAX_EVENTOS_HISTORIAL_RENDER = 200

    def cargar_dia_historial(fecha_str, forzar=False):
        if not forzar and _ultimo_dia_renderizado[0] == fecha_str:
            return  # ya está renderizado este día
        data = enviar_correos.cargar_historial_dia(fecha_str)
        lbl_hist_fecha.value = f"Historial del {fecha_str}"
        env = data.get("enviados", 0)
        reb = data.get("rebotes", 0)
        lbl_hist_stats.value = f"Enviados: {env}  •  Rechazados: {reb}"
        lista_hist_eventos.controls.clear()
        eventos = data.get("eventos", [])
        if not eventos:
            lista_hist_eventos.controls.append(
                ft.Container(
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                    padding=ft.Padding(40, 40, 40, 40),
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10,
                        controls=[
                            ft.Icon(ft.Icons.EVENT_BUSY_ROUNDED,
                                    color=C_TEXTO_3, size=40),
                            ft.Text(
                                "Este día no tiene eventos registrados.",
                                size=13, color=C_TEXTO_2,
                                font_family="Saira",
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ],
                    ),
                )
            )
            _ultimo_dia_renderizado[0] = fecha_str
            safe_update(lista_hist_eventos, lbl_hist_fecha, lbl_hist_stats)
            return

        # Capamos a los últimos 200 eventos visibles. Para días con más,
        # mostramos un aviso al final.
        eventos_render = list(reversed(eventos))[:MAX_EVENTOS_HISTORIAL_RENDER]
        total_eventos  = len(eventos)
        truncado = total_eventos > MAX_EVENTOS_HISTORIAL_RENDER

        for ev in eventos_render:
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

        if truncado:
            # Aviso: hay más eventos en el JSON pero no los rendereamos
            # para mantener la UI fluida. El usuario puede abrir el JSON
            # directo si necesita los más antiguos.
            ocultos = total_eventos - MAX_EVENTOS_HISTORIAL_RENDER
            lista_hist_eventos.controls.append(
                ft.Container(
                    padding=ft.Padding(12, 14, 12, 14),
                    alignment=ft.Alignment(0, 0),
                    content=ft.Text(
                        f"+ {ocultos} evento(s) más antiguos no renderizados "
                        f"(visibles en el JSON del día).",
                        size=11, color=C_TEXTO_3, italic=True,
                        font_family="Saira",
                        text_align=ft.TextAlign.CENTER,
                    ),
                )
            )

        _ultimo_dia_renderizado[0] = fecha_str
        # safe_update específico: sólo los 3 controles del panel detalle,
        # no toda la página. Esto fue lo que generaba el lag al abrir
        # un día con 500+ eventos.
        safe_update(lista_hist_eventos, lbl_hist_fecha, lbl_hist_stats)

    def refrescar_dias_historial():
        lista_historial_dias.controls.clear()
        dias = enviar_correos.listar_dias_historial()
        if not dias:
            # Empty state pulido — estilo Lista negra/Respuestas/Rechazados.
            lista_historial_dias.controls.append(
                ft.Container(
                    padding=ft.Padding(20, 50, 20, 50),
                    alignment=ft.Alignment(0, 0),
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=12,
                        controls=[
                            ft.Container(
                                width=64, height=64,
                                bgcolor=C_MORADO_LIGHT,
                                border_radius=ft.BorderRadius(32, 32, 32, 32),
                                alignment=ft.Alignment(0, 0),
                                content=ft.Icon(
                                    ft.Icons.HISTORY_TOGGLE_OFF_ROUNDED,
                                    color=C_MORADO, size=30,
                                ),
                            ),
                            ft.Text(
                                "Sin historial todavía",
                                size=15, weight=ft.FontWeight.BOLD,
                                color=C_TEXTO_1, font_family="Saira",
                                text_align=ft.TextAlign.CENTER,
                            ),
                            ft.Text(
                                "Cuando inicies tu primera campaña, cada día "
                                "que envíes correos va a quedar registrado "
                                "acá con el detalle de eventos.",
                                size=11, color=C_TEXTO_3,
                                font_family="Saira",
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ],
                    ),
                )
            )
        # Tarjeta horizontal con fecha legible arriba y badges abajo
        for d in dias:
            data = enviar_correos.cargar_historial_dia(d)
            env  = data.get("enviados", 0)
            reb  = data.get("rebotes", 0)
            dd   = d
            # Fecha amigable: 2026-05-03 → "03 May 2026"
            fecha_amigable = dd
            try:
                _meses = ["Ene","Feb","Mar","Abr","May","Jun",
                          "Jul","Ago","Sep","Oct","Nov","Dic"]
                _y, _m, _da = dd.split("-")
                fecha_amigable = f"{_da} {_meses[int(_m)-1]} {_y}"
            except Exception:
                pass

            lista_historial_dias.controls.append(
                ft.Container(
                    bgcolor=C_BLANCO,
                    border_radius=ft.BorderRadius(12, 12, 12, 12),
                    border=borde_all(1, C_BORDE),
                    padding=ft.Padding(14, 12, 14, 12),
                    on_click=lambda e, fecha=dd: cargar_dia_historial(fecha),
                    ink=True,
                    content=ft.Column(
                        spacing=10,
                        controls=[
                            ft.Row(
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=8,
                                controls=[
                                    ft.Icon(ft.Icons.CALENDAR_TODAY_ROUNDED,
                                            color=C_MORADO, size=16),
                                    ft.Text(fecha_amigable, size=14,
                                            weight=ft.FontWeight.BOLD,
                                            color=C_TEXTO_1, font_family="Saira",
                                            no_wrap=True),
                                ],
                            ),
                            ft.Row(
                                spacing=6,
                                controls=[
                                    ft.Container(
                                        bgcolor=C_MORADO_LIGHT,
                                        border_radius=ft.BorderRadius(6, 6, 6, 6),
                                        padding=ft.Padding(10, 3, 10, 3),
                                        content=ft.Text(
                                            f"{env} env.", size=11,
                                            color=C_MORADO,
                                            weight=ft.FontWeight.W_600,
                                            font_family="Saira",
                                        ),
                                    ),
                                    ft.Container(
                                        bgcolor=C_ROJO_LIGHT,
                                        border_radius=ft.BorderRadius(6, 6, 6, 6),
                                        padding=ft.Padding(10, 3, 10, 3),
                                        content=ft.Text(
                                            f"{reb} rech.", size=11,
                                            color=C_ROJO,
                                            weight=ft.FontWeight.W_600,
                                            font_family="Saira",
                                        ),
                                    ),
                                ],
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
                        width=290,
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
    filtro_auto_resp      = ["reales"]                      # todas | reales | auto (default: solo reales)
    filtro_asunto_resp    = [""]                            # texto libre
    solo_campana_resp     = [True]                          # sólo correos cuyo asunto matchee la campaña
    mostrar_ignorados     = [False]                         # checkbox "Mostrar ignorados"
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
                # Defensa en UI: nunca mostrar BAJA ni rebotes aunque hayan
                # quedado en el archivo (el detector los limpia, pero esto
                # garantiza que no se cuelen entre limpieza y limpieza).
                if r.get("es_baja"):
                    continue
                if enviar_correos._es_remitente_rebote(r.get("from")):
                    continue
                items.append(("respuesta", r))
        if filtro_respuestas[0] in ("todas", "calendly"):
            for c in calendly:
                items.append(("calendly", c))

        # Filtro Reales vs Automáticas (sólo aplica a respuestas). Una
        # respuesta es "automática" si su asunto es de fuera-de-oficina /
        # auto-reply. Con "reales" mostramos sólo respuestas de verdad;
        # con "auto", sólo las automáticas. Las reuniones no entran en
        # este eje (se ven con el filtro Reuniones).
        def _es_auto_item(it):
            return bool(it.get("es_auto")) or enviar_correos.parece_auto_reply(
                it.get("subject", "")
            )
        if filtro_auto_resp[0] == "reales":
            items = [(t, it) for (t, it) in items
                     if t == "respuesta" and not _es_auto_item(it)]
        elif filtro_auto_resp[0] == "auto":
            items = [(t, it) for (t, it) in items
                     if t == "respuesta" and _es_auto_item(it)]

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

        # Filtro de ignorados con semántica EXCLUSIVA:
        #   - Checkbox APAGADO (default) → mostrar SÓLO los NO-ignorados.
        #   - Checkbox PRENDIDO          → mostrar SÓLO los ignorados.
        # Antes era "incluir/excluir" (con checkbox ON veías todos los
        # normales + los ignorados mezclados) — confuso. El usuario pidió
        # comportamiento de "vista exclusiva" como un toggle de tab.
        ignorados_set = enviar_correos.cargar_ignorados()
        agrupados = []
        contado_ignorados = 0
        ver_solo_ignorados = mostrar_ignorados[0]
        for g in grupos.values():
            es_ignorado = g["clave"] in ignorados_set
            if es_ignorado:
                contado_ignorados += 1
                if not ver_solo_ignorados:
                    continue   # checkbox OFF: ocultar ignorados
            else:
                if ver_solo_ignorados:
                    continue   # checkbox ON: ocultar los NO-ignorados
            g["ignorado"] = es_ignorado
            agrupados.append(g)

        agrupados.sort(key=lambda g: g["ultimo"].get("date", ""), reverse=True)
        # Devolvemos también el conteo de ignorados para el header
        return agrupados, len(respuestas), len(calendly), contado_ignorados

    def _render_respuestas():
        grupos, total_resp, total_cal, total_ignorados = _items_filtrados()
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
            es_ignorado = grupo.get("ignorado", False)

            # ¿El hilo tiene mensajes nuevos sin que el usuario los abrió?
            hay_nuevos = any(u not in vistos_set for u in uids) if uids else (
                clave not in vistos_set
            )
            # Detectar respuesta automática (sólo etiqueta sugerida)
            sugerir_ignorar = enviar_correos.parece_auto_reply(
                item.get("subject", "")
            ) and not es_ignorado

            if tipo == "calendly":
                # Diferenciamos visualmente Calendly vs Cal.com con icono
                # y label, manteniendo el mismo estilo verde del grupo
                # "REUNIÓN" para que el usuario las identifique de un vistazo.
                plataforma_reu = (item.get("plataforma") or "calendly").lower()
                if plataforma_reu == "cal_com":
                    icono = ft.Icons.CALENDAR_MONTH_ROUNDED
                    etiq  = "CAL.COM"
                else:
                    icono = ft.Icons.EVENT_AVAILABLE_ROUNDED
                    etiq  = "CALENDLY"
                color       = C_VERDE_DARK
                bg          = C_VERDE_LIGHT
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

            def _toggle_ignorar(e, clave_loc=clave, ya=es_ignorado,
                                  principal_loc=accion_email):
                if ya:
                    enviar_correos.desmarcar_ignorado(clave_loc)
                    _flash_resp(f"Restaurado: {principal_loc}", C_AZUL, 3)
                else:
                    enviar_correos.marcar_ignorado(clave_loc)
                    _flash_resp(f"Ignorado: {principal_loc}", C_NARANJA, 3)
                _render_respuestas()

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

            # Badge "AUTO" si parece respuesta automática
            badge_auto = []
            if sugerir_ignorar:
                badge_auto.append(
                    ft.Container(
                        bgcolor=C_NARANJA_LIGHT,
                        border_radius=ft.BorderRadius(4, 4, 4, 4),
                        padding=ft.Padding(6, 1, 6, 1),
                        content=ft.Text("AUTO", size=9, color=C_NARANJA,
                                        weight=ft.FontWeight.BOLD,
                                        font_family="Saira"),
                        tooltip="Parece respuesta automática "
                                "(out-of-office / unsubscribe / etc.)",
                    )
                )

            # Badge "IGNORADO" si está ignorado
            badge_ignorado = []
            if es_ignorado:
                badge_ignorado.append(
                    ft.Container(
                        bgcolor=C_TEXTO_3 + "33",
                        border_radius=ft.BorderRadius(4, 4, 4, 4),
                        padding=ft.Padding(6, 1, 6, 1),
                        content=ft.Text("IGNORADO", size=9, color=C_TEXTO_3,
                                        weight=ft.FontWeight.BOLD,
                                        font_family="Saira"),
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
                                            *badge_auto,
                                            *badge_ignorado,
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
                                icon=(ft.Icons.VISIBILITY_ROUNDED if es_ignorado
                                       else ft.Icons.VISIBILITY_OFF_ROUNDED),
                                icon_color=(C_AZUL if es_ignorado
                                             else C_TEXTO_3),
                                tooltip=("Restaurar (volver a mostrar)"
                                          if es_ignorado
                                          else "Ignorar este hilo"),
                                on_click=_toggle_ignorar,
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
            # Empty state: distinguimos tres escenarios distintos para
            # darle al usuario un copy útil según en qué situación está.
            hay_datos_total = (total_resp + total_cal) > 0
            if hay_datos_total:
                # Hay datos pero el filtro/checkbox los oculta a todos
                icono_e  = ft.Icons.FILTER_ALT_OFF_ROUNDED
                titulo_e = "Sin coincidencias con el filtro actual"
                msg_e = (
                    "Tenés respuestas registradas pero ninguna pasa los "
                    "filtros activos. Probá destildar \"Solo correos de "
                    "esta campaña\" para ver todas las respuestas, o "
                    "limpiá el buscador."
                )
            else:
                # No hay nada — primera vez o nada que escanear todavía
                icono_e  = ft.Icons.INBOX_ROUNDED
                titulo_e = "Sin respuestas todavía"
                msg_e = (
                    "Cuando un contacto de tu campaña responda a uno "
                    "de los correos, va a aparecer acá automáticamente. "
                    "También vas a ver las confirmaciones de reuniones "
                    "de Calendly o Cal.com. Apretá \"Escanear bandeja\" "
                    "para hacer un escaneo manual."
                )
            lista_respuestas.controls.append(
                ft.Container(
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                    padding=ft.Padding(40, 60, 40, 60),
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=14,
                        controls=[
                            ft.Container(
                                width=72, height=72,
                                bgcolor=C_MORADO_LIGHT,
                                border_radius=ft.BorderRadius(36, 36, 36, 36),
                                alignment=ft.Alignment(0, 0),
                                content=ft.Icon(
                                    icono_e, color=C_MORADO, size=36,
                                ),
                            ),
                            ft.Text(
                                titulo_e,
                                size=18, weight=ft.FontWeight.BOLD,
                                color=C_TEXTO_1, font_family="Saira",
                            ),
                            ft.Text(
                                msg_e,
                                size=12, color=C_TEXTO_3,
                                font_family="Saira",
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ],
                    ),
                )
            )

        partes_total = [
            f"{total_resp} respuestas",
            f"{total_cal} reuniones",
            f"{total_visibles} hilos",
        ]
        if total_ignorados:
            partes_total.append(f"{total_ignorados} ignorados")
        lbl_resp_total.value = "  •  ".join(partes_total)
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
        _flash_resp("Escaneando bandeja (full rescan)...", C_AZUL, 60)

        def trabajador():
            try:
                # Comparar antes/después para reportar cuántas respuestas
                # nuevas trajo el escaneo manual.
                antes  = enviar_correos.cargar_respuestas()
                n_antes = (len(antes.get("respuestas", []))
                            + len(antes.get("calendly", [])))
                # forzar_full=True ignora el `_last_uid` cacheado y
                # rescanea TODO el rango. Es lo que el usuario espera
                # cuando aprieta "Escanear bandeja" — no un escaneo
                # incremental, sino uno completo que garantice que
                # encuentre todo lo que hay.
                enviar_correos.detectar_respuestas_y_calendly(
                    dias=60, forzar_full=True,
                )
                despues = enviar_correos.cargar_respuestas()
                n_desp  = (len(despues.get("respuestas", []))
                            + len(despues.get("calendly", [])))
                nuevas  = max(0, n_desp - n_antes)
                if nuevas > 0:
                    _flash_resp(
                        f"Escaneo completo · {nuevas} respuesta(s) nueva(s)",
                        C_EXITO, 4,
                    )
                else:
                    _flash_resp("Escaneo completo · sin novedades",
                                 C_AZUL, 3)
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

    # ── Filtro Reales vs Automáticas (respuestas de verdad vs fuera-de-
    #    oficina/auto-reply). Eje independiente del filtro Todas/Respuestas/
    #    Reuniones. Color azul para diferenciarlo. ──
    def _set_filtro_auto_resp(valor):
        filtro_auto_resp[0] = valor
        pagina_resp[0]      = 0
        for k, b in btns_filtro_auto.items():
            activo = (k == valor)
            b.style = ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: C_AZUL if activo else C_BLANCO},
                color={ft.ControlState.DEFAULT: C_BLANCO if activo else C_AZUL},
                side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, C_AZUL)},
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.Padding(12, 8, 12, 8),
            )
        _render_respuestas()

    btns_filtro_auto = {
        "todas":  ft.ElevatedButton(
            "Todas", on_click=lambda e: _set_filtro_auto_resp("todas")),
        "reales": ft.ElevatedButton(
            "Reales", icon=ft.Icons.PERSON_ROUNDED,
            on_click=lambda e: _set_filtro_auto_resp("reales")),
        "auto":   ft.ElevatedButton(
            "Automáticas", icon=ft.Icons.SMART_TOY_ROUNDED,
            on_click=lambda e: _set_filtro_auto_resp("auto")),
    }
    for k, b in btns_filtro_auto.items():
        activo = (k == filtro_auto_resp[0])
        b.style = ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: C_AZUL if activo else C_BLANCO},
            color={ft.ControlState.DEFAULT: C_BLANCO if activo else C_AZUL},
            side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, C_AZUL)},
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
    chk_mostrar_ignorados = ft.Checkbox(
        label="Mostrar ignorados",
        value=False,
        active_color=C_MORADO,
        label_style=ft.TextStyle(font_family="Saira", size=12, color=C_TEXTO_2),
        on_change=lambda e: (mostrar_ignorados.__setitem__(0, bool(e.control.value)),
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
                    chk_mostrar_ignorados,
                ],
            ),
            ft.Row(
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Text("Tipo de respuesta:", size=12, color=C_TEXTO_3,
                            font_family="Saira"),
                    btns_filtro_auto["todas"],
                    btns_filtro_auto["reales"],
                    btns_filtro_auto["auto"],
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
                    # `fit="fitWidth"` => la imagen siempre llena el ancho
                    # del contenedor manteniendo aspect ratio (se ve igual
                    # en monitores de cualquier resolución). El alto se
                    # ajusta automáticamente al contenido.
                    img_render = ft.Image(
                        src="",
                        fit="fitWidth",
                        visible=False,
                        expand=False,
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

                    # Container que se EXPANDE al ancho disponible. La
                    # imagen adentro usa `fit="fitWidth"` y queda escalada
                    # al ancho real, sin importar la resolución de la
                    # pantalla del usuario.
                    contenedor_img = ft.Container(
                        expand=True,
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

        # Threading headers + Responder a todos
        in_reply_to = ""
        references  = ""
        cc_lista    = []
        if hilo_mensajes[0]:
            ultimo = hilo_mensajes[0][-1]
            in_reply_to = ultimo.get("message_id", "")
            ref_acum    = ultimo.get("references", "")
            references  = (ref_acum + " " + in_reply_to).strip() if ref_acum else in_reply_to

            # "Responder a todos" REAL: recolectamos TODOS los emails que
            # aparecieron en CUALQUIER mensaje del hilo (To + Cc + From),
            # excluyendo nuestro propio correo y el destinatario principal.
            # Esto asegura que si el cliente metió a alguien en copia en
            # cualquier punto del hilo, lo seguimos incluyendo.
            mi_correo   = (enviar_correos.MI_CORREO() or "").lower()
            destino_low = destino.lower()
            ya_incluidos = {mi_correo, destino_low}

            for m in hilo_mensajes[0]:
                # En cada mensaje, juntar To + Cc. Si es entrante también
                # incluir el From (porque en otros mensajes del hilo el
                # remitente original puede haber sido distinto).
                campos = [m.get("to", ""), m.get("cc", "")]
                if m.get("direccion") == "entrante":
                    # NO incluimos From de entrantes en CC porque ése es
                    # el remitente principal — ya está en el TO.
                    pass
                texto_emails = " ".join(campos)
                for em in re.findall(
                    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
                    texto_emails,
                ):
                    em_low = em.lower()
                    if em_low in ya_incluidos:
                        continue
                    ya_incluidos.add(em_low)
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
    # ── Auto-envío programado ──
    chk_auto_envio = ft.Checkbox(
        label="Enviar solo cada día a esta hora (hasta terminar toda la base)",
        value=bool(cfg_actual.get("auto_envio_activo", False)),
        active_color=C_MORADO,
        label_style=ft.TextStyle(font_family="Saira", size=12, color=C_TEXTO_2),
    )
    tf_auto_envio_hora = ft.TextField(
        label="Hora de inicio (HH:MM)",
        value=str(cfg_actual.get("auto_envio_hora", "09:00")),
        hint_text="09:00",
        prefix_icon=ft.Icons.SCHEDULE_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        width=200,
    )
    tf_correos_copia = ft.TextField(
        label="Correos en copia (CC) — opcional",
        value=cfg_actual.get("correos_copia", ""),
        hint_text="ventas@empresa.com, jefe@empresa.com",
        prefix_icon=ft.Icons.GROUP_ADD_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
    )
    tf_url_calendly = ft.TextField(
        label="URL Calendly",
        value=cfg_actual.get("url_calendly", ""),
        hint_text="https://calendly.com/tu-usuario/30min",
        prefix_icon=ft.Icons.EVENT_AVAILABLE_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
    )
    tf_url_cal_com = ft.TextField(
        label="URL Cal.com",
        value=cfg_actual.get("url_cal_com", ""),
        hint_text="https://cal.com/tu-usuario/15min",
        prefix_icon=ft.Icons.CALENDAR_MONTH_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
    )

    # ── Toggle de plataforma activa (Calendly vs Cal.com) ──
    plataforma_actual = [cfg_actual.get("plataforma_reunion", "calendly")]
    btns_plataforma = {}

    def _refrescar_botones_plataforma():
        for k, b in btns_plataforma.items():
            activo = (k == plataforma_actual[0])
            b.style = ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: C_MORADO if activo else C_BLANCO},
                color={ft.ControlState.DEFAULT: C_BLANCO if activo else C_MORADO},
                side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, C_MORADO)},
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.Padding(14, 8, 14, 8),
            )
        try:
            for b in btns_plataforma.values():
                b.update()
        except Exception:
            pass

    def _set_plataforma(p):
        plataforma_actual[0] = p
        cfg_p = enviar_correos.cargar_config()
        cfg_p["plataforma_reunion"] = p
        enviar_correos.guardar_config(cfg_p)
        _refrescar_botones_plataforma()

    btns_plataforma["calendly"] = ft.ElevatedButton(
        "Calendly", icon=ft.Icons.EVENT_AVAILABLE_ROUNDED,
        on_click=lambda e: _set_plataforma("calendly"),
    )
    btns_plataforma["cal_com"] = ft.ElevatedButton(
        "Cal.com", icon=ft.Icons.CALENDAR_MONTH_ROUNDED,
        on_click=lambda e: _set_plataforma("cal_com"),
    )
    _refrescar_botones_plataforma()

    tf_url_whatsapp = ft.TextField(
        label="URL del botón WhatsApp",
        value=cfg_actual.get("url_whatsapp", ""),
        hint_text="https://wa.me/541112345678?text=Hola",
        prefix_icon=ft.Icons.CHAT_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
    )
    # ── Datos de la empresa (se muestran en el correo de campaña) ──
    tf_empresa_nombre = ft.TextField(
        label="Nombre de la empresa",
        value=cfg_actual.get("empresa_nombre", ""),
        hint_text="Intellihelp",
        prefix_icon=ft.Icons.BUSINESS_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
    )
    tf_empresa_web = ft.TextField(
        label="Sitio web",
        value=cfg_actual.get("empresa_web", ""),
        hint_text="intellihelp.tech",
        prefix_icon=ft.Icons.LANGUAGE_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
    )
    tf_empresa_telefono = ft.TextField(
        label="Teléfono fijo",
        value=cfg_actual.get("empresa_telefono", ""),
        hint_text="+54 11 7700-6868",
        prefix_icon=ft.Icons.CALL_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
    )
    tf_empresa_email = ft.TextField(
        label="Email de contacto",
        value=cfg_actual.get("empresa_email", ""),
        hint_text="info@intellihelp.tech",
        prefix_icon=ft.Icons.ALTERNATE_EMAIL_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
    )
    tf_empresa_whatsapp = ft.TextField(
        label="WhatsApp (número visible)",
        value=cfg_actual.get("empresa_whatsapp", ""),
        hint_text="+54 9 11 5027-4827",
        prefix_icon=ft.Icons.CHAT_ROUNDED,
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
                path = _dialogo_archivo_nativo(
                    save=False,
                    title="Seleccioná tu firma",
                    filtros=[
                        ("Imágenes", "*.png *.jpg *.jpeg *.gif *.webp *.bmp"),
                        ("Todos los archivos", "*.*"),
                    ],
                )
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

    # ── Formato del correo de campaña: Texto plano vs HTML ──
    modo_correo_actual = [cfg_actual.get("modo_correo", "texto")]

    def _refrescar_botones_modo():
        for k, b in btns_modo_correo.items():
            activo = (k == modo_correo_actual[0])
            b.style = ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: C_MORADO if activo else C_BLANCO},
                color={ft.ControlState.DEFAULT: C_BLANCO if activo else C_MORADO},
                side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, C_MORADO)},
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.Padding(14, 8, 14, 8),
            )
        try:
            for b in btns_modo_correo.values():
                b.update()
        except Exception:
            pass

    def _set_modo_correo(m):
        modo_correo_actual[0] = m
        cfg_p = enviar_correos.cargar_config()
        cfg_p["modo_correo"] = m
        enviar_correos.guardar_config(cfg_p)
        _refrescar_botones_modo()

    btns_modo_correo = {
        "texto": ft.ElevatedButton("Texto plano (personal)",
                                   icon=ft.Icons.TEXT_SNIPPET_ROUNDED,
                                   on_click=lambda e: _set_modo_correo("texto")),
        "html":  ft.ElevatedButton("HTML (diseño profesional)",
                                   icon=ft.Icons.BRUSH_ROUNDED,
                                   on_click=lambda e: _set_modo_correo("html")),
    }

    tf_texto_asunto = ft.TextField(
        label="Asunto",
        value=cfg_actual.get("texto_asunto",
                             enviar_correos.TEXTO_ASUNTO_DEFAULT),
        prefix_icon=ft.Icons.SUBJECT_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
    )
    tf_texto_cuerpo = ft.TextField(
        label="Mensaje (usá @nombre para el nombre del contacto)",
        value=cfg_actual.get("texto_cuerpo",
                             enviar_correos.TEXTO_CUERPO_DEFAULT),
        multiline=True,
        min_lines=8,
        max_lines=16,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
    )

    # ── Logo personalizado del cliente ───────────────────────────
    # Se muestra en el sidebar y se incrusta en cada correo enviado
    # (reemplaza al logo embebido del bundle).
    logo_personalizado_actual = [cfg_actual.get("logo_personalizado", "")]
    img_logo_preview = ft.Image(
        src=logo_personalizado_actual[0] if (
            logo_personalizado_actual[0]
            and os.path.exists(logo_personalizado_actual[0])
        ) else "",
        fit="contain",
        width=240,
        height=80,
        visible=bool(logo_personalizado_actual[0]
                     and os.path.exists(logo_personalizado_actual[0])),
    )
    lbl_logo_path = ft.Text(
        logo_personalizado_actual[0] or "(usando logo por defecto)",
        size=11, color=C_TEXTO_3, italic=True, font_family="Saira",
    )

    def _on_logo_path(original):
        if not original or not os.path.exists(original):
            return
        # Rescalado opcional: si la imagen es muy grande, la reducimos
        # a 600px de ancho para que el correo pese poco y el sidebar
        # cargue rápido.
        try:
            from PIL import Image as _PILImg
            img = _PILImg.open(original)
            if img.width > 600:
                ratio = 600 / float(img.width)
                new_h = max(1, int(img.height * ratio))
                resized = img.resize((600, new_h), _PILImg.LANCZOS)
                base, ext = os.path.splitext(original)
                final_path = base + "_pulsemail_logo" + (ext or ".png")
                resized.save(final_path)
            else:
                final_path = original
        except Exception:
            final_path = original
        logo_personalizado_actual[0] = final_path
        img_logo_preview.src     = final_path
        img_logo_preview.visible = True
        lbl_logo_path.value      = final_path
        cfg_p = enviar_correos.cargar_config()
        cfg_p["logo_personalizado"] = final_path
        enviar_correos.guardar_config(cfg_p)
        # Actualizar el sidebar en vivo
        try:
            sidebar_logo_img.src = final_path
            sidebar_logo_img.update()
        except Exception:
            pass
        safe_update(img_logo_preview, lbl_logo_path)

    def _abrir_dialogo_logo(e=None):
        def _picker():
            try:
                path = _dialogo_archivo_nativo(
                    save=False,
                    title="Seleccioná tu logo",
                    filtros=[
                        ("Imágenes", "*.png *.jpg *.jpeg *.gif *.webp *.bmp"),
                        ("Todos los archivos", "*.*"),
                    ],
                )
                if path:
                    _on_logo_path(path)
            except Exception as ex:
                try:
                    agregar_log("error",
                                f"No se pudo abrir el selector: {ex}")
                except Exception:
                    pass
        threading.Thread(target=_picker, daemon=True).start()

    def _quitar_logo(e=None):
        logo_personalizado_actual[0] = ""
        img_logo_preview.src = ""
        img_logo_preview.visible = False
        lbl_logo_path.value = "(usando logo por defecto)"
        cfg_p = enviar_correos.cargar_config()
        cfg_p["logo_personalizado"] = ""
        enviar_correos.guardar_config(cfg_p)
        # Volver al logo embebido en el sidebar
        try:
            default_logo = os.path.join(CARPETA_ASSETS, "ITH-logo.png")
            sidebar_logo_img.src = default_logo
            sidebar_logo_img.update()
        except Exception:
            pass
        safe_update(img_logo_preview, lbl_logo_path)

    btn_subir_logo = ft.OutlinedButton(
        "Cargar logo…",
        icon=ft.Icons.UPLOAD_FILE_ROUNDED,
        on_click=_abrir_dialogo_logo,
        style=ft.ButtonStyle(
            color={ft.ControlState.DEFAULT: C_MORADO},
            side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, C_MORADO)},
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(14, 10, 14, 10),
        ),
    )
    btn_quitar_logo = ft.TextButton(
        "Usar logo por defecto",
        icon=ft.Icons.RESTORE_ROUNDED,
        on_click=_quitar_logo,
        style=ft.ButtonStyle(color=C_ROJO),
    )
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

    def _norm_hora(v):
        """Normaliza 'HH:MM' (0-23:0-59). Cae a '09:00' si es inválido."""
        v = (v or "").strip()
        m = re.match(r"^(\d{1,2}):(\d{2})$", v)
        if not m:
            return "09:00"
        h = min(23, max(0, int(m.group(1))))
        mi = min(59, max(0, int(m.group(2))))
        return f"{h:02d}:{mi:02d}"

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
            "correos_copia": (tf_correos_copia.value or "").strip(),
            "url_calendly":       (tf_url_calendly.value or "").strip(),
            "url_cal_com":        (tf_url_cal_com.value or "").strip(),
            "plataforma_reunion": plataforma_actual[0],
            "url_whatsapp":       (tf_url_whatsapp.value or "").strip(),
            "empresa_nombre":     (tf_empresa_nombre.value or "").strip(),
            "empresa_web":        (tf_empresa_web.value or "").strip(),
            "empresa_telefono":   (tf_empresa_telefono.value or "").strip(),
            "empresa_email":      (tf_empresa_email.value or "").strip(),
            "empresa_whatsapp":   (tf_empresa_whatsapp.value or "").strip(),
            "auto_envio_activo":  bool(chk_auto_envio.value),
            "auto_envio_hora":    _norm_hora(tf_auto_envio_hora.value),
            "modo_correo":        modo_correo_actual[0],
            "texto_asunto":       (tf_texto_asunto.value or "").strip()
                                   or enviar_correos.TEXTO_ASUNTO_DEFAULT,
            "texto_cuerpo":       (tf_texto_cuerpo.value or "").rstrip()
                                   or enviar_correos.TEXTO_CUERPO_DEFAULT,
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

                # ── Auto-envío programado ──
                ft.Container(
                    bgcolor=C_FONDO,
                    border_radius=ft.BorderRadius(10, 10, 10, 10),
                    border=borde_all(1, C_BORDE),
                    padding=ft.Padding(16, 14, 16, 14),
                    content=ft.Column(
                        spacing=10,
                        controls=[
                            ft.Row(
                                spacing=8,
                                controls=[
                                    ft.Icon(ft.Icons.ALARM_ON_ROUNDED,
                                            color=C_MORADO, size=20),
                                    ft.Text("Auto-envío programado",
                                            size=14, weight=ft.FontWeight.BOLD,
                                            color=C_TEXTO_1, font_family="Saira"),
                                ],
                            ),
                            chk_auto_envio,
                            ft.Row(spacing=12, controls=[tf_auto_envio_hora]),
                            ft.Text(
                                "Cada día a la hora indicada, la app lanza la "
                                "campaña sola, envía hasta el límite diario y "
                                "sigue al día siguiente donde quedó — hasta "
                                "terminar toda la base cargada. Si cargás una "
                                "base nueva, arranca de cero. Requiere que la "
                                "app esté abierta a esa hora.",
                                size=11, color=C_TEXTO_3, italic=True,
                                font_family="Saira",
                            ),
                        ],
                    ),
                ),

                ft.Container(
                    padding=ft.Padding(0, 8, 0, 0),
                    content=ft.Text(
                        "Las direcciones que pongas en CC reciben copia de "
                        "TODOS los envíos de la campaña. Separá por coma. "
                        "Dejá vacío para enviar sin copia.",
                        size=11, color=C_TEXTO_3, italic=True,
                        font_family="Saira",
                    ),
                ),
                ft.Row(spacing=12, controls=[tf_correos_copia]),
            ],
        ),
    )

    # ── Correo de prueba (previsualizar antes de lanzar) ──
    tf_correo_prueba = ft.TextField(
        label="Enviar prueba a",
        value="bsierra@intellihelp.tech",
        prefix_icon=ft.Icons.SEND_ROUNDED,
        border_color=C_BORDE,
        focused_border_color=C_MORADO,
        label_style=ft.TextStyle(color=C_TEXTO_2, font_family="Saira"),
        text_style=ft.TextStyle(font_family="Saira"),
        expand=True,
    )
    lbl_prueba_estado = ft.Text("", size=12, font_family="Saira")
    ring_prueba = ft.ProgressRing(color=C_MORADO, width=16, height=16,
                                  stroke_width=2.5, visible=False)

    def _enviar_prueba(e=None):
        dest = (tf_correo_prueba.value or "").strip()
        if not dest or "@" not in dest:
            lbl_prueba_estado.value = "Poné una dirección de prueba válida."
            lbl_prueba_estado.color = C_ROJO
            safe_update(lbl_prueba_estado)
            return
        # Guardamos los campos del Mensaje para que la prueba refleje lo que
        # tenés escrito AHORA (aunque no hayas apretado Guardar).
        cfg_p = enviar_correos.cargar_config()
        cfg_p["modo_correo"]  = modo_correo_actual[0]
        cfg_p["texto_asunto"] = (tf_texto_asunto.value or "").strip() \
            or enviar_correos.TEXTO_ASUNTO_DEFAULT
        cfg_p["texto_cuerpo"] = (tf_texto_cuerpo.value or "").rstrip() \
            or enviar_correos.TEXTO_CUERPO_DEFAULT
        enviar_correos.guardar_config(cfg_p)
        ring_prueba.visible = True
        lbl_prueba_estado.value = "Enviando prueba..."
        lbl_prueba_estado.color = C_AZUL
        safe_update(ring_prueba, lbl_prueba_estado)

        def _trab():
            try:
                # Sin nombre: se deriva de la dirección de prueba (parte
                # antes del @), ej nbaldelli → Nbaldelli.
                ok, msg = enviar_correos.enviar_correo_prueba(dest)
            except Exception as ex:
                ok, msg = False, str(ex)
            ring_prueba.visible = False
            lbl_prueba_estado.value = ("✓ " if ok else "") + msg
            lbl_prueba_estado.color = C_EXITO if ok else C_ROJO
            safe_update(ring_prueba, lbl_prueba_estado)

        threading.Thread(target=_trab, daemon=True).start()

    btn_correo_prueba = ft.ElevatedButton(
        "Enviar correo de prueba",
        icon=ft.Icons.FORWARD_TO_INBOX_ROUNDED,
        on_click=_enviar_prueba,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: C_VERDE,
                     ft.ControlState.HOVERED: C_VERDE_DARK},
            color={ft.ControlState.DEFAULT: C_BLANCO},
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding(16, 12, 16, 12),
        ),
    )

    # ── Tab "Mensaje" — formato y contenido del correo de campaña ──
    _refrescar_botones_modo()
    tab_mensaje = ft.Container(
        padding=ft.Padding(0, 20, 0, 0),
        content=ft.Column(
            spacing=16,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Text(
                    "Elegí cómo se envía el correo de campaña. "
                    "\"Texto plano\" es un email simple y personal (como el que "
                    "escribirías a mano) — suele rendir mucho mejor en frío y "
                    "entra menos a spam. \"HTML\" usa la plantilla con diseño.",
                    size=12, color=C_TEXTO_3, font_family="Saira",
                ),
                ft.Row(
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text("Formato:", size=12, color=C_TEXTO_2,
                                weight=ft.FontWeight.W_500, font_family="Saira"),
                        btns_modo_correo["texto"],
                        btns_modo_correo["html"],
                    ],
                ),
                ft.Divider(height=1, color=C_BORDE),
                ft.Text(
                    "Contenido del modo TEXTO PLANO (editable). Usá "
                    "@nombre donde quieras que vaya el nombre del contacto.",
                    size=12, weight=ft.FontWeight.BOLD, color=C_TEXTO_2,
                    font_family="Saira",
                ),
                ft.Row(spacing=12, controls=[tf_texto_asunto]),
                ft.Row(spacing=12, controls=[tf_texto_cuerpo]),
                ft.Text(
                    "Si tenés una firma de texto configurada en la pestaña "
                    "Firma, se agrega automáticamente al final. El asunto NO "
                    "lleva el nombre para que parezca un correo personal.",
                    size=11, color=C_TEXTO_3, italic=True, font_family="Saira",
                ),

                ft.Divider(height=1, color=C_BORDE),

                # ── Correo de prueba ──
                ft.Container(
                    bgcolor=C_FONDO,
                    border_radius=ft.BorderRadius(10, 10, 10, 10),
                    border=borde_all(1, C_BORDE),
                    padding=ft.Padding(16, 14, 16, 14),
                    content=ft.Column(
                        spacing=10,
                        controls=[
                            ft.Row(
                                spacing=8,
                                controls=[
                                    ft.Icon(ft.Icons.SCIENCE_ROUNDED,
                                            color=C_MORADO, size=20),
                                    ft.Text("Probar el correo antes de enviar",
                                            size=14, weight=ft.FontWeight.BOLD,
                                            color=C_TEXTO_1, font_family="Saira"),
                                ],
                            ),
                            ft.Text(
                                "Poné la dirección de prueba: el correo sale "
                                "armado igual que la campaña y el @nombre se "
                                "toma de esa misma dirección (ej: "
                                "carlos.baldelli@… → Carlos Baldelli). Si la "
                                "firma es de Texto, sale texto puro; si es "
                                "Imagen, se incrusta la imagen de la firma.",
                                size=11, color=C_TEXTO_3, font_family="Saira",
                            ),
                            ft.Row(
                                spacing=12,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    tf_correo_prueba,
                                    btn_correo_prueba,
                                    ring_prueba,
                                ],
                            ),
                            lbl_prueba_estado,
                        ],
                    ),
                ),
            ],
        ),
    )

    # ── Tab "Reuniones" — Calendly / Cal.com ────────────────────
    tab_reuniones = ft.Container(
        padding=ft.Padding(0, 20, 0, 0),
        content=ft.Column(
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Text(
                    "Elegí qué plataforma usás para agendar reuniones. "
                    "El botón \"Agendar reunión\" del correo va a abrir "
                    "la URL de la plataforma elegida. Si alguien agenda "
                    "con la OTRA plataforma, también se detecta y aparece "
                    "en Respuestas — no se pierde nada al cambiar.",
                    size=12, color=C_TEXTO_3, font_family="Saira",
                ),
                ft.Container(
                    bgcolor=C_FONDO,
                    border_radius=ft.BorderRadius(10, 10, 10, 10),
                    padding=ft.Padding(14, 12, 14, 12),
                    border=borde_all(1, C_BORDE),
                    content=ft.Row(
                        spacing=10,
                        controls=[
                            ft.Text("Plataforma activa:",
                                    size=12, color=C_TEXTO_2,
                                    weight=ft.FontWeight.W_500,
                                    font_family="Saira"),
                            btns_plataforma["calendly"],
                            btns_plataforma["cal_com"],
                        ],
                    ),
                ),
                ft.Text(
                    "Pegá los enlaces tuyos. Si dejás un campo vacío, "
                    "ese botón NO aparece en el correo (no se manda "
                    "nada genérico). Sólo se incluye lo que vos configures.",
                    size=11, color=C_TEXTO_3, italic=True,
                    font_family="Saira",
                ),
                ft.Row(spacing=12, controls=[tf_url_calendly]),
                ft.Row(spacing=12, controls=[tf_url_cal_com]),
            ],
        ),
    )

    # ── Tab "WhatsApp" ─────────────────────────────────────────
    tab_whatsapp = ft.Container(
        padding=ft.Padding(0, 20, 0, 0),
        content=ft.Column(
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Text(
                    "URL del botón verde \"Conversar por WhatsApp\" del "
                    "correo. Si la dejás vacía, el botón no aparece.",
                    size=12, color=C_TEXTO_3, font_family="Saira",
                ),
                ft.Container(
                    bgcolor=C_FONDO,
                    border_radius=ft.BorderRadius(10, 10, 10, 10),
                    padding=ft.Padding(14, 12, 14, 12),
                    border=borde_all(1, C_BORDE),
                    content=ft.Column(
                        spacing=8,
                        controls=[
                            ft.Text("¿Cómo armar el enlace?",
                                    size=12, weight=ft.FontWeight.BOLD,
                                    color=C_TEXTO_2, font_family="Saira"),
                            ft.Text(
                                "Formato: https://wa.me/<código país + número>"
                                "?text=<mensaje pre-cargado>\n"
                                "Ejemplo (Argentina, +54 9 11 2345-6789):\n"
                                "https://wa.me/5491123456789?text=Hola%2C%20me"
                                "%20interesa",
                                size=11, color=C_TEXTO_3,
                                font_family="Saira",
                            ),
                            ft.Text(
                                "Tip: usá https://wa.me para generar el "
                                "enlace correcto con tu número y mensaje.",
                                size=11, color=C_TEXTO_3, italic=True,
                                font_family="Saira",
                            ),
                        ],
                    ),
                ),
                ft.Row(spacing=12, controls=[tf_url_whatsapp]),
            ],
        ),
    )

    # ── Tab "Empresa" — datos que se muestran en el correo de campaña ──
    tab_empresa = ft.Container(
        padding=ft.Padding(0, 20, 0, 0),
        content=ft.Column(
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Text(
                    "Estos datos se muestran en el correo de campaña "
                    "(encabezado, bloque de contacto y pie). Si dejás un "
                    "campo vacío, esa línea no aparece. Nada está fijo en el "
                    "código: todo sale de acá.",
                    size=12, color=C_TEXTO_3, font_family="Saira",
                ),
                ft.Row(spacing=12, controls=[tf_empresa_nombre]),
                ft.Row(spacing=12, controls=[tf_empresa_web]),
                ft.Row(spacing=12, controls=[tf_empresa_telefono]),
                ft.Row(spacing=12, controls=[tf_empresa_email]),
                ft.Row(spacing=12, controls=[tf_empresa_whatsapp]),
                ft.Text(
                    "El número de WhatsApp de acá es sólo el texto visible en "
                    "el bloque de contacto. El botón verde \"Contáctanos por "
                    "WhatsApp\" usa el enlace de la pestaña WhatsApp, y el "
                    "botón \"Agendar reunión\" usa el de la pestaña Reuniones. "
                    "Cada botón aparece sólo si su enlace está configurado.",
                    size=11, color=C_TEXTO_3, italic=True, font_family="Saira",
                ),
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
                    "Esta firma se agrega automáticamente al cierre del correo "
                    "de campaña y de las respuestas que envíes desde el hilo. "
                    "Si la dejás vacía, el correo cierra con el nombre de la "
                    "empresa. Podés usar texto o una imagen.",
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
                ft.Text("Tema",
                        size=12, weight=ft.FontWeight.BOLD,
                        color=C_TEXTO_2, font_family="Saira"),
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
                ft.Divider(height=1, color=C_BORDE),
                ft.Text("Logo del cliente",
                        size=12, weight=ft.FontWeight.BOLD,
                        color=C_TEXTO_2, font_family="Saira"),
                ft.Text(
                    "El logo aparece en el sidebar de la app y se incrusta "
                    "en cada correo enviado (reemplaza al logo por defecto). "
                    "Se rescala a 600px de ancho. PNG/JPG/WEBP.",
                    size=11, color=C_TEXTO_3, font_family="Saira",
                ),
                ft.Row(
                    spacing=10,
                    controls=[btn_subir_logo, btn_quitar_logo, lbl_logo_path],
                ),
                ft.Container(
                    bgcolor=C_FONDO,
                    border_radius=ft.BorderRadius(8, 8, 8, 8),
                    padding=ft.Padding(10, 10, 10, 10),
                    border=borde_all(1, C_BORDE),
                    content=img_logo_preview,
                ),
            ],
        ),
    )

    # ── Tab "Datos" (import/export, backups) ────────────────────
    lbl_datos_estado = ft.Text("", size=12, italic=True, font_family="Saira")

    def _flash_datos(msg, color=C_AZUL, segundos=4):
        lbl_datos_estado.value = msg
        lbl_datos_estado.color = color
        safe_update(lbl_datos_estado)
        def _limpiar():
            import time as _t
            _t.sleep(segundos)
            if lbl_datos_estado.value == msg:
                lbl_datos_estado.value = ""
                safe_update(lbl_datos_estado)
        threading.Thread(target=_limpiar, daemon=True).start()

    def _abrir_dialogo(titulo, modo, filetypes, default_name=""):
        """Abre el diálogo NATIVO de Windows y devuelve la ruta elegida
        (o '' si el usuario canceló). modo = 'open' | 'save'.
        `filetypes` en formato tkinter: [(etiqueta, "*.ext"), ...].

        Antes usaba `tk.Tk()` en un thread daemon, lo cual fallaba en el
        .exe compilado (tcl/tk no siempre se empaqueta) → los backups no
        se podían importar ni exportar. Ahora delega en el diálogo nativo
        Win32 (ver `_dialogo_archivo_nativo`), robusto y sin dependencias."""
        try:
            default_ext = filetypes[0][1].split()[0].lstrip("*").lstrip(".")
        except Exception:
            default_ext = ""
        return _dialogo_archivo_nativo(
            save=(modo == "save"),
            title=titulo,
            filtros=filetypes,
            default_name=default_name,
            default_ext=default_ext,
        )

    def _importar_archivo_dialog(nombre_local, descripcion, exts):
        def _picker():
            try:
                path = _abrir_dialogo(
                    f"Importar {descripcion}",
                    "open",
                    [(descripcion, " ".join(f"*.{e}" for e in exts)),
                     ("Todos los archivos", "*.*")],
                )
                if not path:
                    return
                ok, msg = enviar_correos.importar_archivo_local(
                    path, nombre_local
                )
                if ok:
                    _flash_datos(f"✓ {msg}", C_EXITO, 4)
                    agregar_log("info",
                                f"{descripcion} importado desde: {path}")
                else:
                    _flash_datos(msg, C_ROJO, 5)
            except Exception as ex:
                _flash_datos(f"Error: {ex}", C_ROJO, 5)
        threading.Thread(target=_picker, daemon=True).start()

    def _exportar_archivo_dialog(nombre_local, descripcion, exts):
        def _picker():
            try:
                # Sugerimos un nombre de archivo con timestamp
                sufijo = datetime.now().strftime("%Y%m%d_%H%M")
                base, ext = os.path.splitext(nombre_local)
                default_name = f"{base}_{sufijo}{ext}"
                path = _abrir_dialogo(
                    f"Exportar {descripcion}",
                    "save",
                    [(descripcion, " ".join(f"*.{e}" for e in exts)),
                     ("Todos los archivos", "*.*")],
                    default_name=default_name,
                )
                if not path:
                    return
                ok, msg = enviar_correos.exportar_archivo_local(
                    nombre_local, path
                )
                _flash_datos(("✓ " if ok else "") + msg,
                             C_EXITO if ok else C_ROJO, 5)
                if ok:
                    agregar_log("info",
                                f"{descripcion} exportado a: {path}")
            except Exception as ex:
                _flash_datos(f"Error: {ex}", C_ROJO, 5)
        threading.Thread(target=_picker, daemon=True).start()

    def _exportar_backup_completo_dialog(e=None):
        def _picker():
            try:
                sufijo = datetime.now().strftime("%Y%m%d_%H%M")
                default_name = f"pulsemail_backup_{sufijo}.zip"
                path = _abrir_dialogo(
                    "Exportar configuración completa (ZIP)",
                    "save",
                    [("Backup ZIP", "*.zip"), ("Todos", "*.*")],
                    default_name=default_name,
                )
                if not path:
                    return
                _flash_datos("Comprimiendo backup...", C_AZUL, 30)
                ok, msg = enviar_correos.exportar_backup_completo(path)
                _flash_datos(("✓ " if ok else "") + msg,
                             C_EXITO if ok else C_ROJO, 6)
                if ok:
                    agregar_log("info",
                                f"Backup completo exportado a: {path}")
            except Exception as ex:
                _flash_datos(f"Error: {ex}", C_ROJO, 5)
        threading.Thread(target=_picker, daemon=True).start()

    def _importar_backup_completo_dialog(e=None):
        def _picker():
            try:
                path = _abrir_dialogo(
                    "Importar configuración completa (ZIP)",
                    "open",
                    [("Backup ZIP", "*.zip"), ("Todos", "*.*")],
                )
                if not path:
                    return
                _flash_datos("Restaurando backup...", C_AZUL, 30)
                ok, msg = enviar_correos.importar_backup_completo(path)
                if ok:
                    _flash_datos(
                        "✓ Backup restaurado. Reiniciá la app para que "
                        "tome todos los cambios.",
                        C_EXITO, 12,
                    )
                    agregar_log("info",
                                f"Backup completo restaurado desde: {path}. "
                                f"Reiniciá Pulsemail.")
                    # Recargar contactos en vivo
                    try:
                        cargar_contactos(forzar=True)
                    except Exception:
                        pass
                else:
                    _flash_datos(msg, C_ROJO, 6)
            except Exception as ex:
                _flash_datos(f"Error: {ex}", C_ROJO, 5)
        threading.Thread(target=_picker, daemon=True).start()

    def _btn_outlined(label, icon, handler, color=C_MORADO):
        return ft.OutlinedButton(
            label,
            icon=icon,
            on_click=handler,
            style=ft.ButtonStyle(
                color={ft.ControlState.DEFAULT: color},
                side={ft.ControlState.DEFAULT: ft.BorderSide(1.2, color)},
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.Padding(14, 10, 14, 10),
            ),
        )

    def _btn_filled(label, icon, handler, color=C_MORADO):
        return ft.ElevatedButton(
            label,
            icon=icon,
            on_click=handler,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: color,
                         ft.ControlState.HOVERED: C_MORADO_DARK},
                color={ft.ControlState.DEFAULT: C_BLANCO},
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.Padding(16, 12, 16, 12),
            ),
        )

    tab_datos = ft.Container(
        padding=ft.Padding(0, 20, 0, 0),
        content=ft.Column(
            spacing=18,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Text(
                    "Importá y exportá los datos de Pulsemail. Útil para "
                    "migrar a otra PC, hacer backups o pasarle el software "
                    "a otra persona con la campaña ya en curso.",
                    size=12, color=C_TEXTO_3, font_family="Saira",
                ),
                lbl_datos_estado,

                # ── Backup completo ─────────────────────────────────
                ft.Container(
                    bgcolor=C_FONDO,
                    border_radius=ft.BorderRadius(10, 10, 10, 10),
                    border=borde_all(1, C_BORDE),
                    padding=ft.Padding(16, 14, 16, 14),
                    content=ft.Column(
                        spacing=10,
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.BACKUP_ROUNDED,
                                            color=C_MORADO, size=20),
                                    ft.Text("Backup completo (recomendado)",
                                            size=14, weight=ft.FontWeight.BOLD,
                                            color=C_TEXTO_1, font_family="Saira"),
                                ],
                            ),
                            ft.Text(
                                "Exporta TODO en un solo ZIP: configuración, "
                                "contactos, historial diario completo, "
                                "registros de envíos/rechazados/respuestas, "
                                "firma y tema. Para restaurar en otra PC, "
                                "instalá Pulsemail y apretá 'Importar backup'.",
                                size=11, color=C_TEXTO_2, font_family="Saira",
                            ),
                            ft.Row(
                                spacing=10,
                                controls=[
                                    _btn_filled(
                                        "Exportar configuración completa",
                                        ft.Icons.FILE_DOWNLOAD_ROUNDED,
                                        _exportar_backup_completo_dialog,
                                    ),
                                    _btn_outlined(
                                        "Importar backup",
                                        ft.Icons.FILE_UPLOAD_ROUNDED,
                                        _importar_backup_completo_dialog,
                                    ),
                                ],
                            ),
                        ],
                    ),
                ),

                # ── Archivos individuales ────────────────────────────
                ft.Container(
                    bgcolor=C_FONDO,
                    border_radius=ft.BorderRadius(10, 10, 10, 10),
                    border=borde_all(1, C_BORDE),
                    padding=ft.Padding(16, 14, 16, 14),
                    content=ft.Column(
                        spacing=12,
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.FOLDER_OPEN_ROUNDED,
                                            color=C_MORADO, size=20),
                                    ft.Text("Archivos individuales",
                                            size=14, weight=ft.FontWeight.BOLD,
                                            color=C_TEXTO_1,
                                            font_family="Saira"),
                                ],
                            ),
                            ft.Text(
                                "Si solo querés mover un archivo puntual "
                                "(por ejemplo, el progreso del día actual "
                                "o el listado de contactos).",
                                size=11, color=C_TEXTO_2, font_family="Saira",
                            ),
                            # registro_envios.json
                            ft.Row(
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=10,
                                controls=[
                                    ft.Text("registro_envios.json",
                                            size=12, color=C_TEXTO_1,
                                            font_family="Saira",
                                            weight=ft.FontWeight.W_500,
                                            expand=True),
                                    _btn_outlined(
                                        "Exportar",
                                        ft.Icons.FILE_DOWNLOAD_ROUNDED,
                                        lambda e: _exportar_archivo_dialog(
                                            "registro_envios.json",
                                            "Progreso del día (JSON)",
                                            ["json"],
                                        ),
                                    ),
                                    _btn_outlined(
                                        "Importar",
                                        ft.Icons.FILE_UPLOAD_ROUNDED,
                                        lambda e: _importar_archivo_dialog(
                                            "registro_envios.json",
                                            "Progreso del día (JSON)",
                                            ["json"],
                                        ),
                                    ),
                                ],
                            ),
                            # contactos.csv
                            ft.Row(
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=10,
                                controls=[
                                    ft.Text("contactos.csv",
                                            size=12, color=C_TEXTO_1,
                                            font_family="Saira",
                                            weight=ft.FontWeight.W_500,
                                            expand=True),
                                    _btn_outlined(
                                        "Exportar",
                                        ft.Icons.FILE_DOWNLOAD_ROUNDED,
                                        lambda e: _exportar_archivo_dialog(
                                            "contactos.csv",
                                            "Lista de contactos",
                                            ["csv"],
                                        ),
                                    ),
                                    _btn_outlined(
                                        "Importar",
                                        ft.Icons.FILE_UPLOAD_ROUNDED,
                                        lambda e: _importar_archivo_dialog(
                                            "contactos.csv",
                                            "Lista de contactos",
                                            ["csv"],
                                        ),
                                    ),
                                ],
                            ),
                            # config.json
                            ft.Row(
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=10,
                                controls=[
                                    ft.Text("config.json",
                                            size=12, color=C_TEXTO_1,
                                            font_family="Saira",
                                            weight=ft.FontWeight.W_500,
                                            expand=True),
                                    _btn_outlined(
                                        "Exportar",
                                        ft.Icons.FILE_DOWNLOAD_ROUNDED,
                                        lambda e: _exportar_archivo_dialog(
                                            "config.json",
                                            "Configuración",
                                            ["json"],
                                        ),
                                    ),
                                    _btn_outlined(
                                        "Importar",
                                        ft.Icons.FILE_UPLOAD_ROUNDED,
                                        lambda e: _importar_archivo_dialog(
                                            "config.json",
                                            "Configuración",
                                            ["json"],
                                        ),
                                    ),
                                ],
                            ),
                        ],
                    ),
                ),

                ft.Text(
                    "Antes de importar cualquier archivo, Pulsemail crea "
                    "automáticamente un .bak del archivo existente. Para "
                    "que algunos cambios se reflejen completamente "
                    "(ej. firma de imagen) conviene reiniciar la app.",
                    size=11, color=C_TEXTO_3, italic=True, font_family="Saira",
                ),
            ],
        ),
    )

    # ── Sub-pestañas custom (más confiable que ft.Tabs en Flet 0.84) ──
    cfg_tabs = [
        ("cuenta",     "Cuenta",     ft.Icons.ACCOUNT_CIRCLE_ROUNDED, tab_cuenta),
        ("mensaje",    "Mensaje",    ft.Icons.MAIL_OUTLINE_ROUNDED,   tab_mensaje),
        ("reuniones",  "Reuniones",  ft.Icons.EVENT_AVAILABLE_ROUNDED, tab_reuniones),
        ("whatsapp",   "WhatsApp",   ft.Icons.CHAT_ROUNDED,           tab_whatsapp),
        ("empresa",    "Empresa",    ft.Icons.BUSINESS_ROUNDED,       tab_empresa),
        ("firma",      "Firma",      ft.Icons.DRAW_ROUNDED,           tab_firma),
        ("servidores", "Servidores", ft.Icons.DNS_ROUNDED,            tab_servidores),
        ("apariencia", "Apariencia", ft.Icons.PALETTE_ROUNDED,        tab_apariencia),
        ("datos",      "Datos",      ft.Icons.STORAGE_ROUNDED,        tab_datos),
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
        elif vista_key == "lista_negra":
            contenedor_vista.content = vista_lista_negra
            lbl_topbar_titulo.value  = "Lista negra"
            btn_iniciar.visible      = False
            cargar_lista_negra_panel()
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
            # Si entramos al panel y está vacío, disparamos un full
            # rescan en background. Esto cubre el bug de "Pulsemail
            # dice 0 respuestas pero en Gmail hay varias" — fuerza al
            # módulo a buscar en los últimos 7 días sin importar el
            # último UID conocido.
            try:
                data_actual = enviar_correos.cargar_respuestas()
                total_actual = (
                    len(data_actual.get("respuestas", []))
                    + len(data_actual.get("calendly", []))
                )
                if total_actual == 0:
                    def _full_rescan_bg():
                        try:
                            enviar_correos.detectar_respuestas_y_calendly(
                                dias=7, forzar_full=True,
                            )
                            _render_respuestas()
                        except Exception:
                            pass
                    threading.Thread(
                        target=_full_rescan_bg, daemon=True,
                    ).start()
            except Exception:
                pass
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
            tf_imap_host.value     = cfg_r.get("imap_host", "imap.gmail.com")
            tf_firma.value         = cfg_r.get("firma", "")
            tf_correos_copia.value = cfg_r.get("correos_copia", "")
            tf_url_calendly.value  = cfg_r.get("url_calendly", "")
            tf_url_cal_com.value   = cfg_r.get("url_cal_com", "")
            plataforma_actual[0]   = cfg_r.get("plataforma_reunion", "calendly")
            _refrescar_botones_plataforma()
            tf_url_whatsapp.value  = cfg_r.get("url_whatsapp", "")
            tf_empresa_nombre.value   = cfg_r.get("empresa_nombre", "")
            tf_empresa_web.value      = cfg_r.get("empresa_web", "")
            tf_empresa_telefono.value = cfg_r.get("empresa_telefono", "")
            tf_empresa_email.value    = cfg_r.get("empresa_email", "")
            tf_empresa_whatsapp.value = cfg_r.get("empresa_whatsapp", "")
            chk_auto_envio.value      = bool(cfg_r.get("auto_envio_activo", False))
            tf_auto_envio_hora.value  = str(cfg_r.get("auto_envio_hora", "09:00"))
            modo_correo_actual[0]     = cfg_r.get("modo_correo", "texto")
            _refrescar_botones_modo()
            tf_texto_asunto.value     = cfg_r.get("texto_asunto",
                                                  enviar_correos.TEXTO_ASUNTO_DEFAULT)
            tf_texto_cuerpo.value     = cfg_r.get("texto_cuerpo",
                                                  enviar_correos.TEXTO_CUERPO_DEFAULT)
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
    # Cada N ciclos hace un FULL rescan para captar respuestas que el
    # tracking incremental (_last_uid) podría haber perdido por algún
    # cierre forzado, sync con la nube, etc.
    _CICLOS_FULL_RESCAN = 12   # con polling de ~10-15s, full ~cada 2-3 min
    contador_ciclos = [0]

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

                    # Decidimos si forzar full rescan:
                    #   - Cada N ciclos (heartbeat)
                    #   - Si la lista de respuestas está vacía PERO hay
                    #     un _last_uid > 0 (significa que algo se perdió:
                    #     el JSON fue limpiado/corrupted y el tracking
                    #     incremental dejaría fuera respuestas reales)
                    contador_ciclos[0] += 1
                    last_uid = int(antes.get("_last_uid", 0) or 0)
                    forzar = (
                        contador_ciclos[0] % _CICLOS_FULL_RESCAN == 0
                        or (n_antes_resp == 0 and n_antes_cal == 0 and last_uid > 0)
                    )

                    enviar_correos.detectar_respuestas_y_calendly(
                        dias=7 if forzar else 2,
                        forzar_full=forzar,
                    )

                    despues     = enviar_correos.cargar_respuestas()
                    n_desp_resp = len(despues.get("respuestas", []))
                    n_desp_cal  = len(despues.get("calendly", []))

                    nuevas_resp_total = max(0, n_desp_resp - n_antes_resp)
                    nuevas_cal_total  = max(0, n_desp_cal  - n_antes_cal)

                    # Para la notificación tipo toast, sólo contamos las
                    # respuestas NUEVAS que vienen de contactos que están
                    # AHORA en contactos.csv. Una respuesta vieja en el
                    # JSON cuyo remitente ya no está en el CSV (porque el
                    # cliente cambió la lista de campaña) NO debe
                    # disparar notificación — el cliente quiere ver sólo
                    # respuestas verdaderas de SU campaña actual.
                    contactos_actuales = enviar_correos.emails_de_contactos()
                    resp_lista     = despues.get("respuestas", [])
                    cal_lista      = despues.get("calendly", [])
                    nuevas_resp_lst = resp_lista[n_antes_resp:] if n_antes_resp <= len(resp_lista) else []
                    nuevas_cal_lst  = cal_lista[n_antes_cal:]  if n_antes_cal  <= len(cal_lista)  else []

                    def _es_de_campana(item):
                        # Calendly: usa el campo "invitado" (email del
                        # cliente que agendó), no el "from" del propio
                        # Calendly. Respuestas: el "from" es el cliente.
                        em = (
                            item.get("invitado")
                            or item.get("from")
                            or ""
                        ).strip().lower()
                        return em in contactos_actuales

                    nuevas_resp = sum(1 for r in nuevas_resp_lst if _es_de_campana(r))
                    nuevas_cal  = sum(1 for c in nuevas_cal_lst  if _es_de_campana(c))
                    total_nuevas       = nuevas_resp + nuevas_cal
                    total_nuevas_total = nuevas_resp_total + nuevas_cal_total

                    if total_nuevas > 0:
                        # Marcar timestamp de actividad para polling adaptativo
                        _ULTIMA_ACTIVIDAD_RESPUESTA[0] = _time.time()

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
                            _render_respuestas()
                        else:
                            # Sólo subimos el contador del badge con las
                            # respuestas que SÍ son de la campaña actual.
                            respuestas_no_vistas[0] += total_nuevas
                            _actualizar_badge_respuestas()
                            agregar_log(
                                "info",
                                f"{total_nuevas} nueva(s) respuesta(s) de la campaña."
                            )

                    # Si hubo respuestas nuevas pero NINGUNA es de la
                    # campaña actual, refrescamos la UI silenciosamente
                    # (sin toast, sin badge) — el listado completo del
                    # panel "Respuestas" igual las muestra por si el
                    # usuario quiere verlas con el checkbox apagado.
                    elif total_nuevas_total > 0 and vista_actual[0] == "respuestas":
                        _render_respuestas()
                except Exception:
                    pass

            # Polling ADAPTATIVO: si hubo actividad reciente, polea más
            # rápido (sospecha que vienen más respuestas en cadena).
            # Si la cuenta está quieta, polea más lento para respetar el
            # rate-limit de Gmail (evita "Application-specific password").
            _now = _time.time()
            desde_actividad = _now - _ULTIMA_ACTIVIDAD_RESPUESTA[0]
            mirando_respuestas = (vista_actual[0] == "respuestas")

            if desde_actividad < 300:        # actividad en últimos 5 min
                # Más agresivo cuando el usuario está MIRANDO el panel
                # de respuestas: 2.5s entre polls. Sensación "instantánea"
                # sin abusar del rate limit de Gmail. Cuando no está en
                # el panel, baja a 8s.
                sleep_t = 2.5 if mirando_respuestas else 8
            elif desde_actividad < 1800:     # entre 5 y 30 min
                sleep_t = 4 if mirando_respuestas else 15
            else:                            # más de 30 min sin actividad
                sleep_t = 15 if mirando_respuestas else 25
            _time.sleep(sleep_t)

    if not _INIT_HECHO[0]:
        threading.Thread(target=watcher_respuestas, daemon=True).start()

    # ── Watcher del auto-envío programado ──────────────────────────
    # Cada día, a la hora configurada, lanza la campaña sola (si está
    # activado, hay credenciales, no está ya corriendo y la base no está
    # completa). main() envía hasta el límite diario y sigue al día
    # siguiente donde quedó, hasta terminar toda la base.
    def watcher_scheduler():
        import time as _time
        ultimo_lanzamiento = [None]   # "YYYY-MM-DD" del último auto-lanzamiento
        while True:
            _time.sleep(20)
            try:
                cfg = enviar_correos.cargar_config()
                if not cfg.get("auto_envio_activo"):
                    continue
                hora_cfg = _norm_hora(cfg.get("auto_envio_hora") or "09:00")
                ahora   = datetime.now()
                hoy_str = ahora.strftime("%Y-%m-%d")
                hh, mm  = int(hora_cfg[:2]), int(hora_cfg[3:5])
                # Ventana de disparo: de la hora exacta hasta +5 min (por si
                # el chequeo de 20s no cae justo en el minuto).
                delta_min = (ahora.hour * 60 + ahora.minute) - (hh * 60 + mm)
                if not (0 <= delta_min <= 5):
                    continue
                if ultimo_lanzamiento[0] == hoy_str:
                    continue                       # ya se disparó hoy
                if campana_activa[0]:
                    ultimo_lanzamiento[0] = hoy_str
                    continue                       # ya está corriendo
                if not cfg.get("correo") or not cfg.get("password"):
                    continue                       # sin credenciales
                ultimo_lanzamiento[0] = hoy_str
                if enviar_correos.campana_esta_completa():
                    agregar_log("info",
                                "Auto-envío: la base ya está completa. "
                                "Cargá una base nueva para reanudar.")
                    continue
                agregar_log("info",
                            f"Auto-envío programado ({hora_cfg}): "
                            "lanzando la campaña automáticamente.")
                try:
                    arrancar(None)
                except Exception as ex:
                    agregar_log("error", f"Auto-envío no pudo lanzar: {ex}")
            except Exception:
                pass

    if not _INIT_HECHO[0]:
        threading.Thread(target=watcher_scheduler, daemon=True).start()

        # Pre-warm de Chrome en background. La primera renderización de
        # un correo del Hilo cuesta 2-3 s porque Chrome tiene que
        # arrancar. Si esto pasa en background al iniciar la app, cuando
        # el usuario finalmente abre un hilo el render es instantáneo.
        # Si el usuario nunca entra al Hilo, este thread igual termina
        # rápido (sólo inicializa el binding html2image, ~200 MB RAM
        # vienen recién al primer screenshot).
        def _prewarm_chrome():
            try:
                _hti_init()
            except Exception:
                pass
        threading.Thread(target=_prewarm_chrome, daemon=True).start()

        # Pre-load del CSV de contactos en background. Con 30k+ contactos
        # parsear el archivo toma 500-800 ms — si lo hacemos al cargar
        # la app, cuando el usuario entra al panel "Contactos" la tabla
        # se muestra al instante. Si nunca entra, el set queda cacheado
        # para uso en main() y detectar_respuestas().
        def _preload_contactos():
            try:
                enviar_correos.emails_de_contactos()
            except Exception:
                pass
        threading.Thread(target=_preload_contactos, daemon=True).start()

    _INIT_HECHO[0] = True

    # ── Header del sidebar: nombre del producto + logo del cliente ──
    # Si el usuario configuró un logo personalizado en Configuración →
    # Apariencia, lo usamos. Si no, fallback al logo embebido (ITH-logo.png
    # del bundle). Path SIEMPRE absoluto: en .exe compilado el cwd no es
    # CARPETA_ASSETS y un src relativo no encuentra la imagen.
    _logo_user = (cfg_actual.get("logo_personalizado") or "").strip()
    if _logo_user and os.path.exists(_logo_user):
        logo_path = _logo_user
    else:
        logo_path = os.path.join(CARPETA_ASSETS, "ITH-logo.png")
    sidebar_logo_img = ft.Image(
        src=logo_path,
        width=110,
        height=46,
        fit="contain",
    )
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
                ft.Container(
                    bgcolor=C_FONDO,
                    border_radius=ft.BorderRadius(12, 12, 12, 12),
                    padding=ft.Padding(14, 10, 14, 10),
                    content=sidebar_logo_img,
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
                            nav_item("Lista negra",    ft.Icons.BLOCK_ROUNDED,             "lista_negra"),
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
