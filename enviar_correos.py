import smtplib, csv, time, os, random, mimetypes, json, imaplib, email, re
from datetime import datetime
from email.message import EmailMessage
# ==========================================
# 1. CONFIGURACIÓN
# ==========================================
CARPETA_ACTUAL = os.path.dirname(os.path.abspath(__file__))

MI_CORREO = ""
MI_PASSWORD = ""

ARCHIVO_CSV = os.path.join(CARPETA_ACTUAL, "contactos.csv")
LOG_PROGRESO = os.path.join(CARPETA_ACTUAL, "registro_envios.json")
ARCHIVO_TXT_VIEJO = os.path.join(CARPETA_ACTUAL, "ultimo_enviado.txt")
ARCHIVO_RECHAZOS = os.path.join(CARPETA_ACTUAL, "registro_rechazados.json") # NUEVO: Archivo de rechazados

LIMITE_DIARIO = 250  
ASUNTO = "TECNOLOGIA PARA EMPRESAS: MEJORAR LA PRODUCTIVIDAD Y BAJAR COSTOS"
CORREO_COPIA = "ventas@intellihelp.tech"

# --- CONFIGURACIÓN DE ENLACES PARA LOS BOTONES ---
URL_WHATSAPP = "https://wa.me/5491150274827?text=Hola,%20me%20interesa%20conocer%20m%C3%A1s%20sobre%20sus%20soluciones."
URL_CALENDLY = "https://calendly.com/rnasif-intellihelp/30min" 

# --- CONFIGURACIÓN DE PAUSA ---
TIEMPO_MINIMO = 25  
TIEMPO_MAXIMO = 45  

# ==========================================
# 2. FUNCIONES AUXILIARES
# ==========================================
def leer_registro():
    if os.path.exists(LOG_PROGRESO):
        try:
            with open(LOG_PROGRESO, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
            
    if os.path.exists(ARCHIVO_TXT_VIEJO):
        with open(ARCHIVO_TXT_VIEJO, "r", encoding="utf-8") as f:
            email_viejo = f.read().strip()
            return {"ultimo_email": email_viejo, "fecha": "", "enviados_hoy": 0}
            
    return {"ultimo_email": "", "fecha": "", "enviados_hoy": 0}

def guardar_registro(email_str, enviados, fecha):
    datos = {
        "ultimo_email": email_str,
        "fecha": fecha,
        "enviados_hoy": enviados
    }
    with open(LOG_PROGRESO, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=4)

# --- FUNCION PARA ADJUNTAR IMÁGENES ---
def adjuntar_imagen(msg_obj, nombre_archivo, cid):
    ruta = os.path.join(CARPETA_ACTUAL, nombre_archivo)
    try:
        with open(ruta, 'rb') as img_file:
            imagen_data = img_file.read()
            tipo_mime = mimetypes.guess_type(ruta)[0]
            if tipo_mime is None:
                if nombre_archivo.endswith('.svg'):
                    tipo_mime = 'image/svg+xml'
                else:
                    tipo_mime = 'application/octet-stream'
            tipo_principal, sub_tipo = tipo_mime.split('/')
            msg_obj.get_payload()[1].add_related(imagen_data, maintype=tipo_principal, subtype=sub_tipo, cid=f"<{cid}>")
    except FileNotFoundError:
        print(f"⚠️ ADVERTENCIA: No se encontró la imagen '{nombre_archivo}'.")

# ==========================================
# NUEVO: 2.5 FUNCION PARA LEER REBOTES (IMAP)
# ==========================================
def procesar_rebotes_del_dia(fecha_actual, enviados_totales_hoy):
    print("\n--- 🔍 REVISANDO BANDEJA EN BUSCA DE CORREOS RECHAZADOS ---")
    rechazados_hoy = set()
    
    try:
        # Conectar a Gmail por IMAP
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(MI_CORREO, MI_PASSWORD)
        mail.select("inbox")

        # Formatear fecha para la búsqueda IMAP (Ej. 27-Apr-2026)
        fecha_dt = datetime.strptime(fecha_actual, "%Y-%m-%d")
        meses_imap = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        fecha_imap = f"{fecha_dt.day:02d}-{meses_imap[fecha_dt.month - 1]}-{fecha_dt.year}"

        # Buscar correos del Mail Delivery Subsystem recibidos hoy
        status, mensajes = mail.search(None, f'(FROM "mailer-daemon@googlemail.com" SINCE "{fecha_imap}")')

        if status == 'OK':
            lista_ids = mensajes[0].split()
            for num_id in lista_ids:
                res, msg_data = mail.fetch(num_id, '(RFC822)')
                for respuesta in msg_data:
                    if isinstance(respuesta, tuple):
                        msg_correo = email.message_from_bytes(respuesta[1])
                        cuerpo = ""
                        # Extraer el texto del correo
                        if msg_correo.is_multipart():
                            for part in msg_correo.walk():
                                if part.get_content_type() == "text/plain":
                                    try:
                                        cuerpo += part.get_payload(decode=True).decode('utf-8', errors='ignore')
                                    except:
                                        pass
                        else:
                            try:
                                cuerpo = msg_correo.get_payload(decode=True).decode('utf-8', errors='ignore')
                            except:
                                pass
                        
                        # Extraer todos los emails del cuerpo del mensaje de error
                        correos_en_cuerpo = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', cuerpo)
                        for c in correos_en_cuerpo:
                            c_limpio = c.lower()
                            # Filtrar para no guardar nuestro propio correo ni el del sistema
                            if "mailer-daemon" not in c_limpio and "postmaster" not in c_limpio and MI_CORREO.lower() not in c_limpio:
                                rechazados_hoy.add(c_limpio)
                                break # El primer correo encontrado suele ser el rechazado

        mail.logout()

        # Guardar historial en JSON
        historial_rechazos = {}
        if os.path.exists(ARCHIVO_RECHAZOS):
            with open(ARCHIVO_RECHAZOS, "r", encoding="utf-8") as f:
                try:
                    historial_rechazos = json.load(f)
                except:
                    pass
        
        cantidad_rechazos = len(rechazados_hoy)
        historial_rechazos[fecha_actual] = {
            "total_rechazados": cantidad_rechazos,
            "correos": list(rechazados_hoy)
        }

        with open(ARCHIVO_RECHAZOS, "w", encoding="utf-8") as f:
            json.dump(historial_rechazos, f, indent=4)

        # Calcular porcentaje
        porcentaje = 0
        if enviados_totales_hoy > 0:
            porcentaje = (cantidad_rechazos / enviados_totales_hoy) * 100

        print(f"\n📊 --- REPORTE DE REBOTES ({fecha_actual}) ---")
        print(f"📩 Total enviados hoy: {enviados_totales_hoy}")
        print(f"❌ Total rechazados: {cantidad_rechazos}")
        print(f"📈 Porcentaje de rechazo: {porcentaje:.2f}%")
        print(f"📁 Detalle guardado en: {ARCHIVO_RECHAZOS}\n")

    except Exception as e:
        print(f"⚠️ Error al revisar rebotes (IMAP): {e}\n(Asegúrate de que el acceso IMAP esté habilitado en la configuración de tu Gmail).")


# ==========================================
# 3. PROCESO DE ENVÍO
# ==========================================
registro = leer_registro()
ultimo_email_enviado = registro["ultimo_email"]
fecha_hoy = datetime.now().strftime("%Y-%m-%d")

if registro["fecha"] == fecha_hoy:
    enviados_hoy = registro["enviados_hoy"]
else:
    enviados_hoy = 0

try:
    print("\n--- INICIANDO PROCESO DE ENVÍOS MASIVOS ---")
    print(f"📅 Fecha actual: {fecha_hoy}")
    print(f"📊 Correos ya enviados hoy: {enviados_hoy} / {LIMITE_DIARIO}")

    if enviados_hoy >= LIMITE_DIARIO:
        print("\n✅ Ya has alcanzado tu límite de 250 correos por el día de hoy.")
        print("Vuelve a ejecutar este script mañana para continuar automáticamente.")
        # NUEVO: Llama a la revisión de rebotes aunque haya llegado al límite
        procesar_rebotes_del_dia(fecha_hoy, enviados_hoy)
        exit()

    if ultimo_email_enviado:
        print(f"Último cliente procesado: {ultimo_email_enviado}")
        print("Buscando en la lista para continuar desde el siguiente...")
    else:
        print("No hay registro anterior. Iniciando desde el principio de la lista.")

    with open(ARCHIVO_CSV, mode='r', encoding='utf-8') as file:
        reader = list(csv.DictReader(file))
        total_filas = len(reader)
        
        empezar_envio = False if ultimo_email_enviado else True

        for i, fila in enumerate(reader):
            if enviados_hoy >= LIMITE_DIARIO:
                print(f"\n✅ Se alcanzó el límite diario de {LIMITE_DIARIO} envíos. Deteniendo...")
                break

            correo_destino = fila.get('Correo electrónico', '').strip()
            if not correo_destino:
                correo_destino = fila.get('Correo electrónico secundario', '').strip()
            if not correo_destino:
                correo_destino = fila.get('Correo electrónico terciario', '').strip()
            if not correo_destino:
                continue

            if not empezar_envio:
                if correo_destino == ultimo_email_enviado:
                    empezar_envio = True 
                continue

            nombre_pila = fila.get('Nombre', '').strip()
            apellido = fila.get('Apellidos', '').strip()
            nombre_completo = f"{nombre_pila} {apellido}".strip()

            if not nombre_completo:
                nombre_completo = fila.get('Nombre de Cuenta', '').strip()
            if not nombre_completo: 
                nombre_completo = 'Cliente'

            msg = EmailMessage()
            msg['Subject'] = f"{ASUNTO} | {nombre_completo}"
            msg['From'] = MI_CORREO
            msg['To'] = correo_destino
            msg['Cc'] = CORREO_COPIA
            
            # 1. Versión en Texto Plano
            cuerpo_texto = f"Estimado/a {nombre_completo}:\n\nAutomatizá tu empresa. Producí más, gastá menos.\n\nSoluciones tecnológicas a medida que reducen costos operativos y liberan a tu equipo para lo que realmente importa.\n\nAgendá una reunión: {URL_CALENDLY}\nWhatsApp: {URL_WHATSAPP}"
            msg.set_content(cuerpo_texto)

            fuente = "font-family: 'Saira', Arial, sans-serif;"

            # 2. Versión en HTML
            cuerpo_html = f"""
            <!doctype html>
            <html lang="es">
            <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <title>IntelliHelp</title>
            <style>
                @import url('https://fonts.googleapis.com/css2?family=Saira:wght@400;500;600;700&display=swap');
                body, p, h1, h2, h3, a, span, div {{ {fuente} }}
                @media only screen and (max-width: 480px) {{
                    .m-stack {{ display: block !important; width: 100% !important; margin-bottom: 12px !important; }}
                    .m-p-20 {{ padding: 20px !important; }}
                    .m-txt-24 {{ font-size: 24px !important; }}
                    .m-btn {{ width: 100% !important; box-sizing: border-box !important; text-align: center !important; }}
                }}
            </style>
            </head>
            <body style="margin: 0; padding: 24px 16px; background-color: #eeeaf2; -webkit-font-smoothing: antialiased; {fuente}">
            
              <table width="100%" cellpadding="0" cellspacing="0" style="margin: 0 auto; max-width: 560px; background-color: #ffffff; border-radius: 20px; overflow: hidden; box-shadow: 0 4px 10px rgba(22,25,34,0.04);">
                
                <tr>
                  <td style="padding: 22px 28px; border-bottom: 1px solid #eeeeee;">
                    <table width="100%" cellpadding="0" cellspacing="0">
                      <tr>
                        <td align="left" valign="middle">
                          <img src="cid:logo_intellihelp" alt="IntelliHelp" width="130" style="display: block; border: none; height: auto;" />
                        </td>
                        <td align="right" valign="middle">
                          <div style="font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: #663399; font-weight: 600; background-color: #f3eefa; padding: 6px 10px; border-radius: 999px; display: inline-block; {fuente}">
                            Automatización empresarial
                          </div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <tr>
                  <td class="m-p-20" style="padding: 32px 28px 28px;">
                    <p style="margin: 0 0 15px 0; font-size: 15px; color: #5a5d68; {fuente}">Estimado/a <strong style="{fuente}">{nombre_completo}</strong>,</p>
                    <h1 class="m-txt-24" style="margin: 0 0 12px 0; font-size: 32px; line-height: 1.08; font-weight: 600; letter-spacing: -0.02em; color: #161922; {fuente}">
                      Automatizá tu empresa.<br/>
                      <span style="color: #663399; {fuente}">Producí más, gastá menos.</span>
                    </h1>
                    <p style="font-size: 14px; color: #5a5d68; margin: 0 0 24px 0; line-height: 1.5; {fuente}">
                      Soluciones tecnológicas a medida que reducen costos operativos y liberan a tu equipo para lo que realmente importa.
                    </p>

                    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 24px;">
                      <tr>
                        <td width="50%" valign="top" class="m-stack">
                          
                          <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 14px;">
                            <tr>
                              <td width="38" valign="middle">
                                <table width="28" height="28" cellpadding="0" cellspacing="0" style="background-color: #f3eefa; border-radius: 8px;">
                                  <tr><td align="center" valign="middle">
                                    <img src="cid:icon_process" width="14" height="14" style="display: block; border: none;" />
                                  </td></tr>
                                </table>
                              </td>
                              <td valign="middle" style="font-size: 13px; font-weight: 500; color: #161922; {fuente}">Automatización de procesos</td>
                            </tr>
                          </table>
                          
                          <table width="100%" cellpadding="0" cellspacing="0">
                            <tr>
                              <td width="38" valign="middle">
                                <table width="28" height="28" cellpadding="0" cellspacing="0" style="background-color: #f3eefa; border-radius: 8px;">
                                  <tr><td align="center" valign="middle">
                                    <img src="cid:icon_prod" width="14" height="14" style="display: block; border: none;" />
                                  </td></tr>
                                </table>
                              </td>
                              <td valign="middle" style="font-size: 13px; font-weight: 500; color: #161922; {fuente}">Mayor productividad</td>
                            </tr>
                          </table>

                        </td>
                        <td width="50%" valign="top" class="m-stack">
                          
                          <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 14px;">
                            <tr>
                              <td width="38" valign="middle">
                                <table width="28" height="28" cellpadding="0" cellspacing="0" style="background-color: #f3eefa; border-radius: 8px;">
                                  <tr><td align="center" valign="middle">
                                    <img src="cid:icon_cost" width="14" height="14" style="display: block; border: none;" />
                                  </td></tr>
                                </table>
                              </td>
                              <td valign="middle" style="font-size: 13px; font-weight: 500; color: #161922; {fuente}">Reducción de costos</td>
                            </tr>
                          </table>
                          
                          <table width="100%" cellpadding="0" cellspacing="0">
                            <tr>
                              <td width="38" valign="middle">
                                <table width="28" height="28" cellpadding="0" cellspacing="0" style="background-color: #f3eefa; border-radius: 8px;">
                                  <tr><td align="center" valign="middle">
                                    <img src="cid:icon_solution" width="14" height="14" style="display: block; border: none;" />
                                  </td></tr>
                                </table>
                              </td>
                              <td valign="middle" style="font-size: 13px; font-weight: 500; color: #161922; {fuente}">Soluciones a medida</td>
                            </tr>
                          </table>

                        </td>
                      </tr>
                    </table>

                    <table width="100%" cellpadding="0" cellspacing="0">
                      <tr>
                        <td align="left">
                          
                          <table cellpadding="0" cellspacing="0" align="left" class="m-stack" style="margin-right: 10px;">
                            <tr>
                                <td>
                                    <a href="{URL_CALENDLY}" target="_blank" style="display: block; background-color: #663399; color: #ffffff; font-weight: 600; font-size: 14px; padding: 13px 20px; border-radius: 12px; text-decoration: none; text-align: center; {fuente}">
                                      <img src="cid:icon_calendar" width="14" height="14" style="vertical-align: middle; margin-right: 6px; border: none; display: inline-block;" />
                                      <span style="vertical-align: middle; {fuente}">Agendá una reunión</span>
                                    </a>
                                </td>
                            </tr>
                          </table>

                          <table cellpadding="0" cellspacing="0" align="left" class="m-stack">
                            <tr>
                                <td>
                                    <a href="{URL_WHATSAPP}" target="_blank" style="display: block; background-color: #25D366; color: #ffffff; font-weight: 600; font-size: 14px; padding: 13px 20px; border-radius: 12px; text-decoration: none; text-align: center; {fuente}">
                                      <img src="cid:icon_whatsapp" width="14" height="14" style="vertical-align: middle; margin-right: 6px; border: none; display: inline-block;" />
                                      <span style="vertical-align: middle; {fuente}">WhatsApp</span>
                                    </a>
                                </td>
                            </tr>
                          </table>

                        </td>
                      </tr>
                    </table>

                  </td>
                </tr>

                <tr>
                  <td style="background-color: #161922; padding: 14px 28px;">
                    <table width="100%" cellpadding="0" cellspacing="0">
                      <tr>
                        <td align="left" class="m-stack" style="font-size: 12px; color: #ffffff; padding-bottom: 5px; {fuente}">
                          <a href="mailto:ventas@intellihelp.tech" style="color: #ffffff; text-decoration: none; opacity: 0.9; {fuente}">ventas@intellihelp.tech</a>
                          <span style="opacity: 0.25; margin: 0 8px; {fuente}">•</span>
                          <a href="https://intellihelp.tech" target="_blank" style="color: #ffffff; text-decoration: none; opacity: 0.9; {fuente}">intellihelp.tech</a>
                        </td>
                        <td align="right" class="m-stack" style="font-size: 12px; color: #ffffff; opacity: 0.6; padding-top: 5px; {fuente}">
                          © 2026 IntelliHelp
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </body>
            </html>
            """
            msg.add_alternative(cuerpo_html, subtype='html')
            
            adjuntar_imagen(msg, "ITH-logo.png", "logo_intellihelp")
            adjuntar_imagen(msg, "icon-process.svg", "icon_process")
            adjuntar_imagen(msg, "icon-cost.svg", "icon_cost")
            adjuntar_imagen(msg, "icon-prod.svg", "icon_prod")
            adjuntar_imagen(msg, "icon-solution.svg", "icon_solution")
            adjuntar_imagen(msg, "icon-calendar.svg", "icon_calendar")
            adjuntar_imagen(msg, "icon-whatsapp.svg", "icon_whatsapp")

            # --- CONEXIÓN INDIVIDUAL POR CORREO ---
            try:
                server = smtplib.SMTP('smtp.gmail.com', 587)
                server.starttls()
                server.login(MI_CORREO, MI_PASSWORD)
                server.send_message(msg)
                server.quit()
            except smtplib.SMTPRecipientsRefused:
                # Si el servidor lo rechaza inmediatamente al intentar enviar
                print(f"❌ Rechazo inmediato detectado para: {correo_destino}")
            except Exception as e:
                print(f"⚠️ Error de conexión al enviar a {correo_destino}: {e}")

            enviados_hoy += 1
            guardar_registro(correo_destino, enviados_hoy, fecha_hoy)
            
            print(f"[{i + 1}/{total_filas}] (Enviado hoy: {enviados_hoy}) Destino: {correo_destino}")

            if enviados_hoy < LIMITE_DIARIO:
                pausa_aleatoria = random.randint(TIEMPO_MINIMO, TIEMPO_MAXIMO)
                print(f"   ⏳ Simulando humano... esperando {pausa_aleatoria} segundos para el próximo.")
                time.sleep(pausa_aleatoria)

    if enviados_hoy == 0 and ultimo_email_enviado:
        print("\n⚠️ No se enviaron correos. Es posible que el correo anterior no se haya encontrado en la lista o ya hayas llegado al final del archivo.")
    else:
        print(f"\nResumen final: Terminaste el día con {enviados_hoy} correos procesados.")
        
    # ==========================================
    # NUEVO: LLAMADA A LA REVISIÓN DE REBOTES
    # ==========================================
    # Ejecutamos la búsqueda de rebotes al terminar la ráfaga de envíos
    procesar_rebotes_del_dia(fecha_hoy, enviados_hoy)

except FileNotFoundError as e:
    print(f"\n❌ Error: No se encontró tu base de datos 'contactos.csv'. Asegúrate de que esté en: {CARPETA_ACTUAL}")
except Exception as e:
    print(f"\n❌ Error al ejecutar: {e}")