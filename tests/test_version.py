"""Versionado: archivo VERSION, instalador, changelog y bump_version.py."""

import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from entorno import RAIZ

import bump_version as bv


def leer(nombre):
    with open(os.path.join(RAIZ, nombre), encoding="utf-8") as f:
        return f.read()


class Proyecto(unittest.TestCase):
    def test_version_es_semver(self):
        self.assertRegex(leer("VERSION").strip(), r"^\d+\.\d+\.\d+$")

    def test_changelog_tiene_la_version_actual(self):
        version = leer("VERSION").strip()
        self.assertIn(f"## [{version}] - ", leer("CHANGELOG.md"))

    def test_changelog_ordenado_de_mas_nueva_a_mas_vieja(self):
        versiones = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", leer("CHANGELOG.md"), re.M)
        claves = [tuple(map(int, v.split("."))) for v in versiones]
        self.assertEqual(claves, sorted(claves, reverse=True))
        self.assertEqual(versiones[0], leer("VERSION").strip())

    def test_instalador_lee_la_version_del_archivo(self):
        iss = leer(os.path.join("installer", "pulsemail.iss"))
        self.assertIn('FileRead(FileOpen("..\\VERSION"))', iss)


class Bump(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pulsemail-version-")
        self.version = os.path.join(self.dir, "VERSION")
        self.changelog = os.path.join(self.dir, "CHANGELOG.md")
        parche = mock.patch.multiple(bv, ARCHIVO_VERSION=self.version,
                                     ARCHIVO_CHANGELOG=self.changelog)
        parche.start()
        self.addCleanup(parche.stop)
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_calculo(self):
        self.assertEqual(bv.bump("1.4.7", "patch"), "1.4.8")
        self.assertEqual(bv.bump("1.4.7", "minor"), "1.5.0")
        self.assertEqual(bv.bump("1.4.7", "major"), "2.0.0")
        with self.assertRaises(SystemExit):
            bv.bump("1.4.7", "otro")

    def test_escribir_y_leer(self):
        bv.escribir_version("2.3.4")
        self.assertEqual(bv.leer_version(), "2.3.4")
        with open(self.version, "rb") as f:
            self.assertEqual(f.read(), b"2.3.4")   # sin salto de línea, lo lee el .bat
        with self.assertRaises(SystemExit):
            bv.escribir_version("2.3")

    def test_entrada_nueva_debajo_de_unreleased(self):
        shutil.copy(os.path.join(RAIZ, "CHANGELOG.md"), self.changelog)
        bv.agregar_changelog("9.9.9", "patch", "Corrige algo")
        with open(self.changelog, encoding="utf-8") as f:
            texto = f.read()
        self.assertLess(texto.index("## [Unreleased]"), texto.index("## [9.9.9] - "))
        self.assertLess(texto.index("## [9.9.9] - "), texto.index("## [1.4.7] - "))
        self.assertIn("### Fixed\n\n- Corrige algo", texto)

    def test_crea_el_changelog_si_no_existe(self):
        bv.agregar_changelog("1.0.0", "minor", "")
        with open(self.changelog, encoding="utf-8") as f:
            texto = f.read()
        self.assertTrue(texto.startswith("# Changelog"))
        self.assertIn("## [1.0.0] - ", texto)
        self.assertIn("- Sin notas.", texto)


if __name__ == "__main__":
    unittest.main()
