import os, sys, csv, json, time, random, smtplib, imaplib, email, email.header, re, mimetypes, logging, base64, shutil, zipfile
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parsedate_to_datetime

# ==========================================
# 1. PARÁMETROS DEL SISTEMA Y LOGS
# ==========================================

def _carpeta_app():
    """Carpeta donde se guardan los datos del usuario (config, contactos,
    historial, registros). Estable entre ejecuciones, también dentro de
    un bundle PyInstaller (`flet pack`) donde `__file__` apuntaría a una
    temp folder que se borra al cerrar la app."""
    if getattr(sys, "frozen", False):
        # Bundle compilado (.exe): usar el directorio del ejecutable
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _carpeta_assets():
    """Carpeta donde están los recursos empaquetados (logos, iconos SVG).
    En PyInstaller onefile esto apunta a `sys._MEIPASS`. En modo dev,
    apunta a la misma carpeta del script."""
    if hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


CARPETA_ACTUAL = _carpeta_app()
CARPETA_ASSETS = _carpeta_assets()

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
ARCHIVO_VISTOS    = os.path.join(CARPETA_ACTUAL, "registro_vistos.json")
ARCHIVO_IGNORADOS = os.path.join(CARPETA_ACTUAL, "registro_ignorados.json")
ARCHIVO_PENDIENTE = os.path.join(CARPETA_ACTUAL, "registro_pendiente.json")
ARCHIVO_LISTA_NEGRA = os.path.join(CARPETA_ACTUAL, "lista_negra.json")
ARCHIVO_MSG_IDS    = os.path.join(CARPETA_ACTUAL, "registro_msg_ids.json")

# ── Control de campaña: stop manual + reintentos red ───────────
# Reintentos máximos por correo cuando se cae internet:
#   1000 intentos × 10 s = ~2h 47min
MAX_REINTENTOS_RED  = 1000
INTERVALO_REINTENTO = 10
import threading as _t_mod

_STOP_CAMPANA = _t_mod.Event()
_RED_HOOK     = [None]   # callback(estado, intento, maximo, destino)

def reset_stop_campana():
    _STOP_CAMPANA.clear()

def detener_campana():
    _STOP_CAMPANA.set()

def campana_detenida():
    return _STOP_CAMPANA.is_set()

def set_red_hook(cb):
    """Registra callback que recibe estados de la red durante envío.
    estado ∈ ('caido', 'inestable', 'reintentando', 'recuperado',
              'agotado', 'detenido')."""
    _RED_HOOK[0] = cb

def _emit_red(estado, intento, maximo, destino):
    cb = _RED_HOOK[0]
    if cb:
        try:
            cb(estado, intento, maximo, destino)
        except Exception:
            pass


# ── Persistencia del correo en cola de reintentos ──────────────
def cargar_pendiente():
    """Devuelve {destino, nombre, intentos} o None."""
    if not os.path.exists(ARCHIVO_PENDIENTE):
        return None
    try:
        with open(ARCHIVO_PENDIENTE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def guardar_pendiente(destino, nombre, intentos):
    try:
        data = {
            "destino":  destino,
            "nombre":   nombre or "",
            "intentos": int(intentos),
            "fecha":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(ARCHIVO_PENDIENTE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def borrar_pendiente():
    try:
        if os.path.exists(ARCHIVO_PENDIENTE):
            os.remove(ARCHIVO_PENDIENTE)
    except Exception:
        pass


# ==========================================
# TRACKING DE MESSAGE-IDs ENVIADOS
# ==========================================
# Guardamos los Message-ID que generamos al mandar cada correo. Cuando
# alguien responde, su email trae In-Reply-To / References apuntando a
# esos IDs. Esto nos permite detectar la respuesta CON CERTEZA aunque:
#   - El remitente no esté tal cual en contactos.csv (otro email del
#     mismo cliente, alias corporativo, etc).
#   - Le hayan cambiado el asunto (ej: "Baja", "Fuera de oficina Re:...").
#   - El servidor anti-spam haya re-empaquetado el mensaje.
# Es la forma 100% confiable de no perder respuestas.

_MAX_MSG_IDS_GUARDADOS = 10000  # ~ 6-7 campañas de 1500 envíos cada una
_msg_ids_cache = [None]         # cache en memoria del set; invalidado al guardar

def _cargar_msg_ids_archivo():
    if not os.path.exists(ARCHIVO_MSG_IDS):
        return []
    try:
        with open(ARCHIVO_MSG_IDS, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("ids"), list):
            return data["ids"]
    except Exception:
        pass
    return []

def cargar_message_ids_enviados():
    """Set de Message-IDs que mandamos (los que esperamos ver en
    In-Reply-To de las respuestas). Cacheado en memoria."""
    if _msg_ids_cache[0] is None:
        _msg_ids_cache[0] = set(_cargar_msg_ids_archivo())
    return _msg_ids_cache[0]

def registrar_message_id_enviado(message_id):
    """Agrega un Message-ID al registro. Idempotente. Rota cuando supera
    `_MAX_MSG_IDS_GUARDADOS` (descarta los más viejos)."""
    if not message_id:
        return
    mid = message_id.strip()
    if not mid:
        return
    # Normalización mínima: aseguramos que tenga <...> envolventes para
    # match consistente con headers IMAP.
    if not mid.startswith("<"):
        mid = "<" + mid
    if not mid.endswith(">"):
        mid = mid + ">"
    try:
        ids = _cargar_msg_ids_archivo()
        if mid in ids:
            return  # ya estaba
        ids.append(mid)
        if len(ids) > _MAX_MSG_IDS_GUARDADOS:
            ids = ids[-_MAX_MSG_IDS_GUARDADOS:]
        with open(ARCHIVO_MSG_IDS, "w", encoding="utf-8") as f:
            json.dump({"ids": ids}, f, ensure_ascii=False)
        # Invalidar cache para que el próximo `cargar_message_ids_enviados`
        # vea el nuevo.
        _msg_ids_cache[0] = None
    except Exception:
        pass


# ==========================================
# LISTA NEGRA — opt-outs (responden "BAJA" o piden no recibir más)
# ==========================================
# `lista_negra.json` estructura:
#   {"emails": [{"email": "x@y.com", "fecha": "2026-05-08 14:30",
#                "motivo": "Respondió BAJA", "auto": true}]}
# Acceso O(1) vía set cacheado en `cargar_lista_negra_set()`.

def cargar_lista_negra():
    """Devuelve el dict crudo con metadata. Para lookup rápido por email,
    usar `cargar_lista_negra_set()`."""
    def _loader():
        if not os.path.exists(ARCHIVO_LISTA_NEGRA):
            return {"emails": []}
        try:
            with open(ARCHIVO_LISTA_NEGRA, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"emails": []}
            data.setdefault("emails", [])
            return data
        except Exception:
            return {"emails": []}
    return _cached_read("lista_negra", ARCHIVO_LISTA_NEGRA, _loader)


def cargar_lista_negra_set():
    """Set de emails (en minúsculas) para chequeo O(1) en el loop de envío."""
    data = cargar_lista_negra()
    return {
        (e.get("email") or "").strip().lower()
        for e in data.get("emails", [])
        if e.get("email")
    }


def _guardar_lista_negra(data):
    with open(ARCHIVO_LISTA_NEGRA, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    _cache_invalidate("lista_negra")


def agregar_a_lista_negra(email_addr, motivo="Agregado manualmente", auto=False):
    """Agrega un email a la lista negra. Idempotente: si ya está,
    actualiza la fecha/motivo pero no duplica.
    Retorna True si quedó agregado, False si el email es inválido."""
    if not email_addr or "@" not in email_addr:
        return False
    email_norm = email_addr.strip().lower()
    data = cargar_lista_negra()
    # Si ya existe, actualizamos motivo+fecha (el más reciente gana)
    for entry in data["emails"]:
        if (entry.get("email") or "").strip().lower() == email_norm:
            entry["motivo"] = motivo
            entry["fecha"]  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry["auto"]   = auto or entry.get("auto", False)
            _guardar_lista_negra(data)
            return True
    data["emails"].append({
        "email":  email_norm,
        "fecha":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "motivo": motivo,
        "auto":   bool(auto),
    })
    _guardar_lista_negra(data)
    return True


def agregar_lote_lista_negra(emails, motivo="Agregado en lote", auto=True):
    """Agrega muchos emails a la lista negra en UNA sola lectura/escritura
    (mucho más rápido que llamar `agregar_a_lista_negra` N veces).
    Idempotente: ignora los que ya están. Retorna cuántos NUEVOS se agregaron."""
    if not emails:
        return 0
    data = cargar_lista_negra()
    existentes = {
        (e.get("email") or "").strip().lower()
        for e in data["emails"] if e.get("email")
    }
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    nuevos = 0
    for em in emails:
        if not em or "@" not in em:
            continue
        en = em.strip().lower()
        if en in existentes:
            continue
        data["emails"].append({
            "email": en, "fecha": ahora, "motivo": motivo, "auto": bool(auto),
        })
        existentes.add(en)
        nuevos += 1
    if nuevos:
        _guardar_lista_negra(data)
    return nuevos


def quitar_de_lista_negra(email_addr):
    """Quita un email. Retorna True si existía y fue removido."""
    if not email_addr:
        return False
    email_norm = email_addr.strip().lower()
    data = cargar_lista_negra()
    nuevos = [
        e for e in data["emails"]
        if (e.get("email") or "").strip().lower() != email_norm
    ]
    if len(nuevos) == len(data["emails"]):
        return False
    data["emails"] = nuevos
    _guardar_lista_negra(data)
    return True


def escanear_bajas_retroactivo(dias=180):
    """Escanea respuestas registradas en `registro_respuestas.json` y
    analiza con `es_pedido_de_baja()` las que no fueron evaluadas todavía.
    Las que matchean se agregan a la lista negra automáticamente.

    **Optimización**: en vez de hacer SEARCH+FETCH por cada respuesta
    individual (2 round-trips IMAP × N respuestas = lentísimo), hace:
      1. UN SEARCH del INBOX en los últimos `dias` días.
      2. UN BATCH FETCH de headers para construir un dict
         {Message-ID → UID} en memoria.
      3. UN BATCH FETCH de RFC822 de los UIDs que matchean.
      4. Procesamiento local de los cuerpos.
    De 1000+ round-trips IMAP a ~3 → de 10 minutos a < 30 segundos.

    Retorna dict {analizados, ya_evaluados, nuevas_bajas, errores}.
    """
    resumen = {
        "analizados":     0,
        "ya_evaluados":   0,
        "nuevas_bajas":   0,
        "errores":        0,
    }

    cfg = cargar_config()
    imap_host = (cfg.get("imap_host") or "imap.gmail.com").strip()
    if not MI_CORREO() or not MI_PASSWORD():
        return resumen

    data = _cargar_respuestas_archivo()
    respuestas = data.get("respuestas", [])
    if not respuestas:
        return resumen

    blacklist_set = cargar_lista_negra_set()

    # Paso 1 — filtrar localmente las respuestas que necesitan análisis.
    # Las ya evaluadas (es_baja=False explícito), las que ya están en
    # blacklist, o las que tienen es_baja=True (re-aplicar idempotente)
    # se procesan sin tocar IMAP.
    a_evaluar = []      # [{resp, msg_id_normalizado}]
    for resp in respuestas:
        remitente = (resp.get("from") or "").strip().lower()
        if not remitente:
            continue
        if remitente in blacklist_set:
            resumen["ya_evaluados"] += 1
            continue
        if resp.get("es_baja") is False:
            resumen["ya_evaluados"] += 1
            continue
        if resp.get("es_baja"):
            # Idempotente: re-agregamos a la blacklist
            agregar_a_lista_negra(
                remitente,
                motivo="Re-aplicación de auto-baja histórica",
                auto=True,
            )
            blacklist_set.add(remitente)
            resumen["nuevas_bajas"] += 1
            continue
        msg_id = (resp.get("uid") or "").strip()
        if msg_id:
            a_evaluar.append((resp, msg_id))

    if not a_evaluar:
        # No hay nada que bajar de IMAP, terminamos rápido
        _guardar_respuestas_archivo(data)
        return resumen

    # Set de Message-IDs para lookup O(1) cuando procesamos los headers
    msg_ids_buscados = {mid for _, mid in a_evaluar}

    try:
        with imaplib.IMAP4_SSL(imap_host) as mail:
            mail.login(MI_CORREO(), MI_PASSWORD())
            mail.select("inbox", readonly=True)

            # Paso 2 — UN solo SEARCH para acotar el universo de UIDs.
            try:
                desde = datetime.now() - timedelta(days=int(dias))
            except Exception:
                desde = datetime.now() - timedelta(days=180)
            fecha_imap = desde.strftime("%d-%b-%Y")
            try:
                estado, ids = mail.uid(
                    "SEARCH", None, f'(SINCE "{fecha_imap}")'
                )
                if estado != "OK" or not ids or not ids[0]:
                    _guardar_respuestas_archivo(data)
                    return resumen
                todos_uids = ids[0].split()
            except Exception as e:
                logging.error(f"SEARCH en scan retro falló: {e}")
                resumen["errores"] += 1
                _guardar_respuestas_archivo(data)
                return resumen

            # Paso 3 — UN BATCH FETCH de headers de todo el rango.
            # Construye dict {Message-ID → UID}.
            msgid_to_uid = {}
            if todos_uids:
                # Si hay muchos UIDs los fetcheamos en chunks de 500 para
                # no superar el límite de comando IMAP (~8KB).
                CHUNK = 500
                for i in range(0, len(todos_uids), CHUNK):
                    chunk = todos_uids[i:i + CHUNK]
                    try:
                        _, fetched = mail.uid(
                            "FETCH", b",".join(chunk),
                            "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])",
                        )
                    except Exception:
                        continue
                    # Parsear el response: viene como secuencia alternada
                    # de tuplas (uid_header_bytes, header_body) y bytes
                    # cierre. Extraemos UID y Message-ID de cada tupla.
                    uid_actual = None
                    for item in fetched:
                        if isinstance(item, tuple) and len(item) >= 2:
                            raw_meta = item[0]
                            raw_body = item[1]
                            # raw_meta tiene formato: b'123 (UID 456 BODY[...]'
                            m_uid = re.search(rb"UID (\d+)", raw_meta)
                            uid_actual = m_uid.group(1) if m_uid else None
                            if uid_actual:
                                m_mid = re.search(
                                    rb"Message-ID:\s*(<[^>]+>)",
                                    raw_body, re.IGNORECASE,
                                )
                                if m_mid:
                                    mid_str = m_mid.group(1).decode(
                                        "utf-8", "ignore"
                                    )
                                    if mid_str in msg_ids_buscados:
                                        msgid_to_uid[mid_str] = uid_actual

            # Paso 4 — BATCH FETCH de RFC822 sólo para los UIDs que
            # necesitamos (los que tienen Message-ID que matchea).
            uids_finales = list(msgid_to_uid.values())
            uid_to_cuerpo = {}
            if uids_finales:
                CHUNK = 100  # cuerpos enteros pesan más
                for i in range(0, len(uids_finales), CHUNK):
                    chunk = uids_finales[i:i + CHUNK]
                    try:
                        _, fetched = mail.uid(
                            "FETCH", b",".join(chunk), "(RFC822)"
                        )
                    except Exception:
                        continue
                    uid_actual = None
                    for item in fetched:
                        if isinstance(item, tuple) and len(item) >= 2:
                            m_uid = re.search(rb"UID (\d+)", item[0])
                            uid_actual = m_uid.group(1) if m_uid else None
                            if uid_actual:
                                try:
                                    msg_full = email.message_from_bytes(
                                        item[1]
                                    )
                                    uid_to_cuerpo[uid_actual] = (
                                        _texto_correo(msg_full) or ""
                                    )
                                except Exception:
                                    uid_to_cuerpo[uid_actual] = ""

            # Paso 5 — Evaluar localmente cada respuesta con su cuerpo
            for resp, msg_id in a_evaluar:
                uid_imap = msgid_to_uid.get(msg_id)
                cuerpo_resp = uid_to_cuerpo.get(uid_imap, "") if uid_imap else ""

                resumen["analizados"] += 1
                asunto = resp.get("subject", "")
                es_baja, razon = es_pedido_de_baja(asunto, cuerpo_resp)
                resp["es_baja"] = bool(es_baja)

                if es_baja:
                    remitente = (resp.get("from") or "").strip().lower()
                    agregar_a_lista_negra(
                        remitente,
                        motivo=f"Auto-baja retroactiva: {razon}",
                        auto=True,
                    )
                    blacklist_set.add(remitente)
                    resumen["nuevas_bajas"] += 1

            _guardar_respuestas_archivo(data)
    except Exception as e:
        logging.error(f"Scan retroactivo BAJA falló: {e}")
        resumen["errores"] += 1

    return resumen


# ── Frases típicas de opt-out (case-insensitive, regex) ──
# Cubre español, inglés y formas comunes. Las frases tienen que ser
# claras y explícitas — NO matchean "necesito una app para bajar costos"
# u otros contextos donde "baja" aparece como sustantivo o verbo común.
# TODOS los regex de detección están PRECOMPILADOS a nivel módulo — así
# `es_pedido_de_baja()` no paga el costo de compilación en cada llamada.
# Para un polling de respuestas con 50 emails/día esto evita ~750 compi-
# laciones de regex al día (15 patrones × 50 evaluaciones).
_RE_BAJA_ASUNTO = re.compile(
    r"\b(baja|unsubscribe|opt[- ]?out)\b", re.IGNORECASE,
)
_RE_BAJA_CUERPO_CORTO = re.compile(r"\bbaja\b", re.IGNORECASE)
_RE_FIRMA_GUION  = re.compile(r"\n[> ]*-{2,}.*", re.DOTALL)
_RE_LINEAS_QUOTE = re.compile(r"^>.*$", re.MULTILINE)
_RE_WHITESPACE   = re.compile(r"\s+")
# Combinamos todos los patrones explícitos en UN solo regex con alternancia.
# Es más rápido que iterar 14 regex separados.
_RE_BAJA_EXPLICITO = re.compile(
    "|".join([
        r"\bdarme de baja\b",
        r"\bdate de baja\b",
        r"\bdar(?:me)? de baja\b",
        r"\bno (?:quiero|deseo) (?:recibir|seguir recibiendo)\b",
        r"\bno me (?:env[íi]en|env[íi]es|manden|mandes)\b",
        r"\bdejen? de (?:enviar|mandar)\b",
        r"\bdesuscrib(?:ir|irme|ame|anme)\b",
        r"\bcancelar (?:la )?(?:suscripci[óo]n|inscripci[óo]n)\b",
        r"\bquitar(?:me)? de (?:la )?lista\b",
        r"\bno (?:contactar(?:me)?|me contacten)\b",
        r"\bme bajo de (?:la|esta) (?:lista|campa[ñn]a)\b",
        r"\bunsubscribe\b",
        r"\bremove me\b",
        r"\bstop sending\b",
        r"\bopt[- ]?out\b",
    ]),
    re.IGNORECASE,
)


def es_pedido_de_baja(asunto, cuerpo):
    """Heurística: decide si una respuesta es un pedido de no recibir más
    correos.

    Devuelve (es_baja: bool, razon: str).

    Reglas (en orden):
      1. Si el ASUNTO contiene "baja", "unsubscribe" u "opt-out" como
         palabra aislada → SÍ, es baja (señal muy fuerte).
      2. Si el CUERPO contiene "BAJA" aislada Y es corto (< 300 chars de
         texto significativo) → SÍ. Las respuestas legítimas de baja son
         típicamente "BAJA" sola o frases muy cortas.
      3. Si el CUERPO contiene frases de opt-out explícitas (regardless
         de la longitud), como "no quiero recibir más", "unsubscribe",
         "darme de baja" → SÍ.
      4. Si "baja" aparece sólo dentro de un mensaje largo SIN frases de
         opt-out claras → NO. Ejemplo: "necesito una app para procesar
         bajas de personal" no debe matchear.
    """
    asunto = (asunto or "").strip()
    cuerpo = (cuerpo or "").strip()

    # Regla 1: asunto explícito
    if _RE_BAJA_ASUNTO.search(asunto):
        return True, f"Asunto contiene pedido de baja: {asunto[:80]!r}"

    # Limpiamos firmas/quotes/footers del cuerpo para no contar contenido
    # que es de NUESTRO correo original embebido como quote en la respuesta.
    cuerpo_limpio = _RE_FIRMA_GUION.sub("", cuerpo)
    cuerpo_limpio = _RE_LINEAS_QUOTE.sub("", cuerpo_limpio)
    cuerpo_limpio = _RE_WHITESPACE.sub(" ", cuerpo_limpio).strip()

    # Regla 2: cuerpo corto con "BAJA" aislada
    if len(cuerpo_limpio) < 300 and _RE_BAJA_CUERPO_CORTO.search(cuerpo_limpio):
        return True, "Respuesta corta con 'BAJA'"

    # Regla 3: frases de opt-out explícitas en cualquier longitud.
    # Un solo regex con alternancia es mucho más rápido que iterar
    # 15 patrones separados.
    m = _RE_BAJA_EXPLICITO.search(cuerpo_limpio)
    if m:
        return True, f"Frase de opt-out detectada: {m.group(0)!r}"

    return False, ""
CARPETA_HISTORIAL = os.path.join(CARPETA_ACTUAL, "historial")

# Configuración de los correos a enviar
# El ASUNTO es lo único fijo del template; TODO el resto (botones, datos de
# contacto, firma, logo, CC) se arma desde la config del usuario — nada
# hardcodeado. Ver `preparar_correo` y los defaults `empresa_*` de config.
ASUNTO       = "TE AYUDAMOS A BUSCAR LOS MEJORES RECURSOS PARA TU EMPRESA"
CORREO_COPIA = ""
URL_WHATSAPP = ""
URL_CALENDLY = ""

TIEMPO_MINIMO, TIEMPO_MAXIMO = 25, 45


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
    "tema":          "sistema",   # 'claro' | 'oscuro' | 'sistema'
    "firma":         "",          # firma personal del usuario (texto plano)
    "firma_tipo":    "texto",     # 'texto' | 'imagen'
    "firma_imagen":  "",          # ruta absoluta a la imagen de firma
    "correos_copia": "",          # CC: lista separada por coma o vacío
    "logo_personalizado": "",     # path absoluto al logo del cliente
    "url_calendly":      "",      # URL botón cuando plataforma_reunion="calendly"
    "url_cal_com":       "",      # URL botón cuando plataforma_reunion="cal_com"
    "plataforma_reunion": "cal_com",   # 'calendly' | 'cal_com'
    "url_whatsapp":      "",      # URL botón "WhatsApp"
    # ── Datos de la empresa (se muestran en el correo de campaña) ──
    # Configurables desde Configuración → Empresa. Vacío = no se muestra
    # esa línea. Nada de esto está hardcodeado en el template.
    "empresa_nombre":    "Intellihelp",
    "empresa_web":       "intellihelp.tech",
    "empresa_telefono":  "+54 11 7700-6868",
    "empresa_email":     "info@intellihelp.tech",
    "empresa_whatsapp":  "+54 9 11 5027-4827",
}


def URL_CALENDLY_CFG():
    """Devuelve la URL Calendly del usuario o la por defecto del módulo."""
    v = (get_config_value("url_calendly") or "").strip()
    return v or URL_CALENDLY


def URL_CAL_COM_CFG():
    """Devuelve la URL Cal.com del usuario (o vacío si no configuró)."""
    return (get_config_value("url_cal_com") or "").strip()


def URL_REUNION_CFG():
    """URL que va en el botón "Agendar reunión" del correo. Selecciona
    entre Calendly o Cal.com según `plataforma_reunion`. Si la elegida
    no tiene URL configurada, hace fallback a la otra (no romper el
    botón por un campo vacío)."""
    plataforma = (get_config_value("plataforma_reunion") or "calendly").lower()
    url_cd = URL_CALENDLY_CFG()
    url_cc = URL_CAL_COM_CFG()
    if plataforma == "cal_com":
        return url_cc or url_cd
    return url_cd or url_cc


def URL_WHATSAPP_CFG():
    v = (get_config_value("url_whatsapp") or "").strip()
    return v or URL_WHATSAPP


def _parsear_cc(valor):
    """Convierte el string del config 'a@x.com, b@y.com' en lista limpia."""
    if not valor:
        return []
    partes = re.split(r"[,;\s]+", str(valor))
    return [p.strip() for p in partes if "@" in p]

# ── Cache con TTL para lecturas de disco frecuentes ──
# Permite que cambiar entre pestañas sea instantáneo aunque internamente
# se llamen funciones que leen JSON de disco (config, contactos,
# rechazados, depurados, vistos, ignorados).
_CACHE = {}        # key -> (mtime_archivo, ts_cache, valor)
_CACHE_TTL = 3.0   # segundos


def _cached_read(clave, archivo, loader):
    """Lee `archivo` usando `loader()` si:
      - no está en cache, O
      - el archivo cambió en disco (mtime), O
      - pasó más de _CACHE_TTL segundos.
    Retorna lo que devuelve `loader()` (sin parámetros)."""
    import time as _t
    try:
        mtime = os.path.getmtime(archivo) if os.path.exists(archivo) else 0
    except Exception:
        mtime = 0
    ahora = _t.time()
    entrada = _CACHE.get(clave)
    if entrada is not None:
        mt_old, ts_old, valor_old = entrada
        if mt_old == mtime and (ahora - ts_old) < _CACHE_TTL:
            return valor_old
    valor = loader()
    _CACHE[clave] = (mtime, ahora, valor)
    return valor


def _cache_invalidate(clave=None):
    """Invalida el cache (o una clave puntual). Llamar después de
    escribir un archivo para que la próxima lectura sea fresca."""
    if clave is None:
        _CACHE.clear()
    else:
        _CACHE.pop(clave, None)


def cargar_config():
    def _loader():
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
    return _cached_read("config", ARCHIVO_CONFIG, _loader)

def guardar_config(cfg: dict):
    with open(ARCHIVO_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)
    _cache_invalidate("config")

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
_FF_CORREO = "'Saira',Arial,Helvetica,sans-serif"


def _pilar_html(titulo, desc):
    """HTML de un 'pilar de valor': chip verde con check + título + desc."""
    _ff = _FF_CORREO
    return (
        '<table role="presentation" width="100%" border="0" cellpadding="0" '
        'cellspacing="0" style="margin:0 0 14px 0;"><tr>'
        '<td width="38" valign="top" style="padding-top:1px;">'
        '<table role="presentation" border="0" cellpadding="0" cellspacing="0">'
        '<tr><td width="26" height="26" align="center" valign="middle" '
        'bgcolor="#8bc53f" style="width:26px;height:26px;border-radius:13px;'
        'color:#ffffff;font-family:Arial,Helvetica,sans-serif;font-size:14px;'
        'font-weight:bold;line-height:26px;">&#10003;</td></tr></table></td>'
        '<td valign="top" style="padding-left:12px;">'
        f'<div style="font-family:{_ff};font-size:15px;'
        f'font-weight:bold;color:#241a33;line-height:1.45;">{titulo}</div>'
        f'<div style="font-family:{_ff};font-size:14px;'
        f'color:#6b6b76;line-height:1.5;">{desc}</div>'
        '</td></tr></table>'
    )


def _boton_html(label, url, fill, stroke):
    """Botón 'bulletproof' con VML para Outlook. `url`, `fill` (relleno) y
    `stroke` (borde). Se renderiza igual en Gmail, Outlook, Apple Mail."""
    _ff = _FF_CORREO
    return (
        '<!--[if mso]>'
        '<v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:w="urn:schemas-microsoft-com:office:word" '
        f'href="{url}" style="height:50px;v-text-anchor:middle;width:300px;" '
        f'arcsize="14%" strokecolor="{stroke}" fillcolor="{fill}">'
        '<w:anchorlock/>'
        f'<center style="color:#ffffff;font-family:Arial,sans-serif;'
        f'font-size:16px;font-weight:bold;">{label}</center>'
        '</v:roundrect>'
        '<![endif]-->'
        '<!--[if !mso]><!-- -->'
        f'<a class="btn" href="{url}" target="_blank" '
        f'style="background-color:{fill}; border:1px solid {stroke}; '
        f'border-radius:8px; color:#ffffff; display:inline-block; '
        f'font-family:{_ff}; font-size:16px; font-weight:bold; '
        f'line-height:50px; text-align:center; text-decoration:none; '
        f'width:300px; -webkit-text-size-adjust:none;">{label}</a>'
        '<!--<![endif]-->'
    )


def _fila_contacto_html(label, value_html):
    """Una fila del bloque de contacto: etiqueta (morado) + valor (negro)."""
    _ff = _FF_CORREO
    return (
        '<tr>'
        f'<td style="font-family:{_ff}; font-size:13px; color:#5b2d91; '
        'font-weight:bold; text-transform:uppercase; letter-spacing:0.5px; '
        f'padding:5px 0; width:110px; vertical-align:top;">{label}</td>'
        f'<td style="font-family:{_ff}; font-size:14px; padding:5px 0; '
        f'color:#241a33;">{value_html}</td>'
        '</tr>'
    )


def preparar_correo(nombre, destino):
    from html import escape as _esc
    correo_remitente = MI_CORREO()
    _ff = _FF_CORREO

    msg = EmailMessage()
    cc_lista = _parsear_cc(get_config_value("correos_copia"))
    msg["Subject"] = f"{ASUNTO} | {nombre}" if nombre else ASUNTO
    msg["From"]    = correo_remitente
    msg["To"]      = destino
    if cc_lista:
        msg["Cc"]  = ", ".join(cc_lista)

    # List-Unsubscribe (anti-spam): atado al sistema de "responde BAJA".
    if correo_remitente:
        msg["List-Unsubscribe"] = f"<mailto:{correo_remitente}?subject=BAJA>"

    # ── TODO desde config del usuario (nada hardcodeado) ──
    url_wsp     = (URL_WHATSAPP_CFG() or "").strip()       # botón WhatsApp
    url_reunion = (URL_REUNION_CFG() or "").strip()        # botón Agendar reunión
    emp_nombre  = (get_config_value("empresa_nombre")   or "").strip()
    emp_web     = (get_config_value("empresa_web")      or "").strip()
    emp_tel     = (get_config_value("empresa_telefono") or "").strip()
    emp_email   = (get_config_value("empresa_email")    or "").strip()
    emp_wsp     = (get_config_value("empresa_whatsapp") or "").strip()
    marca = emp_nombre or "nuestra empresa"

    # Firma configurada (texto o imagen) — se muestra al cierre si existe.
    firma_tipo   = (get_config_value("firma_tipo") or "texto").lower()
    firma_texto  = (get_config_value("firma") or "").strip()
    firma_imagen = (get_config_value("firma_imagen") or "").strip()

    # Nombre de pila para el saludo personal "Hola Juan,".
    nombre_pila = (nombre or "").strip().split()[0] if (nombre or "").strip() else ""
    saludo = nombre_pila if nombre_pila else (nombre or "Cliente")

    # ── Logo: personalizado del config, o ITH-logo.png del bundle ──
    logo_cfg = (get_config_value("logo_personalizado") or "").strip()
    logo_path = None
    if logo_cfg and os.path.exists(logo_cfg):
        logo_path = logo_cfg
    else:
        for _carpeta in (CARPETA_ACTUAL, CARPETA_ASSETS):
            for _nb in ("ITH-logo.png", "logo-app.png"):
                _p = os.path.join(_carpeta, _nb)
                if os.path.exists(_p):
                    logo_path = _p
                    break
            if logo_path:
                break

    # ── Botones condicionales según config ──
    #   ambos configurados → 2 botones · sólo uno → 1 botón · ninguno → 0
    botones = []
    if url_wsp:
        botones.append(_boton_html("Contáctanos por WhatsApp", url_wsp,
                                    "#25D366", "#1EBE57"))
    if url_reunion:
        botones.append(_boton_html("Agendar reunión", url_reunion,
                                    "#5b2d91", "#4a2277"))
    _sep_btn = '<div style="font-size:0; line-height:12px;">&nbsp;</div>'
    botones_html = _sep_btn.join(botones)

    # ── Bloque de contacto (sólo las líneas que estén configuradas) ──
    filas = []
    if emp_web:
        web_url = emp_web if emp_web.lower().startswith("http") else "https://" + emp_web
        filas.append(_fila_contacto_html(
            "Web",
            f'<a href="{web_url}" target="_blank" style="color:#241a33; '
            f'font-weight:bold; text-decoration:none;">{_esc(emp_web)}</a>'))
    if emp_wsp:
        filas.append(_fila_contacto_html(
            "WhatsApp",
            f'<span style="font-weight:bold;">{_esc(emp_wsp)}</span>'))
    if emp_tel:
        filas.append(_fila_contacto_html(
            "Teléfono",
            f'<span style="font-weight:bold;">{_esc(emp_tel)}</span>'))
    if emp_email:
        filas.append(_fila_contacto_html(
            "Email",
            f'<a href="mailto:{_esc(emp_email)}" style="color:#241a33; '
            f'font-weight:bold; text-decoration:none;">{_esc(emp_email)}</a>'))

    contacto_html = ""
    if filas:
        contacto_html = (
            '<tr><td class="px" style="padding:22px 44px 8px 44px;">'
            '<table role="presentation" width="100%" border="0" cellpadding="0" '
            'cellspacing="0" style="border:1px solid #ececf2; border-radius:10px;">'
            '<tr><td style="padding:20px 26px;">'
            '<table role="presentation" width="100%" border="0" cellpadding="0" '
            'cellspacing="0">' + "".join(filas) + '</table>'
            '</td></tr></table></td></tr>'
        )

    # ── Firma configurada (imagen o texto) ──
    firma_img_path = None
    if firma_tipo == "imagen" and firma_imagen and os.path.exists(firma_imagen):
        firma_bloque = ('<img src="cid:firma_usuario" alt="Firma" '
                        'style="max-width:100%; height:auto; display:block; '
                        'border:0; margin-top:10px;" />')
        firma_img_path = firma_imagen
    elif firma_tipo == "texto" and firma_texto:
        firma_bloque = (
            f'<div style="margin-top:8px; font-family:{_ff}; font-size:14px; '
            f'line-height:1.5; color:#4a4a55;">'
            + _esc(firma_texto).replace("\n", "<br />") + '</div>')
    elif emp_nombre:
        firma_bloque = (f'<p style="margin:6px 0 0 0; font-family:{_ff}; '
                        f'font-size:16px; font-weight:bold; color:#5b2d91;">'
                        f'{_esc(emp_nombre)}</p>')
    else:
        firma_bloque = ""

    firma_area_html = (
        '<tr><td class="px" style="padding:22px 44px 34px 44px;">'
        f'<p style="margin:0; font-family:{_ff}; font-size:15px; '
        f'color:#4a4a55;">Saludos cordiales,</p>'
        + firma_bloque +
        '</td></tr>'
    )

    # ── Versión texto plano (fallback para clientes sin HTML) ──
    cta_lineas_txt = []
    if url_wsp:
        cta_lineas_txt.append(f"  Contáctanos por WhatsApp:  {url_wsp}")
    if url_reunion:
        cta_lineas_txt.append(f"  Agendar reunión:           {url_reunion}")
    bloque_cta_txt = ("\n".join(cta_lineas_txt) + "\n\n") if cta_lineas_txt else ""

    contacto_txt_lineas = []
    if emp_web:
        contacto_txt_lineas.append(f"  Web:       {emp_web}")
    if emp_wsp:
        contacto_txt_lineas.append(f"  WhatsApp:  {emp_wsp}")
    if emp_tel:
        contacto_txt_lineas.append(f"  Teléfono:  {emp_tel}")
    if emp_email:
        contacto_txt_lineas.append(f"  Email:     {emp_email}")
    bloque_contacto_txt = ""
    if contacto_txt_lineas:
        bloque_contacto_txt = (
            "------------------------------------------------------------\n"
            + "\n".join(contacto_txt_lineas) + "\n"
            "------------------------------------------------------------\n\n")

    firma_txt = ""
    if firma_tipo == "texto" and firma_texto:
        firma_txt = firma_texto + "\n"
    elif emp_nombre:
        firma_txt = emp_nombre + "\n"

    cuerpo_texto = (
        f"Hola {saludo},\n\n"
        "LOS MEJORES RECURSOS PARA TU EMPRESA\n"
        "Outsourcing y selección de personal\n\n"
        f"En {marca} contamos con más de 15 años ayudando a las empresas a "
        "completar sus equipos de trabajo. Nos ocupamos del outsourcing, la "
        "búsqueda y la selección de personal: vos definís el perfil y "
        "nosotros te presentamos a los candidatos indicados.\n\n"
        "  + Outsourcing de personal: tercerizá la búsqueda, selección y "
        "administración de tu equipo.\n"
        "  + Selección a medida: encontramos los recursos que encajan con "
        "tu operación.\n"
        "  + Más de 15 años de experiencia respaldando cada proceso.\n\n"
        "Contáctanos, te asesoramos sin cargo.\n\n"
        f"{bloque_cta_txt}"
        f"{bloque_contacto_txt}"
        "Saludos cordiales,\n"
        f"{firma_txt}\n"
        "Si no deseas recibir más información, responde este correo con la "
        'palabra "BAJA".'
    )
    msg.set_content(cuerpo_texto)

    # ── Logo (imagen CID) con fallback a wordmark si se bloquea ──
    if logo_path:
        logo_html = (
            '<img src="cid:logo_empresa" alt="' + _esc(marca) + '" height="42" '
            'style="height:42px;width:auto;display:block;border:0;outline:none;'
            'text-decoration:none;" />'
        )
    else:
        logo_html = (f"<span style=\"font-family:{_ff};font-size:22px;"
                     "font-weight:bold;color:#5b2d91;letter-spacing:0.5px;\">"
                     f"{_esc((emp_nombre or 'INTELLIHELP').upper())}</span>")

    preheader = ("Más de 15 años en outsourcing y selección de personal. "
                 "Asesoría sin cargo.")

    # Saira (Google Fonts) para clientes que soportan fuentes web; el resto
    # cae a Arial. El @import va primero dentro del <style>.
    estilos = (
        "<style type=\"text/css\">"
        "@import url('https://fonts.googleapis.com/css2?"
        "family=Saira:wght@400;500;600;700&display=swap');"
        "@media only screen and (max-width:620px){"
        ".cont{width:100%!important;}"
        ".px{padding-left:26px!important;padding-right:26px!important;}"
        ".hero-px{padding-left:26px!important;padding-right:26px!important;}"
        ".h1{font-size:25px!important;line-height:1.25!important;}"
        ".btn{width:100%!important;}"
        "}"
        "</style>"
    )

    # Bloque CTA (headline + subtítulo + botones si hay).
    cta_html = (
        '<tr><td class="px" style="padding:14px 44px 8px 44px;">'
        '<table role="presentation" width="100%" border="0" cellpadding="0" '
        'cellspacing="0" style="background-color:#f5f3fa; border-radius:12px;">'
        '<tr><td align="center" style="padding:28px 26px 30px 26px;">'
        f'<p style="margin:0 0 4px 0; font-family:{_ff}; font-size:21px; '
        f'font-weight:bold; color:#5b2d91;">Contáctanos, te asesoramos sin cargo.</p>'
        f'<p style="margin:0 0 {"22px" if botones_html else "0"} 0; '
        f'font-family:{_ff}; font-size:15px; color:#6b6b76;">'
        'Conversemos hoy mismo cómo podemos sumar a tu equipo.</p>'
        + botones_html +
        '</td></tr></table></td></tr>'
    )

    html = f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" lang="es">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta http-equiv="X-UA-Compatible" content="IE=edge" />
    <meta name="x-apple-disable-message-reformatting" />
    <title>{_esc(marca)}</title>
    <!--[if !mso]><!-->
    <link href="https://fonts.googleapis.com/css2?family=Saira:wght@400;500;600;700&display=swap" rel="stylesheet" />
    <!--<![endif]-->
    <!--[if mso]>
    <style type="text/css">table{{border-collapse:collapse;}} body,table,td{{font-family:Arial,Helvetica,sans-serif !important;}}</style>
    <![endif]-->
    {estilos}
</head>
<body style="margin:0; padding:0; background-color:#eef0f4; -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%;">
    <div style="display:none; max-height:0; overflow:hidden; mso-hide:all; font-size:1px; line-height:1px; color:#eef0f4; opacity:0;">
        {preheader}&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;
    </div>

    <table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" style="background-color:#eef0f4;">
        <tr>
            <td align="center" style="padding:34px 12px;">

                <table role="presentation" class="cont" width="600" border="0" cellpadding="0" cellspacing="0" style="width:600px; max-width:600px; background-color:#ffffff; border-radius:14px; overflow:hidden; box-shadow:0 6px 24px rgba(36,26,51,0.10);">

                    <!-- Barra bicolor superior -->
                    <tr>
                        <td style="padding:0; font-size:0; line-height:0;">
                            <table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td width="66%" style="height:6px; background-color:#5b2d91; font-size:0; line-height:0;">&nbsp;</td>
                                    <td width="34%" style="height:6px; background-color:#8bc53f; font-size:0; line-height:0;">&nbsp;</td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Header: logo + web -->
                    <tr>
                        <td class="px" style="padding:26px 40px 22px 40px;">
                            <table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td align="left" valign="middle">{logo_html}</td>
                                    <td align="right" valign="middle" style="font-family:{_ff}; font-size:13px; color:#9a9aa6; letter-spacing:0.3px;">{_esc(emp_web)}</td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Hero -->
                    <tr>
                        <td class="hero-px" bgcolor="#5b2d91" style="background-color:#5b2d91; padding:36px 44px 38px 44px;">
                            <p style="margin:0 0 12px 0; font-family:{_ff}; font-size:12px; font-weight:bold; letter-spacing:2px; text-transform:uppercase; color:#a8e05f;">
                                Outsourcing y selección de personal
                            </p>
                            <h1 class="h1" style="margin:0 0 14px 0; font-family:{_ff}; font-size:30px; line-height:1.22; font-weight:bold; color:#ffffff;">
                                El personal indicado para tu empresa, cuando lo necesitás.
                            </h1>
                            <p style="margin:0; font-family:{_ff}; font-size:16px; line-height:1.6; color:#e3d8f2;">
                                Más de <strong style="color:#ffffff;">15 años</strong> en outsourcing y selección de personal para empresas como la tuya.
                            </p>
                        </td>
                    </tr>

                    <!-- Cuerpo -->
                    <tr>
                        <td class="px" style="padding:34px 44px 6px 44px;">
                            <p style="margin:0 0 16px 0; font-family:{_ff}; font-size:16px; line-height:1.65; color:#4a4a55;">
                                Hola <strong style="color:#241a33;">{saludo}</strong>,
                            </p>
                            <p style="margin:0 0 26px 0; font-family:{_ff}; font-size:16px; line-height:1.7; color:#4a4a55;">
                                En <strong style="color:#5b2d91;">{_esc(marca)}</strong> contamos con <strong>más de 15 años</strong> ayudando a las empresas a <strong>completar sus equipos de trabajo</strong>. Nos ocupamos del outsourcing, la búsqueda y la selección de personal: <em>vos definís el perfil y nosotros te presentamos a los candidatos indicados.</em>
                            </p>
                        </td>
                    </tr>

                    <!-- Pilares -->
                    <tr>
                        <td class="px" style="padding:0 44px 6px 44px;">
                            {_pilar_html("Outsourcing de personal", "Tercerizá la búsqueda, selección y administración de tu equipo.")}
                            {_pilar_html("Selección a medida", "Encontramos los recursos que encajan con tu operación.")}
                            {_pilar_html("Más de 15 años de experiencia", "Una trayectoria que respalda cada proceso.")}
                        </td>
                    </tr>

                    {cta_html}

                    {contacto_html}

                    {firma_area_html}
                </table>

                <!-- Footer -->
                <table role="presentation" class="cont" width="600" border="0" cellpadding="0" cellspacing="0" style="width:600px; max-width:600px;">
                    <tr>
                        <td style="padding:22px 40px 6px 40px; text-align:center; font-family:{_ff}; font-size:12px; line-height:1.6; color:#9a9aa6;">
                            <strong style="color:#6b6b76;">{_esc(marca)}</strong> &nbsp;·&nbsp; Outsourcing y selección de personal<br />
                            Esta es una comunicación corporativa de {_esc(marca)}.
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:2px 40px 26px 40px; text-align:center; font-family:{_ff}; font-size:12px; line-height:1.6; color:#9a9aa6;">
                            Si no deseas recibir más información, responde este correo con la palabra <strong style="color:#6b6b76;">"BAJA"</strong>.
                        </td>
                    </tr>
                </table>

            </td>
        </tr>
    </table>
</body>
</html>"""
    msg.add_alternative(html, subtype="html")
    _html_part = msg.get_payload()[1]

    # ── Adjuntar logo y firma-imagen como inline (CID) del HTML ──
    if logo_path:
        try:
            with open(logo_path, "rb") as _f:
                _datos = _f.read()
            _ext = os.path.splitext(logo_path)[1].lower().lstrip(".") or "png"
            if _ext == "jpg":
                _ext = "jpeg"
            _html_part.add_related(_datos, maintype="image", subtype=_ext,
                                   cid="<logo_empresa>")
        except Exception:
            pass

    if firma_img_path:
        try:
            with open(firma_img_path, "rb") as _f:
                _fdatos = _f.read()
            _fext = os.path.splitext(firma_img_path)[1].lower().lstrip(".") or "png"
            if _fext == "jpg":
                _fext = "jpeg"
            _html_part.add_related(_fdatos, maintype="image", subtype=_fext,
                                   cid="<firma_usuario>")
        except Exception:
            pass

    return msg


def enviar_correo(msg, destino, intentos_previos=0, nombre=""):
    """Envía un correo con reintentos acotados por red.

    Retorna uno de:
      "enviado"    - éxito
      "rechazado"  - destinatario inválido (SMTPRecipientsRefused).
                     Avanzar al siguiente.
      "auth"       - credenciales rotas. Abortar campaña.
      "agotado"    - se agotaron los MAX_REINTENTOS_RED. Abortar.
                     Queda guardado en `registro_pendiente.json`.
      "detenido"   - el usuario apretó "Detener". Queda guardado en
                     `registro_pendiente.json` para retomar luego.

    `intentos_previos`: si ya se hicieron N intentos en una sesión
    anterior (cargados desde pendiente), arrancamos desde ahí — así
    el tope de 1000 es global por correo, no por sesión.
    """
    cfg  = cargar_config()
    host = cfg.get("smtp_host", "smtp.gmail.com")
    port = int(cfg.get("smtp_port", 587))

    intento = max(0, int(intentos_previos))
    aviso_red = False

    while intento < MAX_REINTENTOS_RED:
        # Stop manual del usuario antes de cada intento de conexión
        if campana_detenida():
            guardar_pendiente(destino, nombre, intento)
            _emit_red("detenido", intento, MAX_REINTENTOS_RED, destino)
            return "detenido"

        intento += 1
        try:
            # Si el correo no tiene Message-ID (no se lo seteamos a mano),
            # Python lo va a generar al serializar. Para poder trackear-
            # lo después al detectar respuestas, lo seteamos NOSOTROS
            # acá y lo registramos antes de enviar.
            if not msg.get("Message-ID"):
                try:
                    from email.utils import make_msgid
                    msg["Message-ID"] = make_msgid()
                except Exception:
                    pass

            with smtplib.SMTP(host, port, timeout=30) as server:
                server.starttls()
                server.login(MI_CORREO(), MI_PASSWORD())
                server.send_message(msg)

            # Persistir Message-ID al registro de IDs enviados — es la
            # forma confiable de detectar respuestas aunque cambien el
            # asunto (la respuesta viene con In-Reply-To: <ese-id>).
            try:
                mid = msg.get("Message-ID") or ""
                if mid:
                    registrar_message_id_enviado(mid)
            except Exception:
                pass

            if aviso_red:
                _emit_red("recuperado", intento, MAX_REINTENTOS_RED, destino)
                print(f" Conexión recuperada. Enviado a {destino} "
                      f"en el intento {intento}.")
            # Limpiar pendiente si lo había
            borrar_pendiente()
            return "enviado"

        except smtplib.SMTPRecipientsRefused:
            logging.warning(
                f"Google avisó que este correo está mal escrito: {destino}"
            )
            borrar_pendiente()
            return "rechazado"

        except smtplib.SMTPAuthenticationError as e:
            logging.error(
                f"Credenciales SMTP rechazadas al enviar a {destino}: {e}"
            )
            borrar_pendiente()
            return "auth"

        except Exception as e:
            err_str = str(e)
            # Notificaciones escalonadas para no spamear:
            #   intento 1   → "caido"        (acaba de cortarse)
            #   intento 30  → "inestable"    (~5 min sin volver)
            #   cada 100    → "reintentando" (avance periódico)
            if intento == 1:
                aviso_red = True
                _emit_red("caido", intento, MAX_REINTENTOS_RED, destino)
                logging.error(
                    f"Sin conexión enviando a {destino}. "
                    f"Reintentos hasta {MAX_REINTENTOS_RED}. {err_str[:80]}"
                )
                print(f" Sin conexión enviando a {destino}. "
                      f"Reintento cada {INTERVALO_REINTENTO}s "
                      f"hasta {MAX_REINTENTOS_RED} intentos.")
            elif intento == 30:
                _emit_red("inestable", intento, MAX_REINTENTOS_RED, destino)
            elif intento % 100 == 0:
                _emit_red("reintentando", intento, MAX_REINTENTOS_RED, destino)
                print(f" Reintento {intento}/{MAX_REINTENTOS_RED} para "
                      f"{destino}...")

            # Persistimos el pendiente cada 10 intentos así sobrevivimos
            # a un crash/cerrar app sin perder el correo en cola.
            if intento % 10 == 0:
                guardar_pendiente(destino, nombre, intento)

            # Espera interrumpible: chequeamos stop event cada segundo
            for _ in range(INTERVALO_REINTENTO):
                if campana_detenida():
                    guardar_pendiente(destino, nombre, intento)
                    _emit_red("detenido", intento, MAX_REINTENTOS_RED, destino)
                    return "detenido"
                time.sleep(1)
            continue

    # Salimos del while → agotamos los reintentos sin éxito
    guardar_pendiente(destino, nombre, intento)
    _emit_red("agotado", intento, MAX_REINTENTOS_RED, destino)
    logging.error(
        f"Se agotaron los {MAX_REINTENTOS_RED} reintentos para {destino}. "
        f"Guardado en pendiente para retomar."
    )
    return "agotado"


# ==========================================
# 7. REVISIÓN DE REBOTES
# ==========================================
def revisar_rebotes(fecha_actual, enviados_hoy):
    print(f"\nRevisando si algún correo fue devuelto (fecha: {fecha_actual})...")
    rechazados = set()

    cfg       = cargar_config()
    imap_host = cfg.get("imap_host", "imap.gmail.com")
    # Cargar contactos de la campaña para filtrar — sólo contamos como
    # rechazados los que SÍ pertenecen a NUESTRA lista (evita contar
    # rebotes de otros correos del cliente).
    contactos_set = emails_de_contactos()

    try:
        with imaplib.IMAP4_SSL(imap_host) as mail:
            mail.login(MI_CORREO(), MI_PASSWORD())
            mail.select("inbox")

            fecha_google = datetime.strptime(fecha_actual, "%Y-%m-%d").strftime("%d-%b-%Y")
            # Buscar también de "postmaster" (algunos servers lo usan en vez
            # de mailer-daemon), no sólo googlemail.com
            ids_total = set()
            for remitente in ("mailer-daemon@googlemail.com",
                              "mailer-daemon", "postmaster"):
                try:
                    estado, mensajes = mail.search(
                        None, f'(FROM "{remitente}" SINCE "{fecha_google}")'
                    )
                    if estado == "OK" and mensajes and mensajes[0]:
                        for n in mensajes[0].split():
                            ids_total.add(n)
                except Exception:
                    continue

            if not ids_total:
                print("Todo excelente. Ningún correo rebotó hoy.")
                guardar_evento_historial(fecha_actual, "success",
                                         "Todo excelente. Ningún correo rebotó hoy.",
                                         enviados=enviados_hoy, rebotes=0)
                return

            for num_id in ids_total:
                try:
                    _, datos = mail.fetch(num_id, "(RFC822)")
                except Exception:
                    continue
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
                        if "daemon" in c_limpio or "postmaster" in c_limpio:
                            continue
                        if MI_CORREO().lower() in c_limpio:
                            continue
                        # Filtrar: sólo contamos rebotes de emails que
                        # pertenecen a la campaña actual (contactos.csv).
                        # Si no hay contactos cargados, aceptamos todo.
                        if contactos_set and c_limpio not in contactos_set:
                            continue
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

        # Auto-lista negra: todo correo que rebotó (postmaster/mailer-daemon,
        # "no entregable") se agrega para NO reintentarlo en futuras campañas.
        if rechazados:
            try:
                agregar_lote_lista_negra(
                    rechazados,
                    motivo="Rebote: correo no entregable (postmaster/mailer-daemon)",
                    auto=True,
                )
            except Exception:
                pass

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
    # Reset del flag de stop al comenzar la campaña — si veníamos de
    # un "Detener" previo, ya no aplica para esta corrida nueva.
    reset_stop_campana()

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

    # ── Retomar pendiente: si en una sesión anterior se cortó internet
    #    (o el usuario apretó Detener) y quedó un correo en `registro_
    #    pendiente.json`, lo intentamos PRIMERO antes de seguir el CSV.
    #    El tope de 1000 reintentos arranca desde el contador previo, así
    #    el límite de ~3hs es global por correo, no por sesión.
    pendiente = cargar_pendiente()
    if pendiente and pendiente.get("destino"):
        p_destino  = pendiente["destino"]
        p_nombre   = pendiente.get("nombre") or "Cliente"
        p_intentos = int(pendiente.get("intentos") or 0)

        # Si entre que se guardó el pendiente y ahora se agregó este
        # destinatario a la lista negra, no le mandamos. Borramos el
        # pendiente y seguimos con el CSV.
        if p_destino.lower() in cargar_lista_negra_set():
            msg = (f"Correo pendiente {p_destino} está en lista negra. "
                   "Descartado.")
            print(msg)
            guardar_evento_historial(hoy, "info", msg)
            borrar_pendiente()
            pendiente = None

    if pendiente and pendiente.get("destino"):
        msg_p = (f"Retomando correo pendiente: {p_destino} "
                 f"(intentos previos: {p_intentos}/{MAX_REINTENTOS_RED}).")
        print(msg_p)
        guardar_evento_historial(hoy, "info", msg_p)
        resultado = enviar_correo(
            preparar_correo(p_nombre, p_destino), p_destino,
            intentos_previos=p_intentos, nombre=p_nombre,
        )
        if resultado == "enviado":
            enviados += 1
            guardar_estado(p_destino, enviados, hoy)
            msg = f"Enviado con éxito a: {p_destino} (Van {enviados} de {limite})"
            print(msg)
            guardar_evento_historial(hoy, "success", msg, enviados=enviados)
        elif resultado == "rechazado":
            msg = f"Correo pendiente {p_destino} rechazado por Gmail. Avanzando."
            print(msg)
            guardar_evento_historial(hoy, "warning", msg)
            # ultimo_correo se actualiza al rechazado para no repetirlo
            guardar_estado(p_destino, enviados, hoy)
            ultimo_correo = p_destino
        elif resultado in ("detenido", "agotado", "auth"):
            # No se pudo: salimos sin tocar el CSV. Pendiente queda en disco.
            motivo = {
                "detenido": "Campaña detenida por el usuario.",
                "agotado":  (f"Sin conexión tras {MAX_REINTENTOS_RED} reintentos. "
                              "Campaña detenida automáticamente."),
                "auth":     "Credenciales SMTP rechazadas.",
            }[resultado]
            print(motivo)
            guardar_evento_historial(hoy, "error", motivo, enviados=enviados)
            return

    with open(ARCHIVO_CSV, "r", encoding="utf-8") as f:
        lista_clientes = list(csv.DictReader(f))

    # Recargar último_correo después de procesar pendiente — puede haberse
    # actualizado si el pendiente fue enviado o rechazado.
    estado_post = cargar_estado()
    if estado_post.get("fecha") == hoy:
        ultimo_correo = estado_post.get("ultimo_email", ultimo_correo)

    saltar_hasta_ultimo = bool(ultimo_correo)
    if saltar_hasta_ultimo:
        print("Avanzando automáticamente hasta encontrar dónde nos quedamos la última vez...")

    # Lista negra cargada UNA vez al inicio del loop para no leer disco
    # por cada iteración. Si el usuario agrega manualmente alguien mid-
    # campaña, se aplicará en la próxima corrida (igualmente la mayoría
    # de adds son automáticos al recibir un BAJA, que se aplica en la
    # siguiente campaña).
    # Set de exclusión: lista negra (opt-outs + rebotes auto-agregados) MÁS
    # los correos que ya rebotaron antes (registro_rechazados.json). Así
    # NUNCA reenviamos a un correo que dio "no entregable"/postmaster ni a
    # uno ya depurado — no se repiten.
    blacklist = cargar_lista_negra_set()
    try:
        rechazados_previos = {
            (r.get("email") or "").strip().lower()
            for r in cargar_rechazados_todos(filtrar_por_contactos=False)
            if r.get("email")
        }
    except Exception:
        rechazados_previos = set()
    excluidos = blacklist | rechazados_previos
    skipped_blacklist = 0

    for fila in lista_clientes:
        if campana_detenida():
            msg = "Campaña detenida por el usuario."
            print(msg)
            guardar_evento_historial(hoy, "warning", msg, enviados=enviados)
            return

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

        # ── Exclusión: opt-outs + rebotes previos (no reenviar) ──
        if destino.lower() in excluidos:
            skipped_blacklist += 1
            if skipped_blacklist <= 5:   # primeros 5 al historial; el resto, batch
                guardar_evento_historial(
                    hoy, "info",
                    f"Saltado (lista negra / rebote previo): {destino}",
                )
            print(f" Saltado (lista negra / rebote previo): {destino}")
            continue

        nombre = (
            (fila.get("Nombre", "") + " " + fila.get("Apellidos", "")).strip()
            or fila.get("Nombre de Cuenta", "").strip()
            or "Cliente"
        )

        resultado = enviar_correo(
            preparar_correo(nombre, destino), destino,
            intentos_previos=0, nombre=nombre,
        )

        if resultado == "enviado":
            enviados += 1
            guardar_estado(destino, enviados, hoy)
            msg = f"Enviado con éxito a: {destino} (Van {enviados} de {limite})"
            print(msg)
            guardar_evento_historial(hoy, "success", msg, enviados=enviados)

            if enviados < limite:
                espera = random.randint(TIEMPO_MINIMO, TIEMPO_MAXIMO)
                print(f" Esperando {espera} segundos antes del siguiente...")
                # Sleep interrumpible: si el usuario pide detener durante
                # la pausa entre correos, salimos al instante.
                for _ in range(espera):
                    if campana_detenida():
                        msg = "Campaña detenida por el usuario."
                        print(msg)
                        guardar_evento_historial(hoy, "warning", msg,
                                                  enviados=enviados)
                        return
                    time.sleep(1)
        elif resultado == "rechazado":
            msg = f"Error al enviar a: {destino}"
            print(msg)
            guardar_evento_historial(hoy, "error", msg)
            # Avanzamos: el ultimo_email NO se actualiza para que
            # `revisar_rebotes` lo detecte como rebote.
        elif resultado in ("detenido", "agotado", "auth"):
            motivo = {
                "detenido": "Campaña detenida por el usuario.",
                "agotado":  (f"Sin conexión tras {MAX_REINTENTOS_RED} reintentos. "
                              "Campaña detenida automáticamente."),
                "auth":     "Credenciales SMTP rechazadas.",
            }[resultado]
            print(motivo)
            guardar_evento_historial(hoy, "error", motivo, enviados=enviados)
            return

    if enviados == 0 and ultimo_correo:
        msg = "No se enviaron correos nuevos. Ya terminamos la lista entera."
        print(f"\n{msg}")
        guardar_evento_historial(hoy, "info", msg)
    else:
        msg = f"Lista finalizada por el momento. Total enviados hoy: {enviados}"
        print(f"\n{msg}")
        guardar_evento_historial(hoy, "info", msg, enviados=enviados)

    if skipped_blacklist > 0:
        msg_bl = (f"Se saltaron {skipped_blacklist} contacto(s) por estar en "
                   "lista negra (opt-out).")
        print(msg_bl)
        guardar_evento_historial(hoy, "info", msg_bl)

    revisar_rebotes(hoy, enviados)


# ==========================================
# 9. RECHAZADOS: vista global y depurados
# ==========================================
def cargar_rechazados_todos(filtrar_por_contactos=True):
    """Devuelve lista [{email, fecha}] de todos los rechazados conocidos,
    sin duplicar. Por defecto filtra: sólo los que están en contactos.csv
    (es decir, los que pertenecen a NUESTRA campaña). Si no hay contactos
    cargados, devuelve todos. Cacheado por mtime."""
    clave = f"rechazados_todos_{filtrar_por_contactos}"
    def _loader():
        if not os.path.exists(ARCHIVO_RECHAZOS):
            return []
        try:
            with open(ARCHIVO_RECHAZOS, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []

        contactos_set = emails_de_contactos() if filtrar_por_contactos else set()

        vistos = {}
        for fecha in sorted(data.keys()):
            bloque = data.get(fecha) or {}
            for c in bloque.get("correos", []):
                c_lower = (c or "").strip().lower()
                if not c_lower:
                    continue
                if filtrar_por_contactos and contactos_set and c_lower not in contactos_set:
                    continue
                if c_lower not in vistos:
                    vistos[c_lower] = {"email": c_lower, "fecha": fecha}
        return list(vistos.values())
    return _cached_read(clave, ARCHIVO_RECHAZOS, _loader)


def cargar_depurados():
    """Set de correos marcados como ya depurados (ocultos en la pestaña)."""
    def _loader():
        if not os.path.exists(ARCHIVO_DEPURADOS):
            return set()
        try:
            with open(ARCHIVO_DEPURADOS, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set((c or "").lower() for c in data.get("depurados", []))
        except Exception:
            return set()
    return _cached_read("depurados", ARCHIVO_DEPURADOS, _loader)


def _guardar_depurados(conjunto):
    with open(ARCHIVO_DEPURADOS, "w", encoding="utf-8") as f:
        json.dump({"depurados": sorted(conjunto)}, f, indent=2, ensure_ascii=False)
    _cache_invalidate("depurados")


def marcar_depurado(email, borrar_de_gmail=False):
    """Marca el email como depurado. Si `borrar_de_gmail=True`, también
    mueve a la papelera el correo de mailer-daemon/postmaster que reportó
    el rebote (pensado para que el usuario haga un solo click y no tenga
    que ir a Gmail a borrar manualmente)."""
    actuales = cargar_depurados()
    actuales.add((email or "").strip().lower())
    _guardar_depurados(actuales)
    if borrar_de_gmail and email:
        try:
            return borrar_correo_rebote_gmail(email)
        except Exception:
            return 0
    return 0


def desmarcar_depurado(email):
    actuales = cargar_depurados()
    actuales.discard((email or "").strip().lower())
    _guardar_depurados(actuales)


def cargar_vistos():
    """Set de claves de hilos/respuestas ya vistas por el usuario."""
    def _loader():
        if not os.path.exists(ARCHIVO_VISTOS):
            return set()
        try:
            with open(ARCHIVO_VISTOS, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data.get("vistos", []))
        except Exception:
            return set()
    return _cached_read("vistos", ARCHIVO_VISTOS, _loader)


def _guardar_vistos(conjunto):
    try:
        with open(ARCHIVO_VISTOS, "w", encoding="utf-8") as f:
            json.dump({"vistos": sorted(conjunto)}, f, indent=2, ensure_ascii=False)
        _cache_invalidate("vistos")
    except Exception:
        pass


def marcar_visto(clave):
    """Marca un hilo/respuesta como visto por el usuario."""
    if not clave:
        return
    actuales = cargar_vistos()
    actuales.add(str(clave))
    _guardar_vistos(actuales)


def marcar_vistos(claves):
    """Marca varias claves como vistas en una sola escritura."""
    if not claves:
        return
    actuales = cargar_vistos()
    for c in claves:
        if c:
            actuales.add(str(c))
    _guardar_vistos(actuales)


# ── Hilos ignorados (out-of-office, unsubscribe, fuera de oficina, etc.) ──
def cargar_ignorados():
    """Set de claves de hilos que el usuario marcó como 'no me interesa'."""
    def _loader():
        if not os.path.exists(ARCHIVO_IGNORADOS):
            return set()
        try:
            with open(ARCHIVO_IGNORADOS, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data.get("ignorados", []))
        except Exception:
            return set()
    return _cached_read("ignorados", ARCHIVO_IGNORADOS, _loader)


def _guardar_ignorados(conjunto):
    try:
        with open(ARCHIVO_IGNORADOS, "w", encoding="utf-8") as f:
            json.dump({"ignorados": sorted(conjunto)}, f,
                      indent=2, ensure_ascii=False)
        _cache_invalidate("ignorados")
    except Exception:
        pass


def marcar_ignorado(clave):
    if not clave:
        return
    actuales = cargar_ignorados()
    actuales.add(str(clave))
    _guardar_ignorados(actuales)


def desmarcar_ignorado(clave):
    actuales = cargar_ignorados()
    actuales.discard(str(clave))
    _guardar_ignorados(actuales)


# Patrones que sugieren un correo automático (auto-reply, out-of-office,
# unsubscribe, vacaciones, etc.). Se usan para sugerir ignorar pero
# NO se ignoran automáticamente — siempre lo decide el usuario.
_PATRONES_AUTO_REPLY = re.compile(
    r"\b("
    r"out\s*of\s*office|"
    r"automatic\s*reply|"
    r"auto[-\s]?reply|"
    r"fuera\s*de\s*(la\s*)?oficina|"
    r"respuesta\s*autom[aá]tica|"
    r"vacaci[oó]n(es)?|"
    r"unsubscribe|"
    r"desuscribir|"
    r"baja\s*de\s*la\s*lista|"
    r"no[-\s]?reply|"
    r"do[-\s]?not[-\s]?reply"
    r")\b",
    re.IGNORECASE,
)


def parece_auto_reply(asunto):
    """True si el asunto coincide con patrones típicos de respuesta automática."""
    if not asunto:
        return False
    return bool(_PATRONES_AUTO_REPLY.search(asunto))


# ============================================================
# Re-escaneo forzado de rebotes (mailer-daemon + postmaster)
# ============================================================
# Direcciones que típicamente envían bounces.
_REMITENTES_REBOTE = [
    "mailer-daemon@googlemail.com",
    "mailer-daemon",          # genérico (cualquier dominio)
    "postmaster",
]


def revisar_rebotes_recientes(dias=7):
    """Re-escanea IMAP en los últimos `dias` días buscando bounces de
    mailer-daemon y postmaster, y reconstruye el listado de rechazados
    sólo con los correos que TODAVÍA están en la bandeja (los que el
    cliente eliminó manualmente desaparecen) Y que pertenecen a la
    campaña (están en contactos.csv).
    Devuelve dict con: total, agregados, eliminados (limpiados de la lista).
    """
    cfg = cargar_config()
    correo   = (cfg.get("correo")   or "").strip()
    password = (cfg.get("password") or "").strip()
    imap_host = (cfg.get("imap_host") or "imap.gmail.com").strip()
    if not correo or not password:
        return {"total": 0, "agregados": 0, "eliminados": 0,
                "error": "Sin credenciales"}

    desde = (datetime.now() - timedelta(days=int(dias or 7))).strftime("%d-%b-%Y")
    # Cargamos la lista de contactos de la campaña — sólo nos interesan
    # los rebotes de emails que pertenecen a NUESTRA lista de envío.
    contactos_set = emails_de_contactos()

    # Set actual de rechazados (para detectar nuevos vs eliminados)
    actuales_set = set()
    historial_actual = {}
    if os.path.exists(ARCHIVO_RECHAZOS):
        try:
            with open(ARCHIVO_RECHAZOS, "r", encoding="utf-8") as f:
                historial_actual = json.load(f)
            for fecha_k, bloque in historial_actual.items():
                for c in (bloque.get("correos") or []):
                    cl = (c or "").strip().lower()
                    if cl:
                        actuales_set.add(cl)
        except Exception:
            historial_actual = {}

    encontrados = {}   # {fecha_str: set(emails)}

    try:
        with imaplib.IMAP4_SSL(imap_host) as mail:
            mail.login(correo, password)
            mail.select("inbox", readonly=True)

            # Buscar correos de cada remitente típico de rebotes
            ids_total = set()
            for remitente in _REMITENTES_REBOTE:
                try:
                    estado, ids = mail.search(
                        None, f'(FROM "{remitente}" SINCE "{desde}")'
                    )
                    if estado == "OK" and ids and ids[0]:
                        for n in ids[0].split():
                            ids_total.add(n)
                except Exception:
                    continue

            # También por el subject (algunos servers no usan mailer-daemon)
            for asunto_kw in ("Delivery Status Notification",
                              "Undeliverable",
                              "Mail Delivery Failure"):
                try:
                    estado, ids = mail.search(
                        None, f'(SUBJECT "{asunto_kw}" SINCE "{desde}")'
                    )
                    if estado == "OK" and ids and ids[0]:
                        for n in ids[0].split():
                            ids_total.add(n)
                except Exception:
                    continue

            for num_id in ids_total:
                try:
                    _, datos = mail.fetch(num_id, "(RFC822)")
                except Exception:
                    continue
                for r in datos:
                    if not isinstance(r, tuple):
                        continue
                    try:
                        raw = email.message_from_bytes(r[1])
                    except Exception:
                        continue

                    # Fecha del rebote
                    fecha_str = datetime.now().strftime("%Y-%m-%d")
                    try:
                        dt = parsedate_to_datetime(raw.get("Date", ""))
                        if dt:
                            fecha_str = dt.strftime("%Y-%m-%d")
                    except Exception:
                        pass

                    # Extraer email rebotado del cuerpo
                    cuerpo = _texto_correo(raw)
                    encontrado = ""
                    for c in re.findall(
                        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
                        cuerpo,
                    ):
                        cl = c.lower()
                        if "daemon" in cl or "postmaster" in cl:
                            continue
                        if cl == correo.lower():
                            continue
                        encontrado = cl
                        break

                    if encontrado:
                        # Sólo lo contamos si pertenece a la campaña (está en
                        # contactos.csv). Si no hay contactos cargados,
                        # aceptamos todo (modo legacy).
                        if not contactos_set or encontrado in contactos_set:
                            encontrados.setdefault(fecha_str, set()).add(encontrado)

        # Reconstruir el archivo de rechazados con SOLO los encontrados
        # (esto efectivamente "limpia" rechazados que el usuario eliminó
        # manualmente del INBOX, como pidió el cliente)
        nuevo_historial = {}
        for fecha_k, emails in encontrados.items():
            nuevo_historial[fecha_k] = {
                "total":   len(emails),
                "correos": sorted(emails),
            }

        with open(ARCHIVO_RECHAZOS, "w", encoding="utf-8") as f:
            json.dump(nuevo_historial, f, indent=4, ensure_ascii=False)

        nuevos_set = set()
        for emails in encontrados.values():
            nuevos_set |= emails

        # Auto-lista negra: los rebotados no se reintentan nunca más.
        if nuevos_set:
            try:
                agregar_lote_lista_negra(
                    nuevos_set,
                    motivo="Rebote: correo no entregable",
                    auto=True,
                )
            except Exception:
                pass

        # Sincronizar el contador de "rebotes" del historial diario, así
        # el Dashboard y Estadísticas reflejan el número correcto sin
        # esperar a que se vuelva a correr la campaña.
        try:
            for fecha_k, emails in encontrados.items():
                data_dia = cargar_historial_dia(fecha_k)
                data_dia["rebotes"] = len(emails)
                ruta = _ruta_historial_dia(fecha_k)
                with open(ruta, "w", encoding="utf-8") as f:
                    json.dump(data_dia, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

        return {
            "total":      len(nuevos_set),
            "agregados":  len(nuevos_set - actuales_set),
            "eliminados": len(actuales_set - nuevos_set),
            "error":      "",
        }

    except Exception as e:
        logging.error(f"Error en revisar_rebotes_recientes: {e}")
        return {"total": 0, "agregados": 0, "eliminados": 0,
                "error": str(e)}


def borrar_correo_rebote_gmail(email_rechazado):
    """Busca el(los) correo(s) de mailer-daemon/postmaster en INBOX que
    rebotaron a `email_rechazado` y los mueve a la papelera de Gmail.
    Devuelve cantidad de correos movidos."""
    cfg = cargar_config()
    correo   = (cfg.get("correo")   or "").strip()
    password = (cfg.get("password") or "").strip()
    imap_host = (cfg.get("imap_host") or "imap.gmail.com").strip()
    if not correo or not password or not email_rechazado:
        return 0

    email_lower = email_rechazado.lower().strip()
    movidos = 0

    try:
        with imaplib.IMAP4_SSL(imap_host) as mail:
            mail.login(correo, password)

            # Detectar dinámicamente el buzón Trash/Papelera de esta cuenta
            buzon_papelera = _detectar_buzon_papelera(mail)

            # ── 1) Borrar el correo de mailer-daemon / postmaster del INBOX
            mail.select("inbox")
            ids_buscar = set()
            for remitente in _REMITENTES_REBOTE:
                try:
                    estado, ids = mail.search(None, f'(FROM "{remitente}")')
                    if estado == "OK" and ids and ids[0]:
                        for n in ids[0].split():
                            ids_buscar.add(n)
                except Exception:
                    continue

            for num_id in ids_buscar:
                try:
                    _, datos = mail.fetch(num_id, "(RFC822)")
                except Exception:
                    continue
                for r in datos:
                    if not isinstance(r, tuple):
                        continue
                    try:
                        raw = email.message_from_bytes(r[1])
                    except Exception:
                        continue
                    cuerpo = _texto_correo(raw).lower()
                    if email_lower in cuerpo:
                        movido_ok = False
                        try:
                            estado_copy, _ = mail.copy(num_id, buzon_papelera)
                            if estado_copy == "OK":
                                movido_ok = True
                        except Exception:
                            pass
                        if movido_ok:
                            try:
                                mail.store(num_id, '+FLAGS', '\\Deleted')
                                movidos += 1
                            except Exception:
                                pass
                        break

            try:
                mail.expunge()
            except Exception:
                pass

            # ── 2) Borrar el correo ENVIADO original al destinatario.
            # Buscamos en todos los buzones de "enviados" comunes.
            for buzon_sent in _BUZONES_SENT:
                try:
                    estado_sel, _ = mail.select(buzon_sent, readonly=False)
                    if estado_sel != "OK":
                        continue
                    estado, ids = mail.search(
                        None, f'(TO "{email_rechazado}")'
                    )
                    if estado == "OK" and ids and ids[0]:
                        for num_id in ids[0].split():
                            try:
                                estado_copy, _ = mail.copy(num_id, buzon_papelera)
                                if estado_copy == "OK":
                                    mail.store(num_id, '+FLAGS', '\\Deleted')
                                    movidos += 1
                            except Exception:
                                continue
                        try:
                            mail.expunge()
                        except Exception:
                            pass
                    # Salimos al primer buzón Sent que existió
                    break
                except Exception:
                    continue

    except Exception as e:
        # Silencioso: si no hay nada para borrar, no es un error real para
        # el usuario. Sólo se loguea para debug.
        msg_err = str(e).lower()
        if "no such" in msg_err or "doesn't exist" in msg_err or "not found" in msg_err:
            return movidos  # no es error
        logging.error(f"Error moviendo rebote a papelera ({email_rechazado}): {e}")

    return movidos


# ── Cola IMAP batch ─────────────────────────────────────────────
# Cuando el usuario depura varios emails seguidos, en vez de abrir/cerrar
# una conexión IMAP por cada uno (lento), encolamos todos en una sola
# conexión. Un thread worker procesa la cola, mantiene la sesión IMAP
# abierta y hace todos los deletes batch.
import threading as _threading
_GMAIL_DEL_QUEUE   = []
_GMAIL_DEL_LOCK    = _threading.Lock()
_GMAIL_DEL_RUNNING = [False]


def encolar_borrado_gmail(email_rechazado, callback=None):
    """Encola `email_rechazado` para borrar de Gmail. Si no hay worker
    corriendo, lo lanza. callback(email, movidos) se ejecuta cuando
    cada email termina de procesarse."""
    if not email_rechazado:
        return
    with _GMAIL_DEL_LOCK:
        _GMAIL_DEL_QUEUE.append((email_rechazado, callback))
        if _GMAIL_DEL_RUNNING[0]:
            return  # ya hay un worker, se va a comer este item también
        _GMAIL_DEL_RUNNING[0] = True
    _threading.Thread(target=_gmail_delete_worker, daemon=True).start()


def _gmail_delete_worker():
    """Worker que consume la cola con UNA sola conexión IMAP. Mucho más
    rápido que abrir IMAP por cada email."""
    cfg = cargar_config()
    correo   = (cfg.get("correo")   or "").strip()
    password = (cfg.get("password") or "").strip()
    imap_host = (cfg.get("imap_host") or "imap.gmail.com").strip()
    if not correo or not password:
        with _GMAIL_DEL_LOCK:
            _GMAIL_DEL_RUNNING[0] = False
            _GMAIL_DEL_QUEUE.clear()
        return

    es_gmail = "gmail" in imap_host.lower() or "googlemail" in imap_host.lower()

    try:
        with imaplib.IMAP4_SSL(imap_host) as mail:
            mail.login(correo, password)
            buzon_papelera = _detectar_buzon_papelera(mail)

            # Detectar buzón Sent que existe en esta cuenta (una sola vez)
            buzon_sent_actual = None
            for buzon_sent in _BUZONES_SENT:
                try:
                    estado_sel, _ = mail.select(buzon_sent, readonly=True)
                    if estado_sel == "OK":
                        buzon_sent_actual = buzon_sent
                        break
                except Exception:
                    continue

            # Helper: mueve físicamente el mensaje (UID) a la papelera.
            # Usamos UID MOVE (RFC 6851) cuando está disponible — es una
            # operación atómica del servidor. Gmail lo soporta. Si el
            # servidor no implementa MOVE, caemos a UID COPY + UID STORE
            # \Deleted + UID EXPUNGE (todo por UID, no por seq number,
            # para evitar invalidaciones por concurrencia).
            def _mover_uid_a_papelera(uid):
                # Intento 1: UID MOVE (atómico)
                try:
                    estado, _ = mail.uid('MOVE', uid, buzon_papelera)
                    if estado == "OK":
                        return True
                except Exception:
                    pass
                # Intento 2: UID COPY + UID STORE + UID EXPUNGE
                try:
                    estado_copy, _ = mail.uid('COPY', uid, buzon_papelera)
                    if estado_copy != "OK":
                        return False
                    mail.uid('STORE', uid, '+FLAGS', '\\Deleted')
                    # UID EXPUNGE sólo borra el UID puntual (no toda la
                    # carpeta), evitando matar mensajes ajenos con \Deleted
                    try:
                        mail.uid('EXPUNGE', uid)
                    except Exception:
                        # Servidor no soporta UID EXPUNGE → expunge total
                        try:
                            mail.expunge()
                        except Exception:
                            pass
                    return True
                except Exception:
                    return False

            while True:
                with _GMAIL_DEL_LOCK:
                    if not _GMAIL_DEL_QUEUE:
                        _GMAIL_DEL_RUNNING[0] = False
                        return
                    email_obj, cb = _GMAIL_DEL_QUEUE.pop(0)

                movidos = 0
                email_lower = email_obj.lower().strip()

                # ── 1) Buscar bounce(s) del rebote en INBOX ──
                # Sacamos UIDs (no seq numbers) para que sigan siendo
                # válidos aunque otra operación borre algo en paralelo.
                try:
                    mail.select("inbox", readonly=False)
                except Exception:
                    pass

                uids_inbox = []
                try:
                    estado, ids = mail.uid(
                        'SEARCH', None, f'(BODY "{email_obj}")'
                    )
                    if estado == "OK" and ids and ids[0]:
                        uids_inbox = ids[0].split()
                except Exception:
                    pass

                # IDs originales del correo enviado que rebotó.
                # Los extraemos del header In-Reply-To del bounce — eso
                # apunta exactamente al Message-ID del correo que mandamos.
                # Esto garantiza que sólo borramos ESE correo del Sent y
                # no cualquier otro correo legítimo enviado al mismo email.
                ids_originales = set()

                for uid in uids_inbox:
                    try:
                        _, datos = mail.uid(
                            'FETCH', uid, '(BODY.PEEK[HEADER])'
                        )
                    except Exception:
                        continue
                    es_bounce = False
                    in_reply_to = ""
                    for r in datos:
                        if not isinstance(r, tuple):
                            continue
                        try:
                            raw = email.message_from_bytes(r[1])
                        except Exception:
                            continue
                        from_hdr = (raw.get("From", "") or "").lower()
                        if ("daemon" in from_hdr or "postmaster" in from_hdr
                                or "mail-daemon" in from_hdr):
                            es_bounce = True
                            in_reply_to = (
                                raw.get("In-Reply-To", "")
                                or raw.get("References", "")
                                or ""
                            ).strip()
                        break

                    if not es_bounce:
                        continue

                    # Mover el bounce a la papelera
                    if _mover_uid_a_papelera(uid):
                        movidos += 1

                    # Si pudimos extraer el Message-ID original, marcarlo
                    # para borrar también su gemelo en Sent.
                    if in_reply_to:
                        # Tomamos sólo el primer <id> si vienen varios
                        m = re.search(r"<[^>]+>", in_reply_to)
                        if m:
                            ids_originales.add(m.group(0))

                # ── 2) Mover el correo enviado original (matching exacto
                #     por Message-ID) a la papelera ──
                # Buscamos en TODAS las carpetas posibles (Sent, Inbox,
                # All Mail). Esto cubre el caso "restaurar y volver a
                # depurar": después de restaurar, el correo enviado puede
                # estar en INBOX (no en Sent), así que buscar sólo en Sent
                # lo perdería. Buscamos por HEADER Message-ID exacto, así
                # que es imposible tocar un correo legítimo de otro id.
                if ids_originales:
                    buzones_a_revisar = []
                    if buzon_sent_actual:
                        buzones_a_revisar.append(buzon_sent_actual)
                    buzones_a_revisar.append("inbox")
                    # All Mail (Gmail) — contiene archivados/movidos también
                    for b_am in _BUZONES_ALL_MAIL:
                        buzones_a_revisar.append(b_am)

                    uids_movidos_global = set()
                    for buzon_busq in buzones_a_revisar:
                        try:
                            estado_sel, _ = mail.select(
                                buzon_busq, readonly=False
                            )
                            if estado_sel != "OK":
                                continue
                        except Exception:
                            continue
                        for msg_id_original in ids_originales:
                            try:
                                estado, ids = mail.uid(
                                    'SEARCH', None,
                                    'HEADER', 'Message-ID',
                                    msg_id_original,
                                )
                            except Exception:
                                continue
                            if estado != "OK" or not ids or not ids[0]:
                                continue
                            for uid_sent in ids[0].split():
                                # Evitar contar 2x el mismo Gmail-msg que
                                # aparece en Sent + All Mail (mismo X-GM-MSGID)
                                clave = (buzon_busq, uid_sent)
                                if clave in uids_movidos_global:
                                    continue
                                uids_movidos_global.add(clave)
                                if _mover_uid_a_papelera(uid_sent):
                                    movidos += 1

                if cb:
                    try:
                        cb(email_obj, movidos)
                    except Exception:
                        pass

    except Exception as e:
        msg_err = str(e).lower()
        if not any(k in msg_err for k in ("eof", "timeout", "timed out",
                                          "no such", "doesn't exist",
                                          "not found")):
            logging.error(f"Worker batch delete falló: {e}")
    finally:
        with _GMAIL_DEL_LOCK:
            _GMAIL_DEL_RUNNING[0] = False


def restaurar_correo_rebote_gmail(email_rechazado):
    """Si en la PAPELERA hay correos relacionados con `email_rechazado`
    (rebote de mailer-daemon o el original enviado), los mueve de vuelta
    a INBOX. Si no hay nada en papelera, no hace nada (no es error).
    Devuelve cantidad de correos restaurados."""
    cfg = cargar_config()
    correo   = (cfg.get("correo")   or "").strip()
    password = (cfg.get("password") or "").strip()
    imap_host = (cfg.get("imap_host") or "imap.gmail.com").strip()
    if not correo or not password or not email_rechazado:
        return 0

    email_lower = email_rechazado.lower().strip()
    restaurados = 0
    es_gmail = "gmail" in imap_host.lower() or "googlemail" in imap_host.lower()

    try:
        with imaplib.IMAP4_SSL(imap_host) as mail:
            mail.login(correo, password)
            buzon_papelera = _detectar_buzon_papelera(mail)
            try:
                estado_sel, _ = mail.select(buzon_papelera)
            except Exception:
                return 0
            if estado_sel != "OK":
                return 0

            def _restaurar_a_inbox(num_id):
                # UID MOVE de la papelera al INBOX. Operación atómica del
                # servidor, sin riesgo de permadelete por race condition.
                # Convertimos num_id (seq number del search) a UID primero.
                try:
                    estado_uid, datos_uid = mail.fetch(num_id, '(UID)')
                    if estado_uid != "OK" or not datos_uid:
                        return False
                    m = re.search(rb'UID (\d+)', datos_uid[0] or b'')
                    if not m:
                        return False
                    uid = m.group(1)
                except Exception:
                    return False
                try:
                    estado, _ = mail.uid('MOVE', uid, '"INBOX"')
                    if estado == "OK":
                        return True
                except Exception:
                    pass
                try:
                    estado_copy, _ = mail.uid('COPY', uid, '"INBOX"')
                    if estado_copy == "OK":
                        mail.uid('STORE', uid, '+FLAGS', '\\Deleted')
                        try:
                            mail.uid('EXPUNGE', uid)
                        except Exception:
                            try:
                                mail.expunge()
                            except Exception:
                                pass
                        return True
                except Exception:
                    pass
                return False

            # Buscar bounces (mailer-daemon/postmaster) que mencionen el email
            ids_b = set()
            for remitente in _REMITENTES_REBOTE:
                try:
                    estado, ids = mail.search(None, f'(FROM "{remitente}")')
                    if estado == "OK" and ids and ids[0]:
                        for n in ids[0].split():
                            ids_b.add(n)
                except Exception:
                    continue

            for num_id in ids_b:
                try:
                    _, datos = mail.fetch(num_id, "(RFC822)")
                except Exception:
                    continue
                for r in datos:
                    if not isinstance(r, tuple):
                        continue
                    try:
                        raw = email.message_from_bytes(r[1])
                    except Exception:
                        continue
                    cuerpo = _texto_correo(raw).lower()
                    if email_lower in cuerpo:
                        if _restaurar_a_inbox(num_id):
                            restaurados += 1
                        break

            # Buscar también el correo original (TO email_rechazado) en papelera
            try:
                estado, ids = mail.search(
                    None, f'(TO "{email_rechazado}")'
                )
                if estado == "OK" and ids and ids[0]:
                    for num_id in ids[0].split():
                        if _restaurar_a_inbox(num_id):
                            restaurados += 1
            except Exception:
                pass

            if not es_gmail:
                try:
                    mail.expunge()
                except Exception:
                    pass

    except Exception as e:
        msg_err = str(e).lower()
        if "no such" in msg_err or "doesn't exist" in msg_err or "not found" in msg_err:
            return 0
        logging.error(f"Error restaurando rebote ({email_rechazado}): {e}")

    return restaurados


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
    """Devuelve set de todos los correos válidos del CSV (los 3 campos).
    Cacheado por mtime — si el CSV no cambió, devuelve el set anterior
    sin reabrir el archivo (para campañas con 30k+ contactos esto
    evita relecturas costosas en cada cambio de pestaña)."""
    def _loader():
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
    return _cached_read("emails_contactos", ARCHIVO_CSV, _loader)


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
# Dominios desde los que llegan emails de confirmación de reunión.
# Detectamos AMBAS plataformas siempre (independiente de cuál usa el
# usuario en el botón) — así si cambia de Calendly a Cal.com o viceversa
# no pierde el histórico de bookings de la otra.
_DOMINIOS_REUNION = {
    "calendly": ("calendly.com",),
    "cal_com":  ("cal.com", "no-reply@cal.com", "notifications@cal.com"),
}
# Mantenido por compatibilidad con código viejo
_DOMINIOS_CALENDLY = _DOMINIOS_REUNION["calendly"]


def _identificar_plataforma_reunion(remitente):
    """Devuelve 'calendly', 'cal_com' o None según el dominio del FROM."""
    if not remitente:
        return None
    r = remitente.lower()
    for plataforma, dominios in _DOMINIOS_REUNION.items():
        if any(d in r for d in dominios):
            return plataforma
    return None


def _cargar_respuestas_archivo():
    def _loader():
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
    return _cached_read("respuestas", ARCHIVO_RESPUESTAS, _loader)


def _guardar_respuestas_archivo(data):
    with open(ARCHIVO_RESPUESTAS, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    _cache_invalidate("respuestas")


def cargar_respuestas():
    """API pública: devuelve dict {respuestas: [...], calendly: [...]}."""
    return _cargar_respuestas_archivo()


def enviar_respuesta(destino, asunto, cuerpo, in_reply_to=None, references=None,
                     cc=None):
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

    firma_tipo   = (cfg.get("firma_tipo") or "texto").lower()
    firma_imagen = (cfg.get("firma_imagen") or "").strip()
    firma_texto  = (cfg.get("firma") or "").strip()

    # Para la versión texto plano (compatibilidad), incluir la firma de texto
    cuerpo_plano = cuerpo
    if firma_tipo == "texto" and firma_texto and firma_texto not in cuerpo_plano:
        cuerpo_plano = cuerpo_plano.rstrip() + "\n\n--\n" + firma_texto + "\n"

    # Sanitizar headers: Python prohíbe \r\n dentro de cabeceras.
    def _h(s):
        if not s:
            return ""
        return re.sub(r"\s+", " ", str(s).replace("\r", " ").replace("\n", " ")).strip()

    msg = EmailMessage()
    msg["Subject"]    = _h(asunto)
    msg["From"]       = _h(correo)
    msg["To"]         = _h(destino)
    if cc:
        cc_clean = _h(cc) if isinstance(cc, str) else _h(", ".join(cc))
        if cc_clean:
            msg["Cc"] = cc_clean
    msg["Date"]       = formatdate(localtime=True)
    try:
        dominio = correo.split("@", 1)[1] if "@" in correo else "localhost"
        msg["Message-ID"] = make_msgid(domain=dominio)
    except Exception:
        msg["Message-ID"] = make_msgid()
    if in_reply_to:
        msg["In-Reply-To"] = _h(in_reply_to)
    if references:
        # References puede tener varios Message-IDs separados por espacios;
        # los normalizamos sin saltos de línea.
        msg["References"] = _h(references)

    msg.set_content(cuerpo_plano)

    # Si la firma es una imagen, mandamos también una versión HTML con la
    # imagen como adjunto inline (CID). Esto es lo que Gmail/Outlook
    # respetan en clientes web Y mobile (las data URL muchas veces se
    # bloquean por anti-spam).
    if firma_tipo == "imagen" and firma_imagen and os.path.exists(firma_imagen):
        try:
            with open(firma_imagen, "rb") as f:
                img_bytes = f.read()
            ext = os.path.splitext(firma_imagen)[1].lstrip(".").lower() or "png"
            if ext == "jpg":
                ext = "jpeg"

            # CID único para esta firma
            firma_cid = make_msgid(domain="pulsemail.local").strip("<>")

            from html import escape as _html_escape
            cuerpo_html = _html_escape(cuerpo).replace("\n", "<br>")
            # max-width 380px + width attribute → Gmail Web respeta el
            # tamaño y mobile escala bien al 100%.
            html_body = (
                "<!doctype html><html><body style=\"font-family:Arial,"
                "sans-serif;font-size:14px;color:#1a1a1a;\">"
                f"<div>{cuerpo_html}</div>"
                "<br><br>"
                f"<img src=\"cid:{firma_cid}\" alt=\"Firma\" width=\"380\" "
                "style=\"max-width:380px;width:100%;height:auto;"
                "display:block;\"/>"
                "</body></html>"
            )
            msg.add_alternative(html_body, subtype="html")

            # Adjuntar la imagen como related al HTML que acabamos de
            # añadir (último payload del multipart).
            msg.get_payload()[-1].add_related(
                img_bytes,
                maintype="image",
                subtype=ext,
                cid=f"<{firma_cid}>",
                filename=f"firma_pulsemail.{ext}",
            )
        except Exception as e:
            logging.error(f"No se pudo embeber firma de imagen: {e}")

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

# "All Mail" en Gmail contiene TODOS los correos (Inbox + archivados +
# movidos a Importantes + cualquier etiqueta). Es la mejor fuente para
# reconstruir un hilo completo aunque el cliente haya archivado/movido
# manualmente alguno de los mensajes.
_BUZONES_ALL_MAIL = [
    '"[Gmail]/All Mail"',
    '"[Gmail]/Todos"',
    '"[Gmail]/Todos los correos"',
    '"[Google Mail]/All Mail"',
]


def _parse_mensaje_imap(raw_msg, direccion):
    asunto    = _decodificar_cabecera(raw_msg.get("Subject", ""))
    fecha     = _decodificar_cabecera(raw_msg.get("Date", ""))
    remitente = _decodificar_cabecera(raw_msg.get("From", ""))
    destino   = _decodificar_cabecera(raw_msg.get("To", ""))
    cc        = _decodificar_cabecera(raw_msg.get("Cc", ""))
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
        "cc":          cc,
        "subject":     asunto,
        "date":        fecha,
        "ts":          ts,
        "message_id":  msg_id,
        "in_reply_to": in_reply,
        "references":  refs,
        "body":        texto or body_md,
        "body_md":     body_md,
        "body_html":   html or "",
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

    mi_correo_low = (MI_CORREO() or "").lower()

    try:
        with imaplib.IMAP4_SSL(imap_host) as mail:
            mail.login(MI_CORREO(), MI_PASSWORD())

            # ── Estrategia: usar [Gmail]/All Mail ──
            # All Mail contiene TODOS los correos del usuario sin importar
            # etiquetas/carpetas (Inbox, Importantes, Archivados, Sent…).
            # Es la forma más confiable de reconstruir un hilo completo
            # aunque el cliente haya movido manualmente algún mensaje.
            buzon_principal = None
            for buzon in _BUZONES_ALL_MAIL:
                try:
                    estado, _ = mail.select(buzon, readonly=True)
                    if estado == "OK":
                        buzon_principal = buzon
                        break
                except Exception:
                    continue

            if buzon_principal:
                # En All Mail, un mismo email puede ser entrante O saliente.
                # Buscamos por participación: cualquier mensaje donde
                # `remitente` aparezca en From o To.
                ids_total = set()
                for query in (
                    f'(FROM "{remitente}" SINCE "{desde}")',
                    f'(TO "{remitente}" SINCE "{desde}")',
                    f'(CC "{remitente}" SINCE "{desde}")',
                ):
                    try:
                        estado, ids = mail.search(None, query)
                        if estado == "OK" and ids and ids[0]:
                            for n in ids[0].split():
                                ids_total.add(n)
                    except Exception:
                        continue

                # Fetch en BATCH: una sola llamada con todos los IDs
                # separados por coma. Es 5-10x más rápido que un fetch
                # por mensaje porque ahorra los round-trips IMAP.
                if ids_total:
                    id_list = b",".join(ids_total)
                    try:
                        _, fetched = mail.fetch(id_list, "(RFC822)")
                        for r in fetched:
                            if not isinstance(r, tuple):
                                continue
                            try:
                                raw = email.message_from_bytes(r[1])
                            except Exception:
                                continue
                            from_em = _extraer_email(
                                _decodificar_cabecera(raw.get("From", ""))
                            ).lower()
                            direccion = (
                                "saliente" if from_em == mi_correo_low
                                else "entrante"
                            )
                            _agregar(raw, direccion)
                    except Exception:
                        pass
            else:
                # Fallback: cuenta sin All Mail (no es Gmail) → buscamos
                # en INBOX y carpeta de Enviados como antes.
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
                                        _agregar(email.message_from_bytes(r[1]),
                                                  "entrante")
                            except Exception:
                                continue
                except Exception:
                    pass

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
                            break
                    except Exception:
                        continue
    except Exception as e:
        logging.error(f"Error obteniendo hilo de {remitente}: {e}")
        return []

    total_raw = len(mensajes)
    logging.info(f"Hilo {remitente!r}: {total_raw} mensajes raw encontrados")

    # Filtrar por asunto base si se pidió: matching tolerante.
    if asunto_base and mensajes:
        # Normalización: quitar pipe + nombre, espacios múltiples, signos.
        def _norm(s):
            s = re.sub(r"^\s*(Re:|Fwd?:)\s*", "", s or "", flags=re.IGNORECASE)
            s = re.sub(r"\s*\|\s*[^|]*$", "", s)   # quita "| Nombre" del final
            s = re.sub(r"\s+", " ", s).strip().lower()
            return s

        base_norm = _norm(asunto)
        # Tomamos los primeros 30 chars distintivos del asunto base
        clave_corta = base_norm[:30] if base_norm else ""

        def _coincide(msg):
            sub_norm = _norm(msg.get("subject", ""))
            if not clave_corta:
                return True
            return clave_corta in sub_norm or sub_norm in base_norm

        filtrados = [m for m in mensajes if _coincide(m)]

        # Fallback: si el filtro eliminó TODO pero teníamos mensajes,
        # mantenemos todos sin filtrar (mejor mostrar algo que nada).
        if filtrados:
            mensajes = filtrados
            logging.info(
                f"Hilo {remitente!r}: {len(mensajes)} mensajes después del filtro "
                f"de asunto ({clave_corta!r})"
            )
        else:
            logging.warning(
                f"Hilo {remitente!r}: filtro de asunto {clave_corta!r} dejó 0 "
                f"mensajes. Devolviendo {total_raw} sin filtrar como fallback."
            )

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


def _limpiar_html_quote(html_str):
    """Trunca el HTML al primer marcador de 'mensaje original quoted'.

    Cuando alguien responde un correo, Gmail/Outlook/Yahoo dejan debajo el
    mensaje original (con un header tipo 'El viernes 1 de mayo... escribió:'
    o 'On X, Y wrote:'). Eso ensucia la burbuja del hilo en la app, así que
    cortamos el HTML al primer marcador encontrado.
    """
    if not html_str:
        return html_str

    # Marcadores comunes que indican el inicio del quote.
    # Buscamos la posición más temprana entre todos.
    markers = [
        # Tags que siempre son quote
        r"<blockquote\b",
        # Contenedores de quote por cliente
        r'<div[^>]*class\s*=\s*["\'][^"\']*gmail_quote[^"\']*["\']',
        r'<div[^>]*class\s*=\s*["\'][^"\']*gmail_attr[^"\']*["\']',
        r'<div[^>]*class\s*=\s*["\'][^"\']*moz-cite-prefix[^"\']*["\']',
        r'<div[^>]*class\s*=\s*["\'][^"\']*yahoo_quoted[^"\']*["\']',
        r'<div[^>]*class\s*=\s*["\'][^"\']*OutlookMessageHeader[^"\']*["\']',
        r'<div[^>]*id\s*=\s*["\'][^"\']*appendonsend[^"\']*["\']',
        r'<div[^>]*id\s*=\s*["\'][^"\']*divRplyFwdMsg[^"\']*["\']',
        r'<hr[^>]*id\s*=\s*["\']stopSpelling["\']',
        # Cabeceras textuales típicas del quote
        r"On\s+\w+,\s+\w+\s+\d+,\s+\d{4}\s+at\s+\d+:\d+[^<]*wrote\s*:",
        r"El\s+\w+,?\s+\d{1,2}\s+(?:de\s+)?\w+\s+(?:de\s+)?\d{4}[^<]*escrib(?:i[oó]|ió)\s*:",
        r"El\s+\w+,?\s+\d{1,2}/\d{1,2}/\d{2,4}[^<]*escrib(?:i[oó]|ió)\s*:",
        # Outlook plain
        r"-{2,}\s*(?:Mensaje\s+(?:original|reenviado)|Original\s+Message)\s*-{2,}",
        r"_{5,}",  # divider del Outlook
        # "From: X" típica de forwards de Outlook
        r"From:\s*[^\n<]*<\s*[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-.]+\s*>",
    ]

    earliest = len(html_str)
    for patron in markers:
        try:
            match = re.search(patron, html_str, flags=re.IGNORECASE)
            if match and match.start() < earliest:
                earliest = match.start()
        except re.error:
            continue

    if earliest < len(html_str):
        # Cortamos y cerramos los tags básicos para que el HTML siga válido
        return html_str[:earliest].rstrip() + "</body></html>"
    return html_str


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

    # Eliminar <img> con cid: que no se pudieron resolver (quedan como
    # imagen rota y dejan un espacio blanco en el render). Igual con los
    # <img> sin src.
    if html_final:
        html_final = re.sub(
            r"<img\b[^>]*\bsrc\s*=\s*[\"']cid:[^\"']*[\"'][^>]*/?>",
            "", html_final, flags=re.IGNORECASE,
        )
        html_final = re.sub(
            r"<img\b(?:(?!src\s*=)[^>])*/?>",   # <img sin src
            "", html_final, flags=re.IGNORECASE,
        )

    # Quitar el "quote" del mensaje anterior (si esto es una respuesta)
    if html_final:
        html_final = _limpiar_html_quote(html_final)

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


# ── Detección de REBOTES (bounces) — NO son respuestas de clientes ──
# Un rebote llega desde postmaster/mailer-daemon (o con asunto tipo
# "Undeliverable") y trae In-Reply-To apuntando a nuestro correo, así que
# el detector lo tomaría como "respuesta". Lo interceptamos: el correo
# afectado va DIRECTO a lista negra (es problema del dominio destino, no
# una respuesta real) y NO aparece en el panel Respuestas.
_RE_ASUNTO_REBOTE = re.compile(
    r"(undeliverable|undelivered|delivery status notification|"
    r"delivery (?:has )?failed|mail delivery (?:failed|failure|subsystem|system)|"
    r"returned mail|failure notice|no se pudo entregar|correo no entregado|"
    r"mensaje no entregado|devoluci[oó]n de correo)",
    re.IGNORECASE,
)


def _es_remitente_rebote(rem):
    """True si el From es un notificador de rebotes (postmaster/mailer-daemon)."""
    r = (rem or "").lower()
    return ("postmaster" in r or "mailer-daemon" in r or "mail-daemon" in r
            or "maildaemon" in r or "daemon" in r)


def _es_asunto_rebote(asunto):
    return bool(_RE_ASUNTO_REBOTE.search(asunto or ""))


def _extraer_email_rebotado(cuerpo, mi_correo, contactos):
    """Extrae del cuerpo del bounce el correo del destinatario que rebotó
    (el primero que no sea postmaster/daemon ni el nuestro, y que —si hay
    contactos cargados— pertenezca a la campaña)."""
    mi = (mi_correo or "").lower()
    for c in re.findall(
        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", cuerpo or ""
    ):
        cl = c.lower()
        if "daemon" in cl or "postmaster" in cl:
            continue
        if cl == mi:
            continue
        if contactos and cl not in contactos:
            continue
        return cl
    return ""


def detectar_respuestas_y_calendly(dias=30, forzar_full=False):
    """
    Busca por IMAP en los últimos `dias`:
      - Respuestas: correos cuyo From coincide con un contacto del CSV.
      - Calendly: correos de Calendly cuya confirmación menciona un contacto del CSV.
      - Auto-baja: respuestas que piden no recibir más → agregadas a lista negra.

    Persiste en registro_respuestas.json y devuelve el dict.

    `forzar_full=True` ignora el `_last_uid` cacheado y rescanea TODO el
    rango `SINCE dias`. Útil cuando se sospecha que se perdieron respuestas
    (UI muestra lista vacía pero el server tiene respuestas).
    """
    cfg = cargar_config()
    imap_host = cfg.get("imap_host", "imap.gmail.com")
    if not MI_CORREO() or not MI_PASSWORD():
        return _cargar_respuestas_archivo()

    contactos = emails_de_contactos()
    if not contactos:
        return _cargar_respuestas_archivo()

    data = _cargar_respuestas_archivo()

    # ── Limpieza: sacar del panel Respuestas los REBOTES (postmaster/
    #    mailer-daemon) que se hayan colado antes. No son respuestas de
    #    clientes — el correo afectado va a lista negra, no acá. ──
    _resp_limpias = [
        r for r in data["respuestas"]
        if not _es_remitente_rebote(r.get("from"))
    ]
    if len(_resp_limpias) != len(data["respuestas"]):
        data["respuestas"] = _resp_limpias

    vistos_resp = {(r.get("uid"), r.get("from")) for r in data["respuestas"]}
    vistos_cal  = {c.get("uid") for c in data["calendly"]}
    vistos_rebote = set(data.get("_rebotes_vistos", []))

    # IDs que mandamos NOSOTROS. Si una respuesta tiene In-Reply-To o
    # References apuntando a uno de estos IDs, ES una respuesta a un
    # correo nuestro — sin importar quién la mande ni qué asunto tenga.
    # Esto cubre los casos: cambio de asunto ("Baja", "Fuera de oficina"),
    # respuesta desde un alias o personal, anti-spam que re-empaqueta el
    # mensaje, etc.
    ids_propios = cargar_message_ids_enviados()

    try:
        desde = datetime.now() - timedelta(days=int(dias))
    except Exception:
        desde = datetime.now() - timedelta(days=30)
    fecha_imap = desde.strftime("%d-%b-%Y")

    # Tracking de UID máximo visto: en lugar de re-escanear los últimos
    # 30 días cada vez (lento, 100s de fetches), sólo buscamos UIDs
    # mayores al último procesado. Primer escaneo: usa SINCE; los
    # siguientes son casi instantáneos porque sólo bajan correos nuevos.
    # `forzar_full` resetea ese tracking para un re-escaneo completo.
    last_uid = 0 if forzar_full else int(data.get("_last_uid", 0) or 0)

    try:
        with imaplib.IMAP4_SSL(imap_host) as mail:
            mail.login(MI_CORREO(), MI_PASSWORD())
            mail.select("inbox")

            if last_uid > 0:
                estado, msgs = mail.uid(
                    "SEARCH", None, f"UID {last_uid + 1}:*"
                )
            else:
                estado, msgs = mail.uid(
                    "SEARCH", None, f'(SINCE "{fecha_imap}")'
                )
            if estado != "OK" or not msgs or not msgs[0]:
                _guardar_respuestas_archivo(data)
                return data

            uids = msgs[0].split()
            max_uid_visto = last_uid

            # Filtrar IN-MEMORY los UIDs nuevos (los <= last_uid ya se vieron).
            uids_nuevos = []
            for uid_b in uids:
                try:
                    uid_i = int(uid_b)
                except Exception:
                    continue
                if uid_i <= last_uid:
                    continue
                if uid_i > max_uid_visto:
                    max_uid_visto = uid_i
                uids_nuevos.append(uid_b)

            if not uids_nuevos:
                data["_last_uid"] = max_uid_visto
                _guardar_respuestas_archivo(data)
                return data

            # ──────────────────────────────────────────────────────────
            # PASO 1: BATCH FETCH de headers de TODOS los UIDs nuevos
            # ──────────────────────────────────────────────────────────
            # Antes hacíamos un FETCH individual por cada UID → 5000+
            # round-trips en una bandeja de 30 días con tráfico normal.
            # Ahora un fetch por chunk de 500 (10 round-trips para 5000).
            # Esto es lo que hizo el "Escanear bandeja" demorar mucho
            # con forzar_full=True.
            CHUNK_HEADERS = 500
            # Almacenamos por UID lo que necesitamos para decidir qué
            # hacer (sin volver a tocar IMAP).
            info_por_uid = {}   # uid_bytes -> {remitente, asunto, fecha, msg_id, in_reply_to, references}

            for i in range(0, len(uids_nuevos), CHUNK_HEADERS):
                chunk = uids_nuevos[i:i + CHUNK_HEADERS]
                try:
                    _, fetched = mail.uid(
                        "FETCH", b",".join(chunk), "(BODY.PEEK[HEADER])"
                    )
                except Exception:
                    continue
                # Parsear respuesta: tuplas (meta_bytes, header_body)
                uid_actual = None
                for item in fetched:
                    if isinstance(item, tuple) and len(item) >= 2:
                        m_uid = re.search(rb"UID (\d+)", item[0])
                        uid_actual = m_uid.group(1) if m_uid else None
                        if not uid_actual:
                            continue
                        try:
                            msg = email.message_from_bytes(item[1])
                        except Exception:
                            continue
                        rem_raw = _decodificar_cabecera(msg.get("From", ""))
                        info_por_uid[uid_actual] = {
                            "remitente":   _extraer_email(rem_raw),
                            "asunto":      _decodificar_cabecera(msg.get("Subject", "")),
                            "fecha":       _decodificar_cabecera(msg.get("Date", "")),
                            "msg_id":      msg.get("Message-ID", "") or uid_actual.decode("utf-8", "ignore"),
                            "in_reply_to": msg.get("In-Reply-To", "") or "",
                            "references":  msg.get("References", "") or "",
                        }

            # ──────────────────────────────────────────────────────────
            # PASO 2: Decisión local — qué UIDs necesitan cuerpo (RFC822)
            # ──────────────────────────────────────────────────────────
            mi_correo = (MI_CORREO() or "").lower()
            uids_necesita_cuerpo = []   # [(uid_b, "calendly"|"respuesta"|"rebote", info)]
            for uid_b, info in info_por_uid.items():
                rem = info["remitente"]
                if not rem:
                    continue
                if rem == mi_correo:
                    continue

                # ¿Responde a un correo nuestro? (match por Message-ID)
                respuesta_hilo = False
                if ids_propios:
                    headers_thread = f"{info['in_reply_to']} {info['references']}"
                    if headers_thread.strip():
                        for mid_ref in re.findall(r"<[^>]+>", headers_thread):
                            if mid_ref in ids_propios:
                                respuesta_hilo = True
                                break
                info["via_hilo"] = respuesta_hilo

                # ── REBOTE (bounce): postmaster/mailer-daemon, o un NDR de
                #    "no entregable" en respuesta a un correo nuestro. NO es
                #    una respuesta del cliente → el correo afectado va DIRECTO
                #    a lista negra y NO aparece en el panel Respuestas. ──
                if _es_remitente_rebote(rem) or (
                    respuesta_hilo and _es_asunto_rebote(info["asunto"])
                ):
                    if info["msg_id"] in vistos_rebote:
                        continue
                    uids_necesita_cuerpo.append((uid_b, "rebote", info))
                    continue

                plataforma = _identificar_plataforma_reunion(rem)
                if plataforma:
                    if info["msg_id"] in vistos_cal:
                        continue
                    info["plataforma"] = plataforma
                    uids_necesita_cuerpo.append((uid_b, "calendly", info))
                elif rem in contactos or respuesta_hilo:
                    clave = (info["msg_id"], rem)
                    if clave in vistos_resp:
                        continue
                    info["clave"] = clave
                    uids_necesita_cuerpo.append((uid_b, "respuesta", info))

            # ──────────────────────────────────────────────────────────
            # PASO 3: BATCH FETCH de RFC822 sólo para los necesarios
            # ──────────────────────────────────────────────────────────
            cuerpos_por_uid = {}   # uid_bytes -> texto plano
            if uids_necesita_cuerpo:
                CHUNK_CUERPOS = 100
                uids_a_fetch = [u for u, _, _ in uids_necesita_cuerpo]
                for i in range(0, len(uids_a_fetch), CHUNK_CUERPOS):
                    chunk = uids_a_fetch[i:i + CHUNK_CUERPOS]
                    try:
                        _, fetched = mail.uid(
                            "FETCH", b",".join(chunk), "(RFC822)"
                        )
                    except Exception:
                        continue
                    for item in fetched:
                        if isinstance(item, tuple) and len(item) >= 2:
                            m_uid = re.search(rb"UID (\d+)", item[0])
                            uid_actual = m_uid.group(1) if m_uid else None
                            if uid_actual:
                                try:
                                    msg_full = email.message_from_bytes(item[1])
                                    cuerpos_por_uid[uid_actual] = (
                                        _texto_correo(msg_full) or ""
                                    )
                                except Exception:
                                    cuerpos_por_uid[uid_actual] = ""

            # ──────────────────────────────────────────────────────────
            # PASO 4: Procesamiento local (sin más IMAP)
            # ──────────────────────────────────────────────────────────
            rebotados_nuevos = []   # correos que rebotaron → lista negra (lote)
            for uid_b, tipo, info in uids_necesita_cuerpo:
                cuerpo = cuerpos_por_uid.get(uid_b, "")
                rem = info["remitente"]
                msg_id = info["msg_id"]
                asunto = info["asunto"]
                fecha_msg = info["fecha"]

                if tipo == "calendly":
                    invitado = ""
                    for c in re.findall(
                        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
                        cuerpo,
                    ):
                        cl = c.lower()
                        if cl in contactos:
                            invitado = cl
                            break
                    data["calendly"].append({
                        "uid":        msg_id,
                        "from":       rem,
                        "subject":    asunto,
                        "plataforma": info["plataforma"],
                        "date":       fecha_msg,
                        "invitado":   invitado,
                    })
                    vistos_cal.add(msg_id)
                elif tipo == "rebote":
                    # El correo afectado va DIRECTO a lista negra (problema
                    # del dominio destino), NO al panel Respuestas.
                    rebotado = _extraer_email_rebotado(cuerpo, mi_correo, contactos)
                    if rebotado:
                        rebotados_nuevos.append(rebotado)
                    vistos_rebote.add(msg_id)
                else:  # respuesta
                    es_baja = False
                    razon_baja = ""
                    if cuerpo or asunto:
                        es_baja, razon_baja = es_pedido_de_baja(asunto, cuerpo)
                    if es_baja:
                        agregar_a_lista_negra(
                            rem,
                            motivo=f"Auto-baja: {razon_baja}",
                            auto=True,
                        )
                        logging.info(
                            f"Lista negra: {rem} agregado "
                            f"automáticamente ({razon_baja})"
                        )
                    data["respuestas"].append({
                        "uid":      msg_id,
                        "from":     rem,
                        "subject":  asunto,
                        "date":     fecha_msg,
                        "es_baja":  es_baja,
                        "via_hilo": info["via_hilo"],
                    })
                    vistos_resp.add(info["clave"])

            # Rebotados → lista negra en UNA sola escritura (rápido).
            if rebotados_nuevos:
                try:
                    agregar_lote_lista_negra(
                        rebotados_nuevos,
                        motivo="Rebote: correo no entregable (dominio destino)",
                        auto=True,
                    )
                except Exception:
                    pass

            data["_last_uid"] = max_uid_visto
            # Cap del tracking de rebotes vistos (evita crecer sin fin)
            data["_rebotes_vistos"] = list(vistos_rebote)[-8000:]
    except Exception as e:
        # Errores transitorios de red (SSL EOF, timeouts) NO los logueamos
        # como ERROR — son comunes con polling frecuente y no requieren
        # acción del usuario. Sólo se reportan a nivel debug.
        msg_err = str(e).lower()
        transient = any(k in msg_err for k in (
            "eof occurred", "timed out", "timeout",
            "connection reset", "connection aborted",
            "connection refused",
            "network is unreachable", "temporary failure",
        ))
        if transient:
            logging.debug(f"Escaneo respuestas: error transitorio: {e}")
        else:
            logging.error(f"No se pudo escanear respuestas: {e}")

    _guardar_respuestas_archivo(data)
    return data


# ==========================================
# 14. IMPORT / EXPORT — backup completo y archivos sueltos
# ==========================================

# Archivos de datos en la raíz del proyecto que entran al backup completo.
# Excluimos cosas como sistema_errores.log y __pycache__ que no son estado.
_ARCHIVOS_BACKUP = [
    "config.json",
    "contactos.csv",
    "registro_envios.json",
    "registro_rechazados.json",
    "registro_depurados.json",
    "registro_respuestas.json",
    "registro_vistos.json",
]


def importar_archivo_local(origen_path, nombre_local):
    """Copia un archivo externo a la carpeta del proyecto bajo `nombre_local`.
    Devuelve (ok, mensaje).
    Sobrescribe si ya existe (hace backup .bak previo)."""
    if not origen_path or not os.path.exists(origen_path):
        return False, "El archivo origen no existe."
    if not nombre_local:
        return False, "Falta el nombre destino."
    destino = os.path.join(CARPETA_ACTUAL, nombre_local)
    try:
        if os.path.exists(destino):
            try:
                shutil.copy2(destino, destino + ".bak")
            except Exception:
                pass
        shutil.copy2(origen_path, destino)
        return True, f"Importado: {nombre_local}"
    except Exception as e:
        logging.error(f"Error importando {origen_path} -> {nombre_local}: {e}")
        return False, f"Error: {e}"


def exportar_archivo_local(nombre_local, destino_path):
    """Copia un archivo del proyecto a una ruta externa elegida por el usuario."""
    origen = os.path.join(CARPETA_ACTUAL, nombre_local)
    if not os.path.exists(origen):
        return False, f"No existe {nombre_local} en el proyecto."
    try:
        shutil.copy2(origen, destino_path)
        return True, f"Exportado a {destino_path}"
    except Exception as e:
        logging.error(f"Error exportando {nombre_local} -> {destino_path}: {e}")
        return False, f"Error: {e}"


def exportar_backup_completo(destino_zip):
    """Crea un ZIP con TODA la configuración y estado de Pulsemail:
      - config.json (incluye firma de texto + path a firma de imagen)
      - contactos.csv
      - registro_envios.json (estado del día actual)
      - registro_rechazados.json
      - registro_depurados.json
      - registro_respuestas.json
      - registro_vistos.json
      - historial/ (carpeta entera, todos los días de campaña)
      - firma/<imagen> si la firma_imagen apunta a un archivo válido

    El ZIP resultante se puede usar con `importar_backup_completo()` en otra
    PC para clonar la instalación.
    """
    if not destino_zip:
        return False, "Falta path destino."
    try:
        with zipfile.ZipFile(destino_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Archivos sueltos en raíz
            for nombre in _ARCHIVOS_BACKUP:
                ruta = os.path.join(CARPETA_ACTUAL, nombre)
                if os.path.exists(ruta):
                    zf.write(ruta, nombre)

            # 2. Carpeta historial completa (todos los días/meses/años)
            if os.path.isdir(CARPETA_HISTORIAL):
                for root, _dirs, files in os.walk(CARPETA_HISTORIAL):
                    for f in files:
                        abs_path = os.path.join(root, f)
                        rel_path = os.path.relpath(abs_path, CARPETA_ACTUAL)
                        try:
                            zf.write(abs_path, rel_path.replace("\\", "/"))
                        except Exception:
                            continue

            # 3. Firma de imagen (si está configurada y existe)
            try:
                cfg = cargar_config()
                firma_img = (cfg.get("firma_imagen") or "").strip()
                if firma_img and os.path.exists(firma_img):
                    arcname = "firma/" + os.path.basename(firma_img)
                    zf.write(firma_img, arcname)
            except Exception:
                pass

            # 4. Metadata del backup (para validar al importar)
            meta = {
                "app":          "Pulsemail",
                "version":      "1.0",
                "timestamp":    datetime.now().isoformat(),
                "incluye":      _ARCHIVOS_BACKUP + ["historial/", "firma/"],
            }
            zf.writestr("pulsemail_backup.json",
                        json.dumps(meta, indent=2, ensure_ascii=False))

        return True, f"Backup creado: {destino_zip}"
    except Exception as e:
        logging.error(f"Error creando backup: {e}")
        return False, f"Error creando backup: {e}"


def importar_backup_completo(origen_zip):
    """Restaura un ZIP creado por `exportar_backup_completo()` encima de la
    carpeta actual. Sobrescribe los archivos existentes (hace .bak antes).
    Tras restaurar, verifica que los paths referenciados en config (firma
    de imagen) existan; si no, los limpia para que la app no se bugee.
    Devuelve (ok, mensaje)."""
    if not origen_zip or not os.path.exists(origen_zip):
        return False, "El backup no existe."
    if not zipfile.is_zipfile(origen_zip):
        return False, "El archivo no es un ZIP válido."

    try:
        with zipfile.ZipFile(origen_zip, "r") as zf:
            # Hacer backup de los archivos críticos antes de pisar
            for nombre in _ARCHIVOS_BACKUP:
                ruta_local = os.path.join(CARPETA_ACTUAL, nombre)
                if os.path.exists(ruta_local):
                    try:
                        shutil.copy2(ruta_local, ruta_local + ".bak")
                    except Exception:
                        pass

            # Extraer todo en la carpeta del proyecto
            zf.extractall(CARPETA_ACTUAL)

            # Si vino una firma de imagen, actualizar el path en config
            firma_dir = os.path.join(CARPETA_ACTUAL, "firma")
            if os.path.isdir(firma_dir):
                imgs = [
                    os.path.join(firma_dir, f) for f in os.listdir(firma_dir)
                    if os.path.isfile(os.path.join(firma_dir, f))
                ]
                if imgs:
                    try:
                        cfg = cargar_config()
                        cfg["firma_imagen"] = imgs[0]
                        if not cfg.get("firma_tipo"):
                            cfg["firma_tipo"] = "imagen"
                        guardar_config(cfg)
                    except Exception:
                        pass

        # ── Sanitización post-import ──
        # Si el config menciona archivos que no se restauraron (ej: una
        # firma_imagen con path antiguo), los limpiamos para que la app
        # no falle al renderizar el preview ni al enviar correos.
        try:
            cfg = cargar_config()
            firma_img = (cfg.get("firma_imagen") or "").strip()
            if firma_img and not os.path.exists(firma_img):
                cfg["firma_imagen"] = ""
                if cfg.get("firma_tipo") == "imagen":
                    cfg["firma_tipo"] = "texto"
                guardar_config(cfg)
        except Exception:
            pass

        return True, f"Backup restaurado desde {origen_zip}"
    except Exception as e:
        logging.error(f"Error restaurando backup: {e}")
        return False, f"Error restaurando: {e}"


def _detectar_buzon_papelera(mail):
    """Devuelve el nombre del buzón Trash/Papelera de la cuenta IMAP.
    Útil para Gmail (que usa [Gmail]/Trash en EN o [Gmail]/Papelera en ES)
    y para otras cuentas. Si no encuentra, devuelve `[Gmail]/Trash` como
    fallback."""
    candidatos = []
    try:
        estado, lineas = mail.list()
        if estado == "OK" and lineas:
            for raw in lineas:
                try:
                    txt = raw.decode("utf-8", errors="ignore") if isinstance(
                        raw, (bytes, bytearray)) else str(raw)
                except Exception:
                    continue
                txt_low = txt.lower()
                # Marcado con \Trash flag (estándar SPECIAL-USE)
                if "\\trash" in txt_low:
                    # El buzón es el último elemento entre comillas
                    m = re.search(r'"([^"]+)"\s*$', txt)
                    if m:
                        candidatos.insert(0, m.group(1))
                        continue
                # Heurística por nombre
                for kw in ('"[Gmail]/Trash"', '"[Gmail]/Papelera"',
                           '"[Gmail]/Bin"', '"Trash"', '"Papelera"',
                           '"Deleted Items"'):
                    if kw.lower() in txt_low:
                        m = re.search(r'"([^"]+)"\s*$', txt)
                        if m:
                            candidatos.append(m.group(1))
    except Exception:
        pass

    if candidatos:
        # Devolver el primer match con prefijo Gmail si existe
        for c in candidatos:
            if "trash" in c.lower() or "papelera" in c.lower() or "bin" in c.lower():
                return f'"{c}"'
        return f'"{candidatos[0]}"'
    return '"[Gmail]/Trash"'


if __name__ == "__main__":
    main()
