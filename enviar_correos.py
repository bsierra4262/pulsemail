import os, csv, json, time, random, smtplib, imaplib, email, re, mimetypes
from datetime import datetime
from email.message import EmailMessage

# ==========================================
# 1. PARÁMETROS DEL SISTEMA
# ==========================================
CARPETA_ACTUAL = os.path.dirname(os.path.abspath(__file__))

MI_CORREO = ""
MI_PASSWORD = ""

ARCHIVO_CSV = os.path.join(CARPETA_ACTUAL, "contactos.csv")
LOG_PROGRESO = os.path.join(CARPETA_ACTUAL, "registro_envios.json")
ARCHIVO_RECHAZOS = os.path.join(CARPETA_ACTUAL, "registro_rechazados.json")

LIMITE_DIARIO = 250
ASUNTO = "TECNOLOGIA PARA EMPRESAS: MEJORAR LA PRODUCTIVIDAD Y BAJAR COSTOS"
CORREO_COPIA = "ventas@intellihelp.tech"

URL_WHATSAPP = "https://wa.me/5491150274827?text=Hola,%20me%20interesa%20conocer%20m%C3%A1s%20sobre%20sus%20soluciones."
URL_CALENDLY = "https://calendly.com/rnasif-intellihelp/30min"

TIEMPO_MINIMO = 25
TIEMPO_MAXIMO = 45

FUENTE_BASE = "font-family: 'Saira', Arial, sans-serif;"

# Lista de imágenes a adjuntar (Nombre del archivo en PC -> ID interno para el HTML)
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
# 2. MANEJO DE ESTADO (GUARDAR/CARGAR PROGRESO)
# ==========================================
def cargar_estado_ejecucion():
    """
    Lee el archivo JSON para saber dónde nos quedamos en la ejecución anterior.
    Esto evita que empecemos desde cero si el programa se cierra.
    """
    if os.path.exists(LOG_PROGRESO):
        try:
            with open(LOG_PROGRESO, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(
                "[ADVERTENCIA] El archivo de progreso está roto. Empezaremos a contar desde cero."
            )

    # Código de compatibilidad por si aún existe el viejo archivo .txt
    txt_legado = os.path.join(CARPETA_ACTUAL, "ultimo_enviado.txt")
    if os.path.exists(txt_legado):
        with open(txt_legado, "r", encoding="utf-8") as f:
            return {"ultimo_email": f.read().strip(), "fecha": "", "enviados_hoy": 0}

    return {"ultimo_email": "", "fecha": "", "enviados_hoy": 0}


def persistir_estado(email_str, enviados, fecha):
    """
    Guarda el correo actual y la cantidad de envíos en un JSON.
    Se hace después de cada envío exitoso para no perder el progreso.
    """
    with open(LOG_PROGRESO, "w", encoding="utf-8") as f:
        json.dump(
            {"ultimo_email": email_str, "fecha": fecha, "enviados_hoy": enviados},
            f,
            indent=4,
        )


# ==========================================
# 3. ARMADO Y ENVÍO DEL CORREO
# ==========================================
def _inyectar_recursos(msg_obj):
    """
    Toma las imágenes locales y las incrusta dentro del código del correo.
    MIME es el estándar de internet para enviar archivos adjuntos o imágenes.
    """
    for nombre_archivo, cid in ACTIVOS_MULTIMEDIA:
        ruta = os.path.join(CARPETA_ACTUAL, nombre_archivo)
        if not os.path.exists(ruta):
            print(
                f"[ADVERTENCIA] No encontré la imagen '{nombre_archivo}'. Se enviará el correo sin ella."
            )
            continue

        with open(ruta, "rb") as img:
            datos = img.read()

        tipo_mime, _ = mimetypes.guess_type(ruta)
        tipo_mime = tipo_mime or (
            "image/svg+xml"
            if nombre_archivo.endswith(".svg")
            else "application/octet-stream"
        )
        tipo, subtipo = tipo_mime.split("/")
        msg_obj.get_payload()[1].add_related(
            datos, maintype=tipo, subtype=subtipo, cid=f"<{cid}>"
        )


def _ensamblar_mensaje(nombre_completo, correo_destino):
    """
    Fabrica el paquete de datos a enviar (Payload).
    Junta el Asunto, Destinatario, Texto Simple y el código HTML.
    """
    msg = EmailMessage()
    msg["Subject"] = f"{ASUNTO} | {nombre_completo}"
    msg["From"] = MI_CORREO
    msg["To"] = correo_destino
    msg["Cc"] = CORREO_COPIA

    # Versión simple por si el cliente no soporta HTML
    txt_plano = (
        f"Estimado/a {nombre_completo}:\n\nAutomatizá tu empresa. Producí más, gastá menos.\n\n"
        f"Soluciones tecnológicas a medida que reducen costos operativos y liberan a tu equipo.\n\n"
        f"Agendá una reunión: {URL_CALENDLY}\nWhatsApp: {URL_WHATSAPP}"
    )
    msg.set_content(txt_plano)

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
            <p style="font-size: 15px; color: #5a5d68; margin: 0 0 15px 0;">Estimado/a <strong>{nombre_completo}</strong>,</p>
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
    _inyectar_recursos(msg)
    return msg


def _transmitir_via_smtp(msg, destino):
    """
    Abre una conexión segura (socket) con Google y despacha el correo.
    Retorna True si fue exitoso, o False si falló.
    """
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()  # Asegura que la contraseña viaje encriptada
        server.login(MI_CORREO, MI_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except smtplib.SMTPRecipientsRefused:
        print(
            f"[ADVERTENCIA] Google rechazó el envío de inmediato (el correo destino es inválido): {destino}"
        )
    except Exception as e:
        print(
            f"[ERROR] Falló la conexión a internet o al servidor intentando enviar a {destino}: {e}"
        )
    return False


# ==========================================
# 4. REVISIÓN DE REBOTES (LECTURA DE BANDEJA IMAP)
# ==========================================
def auditar_rebotes_diarios(fecha_actual, enviados_totales_hoy):
    """
    Se conecta a la bandeja de entrada para leer correos nuevos.
    Busca avisos de 'Mail Delivery Subsystem' (DSN) que indican que un correo no existe (Hard Bounce).
    """
    print(
        f"\n[SISTEMA] Revisando la bandeja de entrada buscando correos devueltos (Hard Bounces) para la fecha: {fecha_actual}"
    )
    rechazados_hoy = set()

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(MI_CORREO, MI_PASSWORD)
        mail.select("inbox")

        # Formatea la fecha para que el servidor de Google la entienda
        fecha_imap = datetime.strptime(fecha_actual, "%Y-%m-%d").strftime("%d-%b-%Y")

        # Busca correos enviados por el sistema automático de devoluciones
        status, mensajes = mail.search(
            None, f'(FROM "mailer-daemon@googlemail.com" SINCE "{fecha_imap}")'
        )

        if status == "OK" and mensajes[0]:
            for num_id in mensajes[0].split():
                _, msg_data = mail.fetch(num_id, "(RFC822)")
                for respuesta in msg_data:
                    if not isinstance(respuesta, tuple):
                        continue

                    msg_correo = email.message_from_bytes(respuesta[1])
                    cuerpo = ""

                    # Lee el contenido del correo devuelto para encontrar a quién intentamos enviar
                    if msg_correo.is_multipart():
                        for part in msg_correo.walk():
                            if part.get_content_type() == "text/plain":
                                cuerpo += part.get_payload(decode=True).decode(
                                    "utf-8", errors="ignore"
                                )
                    else:
                        cuerpo = msg_correo.get_payload(decode=True).decode(
                            "utf-8", errors="ignore"
                        )

                    # Usa una expresión regular (RegEx) para extraer direcciones de email del texto
                    correos = re.findall(
                        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", cuerpo
                    )
                    for c in [x.lower() for x in correos]:
                        # Ignoramos nuestro propio correo y los correos del sistema
                        if (
                            "mailer-daemon" not in c
                            and "postmaster" not in c
                            and MI_CORREO.lower() not in c
                        ):
                            rechazados_hoy.add(c)
                            break

        mail.logout()

        # Guarda la lista de rebotados en un archivo JSON sin borrar los días anteriores
        historial = {}
        if os.path.exists(ARCHIVO_RECHAZOS):
            try:
                with open(ARCHIVO_RECHAZOS, "r", encoding="utf-8") as f:
                    historial = json.load(f)
            except json.JSONDecodeError:
                pass

        historial[fecha_actual] = {
            "total": len(rechazados_hoy),
            "correos": list(rechazados_hoy),
        }
        with open(ARCHIVO_RECHAZOS, "w", encoding="utf-8") as f:
            json.dump(historial, f, indent=4)

        tasa = (
            (len(rechazados_hoy) / enviados_totales_hoy * 100)
            if enviados_totales_hoy > 0
            else 0
        )
        print(f"\n[INFO] --- REPORTE DE ENTREGAS Y REBOTES ({fecha_actual}) ---")
        print(
            f"[INFO] Correos transmitidos: {enviados_totales_hoy} | Rebotados: {len(rechazados_hoy)} | Tasa de error: {tasa:.2f}%"
        )

    except Exception as e:
        print(f"[ERROR] Problema al leer la bandeja de entrada (IMAP): {e}")


# ==========================================
# 5. ORQUESTADOR (FUNCIÓN PRINCIPAL)
# ==========================================
def main():
    estado = cargar_estado_ejecucion()
    ultimo_idx = estado.get("ultimo_email", "")
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    enviados_hoy = (
        estado.get("enviados_hoy", 0) if estado.get("fecha") == fecha_hoy else 0
    )

    print(
        f"\n[SISTEMA] Iniciando programa principal (Daemon). Cuota utilizada hoy: {enviados_hoy}/{LIMITE_DIARIO}"
    )

    if enviados_hoy >= LIMITE_DIARIO:
        print(
            "[SISTEMA] Ya alcanzaste el límite de envíos diarios permitidos. Terminando programa."
        )
        return auditar_rebotes_diarios(fecha_hoy, enviados_hoy)

    if not os.path.exists(ARCHIVO_CSV):
        return print(
            f"[ERROR] No se encontró el archivo de Excel/CSV en la ruta: {ARCHIVO_CSV}"
        )

    # Lee todos los clientes de una vez y los guarda en memoria RAM
    with open(ARCHIVO_CSV, mode="r", encoding="utf-8") as f:
        registros = list(csv.DictReader(f))

    procesando_activo = not bool(ultimo_idx)
    if ultimo_idx:
        print(
            f"[INFO] Buscando al último cliente procesado ({ultimo_idx}) para continuar desde ahí..."
        )

    for i, fila in enumerate(registros):
        if enviados_hoy >= LIMITE_DIARIO:
            print("[SISTEMA] Se llegó al máximo de envíos permitidos en este momento.")
            break

        # Busca en las tres columnas de email, usa la primera que tenga datos
        destino = (
            fila.get("Correo electrónico")
            or fila.get("Correo electrónico secundario")
            or fila.get("Correo electrónico terciario")
            or ""
        ).strip()
        if not destino:
            continue

        if not procesando_activo:
            if destino == ultimo_idx:
                procesando_activo = True
            continue

        nombre = f"{fila.get('Nombre', '').strip()} {fila.get('Apellidos', '').strip()}".strip()
        nombre = nombre or fila.get("Nombre de Cuenta", "").strip() or "Cliente"

        mensaje = _ensamblar_mensaje(nombre, destino)

        # Intenta enviar el correo
        if _transmitir_via_smtp(mensaje, destino):
            enviados_hoy += 1
            persistir_estado(destino, enviados_hoy, fecha_hoy)
            print(
                f"[Envío {i + 1}/{len(registros)}] (Total hoy: {enviados_hoy}) -> Entregado al servidor destino: {destino}"
            )

            # Si no hemos llegado al límite, hacemos una pausa antes del siguiente cliente
            if enviados_hoy < LIMITE_DIARIO:
                pausa = random.randint(TIEMPO_MINIMO, TIEMPO_MAXIMO)
                print(
                    f"  [SISTEMA] Pausa aleatoria (Jitter) de {pausa}s para simular comportamiento humano (Prevención Anti-Spam)."
                )
                time.sleep(pausa)

    if enviados_hoy == 0 and ultimo_idx:
        print(
            "\n[ADVERTENCIA] No se envió nada. O llegaste al final del archivo, o el último correo no existe en la lista."
        )
    else:
        print(
            f"\n[SISTEMA] Ciclo finalizado. Total de correos procesados hoy: {enviados_hoy}"
        )

    auditar_rebotes_diarios(fecha_hoy, enviados_hoy)


# Esta línea asegura que el código solo corra si ejecutamos este archivo directamente
if __name__ == "__main__":
    main()
