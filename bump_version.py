"""
bump_version.py — Versionado automático de Pulsemail
=====================================================

Sube la versión del proyecto y deja todos los artefactos sincronizados.
La fuente única de verdad es el archivo `VERSION` (en la raíz). El
`build_installer.bat` y el `installer/pulsemail.iss` leen de ese archivo,
así que basta con cambiarlo en un solo lugar.

USO
---
    python bump_version.py patch              # 1.0.3 -> 1.0.4 (bug fix)
    python bump_version.py minor              # 1.0.3 -> 1.1.0 (feature)
    python bump_version.py major              # 1.0.3 -> 2.0.0 (breaking)
    python bump_version.py set 1.2.3          # fija una versión específica
    python bump_version.py show               # imprime la versión actual

Para registrar qué cambió en cada versión, agregá el flag --notes:

    python bump_version.py patch --notes "Optimizé reescan BAJA, agregué cap historial"

Eso agrega una entrada al CHANGELOG.md con la fecha de hoy.
"""
import sys
import os
import re
from datetime import datetime

RAIZ = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_VERSION   = os.path.join(RAIZ, "VERSION")
ARCHIVO_CHANGELOG = os.path.join(RAIZ, "CHANGELOG.md")


def leer_version() -> str:
    if not os.path.exists(ARCHIVO_VERSION):
        raise SystemExit(
            f"No se encontró {ARCHIVO_VERSION}. Creá uno con '1.0.0' o "
            f"corré `python bump_version.py set 1.0.0`."
        )
    with open(ARCHIVO_VERSION, "r", encoding="utf-8") as f:
        v = f.read().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", v):
        raise SystemExit(
            f"Versión inválida en VERSION: {v!r}. Esperado MAJOR.MINOR.PATCH"
        )
    return v


def escribir_version(v: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", v):
        raise SystemExit(f"Versión inválida: {v!r}. Esperado MAJOR.MINOR.PATCH")
    # Sin newline al final — más fácil para `set /p` del .bat.
    with open(ARCHIVO_VERSION, "w", encoding="utf-8", newline="") as f:
        f.write(v)


def bump(actual: str, tipo: str) -> str:
    major, minor, patch = map(int, actual.split("."))
    if tipo == "major":
        return f"{major + 1}.0.0"
    if tipo == "minor":
        return f"{major}.{minor + 1}.0"
    if tipo == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise SystemExit(f"Tipo de bump desconocido: {tipo}")


def agregar_changelog(version_nueva: str, tipo: str, notas: str) -> None:
    """Inserta una entrada nueva al principio del CHANGELOG.md.
    Si el archivo no existe, lo crea con un header."""
    fecha = datetime.now().strftime("%Y-%m-%d")
    seccion = (
        f"## [{version_nueva}] — {fecha}  _{tipo}_\n\n"
        f"{notas.strip() if notas else '_(sin notas)_'}\n\n"
    )

    if not os.path.exists(ARCHIVO_CHANGELOG):
        header = (
            "# Changelog — Pulsemail\n\n"
            "Formato basado en [Keep a Changelog](https://keepachangelog.com/) "
            "y [SemVer](https://semver.org/).\n\n"
        )
        contenido = header + seccion
    else:
        with open(ARCHIVO_CHANGELOG, "r", encoding="utf-8") as f:
            previo = f.read()
        # Insertamos la nueva sección justo después de la primera línea
        # blanca posterior al título (preserva el header de intro).
        partes = previo.split("\n\n", 2)
        if len(partes) >= 3:
            contenido = f"{partes[0]}\n\n{partes[1]}\n\n{seccion}{partes[2]}"
        else:
            contenido = previo.rstrip() + "\n\n" + seccion

    with open(ARCHIVO_CHANGELOG, "w", encoding="utf-8") as f:
        f.write(contenido)


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    comando = args[0]

    if comando == "show":
        print(leer_version())
        return

    if comando == "set":
        if len(args) < 2:
            raise SystemExit("Usar: bump_version.py set X.Y.Z")
        version_nueva = args[1]
        version_anterior = leer_version() if os.path.exists(ARCHIVO_VERSION) else "—"
        escribir_version(version_nueva)
        print(f"Versión: {version_anterior} -> {version_nueva}")
        return

    if comando not in ("patch", "minor", "major"):
        print(__doc__)
        raise SystemExit(f"Comando desconocido: {comando}")

    notas = ""
    if "--notes" in args:
        idx = args.index("--notes")
        notas = " ".join(args[idx + 1:]).strip()

    actual = leer_version()
    nueva = bump(actual, comando)
    escribir_version(nueva)

    if notas:
        agregar_changelog(nueva, comando, notas)
        print(f"Versión: {actual} -> {nueva}  ({comando})")
        print(f"  + entrada agregada a CHANGELOG.md")
    else:
        print(f"Versión: {actual} -> {nueva}  ({comando})")
        print(f"  (sin notas — usá --notes \"…\" para registrar en CHANGELOG)")


if __name__ == "__main__":
    main()
