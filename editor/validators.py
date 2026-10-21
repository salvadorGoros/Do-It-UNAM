import re

from django.conf import settings
from django.core.exceptions import ValidationError


def normalizar_numero_cuenta(value):
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\s-]", "", value)


def validar_numero_cuenta(value):
    normalized = normalizar_numero_cuenta(value)
    if not re.fullmatch(r"\d{8,15}", normalized):
        raise ValidationError("Escribe un número de cuenta de 8 a 15 dígitos.")


def validar_correo_institucional(value):
    value = (value or "").strip().lower()
    domain = value.rpartition("@")[2]
    if not domain or domain not in settings.INSTITUTIONAL_EMAIL_DOMAINS:
        allowed = ", ".join(f"@{item}" for item in settings.INSTITUTIONAL_EMAIL_DOMAINS)
        raise ValidationError(f"Usa un correo institucional válido ({allowed}).")
