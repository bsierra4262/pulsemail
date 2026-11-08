"""Servidor SMTP de prueba que corre en 127.0.0.1 y no reenvía nada.

Acepta la conversación SMTP completa (EHLO, AUTH, MAIL, RCPT, DATA, QUIT) y
guarda en memoria cada mensaje recibido para que las pruebas lo inspeccionen.
Nunca abre conexiones hacia afuera: sólo escucha en la interfaz local.

Opciones pensadas para ejercitar los caminos de error del motor de envío:

- ``rechazar``: direcciones a las que responde ``550`` en ``RCPT TO``.
- ``password_valida``: si se indica, cualquier otra contraseña recibe ``535``.
- ``certificado``: ruta a un par certificado/clave PEM para ofrecer STARTTLS.
  Sin certificado el servidor no anuncia STARTTLS (las pruebas lo omiten).
"""

import base64
import socket
import ssl
import threading
from email import message_from_bytes, policy


class ServidorSMTPFalso:
    def __init__(self, host="127.0.0.1", puerto=0, rechazar=(),
                 password_valida=None, certificado=None, clave=None):
        self.host = host
        self._puerto_pedido = puerto
        self.rechazar = {r.lower() for r in rechazar}
        self.password_valida = password_valida
        self.recibidos = []          # [{"de", "para", "mensaje"}]
        self.logins = []             # [(usuario, password)]
        self._tls = None
        if certificado:
            ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ctx.load_cert_chain(certificado, clave)
            self._tls = ctx
        self._sock = None
        self._hilo = None
        self._activo = False

    # ── ciclo de vida ────────────────────────────────────────────
    @property
    def puerto(self):
        return self._sock.getsockname()[1]

    def iniciar(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self._puerto_pedido))
        self._sock.listen(8)
        self._sock.settimeout(0.2)
        self._activo = True
        self._hilo = threading.Thread(target=self._aceptar, daemon=True)
        self._hilo.start()
        return self

    def detener(self):
        self._activo = False
        if self._hilo:
            self._hilo.join(timeout=2)
        if self._sock:
            self._sock.close()

    def __enter__(self):
        return self.iniciar()

    def __exit__(self, *exc):
        self.detener()

    # ── conversación SMTP ────────────────────────────────────────
    def _aceptar(self):
        while self._activo:
            try:
                conn, _ = self._sock.accept()
            except (socket.timeout, OSError):
                continue
            threading.Thread(target=self._atender, args=(conn,),
                             daemon=True).start()

    def _atender(self, conn):
        conn.settimeout(10)
        archivo = conn.makefile("rb")

        def decir(linea):
            conn.sendall((linea + "\r\n").encode("ascii"))

        def leer():
            datos = archivo.readline()
            if not datos:
                raise ConnectionError
            return datos.decode("utf-8", "replace").rstrip("\r\n")

        de, para = "", []
        try:
            decir("220 smtp-falso listo")
            while True:
                linea = leer()
                cmd = linea[:4].upper()
                if cmd in ("EHLO", "HELO"):
                    extras = ["AUTH PLAIN LOGIN", "8BITMIME", "SMTPUTF8"]
                    if self._tls is not None:
                        extras.insert(0, "STARTTLS")
                    conn.sendall(b"250-smtp-falso\r\n")
                    for i, ext in enumerate(extras):
                        sep = " " if i == len(extras) - 1 else "-"
                        conn.sendall(f"250{sep}{ext}\r\n".encode("ascii"))
                elif linea.upper() == "STARTTLS" and self._tls is not None:
                    decir("220 listo para TLS")
                    conn = self._tls.wrap_socket(conn, server_side=True)
                    archivo = conn.makefile("rb")
                elif cmd == "AUTH":
                    usuario, password = self._autenticar(linea, decir, leer)
                    self.logins.append((usuario, password))
                    if (self.password_valida is not None
                            and password != self.password_valida):
                        decir("535 5.7.8 credenciales invalidas")
                    else:
                        decir("235 2.7.0 autenticado")
                elif cmd == "MAIL":
                    de, para = linea.split(":", 1)[1].strip().strip("<>").split(">")[0], []
                    decir("250 ok")
                elif cmd == "RCPT":
                    destino = linea.split(":", 1)[1].strip().strip("<>").split(">")[0]
                    if destino.lower() in self.rechazar:
                        decir("550 5.1.1 la casilla no existe")
                    else:
                        para.append(destino)
                        decir("250 ok")
                elif cmd == "DATA":
                    decir("354 terminar con <CRLF>.<CRLF>")
                    crudo = bytearray()
                    while True:
                        renglon = archivo.readline()
                        if renglon in (b".\r\n", b".\n", b""):
                            break
                        if renglon.startswith(b".."):
                            renglon = renglon[1:]
                        crudo.extend(renglon)
                    self.recibidos.append({
                        "de": de,
                        "para": list(para),
                        "mensaje": message_from_bytes(bytes(crudo),
                                                      policy=policy.default),
                    })
                    decir("250 recibido")
                elif cmd == "QUIT":
                    decir("221 chau")
                    break
                else:
                    decir("250 ok")   # RSET, NOOP y el resto
        except (ConnectionError, OSError, ssl.SSLError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    @staticmethod
    def _autenticar(linea, decir, leer):
        partes = linea.split()
        mecanismo = partes[1].upper() if len(partes) > 1 else ""
        if mecanismo == "PLAIN":
            if len(partes) > 2:
                crudo = partes[2]
            else:
                decir("334 ")
                crudo = leer()
            _, usuario, password = base64.b64decode(crudo).decode().split("\0")
            return usuario, password
        # LOGIN
        if len(partes) > 2:
            usuario = base64.b64decode(partes[2]).decode()
        else:
            decir("334 VXNlcm5hbWU6")
            usuario = base64.b64decode(leer()).decode()
        decir("334 UGFzc3dvcmQ6")
        password = base64.b64decode(leer()).decode()
        return usuario, password
