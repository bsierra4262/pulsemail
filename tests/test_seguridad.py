"""Credenciales y datos privados: nada sensible en el código ni en el repo."""

import os
import re
import subprocess
import unittest

from entorno import RAIZ, ec


def archivos_versionados():
    try:
        salida = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True,
                                text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [l for l in salida.splitlines() if l]


class Credenciales(unittest.TestCase):
    def test_sin_cuenta_ni_contrasena_por_defecto(self):
        self.assertEqual(ec._CONFIG_DEFAULTS["correo"], "")
        self.assertEqual(ec._CONFIG_DEFAULTS["password"], "")

    def test_el_codigo_no_contiene_contrasenas_de_aplicacion(self):
        # Las contraseñas de aplicación de Google son 16 letras, a veces en 4
        # grupos. Se ignoran los marcadores de ejemplo («xxxx xxxx xxxx xxxx»).
        patron = re.compile(r"""["']((?:[a-z]{4} ){3}[a-z]{4}|[a-z]{16})["']""")
        for nombre in ("enviar_correos.py", "interfaz.py"):
            with open(os.path.join(RAIZ, nombre), encoding="utf-8") as f:
                hallados = [m for m in patron.findall(f.read())
                            if len(set(m.replace(" ", ""))) > 1]
            self.assertEqual(hallados, [], nombre)


class Repositorio(unittest.TestCase):
    PRIVADOS = ("config.json", "contactos.csv", "lista_negra.json", "registro_envios.json",
                "registro_respuestas.json", "registro_rechazados.json", "historial/", ".env")

    def test_gitignore_excluye_los_datos_del_usuario(self):
        with open(os.path.join(RAIZ, ".gitignore"), encoding="utf-8") as f:
            reglas = {l.strip() for l in f if l.strip() and not l.startswith("#")}
        for privado in self.PRIVADOS:
            with self.subTest(privado=privado):
                self.assertIn(privado, reglas)

    def test_no_hay_datos_del_usuario_versionados(self):
        versionados = archivos_versionados()
        if versionados is None:
            self.skipTest("git no disponible")
        prohibidos = re.compile(
            r"(^|/)(config\.json|contactos\.csv|lista_negra\.json|registro_[a-z_]+\.json|"
            r"\.env(\..*)?|.*\.(pem|key|p12))$|(^|/)historial/")
        self.assertEqual([a for a in versionados if prohibidos.search(a)], [])


if __name__ == "__main__":
    unittest.main()
