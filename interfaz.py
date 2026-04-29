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

        match_rebote = re.search(r"(\d+) rebotaron", linea)
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
    def kpi_card(titulo, widget_valor, subtitulo, color_acento, bg_acento):
        return ft.Container(
            expand=True,
            bgcolor=C_BLANCO,
            border_radius=ft.BorderRadius(14, 14, 14, 14),
            border=borde_all(1, C_BORDE),
            padding=ft.Padding(24, 20, 24, 20),
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

    card_enviados = kpi_card("Enviados hoy",  lbl_enviados, "correos salientes", C_MORADO,  C_MORADO_LIGHT)
    card_limite   = kpi_card("Límite diario", lbl_limite,   "cuota configurada", C_TEXTO_2, C_FONDO)
    card_rebotes  = kpi_card("Rebotes",       lbl_rebotes,  "sin entrega",       C_ROJO,    C_ROJO_LIGHT)
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
        page.update()

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
        page.update()

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
        page.update()

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
                page.update()

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
        page.update()

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
        page.update()

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
    # PANEL CONTACTOS
    # ==========================================
    tabla_contactos_rows = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Nombre", font_family="Saira", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Apellido", font_family="Saira", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text("Cuenta", font_family="Saira", weight=ft.FontWeight.BOLD)),
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

    lbl_contactos_total = ft.Text("", size=12, color=C_TEXTO_3, font_family="Saira")
    lbl_csv_path        = ft.Text("", size=11, color=C_TEXTO_3, font_family="Saira", italic=True)

    def cargar_contactos():
        ruta = enviar_correos.ARCHIVO_CSV
        tabla_contactos_rows.rows.clear()
        if not os.path.exists(ruta):
            lbl_contactos_total.value = "Archivo contactos.csv no encontrado"
            lbl_csv_path.value = ruta
            page.update()
            return
        lbl_csv_path.value = ruta
        total = 0
        with open(ruta, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for fila in reader:
                total += 1
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
        lbl_contactos_total.value = f"{total} contacto{'s' if total != 1 else ''} en total"
        page.update()

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
                    lbl_contactos_total,
                    ft.ElevatedButton(
                        "Recargar CSV",
                        icon=ft.Icons.REFRESH_ROUNDED,
                        on_click=lambda e: cargar_contactos(),
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
        lbl_hist_stats.value = f"Enviados: {env}  •  Rebotes: {reb}"
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
        page.update()

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
                                content=ft.Text(f"{reb} reb.", size=11, color=C_ROJO,
                                                font_family="Saira"),
                            ),
                        ],
                    ),
                )
            )
        page.update()

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
        page.update()

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
        page.update()

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
            page.update()
            return

        lbl_cfg_estado.value     = "Verificando conexión SMTP..."
        lbl_cfg_estado.color     = C_AZUL
        dot_cfg_estado.bgcolor   = C_NARANJA
        smtp_dot_sidebar.bgcolor = C_NARANJA
        smtp_label_sidebar.value = "Verificando..."
        smtp_cuenta_label.value  = correo
        page.update()

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

    def nav_item(label, icono, vista_key, activo=False):
        def on_click(e):
            for k, c in nav_items_refs.items():
                c.bgcolor = ft.Colors.TRANSPARENT
                c.content.controls[0].color = C_TEXTO_3
                c.content.controls[1].color = C_TEXTO_2
                c.content.controls[1].weight = ft.FontWeight.NORMAL
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
            page.update()

        cont = ft.Container(
            border_radius=ft.BorderRadius(10, 10, 10, 10),
            bgcolor=C_MORADO_LIGHT if activo else ft.Colors.TRANSPARENT,
            padding=ft.Padding(14, 11, 14, 11),
            on_click=on_click,
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
            page.update()
            return
        ok, msg = enviar_correos.verificar_smtp()
        _aplicar_estado_smtp(ok, msg, cfg_i.get("correo", ""))

    threading.Thread(target=verificar_smtp_inicial, daemon=True).start()

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
                            nav_item("Dashboard",      ft.Icons.DASHBOARD_ROUNDED,  "dashboard",     True),
                            nav_item("Contactos",      ft.Icons.PEOPLE_ALT_ROUNDED, "contactos"),
                            nav_item("Historial",      ft.Icons.HISTORY_ROUNDED,    "historial"),
                            nav_item("Configuración",  ft.Icons.SETTINGS_ROUNDED,   "configuracion"),
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
