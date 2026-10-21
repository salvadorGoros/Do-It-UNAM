# DO IT UNAM

Editor multimedia con Python y Django, configuración en español y soporte para
SQLite en desarrollo o PostgreSQL en despliegue.
Cada usuario puede crear proyectos de animación, agregar cuadros de texto y
usar imágenes de las galerías de **Elementos** y **Fondos**.

## Ejecutar en Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

Si el entorno ya existe y las dependencias están instaladas, basta con el último
comando. No es necesario activar el entorno virtual.

Abrir http://127.0.0.1:8000/ y crear una cuenta o iniciar sesión para ver los
proyectos propios.
Para detener el servidor, vuelve a la misma ventana de PowerShell donde está
ejecutándose y presiona **Ctrl+C**.

## Configurar Gemini

El apartado **IA** funciona con una clave de Google AI Studio. El proyecto ya
incluye un archivo `.env` local, excluido por `.gitignore`. Abrirlo y completar:

```dotenv
GEMINI_API_KEY=pega_aqui_tu_clave
```

Después hay que reiniciar Django. La clave se utiliza solo en el servidor: no se
envía al navegador, no se guarda en proyectos y no debe escribirse en el código.
`GEMINI_TEXT_MODEL`, `GEMINI_IMAGE_MODEL` y `GEMINI_DAILY_TOKEN_LIMIT` pueden
ajustarse en el mismo archivo sin modificar Python. `.env.example` documenta
todos los valores disponibles.

La IA permite crear diapositivas editables con viñetas, notas y sugerencias
visuales; resumir o mejorar texto; crear viñetas o guiones; y generar imágenes o
diagramas guardados en la biblioteca privada. Cada solicitud registra solamente
el tipo de tarea, modelo, tokens y resultado, no el prompt ni la respuesta.

Desde el mismo panel se pueden convertir archivos PDF o PPTX de hasta 50 MB en
1 a 20 diapositivas editables. El PDF se analiza con la comprensión visual de
Gemini; en PPTX se extraen textos, tablas y notas sin enviar el archivo original.
El trabajo conserva progreso, cancelación y reintento, y solo su propietario puede
consultarlo. La copia temporal subida a Gemini para un PDF se elimina al terminar.

## PostgreSQL, Redis y el trabajador

El modo local usa SQLite y ejecuta la cola inmediatamente. Para separar las
conversiones del servidor web, configura en `.env`:

```dotenv
POSTGRES_DB=doit_unam
POSTGRES_USER=postgres
POSTGRES_PASSWORD=una_contrasena_segura
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
CELERY_TASK_ALWAYS_EAGER=0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
```

Con PostgreSQL y Redis encendidos, aplica las migraciones e inicia en terminales
separadas Django y el trabajador:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
.\.venv\Scripts\python.exe -m celery -A config worker -l INFO --pool=solo
```

En Windows se usa `--pool=solo`; en Linux se puede omitir. Si `POSTGRES_DB` queda
vacío, el proyecto continúa usando `db.sqlite3`.

## Compartir temporalmente por internet

Para que alguien desde otra red pueda abrir el sitio, instala
[cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
(por ejemplo, en Windows con `winget install --id Cloudflare.cloudflared`) y
ejecuta desde PowerShell:

```powershell
.\.venv\Scripts\python.exe run_public.py
```

El programa inicia Django en `127.0.0.1:8000`, crea un Cloudflare Quick Tunnel
y muestra el enlace HTTPS temporal para compartir. No requiere una cuenta de
Cloudflare; sí conexión a internet. La URL cambia al iniciar un túnel nuevo y
solo funciona mientras la ventana siga abierta. Presiona **Ctrl+C** para detener
el servidor y cerrar el acceso. Como el sitio será público, comparte el enlace
solo con quienes deban usarlo; las cuentas y los proyectos siguen protegidos
por el inicio de sesión existente.

## Crear el administrador

Una vez aplicadas las migraciones, ejecutar en una terminal interactiva:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Introducir usuario, correo y contraseña cuando se soliciten. La contraseña no se
muestra al escribir y no debe añadirse al código ni a este archivo.

Quienes usarán el editor pueden crear su propia cuenta desde **Regístrate aquí**
en la pantalla de inicio de sesión, o abrir `/cuentas/registro/`. Se exige correo
`@comunidad.unam.mx`; el número de cuenta es opcional y también sirve para iniciar
sesión. Django valida y guarda la contraseña de forma segura. Todas las altas,
incluidas las creadas por un administrador, reciben el rol **Alumno**. El panel
propio `/administracion/` permite crear cuentas, cambiarlas a **Docente** o
**Administrador**, buscar usuarios y configurar las cuotas de IA. `/admin/`
queda disponible únicamente como herramienta técnica de Django.

Las cuotas iniciales son 10,000 tokens diarios para Alumno, 50,000 para Docente y
200,000 para Administrador. Se editan en **Roles** dentro del panel administrativo
y se aplican inmediatamente. El historial de consumo se puede filtrar por rol,
operación, modelo, resultado y fecha.

Para no bloquear las cuentas creadas antes de esta migración, `.env` incluye
`ALLOW_LEGACY_USERNAME_LOGIN=1`. Primero agrega a cada cuenta anterior su perfil
institucional desde **Perfiles de usuario** y después cambia el valor a `0` para
restringir completamente el acceso. Los enlaces de recuperación de contraseña
se imprimen en la terminal durante el desarrollo; en producción debe configurarse
un backend SMTP de Django.

## Uso

1. Crear una cuenta en `/cuentas/registro/` o iniciar sesión en `/cuentas/entrar/`.
2. En **Mis proyectos**, escribir un nombre y pulsar **Crear proyecto**.
3. Pulsar **Agregar texto** o **Texto** en la barra lateral. Escribir directamente
   en el cuadro; pulsar Escape para terminar. Doble clic o **Editar** vuelve a abrirlo.
4. Arrastrar el cuadro para moverlo y la esquina azul para redimensionarlo.
   La barra superior cambia fuente, tamaño, color, negrita, cursiva, subrayado y
   alineación del cuadro seleccionado. **Eliminar** borra ese cuadro.
5. Los cambios se guardan automáticamente mientras editas. También puedes pulsar
   **Guardar** para guardar inmediatamente.
6. Volver a **Mis proyectos** o pulsar **Cerrar sesión**.

Los nombres admiten hasta 150 caracteres, pueden repetirse y no pueden estar
vacíos. Se eliminan los espacios exteriores. Los proyectos se ordenan por última
modificación y solo su propietario puede abrirlos o cambiarles el nombre en el editor.

Cada diapositiva admite hasta 100 objetos. Agrega hojas en la barra inferior,
selecciónalas para editarlas de forma independiente, duplica, cambia su orden,
elimina, copia y pega hojas. También puedes copiar y pegar objetos con Ctrl+C y
Ctrl+V. Cada hoja tiene una duración de 1 a 3600 segundos; **Presentar** cambia de
hoja automáticamente al terminar ese tiempo y también permite avanzar con las
flechas del teclado. Presiona Escape para salir.

En teléfonos y tabletas, las herramientas cambian a una barra horizontal y las
bibliotecas se abren como paneles superpuestos. La línea de tiempo aparece como
una hoja inferior compacta, los menús respetan las áreas seguras del dispositivo
y cada miniatura incluye un botón táctil para copiar, duplicar o eliminar. El lienzo
se ajusta automáticamente tanto en orientación vertical como horizontal.
Los cuadros de texto aceptan hasta 5000
caracteres, incluidos saltos de línea; los elementos gráficos se pueden mover,
redimensionar y animar igual que los cuadros.
En **Audio** puedes subir archivos MP3, WAV, OGG o M4A de hasta 25 MB, escuchar
una vista previa y asignar hasta tres pistas a cada diapositiva. Una pista
seleccionada puede aplicarse o retirarse de todas las diapositivas a la vez sin
reemplazar las demás; las hojas que ya tengan tres pistas se omiten y se notifican.
La línea de tiempo permite ajustar inicio, recorte, volumen, silencio, fundido de
entrada y salida, y muestra la forma de onda. La duración se amplía al agregar
audio o fotogramas que terminan después del final actual. Quitar una pista no la
borra de la biblioteca privada del usuario.
Enter edita el cuadro seleccionado, Escape termina la edición, las flechas lo
mueven (Shift mueve 10 píxeles) y Supr lo elimina cuando no estás escribiendo.
Ctrl+Z o la flecha curva izquierda deshacen la última edición; Ctrl+Y, Ctrl+Shift+Z
o la flecha curva derecha la rehacen. El historial incluye texto, formato,
movimientos, tamaño, elementos y cambios de diapositiva.
Los cuadros mantienen su posición sobre un lienzo de 800 × 450 que se escala para
ajustarse al espacio disponible. El texto que excede el cuadro queda recortado:
amplía el cuadro o reduce la fuente para verlo completo. Cada objeto tiene un ID
estable, texto plano, posición, dimensiones y formato. Abre **Animar** y elige un
preajuste de entrada, énfasis o salida. El botón **Línea de tiempo** abre un panel
desplegable y redimensionable a 30 fps con zoom, bucle, pistas agrupadas y
selección múltiple de fotogramas. Desde su inspector se animan posición, tamaño,
rotación, opacidad, color, tipografía y contenido con transiciones lineales,
suaves, rebote, instantáneas o Bézier. Para texto existen cambio instantáneo,
escritura progresiva y transición. Las rutas de movimiento son visibles y
editables sobre el lienzo. Las animaciones pueden guardarse como plantillas
privadas reutilizables entre proyectos.

**+ Clic** agrega una pausa vinculada al objeto seleccionado: en Presentar se
detienen animación y audio hasta pulsar ese objeto. Las exportaciones no esperan
estas pausas. MP4 incluye las pistas mezcladas y GIF se genera sin audio, ambos
en 1080p o 720p. PDF y PNG siguen siendo estáticos; PowerPoint conserva texto e
imágenes como objetos editables.
Las imágenes se descargan juntas como un ZIP de PNG.
Se necesita JavaScript para editar. Se avisa al salir mientras hay cambios sin guardar.

## Archivos principales

- `config/settings.py`: configuración de Django, SQLite/PostgreSQL y Celery/Redis.
- `config/celery.py`: aplicación de tareas asíncronas.
- `config/urls.py`: rutas del proyecto.
- `editor/urls.py` y `editor/views.py`: ruta y vista del editor.
- `editor/templates/editor/index.html`: plantilla activa; editar aquí la interfaz.
- `editor/models.py`, `editor/forms.py` y `editor/scene.py`: proyecto y validación de la escena.
- `editor/static/editor/js/editor.js`: diapositivas, reproducción y edición del lienzo.
- `editor/gemini.py`: acceso de servidor a Gemini y validación de respuestas estructuradas.
- `editor/documents.py` y `editor/tasks.py`: validación, extracción y conversión en segundo plano de PDF/PPTX.
- `editor/exports.py`: exportación a MP4, GIF, PDF, PowerPoint editable y PNG.
- `editor/migrations/`: migraciones del proyecto, incluidas las diapositivas.
- `editor/static/editor/images/logo.png`: logo PNG usado en los encabezados y el acceso a **Mis proyectos**.
- `editor/static/editor/images/favicon.png`: versión recortada del emblema para la pestaña del navegador.
- `editor/static/editor/images/elementos/`: imágenes PNG, JPG, JPEG o WebP disponibles en la sección **Elementos**.
- `editor/static/editor/images/fondos/`: imágenes PNG, JPG, JPEG o WebP disponibles en la sección **Fondos**.
- `media/audio_uploads/`: biblioteca privada de audios subidos, separada por usuario.
- `media/documentos/`: documentos fuente privados, separados por usuario.
- `docs/ANALISIS_REQUERIMIENTOS_IA.md`: comparación entre los requerimientos, lo implementado y lo pendiente.
- `editor/templates/editor/proyectos.html`: listado y creación de proyectos.
- `editor/templates/registration/login.html`: inicio de sesión.
- `editor/static/editor/css/editor.css`: estilos propios.
- `index.html`: referencia original, conservada sin cambios.

## Estado actual

Se guardan el nombre, propietario, fechas y las diapositivas independientes con
sus objetos, fondos y duración.
Los proyectos nuevos empiezan sin texto. Ya no existe el panel de título/subtítulo.
En **Elementos**, elegir una imagen la agrega al lienzo; se puede seleccionar,
mover, redimensionar y animar como los cuadros de texto. En **Fondos**, elegir
una imagen la aplica al lienzo completo; **Quitar fondo** vuelve al lienzo blanco.
Los cambios se guardan automáticamente. Para agregar más recursos, copia
archivos PNG, JPG, JPEG o WebP en la carpeta de la sección y recarga el editor.
Para el logo, copia el archivo PNG a `editor/static/editor/images/logo.png`.
Ese archivo se muestra en el encabezado como botón para regresar a **Mis proyectos**
y también como icono PNG de la pestaña del navegador.

Si vienes de la primera etapa, ejecutar `manage.py migrate` con el Python del
entorno virtual crea o actualiza la tabla de proyectos sin eliminar los datos
existentes. La migración 0003 convierte los títulos y subtítulos anteriores en
cuadros independientes antes de retirar esos campos.

Tailwind, Font Awesome, Poppins y las imágenes se cargan desde servicios externos,
por lo que se necesita conexión para mostrar el diseño completo.

## Verificación

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test editor
```

Las pruebas usan una base de datos temporal: verifican registro, sesiones,
aislamiento entre usuarios, validación, persistencia, escape de HTML, métodos HTTP
y protección CSRF.

Prueba opcional de interacción real en Chromium:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe manage.py test editor.browser_tests
```

Comprueba diapositivas, animaciones, agregar elementos e imágenes de fondo,
editar, mover, redimensionar, dar formato, guardar, recargar y exportar usando
una base temporal y Chromium sin ventana visible.

Configuración destinada a desarrollo local. Para un despliegue se deben configurar
`DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0` y `DJANGO_ALLOWED_HOSTS` (separados por comas),
además del servidor y los archivos estáticos.
