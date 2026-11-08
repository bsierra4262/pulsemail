# Política de seguridad

## Reporte de vulnerabilidades

Ante una vulnerabilidad de seguridad, **no debe abrirse un issue público**. El reporte se
realiza de forma privada a **bsierra@intellihelp.tech**.

Se solicita incluir, en la medida de lo posible: descripción, pasos de reproducción, impacto
y una posible mitigación. El reporte recibirá respuesta a la brevedad.

## Credenciales SMTP e IMAP

- **El código no contiene credenciales.** La cuenta y la contraseña empiezan vacías
  (`_CONFIG_DEFAULTS` en `enviar_correos.py`) y una prueba automatizada lo verifica en cada
  cambio.
- La cuenta se carga desde la aplicación, en **Configuración → Cuenta**, y se guarda en
  `config.json`, en la carpeta de datos del usuario: junto al ejecutable
  (`%LOCALAPPDATA%\Pulsemail\`, una carpeta por usuario de Windows y sin permisos de
  administrador) o junto a `interfaz.py` cuando se ejecuta desde el código fuente.
- `config.json` está excluido por `.gitignore`, igual que los `.env`, certificados y
  respaldos. El instalador **no lo incluye ni lo pisa** al actualizar.
- Se usa una **contraseña de aplicación** de Google, nunca la contraseña de la cuenta: exige
  verificación en dos pasos, sirve sólo para correo y se revoca desde la cuenta de Google sin
  tocar nada más.
- La conexión SMTP se cifra con **STARTTLS** antes de autenticar y la IMAP usa **SSL**.
- La contraseña se guarda en texto plano dentro de `config.json`, protegida por los permisos
  del perfil de Windows. El **respaldo completo** (Configuración → Datos) incluye ese archivo:
  el ZIP debe guardarse como cualquier otro documento con credenciales.

## Datos de los contactos

- La base de contactos, los registros de envío, la lista negra, las respuestas y el historial
  viven sólo en la carpeta de datos del usuario. **Ninguno se versiona** (`.gitignore`) y una
  prueba de CI falla si alguno entra al repositorio.
- La aplicación no envía datos a servicios de terceros: habla únicamente con el servidor SMTP e
  IMAP configurado.
- Las capturas del README usan una empresa y destinatarios **ficticios** (dominios
  `.example`, reservados) y un servidor SMTP de prueba local.

## Envío responsable

- Cada correo lleva la cabecera `List-Unsubscribe`; quien responde «BAJA» pasa a la lista
  negra y no vuelve a recibir mensajes.
- Las direcciones que rebotaron no se vuelven a intentar.
- Límite diario configurable y pausa aleatoria de 25 a 45 segundos entre correos.
