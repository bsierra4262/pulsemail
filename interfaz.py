import flet as ft
import threading
import os
import sys
import re
import csv
import json
import enviar_correos
from datetime import datetime

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
    page.title             = "IntelliHelp — Motor de Campañas"
    page.window.width      = 1200
    page.window.height     = 820
    page.window.min_width  = 960
    page.window.min_height = 660
    page.bgcolor           = C_FONDO
    page.theme_mode        = ft.ThemeMode.LIGHT
    page.padding           = 0

    # Ícono de la ventana / barra de tareas (usa ITH-logo.png si existe)
    _logo_full = os.path.join(CARPETA_ACTUAL, "ITH-logo.png")
    if os.path.exists(_logo_full):
        for attr in ("icon",):
            try:
                setattr(page.window, attr, _logo_full)
            except Exception:
                pass
        try:
            page.window_icon = _logo_full
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
        heading_row_height=44,
        data_row_min_height=40,
        column_spacing=20,
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
                padding=ft.Padding(0, 0, 0, 0),
                content=ft.Column(
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    controls=[tabla_contactos_rows],
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
                            _leyenda_item(C_VERDE, f"Enviados ({pct_env*100:.1f}%)", env),
                            _leyenda_item(C_ROJO,  f"Rechazados ({pct_rech*100:.1f}%)", rech),
                            ft.Divider(height=1, color=C_BORDE),
                            _leyenda_item(C_MORADO, "Total", total),
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
        stats = enviar_correos.obtener_estadisticas_globales()
        env   = stats.get("total_enviados", 0)
        rech  = stats.get("total_rechazados", 0)
        total = env + rech
        lbl_stats_enviados.value   = f"{env:,}".replace(",", ".")
        lbl_stats_rechazados.value = f"{rech:,}".replace(",", ".")
        lbl_stats_total.value      = f"{total:,}".replace(",", ".")
        if total > 0:
            tasa = env / total * 100
            lbl_stats_efectivo.value = f"{tasa:.1f}%"
            if tasa >= 50:
                lbl_stats_resumen.value = (
                    f"Campaña positiva: {tasa:.1f}% de los correos llegaron sin rebotar."
                )
                lbl_stats_resumen.color = C_VERDE_DARK
            else:
                lbl_stats_resumen.value = (
                    f"Campaña con problemas: solo el {tasa:.1f}% llegó. "
                    f"Conviene depurar la base."
                )
                lbl_stats_resumen.color = C_ROJO
        else:
            lbl_stats_efectivo.value = "0%"
            lbl_stats_resumen.value  = "Todavía no hay envíos registrados."
            lbl_stats_resumen.color  = C_TEXTO_3

        if tipo_grafico[0] == "torta":
            contenedor_grafico.content = _construir_grafico_torta(env, rech)
        elif tipo_grafico[0] == "barra":
            contenedor_grafico.content = _construir_grafico_barra(env, rech)
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
                _stat_card("Total",      lbl_stats_total,      C_MORADO,     C_MORADO_LIGHT),
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
            clave = _asunto_campana_lower[:40]   # primeros 40 chars son distintivos
            items = [
                t for t in items
                if clave in (t[1].get("subject", "") or "").lower()
                or t[0] == "calendly"   # confirmaciones de Calendly siempre son de la campaña
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

        items.sort(key=lambda t: t[1].get("date", ""), reverse=True)
        return items, len(respuestas), len(calendly)

    def _render_respuestas():
        items, total_resp, total_cal = _items_filtrados()
        total_visibles = len(items)

        max_pag = max(0, (total_visibles - 1) // TAM_PAGINA_RESP) if total_visibles else 0
        if pagina_resp[0] > max_pag:
            pagina_resp[0] = max_pag
        if pagina_resp[0] < 0:
            pagina_resp[0] = 0
        ini = pagina_resp[0] * TAM_PAGINA_RESP
        fin = min(ini + TAM_PAGINA_RESP, total_visibles)

        lista_respuestas.controls.clear()
        for tipo, item in items[ini:fin]:
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

            def _abrir_resp(e, correo=accion_email, asunto=subtitulo):
                if not correo:
                    _flash_resp("No hay correo del invitado para responder", C_NARANJA)
                    return
                # Cambio a la vista de hilo y traigo la conversación entera
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

            lista_respuestas.controls.append(
                ft.Container(
                    bgcolor=C_BLANCO,
                    border_radius=ft.BorderRadius(10, 10, 10, 10),
                    border=borde_all(1, C_BORDE),
                    padding=ft.Padding(14, 10, 14, 10),
                    content=ft.Row(
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=12,
                        controls=[
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
            f"{total_visibles} visibles"
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

                cuerpo_text = (m.get("body") or "").strip()
                # Recortar quotes pesados (líneas que empiezan con ">")
                lineas = cuerpo_text.split("\n")
                limpio = []
                for ln in lineas:
                    if ln.lstrip().startswith(">"):
                        continue
                    if ln.strip().startswith("On ") and "wrote:" in ln:
                        break
                    if "El " in ln and "escribió:" in ln:
                        break
                    limpio.append(ln)
                cuerpo_text = "\n".join(limpio).strip() or cuerpo_text

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
                            ft.Text(cuerpo_text, size=13, color=C_TEXTO_1,
                                    font_family="Saira", selectable=True),
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
                msgs = enviar_correos.obtener_hilo(email_dest, dias=180)
                hilo_mensajes[0] = msgs
                _flash_hilo(f"{len(msgs)} mensajes en el hilo.", C_EXITO, 2)
            except Exception as ex:
                _flash_hilo(f"Error al traer el hilo: {ex}", C_ROJO, 4)
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
        if hilo_mensajes[0]:
            ultimo = hilo_mensajes[0][-1]
            in_reply_to = ultimo.get("message_id", "")
            ref_acum    = ultimo.get("references", "")
            references  = (ref_acum + " " + in_reply_to).strip() if ref_acum else in_reply_to

        btn_enviar_hilo.disabled = True
        ring_hilo.visible        = True
        _flash_hilo("Enviando respuesta...", C_AZUL, 60)
        safe_update(btn_enviar_hilo, ring_hilo)

        def trabajador():
            ok, mensaje = enviar_correos.enviar_respuesta(
                destino, asunto, cuerpo,
                in_reply_to=in_reply_to or None,
                references=references or None,
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

    lbl_cfg_estado = ft.Text("", size=13, font_family="Saira")
    dot_cfg_estado = ft.Container(width=8, height=8, bgcolor=C_TEXTO_3,
                                  border_radius=ft.BorderRadius(4, 4, 4, 4))

    # Referencias del sidebar (se definen abajo, pero las usamos en callbacks)
    smtp_dot_sidebar   = ft.Container(width=8, height=8, bgcolor=C_TEXTO_3,
                                      border_radius=ft.BorderRadius(4, 4, 4, 4))
    smtp_label_sidebar = ft.Text("Verificando...", size=11, color=C_TEXTO_2, font_family="Saira")
    smtp_cuenta_label  = ft.Text(cfg_actual.get("correo") or "Sin cuenta", size=11,
                                  color=C_TEXTO_1, weight=ft.FontWeight.W_500, font_family="Saira")

    def _aplicar_estado_smtp(ok, msg, correo_mostrar):
        """Actualiza ambos: el panel de configuración Y el sidebar."""
        lbl_cfg_estado.value      = msg
        lbl_cfg_estado.color      = C_EXITO if ok else C_ROJO
        dot_cfg_estado.bgcolor    = C_EXITO if ok else C_ROJO
        smtp_dot_sidebar.bgcolor  = C_EXITO if ok else C_ROJO
        smtp_label_sidebar.value  = msg
        smtp_cuenta_label.value   = correo_mostrar or "Sin cuenta"
        safe_update(lbl_cfg_estado, dot_cfg_estado, smtp_dot_sidebar,
                    smtp_label_sidebar, smtp_cuenta_label)

    def guardar_configuracion(e):
        cfg = {
            "correo":        tf_correo.value.strip(),
            "password":      tf_password.value.strip(),
            "limite_diario": int(tf_limite.value.strip() or 250),
            "smtp_host":     tf_smtp_host.value.strip(),
            "smtp_port":     int(tf_smtp_port.value.strip() or 587),
            "imap_host":     tf_imap_host.value.strip(),
        }
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
        lbl_cfg_estado.value     = "Configuración guardada. Verificando conexión..."
        lbl_cfg_estado.color     = C_AZUL
        dot_cfg_estado.bgcolor   = C_NARANJA
        safe_update()

        def verificar():
            ok, msg = enviar_correos.verificar_smtp()
            _aplicar_estado_smtp(ok, msg, cfg["correo"])

        threading.Thread(target=verificar, daemon=True).start()

    def verificar_conexion(e):
        # Verifica usando los valores actuales del formulario, SIN guardar
        correo    = tf_correo.value.strip()
        password  = tf_password.value.strip()
        smtp_host = tf_smtp_host.value.strip()
        smtp_port = tf_smtp_port.value.strip() or "587"

        if not correo or not password:
            lbl_cfg_estado.value   = "Completá correo y contraseña primero."
            lbl_cfg_estado.color   = C_NARANJA
            dot_cfg_estado.bgcolor = C_NARANJA
            safe_update()
            return

        lbl_cfg_estado.value     = "Verificando conexión SMTP..."
        lbl_cfg_estado.color     = C_AZUL
        dot_cfg_estado.bgcolor   = C_NARANJA
        smtp_dot_sidebar.bgcolor = C_NARANJA
        smtp_label_sidebar.value = "Verificando..."
        smtp_cuenta_label.value  = correo
        safe_update()

        def verificar():
            ok, msg = enviar_correos.verificar_smtp(
                correo=correo, password=password,
                smtp_host=smtp_host, smtp_port=smtp_port,
            )
            _aplicar_estado_smtp(ok, msg, correo)

        threading.Thread(target=verificar, daemon=True).start()

    vista_configuracion = ft.Column(
        expand=True,
        spacing=20,
        scroll=ft.ScrollMode.AUTO,
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
                bgcolor=C_BLANCO,
                border_radius=ft.BorderRadius(14, 14, 14, 14),
                border=borde_all(1, C_BORDE),
                padding=ft.Padding(28, 24, 28, 24),
                content=ft.Column(
                    spacing=20,
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.ACCOUNT_CIRCLE_ROUNDED, color=C_MORADO, size=18),
                                ft.Text("Cuenta de envío", size=14, weight=ft.FontWeight.BOLD,
                                        color=C_TEXTO_1, font_family="Saira", expand=True),
                            ],
                        ),
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
            ),
            ft.Container(
                bgcolor=C_BLANCO,
                border_radius=ft.BorderRadius(14, 14, 14, 14),
                border=borde_all(1, C_BORDE),
                padding=ft.Padding(28, 24, 28, 24),
                content=ft.Column(
                    spacing=20,
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.DNS_ROUNDED, color=C_MORADO, size=18),
                                ft.Text("Servidores de correo", size=14, weight=ft.FontWeight.BOLD,
                                        color=C_TEXTO_1, font_family="Saira", expand=True),
                            ],
                        ),
                        ft.Row(spacing=12, controls=[tf_smtp_host, tf_smtp_port]),
                        ft.Row(spacing=12, controls=[tf_imap_host]),
                    ],
                ),
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
                    ft.Row(
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[dot_cfg_estado, lbl_cfg_estado],
                    ),
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
    lbl_topbar_titulo = ft.Text("Gestor de correos masivos", size=20,
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
            lbl_topbar_titulo.value  = "Gestor de correos masivos"
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
            contenedor_vista.content = vista_configuracion
            lbl_topbar_titulo.value  = "Configuración"
            btn_iniciar.visible      = False
        safe_update()

    ir_a_vista[0] = cambiar_vista

    def nav_item(label, icono, vista_key, activo=False):
        cont = ft.Container(
            border_radius=ft.BorderRadius(10, 10, 10, 10),
            bgcolor=C_MORADO_LIGHT if activo else ft.Colors.TRANSPARENT,
            padding=ft.Padding(14, 11, 14, 11),
            on_click=lambda e, vk=vista_key: cambiar_vista(vk),
            ink=True,
            content=ft.Row(
                spacing=12,
                controls=[
                    ft.Icon(icono,
                            color=C_MORADO if activo else C_TEXTO_3,
                            size=20),
                    ft.Text(label,
                            color=C_MORADO if activo else C_TEXTO_2,
                            size=14,
                            weight=ft.FontWeight.BOLD if activo else ft.FontWeight.NORMAL,
                            font_family="Saira"),
                ],
            ),
        )
        nav_items_refs[vista_key] = cont
        return cont

    # Verificación inicial al arrancar
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

    threading.Thread(target=watcher_dashboard, daemon=True).start()

    # ── Header del sidebar con LOGO ITH ──────────────────────────
    logo_path = os.path.join(CARPETA_ACTUAL, "ITH-logo.png")
    if os.path.exists(logo_path):
        sidebar_header = ft.Container(
            bgcolor=C_MORADO,
            padding=ft.Padding(20, 18, 20, 18),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[
                    ft.Image(
                        src="ITH-logo.png",
                        width=140,
                        height=58,
                        fit="contain",
                    ),
                ],
            ),
        )
    else:
        # Fallback al texto si no se encuentra la imagen
        sidebar_header = ft.Container(
            bgcolor=C_MORADO,
            padding=ft.Padding(22, 24, 22, 24),
            content=ft.Column(
                spacing=4,
                controls=[
                    ft.Text("IntelliHelp", size=20, weight=ft.FontWeight.BOLD,
                            color=C_BLANCO, font_family="Saira"),
                    ft.Text("Business Solutions", size=11,
                            color="#ffffffaa", font_family="Saira"),
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
                            nav_item("Respuestas",     ft.Icons.MARK_EMAIL_READ_ROUNDED,   "respuestas"),
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


if __name__ == "__main__":
    ft.app(target=main, assets_dir=CARPETA_ACTUAL)
