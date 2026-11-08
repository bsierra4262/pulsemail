"""Armado del correo de campaña: modo texto, modo HTML, firma y cabeceras."""

import unittest

from entorno import CUENTA, CasoConDatos, ec

# PNG de 1x1 píxel, suficiente para probar la firma de imagen.
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000100e221bc330000000049454e44ae426082"
)


def partes(msg):
    return {p.get_content_type(): p for p in msg.walk()}


class ModoTexto(CasoConDatos):
    def test_cabeceras_basicas(self):
        self.configurar(texto_asunto="Retomando el contacto")
        msg = ec.preparar_correo("Lucía Ferreyra", "lucia@andina.example")
        self.assertEqual(msg["Subject"], "Retomando el contacto")
        self.assertEqual(msg["From"], CUENTA)
        self.assertEqual(msg["To"], "lucia@andina.example")

    def test_asunto_sin_nombre_del_contacto(self):
        self.configurar(texto_asunto="Retomando el contacto")
        msg = ec.preparar_correo("Lucía Ferreyra", "lucia@andina.example")
        self.assertNotIn("Lucía", msg["Subject"])

    def test_cabecera_de_baja(self):
        self.configurar()
        msg = ec.preparar_correo("Lucía", "lucia@andina.example")
        self.assertEqual(msg["List-Unsubscribe"], f"<mailto:{CUENTA}?subject=BAJA>")

    def test_reemplaza_nombre_de_pila(self):
        self.configurar(texto_cuerpo="¡Hola @nombre!\nTe escribo por...")
        msg = ec.preparar_correo("Lucía Ferreyra", "lucia@andina.example")
        cuerpo = msg.get_content()
        self.assertIn("¡Hola Lucía!", cuerpo)
        self.assertNotIn("@nombre", cuerpo)
        self.assertNotIn("Ferreyra", cuerpo)

    def test_sin_nombre_no_deja_hueco_en_el_saludo(self):
        self.configurar(texto_cuerpo="¡Hola @nombre!\nTe escribo por...")
        for nombre in ("", "Cliente"):
            with self.subTest(nombre=nombre):
                cuerpo = ec.preparar_correo(nombre, "x@andina.example").get_content()
                self.assertIn("¡Hola!", cuerpo)
                self.assertNotIn("Cliente", cuerpo)

    def test_firma_de_texto_separada_del_mensaje(self):
        self.configurar(texto_cuerpo="Mensaje.\nSaludos,", firma="Laura Méndez")
        cuerpo = ec.preparar_correo("Ana", "ana@andina.example").get_content()
        self.assertTrue(cuerpo.rstrip().endswith("Saludos,\n\nLaura Méndez"))

    def test_firma_de_texto_no_se_duplica(self):
        self.configurar(texto_cuerpo="Mensaje.\nLaura Méndez", firma="Laura Méndez")
        cuerpo = ec.preparar_correo("Ana", "ana@andina.example").get_content()
        self.assertEqual(cuerpo.count("Laura Méndez"), 1)

    def test_texto_puro_sin_partes_html(self):
        self.configurar(firma_tipo="texto")
        msg = ec.preparar_correo("Ana", "ana@andina.example")
        self.assertFalse(msg.is_multipart())
        self.assertEqual(msg.get_content_type(), "text/plain")

    def test_firma_de_imagen_se_incrusta_en_html(self):
        ruta = self.ruta("firma.png")
        with open(ruta, "wb") as f:
            f.write(PNG_1X1)
        self.configurar(firma_tipo="imagen", firma_imagen=ruta)
        msg = ec.preparar_correo("Ana", "ana@andina.example")
        p = partes(msg)
        self.assertIn("text/plain", p)
        self.assertIn("text/html", p)
        self.assertIn("cid:firma_usuario", p["text/html"].get_content())
        self.assertEqual(p["image/png"]["Content-ID"], "<firma_usuario>")

    def test_firma_jpg_se_declara_como_jpeg(self):
        ruta = self.ruta("firma.jpg")
        with open(ruta, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0contenido")
        self.configurar(firma_tipo="imagen", firma_imagen=ruta)
        self.assertIn("image/jpeg", partes(ec.preparar_correo("Ana", "a@b.example")))

    def test_firma_de_imagen_inexistente_cae_a_texto_puro(self):
        self.configurar(firma_tipo="imagen", firma_imagen=self.ruta("no-existe.png"))
        msg = ec.preparar_correo("Ana", "ana@andina.example")
        self.assertFalse(msg.is_multipart())

    def test_copia_cc(self):
        self.configurar(correos_copia="jefe@nexo.example; archivo@nexo.example")
        msg = ec.preparar_correo("Ana", "ana@andina.example")
        self.assertEqual(msg["Cc"], "jefe@nexo.example, archivo@nexo.example")

    def test_sin_cc_no_hay_cabecera(self):
        self.configurar(correos_copia="")
        self.assertIsNone(ec.preparar_correo("Ana", "a@b.example")["Cc"])


class ModoHTML(CasoConDatos):
    def test_asunto_con_nombre_y_dos_alternativas(self):
        self.configurar(modo_correo="html")
        msg = ec.preparar_correo("Lucía Ferreyra", "lucia@andina.example")
        self.assertEqual(msg["Subject"], f"{ec.ASUNTO} | Lucía Ferreyra")
        p = partes(msg)
        self.assertIn("text/plain", p)
        self.assertIn("text/html", p)

    def test_saludo_y_datos_de_empresa(self):
        self.configurar(modo_correo="html")
        html = partes(ec.preparar_correo("Lucía Ferreyra", "l@a.example"))["text/html"].get_content()
        self.assertIn("Lucía</strong>", html)
        self.assertIn("Nexo Consultores", html)
        self.assertIn("hola@nexo-consultores.example", html)

    def test_botones_solo_si_hay_url(self):
        self.configurar(modo_correo="html", url_whatsapp="", url_calendly="", url_cal_com="")
        html = partes(ec.preparar_correo("Ana", "a@b.example"))["text/html"].get_content()
        self.assertNotIn("Contáctanos por WhatsApp", html)
        self.assertNotIn("Agendar reunión", html)

        self.configurar(modo_correo="html", url_whatsapp="https://wa.example/1",
                        url_cal_com="https://cal.example/r", plataforma_reunion="cal_com")
        html = partes(ec.preparar_correo("Ana", "a@b.example"))["text/html"].get_content()
        self.assertIn("Contáctanos por WhatsApp", html)
        self.assertIn('href="https://cal.example/r"', html)

    def test_logo_incrustado_por_cid(self):
        self.configurar(modo_correo="html")
        html = partes(ec.preparar_correo("Ana", "a@b.example"))["text/html"].get_content()
        self.assertIn("cid:logo_empresa", html)


class UtilidadesDeConfiguracion(CasoConDatos):
    def test_url_de_reunion_segun_plataforma(self):
        self.configurar(plataforma_reunion="cal_com", url_cal_com="https://cal.example/a",
                        url_calendly="https://calendly.example/b")
        self.assertEqual(ec.URL_REUNION_CFG(), "https://cal.example/a")
        self.configurar(plataforma_reunion="calendly", url_cal_com="https://cal.example/a",
                        url_calendly="https://calendly.example/b")
        self.assertEqual(ec.URL_REUNION_CFG(), "https://calendly.example/b")

    def test_url_de_reunion_usa_la_otra_si_la_elegida_esta_vacia(self):
        self.configurar(plataforma_reunion="cal_com", url_cal_com="",
                        url_calendly="https://calendly.example/b")
        self.assertEqual(ec.URL_REUNION_CFG(), "https://calendly.example/b")

    def test_parsear_cc(self):
        self.assertEqual(ec._parsear_cc(""), [])
        self.assertEqual(ec._parsear_cc(None), [])
        self.assertEqual(ec._parsear_cc("a@x.example, b@y.example;c@z.example  d"),
                         ["a@x.example", "b@y.example", "c@z.example"])

    def test_nombre_desde_email(self):
        self.assertEqual(ec._nombre_desde_email("lucia.ferreyra@a.example"), "Lucia Ferreyra")
        self.assertEqual(ec._nombre_desde_email("mperez2024@a.example"), "Mperez")
        self.assertEqual(ec._nombre_desde_email(""), "")


if __name__ == "__main__":
    unittest.main()
