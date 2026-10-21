# Análisis de requerimientos e integración de IA

Documento de referencia analizado: `Requerimientos - Multimedia ll.docx`.
Su contenido se tomó como especificación funcional, no como instrucciones de ejecución.

## Estado comparado

| Área del requerimiento | Estado del proyecto | Observación |
|---|---|---|
| Identidad visual institucional | Parcial | La interfaz ya usa la identidad de DO IT UNAM y su paleta; falta formalizar una biblioteca institucional administrable. |
| Cuentas y proyectos privados | Implementado | Las altas exigen correo `@comunidad.unam.mx`; se puede iniciar sesión con correo o número de cuenta y recuperar la contraseña por correo. Los datos y recursos continúan separados por propietario. |
| Roles Alumno, Docente y Administrador | Implementado | Existen tablas de rol y perfil. Las altas reciben Alumno; el administrador asigna o revoca roles desde Django Admin. |
| Editor tipo Canva | Implementado | Diapositivas, textos, imágenes, fondos, formato, historial, guardado automático y presentación; interfaz adaptable a teléfono, tableta y escritorio. |
| Audio | Implementado | Biblioteca privada y hasta tres pistas por diapositiva con recorte, volumen, fundidos y forma de onda. |
| Animaciones | Implementado | Línea de tiempo compacta a 30 fps, fotogramas clave, rutas, plantillas y pausas activadas por clic. |
| Exportación | Implementado | PDF, PowerPoint editable, PNG, MP4 y GIF; video animado en 1080p o 720p. |
| IA para estructuras de presentación | Implementado en esta etapa | Gemini genera títulos, viñetas, guion y sugerencia visual; el resultado se agrega como diapositivas editables. |
| IA para resumen, mejora, viñetas y guiones | Implementado en esta etapa | Trabaja con el objeto seleccionado o con texto escrito; los guiones se guardan en notas de la diapositiva. |
| IA para imágenes y diagramas | Implementado en esta etapa | La imagen generada se valida, se guarda en la biblioteca privada del usuario y luego puede agregarse al lienzo. |
| Clave y seguridad de Gemini | Implementado en esta etapa | La clave vive en `.env`, solo se lee en el servidor y nunca se inserta en HTML o JSON. |
| Consumo y cuota de IA | Implementado | Se registran modelo, operación, tokens y resultado. Cada rol tiene una cuota diaria editable y la auditoría administrativa puede filtrarse por rol y periodo. |
| Conversión PDF/PPTX a presentación | Implementado | Trabajos privados con progreso, cancelación y reintento. PDF usa comprensión visual de Gemini; PPTX conserva texto, tablas y notas como fuente de un borrador editable. |
| PostgreSQL | Preparado | Se activa con variables `POSTGRES_*`; SQLite sigue disponible para desarrollo local y no se migran automáticamente datos existentes entre motores. |
| Redis y tareas asíncronas | Implementado/configurable | Celery usa Redis como broker y backend al desactivar el modo inmediato. El modo local funciona sin servicios adicionales. |
| Carpetas, plantillas y recursos administrables | Pendiente/parcial | Hay proyectos y plantillas privadas de animación; faltan carpetas y plantillas institucionales completas. |

## Arquitectura de IA agregada

1. El navegador envía la tarea al endpoint privado del proyecto con sesión y CSRF.
2. Django valida propiedad, tamaños, opciones y cuota antes de invocar Gemini.
3. `editor/gemini.py` usa el SDK oficial y respuestas JSON estructuradas para presentaciones y texto.
4. Django valida de nuevo la respuesta. Las imágenes también se verifican con Pillow antes de guardarse.
5. Se registra solamente metadato de consumo; los prompts y respuestas no se almacenan en la bitácora de uso.
6. La interfaz permite revisar el resultado antes de incorporarlo al proyecto.
7. Los documentos crean un trabajo persistente y el navegador consulta su estado sin exponer la ruta del archivo.
8. Los PDF se envían temporalmente a Gemini y se eliminan de Files API al terminar; los PPTX se extraen localmente.

## Siguiente etapa recomendada

1. Regularizar desde el panel administrativo las cuentas anteriores y luego desactivar `ALLOW_LEGACY_USERNAME_LOGIN`.
2. Levantar PostgreSQL y Redis en el entorno de despliegue, migrar la información real y ejecutar el trabajador Celery como servicio supervisado.
3. Agregar una política programada de retención o borrado de documentos fuente.
4. Implementar carpetas de proyectos y una biblioteca institucional de plantillas y recursos administrables.
5. Añadir colaboración, compartición y permisos granulares si se confirma esa fase del requerimiento.
