from django.urls import path

from . import views

app_name = "editor"
urlpatterns = [
    path("cuentas/registro/", views.registro, name="registro"),
    path("administracion/", views.administracion, name="administracion"),
    path("", views.index, name="index"),
    path("proyectos/nuevo/", views.crear, name="crear"),
    path("proyectos/<int:pk>/", views.detalle, name="detalle"),
    path("proyectos/<int:pk>/guardar/", views.guardar, name="guardar"),
    path("proyectos/<int:pk>/imagenes/subir/", views.subir_imagen, name="subir_imagen"),
    path("proyectos/<int:pk>/imagenes/quitar-fondo/", views.quitar_fondo_imagen, name="quitar_fondo_imagen"),
    path("imagenes/subidas/", views.imagenes_subidas, name="imagenes_subidas"),
    path("imagenes/subidas/<int:owner_id>/<str:filename>/", views.imagen_subida, name="imagen_subida"),
    path("proyectos/<int:pk>/audios/subir/", views.subir_audio, name="subir_audio"),
    path("audios/subidos/", views.audios_subidos, name="audios_subidos"),
    path("audios/subidos/<int:owner_id>/<str:filename>/", views.audio_subido, name="audio_subido"),
    path("animaciones/plantillas/", views.plantillas_animacion, name="plantillas_animacion"),
    path("animaciones/plantillas/guardar/", views.guardar_plantilla_animacion, name="guardar_plantilla_animacion"),
    path("animaciones/plantillas/<int:pk>/eliminar/", views.eliminar_plantilla_animacion, name="eliminar_plantilla_animacion"),
    path("proyectos/<int:pk>/ia/estado/", views.estado_ia, name="estado_ia"),
    path("proyectos/<int:pk>/ia/generar/", views.generar_ia, name="generar_ia"),
    path("proyectos/<int:pk>/ia/documentos/", views.subir_documento_ia, name="subir_documento_ia"),
    path("proyectos/<int:pk>/ia/documentos/<uuid:job_id>/", views.estado_conversion, name="estado_conversion"),
    path("proyectos/<int:pk>/ia/documentos/<uuid:job_id>/cancelar/", views.cancelar_conversion, name="cancelar_conversion"),
    path("proyectos/<int:pk>/ia/documentos/<uuid:job_id>/reintentar/", views.reintentar_conversion, name="reintentar_conversion"),
    path("proyectos/<int:pk>/exportar/<str:formato>/", views.exportar, name="exportar"),
]
