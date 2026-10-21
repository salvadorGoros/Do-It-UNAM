from copy import deepcopy

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, UserCreationForm
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import PerfilUsuario, Proyecto, Rol
from .scene import validar_diapositivas
from .validators import normalizar_numero_cuenta, validar_correo_institucional, validar_numero_cuenta


class RegistroForm(UserCreationForm):
    username = forms.CharField(required=False, widget=forms.HiddenInput())
    correo_institucional = forms.EmailField(
        max_length=150,
        label="Correo institucional",
        help_text="Debe terminar en @comunidad.unam.mx.",
        validators=[validar_correo_institucional],
        widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "nombre@comunidad.unam.mx"}),
    )
    numero_cuenta = forms.CharField(
        max_length=17,
        required=False,
        label="Número de cuenta (opcional)",
        help_text="De 8 a 15 dígitos; puedes usar espacios o guiones.",
        widget=forms.TextInput(attrs={"autocomplete": "off", "inputmode": "numeric"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "Contraseña"
        self.fields["password1"].widget.attrs.update({"autocomplete": "new-password"})
        self.fields["password2"].label = "Confirmar contraseña"
        self.fields["password2"].widget.attrs.update({"autocomplete": "new-password"})

    def clean_correo_institucional(self):
        email = self.cleaned_data["correo_institucional"].strip().lower()
        User = get_user_model()
        if User.objects.filter(email__iexact=email).exists() or PerfilUsuario.objects.filter(
            correo_institucional__iexact=email
        ).exists():
            raise ValidationError("Ya existe una cuenta con este correo institucional.")
        return email

    def clean_numero_cuenta(self):
        value = normalizar_numero_cuenta(self.cleaned_data.get("numero_cuenta", ""))
        if not value:
            return ""
        validar_numero_cuenta(value)
        if PerfilUsuario.objects.filter(numero_cuenta=value).exists():
            raise ValidationError("Ya existe una cuenta con este número de cuenta.")
        return value

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("correo_institucional")
        if email:
            cleaned["username"] = email
            self.instance.username = email
        return cleaned

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        email = self.cleaned_data["correo_institucional"]
        user.username = email
        user.email = email
        if not commit:
            return user
        user.save()
        alumno, _ = Rol.objects.get_or_create(
            clave=Rol.Clave.ALUMNO,
            defaults={"nombre": "Alumno", "cuota_tokens_dia": 10_000},
        )
        profile = PerfilUsuario(
            usuario=user,
            rol=alumno,
            correo_institucional=email,
            numero_cuenta=self.cleaned_data.get("numero_cuenta") or None,
        )
        profile.full_clean()
        profile.save()
        return user

    class Meta(UserCreationForm.Meta):
        fields = ("username", "correo_institucional", "numero_cuenta", "password1", "password2")


class InstitutionalAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Correo institucional o número de cuenta",
        widget=forms.TextInput(attrs={
            "autofocus": True,
            "autocomplete": "username",
            "placeholder": "nombre@comunidad.unam.mx o número de cuenta",
        }),
    )

    def clean(self):
        identifier = (self.cleaned_data.get("username") or "").strip()
        User = get_user_model()
        user = None
        if "@" in identifier:
            user = User.objects.filter(email__iexact=identifier).first()
        else:
            account_number = normalizar_numero_cuenta(identifier)
            if account_number.isdigit():
                profile = PerfilUsuario.objects.select_related("usuario").filter(
                    numero_cuenta=account_number
                ).first()
                user = profile.usuario if profile else None
        if user is None:
            user = User.objects.filter(username__iexact=identifier, is_superuser=True).first()
        if user is not None:
            self.cleaned_data["username"] = user.get_username()
        elif not settings.ALLOW_LEGACY_USERNAME_LOGIN:
            raise self.get_invalid_login_error()
        return super().clean()


class InstitutionalPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        label="Correo institucional",
        max_length=150,
        widget=forms.EmailInput(attrs={
            "autocomplete": "email",
            "placeholder": "nombre@comunidad.unam.mx",
        }),
    )


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
