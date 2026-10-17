import math
import re
from copy import deepcopy
from pathlib import Path

from django.core.exceptions import ValidationError


IMAGE_DIRECTORY = Path(__file__).parent / "static" / "editor" / "images"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
UPLOADED_IMAGE_PATTERN = re.compile(
    r"uploads/[1-9]\d*/[a-f0-9]{32}(?:_[a-zA-Z0-9_-]{1,60})?\.(?:png|jpg|webp)"
)
ANIMATION_PRESETS = {"ninguna", "aparecer", "subir", "zoom", "girar", "rebote"}
MIN_OBJECT_POSITION = -8000
MAX_OBJECT_POSITION = 8000
MAX_OBJECT_WIDTH = 8000
MAX_OBJECT_HEIGHT = 4500


def imagenes_disponibles(seccion):
    if seccion not in {"elementos", "fondos"}:
        return []
    directory = IMAGE_DIRECTORY / seccion
    if not directory.is_dir():
        return []
    return sorted(
        (
            path.relative_to(directory).as_posix()
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ),
        key=str.casefold,
    )


def ruta_imagen_valida(ruta, seccion):
    if not isinstance(ruta, str):
        return False
    if seccion == "elementos" and UPLOADED_IMAGE_PATTERN.fullmatch(ruta):
        return True
    return (
        ruta.startswith(f"{seccion}/")
        and ruta[len(seccion) + 1:] in imagenes_disponibles(seccion)
    )


def imagenes_pertenecen_usuario(diapositivas, usuario_id):
    prefix = f"uploads/{usuario_id}/"
    return all(
        not obj["imagen"].startswith("uploads/")
        or obj["imagen"].startswith(prefix)
        for slide in diapositivas
        for obj in slide["objetos"]
        if obj.get("tipo") == "imagen"
    )


def validar_fondo(fondo):
    if fondo and not ruta_imagen_valida(fondo, "fondos"):
        raise ValidationError("El fondo seleccionado no está disponible.")


def validar_diapositivas(diapositivas):
    def invalid():
        raise ValidationError("Las diapositivas contienen datos inválidos.")

    if not isinstance(diapositivas, list) or not 1 <= len(diapositivas) <= 100:
        invalid()
    for diapositiva in diapositivas:
        required_keys = {"id", "objetos", "fondo", "duracion_frames"}
        if (
            not isinstance(diapositiva, dict)
            or set(diapositiva) not in (required_keys, required_keys | {"color_fondo"})
        ):
            invalid()
        if not isinstance(diapositiva["id"], str) or not re.fullmatch(
            r"[a-zA-Z0-9_-]{1,64}", diapositiva["id"]
        ):
            invalid()
        try:
            validar_objetos(diapositiva["objetos"])
            validar_fondo(diapositiva["fondo"])
        except ValidationError:
            invalid()
        color_fondo = diapositiva.get("color_fondo", "#ffffff")
        if not isinstance(color_fondo, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color_fondo):
            invalid()
        duracion = diapositiva["duracion_frames"]
        if type(duracion) is not int or not 30 <= duracion <= 3600:
            invalid()
        if any(
            key["frame"] > duracion
            for obj in diapositiva["objetos"]
            for key in obj["fotogramas"]
        ):
            invalid()


def completar_animacion(objetos, anteriores=()):
    objetos = deepcopy(objetos)
    guardados = {obj["id"]: obj for obj in anteriores}
    if isinstance(objetos, list):
        for obj in objetos:
            if isinstance(obj, dict) and "fotogramas" not in obj:
                previo = guardados.get(obj.get("id")) if isinstance(obj.get("id"), str) else None
                obj["fotogramas"] = deepcopy(previo["fotogramas"]) if previo and "fotogramas" in previo else [
                    dict(frame=0, x=obj.get("x"), y=obj.get("y"), giro=0, opacidad=1, interpolacion="lineal")
                ]
    return objetos


def validar_objetos(objetos):
    """Valida cuadros de texto e imágenes para una escena de 800 x 450."""
    def invalid():
        raise ValidationError("Los objetos de la escena contienen datos inválidos.")

    if not isinstance(objetos, list) or len(objetos) > 100:
        invalid()
    ids = set()
    keys = {"id", "texto", "x", "y", "ancho", "alto", "fuente", "tamano", "color", "negrita", "cursiva", "subrayado", "alineacion", "fotogramas"}
    for item in objetos:
        if not isinstance(item, dict):
            invalid()
        image_object = item.get("tipo") == "imagen"
        expected_keys = keys | {"tipo", "imagen"} if image_object else keys
        if "animacion" in item:
            expected_keys.add("animacion")
        if set(item) != expected_keys or ("tipo" in item and not image_object):
            invalid()
        if item.get("animacion", "ninguna") not in ANIMATION_PRESETS:
            invalid()
        if image_object and not ruta_imagen_valida(item["imagen"], "elementos"):
            invalid()
        if not isinstance(item["id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", item["id"]) or item["id"] in ids:
            invalid()
        ids.add(item["id"])
        if not isinstance(item["texto"], str) or len(item["texto"]) > 5000:
            invalid()
        for field, low, high in [
            ("x", MIN_OBJECT_POSITION, MAX_OBJECT_POSITION),
            ("y", MIN_OBJECT_POSITION, MAX_OBJECT_POSITION),
            ("ancho", 60, MAX_OBJECT_WIDTH),
            ("alto", 30, MAX_OBJECT_HEIGHT),
            ("tamano", 8, 120),
        ]:
            value = item[field]
            if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
                invalid()
        if item["fuente"] not in ("Poppins", "Arial") or item["alineacion"] not in ("left", "center", "right"):
            invalid()
        if not isinstance(item["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", item["color"]):
            invalid()
        if any(type(item[field]) is not bool for field in ("negrita", "cursiva", "subrayado")):
            invalid()
        frames = item["fotogramas"]
        if not isinstance(frames, list) or not 1 <= len(frames) <= 3601:
            invalid()
        previous = -1
        for key in frames:
            if not isinstance(key, dict) or set(key) != {"frame", "x", "y", "giro", "opacidad", "interpolacion"}:
                invalid()
            if type(key["frame"]) is not int or not previous < key["frame"] <= 3600:
                invalid()
            previous = key["frame"]
            for field, low, high in [
                ("x", MIN_OBJECT_POSITION, MAX_OBJECT_POSITION),
                ("y", MIN_OBJECT_POSITION, MAX_OBJECT_POSITION),
                ("giro", -360, 360),
                ("opacidad", 0, 1),
            ]:
                value = key[field]
                if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
                    invalid()
            if key["interpolacion"] not in ("lineal", "suave"):
                invalid()
