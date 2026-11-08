# Guía de contribución

Convenciones del proyecto **Pulsemail**.

## Flujo de trabajo

1. Crear una rama desde `main`: `git checkout -b feat/mi-cambio`.
2. Realizar cambios atómicos y acompañados de pruebas.
3. Ejecutar la batería antes de abrir el Pull Request:
   `python -m unittest discover -s tests -v` (sin red ni dependencias externas).
4. Si el cambio llega a los usuarios, subir la versión con `bump_version.py` (ver abajo).
5. Abrir un Pull Request describiendo el qué y el porqué del cambio. La integración continua
   corre las pruebas en Windows y Ubuntu.

## Mensajes de commit — [Conventional Commits](https://www.conventionalcommits.org/es/)

```
<tipo>(ámbito opcional): <descripción en imperativo, minúscula, sin punto>
```

Tipos: `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`.

Ejemplos:

```
feat(campana): auto-envío programado a una hora fija
fix(rebotes): no reenviar a direcciones que ya rebotaron
docs(readme): agrega capturas de la configuración
test(envio): campaña completa contra el SMTP local de prueba
```

## Versionado

La versión vive en el archivo `VERSION` y la leen el instalador y el script de compilación.

```bash
python bump_version.py patch --notes "Corrige ..."   # 1.4.7 -> 1.4.8
python bump_version.py minor --notes "Agrega ..."    # 1.4.7 -> 1.5.0
python bump_version.py show
```

Con `--notes`, la entrada se agrega a `CHANGELOG.md` debajo de `[Unreleased]`.

## Reglas del proyecto

- **Cada defecto detectado incorpora una prueba de regresión** en `tests/` que falle con el
  bug y pase con el arreglo.
- **Ninguna prueba envía correo real.** El envío se prueba contra `tests/smtp_falso.py`, que
  escucha sólo en `127.0.0.1`, y los datos de ejemplo usan dominios `.example`.
- **Sin secretos ni datos reales en el repositorio.** Credenciales, contactos, registros e
  historial viven en la carpeta de datos del usuario y están excluidos por
  [`.gitignore`](.gitignore). Ver [SECURITY.md](SECURITY.md).
- **Toda funcionalidad se documenta en el mismo cambio**: README, `CHANGELOG.md` y los
  manuales de `md/` cuando corresponda.
- **Flet fijado en 0.84.0.** Varias API cambiaron en versiones posteriores; una actualización
  se hace en un cambio propio, revisando cada control (ver `md/DOCS_DESARROLLADORES.md`).

## Estilo

- Python 3.11+, indentación de 4 espacios, sólo biblioteca estándar en el motor de envío.
- Nombres de dominio en castellano (`preparar_correo`, `agregar_a_lista_negra`); los patrones
  genéricos, en inglés cuando corresponda.
- Comentarios que explican el **porqué** de una decisión, no el qué obvio del código.
- La interfaz nunca debe cerrarse por un error de un control: los callbacks de UI capturan sus
  excepciones y las registran en `sistema_errores.log`.
