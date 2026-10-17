from copy import deepcopy

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError

from .models import Proyecto
from .scene import validar_diapositivas


class RegistroForm(UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Nombre de usuario"
        self.fields["username"].widget.attrs.update({"autocomplete": "username"})
        self.fields["password1"].label = "Contraseña"
        self.fields["password1"].widget.attrs.update({"autocomplete": "new-password"})
        self.fields["password2"].label = "Confirmar contraseña"
        self.fields["password2"].widget.attrs.update({"autocomplete": "new-password"})


class ProyectoForm(forms.ModelForm):
    class Meta:
        model = Proyecto
        fields = ["nombre"]
        labels = {"nombre": "Nombre del proyecto"}
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "project-name", "placeholder": "Nombre del proyecto"})
        }
        error_messages = {
            "nombre": {
                "required": "Escribe un nombre para el proyecto.",
                "max_length": "El nombre no puede superar los 150 caracteres.",
            }
        }


class EditorForm(ProyectoForm):
    objetos = forms.JSONField(required=False, widget=forms.HiddenInput())
    fondo = forms.CharField(required=False, widget=forms.HiddenInput())
    diapositivas = forms.JSONField(required=False, widget=forms.HiddenInput())
    diapositiva_activa = forms.IntegerField(required=False, min_value=0, initial=0, widget=forms.HiddenInput())

    def clean_objetos(self):
        from .scene import completar_animacion, validar_objetos

        objetos = completar_animacion(self.cleaned_data["objetos"], self.instance.objetos or [])
        validar_objetos(objetos)
        return objetos

    def clean_fondo(self):
        from .scene import validar_fondo

        fondo = self.cleaned_data["fondo"]
        validar_fondo(fondo)
        return fondo

    def clean_diapositivas(self):
        return self.cleaned_data.get("diapositivas") or []

    def clean(self):
        cleaned = super().clean()
        required_fields = ("objetos", "fondo", "duracion_frames")
        if any(field not in cleaned for field in required_fields):
            return cleaned
        data = self.cleaned_data.get("diapositivas")
        active_index = cleaned.get("diapositiva_activa") or 0
        if not data:
            data = deepcopy(self.instance.diapositivas or [])
        if not data:
            data = [{
                "id": "slide-1",
                "objetos": cleaned["objetos"],
                "fondo": cleaned["fondo"],
                "duracion_frames": cleaned["duracion_frames"],
            }]
        elif active_index >= len(data):
            self.add_error("diapositiva_activa", ValidationError("La diapositiva activa no existe."))
        else:
            data = deepcopy(data)
            data[active_index] = {
                **data[active_index],
                "objetos": cleaned["objetos"],
                "fondo": cleaned["fondo"],
                "duracion_frames": cleaned["duracion_frames"],
            }
        if active_index < len(data) and any(
            key["frame"] > cleaned["duracion_frames"]
            for obj in cleaned["objetos"]
            for key in obj["fotogramas"]
        ):
            self.add_error(
                "duracion_frames",
                ValidationError("La duración deja fotogramas fuera de la escena."),
            )
        try:
            validar_diapositivas(data)
        except ValidationError as error:
            self.add_error("diapositivas", error)
        cleaned["diapositivas"] = data
        return cleaned

    def save(self, commit=True):
        project = super().save(commit=False)
        slides = self.cleaned_data["diapositivas"]
        active_index = self.cleaned_data.get("diapositiva_activa") or 0
        active_slide = slides[active_index]
        project.diapositivas = slides
        project.objetos = active_slide["objetos"]
        project.fondo = active_slide["fondo"]
        project.duracion_frames = active_slide["duracion_frames"]
        if commit:
            project.save()
            self.save_m2m()
        return project

    class Meta(ProyectoForm.Meta):
        fields = ["nombre", "objetos", "fondo", "duracion_frames", "diapositivas", "diapositiva_activa"]
        widgets = {
            **ProyectoForm.Meta.widgets,
            "duracion_frames": forms.HiddenInput(),
            "diapositivas": forms.HiddenInput(),
            "diapositiva_activa": forms.HiddenInput(),
        }
