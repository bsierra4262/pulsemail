"""Envío real por SMTP contra un servidor falso en 127.0.0.1.

Ningún correo sale de la máquina: el servidor de `smtp_falso` sólo escucha
en la interfaz local y guarda los mensajes en memoria. STARTTLS se omite
(el servidor de prueba no tiene certificado); el resto de la conversación
—autenticación, destinatarios, datos— es la misma que con Gmail.
"""

import smtplib
import unittest
from datetime import datetime
from unittest import mock

from entorno import CUENTA, PASSWORD, CasoConDatos, ec
from smtp_falso import ServidorSMTPFalso


class CasoSMTP(CasoConDatos):
    rechazar = ()

    def setUp(self):
        super().setUp()
        self.srv = ServidorSMTPFalso(rechazar=self.rechazar,
                                     password_valida=PASSWORD).iniciar()
        self.configurar(smtp_host="127.0.0.1", smtp_port=self.srv.puerto,
                        imap_host="127.0.0.1")
        sin_tls = mock.patch.object(smtplib.SMTP, "starttls", lambda self, *a, **k: (220, b""))
        sin_tls.start()
        self.addCleanup(sin_tls.stop)

    def tearDown(self):
        self.srv.detener()
        super().tearDown()

    def destinatarios(self):
        return [d for r in self.srv.recibidos for d in r["para"]]


class EnvioIndividual(CasoSMTP):
    rechazar = ("noexiste@andina.example",)

    def test_envia_y_registra_el_message_id(self):
        msg = ec.preparar_correo("Ana Gómez", "ana@andina.example")
        self.assertEqual(ec.enviar_correo(msg, "ana@andina.example"), "enviado")
        self.assertEqual(self.destinatarios(), ["ana@andina.example"])
        self.assertEqual(self.srv.logins, [(CUENTA, PASSWORD)])
        recibido = self.srv.recibidos[0]["mensaje"]
        self.assertIn("¡Hola Ana!", recibido.get_content())
        self.assertIn(recibido["Message-ID"], ec.cargar_message_ids_enviados())

    def test_destinatario_rechazado(self):
        msg = ec.preparar_correo("X", "noexiste@andina.example")
        self.assertEqual(ec.enviar_correo(msg, "noexiste@andina.example"), "rechazado")
        self.assertEqual(self.srv.recibidos, [])

    def test_credenciales_invalidas(self):
        self.configurar(smtp_host="127.0.0.1", smtp_port=self.srv.puerto, password="otra")
        msg = ec.preparar_correo("Ana", "ana@andina.example")
        self.assertEqual(ec.enviar_correo(msg, "ana@andina.example"), "auth")

    def test_detenido_antes_de_conectar_deja_pendiente(self):
        ec.detener_campana()
        msg = ec.preparar_correo("Ana", "ana@andina.example")
        self.assertEqual(ec.enviar_correo(msg, "ana@andina.example", nombre="Ana"), "detenido")
        self.assertEqual(ec.cargar_pendiente()["destino"], "ana@andina.example")
        self.assertEqual(self.srv.recibidos, [])


class CorreoDePrueba(CasoSMTP):
    def test_sale_igual_que_la_campana_pero_sin_cc(self):
        self.configurar(smtp_host="127.0.0.1", smtp_port=self.srv.puerto,
                        correos_copia="jefe@nexo.example")
        ok, texto = ec.enviar_correo_prueba("lucia.ferreyra@nexo.example")
        self.assertTrue(ok, texto)
        self.assertIn('"Lucia"', texto)
        self.assertEqual(self.destinatarios(), ["lucia.ferreyra@nexo.example"])
        self.assertIsNone(self.srv.recibidos[0]["mensaje"]["Cc"])

    def test_valida_antes_de_conectar(self):
        self.assertFalse(ec.enviar_correo_prueba("sin-arroba")[0])
        self.configurar(password="")
        self.assertFalse(ec.enviar_correo_prueba("a@nexo.example")[0])
        self.assertEqual(self.srv.recibidos, [])


class VerificacionDeCuenta(CasoSMTP):
    def test_ok(self):
        ok, _ = ec.verificar_smtp()
        self.assertTrue(ok)

    def test_credenciales_invalidas(self):
        self.assertEqual(ec.verificar_smtp(password="mala"), (False, "Credenciales inválidas"))

    def test_sin_credenciales(self):
        self.assertEqual(ec.verificar_smtp(correo="", password=""), (False, "Sin credenciales"))


class Campana(CasoSMTP):
    rechazar = ("noexiste@delta.example",)

    def setUp(self):
        super().setUp()
        pausa = mock.patch.multiple(ec, TIEMPO_MINIMO=0, TIEMPO_MAXIMO=0)
        sin_imap = mock.patch.object(ec, "revisar_rebotes", lambda *a, **k: None)
        # La campaña informa su avance por consola; en las pruebas se silencia.
        silencio = mock.patch.object(ec, "print", lambda *a, **k: None, create=True)
        for p in (pausa, sin_imap, silencio):
            p.start()
            self.addCleanup(p.stop)
        self.cargar_contactos([
            ("Ana", "Gómez", "Andina", "ana@andina.example"),
            ("Baja", "Pedida", "Beta", "baja@beta.example"),
            ("Ciro", "Paz", "Delta", "noexiste@delta.example"),
            ("", "", "Sin Nombre SA", "", "compras@sinnombre.example"),
            ("Eva", "Ríos", "Faro", "eva@faro.example"),
        ])
        ec.agregar_a_lista_negra("baja@beta.example", "Respondió BAJA", auto=True)
        self.hoy = datetime.now().strftime("%Y-%m-%d")

    def test_recorre_la_base_respetando_exclusiones(self):
        ec.main()
        self.assertEqual(self.destinatarios(),
                         ["ana@andina.example", "compras@sinnombre.example", "eva@faro.example"])
        self.assertEqual(ec.cargar_estado()["enviados_hoy"], 3)
        mensajes = [e["mensaje"] for e in ec.cargar_historial_dia(self.hoy)["eventos"]]
        self.assertTrue(any("Saltado (lista negra" in m and "baja@beta.example" in m
                            for m in mensajes))
        self.assertTrue(any("Error al enviar a: noexiste@delta.example" in m for m in mensajes))

    def test_usa_el_correo_secundario_si_falta_el_principal(self):
        ec.main()
        self.assertIn("compras@sinnombre.example", self.destinatarios())

    def test_respeta_el_limite_diario(self):
        self.configurar(smtp_host="127.0.0.1", smtp_port=self.srv.puerto, limite_diario=1)
        ec.main()
        self.assertEqual(self.destinatarios(), ["ana@andina.example"])

    def test_retoma_donde_quedo(self):
        ec.guardar_estado("ana@andina.example", 1, self.hoy)
        ec.main()
        self.assertEqual(self.destinatarios(),
                         ["compras@sinnombre.example", "eva@faro.example"])
        self.assertEqual(ec.cargar_estado()["enviados_hoy"], 3)

    def test_no_reenvia_a_rebotes_previos(self):
        ec.agregar_a_rechazados(["eva@faro.example"], "2026-11-01")
        ec.main()
        self.assertNotIn("eva@faro.example", self.destinatarios())

    def test_base_terminada_marca_campana_completa(self):
        ec.guardar_estado("eva@faro.example", 0, self.hoy)
        ec.main()
        self.assertEqual(self.srv.recibidos, [])
        self.assertTrue(ec.campana_esta_completa())


if __name__ == "__main__":
    unittest.main()
