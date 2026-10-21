from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from .validators import validar_correo_institucional, validar_numero_cuenta
from .scene import (
    MAX_SLIDE_FRAMES,
    validar_diapositivas,
    validar_fondo,
    validar_objetos,
    validar_plantilla_animacion,
)


def ruta_documento_fuente(instance, filename):
    extension = Path(filename).suffix.lower()
    return f"documentos/{instance.usuario_id}/{uuid4().hex}{extension}"


class Rol(models.Model):
    class Clave(models.TextChoices):
        ALUMNO = "alumno", "Alumno"
        DOCENTE = "docente", "Docente"
        ADMINISTRADOR = "administrador", "Administrador"

    clave = models.CharField(max_length=20, choices=Clave.choices, unique=True)
    nombre = models.CharField(max_length=30, unique=True)
    cuota_tokens_dia = models.PositiveIntegerField(
        default=10_000,
        validators=[MinValueValidator(0)],
        help_text="Límite total diario para operaciones de IA.",
    )

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return self.nombre


class PerfilUsuario(models.Model):
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="perfil_institucional",
    )
    rol = models.ForeignKey(Rol, on_delete=models.PROTECT, related_name="perfiles")
    numero_cuenta = models.CharField(
        max_length=15,
        unique=True,
        null=True,
        blank=True,
        validators=[validar_numero_cuenta],
    )
    correo_institucional = models.EmailField(
        max_length=150,
        unique=True,
        validators=[validar_correo_institucional],
    )
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["usuario__username"]

    def clean(self):
        super().clean()
        self.correo_institucional = self.correo_institucional.strip().lower()
        if self.numero_cuenta:
            from .validators import normalizar_numero_cuenta

            self.numero_cuenta = normalizar_numero_cuenta(self.numero_cuenta)
        if type(self).objects.filter(
            correo_institucional__iexact=self.correo_institucional
        ).exclude(pk=self.pk).exists():
            raise ValidationError({"correo_institucional": "Ya existe un perfil con este correo."})
        if self.numero_cuenta and type(self).objects.filter(
            numero_cuenta=self.numero_cuenta
        ).exclude(pk=self.pk).exists():
            raise ValidationError({"numero_cuenta": "Ya existe un perfil con este número de cuenta."})

    def save(self, *args, **kwargs):
        self.correo_institucional = self.correo_institucional.strip().lower()
        if self.numero_cuenta:
            from .validators import normalizar_numero_cuenta

            self.numero_cuenta = normalizar_numero_cuenta(self.numero_cuenta)
        super().save(*args, **kwargs)
        should_be_staff = self.usuario.is_superuser or self.rol.clave == Rol.Clave.ADMINISTRADOR
        user_updates = {}
        if self.usuario.is_staff != should_be_staff:
            user_updates["is_staff"] = should_be_staff
            self.usuario.is_staff = should_be_staff
        if self.usuario.email.lower() != self.correo_institucional:
            user_updates["email"] = self.correo_institucional
            self.usuario.email = self.correo_institucional
        if user_updates:
            type(self.usuario).objects.filter(pk=self.usuario_id).update(**user_updates)

    @property
    def cuota_tokens_dia(self):
        return self.rol.cuota_tokens_dia

    def __str__(self):
        return f"{self.correo_institucional} · {self.rol.nombre}"


class Proyecto(models.Model):
    propietario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="proyectos"
    )
    nombre = models.CharField(max_length=150)
    objetos = models.JSONField(default=list, blank=True, validators=[validar_objetos])
    diapositivas = models.JSONField(default=list, blank=True, validators=[validar_diapositivas])
    fondo = models.CharField(max_length=255, blank=True, default="")
    duracion_frames = models.PositiveIntegerField(
        default=300,
        validators=[MinValueValidator(30), MaxValueValidator(MAX_SLIDE_FRAMES)],
    )
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-modificado", "-pk"]

    def __str__(self):
        return self.nombre

    def clean(self):
        super().clean()
        validar_objetos(self.objetos)
        validar_fondo(self.fondo)
        if self.diapositivas:
            validar_diapositivas(self.diapositivas)
        if self.duracion_frames is not None and any(
            key["frame"] > self.duracion_frames for obj in self.objetos for key in obj["fotogramas"]
        ):
            raise ValidationError({"duracion_frames": "La duración deja fotogramas fuera de la escena."})


class PlantillaAnimacion(models.Model):
    propietario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="plantillas_animacion",
    )
    nombre = models.CharField(max_length=100)
    datos = models.JSONField(validators=[validar_plantilla_animacion])
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["propietario", "nombre"],
                name="plantilla_animacion_nombre_por_usuario",
            ),
        ]

    def __str__(self):
        return self.nombre


class UsoIA(models.Model):
    class Accion(models.TextChoices):
        PRESENTACION = "presentacion", "Presentación"
        TEXTO = "texto", "Texto"
        IMAGEN = "imagen", "Imagen"
        DOCUMENTO = "documento", "Conversión de documento"

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="usos_ia",
    )
    proyecto = models.ForeignKey(
        Proyecto,
        on_delete=models.SET_NULL,
        related_name="usos_ia",
        null=True,
        blank=True,
    )
    accion = models.CharField(max_length=20, choices=Accion.choices)
    modelo = models.CharField(max_length=100)
    tokens_entrada = models.PositiveIntegerField(default=0)
    tokens_salida = models.PositiveIntegerField(default=0)
    tokens_totales = models.PositiveIntegerField(default=0)
    exitoso = models.BooleanField(default=True)
    categoria_error = models.CharField(max_length=60, blank=True, default="")
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado", "-pk"]
        indexes = [models.Index(fields=["usuario", "creado"], name="editor_uso_usuario_fecha")]

    def __str__(self):
        return f"{self.usuario} · {self.get_accion_display()} · {self.tokens_totales} tokens"


class DocumentoFuente(models.Model):
    class Tipo(models.TextChoices):
        PDF = "pdf", "PDF"
        PPTX = "pptx", "PowerPoint"

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="documentos_fuente",
    )
    proyecto = models.ForeignKey(
        Proyecto,
        on_delete=models.CASCADE,
        related_name="documentos_fuente",
    )
    archivo = models.FileField(upload_to=ruta_documento_fuente, max_length=255)
    nombre_original = models.CharField(max_length=255)
    tipo = models.CharField(max_length=8, choices=Tipo.choices)
    tamano = models.PositiveBigIntegerField()
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado", "-pk"]

    def __str__(self):
        return self.nombre_original


@receiver(post_delete, sender=DocumentoFuente)
def eliminar_archivo_documento_fuente(sender, instance, **kwargs):
    if instance.archivo.name:
        instance.archivo.storage.delete(instance.archivo.name)


class TrabajoConversion(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        PROCESANDO = "procesando", "Procesando"
        COMPLETADO = "completado", "Completado"
        FALLIDO = "fallido", "Fallido"
        CANCELADO = "cancelado", "Cancelado"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trabajos_conversion",
    )
    proyecto = models.ForeignKey(
        Proyecto,
        on_delete=models.CASCADE,
        related_name="trabajos_conversion",
    )
    documento = models.ForeignKey(
        DocumentoFuente,
        on_delete=models.CASCADE,
        related_name="trabajos",
    )
    estado = models.CharField(
        max_length=12,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    progreso = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    mensaje = models.CharField(max_length=240, blank=True, default="En espera")
    error = models.CharField(max_length=500, blank=True, default="")
    resultado = models.JSONField(null=True, blank=True)
    numero_diapositivas = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(20)],
    )
    audiencia = models.CharField(max_length=120, default="Estudiantes universitarios")
    estilo = models.CharField(max_length=20, default="academico")
    celery_task_id = models.CharField(max_length=255, blank=True, default="")
    intentos = models.PositiveSmallIntegerField(default=1)
    cancelacion_solicitada = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)
    iniciado = models.DateTimeField(null=True, blank=True)
    terminado = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-creado"]
        indexes = [
            models.Index(fields=["usuario", "estado", "creado"], name="editor_conv_usuario_estado"),
        ]

    def __str__(self):
        return f"{self.documento.nombre_original} · {self.get_estado_display()}"
