import os, csv, json, time, random, smtplib, imaplib, email, email.header, re, mimetypes, logging, base64
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parsedate_to_datetime

# ==========================================
# 1. PARÁMETROS DEL SISTEMA Y LOGS
# ==========================================
CARPETA_ACTUAL = os.path.dirname(os.path.abspath(__file__))

ARCHIVO_LOG = os.path.join(CARPETA_ACTUAL, "sistema_errores.log")
logging.basicConfig(
    filename=ARCHIVO_LOG,
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    encoding="utf-8",
)

ARCHIVO_CONFIG    = os.path.join(CARPETA_ACTUAL, "config.json")
ARCHIVO_CSV       = os.path.join(CARPETA_ACTUAL, "contactos.csv")
LOG_PROGRESO      = os.path.join(CARPETA_ACTUAL, "registro_envios.json")
ARCHIVO_RECHAZOS  = os.path.join(CARPETA_ACTUAL, "registro_rechazados.json")
ARCHIVO_DEPURADOS = os.path.join(CARPETA_ACTUAL, "registro_depurados.json")
ARCHIVO_RESPUESTAS = os.path.join(CARPETA_ACTUAL, "registro_respuestas.json")
CARPETA_HISTORIAL = os.path.join(CARPETA_ACTUAL, "historial")

# Configuración de los correos a enviar
ASUNTO       = "TECNOLOGÍA PARA EMPRESAS: MEJORAR LA PRODUCTIVIDAD Y BAJAR COSTOS"
CORREO_COPIA = "ventas@intellihelp.tech"
URL_WHATSAPP = "https://wa.me/5491150274827?text=Hola,%20me%20interesa%20conocer%20m%C3%A1s%20sobre%20sus%20soluciones."
URL_CALENDLY = "https://calendly.com/rnasif-intellihelp/30min"

TIEMPO_MINIMO, TIEMPO_MAXIMO = 25, 45
FUENTE_BASE = "font-family: 'Saira', Arial, sans-serif;"

ACTIVOS_MULTIMEDIA = [
    ("ITH-logo.png",       "logo_intellihelp"),
    ("icon-process.svg",   "icon_process"),
    ("icon-cost.svg",      "icon_cost"),
    ("icon-prod.svg",      "icon_prod"),
    ("icon-solution.svg",  "icon_solution"),
    ("icon-calendar.svg",  "icon_calendar"),
    ("icon-whatsapp.svg",  "icon_whatsapp"),
]


# ==========================================
# 2. CONFIGURACIÓN DE CUENTA (JSON)
# ==========================================
_CONFIG_DEFAULTS = {
    "correo":        "",
    "password":      "",
    "limite_diario": 250,
    "smtp_host":     "smtp.gmail.com",
    "smtp_port":     587,
    "imap_host":     "imap.gmail.com",
}

def cargar_config():
    if not os.path.exists(ARCHIVO_CONFIG):
        return dict(_CONFIG_DEFAULTS)
    try:
        with open(ARCHIVO_CONFIG, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = dict(_CONFIG_DEFAULTS)
        cfg.update(data)
        return cfg
    except Exception:
        return dict(_CONFIG_DEFAULTS)

def guardar_config(cfg: dict):
    with open(ARCHIVO_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)

def get_config_value(key):
    return cargar_config().get(key, _CONFIG_DEFAULTS.get(key, ""))

def MI_CORREO():    return get_config_value("correo")
def MI_PASSWORD():  return get_config_value("password")
def LIMITE_DIARIO(): return int(get_config_value("limite_diario") or 250)


# ==========================================
# 3. VERIFICACIÓN DE SMTP (acepta credenciales sin guardar)
# ==========================================
def verificar_smtp(correo=None, password=None, smtp_host=None, smtp_port=None):
    """
    Verifica conexión SMTP. Si no se pasan credenciales, las lee de config.json.
    Devuelve (True, "GMAIL SMTP activo") o (False, "mensaje de error").
    """
    cfg = cargar_config()
    correo    = correo    if correo    is not None else cfg.get("correo", "")
    password  = password  if password  is not None else cfg.get("password", "")
    smtp_host = smtp_host if smtp_host is not None else cfg.get("smtp_host", "smtp.gmail.com")
    smtp_port = smtp_port if smtp_port not in (None, "") else cfg.get("smtp_port", 587)
    try:
        smtp_port = int(smtp_port)
    except (ValueError, TypeError):
        smtp_port = 587

    correo    = (correo or "").strip()
    password  = (password or "").strip()
    smtp_host = (smtp_host or "").strip()

    if not correo or not password:
        return False, "Sin credenciales"
    if not smtp_host:
        return False, "Servidor SMTP no configurado"

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(correo, password)
        # Nombre legible del servidor: smtp.gmail.com -> GMAIL
        partes = smtp_host.split('.')
        nombre_host = partes[1].upper() if len(partes) >= 2 else smtp_host.upper()
        return True, f"{nombre_host} SMTP activo"
    except smtplib.SMTPAuthenticationError:
        return False, "Credenciales inválidas"
    except Exception:
        return False, "Error de conexión"


# ==========================================
# 4. GUARDAR Y CARGAR PROGRESO
# ==========================================
def cargar_estado():
    if not os.path.exists(LOG_PROGRESO):
        return {"ultimo_email": "", "fecha": "", "enviados_hoy": 0}
    try:
        with open(LOG_PROGRESO, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"ultimo_email": "", "fecha": "", "enviados_hoy": 0}

def guardar_estado(email_str, enviados, fecha):
    with open(LOG_PROGRESO, "w", encoding="utf-8") as f:
        json.dump({"ultimo_email": email_str, "fecha": fecha, "enviados_hoy": enviados}, f)

def estado_de_hoy():
    """Devuelve (enviados_hoy, ultimo_email) si la fecha guardada coincide con hoy, sino (0, '')."""
    estado = cargar_estado()
    hoy = datetime.now().strftime("%Y-%m-%d")
    if estado.get("fecha") == hoy:
        return int(estado.get("enviados_hoy", 0)), estado.get("ultimo_email", "")
    return 0, ""


# ==========================================
# 5. HISTORIAL POR DÍA
# ==========================================
def _ruta_historial_dia(fecha_str: str) -> str:
    os.makedirs(CARPETA_HISTORIAL, exist_ok=True)
    año, mes, _ = fecha_str.split("-")
    carpeta_mes = os.path.join(CARPETA_HISTORIAL, año, mes)
    os.makedirs(carpeta_mes, exist_ok=True)
    return os.path.join(carpeta_mes, f"{fecha_str}.json")

def cargar_historial_dia(fecha_str: str) -> dict:
    ruta = _ruta_historial_dia(fecha_str)
    if not os.path.exists(ruta):
        return {"fecha": fecha_str, "eventos": [], "enviados": 0, "rebotes": 0}
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"fecha": fecha_str, "eventos": [], "enviados": 0, "rebotes": 0}

def guardar_evento_historial(fecha_str: str, tipo: str, mensaje: str,
                             enviados: int = None, rebotes: int = None):
    data = cargar_historial_dia(fecha_str)
    data["eventos"].append({
        "hora":    datetime.now().strftime("%H:%M:%S"),
        "tipo":    tipo,
        "mensaje": mensaje,
    })
    if enviados is not None:
        data["enviados"] = enviados
    if rebotes is not None:
        data["rebotes"] = rebotes
    ruta = _ruta_historial_dia(fecha_str)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def listar_dias_historial() -> list:
    dias = []
    if not os.path.exists(CARPETA_HISTORIAL):
        return dias
    for año in sorted(os.listdir(CARPETA_HISTORIAL), reverse=True):
        ruta_año = os.path.join(CARPETA_HISTORIAL, año)
        if not os.path.isdir(ruta_año):
            continue
        for mes in sorted(os.listdir(ruta_año), reverse=True):
            ruta_mes = os.path.join(ruta_año, mes)
            if not os.path.isdir(ruta_mes):
                continue
            for arch in sorted(os.listdir(ruta_mes), reverse=True):
                if arch.endswith(".json"):
                    dias.append(arch.replace(".json", ""))
    return dias


# ==========================================
# 6. ARMADO Y ENVÍO DEL CORREO
# ==========================================
def preparar_correo(nombre, destino):
    correo_remitente = MI_CORREO()
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"], msg["Cc"] = (
        f"{ASUNTO} | {nombre}",
        correo_remitente,
        destino,
        CORREO_COPIA,
    )

    msg.set_content(
        f"Estimado/a {nombre}:\n\nAutomatizá tu empresa. Producí más, gastá menos.\n"
        f"Agendá una reunión: {URL_CALENDLY}\nWhatsApp: {URL_WHATSAPP}"
    )

    html = f"""
    <!doctype html><html lang="es"><head><meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Saira:wght@400;500;600;700&display=swap');
        body, p, h1, h2, h3, a, span, div {{ {FUENTE_BASE} }}
        @media only screen and (max-width: 480px) {{
            .m-stack {{ display: block !important; width: 100% !important; margin-bottom: 12px !important; }}
            .m-p-20 {{ padding: 20px !important; }}
            .m-txt-24 {{ font-size: 24px !important; }}
        }}
    </style></head>
    <body style="margin: 0; padding: 24px 16px; background-color: #eeeaf2; -webkit-font-smoothing: antialiased; {FUENTE_BASE}">
      <table width="100%" cellpadding="0" cellspacing="0" style="margin: 0 auto; max-width: 560px; background-color: #ffffff; border-radius: 20px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.04);">
        <tr><td style="padding: 22px 28px; border-bottom: 1px solid #eeeeee;">
            <table width="100%" cellpadding="0" cellspacing="0"><tr>
                <td align="left"><img src="cid:logo_intellihelp" width="130" style="display: block; border: none;" /></td>
                <td align="right"><div style="font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: #663399; font-weight: 600; background-color: #f3eefa; padding: 6px 10px; border-radius: 999px; display: inline-block;">Automatización empresarial</div></td>
            </tr></table>
        </td></tr>
        <tr><td class="m-p-20" style="padding: 32px 28px 28px;">
            <p style="font-size: 15px; color: #5a5d68; margin: 0 0 15px 0;">Estimado/a <strong>{nombre}</strong>,</p>
            <h1 class="m-txt-24" style="font-size: 32px; font-weight: 600; color: #161922; margin: 0 0 12px 0;">Automatizá tu empresa.<br/><span style="color: #663399;">Producí más, gastá menos.</span></h1>
            <p style="font-size: 14px; color: #5a5d68; line-height: 1.5; margin: 0 0 24px 0;">Soluciones a medida que reducen costos operativos y liberan a tu equipo.</p>
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 24px;"><tr>
                <td width="50%" valign="top" class="m-stack">
                  <table width="100%" style="margin-bottom: 14px;"><tr><td width="38"><table width="28" height="28" style="background-color: #f3eefa; border-radius: 8px;"><tr><td align="center"><img src="cid:icon_process" width="14" height="14" style="display:block;"/></td></tr></table></td><td style="font-size: 13px; font-weight: 500; color: #161922;">Automatización de procesos</td></tr></table>
                  <table width="100%"><tr><td width="38"><table width="28" height="28" style="background-color: #f3eefa; border-radius: 8px;"><tr><td align="center"><img src="cid:icon_prod" width="14" height="14" style="display:block;"/></td></tr></table></td><td style="font-size: 13px; font-weight: 500; color: #161922;">Mayor productividad</td></tr></table>
                </td>
                <td width="50%" valign="top" class="m-stack">
                  <table width="100%" style="margin-bottom: 14px;"><tr><td width="38"><table width="28" height="28" style="background-color: #f3eefa; border-radius: 8px;"><tr><td align="center"><img src="cid:icon_cost" width="14" height="14" style="display:block;"/></td></tr></table></td><td style="font-size: 13px; font-weight: 500; color: #161922;">Reducción de costos</td></tr></table>
                  <table width="100%"><tr><td width="38"><table width="28" height="28" style="background-color: #f3eefa; border-radius: 8px;"><tr><td align="center"><img src="cid:icon_solution" width="14" height="14" style="display:block;"/></td></tr></table></td><td style="font-size: 13px; font-weight: 500; color: #161922;">Soluciones a medida</td></tr></table>
                </td>
            </tr></table>
            <table width="100%" cellpadding="0" cellspacing="0"><tr><td align="left">
                <table cellpadding="0" cellspacing="0" align="left" class="m-stack" style="margin-right: 10px;"><tr><td><a href="{URL_CALENDLY}" target="_blank" style="display: block; background-color: #663399; color: #ffffff; font-weight: 600; font-size: 14px; padding: 13px 20px; border-radius: 12px; text-decoration: none;"><img src="cid:icon_calendar" width="14" height="14" style="vertical-align: middle; margin-right: 6px;" /><span style="vertical-align: middle;">Agendá una reunión</span></a></td></tr></table>
                <table cellpadding="0" cellspacing="0" align="left" class="m-stack"><tr><td><a href="{URL_WHATSAPP}" target="_blank" style="display: block; background-color: #25D366; color: #ffffff; font-weight: 600; font-size: 14px; padding: 13px 20px; border-radius: 12px; text-decoration: none;"><img src="cid:icon_whatsapp" width="14" height="14" style="vertical-align: middle; margin-right: 6px;" /><span style="vertical-align: middle;">WhatsApp</span></a></td></tr></table>
            </td></tr></table>
        </td></tr>
        <tr><td style="background-color: #161922; padding: 14px 28px;">
            <table width="100%" cellpadding="0" cellspacing="0"><tr>
                <td align="left" class="m-stack" style="font-size: 12px; color: #ffffff;"><a href="mailto:ventas@intellihelp.tech" style="color: #ffffff; text-decoration: none;">ventas@intellihelp.tech</a><span style="opacity: 0.25; margin: 0 8px;">•</span><a href="https://intellihelp.tech" target="_blank" style="color: #ffffff; text-decoration: none;">intellihelp.tech</a></td>
                <td align="right" class="m-stack" style="font-size: 12px; color: #ffffff; opacity: 0.6;">© 2026 IntelliHelp</td>
            </tr></table>
        </td></tr>
      </table>
    </body></html>
    """
    msg.add_alternative(html, subtype="html")

    for archivo, id_imagen in ACTIVOS_MULTIMEDIA:
        ruta = os.path.join(CARPETA_ACTUAL, archivo)
        if not os.path.exists(ruta):
            continue
        with open(ruta, "rb") as img:
            datos = img.read()
        tipo = (
            "image/svg+xml"
            if archivo.endswith(".svg")
            else mimetypes.guess_type(ruta)[0] or "application/octet-stream"
        )
        t, st = tipo.split("/")
        msg.get_payload()[1].add_related(
            datos, maintype=t, subtype=st, cid=f"<{id_imagen}>"
        )

    return msg


def enviar_correo(msg, destino):
    cfg  = cargar_config()
    host = cfg.get("smtp_host", "smtp.gmail.com")
    port = int(cfg.get("smtp_port", 587))
    try:
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(MI_CORREO(), MI_PASSWORD())
            server.send_message(msg)
        return True
    except smtplib.SMTPRecipientsRefused:
        logging.warning(f"Google avisó que este correo está mal escrito: {destino}")
    except Exception as e:
        logging.error(f"Se cortó internet o hubo un error enviando a {destino}. Detalle: {e}")
    return False


# ==========================================
# 7. REVISIÓN DE REBOTES
# ==========================================
def revisar_rebotes(fecha_actual, enviados_hoy):
    print(f"\nRevisando si algún correo fue devuelto (fecha: {fecha_actual})...")
    rechazados = set()

    cfg       = cargar_config()
    imap_host = cfg.get("imap_host", "imap.gmail.com")

    try:
        with imaplib.IMAP4_SSL(imap_host) as mail:
            mail.login(MI_CORREO(), MI_PASSWORD())
            mail.select("inbox")

            fecha_google = datetime.strptime(fecha_actual, "%Y-%m-%d").strftime("%d-%b-%Y")
            estado, mensajes = mail.search(
                None, f'(FROM "mailer-daemon@googlemail.com" SINCE "{fecha_google}")'
            )

            if estado != "OK" or not mensajes[0]:
                print("Todo excelente. Ningún correo rebotó hoy.")
                guardar_evento_historial(fecha_actual, "success",
                                         "Todo excelente. Ningún correo rebotó hoy.",
                                         enviados=enviados_hoy, rebotes=0)
                return

            for num_id in mensajes[0].split():
                _, datos = mail.fetch(num_id, "(RFC822)")
                for respuesta in datos:
                    if not isinstance(respuesta, tuple):
                        continue
                    correo_recibido = email.message_from_bytes(respuesta[1])
                    texto = ""
                    if correo_recibido.is_multipart():
                        texto = "".join(
                            p.get_payload(decode=True).decode("utf-8", "ignore")
                            for p in correo_recibido.walk()
                            if p.get_content_type() == "text/plain"
                        )
                    else:
                        texto = correo_recibido.get_payload(decode=True).decode("utf-8", "ignore")

                    for c in re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", texto):
                        c_limpio = c.lower()
                        if "daemon" not in c_limpio and MI_CORREO().lower() not in c_limpio:
                            rechazados.add(c_limpio)
                            break

        historial = {}
        if os.path.exists(ARCHIVO_RECHAZOS):
            with open(ARCHIVO_RECHAZOS, "r", encoding="utf-8") as f:
                historial = json.load(f)

        historial[fecha_actual] = {
            "total":   len(rechazados),
            "correos": list(rechazados),
        }
        with open(ARCHIVO_RECHAZOS, "w", encoding="utf-8") as f:
            json.dump(historial, f, indent=4, ensure_ascii=False)

        total_rechazados = len(rechazados)
        porcentaje = (total_rechazados / enviados_hoy * 100) if enviados_hoy > 0 else 0

        resumen = (
            f"Resumen del día: De {enviados_hoy} correos enviados, "
            f"{total_rechazados} rebotaron. (Porcentaje de rechazo: {porcentaje:.2f}%)"
        )
        print(resumen)
        guardar_evento_historial(fecha_actual, "success", resumen,
                                  enviados=enviados_hoy, rebotes=total_rechazados)

    except Exception as e:
        logging.error(f"Hubo un problema intentando leer la bandeja de entrada: {e}")


# ==========================================
# 8. MOTOR PRINCIPAL
# ==========================================
def main():
    limite = LIMITE_DIARIO()
    estado = cargar_estado()
    ultimo_correo = estado.get("ultimo_email", "")
    hoy      = datetime.now().strftime("%Y-%m-%d")
    enviados = estado.get("enviados_hoy", 0) if estado.get("fecha") == hoy else 0

    print(f"\nIniciando programa de envíos. Hoy ya mandamos {enviados} de {limite} posibles.")
    guardar_evento_historial(hoy, "info",
                              f"Sesión iniciada. Enviados hoy: {enviados} / {limite}.",
                              enviados=enviados)

    if enviados >= limite:
        print("Ya llegamos al máximo por hoy. Nos vemos mañana.")
        guardar_evento_historial(hoy, "warning", "Límite diario alcanzado. Sin envíos nuevos.")
        return revisar_rebotes(hoy, enviados)

    if not os.path.exists(ARCHIVO_CSV):
        msg = "Atención: No se encontró el archivo de contactos. Revisar que esté en la misma carpeta."
        print(msg)
        guardar_evento_historial(hoy, "error", msg)
        return

    with open(ARCHIVO_CSV, "r", encoding="utf-8") as f:
        lista_clientes = list(csv.DictReader(f))

    saltar_hasta_ultimo = bool(ultimo_correo)
    if saltar_hasta_ultimo:
        print("Avanzando automáticamente hasta encontrar dónde nos quedamos la última vez...")

    for fila in lista_clientes:
        if enviados >= limite:
            print("\nLlegamos al máximo de envíos por hoy. Pausando programa.")
            guardar_evento_historial(hoy, "warning",
                                      f"Límite diario alcanzado ({limite}). Campaña pausada.",
                                      enviados=enviados)
            break

        destino = (
            fila.get("Correo electrónico")
            or fila.get("Correo electrónico secundario")
            or fila.get("Correo electrónico terciario")
            or ""
        ).strip()

        if not destino:
            continue

        if saltar_hasta_ultimo:
            if destino == ultimo_correo:
                saltar_hasta_ultimo = False
            continue

        nombre = (
            (fila.get("Nombre", "") + " " + fila.get("Apellidos", "")).strip()
            or fila.get("Nombre de Cuenta", "").strip()
            or "Cliente"
        )

        if enviar_correo(preparar_correo(nombre, destino), destino):
            enviados += 1
            guardar_estado(destino, enviados, hoy)
            msg = f"Enviado con éxito a: {destino} (Van {enviados} de {limite})"
            print(msg)
            guardar_evento_historial(hoy, "success", msg, enviados=enviados)

            if enviados < limite:
                espera = random.randint(TIEMPO_MINIMO, TIEMPO_MAXIMO)
                print(f" Esperando {espera} segundos antes del siguiente...")
                time.sleep(espera)
        else:
            msg = f"Error al enviar a: {destino}"
            print(msg)
            guardar_evento_historial(hoy, "error", msg)

    if enviados == 0 and ultimo_correo:
        msg = "No se enviaron correos nuevos. Ya terminamos la lista entera."
        print(f"\n{msg}")
        guardar_evento_historial(hoy, "info", msg)
    else:
        msg = f"Lista finalizada por el momento. Total enviados hoy: {enviados}"
        print(f"\n{msg}")
        guardar_evento_historial(hoy, "info", msg, enviados=enviados)

    revisar_rebotes(hoy, enviados)


# ==========================================
# 9. RECHAZADOS: vista global y depurados
# ==========================================
def cargar_rechazados_todos():
    """Devuelve lista [{email, fecha}] de todos los rechazados conocidos, sin duplicar."""
    if not os.path.exists(ARCHIVO_RECHAZOS):
        return []
    try:
        with open(ARCHIVO_RECHAZOS, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    vistos = {}
    for fecha in sorted(data.keys()):
        bloque = data.get(fecha) or {}
        for c in bloque.get("correos", []):
            c_lower = (c or "").strip().lower()
            if not c_lower:
                continue
            if c_lower not in vistos:
                vistos[c_lower] = {"email": c_lower, "fecha": fecha}
    return list(vistos.values())


def cargar_depurados():
    """Set de correos marcados como ya depurados (ocultos en la pestaña)."""
    if not os.path.exists(ARCHIVO_DEPURADOS):
        return set()
    try:
        with open(ARCHIVO_DEPURADOS, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set((c or "").lower() for c in data.get("depurados", []))
    except Exception:
        return set()


def _guardar_depurados(conjunto):
    with open(ARCHIVO_DEPURADOS, "w", encoding="utf-8") as f:
        json.dump({"depurados": sorted(conjunto)}, f, indent=2, ensure_ascii=False)


def marcar_depurado(email):
    actuales = cargar_depurados()
    actuales.add((email or "").strip().lower())
    _guardar_depurados(actuales)


def desmarcar_depurado(email):
    actuales = cargar_depurados()
    actuales.discard((email or "").strip().lower())
    _guardar_depurados(actuales)


# ==========================================
# 10. ESTADÍSTICAS GLOBALES (todos los días)
# ==========================================
def obtener_estadisticas_globales():
    """Suma enviados/rechazados de todo el historial. Devuelve también serie por día."""
    total_env = 0
    total_reb = 0
    serie = []
    if not os.path.exists(CARPETA_HISTORIAL):
        return {"total_enviados": 0, "total_rechazados": 0, "serie": []}

    for año in sorted(os.listdir(CARPETA_HISTORIAL)):
        ruta_año = os.path.join(CARPETA_HISTORIAL, año)
        if not os.path.isdir(ruta_año):
            continue
        for mes in sorted(os.listdir(ruta_año)):
            ruta_mes = os.path.join(ruta_año, mes)
            if not os.path.isdir(ruta_mes):
                continue
            for arch in sorted(os.listdir(ruta_mes)):
                if not arch.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(ruta_mes, arch), "r", encoding="utf-8") as f:
                        d = json.load(f)
                    env = int(d.get("enviados", 0) or 0)
                    reb = int(d.get("rebotes", 0) or 0)
                    total_env += env
                    total_reb += reb
                    serie.append({"fecha": arch.replace(".json", ""),
                                  "enviados": env, "rechazados": reb})
                except Exception:
                    continue

    return {"total_enviados": total_env, "total_rechazados": total_reb, "serie": serie}


# ==========================================
# 11. CONTACTOS: utilidades
# ==========================================
def emails_de_contactos():
    """Devuelve set de todos los correos válidos del CSV (los 3 campos)."""
    correos = set()
    if not os.path.exists(ARCHIVO_CSV):
        return correos
    try:
        with open(ARCHIVO_CSV, "r", encoding="utf-8") as f:
            for fila in csv.DictReader(f):
                for campo in ("Correo electrónico",
                              "Correo electrónico secundario",
                              "Correo electrónico terciario"):
                    valor = (fila.get(campo) or "").strip().lower()
                    if valor:
                        correos.add(valor)
    except Exception:
        pass
    return correos


def contar_contactos():
    """Cuenta filas válidas del CSV sin cargarlas todas en memoria."""
    if not os.path.exists(ARCHIVO_CSV):
        return 0
    total = 0
    try:
        with open(ARCHIVO_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for _ in reader:
                total += 1
    except Exception:
        return 0
    return total


# ==========================================
# 12. RESPUESTAS DE CLIENTES + CALENDLY (IMAP)
# ==========================================
_DOMINIOS_CALENDLY = ("calendly.com",)


def _cargar_respuestas_archivo():
    if not os.path.exists(ARCHIVO_RESPUESTAS):
        return {"respuestas": [], "calendly": []}
    try:
        with open(ARCHIVO_RESPUESTAS, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("respuestas", [])
        data.setdefault("calendly", [])
        return data
    except Exception:
        return {"respuestas": [], "calendly": []}


def _guardar_respuestas_archivo(data):
    with open(ARCHIVO_RESPUESTAS, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def cargar_respuestas():
    """API pública: devuelve dict {respuestas: [...], calendly: [...]}."""
    return _cargar_respuestas_archivo()


def enviar_respuesta(destino, asunto, cuerpo, in_reply_to=None, references=None):
    """Envía un correo de texto plano usando las credenciales SMTP configuradas.
    Si se pasa in_reply_to/references, los agrega para que Gmail mantenga el thread.
    Devuelve (ok: bool, mensaje: str)."""
    cfg = cargar_config()
    correo   = (cfg.get("correo")   or "").strip()
    password = (cfg.get("password") or "").strip()
    host     = (cfg.get("smtp_host") or "smtp.gmail.com").strip()
    try:
        port = int(cfg.get("smtp_port", 587) or 587)
    except (ValueError, TypeError):
        port = 587

    destino = (destino or "").strip()
    asunto  = (asunto  or "").strip()
    cuerpo  = cuerpo or ""

    if not correo or not password:
        return False, "Sin credenciales en config.json"
    if not destino:
        return False, "Falta el destinatario"
    if not asunto:
        return False, "Falta el asunto"

    msg = EmailMessage()
    msg["Subject"]    = asunto
    msg["From"]       = correo
    msg["To"]         = destino
    # Date con timezone local de la PC (ej: -0300 si estás en Buenos Aires)
    msg["Date"]       = formatdate(localtime=True)
    # Message-ID propio para que las respuestas posteriores hagan threading bien
    try:
        dominio = correo.split("@", 1)[1] if "@" in correo else "localhost"
        msg["Message-ID"] = make_msgid(domain=dominio)
    except Exception:
        msg["Message-ID"] = make_msgid()
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    msg.set_content(cuerpo)

    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls()
            server.login(correo, password)
            server.send_message(msg)
        return True, "Correo enviado"
    except smtplib.SMTPAuthenticationError:
        return False, "Credenciales inválidas"
    except smtplib.SMTPRecipientsRefused:
        return False, "Destinatario rechazado"
    except Exception as e:
        logging.error(f"Error enviando respuesta a {destino}: {e}")
        return False, f"Error de envío: {e}"


# ==========================================
# 13. HILO DE CONVERSACIÓN (IMAP: INBOX + Sent)
# ==========================================
_BUZONES_SENT = [
    '"[Gmail]/Sent Mail"',
    '"[Gmail]/Enviados"',
    '"Sent"',
    '"Enviados"',
    '"[Google Mail]/Sent Mail"',
]


def _parse_mensaje_imap(raw_msg, direccion):
    asunto    = _decodificar_cabecera(raw_msg.get("Subject", ""))
    fecha     = _decodificar_cabecera(raw_msg.get("Date", ""))
    remitente = _decodificar_cabecera(raw_msg.get("From", ""))
    destino   = _decodificar_cabecera(raw_msg.get("To", ""))
    msg_id    = (raw_msg.get("Message-ID", "") or "").strip()
    in_reply  = (raw_msg.get("In-Reply-To", "") or "").strip()
    refs      = (raw_msg.get("References", "") or "").strip()

    # Extracción rica: texto plano, HTML con cid resueltos, y markdown
    texto, html, _imgs = _partes_correo(raw_msg)
    body_md = _html_a_markdown(html) if html else (texto or "")
    if len(body_md) > 16000:
        body_md = body_md[:16000] + "\n\n_[... mensaje truncado ...]_"

    # Convertir fecha RFC2822 a datetime para ordenar
    ts = ""
    try:
        dt = parsedate_to_datetime(raw_msg.get("Date", ""))
        if dt:
            ts = dt.isoformat()
    except Exception:
        pass

    return {
        "direccion":   direccion,
        "from":        remitente,
        "from_email":  _extraer_email(remitente),
        "to":          destino,
        "subject":     asunto,
        "date":        fecha,
        "ts":          ts,
        "message_id":  msg_id,
        "in_reply_to": in_reply,
        "references":  refs,
        "body":        texto or body_md,
        "body_md":     body_md,
        "has_html":    bool(html),
    }


def obtener_hilo(remitente, asunto=None, dias=180):
    """Trae los correos enviados/recibidos con `remitente` en los últimos `dias`,
    filtrando por `asunto` (base, sin Re:/Fwd:) si se pasa.
    Devuelve lista ordenada cronológicamente."""
    cfg = cargar_config()
    imap_host = cfg.get("imap_host", "imap.gmail.com")
    if not MI_CORREO() or not MI_PASSWORD() or not remitente:
        return []

    desde = (datetime.now() - timedelta(days=int(dias or 180))).strftime("%d-%b-%Y")
    remitente = remitente.strip().lower()
    asunto_base = re.sub(r"^\s*(Re:|Fwd?:)\s*", "", asunto or "",
                          flags=re.IGNORECASE).strip().lower()
    mensajes = []
    vistos_ids = set()

    def _agregar(raw_msg, direccion):
        m = _parse_mensaje_imap(raw_msg, direccion)
        clave = m["message_id"] or f"{m['direccion']}|{m['ts']}|{m['subject'][:80]}"
        if clave in vistos_ids:
            return
        vistos_ids.add(clave)
        mensajes.append(m)

    try:
        with imaplib.IMAP4_SSL(imap_host) as mail:
            mail.login(MI_CORREO(), MI_PASSWORD())

            # ── Recibidos (FROM remitente) ───────────────────────────
            try:
                mail.select("inbox", readonly=True)
                estado, ids = mail.search(
                    None, f'(FROM "{remitente}" SINCE "{desde}")'
                )
                if estado == "OK" and ids and ids[0]:
                    for num in ids[0].split():
                        try:
                            _, fetched = mail.fetch(num, "(RFC822)")
                            for r in fetched:
                                if isinstance(r, tuple):
                                    _agregar(email.message_from_bytes(r[1]), "entrante")
                        except Exception:
                            continue
            except Exception:
                pass

            # ── Enviados (TO remitente) ──────────────────────────────
            for buzon in _BUZONES_SENT:
                try:
                    estado, _ = mail.select(buzon, readonly=True)
                    if estado != "OK":
                        continue
                    estado, ids = mail.search(
                        None, f'(TO "{remitente}" SINCE "{desde}")'
                    )
                    if estado == "OK" and ids and ids[0]:
                        for num in ids[0].split():
                            try:
                                _, fetched = mail.fetch(num, "(RFC822)")
                                for r in fetched:
                                    if isinstance(r, tuple):
                                        _agregar(email.message_from_bytes(r[1]),
                                                  "saliente")
                            except Exception:
                                continue
                        break  # usamos el primer buzón que matchea
                except Exception:
                    continue
    except Exception as e:
        logging.error(f"Error obteniendo hilo de {remitente}: {e}")
        return []

    # Filtrar por asunto base si se pidió: el subject limpio del mensaje
    # debe contener el asunto base de la conversación.
    if asunto_base:
        def _coincide(msg):
            sub = re.sub(r"^\s*(Re:|Fwd?:)\s*", "", msg.get("subject", "") or "",
                         flags=re.IGNORECASE).strip().lower()
            return asunto_base in sub or sub in asunto_base

        mensajes = [m for m in mensajes if _coincide(m)]

    mensajes.sort(key=lambda m: m.get("ts", ""))
    return mensajes


def _extraer_email(cabecera):
    if not cabecera:
        return ""
    m = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", cabecera)
    return m.group(0).lower() if m else ""


def _decodificar_cabecera(valor):
    if not valor:
        return ""
    try:
        partes = email.header.decode_header(valor)
        salida = []
        for texto, enc in partes:
            if isinstance(texto, bytes):
                salida.append(texto.decode(enc or "utf-8", errors="ignore"))
            else:
                salida.append(texto)
        return "".join(salida)
    except Exception:
        return str(valor)


def _texto_correo(mensaje):
    if mensaje.is_multipart():
        partes = []
        for p in mensaje.walk():
            if p.get_content_type() == "text/plain":
                try:
                    partes.append(p.get_payload(decode=True).decode("utf-8", "ignore"))
                except Exception:
                    continue
        return "\n".join(partes)
    try:
        return mensaje.get_payload(decode=True).decode("utf-8", "ignore")
    except Exception:
        return ""


def _partes_correo(mensaje):
    """Devuelve (texto_plano, html, imagenes_cid) extraídos del mensaje.
    `imagenes_cid` es dict {cid: data_url_base64} para imágenes embebidas."""
    texto = []
    html  = []
    imgs  = {}

    if mensaje.is_multipart():
        for p in mensaje.walk():
            ctype = p.get_content_type()
            cdisp = str(p.get("Content-Disposition") or "").lower()

            if ctype == "text/plain" and "attachment" not in cdisp:
                try:
                    texto.append(p.get_payload(decode=True).decode("utf-8", "ignore"))
                except Exception:
                    pass
            elif ctype == "text/html" and "attachment" not in cdisp:
                try:
                    html.append(p.get_payload(decode=True).decode("utf-8", "ignore"))
                except Exception:
                    pass
            elif ctype.startswith("image/"):
                cid = (p.get("Content-ID") or "").strip().strip("<>").strip()
                if cid:
                    try:
                        data = p.get_payload(decode=True)
                        b64  = base64.b64encode(data).decode("ascii")
                        imgs[cid] = f"data:{ctype};base64,{b64}"
                    except Exception:
                        pass
    else:
        try:
            payload = mensaje.get_payload(decode=True).decode("utf-8", "ignore")
            if mensaje.get_content_type() == "text/html":
                html.append(payload)
            else:
                texto.append(payload)
        except Exception:
            pass

    texto_final = "\n".join(texto).strip()
    html_final  = "\n".join(html).strip()

    # Reemplazar cid: por data URLs base64 directamente en el HTML
    if html_final and imgs:
        for cid, durl in imgs.items():
            html_final = html_final.replace(f"cid:{cid}", durl)
            html_final = html_final.replace(f'"cid:{cid}"', f'"{durl}"')
            html_final = html_final.replace(f"'cid:{cid}'", f"'{durl}'")

    return texto_final, html_final, imgs


def _html_a_markdown(html_str):
    """Conversión HTML→Markdown sin dependencias externas. Preserva bold/italic,
    links, imágenes (incluso data: URLs), saltos de línea y headings."""
    if not html_str:
        return ""

    s = html_str

    # Quitar bloques que no aportan
    s = re.sub(r"<style[^>]*>.*?</style>", "", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<script[^>]*>.*?</script>", "", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<head[^>]*>.*?</head>",   "", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<!--.*?-->",              "", s, flags=re.DOTALL)

    # Saltos de línea estructurales
    s = re.sub(r"<br\s*/?>",                  "\n",   s, flags=re.IGNORECASE)
    s = re.sub(r"</p\s*>",                    "\n\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</(?:div|tr|li|h[1-6])\s*>", "\n",   s, flags=re.IGNORECASE)
    s = re.sub(r"<li[^>]*>",                  "- ",   s, flags=re.IGNORECASE)
    s = re.sub(r"<hr\s*/?>",                  "\n---\n", s, flags=re.IGNORECASE)

    # Headings
    s = re.sub(r"<h([1-6])[^>]*>",
               lambda m: "\n" + "#" * int(m.group(1)) + " ", s,
               flags=re.IGNORECASE)

    # Énfasis
    s = re.sub(r"<(?:strong|b)\s*>", "**", s, flags=re.IGNORECASE)
    s = re.sub(r"</(?:strong|b)\s*>", "**", s, flags=re.IGNORECASE)
    s = re.sub(r"<(?:em|i)\s*>",     "*",  s, flags=re.IGNORECASE)
    s = re.sub(r"</(?:em|i)\s*>",    "*",  s, flags=re.IGNORECASE)

    # Links: <a href="X">Y</a> -> [Y](X)
    s = re.sub(
        r'<a[^>]*href\s*=\s*["\']([^"\']*)["\'][^>]*>(.*?)</a>',
        lambda m: f"[{re.sub(r'<[^>]+>', '', m.group(2)).strip() or m.group(1)}]({m.group(1)})",
        s, flags=re.IGNORECASE | re.DOTALL,
    )

    # Imágenes: <img src="X" alt="Y"> -> ![Y](X)
    def _img_repl(m):
        tag = m.group(0)
        src = re.search(r'src\s*=\s*["\']([^"\']*)["\']', tag, flags=re.IGNORECASE)
        alt = re.search(r'alt\s*=\s*["\']([^"\']*)["\']', tag, flags=re.IGNORECASE)
        url = src.group(1) if src else ""
        txt = alt.group(1) if alt else ""
        if not url:
            return ""
        return f"![{txt}]({url})"
    s = re.sub(r"<img[^>]*/?>", _img_repl, s, flags=re.IGNORECASE)

    # Quitar tags restantes
    s = re.sub(r"<[^>]+>", "", s)

    # Decodificar entidades HTML (&amp;, &nbsp;, &quot;, etc.)
    try:
        import html as _html_mod
        s = _html_mod.unescape(s)
    except Exception:
        pass

    # Limpieza de whitespace
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}",   "\n\n", s)
    s = "\n".join(line.rstrip() for line in s.split("\n"))
    return s.strip()


def detectar_respuestas_y_calendly(dias=30):
    """
    Busca por IMAP en los últimos `dias`:
      - Respuestas: correos cuyo From coincide con un contacto del CSV.
      - Calendly: correos de Calendly cuya confirmación menciona un contacto del CSV.
    Persiste en registro_respuestas.json y devuelve el dict.
    """
    cfg = cargar_config()
    imap_host = cfg.get("imap_host", "imap.gmail.com")
    if not MI_CORREO() or not MI_PASSWORD():
        return _cargar_respuestas_archivo()

    contactos = emails_de_contactos()
    if not contactos:
        return _cargar_respuestas_archivo()

    data = _cargar_respuestas_archivo()
    vistos_resp = {(r.get("uid"), r.get("from")) for r in data["respuestas"]}
    vistos_cal  = {c.get("uid") for c in data["calendly"]}

    try:
        desde = datetime.now() - timedelta(days=int(dias))
    except Exception:
        desde = datetime.now() - timedelta(days=30)
    fecha_imap = desde.strftime("%d-%b-%Y")

    try:
        with imaplib.IMAP4_SSL(imap_host) as mail:
            mail.login(MI_CORREO(), MI_PASSWORD())
            mail.select("inbox")

            estado, msgs = mail.search(None, f'(SINCE "{fecha_imap}")')
            if estado != "OK" or not msgs or not msgs[0]:
                _guardar_respuestas_archivo(data)
                return data

            ids = msgs[0].split()
            for num_id in ids:
                try:
                    _, fetched = mail.fetch(num_id, "(RFC822)")
                except Exception:
                    continue
                for respuesta in fetched:
                    if not isinstance(respuesta, tuple):
                        continue
                    msg = email.message_from_bytes(respuesta[1])
                    remitente_raw = _decodificar_cabecera(msg.get("From", ""))
                    remitente     = _extraer_email(remitente_raw)
                    asunto        = _decodificar_cabecera(msg.get("Subject", ""))
                    fecha_msg     = _decodificar_cabecera(msg.get("Date", ""))
                    uid           = msg.get("Message-ID", "") or num_id.decode("utf-8", "ignore")

                    if not remitente or "daemon" in remitente:
                        continue
                    if remitente == (MI_CORREO() or "").lower():
                        continue

                    es_calendly = any(d in remitente for d in _DOMINIOS_CALENDLY)

                    if es_calendly:
                        if uid in vistos_cal:
                            continue
                        cuerpo = _texto_correo(msg)
                        invitado = ""
                        for c in re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
                                            cuerpo):
                            cl = c.lower()
                            if cl in contactos:
                                invitado = cl
                                break
                        data["calendly"].append({
                            "uid":      uid,
                            "from":     remitente,
                            "subject":  asunto,
                            "date":     fecha_msg,
                            "invitado": invitado,
                        })
                        vistos_cal.add(uid)
                    elif remitente in contactos:
                        clave = (uid, remitente)
                        if clave in vistos_resp:
                            continue
                        data["respuestas"].append({
                            "uid":     uid,
                            "from":    remitente,
                            "subject": asunto,
                            "date":    fecha_msg,
                        })
                        vistos_resp.add(clave)
    except Exception as e:
        logging.error(f"No se pudo escanear respuestas: {e}")

    _guardar_respuestas_archivo(data)
    return data


if __name__ == "__main__":
    main()
