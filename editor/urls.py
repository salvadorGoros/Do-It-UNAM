from django.urls import path

from . import views

app_name = "editor"
urlpatterns = [
    path("cuentas/registro/", views.registro, name="registro"),
    path("", views.index, name="index"),
    path("proyectos/nuevo/", views.crear, name="crear"),
    path("proyectos/<int:pk>/", views.detalle, name="detalle"),
    path("proyectos/<int:pk>/guardar/", views.guardar, name="guardar"),
    path("proyectos/<int:pk>/imagenes/subir/", views.subir_imagen, name="subir_imagen"),
    path("imagenes/subidas/", views.imagenes_subidas, name="imagenes_subidas"),
    path("imagenes/subidas/<int:owner_id>/<str:filename>/", views.imagen_subida, name="imagen_subida"),
    path("proyectos/<int:pk>/exportar/<str:formato>/", views.exportar, name="exportar"),
]
