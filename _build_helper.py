"""
_build_helper.py — Wrapper para invocar `flet pack` desde el .bat.

Por qué existe: en algunas instalaciones de Python (Windows Store, por
ejemplo) el ejecutable `flet.exe` no está en el PATH y `python -m flet`
no funciona porque flet 0.84 no expone `__main__`. Este script importa
la API interna de `flet_cli` y la invoca con sys.argv, lo cual SIEMPRE
funciona si la librería está instalada.

Se invoca desde `build_installer.bat` con la versión como único argumento.
"""
import os
import sys


def main():
    if len(sys.argv) < 2:
        print("ERROR: falta el argumento de versión.", file=sys.stderr)
        return 2

    version = sys.argv[1].strip()
    file_version = f"{version}.0"

    # Lista base de assets que SIEMPRE van al bundle si existen.
    raiz = os.path.dirname(os.path.abspath(__file__))
    add_data_candidatos = [
        "logo-app.png",
        "logo-app.ico",
        "ITH-logo.png",
        "enviar_correos.py",
        "Flyer.png",
        "Flyer.jpg",
        "firma.png",
        "firma.jpg",
    ]
    add_data_args = []
    for nombre in add_data_candidatos:
        if os.path.exists(os.path.join(raiz, nombre)):
            add_data_args.extend(["--add-data", f"{nombre};."])

    # ── Cliente de Flet OFFLINE (CRÍTICO para que sea 100% autónomo) ──
    # `flet pack` NO empaqueta el cliente desktop (la ventana). Al primer
    # arranque, `flet_desktop.ensure_client_cached()` intenta DESCARGARLO
    # de GitHub, y en PCs sin internet o sin certificados actualizados
    # falla con "SSL: CERTIFICATE_VERIFY_FAILED" y la app no abre.
    # Lo empaquetamos nosotros en `flet_desktop/app/flet-windows.zip`:
    # ensure_client_cached() busca ahí PRIMERO y, si está, extrae local sin
    # descargar nada. Lo bajamos una vez a `_flet_client/` (cacheado).
    try:
        import flet_desktop.version as _fdv
        _ver = _fdv.version
        _client_dir = os.path.join(raiz, "_flet_client")
        os.makedirs(_client_dir, exist_ok=True)
        _zip = os.path.join(_client_dir, "flet-windows.zip")
        if not os.path.exists(_zip) or os.path.getsize(_zip) < 1_000_000:
            _url = (f"https://github.com/flet-dev/flet/releases/download/"
                    f"v{_ver}/flet-windows.zip")
            print(f"Descargando cliente Flet v{_ver} para empaquetar offline...")
            import ssl as _ssl, urllib.request as _urlreq, shutil as _sh
            try:
                import certifi as _certifi
                _ctx = _ssl.create_default_context(cafile=_certifi.where())
            except Exception:
                _ctx = _ssl.create_default_context()
            with _urlreq.urlopen(_url, context=_ctx, timeout=300) as _r, \
                    open(_zip, "wb") as _f:
                _sh.copyfileobj(_r, _f)
        add_data_args.extend(["--add-data", f"{_zip};flet_desktop/app"])
        print(f"Cliente Flet empaquetado OFFLINE: {_zip} "
              f"({os.path.getsize(_zip) // (1024*1024)} MB)")
    except Exception as _e:
        print(f"ADVERTENCIA: no se pudo empaquetar el cliente Flet offline "
              f"(la app intentará descargarlo al primer uso): {_e}",
              file=sys.stderr)

    flet_argv = [
        "flet", "pack", "interfaz.py",
        "--name", "Pulsemail",
        "--product-name", "Pulsemail",
        "--product-version", version,
        "--file-version", file_version,
        "--company-name", "Pulsemail",
        "--copyright", "Pulsemail (c) 2026",
        "--icon", "logo-app.ico",
        *add_data_args,
        "--hidden-import", "plyer.platforms.win.notification",
        "--hidden-import", "plyer.platforms.win",
        "--hidden-import", "plyer.platforms",
        "--hidden-import", "plyer",
    ]

    print(f"Compilando Pulsemail v{version}...")
    print(f"Assets incluidos: "
          f"{[a for a in add_data_args if a != '--add-data']}")

    try:
        from flet_cli.cli import main as flet_main
    except ImportError:
        # flet < 0.85 a veces lo expone en otro lado
        try:
            from flet.__pyinstaller.utils import main as flet_main  # type: ignore
        except ImportError:
            print(
                "ERROR: no se encontró el CLI de flet.\n"
                "Asegurate de tener flet instalado:\n"
                "    pip install flet==0.84.0 pyinstaller",
                file=sys.stderr,
            )
            return 1

    sys.argv = flet_argv
    try:
        ret = flet_main()
        return ret if isinstance(ret, int) else 0
    except SystemExit as e:
        return int(e.code) if e.code is not None else 0
    except Exception as e:
        print(f"ERROR durante flet pack: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
