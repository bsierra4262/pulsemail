"""Persistencia local: configuración, contactos, lista negra, rechazados,
progreso diario, historial, Message-IDs y respaldo completo."""

import json
import os
import unittest
from datetime import datetime

from entorno import CasoConDatos, ec


class Configuracion(CasoConDatos):
    def test_sin_archivo_devuelve_valores_por_defecto(self):
        cfg = ec.cargar_config()
        self.assertEqual(cfg["smtp_host"], "smtp.gmail.com")
        self.assertEqual(cfg["password"], "")

    def test_mezcla_con_los_valores_por_defecto(self):
        with open(ec.ARCHIVO_CONFIG, "w", encoding="utf-8") as f:
            json.dump({"limite_diario": 120}, f)
        ec._cache_invalidate()
        cfg = ec.cargar_config()
        self.assertEqual(cfg["limite_diario"], 120)
        self.assertEqual(cfg["imap_host"], "imap.gmail.com")
        self.assertEqual(ec.LIMITE_DIARIO(), 120)

    def test_archivo_dañado_no_rompe(self):
        with open(ec.ARCHIVO_CONFIG, "w", encoding="utf-8") as f:
            f.write("{esto no es json")
        ec._cache_invalidate()
        self.assertEqual(ec.cargar_config()["smtp_port"], 587)

    def test_guardar_invalida_la_cache(self):
        self.configurar(limite_diario=50)
        self.assertEqual(ec.LIMITE_DIARIO(), 50)
        self.configurar(limite_diario=75)
        self.assertEqual(ec.LIMITE_DIARIO(), 75)


class Contactos(CasoConDatos):
    def test_lee_los_tres_correos_en_minusculas(self):
        self.cargar_contactos([
            ("Ana", "Gómez", "Andina", "Ana@Andina.example", "compras@andina.example"),
            ("Luis", "Paz", "Delta", "luis@delta.example"),
            ("Sin", "Correo", "Nada", ""),
        ])
        self.assertEqual(ec.emails_de_contactos(), {
            "ana@andina.example", "compras@andina.example", "luis@delta.example"})
        self.assertEqual(ec.contar_contactos(), 3)

    def test_sin_archivo(self):
        self.assertEqual(ec.emails_de_contactos(), set())
        self.assertEqual(ec.contar_contactos(), 0)


class ListaNegra(CasoConDatos):
    def test_agregar_normaliza_y_no_duplica(self):
        self.assertTrue(ec.agregar_a_lista_negra(" Ana@Andina.Example ", "Respondió BAJA"))
        self.assertTrue(ec.agregar_a_lista_negra("ana@andina.example", "Otra vez"))
        datos = ec.cargar_lista_negra()["emails"]
        self.assertEqual(len(datos), 1)
        self.assertEqual(datos[0]["motivo"], "Otra vez")
        self.assertEqual(ec.cargar_lista_negra_set(), {"ana@andina.example"})

    def test_rechaza_direcciones_invalidas(self):
        self.assertFalse(ec.agregar_a_lista_negra("sin-arroba"))
        self.assertFalse(ec.agregar_a_lista_negra(""))

    def test_lote_cuenta_solo_los_nuevos(self):
        ec.agregar_a_lista_negra("a@x.example")
        nuevos = ec.agregar_lote_lista_negra(
            ["a@x.example", "B@x.example", "b@x.example", "invalido", ""])
        self.assertEqual(nuevos, 1)
        self.assertEqual(ec.cargar_lista_negra_set(), {"a@x.example", "b@x.example"})

    def test_quitar(self):
        ec.agregar_a_lista_negra("a@x.example")
        self.assertTrue(ec.quitar_de_lista_negra("A@X.example"))
        self.assertFalse(ec.quitar_de_lista_negra("a@x.example"))
        self.assertEqual(ec.cargar_lista_negra_set(), set())


class Rechazados(CasoConDatos):
    def test_agregar_es_aditivo_e_idempotente(self):
        self.assertEqual(ec.agregar_a_rechazados(["a@x.example", "b@x.example"], "2026-11-02"), 2)
        self.assertEqual(ec.agregar_a_rechazados(["A@x.example", "c@x.example"], "2026-11-03"), 1)
        with open(ec.ARCHIVO_RECHAZOS, encoding="utf-8") as f:
            datos = json.load(f)
        self.assertEqual(datos["2026-11-02"]["total"], 2)
        self.assertEqual(datos["2026-11-03"]["correos"], ["c@x.example"])

    def test_incluye_rebotes_de_la_lista_negra_y_filtra_por_campana(self):
        self.cargar_contactos([("Ana", "G", "A", "a@x.example"), ("Bea", "L", "B", "b@x.example")])
        ec.agregar_a_rechazados(["a@x.example", "ajeno@otro.example"], "2026-11-02")
        ec.agregar_a_lista_negra("b@x.example", "Rebote: correo no entregable", auto=True)
        ec.agregar_a_lista_negra("c@x.example", "Respondió BAJA", auto=True)
        ec._cache_invalidate()
        filtrados = {r["email"] for r in ec.cargar_rechazados_todos()}
        self.assertEqual(filtrados, {"a@x.example", "b@x.example"})
        todos = {r["email"] for r in ec.cargar_rechazados_todos(filtrar_por_contactos=False)}
        self.assertEqual(todos, {"a@x.example", "b@x.example", "ajeno@otro.example"})

    def test_depurados(self):
        ec.marcar_depurado("A@x.example")
        self.assertEqual(ec.cargar_depurados(), {"a@x.example"})
        ec.desmarcar_depurado("a@x.example")
        self.assertEqual(ec.cargar_depurados(), set())


class ProgresoEHistorial(CasoConDatos):
    def test_estado_conserva_campana_completa(self):
        ec.marcar_campana_completa(True)
        ec.guardar_estado("a@x.example", 3, "2026-11-08")
        self.assertTrue(ec.campana_esta_completa())
        self.assertEqual(ec.cargar_estado()["enviados_hoy"], 3)

    def test_estado_de_hoy(self):
        ec.guardar_estado("a@x.example", 5, datetime.now().strftime("%Y-%m-%d"))
        self.assertEqual(ec.estado_de_hoy(), (5, "a@x.example"))
        ec.guardar_estado("a@x.example", 5, "2000-01-01")
        self.assertEqual(ec.estado_de_hoy(), (0, ""))

    def test_historial_por_dia_y_estadisticas(self):
        ec.guardar_evento_historial("2026-10-30", "success", "Enviado", enviados=200, rebotes=4)
        ec.guardar_evento_historial("2026-11-02", "success", "Enviado", enviados=150, rebotes=1)
        ec.guardar_evento_historial("2026-11-02", "warning", "Límite diario alcanzado")
        self.assertEqual(ec.listar_dias_historial(), ["2026-11-02", "2026-10-30"])
        dia = ec.cargar_historial_dia("2026-11-02")
        self.assertEqual(len(dia["eventos"]), 2)
        self.assertTrue(os.path.exists(os.path.join(ec.CARPETA_HISTORIAL, "2026", "11",
                                                    "2026-11-02.json")))
        est = ec.obtener_estadisticas_globales()
        self.assertEqual((est["total_enviados"], est["total_rechazados"]), (350, 5))
        self.assertEqual([d["fecha"] for d in est["serie"]], ["2026-10-30", "2026-11-02"])

    def test_pendiente(self):
        self.assertIsNone(ec.cargar_pendiente())
        ec.guardar_pendiente("a@x.example", "Ana", 12)
        p = ec.cargar_pendiente()
        self.assertEqual((p["destino"], p["nombre"], p["intentos"]), ("a@x.example", "Ana", 12))
        ec.borrar_pendiente()
        self.assertIsNone(ec.cargar_pendiente())


class MessageIds(CasoConDatos):
    def test_normaliza_y_no_duplica(self):
        ec.registrar_message_id_enviado("abc@nexo.example")
        ec.registrar_message_id_enviado("<abc@nexo.example>")
        ec.registrar_message_id_enviado("")
        self.assertEqual(ec.cargar_message_ids_enviados(), {"<abc@nexo.example>"})

    def test_rota_los_mas_viejos(self):
        original = ec._MAX_MSG_IDS_GUARDADOS
        ec._MAX_MSG_IDS_GUARDADOS = 3
        try:
            for i in range(5):
                ec.registrar_message_id_enviado(f"<{i}@nexo.example>")
        finally:
            ec._MAX_MSG_IDS_GUARDADOS = original
        self.assertEqual(ec.cargar_message_ids_enviados(),
                         {"<2@nexo.example>", "<3@nexo.example>", "<4@nexo.example>"})


class Respaldo(CasoConDatos):
    def test_exportar_e_importar_en_otra_carpeta(self):
        self.configurar(limite_diario=99)
        self.cargar_contactos([("Ana", "G", "A", "a@x.example")])
        ec.guardar_evento_historial("2026-11-02", "info", "Sesión iniciada", enviados=1)
        zip_ruta = os.path.join(self.dir, "respaldo.zip")
        ok, _ = ec.exportar_backup_completo(zip_ruta)
        self.assertTrue(ok)

        destino = os.path.join(self.dir, "otra-pc")
        os.makedirs(destino)
        ec.CARPETA_ACTUAL = destino
        ec.ARCHIVO_CONFIG = os.path.join(destino, "config.json")
        ec.CARPETA_HISTORIAL = os.path.join(destino, "historial")
        ec._cache_invalidate()
        ok, _ = ec.importar_backup_completo(zip_ruta)
        self.assertTrue(ok)
        self.assertEqual(ec.cargar_config()["limite_diario"], 99)
        self.assertTrue(os.path.exists(os.path.join(destino, "contactos.csv")))
        self.assertEqual(ec.listar_dias_historial(), ["2026-11-02"])

    def test_importar_rechaza_lo_que_no_es_zip(self):
        ruta = os.path.join(self.dir, "no-zip.zip")
        with open(ruta, "w") as f:
            f.write("hola")
        self.assertFalse(ec.importar_backup_completo(ruta)[0])
        self.assertFalse(ec.importar_backup_completo(os.path.join(self.dir, "nada.zip"))[0])


if __name__ == "__main__":
    unittest.main()
