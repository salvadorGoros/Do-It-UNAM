from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from .scene import validar_diapositivas, validar_fondo, validar_objetos


class Proyecto(models.Model):
    propietario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="proyectos"
    )
    nombre = models.CharField(max_length=150)
    objetos = models.JSONField(default=list, blank=True, validators=[validar_objetos])
    diapositivas = models.JSONField(default=list, blank=True, validators=[validar_diapositivas])
    fondo = models.CharField(max_length=255, blank=True, default="")
    duracion_frames = models.PositiveIntegerField(default=300, validators=[MinValueValidator(30), MaxValueValidator(3600)])
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
