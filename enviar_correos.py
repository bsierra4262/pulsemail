import os, csv, json, time, random, smtplib, imaplib, email, re, mimetypes, logging
from datetime import datetime
from email.message import EmailMessage

# ==========================================
# 1. PARÁMETROS DEL SISTEMA Y LOGS
# ==========================================
CARPETA_ACTUAL = os.path.dirname(os.path.abspath(__file__))

# Caja Negra: Acá se anotan los errores graves sin asustar al usuario en la pantalla
ARCHIVO_LOG = os.path.join(CARPETA_ACTUAL, "sistema_errores.log")
logging.basicConfig(
    filename=ARCHIVO_LOG,
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    encoding="utf-8",
)

MI_CORREO, MI_PASSWORD = "", ""

# Archivos de lectura y guardado
ARCHIVO_CSV = os.path.join(CARPETA_ACTUAL, "contactos.csv")
LOG_PROGRESO = os.path.join(CARPETA_ACTUAL, "registro_envios.json")
ARCHIVO_RECHAZOS = os.path.join(CARPETA_ACTUAL, "registro_rechazados.json")

# Configuración de los correos a enviar
LIMITE_DIARIO = 250
ASUNTO = "TECNOLOGIA PARA EMPRESAS: MEJORAR LA PRODUCTIVIDAD Y BAJAR COSTOS"
CORREO_COPIA = "ventas@intellihelp.tech"
URL_WHATSAPP = "https://wa.me/5491150274827?text=Hola,%20me%20interesa%20conocer%20m%C3%A1s%20sobre%20sus%20soluciones."
URL_CALENDLY = "https://calendly.com/rnasif-intellihelp/30min"

TIEMPO_MINIMO, TIEMPO_MAXIMO = 25, 45
FUENTE_BASE = "font-family: 'Saira', Arial, sans-serif;"

# Fotos e íconos que van a ir pegados adentro del correo
ACTIVOS_MULTIMEDIA = [
    ("ITH-logo.png", "logo_intellihelp"),
    ("icon-process.svg", "icon_process"),
    ("icon-cost.svg", "icon_cost"),
    ("icon-prod.svg", "icon_prod"),
    ("icon-solution.svg", "icon_solution"),
    ("icon-calendar.svg", "icon_calendar"),
    ("icon-whatsapp.svg", "icon_whatsapp"),
]


# ==========================================
# 2. GUARDAR Y CARGAR PROGRESO
# ==========================================
def cargar_estado():
    # Lee nuestro archivo de guardado para no arrancar de cero si cerramos el programa.
    if not os.path.exists(LOG_PROGRESO):
        return {"ultimo_email": "", "fecha": "", "enviados_hoy": 0}

    try:
        with open(LOG_PROGRESO, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Si el archivo se rompió por algún motivo, empezamos de cero sin hacer ruido.
        return {"ultimo_email": "", "fecha": "", "enviados_hoy": 0}


def guardar_estado(email_str, enviados, fecha):
    # Anota por qué cliente vamos para recordar el progreso.
    with open(LOG_PROGRESO, "w", encoding="utf-8") as f:
        json.dump(
            {"ultimo_email": email_str, "fecha": fecha, "enviados_hoy": enviados}, f
        )


# ==========================================
# 3. ARMADO Y ENVÍO DEL CORREO
# ==========================================
def preparar_correo(nombre, destino):
    # Arma la "carta" completa: textos, diseño y destinatarios.
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"], msg["Cc"] = (
        f"{ASUNTO} | {nombre}",
        MI_CORREO,
        destino,
        CORREO_COPIA,
    )

    # Texto simple por si el cliente del usuario tiene bloqueado el diseño visual
    msg.set_content(
        f"Estimado/a {nombre}:\n\nAutomatizá tu empresa. Producí más, gastá menos.\nAgendá una reunión: {URL_CALENDLY}\nWhatsApp: {URL_WHATSAPP}"
    )

    # Diseño visual
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

    # Pega las imágenes adentro del correo para que no salgan rotas ni las bloqueen
    for archivo, id_imagen in ACTIVOS_MULTIMEDIA:
        ruta = os.path.join(CARPETA_ACTUAL, archivo)
        if not os.path.exists(ruta):
            continue

        with open(ruta, "rb") as img:
            datos = img.read()

        # Le avisa al correo si es una foto normal o un vector (SVG)
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
    # Se conecta a Google y despacha el correo.
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(MI_CORREO, MI_PASSWORD)
            server.send_message(msg)
        return True
    except smtplib.SMTPRecipientsRefused:
        logging.warning(f"Google avisó que este correo está mal escrito: {destino}")
    except Exception as e:
        logging.error(
            f"Se cortó internet o hubo un error enviando a {destino}. Detalle: {e}"
        )
    return False


# ==========================================
# 4. REVISIÓN DE REBOTES (CORREOS QUE NO EXISTEN)
# ==========================================
def revisar_rebotes(fecha_actual, enviados_hoy):
    # Entra a la cuenta a leer los avisos de Google sobre correos que no existen.
    print(f"\nRevisando si algún correo fue devuelto (fecha: {fecha_actual})...")
    rechazados = set()

    try:
        with imaplib.IMAP4_SSL("imap.gmail.com") as mail:
            mail.login(MI_CORREO, MI_PASSWORD)
            mail.select("inbox")

            fecha_google = datetime.strptime(fecha_actual, "%Y-%m-%d").strftime(
                "%d-%b-%Y"
            )
            estado, mensajes = mail.search(
                None, f'(FROM "mailer-daemon@googlemail.com" SINCE "{fecha_google}")'
            )

            # Si no hay avisos de correos devueltos, salimos de esta función rápido (Early Return).
            if estado != "OK" or not mensajes[0]:
                print("Todo excelente. Ningún correo rebotó hoy.")
                return

            # Busca la dirección de email dentro del texto que nos mandó Google
            for num_id in mensajes[0].split():
                _, datos = mail.fetch(num_id, "(RFC822)")
                for respuesta in datos:
                    if not isinstance(respuesta, tuple):
                        continue

                    correo_recibido = email.message_from_bytes(respuesta[1])

                    # Lee todo el texto del aviso
                    texto = ""
                    if correo_recibido.is_multipart():
                        texto = "".join(
                            p.get_payload(decode=True).decode("utf-8", "ignore")
                            for p in correo_recibido.walk()
                            if p.get_content_type() == "text/plain"
                        )
                    else:
                        texto = correo_recibido.get_payload(decode=True).decode(
                            "utf-8", "ignore"
                        )

                    # Atrapa cualquier dirección que tenga un '@'
                    for c in re.findall(
                        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", texto
                    ):
                        c_limpio = c.lower()
                        # Si no es nuestro correo ni el del sistema de Google, lo guardamos.
                        if (
                            "daemon" not in c_limpio
                            and MI_CORREO.lower() not in c_limpio
                        ):
                            rechazados.add(c_limpio)
                            break

        # Actualiza el archivo de historial de rechazos
        historial = {}
        if os.path.exists(ARCHIVO_RECHAZOS):
            with open(ARCHIVO_RECHAZOS, "r", encoding="utf-8") as f:
                historial = json.load(f)

        historial[fecha_actual] = {
            "total": len(rechazados),
            "correos": list(rechazados),
        }

        with open(ARCHIVO_RECHAZOS, "w", encoding="utf-8") as f:
            json.dump(historial, f, indent=4)

        # Cálculo matemático para imprimirle la estadística clara al usuario
        total_rechazados = len(rechazados)
        porcentaje = (total_rechazados / enviados_hoy * 100) if enviados_hoy > 0 else 0

        print(
            f"Resumen del día: De {enviados_hoy} correos enviados, {total_rechazados} rebotaron. (Porcentaje de rechazo: {porcentaje:.2f}%)"
        )

    except Exception as e:
        logging.error(f"Hubo un problema intentando leer la bandeja de entrada: {e}")


# ==========================================
# 5. MOTOR PRINCIPAL
# ==========================================
def main():
    estado = cargar_estado()
    ultimo_correo = estado.get("ultimo_email", "")
    hoy = datetime.now().strftime("%Y-%m-%d")
    enviados = estado.get("enviados_hoy", 0) if estado.get("fecha") == hoy else 0

    print(
        f"\nIniciando programa de envíos. Hoy ya mandamos {enviados} de {LIMITE_DIARIO} posibles."
    )

    # Regla de guarda: Si ya llegamos al máximo, ni entramos a la lista.
    if enviados >= LIMITE_DIARIO:
        print("Ya llegamos al máximo por hoy. Nos vemos mañana.")
        return revisar_rebotes(hoy, enviados)

    if not os.path.exists(ARCHIVO_CSV):
        print(
            "Atención: No se encontró el archivo de contactos. Revisar que esté en la misma carpeta."
        )
        return

    with open(ARCHIVO_CSV, "r", encoding="utf-8") as f:
        lista_clientes = list(csv.DictReader(f))

    # Control de reanudación
    saltar_hasta_ultimo = bool(ultimo_correo)
    if saltar_hasta_ultimo:
        print(
            "Avanzando automáticamente hasta encontrar dónde nos quedamos la última vez..."
        )

    for i, fila in enumerate(lista_clientes):
        if enviados >= LIMITE_DIARIO:
            print("\nLlegamos al máximo de envíos por hoy. Pausando programa.")
            break

        # Agarra el primer correo que no esté vacío en esas 3 columnas
        destino = (
            fila.get("Correo electrónico")
            or fila.get("Correo electrónico secundario")
            or fila.get("Correo electrónico terciario")
            or ""
        ).strip()

        if not destino:
            continue

        # Adelanta rápido hasta llegar al cliente que se cortó la vez pasada
        if saltar_hasta_ultimo:
            if destino == ultimo_correo:
                saltar_hasta_ultimo = False
            continue

        nombre = (
            (fila.get("Nombre", "") + " " + fila.get("Apellidos", "")).strip()
            or fila.get("Nombre de Cuenta", "").strip()
            or "Cliente"
        )

        # Intenta mandar el correo
        if enviar_correo(preparar_correo(nombre, destino), destino):
            enviados += 1
            guardar_estado(destino, enviados, hoy)
            print(f"Enviado con éxito a: {destino} (Van {enviados} de {LIMITE_DIARIO})")

            # Pausa para no parecer un robot mandando a lo loco
            if enviados < LIMITE_DIARIO:
                espera = random.randint(TIEMPO_MINIMO, TIEMPO_MAXIMO)
                print(f" Esperando {espera} segundos antes del siguiente...")
                time.sleep(espera)

    if enviados == 0 and ultimo_correo:
        print("\nNo se enviaron correos nuevos. Ya terminamos la lista entera.")
    else:
        print(f"\nLista finalizada por el momento. Total enviados hoy: {enviados}")

    revisar_rebotes(hoy, enviados)


if __name__ == "__main__":
    main()
