"""Entorno aislado para las pruebas.

`enviar_correos` guarda su estado en archivos junto al ejecutable (config,
contactos, registros, historial). Cada prueba redirige esas rutas a una
carpeta temporal propia, así nunca se lee ni se pisa la configuración real
de quien corre las pruebas, y nada queda en el repositorio.
"""

import csv
import os
import shutil
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import enviar_correos as ec  # noqa: E402

# Atributo del módulo -> nombre del archivo dentro de la carpeta de datos
ARCHIVOS = {
    "ARCHIVO_CONFIG": "config.json",
    "ARCHIVO_CSV": "contactos.csv",
    "LOG_PROGRESO": "registro_envios.json",
    "ARCHIVO_RECHAZOS": "registro_rechazados.json",
    "ARCHIVO_DEPURADOS": "registro_depurados.json",
    "ARCHIVO_RESPUESTAS": "registro_respuestas.json",
    "ARCHIVO_VISTOS": "registro_vistos.json",
    "ARCHIVO_IGNORADOS": "registro_ignorados.json",
    "ARCHIVO_PENDIENTE": "registro_pendiente.json",
    "ARCHIVO_LISTA_NEGRA": "lista_negra.json",
    "ARCHIVO_MSG_IDS": "registro_msg_ids.json",
    "CARPETA_HISTORIAL": "historial",
}

COLUMNAS_CSV = ["Nombre", "Apellidos", "Nombre de Cuenta", "Correo electrónico",
                "Correo electrónico secundario", "Correo electrónico terciario"]

# Datos de ejemplo: dominios .example (reservados, no existen).
CUENTA = "ventas@nexo-consultores.example"
PASSWORD = "clave-de-prueba"


class CasoConDatos(unittest.TestCase):
    """Caso base con la carpeta de datos de la aplicación aislada."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pulsemail-prueba-")
        self._originales = {"CARPETA_ACTUAL": ec.CARPETA_ACTUAL}
        ec.CARPETA_ACTUAL = self.dir
        for atributo, nombre in ARCHIVOS.items():
            self._originales[atributo] = getattr(ec, atributo)
            setattr(ec, atributo, os.path.join(self.dir, nombre))
        ec._CACHE.clear()
        ec._msg_ids_cache[0] = None
        ec.reset_stop_campana()

    def tearDown(self):
        for atributo, valor in self._originales.items():
            setattr(ec, atributo, valor)
        ec._CACHE.clear()
        ec._msg_ids_cache[0] = None
        ec.reset_stop_campana()
        shutil.rmtree(self.dir, ignore_errors=True)

    # ── utilidades ───────────────────────────────────────────────
    def configurar(self, **valores):
        cfg = dict(ec._CONFIG_DEFAULTS)
        cfg.update({
            "correo": CUENTA,
            "password": PASSWORD,
            "firma": "Laura Méndez\nGerente comercial\nNexo Consultores",
            "firma_tipo": "texto",
            "empresa_nombre": "Nexo Consultores",
            "empresa_web": "nexo-consultores.example",
            "empresa_telefono": "+54 11 0000-0000",
            "empresa_email": "hola@nexo-consultores.example",
            "empresa_whatsapp": "",
        })
        cfg.update(valores)
        ec.guardar_config(cfg)
        return cfg

    def cargar_contactos(self, filas):
        """filas: lista de tuplas (nombre, apellido, empresa, correo[, secundario])."""
        ruta = os.path.join(self.dir, "contactos.csv")
        with open(ruta, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(COLUMNAS_CSV)
            for fila in filas:
                fila = list(fila) + [""] * (len(COLUMNAS_CSV) - len(fila))
                w.writerow(fila)
        ec._cache_invalidate()
        return ruta

    def ruta(self, nombre):
        return os.path.join(self.dir, nombre)
