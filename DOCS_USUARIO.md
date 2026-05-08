# Pulsemail — Manual de usuario

> Tu asistente para hacer campañas de correo masivo desde tu propio Gmail, sin pagar plataformas externas.

---

## Índice

1. [¿Qué hace Pulsemail?](#1-qué-hace-pulsemail)
2. [Lo que vas a poder hacer](#2-lo-que-vas-a-poder-hacer)
3. [¿Lo puedo correr en mi computadora?](#3-lo-puedo-correr-en-mi-computadora)
4. [Cómo instalarlo](#4-cómo-instalarlo)
5. [Primera vez: configuración inicial](#5-primera-vez-configuración-inicial)
6. [Cómo usarlo en el día a día](#6-cómo-usarlo-en-el-día-a-día)
7. [Cómo NO terminar en spam o que te bloqueen la cuenta](#7-cómo-no-terminar-en-spam-o-que-te-bloqueen-la-cuenta)
8. [¿Cuántos correos puedo mandar por día?](#8-cuántos-correos-puedo-mandar-por-día)
9. [Cuando algo no funciona](#9-cuando-algo-no-funciona)
10. [Diccionario de palabras raras](#10-diccionario-de-palabras-raras)

---

## 1. ¿Qué hace Pulsemail?

Pulsemail es un programa que te ayuda a mandar correos a muchos contactos a la vez **desde tu propia cuenta de Gmail**, automáticamente, sin que tengas que copiar y pegar cada mensaje.

Imaginá esto: tenés una lista de 200 clientes potenciales y querés mandarles a todos un correo presentando tu servicio. En vez de mandar uno por uno (lo que te llevaría toda la tarde), abrís Pulsemail, le das al botón **Iniciar campaña** y el programa los manda todos solo, con tu firma, tu logo, y un texto personalizado para cada persona ("Estimado Juan", "Estimada María", etc.).

Mientras tanto, el programa también:

- Te avisa si **alguien te respondió** (en tiempo real, con notificación en pantalla).
- Te dice **qué correos no llegaron** (porque la dirección estaba mal escrita o no existe).
- **Borra los rebotes** de tu bandeja para que no se te ensucie con basura.
- Lleva un **historial** de todo lo que mandaste cada día.

Lo bueno es que como sale desde tu Gmail y no desde una plataforma externa, los destinatarios lo ven como un correo personal tuyo, no como un correo "comercial" de Mailchimp o similares. Eso mejora muchísimo la posibilidad de que abran y respondan.

---

## 2. Lo que vas a poder hacer

### Mandar correos masivos

Cargás tu lista de contactos (un Excel/CSV) y el programa los manda uno por uno con una pausa de entre 25 y 45 segundos entre cada uno (para que no parezca un robot y Google no te bloquee). Cada correo lleva el nombre real del destinatario, tu firma, tu logo, y los botones que vos elegís (por ejemplo, "Agendá una reunión" que abre tu Calendly, o "WhatsApp" que abre un chat con vos).

### Pausar y retomar cuando quieras

Si en medio de una campaña te cansás, o se te corta internet, o se te apaga la luz: **el programa no pierde el progreso**. La próxima vez que lo abras, retoma exactamente desde donde se cortó, sin repetirle el correo a los que ya lo recibieron.

### Detectar respuestas automáticamente

Cuando un cliente responde a tu correo, Pulsemail te lo muestra en una bandeja especial llamada **Respuestas y reuniones**. Aparece un número arriba (un "globito" rojo) que te dice cuántas respuestas no leíste todavía. Hacés click y ves toda la conversación con esa persona, ordenada como un chat.

### Ver tus reuniones de Calendly

Si usás Calendly y un cliente te agenda una llamada, Pulsemail también te lo avisa en la misma bandeja. No tenés que ir al Calendly a chequear: te aparece directamente acá, con quién se anotó.

### Limpiar las direcciones malas

Algunos correos no llegan: la dirección no existe, está mal escrita, el buzón está lleno. Cuando eso pasa, el servidor del destinatario te manda un correo automático que dice "Mail Delivery Failure" o algo similar. A esos correos les decimos **rebotes**.

Pulsemail los detecta solo y los muestra en el panel **Rechazados**. Vos podés apretar **Depurar** y el programa los manda a la papelera (los rebotes y el correo original que vos mandaste). Así tu bandeja queda limpia y la próxima vez no le mandás a esa dirección que no existe.

### Estadísticas y historial

- **Estadísticas**: ves cuántos correos mandaste en total, cuántos rebotaron, qué porcentaje fue exitoso.
- **Historial**: ves día por día qué hiciste. Si hace un mes hiciste una campaña, podés volver y ver qué se mandó, a quién, y a qué hora.

### Personalización completa

Todo es ajustable desde el panel **Configuración**:

- Tu firma (texto plano o imagen tipo "tarjeta de presentación").
- Tu logo, que aparece en el sidebar de la app y en cada correo que mandás.
- Las direcciones que reciben copia (CC) de cada envío, si querés que tu jefe o tu equipo vean lo que sale.
- Los enlaces que abren los botones del correo (tu Calendly, tu WhatsApp).
- El tema (claro u oscuro, según preferencia).

### Avisos cuando algo importante pasa

El programa te muestra **notificaciones tipo Windows** (las que aparecen en la esquina inferior derecha) cuando:

- Llega una respuesta nueva.
- Se cae internet.
- Vuelve internet después de un corte.
- Se completa una campaña.
- Pasa algo que requiere tu atención.

---

## 3. ¿Lo puedo correr en mi computadora?

### Lo mínimo que necesitás

Para que Pulsemail funcione básicamente bien:

| | Mínimo |
| --- | --- |
| **Sistema** | Windows 10 o Windows 11 (no Mac, no Linux por ahora) |
| **Memoria RAM** | 4 GB |
| **Espacio libre** | 250 MB para instalar + 100 MB para tus datos |
| **Pantalla** | 1280 × 720 (cualquier pantalla de los últimos 10 años cumple) |
| **Internet** | Conexión razonablemente estable |
| **Cuenta de correo** | Gmail común (`@gmail.com`) o Google Workspace (cuenta empresarial con tu dominio) |
| **Google Chrome instalado** | Sí, es necesario (gratis, [se descarga acá](https://www.google.com/chrome/)) |

**¿Por qué necesito Chrome?** Cuando abrís el panel para ver una conversación con un cliente, Pulsemail usa Chrome por dentro para mostrar los correos exactamente como se ven en Gmail (con logos, colores, firmas elegantes). Sin Chrome, los ves en blanco y negro como texto plano. Microsoft Edge no sirve como reemplazo.

### Lo recomendable para que vuele

Si tu computadora es de los últimos 5 años, ya cumple esto sin problema:

| | Recomendado |
| --- | --- |
| **Sistema** | Windows 11 actualizado |
| **Memoria RAM** | 8 GB o más |
| **Espacio libre** | Disco SSD (no HDD viejo) |
| **Pantalla** | Full HD (1920 × 1080) |
| **Internet** | Cable o WiFi de 5 GHz, estable |
| **Cuenta** | Google Workspace con tu dominio (más profesional, mayor tope diario) |

### ¿Cómo sé si mi PC sirve?

Si tu computadora abre Gmail en el navegador, abre Word, abre Zoom todo a la vez sin colgarse — entonces va a correr Pulsemail sin problemas.

Si la computadora es muy viejita (de antes de 2015) o tiene 2 GB de RAM, puede andar pero lenta, sobre todo cuando abrís la conversación con un cliente.

---

## 4. Cómo instalarlo

### Opción fácil: con el instalador

1. Te pasaron un archivo llamado algo así como `PulsemailSetup_v1.0.0.exe`. Pesa más o menos 80 MB.
2. **Doble click** en ese archivo.
3. Se abre un asistente típico de instalación de Windows, todo en español. Le das **Siguiente** a todo.
4. Te pregunta dónde instalarlo: dejá lo que viene por defecto, no toques nada.
5. Te pregunta si querés un acceso directo en el escritorio: marcalo si querés (recomendado).
6. **Instalar**. Tarda 30 segundos.
7. Cuando termine, podés abrirlo desde el escritorio o desde el menú Inicio.

¿Te pidió permiso de administrador? Probablemente no, porque se instala en tu propia carpeta de usuario, pero si lo pide es normal — decile **Sí**.

### Cuando salga una versión nueva

Cuando te avisen que hay una versión nueva (por ejemplo `PulsemailSetup_v1.1.0.exe`):

1. **Antes de actualizar, hacé un respaldo**. En Pulsemail, andá a **Configuración → Datos → Exportar configuración completa** y guardá el ZIP en un lugar seguro (un pendrive, OneDrive, donde quieras). Esto guarda TODO: tus contactos, tu configuración, tu historial.
2. Doble click en el `.exe` nuevo.
3. El instalador detecta que ya tenés una versión vieja y te avisa que va a actualizar.
4. Le das **Sí** y listo. Tus datos quedan intactos. Solo se reemplaza el programa en sí.

### Para desinstalar

Como cualquier programa de Windows: **Panel de Control → Programas → Pulsemail → Desinstalar**. Tus datos (contactos, historial, configuración) NO se borran por si reinstalás más adelante.

---

## 5. Primera vez: configuración inicial

Esto lo hacés UNA vez. Después no lo tocás más.

### Paso 1: Activar verificación en 2 pasos en tu Google

Esto es un requisito de Google, no nuestro. Sin esto no podés conectar Pulsemail a tu Gmail.

1. Abrí cualquier navegador y andá a [myaccount.google.com](https://myaccount.google.com/).
2. Iniciá sesión con tu cuenta de Gmail.
3. En el menú izquierdo, click en **Seguridad**.
4. Buscá la sección "**Iniciar sesión en Google**" y entrá a "**Verificación en 2 pasos**".
5. Click en **Activar** y seguí los pasos. Te va a pedir tu número de celular para mandarte un código.

¿Por qué hay que hacer esto? Porque Google quiere asegurarse de que sos vos quien le da permiso a Pulsemail de mandar correos. Sin esto, Google no permite que apps externas accedan a tu Gmail.

### Paso 2: Generar una contraseña especial para Pulsemail

Acá viene lo importante: **NO vas a usar tu contraseña normal de Gmail**. Vas a generar una contraseña aparte, que sirve solamente para Pulsemail. Si algún día tenés que cambiarla o cancelarla, tu cuenta de Google sigue funcionando normal.

1. Andá a [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
   - Si esa página te dice "no disponible", es porque no activaste verificación en 2 pasos en el paso 1. Volvé y activala.
2. Te aparece un formulario que dice "Nombre de la app".
3. Escribí: **Pulsemail** (o lo que quieras, es solo para que te acuerdes).
4. Click en **Crear**.
5. Google te muestra una contraseña de **16 letras y números**, algo así: `xkjt mbwq lpzq vnaa`.

**¡IMPORTANTE!** Esa contraseña **solo se ve UNA vez**. Copiala ahora mismo a un lugar seguro (un Notepad, un papel, un gestor de contraseñas). Si la perdés, no es problema: volvés a este mismo paso y generás otra.

### Paso 3: Cargar tus datos en Pulsemail

Abrí Pulsemail y andá al panel **Configuración** (es el ícono de engranaje en el sidebar izquierdo). Ahí dentro:

#### Sub-pestaña "Cuenta"

| Campo | Qué poner |
| --- | --- |
| **Correo electrónico** | Tu email de Gmail (`tunombre@gmail.com`) |
| **Contraseña de aplicación** | Las 16 letras del paso 2 (los espacios no importan, podés ponerla con o sin espacios) |
| **Límite diario** | Ver [sección 8 de este manual](#8-cuántos-correos-puedo-mandar-por-día). Para Gmail común poné **250**. |
| **Correos en copia (CC)** | Opcional. Si querés que tu equipo reciba copia de cada envío, poné los emails separados por coma. Si no, dejalo vacío. |
| **URL del botón Calendly** | Tu link de Calendly (`https://calendly.com/tu-usuario/30min`). Si lo dejás vacío usa el default. |
| **URL del botón WhatsApp** | Tu link de WhatsApp con número y mensaje pre-cargado. Sirve [esta herramienta gratis](https://wa.me) para generarlo. |

Apretá **Guardar configuración**.

Si todo está bien, en el sidebar izquierdo de la app vas a ver un puntito verde con el texto "**GMAIL SMTP activo**". Eso significa que se conectó bien.

Si en cambio aparece rojo con "Credenciales inválidas":

- Revisá que el correo esté bien escrito.
- Revisá la contraseña de aplicación (probá copiándola de nuevo).
- Asegurate de que la verificación en 2 pasos esté activada.

#### Sub-pestaña "Firma"

Acá ponés la firma que va a aparecer cuando le respondés a un cliente desde Pulsemail.

Tenés dos opciones:

- **Texto**: escribís tu nombre, cargo, teléfono, email. Simple.
- **Imagen**: subís una imagen tipo tarjeta de presentación (con tu logo, foto, contacto). Pulsemail la rescala automáticamente para que no pese mucho.

Tip: si tenés una firma profesional armada en un editor (como Canva, o la que te diseñó tu agencia), exportala como PNG y subila como imagen.

#### Sub-pestaña "Apariencia"

- **Tema**: claro, oscuro, o que siga al tema de Windows automáticamente.
- **Logo del cliente**: subí TU logo de empresa. Va a aparecer en dos lugares:
  - En la esquina superior izquierda de la app (bonito, te identifica).
  - En **cada correo** que mandes (reemplaza al logo que viene por defecto).

Si no subís ninguno, se usa el logo que viene de fábrica.

### Paso 4: Cargar tus contactos

Pulsemail necesita una lista de contactos para mandarles correo. Esa lista va en un archivo llamado `contactos.csv`.

#### ¿Qué es un CSV?

Es un Excel simplificado. Si abrís un CSV con Excel o Google Sheets, lo ves como una planilla normal con filas y columnas. La diferencia es que se guarda como texto plano para que cualquier programa lo pueda leer.

#### Formato esperado

Tu CSV debe tener estas columnas (los nombres importan):

```csv
Nombre,Apellidos,Nombre de Cuenta,Correo electrónico,Correo electrónico secundario,Correo electrónico terciario
Juan,Pérez,ACME SA,juan@acme.com,juan.perez@acme.com,
María,García,Beta SRL,maria@beta.com,,
```

- **Nombre + Apellidos**: se concatenan para personalizar el saludo. Si Juan Pérez recibe el correo, ve "Estimado/a Juan Pérez".
- **Nombre de Cuenta**: nombre de la empresa (opcional).
- **Correo electrónico**: la dirección principal. Es la que se usa.
- **Correo electrónico secundario / terciario**: alternativos. Si la principal está vacía, usa el secundario, después el terciario.

#### Dónde poner el archivo

Pulsemail busca el `contactos.csv` en su carpeta de instalación. Por defecto:

```text
C:\Users\TuUsuario\AppData\Local\Pulsemail\contactos.csv
```

Pero la forma fácil de llegar ahí es:

1. Abrí la carpeta donde se instaló Pulsemail (botón derecho sobre el acceso directo del escritorio → "Abrir ubicación del archivo").
2. Pegá tu `contactos.csv` ahí.
3. Cerrá y volvé a abrir Pulsemail.

#### ¿De dónde saco la lista en formato CSV?

Pulsemail está pensado para listas exportadas de **HubSpot** (un CRM popular). Si exportás contactos desde HubSpot, ya viene con las columnas correctas.

Si tu lista está en Excel:

1. Abrí Excel.
2. Asegurate de que las columnas se llamen igual que en el formato de arriba.
3. **Archivo → Guardar como → CSV (delimitado por comas)**.
4. Renombralo a `contactos.csv` y copialo a la carpeta de Pulsemail.

---

## 6. Cómo usarlo en el día a día

### Empezar una campaña

1. Abrí Pulsemail.
2. En el panel **Dashboard** (la pantalla principal), ves un botón verde grande: **Iniciar campaña**.
3. Click.
4. El botón se pone **rojo y dice "Detener campaña"**. Eso significa que está mandando correos.
5. Abajo aparece un **historial de eventos en tiempo real**: "Enviado a `juan@acme.com`", "Enviado a `maria@beta.com`", etc.
6. Cada correo tarda entre 25 y 45 segundos en mandarse al siguiente. Eso es a propósito, para que Google no te trate como un robot.

Mientras la campaña corre, **podés cerrar la app o usar la PC para otra cosa**, no pasa nada. Pulsemail sigue trabajando en segundo plano.

### Detener una campaña antes de que termine

¿Te arrepentiste? ¿Te quedaste sin tiempo? ¿Detectaste un error en el correo?

1. Click en el botón rojo **Detener campaña**.
2. Cambia a "Deteniendo..." por un segundo.
3. Listo. Se detuvo.

**¿Y si después quiero retomar?** Volvés a apretar **Iniciar campaña** y el programa sigue desde el correo siguiente al último que mandó. **Nunca repite a alguien que ya recibió el correo.**

### Si se cae internet en medio de una campaña

Esto pasa muy seguido y Pulsemail está hecho para sobrevivir a esto:

1. Mientras estás mandando, se va el WiFi.
2. Aparece una **notificación en pantalla** (esquina inferior derecha): **"Sin conexión. Reintentando..."**
3. Pulsemail sigue intentando mandar el correo cada 10 segundos. No avanza al siguiente, se queda intentando ese.
4. Si tu conexión es inestable (microcortes), después de unos minutos aparece otra notificación: **"Conexión inestable. Si querés, detené la campaña y retomala más tarde."**
5. Cuando vuelve internet, aparece **"Conexión recuperada"** y la campaña continúa solita.

¿Cuánto tiempo aguanta sin internet? Hasta **3 horas** intentando. Si después de 3 horas no volvió la conexión, Pulsemail se da por vencido y detiene la campaña automáticamente, dejándote una notificación clara. Cuando recuperes internet, abrís la app, le das Iniciar campaña, y retoma desde el correo que quedó pendiente.

### Cuando llega una respuesta de un cliente

1. Aparece una **notificación en pantalla**: "Pulsemail — Nueva respuesta de `juan@acme.com`".
2. Andá al panel **Respuestas y reuniones** (en el sidebar izquierdo). Vas a ver un globito rojo con el número de respuestas sin leer.
3. Click en la respuesta de Juan.
4. Se abre el **panel Conversación** que muestra el historial completo de correos con esa persona, ordenado de más viejo a más nuevo, con todo el diseño original (logos, colores, firmas).
5. Abajo del todo hay un campo **"Tu respuesta"**.
6. Escribís lo que querés contestar.
7. Click en **Enviar respuesta**. Gmail lo agrupa automáticamente al hilo de conversación.

### Cuando un correo no llega a destino

A veces, una dirección de email está mal escrita o no existe. El servidor del destinatario te manda un correo automático avisando ("Mail Delivery Failure"). Pulsemail los detecta solo.

1. Andá al panel **Rechazados**.
2. Ves la lista de todos los correos que no llegaron.
3. Si querés limpiar tu bandeja: marcá los que querés depurar y click en **Depurar seleccionados**.
4. Pulsemail se conecta a Gmail y manda esos correos rebotados a la papelera. **Solo toca esos correos**, no toca otros correos legítimos que mandaste a esa misma persona en otras campañas.
5. Si te equivocaste, hay un botón **Restaurar** para deshacer la depuración.

### Hacer un respaldo de todo

Recomendado: una vez por mes, o antes de actualizar la app.

1. **Configuración → Datos → Exportar configuración completa**.
2. Elegí dónde guardar el archivo ZIP.
3. Listo. Ese ZIP tiene TODO: tu configuración, contactos, historial, rechazados, respuestas. Si tu PC se rompe o querés moverte a otra computadora, importás ese ZIP y todo vuelve como estaba.

---

## 7. Cómo NO terminar en spam o que te bloqueen la cuenta

Esta es **la sección más importante de todo el manual**. Leéla con atención. Si Google detecta que estás mandando spam, te puede **bloquear la cuenta entera** — no solo Gmail, sino también tu Drive, tus Docs, tu YouTube, todo. Y si el bloqueo es definitivo, perdés acceso para siempre.

### Reglas de oro

#### 1. Mandale solo a gente que tenga relación con vos

**NO compres listas de contactos en internet.** Suena tentador ("¡10.000 emails de empresarios por $20!") pero esas listas tienen lo que se llaman **trampas anti-spam**: direcciones plantadas que no tienen dueño real, solamente sirven para que los proveedores anti-spam te detecten. Mandar UN solo correo a una de esas trampas puede hacer que Google bloquee tu dominio entero para siempre.

¿A quién está bien mandarle?

- Clientes anteriores tuyos.
- Personas que llenaron un formulario en tu web.
- Asistentes a un evento al que vos fuiste.
- Contactos de LinkedIn con los que tuviste alguna interacción.
- Empresas a las que ya cotizaste o que te pidieron información.

¿A quién NO?

- Listas compradas.
- Contactos sacados de páginas amarillas.
- Emails encontrados con "scrapers" en LinkedIn.
- Contactos que no tienen idea de quién sos.

#### 2. Empezá despacio si la cuenta es nueva

Si nunca antes mandaste campañas desde tu cuenta de Gmail, empezá de a poco para que Google se acostumbre. Tu cuenta tiene una **reputación** que Google va construyendo silenciosamente. Si pasás de 0 a 250 correos en un día, ven una alarma.

Cronograma sugerido para "calentar" la cuenta:

- **Semana 1**: 30 a 50 correos por día.
- **Semana 2**: 80 a 100 por día.
- **Semana 3**: 150 a 200 por día.
- **Semana 4 en adelante**: 250 (Gmail) o 1500 (Workspace).

Sí, es lento. Pero arruinar tu cuenta es peor que esperar 3 semanas.

#### 3. Limpiá los rebotes después de cada campaña

Después de mandar una campaña, andá al panel **Rechazados** y depurá. Si Google ve que mandás constantemente a direcciones que no existen, asume que no conocés a tu lista y baja tu reputación.

**Tasa de rebote saludable**: menos del 5%. Si de 250 correos te rebotan más de 12, hay un problema con la calidad de la lista.

#### 4. No le mandes el mismo correo a la misma persona muchas veces

Si Juan no te respondió, no le mandes 5 correos más insistiendo en una semana. Eso es comportamiento de spammer. Como mucho:

- 1 correo principal.
- 1 follow-up al cabo de 7-10 días.
- Dejalo ahí.

Si después de eso no respondió, asumilo y movete.

#### 5. El asunto del correo importa

Cosas que **funcionan**:

- "Reunión disponible esta semana"
- "Propuesta para [Nombre Empresa]"
- "Una idea sobre [tema relevante]"
- "Pregunta rápida sobre [empresa]"

Cosas que te mandan a spam **inmediatamente**:

- "🔥 OFERTA IMPERDIBLE 🔥"
- "GRATIS!!! HACÉ CLICK YA"
- "GANASTE UN PREMIO"
- Asuntos en MAYÚSCULAS o con muchos signos !!!.
- Asuntos con palabras como "GRATIS", "URGENTE", "OFERTA", "CRYPTO".

#### 6. El cuerpo del correo también

El template que viene con Pulsemail está balanceado. No lo modifiques agregando:

- "GANÁ 50% DE DESCUENTO"
- Links cortos (bit.ly, tinyurl) — usá URLs completas.
- Más de 2 imágenes grandes.
- Texto puro en mayúsculas.

#### 7. No bajes el tiempo de espera entre correos

Pulsemail espera entre 25 y 45 segundos entre cada envío. **No toques este número** salvo que sepas exactamente qué estás haciendo. Si lo bajás a 5 segundos, parece un robot, y en menos de un día te bloquean.

### Cómo configurar bien tu dominio (si tenés Google Workspace)

Si pagás Google Workspace y mandás desde tu dominio (`tunombre@tuempresa.com`), tu técnico de TI tiene que configurar tres cosas en el DNS de tu dominio. **Sin esto, tus correos van a spam masivamente**, no importa cuán bueno sea el contenido.

Las tres siglas son **SPF, DKIM, DMARC**. No te preocupes por entenderlas: simplemente decile a tu técnico de TI:

> "Necesito que configures SPF, DKIM y DMARC para que mis correos no vayan a spam. Te paso la guía oficial de Google: [support.google.com/a/answer/33786](https://support.google.com/a/answer/33786)"

Es un trámite de 30 minutos para alguien que sepa. Si no tenés un técnico, contactá a tu proveedor de hosting y pedí lo mismo.

### Señales de alarma

Si notás alguna de estas cosas, **detené tus campañas inmediatamente** y revisá tu lista:

- Te llegan muchos rebotes (más del 10%).
- Vos mismo te marcaste como spam con tu propio correo de prueba.
- Tus clientes habituales empiezan a decirte "no me llega tu correo, fijate en spam".
- Recibís un email de Google que dice "Detectamos actividad inusual en tu cuenta".

Si te llega ese último, **pará todo durante 48 horas**. No mandes nada. Después retomá con la mitad del volumen normal durante una semana.

### Si te bloquearon temporalmente

Google a veces hace bloqueos preventivos de 24-48 horas. Pulsemail te lo va a mostrar como un error de envío repetido. Qué hacer:

1. Detené todas las campañas.
2. Esperá 48 horas sin mandar absolutamente nada.
3. Reanudá con un volumen muy bajo (30 correos por día durante una semana).
4. Si seguís ignorando las advertencias, Google **banea la cuenta de forma permanente**, y eso ya no se recupera.

---

## 8. ¿Cuántos correos puedo mandar por día?

Esto depende de qué tipo de cuenta tenés.

### Si usás Gmail común (gratuito, `@gmail.com`)

| | Cantidad |
| --- | --- |
| **Lo que Google te permite por día** | 500 destinatarios |
| **Lo recomendable poner en Pulsemail** | **250** |
| **Por qué no 500** | Google cuenta cada destinatario. Si pones 1 destinatario en TO y 1 en CC, son 2 envíos. Quedarse en 250 deja margen para correos manuales que mandes vos durante el día, las copias, y errores temporales. |

### Si usás Google Workspace (cuenta de pago con tu dominio)

| Plan | Permitido por día |
| --- | --- |
| **Business Starter** ($6/mes) | 2.000 destinatarios externos |
| **Business Standard** ($12/mes) | 2.000 |
| **Business Plus** ($18/mes) | 2.000 |
| **Enterprise** | 10.000 |

| | Cantidad |
| --- | --- |
| **Lo recomendable poner en Pulsemail** | **1.500** |
| **Por qué no 2.000** | Mismo principio: dejar margen para tus correos manuales, copias internas, y no apurar el límite. |

### Cómo cambiar el número

**Configuración → Cuenta → Límite diario de envíos** → poné el número que corresponde.

### ¿Qué pasa cuando llegás al límite?

Cuando Pulsemail llega a la cantidad que configuraste, **detiene la campaña automáticamente** y te avisa: "Llegamos al máximo por hoy". Al día siguiente, cuando volvés a apretar Iniciar campaña, el contador se resetea solo y continúa desde donde quedó.

### Ojo con el robo de cuotas

Si tu cuenta de Gmail también la usás para correos personales o de trabajo durante el día (cosa normal), esos también cuentan dentro del límite de Google. Por eso recomendamos no usar el 100% del tope: si Google te da 500, vos en Pulsemail pone 250-300. Los otros 200 quedan para tus correos personales del día.

---

## 9. Cuando algo no funciona

### "Credenciales inválidas" en el sidebar

- Revisá que tu correo esté escrito exactamente bien (sin espacios al principio o al final).
- Probá copiar y pegar otra vez la contraseña de aplicación. Acordate: 16 caracteres.
- Asegurate de que la verificación en 2 pasos siga activada en tu Google.
- Si nada funciona, generá una contraseña de aplicación nueva.

### Mis correos están yendo a spam

Volvé a leer la [sección 7](#7-cómo-no-terminar-en-spam-o-que-te-bloqueen-la-cuenta). Las causas más típicas:

- La cuenta es nueva y todavía no tiene reputación.
- No tenés SPF/DKIM/DMARC configurados (si usás dominio propio).
- El asunto o el cuerpo tiene palabras que disparan filtros.
- La lista de contactos no es de calidad.

### El panel "Conversación" se ve en blanco y negro como texto plano

Te falta Chrome. Instalalo de [google.com/chrome](https://www.google.com/chrome/), cerrá Pulsemail, volvé a abrirlo. Listo.

### El panel "Conversación" tarda mucho en cargar la primera vez

Es normal. Chrome tarda 2-3 segundos en arrancar la primera vez. La segunda vez ya carga al instante porque queda cacheado.

### No me aparecen las notificaciones en pantalla

- Andá a Configuración de Windows → Sistema → Notificaciones → activalas.
- Buscá Pulsemail en la lista de apps y dejala con permiso de mandar notificaciones.

### "Campaña detenida automáticamente"

Bien, eso significa que Pulsemail estuvo 3 horas intentando mandar un correo y nunca volvió tu internet. Funcionó como debía.

- Verificá tu conexión a internet (probá abrir Google en el navegador).
- Cuando vuelva, abrí Pulsemail y apretá **Iniciar campaña**. Retoma desde donde quedó.

### Veo direcciones repetidas en Rechazados

Cerrá y volvé a abrir la app. El sistema de "limpieza de duplicados" se aplica al cargar.

Si persiste, andá a la carpeta de instalación de Pulsemail y borrá el archivo `registro_rechazados.json`. Al iniciar la próxima campaña se regenera solo escaneando tus rebotes recientes.

### "No se pudo abrir el selector de archivos" cuando subo firma o logo

Falta una librería de Python. Si reinstalás Python (en caso de que estés usándolo en modo desarrollador), marcá la opción "tcl/tk and IDLE" en el instalador. Si usás Pulsemail compilado (el `.exe`), reinstalá la app.

### Cambié de PC, ¿cómo migro todo?

1. En la PC vieja: **Configuración → Datos → Exportar configuración completa**. Guardá el ZIP en un pendrive o subilo a OneDrive/Drive.
2. En la PC nueva: instalá Pulsemail.
3. Abrilo. Andá a **Configuración → Datos → Importar configuración completa**. Seleccioná el ZIP.
4. Reiniciá la app. Listo. Tenés todo igual: contactos, configuración, historial, rechazados, respuestas.

### Quiero empezar de cero

¿Querés tirar todo lo viejo y empezar limpio?

1. Cerrá Pulsemail.
2. Andá a la carpeta de instalación.
3. Borrá los archivos `registro_*.json` y `historial/` (NO borres `config.json` si no querés perder tus credenciales).
4. Abrí la app. Empieza limpia.

---

## 10. Diccionario de palabras raras

| Palabra | Qué significa en términos simples |
| --- | --- |
| **Bounce / Rebote** | Cuando un correo no llega y el servidor del destinatario te avisa "che, este email no existe". Pulsemail los detecta y los muestra en Rechazados. |
| **Mailer-daemon** | El "robot" del servidor de correo que te avisa cuando algo no llegó. Es solo un nombre técnico de quién manda el aviso de rebote. La mayoría de proveedores (Gmail, Yahoo) lo usan. |
| **Postmaster** | Lo mismo que mailer-daemon, pero el nombre que usan otros proveedores como Microsoft Outlook, Office 365 o servidores de empresa. Pulsemail los reconoce a los dos. |
| **Spam** | Correo no deseado, basura. Si tu correo va a "spam" significa que el destinatario probablemente no lo vio. |
| **SPF / DKIM / DMARC** | Tres configuraciones técnicas en tu dominio que le dicen a los servidores receptores "este correo viene legítimamente de mi empresa". Sin esto, vas a spam. Las configura tu técnico de TI. |
| **Cuota / Límite diario** | La cantidad máxima de correos que Google te deja mandar por día. Para Gmail común son 500 al día, para Workspace 2000-10000. |
| **Calentar la cuenta** | Mandar de a poco al principio para que Google te tenga confianza. Empezar con 30 correos al día e ir subiendo. |
| **Lista de contactos / CSV** | Tu base de datos de gente a la que le vas a mandar. Es un archivo tipo Excel pero más simple. |
| **CC (Carbon Copy / Copia)** | Cuando mandás un correo y querés que otra persona lo vea. Por ejemplo, le mandás a tu cliente y a tu jefe le ponés en CC. Tu cliente ve que tu jefe está copiado. |
| **BCC (Blind Carbon Copy / Copia oculta)** | Igual que CC pero el destinatario no ve a quién más le mandaste. (Pulsemail solo soporta CC, no BCC). |
| **Calendly** | Plataforma para que la gente agende reuniones con vos. Si la usás, Pulsemail detecta cuando alguien se anota a una reunión y te avisa. |
| **Workspace** | Versión paga de Gmail con tu propio dominio (`@tuempresa.com`). Más profesional, mayor cuota diaria, mejor reputación que Gmail común. |
| **Pendiente de reintento** | Cuando se cae internet en medio de un envío, Pulsemail guarda el correo que estaba intentando mandar para seguir más tarde sin perder el progreso. |
| **Papelera de Gmail** | Donde van los correos cuando los borrás. Pulsemail mueve los rebotes ahí cuando los depurás, así no se borran de forma definitiva (los podés recuperar). |

---

## ¿Necesitás ayuda?

- **Antes que nada, hacé un respaldo**: Configuración → Datos → Exportar configuración completa.
- **Para problemas técnicos**: contactá a la persona que te dio el programa o a tu equipo de soporte.
- **Documentación técnica para desarrolladores**: hay un archivo separado llamado `DOCS_DESARROLLADORES.md` en la carpeta del programa, pero es bastante denso — está pensado para programadores.

---

*Pulsemail — Tu asistente de correo masivo. Versión actualizada en mayo de 2026.*
