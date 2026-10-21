from django.contrib import admin

from .models import (
    DocumentoFuente,
    PerfilUsuario,
    PlantillaAnimacion,
    Proyecto,
    Rol,
    TrabajoConversion,
    UsoIA,
)


@admin.register(Rol)
class RolAdmin(admin.ModelAdmin):
    list_display = ["nombre", "clave", "cuota_tokens_dia", "usuarios"]
    fields = ["clave", "nombre", "cuota_tokens_dia"]
    readonly_fields = ["clave"]

    @admin.display(description="Usuarios")
    def usuarios(self, obj):
        return obj.perfiles.count()

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = [
        "correo_institucional", "numero_cuenta", "usuario", "rol", "cuota_diaria", "fecha_registro",
    ]
    list_filter = ["rol"]
    search_fields = ["correo_institucional", "numero_cuenta", "usuario__username", "usuario__email"]
    autocomplete_fields = ["usuario"]
    readonly_fields = ["fecha_registro"]

    @admin.display(description="Cuota diaria")
    def cuota_diaria(self, obj):
        return obj.cuota_tokens_dia


@admin.register(Proyecto)
class ProyectoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "propietario", "creado", "modificado"]
    list_filter = ["propietario"]
    search_fields = ["nombre", "propietario__username", "propietario__email"]
    readonly_fields = ["creado", "modificado"]


@admin.register(PlantillaAnimacion)
class PlantillaAnimacionAdmin(admin.ModelAdmin):
    list_display = ["nombre", "propietario", "modificado"]
    list_filter = ["propietario"]
    search_fields = ["nombre", "propietario__username", "propietario__email"]
    readonly_fields = ["creado", "modificado"]


@admin.register(UsoIA)
class UsoIAAdmin(admin.ModelAdmin):
    list_display = ["usuario", "rol", "proyecto", "accion", "modelo", "tokens_totales", "exitoso", "creado"]
    list_filter = ["usuario__perfil_institucional__rol", "accion", "modelo", "exitoso", "creado"]
    search_fields = ["usuario__username", "usuario__email", "proyecto__nombre"]
    readonly_fields = [
        "usuario", "proyecto", "accion", "modelo", "tokens_entrada", "tokens_salida",
        "tokens_totales", "exitoso", "categoria_error", "creado",
    ]

    def has_add_permission(self, request):
        return False

    @admin.display(description="Rol")
    def rol(self, obj):
        try:
            return obj.usuario.perfil_institucional.rol.nombre
        except PerfilUsuario.DoesNotExist:
            return "Cuenta anterior"


@admin.register(DocumentoFuente)
class DocumentoFuenteAdmin(admin.ModelAdmin):
    list_display = ["nombre_original", "tipo", "usuario", "proyecto", "tamano", "creado"]
    list_filter = ["tipo", "creado"]
    search_fields = ["nombre_original", "usuario__email", "proyecto__nombre"]
    readonly_fields = ["usuario", "proyecto", "archivo", "nombre_original", "tipo", "tamano", "creado"]

    def has_add_permission(self, request):
        return False


@admin.register(TrabajoConversion)
class TrabajoConversionAdmin(admin.ModelAdmin):
    list_display = ["documento", "usuario", "proyecto", "estado", "progreso", "intentos", "creado"]
    list_filter = ["estado", "estilo", "creado"]
    search_fields = ["documento__nombre_original", "usuario__email", "proyecto__nombre", "celery_task_id"]
    readonly_fields = [
        "id", "usuario", "proyecto", "documento", "estado", "progreso", "mensaje", "error",
        "resultado", "numero_diapositivas", "audiencia", "estilo", "celery_task_id", "intentos",
        "cancelacion_solicitada", "creado", "iniciado", "terminado",
    ]

    def has_add_permission(self, request):
        return False
