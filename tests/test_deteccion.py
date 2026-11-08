"""Clasificación de lo que llega a la bandeja: bajas, respuestas automáticas,
rebotes y reuniones agendadas. Lógica pura, sin red."""

import unittest

from entorno import ec


class PedidoDeBaja(unittest.TestCase):
    def test_asunto_explicito(self):
        for asunto in ("BAJA", "Re: baja", "Unsubscribe", "opt-out por favor"):
            with self.subTest(asunto=asunto):
                self.assertTrue(ec.es_pedido_de_baja(asunto, "")[0])

    def test_respuesta_corta_con_baja(self):
        es, razon = ec.es_pedido_de_baja("Re: Retomando el contacto", "BAJA")
        self.assertTrue(es)
        self.assertIn("corta", razon)

    def test_frase_de_opt_out_en_mensaje_largo(self):
        cuerpo = ("Buenas tardes, gracias por escribir. " * 15
                  + "Les pido que no me envíen más correos de este tipo.")
        self.assertTrue(ec.es_pedido_de_baja("Re: hola", cuerpo)[0])

    def test_baja_como_tema_de_negocio_no_cuenta(self):
        cuerpo = ("Hola, estamos evaluando un sistema para gestionar altas y bajas "
                  "de personal en nuestra planta. " * 6
                  + "¿Podemos coordinar una llamada la semana próxima?")
        self.assertFalse(ec.es_pedido_de_baja("Re: Retomando el contacto", cuerpo)[0])

    def test_ignora_la_cita_del_correo_original(self):
        cuerpo = ("Me interesa, hablemos el jueves. " * 12
                  + "\n> Si no querés recibir más, darme de baja respondiendo BAJA")
        self.assertFalse(ec.es_pedido_de_baja("Re: Retomando el contacto", cuerpo)[0])

    def test_vacio(self):
        self.assertEqual(ec.es_pedido_de_baja(None, None), (False, ""))


class RespuestaAutomatica(unittest.TestCase):
    def test_detecta(self):
        for asunto in ("Respuesta automática: Fuera de la oficina", "Out of Office",
                       "Automatic reply: Re: hola", "CUENTA NO OPERATIVA",
                       "Ausencia Re: Retomando el contacto", "Estaré de vacaciones"):
            with self.subTest(asunto=asunto):
                self.assertTrue(ec.parece_auto_reply(asunto))

    def test_no_confunde_respuestas_reales(self):
        for asunto in ("Re: Retomando el contacto", "Consulta por presupuesto", "", None):
            with self.subTest(asunto=asunto):
                self.assertFalse(ec.parece_auto_reply(asunto))


class Rebotes(unittest.TestCase):
    def test_remitente_de_rebote(self):
        self.assertTrue(ec._es_remitente_rebote(
            "Mail Delivery Subsystem <mailer-daemon@googlemail.com>"))
        self.assertTrue(ec._es_remitente_rebote("postmaster@empresa.example"))
        self.assertFalse(ec._es_remitente_rebote("ana@empresa.example"))
        self.assertFalse(ec._es_remitente_rebote(None))

    def test_asunto_de_rebote(self):
        for asunto in ("Delivery Status Notification (Failure)", "Undeliverable: hola",
                       "Correo no entregado", "Mail delivery failed"):
            with self.subTest(asunto=asunto):
                self.assertTrue(ec._es_asunto_rebote(asunto))
        self.assertFalse(ec._es_asunto_rebote("Re: Retomando el contacto"))

    def test_extrae_la_direccion_que_reboto(self):
        cuerpo = ("From: mailer-daemon@googlemail.com\n"
                  "No se pudo entregar a ventas@nexo.example ni a "
                  "Final-Recipient: rfc822; Ana.Gomez@Andina.example")
        self.assertEqual(
            ec._extraer_email_rebotado(cuerpo, "ventas@nexo.example", set()),
            "ana.gomez@andina.example")

    def test_solo_cuenta_si_es_de_la_campana(self):
        cuerpo = "Falló: ajeno@otro.example y luego ana@andina.example"
        contactos = {"ana@andina.example"}
        self.assertEqual(
            ec._extraer_email_rebotado(cuerpo, "ventas@nexo.example", contactos),
            "ana@andina.example")
        self.assertEqual(
            ec._extraer_email_rebotado("Falló: ajeno@otro.example", "v@n.example", contactos),
            "")


class Cabeceras(unittest.TestCase):
    def test_extraer_email(self):
        self.assertEqual(ec._extraer_email("Ana Gómez <Ana.Gomez@Andina.example>"),
                         "ana.gomez@andina.example")
        self.assertEqual(ec._extraer_email("sin direccion"), "")
        self.assertEqual(ec._extraer_email(None), "")

    def test_decodificar_cabecera(self):
        self.assertEqual(ec._decodificar_cabecera("=?utf-8?b?UmV1bmnDs24gY29uZmlybWFkYQ==?="),
                         "Reunión confirmada")
        self.assertEqual(ec._decodificar_cabecera("texto plano"), "texto plano")
        self.assertEqual(ec._decodificar_cabecera(""), "")

    def test_plataforma_de_reunion(self):
        self.assertEqual(ec._identificar_plataforma_reunion("no-reply@calendly.com"), "calendly")
        self.assertEqual(ec._identificar_plataforma_reunion("notifications@cal.com"), "cal_com")
        self.assertIsNone(ec._identificar_plataforma_reunion("ana@andina.example"))
        self.assertIsNone(ec._identificar_plataforma_reunion(""))


if __name__ == "__main__":
    unittest.main()
