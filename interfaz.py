import flet as ft
import threading
import os
import sys
import re
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
        self.fn_agregar_log = fn_agregar_log
        self.fn_actualizar_metricas = fn_actualizar_metricas
        self.buffer = ""

    def write(self, texto):
        self.buffer += texto
        if "\n" in self.buffer:
            lineas = self.buffer.split("\n")
            for linea in lineas[:-1]:
                if linea.strip():
                    self._procesar_linea(linea.strip())
            self.buffer = lineas[-1]

    def _procesar_linea(self, linea):
        tipo = "info"
        lower = linea.lower()
        if "éxito" in lower or "excelente" in lower or "finalizada" in lower or "enviado" in lower:
            tipo = "success"
        elif "advertencia" in lower or "atención" in lower or "máximo" in lower or "pausando" in lower:
            tipo = "warning"
        elif "error" in lower or "problema" in lower or "falló" in lower or "no se encontró" in lower:
            tipo = "error"

        self.fn_agregar_log(tipo, linea)

        match_envio = re.search(r"\(Van (\d+) de (\d+)\)", linea)
        if match_envio:
            self.fn_actualizar_metricas(match_envio.group(1), match_envio.group(2), None)

        match_rebote = re.search(r"(\d+) rebotaron", linea)
        if match_rebote:
            match_total = re.search(r"De (\d+) correos", linea)
            enviados = match_total.group(1) if match_total else "0"
            self.fn_actualizar_metricas(enviados, str(enviar_correos.LIMITE_DIARIO), match_rebote.group(1))

    def flush(self):
        pass


# ==========================================
# 3. INTERFAZ GRÁFICA PRINCIPAL
# ==========================================
def main(page: ft.Page):
    page.title = "IntelliHelp — Motor de Campañas"
    page.window.width      = 1200
    page.window.height     = 820
    page.window.min_width  = 960
    page.window.min_height = 660
    page.bgcolor    = C_FONDO
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding    = 0
    page.fonts = {
        "Saira": "https://fonts.gstatic.com/s/saira/v14/memXYa2wxmKQyPMrZX79wwYZQMhsyuShhKMjjbU9uXuA.woff2"
    }
    page.theme = ft.Theme(font_family="Saira")

    # ── Estado global ──────────────────────────────────────────────
    enviados_val   = [0]
    limite_val     = [enviar_correos.LIMITE_DIARIO]
    rebotes_val    = [0]
    campana_activa = [False]

    # ── KPI labels ────────────────────────────────────────────────
    lbl_enviados = ft.Text("0",   size=38, weight=ft.FontWeight.BOLD, color=C_MORADO,  font_family="Saira")
    lbl_limite   = ft.Text(str(enviar_correos.LIMITE_DIARIO), size=38, weight=ft.FontWeight.BOLD, color=C_TEXTO_1, font_family="Saira")
    lbl_rebotes  = ft.Text("0",   size=38, weight=ft.FontWeight.BOLD, color=C_ROJO,    font_family="Saira")
    lbl_tasa     = ft.Text("0%",  size=38, weight=ft.FontWeight.BOLD, color=C_VERDE,   font_family="Saira")

    # Barra de progreso
    barra_progreso   = ft.ProgressBar(value=0, color=C_VERDE, bgcolor=C_BORDE, height=6,
                                      border_radius=ft.BorderRadius(4, 4, 4, 4))
    lbl_progreso_pct = ft.Text(f"0 / {enviar_correos.LIMITE_DIARIO}", size=12,
                               color=C_TEXTO_3, font_family="Saira")

    lista_actividad = ft.ListView(
        expand=True, spacing=8,
        padding=ft.Padding(16, 12, 16, 12),
        auto_scroll=True,
    )
    texto_estado = ft.Text("Listo para iniciar", size=13, color=C_TEXTO_3,
                           italic=True, font_family="Saira")
    ring_estado  = ft.ProgressRing(color=C_VERDE, width=22, height=22,
                                   stroke_width=2.5, visible=False)

    # ── Borde helper ──────────────────────────────────────────────
    def borde_all(w, color):
        s = ft.BorderSide(w, color)
        return ft.Border(s, s, s, s)

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

    card_enviados = kpi_card("Enviados hoy",   lbl_enviados, "correos salientes", C_MORADO,  C_MORADO_LIGHT)
    card_limite   = kpi_card("Limite diario",  lbl_limite,   "cuota configurada", C_TEXTO_2, C_FONDO)
    card_rebotes  = kpi_card("Rebotes",        lbl_rebotes,  "sin entrega",       C_ROJO,    C_ROJO_LIGHT)
    card_tasa     = kpi_card("Tasa de exito",  lbl_tasa,     "de entregas",       C_VERDE,   C_VERDE_LIGHT)

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

        barra_progreso.value = min(env / lim, 1.0)
        lbl_progreso_pct.value = f"{env} / {lim}"
        tasa = max(0, (env - reb) / env * 100) if env > 0 else 0
        lbl_tasa.value = f"{tasa:.1f}%"
        page.update()

    # ── Log de eventos ────────────────────────────────────────────
    TIPOS_LOG = {
        "success": (C_EXITO,   C_EXITO_LIGHT,   ft.Icons.CHECK_CIRCLE_ROUNDED,  "EXITO"),
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
        lista_actividad.controls.append(fila)
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
        campana_activa[0]    = True
        btn_iniciar.disabled = True
        ring_estado.visible  = True
        texto_estado.value   = "Campana en ejecucion..."
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
                texto_estado.value   = "Campana finalizada."
                btn_iniciar.content  = _contenido_btn("Iniciar campana", ft.Icons.SEND_ROUNDED)
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
        content=_contenido_btn("Iniciar campana", ft.Icons.SEND_ROUNDED),
    )

    def limpiar_log(e):
        lista_actividad.controls.clear()
        page.update()

    btn_limpiar = ft.TextButton(
        "Limpiar historial",
        on_click=limpiar_log,
        style=ft.ButtonStyle(color=C_TEXTO_3),
    )

    # ── Sidebar ───────────────────────────────────────────────────
    def nav_item(label, icono, activo=False):
        return ft.Container(
            border_radius=ft.BorderRadius(10, 10, 10, 10),
            bgcolor=C_MORADO_LIGHT if activo else ft.Colors.TRANSPARENT,
            padding=ft.Padding(14, 11, 14, 11),
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
                ft.Container(
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
                ),
                ft.Container(height=16),
                ft.Container(
                    padding=ft.Padding(14, 0, 14, 0),
                    content=ft.Column(
                        spacing=4,
                        controls=[
                            nav_item("Dashboard",     ft.Icons.DASHBOARD_ROUNDED,     True),
                            nav_item("Contactos",     ft.Icons.PEOPLE_ALT_ROUNDED),
                            nav_item("Historial",     ft.Icons.HISTORY_ROUNDED),
                            nav_item("Configuracion", ft.Icons.SETTINGS_ROUNDED),
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
                            ft.Text("", size=11,
                                    color=C_TEXTO_1, weight=ft.FontWeight.W_500,
                                    font_family="Saira"),
                            ft.Container(height=4),
                            ft.Row(
                                spacing=6,
                                controls=[
                                    ft.Container(width=8, height=8, bgcolor=C_EXITO,
                                                 border_radius=ft.BorderRadius(4, 4, 4, 4)),
                                    ft.Text("Gmail SMTP activo", size=11,
                                            color=C_TEXTO_2, font_family="Saira"),
                                ],
                            ),
                        ],
                    ),
                ),
            ],
        ),
    )

    # ── Topbar ────────────────────────────────────────────────────
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
                        ft.Text("Gestor de correos masivos", size=20,
                                weight=ft.FontWeight.BOLD, color=C_TEXTO_1,
                                font_family="Saira"),
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

    # ── Paneles ───────────────────────────────────────────────────
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
                        ft.Text("Progreso de campana", size=13, weight=ft.FontWeight.BOLD,
                                color=C_TEXTO_1, font_family="Saira"),
                        ft.Container(expand=True),
                        lbl_progreso_pct,
                    ],
                ),
                barra_progreso,
            ],
        ),
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
                            btn_limpiar,
                        ],
                    ),
                ),
                ft.Container(expand=True, content=lista_actividad),
            ],
        ),
    )

    # ── Layout raíz ───────────────────────────────────────────────
    contenido_principal = ft.Column(
        expand=True,
        spacing=0,
        controls=[
            topbar,
            ft.Container(
                expand=True,
                padding=ft.Padding(28, 28, 28, 28),
                content=ft.Column(
                    expand=True,
                    spacing=20,
                    controls=[panel_kpis, panel_progreso, panel_log],
                ),
            ),
        ],
    )

    page.add(
        ft.Row(
            expand=True,
            spacing=0,
            controls=[sidebar, contenido_principal],
        )
    )


if __name__ == "__main__":
    ft.app(target=main, assets_dir=CARPETA_ACTUAL)
