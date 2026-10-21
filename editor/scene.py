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
UPLOADED_AUDIO_PATTERN = re.compile(
    r"audio_uploads/[1-9]\d*/[a-f0-9]{32}(?:_[a-zA-Z0-9_-]{1,60})?\.(?:mp3|wav|ogg|m4a)"
)
ANIMATION_PRESETS = {
    "ninguna", "aparecer", "subir", "zoom", "girar", "rebote", "pulso",
    "desaparecer", "salir-arriba",
}
FONT_FAMILIES = {"Poppins", "Arial", "Georgia", "Verdana", "Courier New"}
KEYFRAME_INTERPOLATIONS = {"lineal", "suave", "rebote", "instantanea", "bezier"}
TEXT_TRANSITIONS = {"instantaneo", "escritura", "transicion"}
MAX_SLIDE_FRAMES = 108000
MAX_AUDIO_TRACKS = 3
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


def audios_pertenecen_usuario(diapositivas, usuario_id):
    prefix = f"audio_uploads/{usuario_id}/"
    return all(
        (
            not slide.get("audio") or slide["audio"].startswith(prefix)
        ) and all(track["path"].startswith(prefix) for track in slide.get("audios", []))
        for slide in diapositivas
    )


def validar_fondo(fondo):
    if fondo and not ruta_imagen_valida(fondo, "fondos"):
        raise ValidationError("El fondo seleccionado no está disponible.")


def validar_audio(audio):
    if not isinstance(audio, str) or (audio and not UPLOADED_AUDIO_PATTERN.fullmatch(audio)):
        raise ValidationError("El audio seleccionado no está disponible.")


def validar_diapositivas(diapositivas):
    def invalid():
        raise ValidationError("Las diapositivas contienen datos inválidos.")

    if not isinstance(diapositivas, list) or not 1 <= len(diapositivas) <= 100:
        invalid()
    for diapositiva in diapositivas:
        required_keys = {"id", "objetos", "fondo", "duracion_frames"}
        optional_keys = {"color_fondo", "audio", "audios", "marcadores", "notas"}
        if (
            not isinstance(diapositiva, dict)
            or not required_keys.issubset(diapositiva)
            or not set(diapositiva).issubset(required_keys | optional_keys)
        ):
            invalid()
        if not isinstance(diapositiva["id"], str) or not re.fullmatch(
            r"[a-zA-Z0-9_-]{1,64}", diapositiva["id"]
        ):
            invalid()
        try:
            validar_objetos(diapositiva["objetos"])
            validar_fondo(diapositiva["fondo"])
            validar_audio(diapositiva.get("audio", ""))
        except ValidationError:
            invalid()
        color_fondo = diapositiva.get("color_fondo", "#ffffff")
        if not isinstance(color_fondo, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color_fondo):
            invalid()
        notas = diapositiva.get("notas", "")
        if not isinstance(notas, str) or len(notas) > 20_000:
            invalid()
        duracion = diapositiva["duracion_frames"]
        if type(duracion) is not int or not 30 <= duracion <= MAX_SLIDE_FRAMES:
            invalid()
        if any(
            key["frame"] > duracion
            for obj in diapositiva["objetos"]
            for key in obj["fotogramas"]
        ):
            invalid()
        audios = diapositiva.get("audios", [])
        if not isinstance(audios, list) or len(audios) > MAX_AUDIO_TRACKS:
            invalid()
        audio_ids = set()
        audio_keys = {
            "id", "path", "inicio_frame", "recorte_inicio", "recorte_fin",
            "volumen", "silenciado", "fundido_entrada", "fundido_salida",
        }
        for track in audios:
            if not isinstance(track, dict) or set(track) != audio_keys:
                invalid()
            if (
                not isinstance(track["id"], str)
                or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", track["id"])
                or track["id"] in audio_ids
            ):
                invalid()
            audio_ids.add(track["id"])
            try:
                validar_audio(track["path"])
            except ValidationError:
                invalid()
            if type(track["inicio_frame"]) is not int or not 0 <= track["inicio_frame"] <= MAX_SLIDE_FRAMES:
                invalid()
            for field in ("recorte_inicio", "fundido_entrada", "fundido_salida"):
                value = track[field]
                if type(value) not in (int, float) or not 0 <= value <= 3600 or not math.isfinite(value):
                    invalid()
            recorte_fin = track["recorte_fin"]
            if recorte_fin is not None and (
                type(recorte_fin) not in (int, float)
                or not track["recorte_inicio"] < recorte_fin <= 3600
                or not math.isfinite(recorte_fin)
            ):
                invalid()
            if type(track["volumen"]) not in (int, float) or not 0 <= track["volumen"] <= 1:
                invalid()
            if type(track["silenciado"]) is not bool:
                invalid()
        markers = diapositiva.get("marcadores", [])
        if not isinstance(markers, list) or len(markers) > 100:
            invalid()
        marker_ids = set()
        object_ids = {obj["id"] for obj in diapositiva["objetos"]}
        for marker in markers:
            if not isinstance(marker, dict) or set(marker) != {"id", "frame", "objeto_id"}:
                invalid()
            if (
                not isinstance(marker["id"], str)
                or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", marker["id"])
                or marker["id"] in marker_ids
                or type(marker["frame"]) is not int
                or not 0 <= marker["frame"] <= duracion
                or marker["objeto_id"] not in object_ids
            ):
                invalid()
            marker_ids.add(marker["id"])


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


def validar_plantilla_animacion(datos):
    if not isinstance(datos, dict) or set(datos) != {"fotogramas"}:
        raise ValidationError("La plantilla de animación contiene datos inválidos.")
    objeto = {
        "id": "plantilla", "texto": "", "x": 0, "y": 0, "ancho": 100, "alto": 100,
        "fuente": "Poppins", "tamano": 36, "color": "#000000", "negrita": False,
        "cursiva": False, "subrayado": False, "alineacion": "left",
        "fotogramas": datos["fotogramas"],
    }
    try:
        validar_objetos([objeto])
    except ValidationError as error:
        raise ValidationError("La plantilla de animación contiene datos inválidos.") from error


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
        expected_keys = keys | {"tipo", "imagen"} if image_object else set(keys)
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
        if item["fuente"] not in FONT_FAMILIES or item["alineacion"] not in ("left", "center", "right"):
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
            required_keyframe_keys = {"frame", "x", "y", "giro", "opacidad", "interpolacion"}
            optional_keyframe_keys = {
                "ancho", "alto", "color", "tamano", "texto", "fuente", "bezier", "texto_modo",
            }
            if (
                not isinstance(key, dict)
                or not required_keyframe_keys.issubset(key)
                or not set(key).issubset(required_keyframe_keys | optional_keyframe_keys)
            ):
                invalid()
            if type(key["frame"]) is not int or not previous < key["frame"] <= MAX_SLIDE_FRAMES:
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
            for field, low, high in (("ancho", 60, MAX_OBJECT_WIDTH), ("alto", 30, MAX_OBJECT_HEIGHT), ("tamano", 8, 120)):
                if field in key:
                    value = key[field]
                    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
                        invalid()
            if "color" in key and (
                not isinstance(key["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", key["color"])
            ):
                invalid()
            if "texto" in key and (not isinstance(key["texto"], str) or len(key["texto"]) > 5000):
                invalid()
            if "fuente" in key and key["fuente"] not in FONT_FAMILIES:
                invalid()
            if "texto_modo" in key and key["texto_modo"] not in TEXT_TRANSITIONS:
                invalid()
            if key["interpolacion"] not in KEYFRAME_INTERPOLATIONS:
                invalid()
            bezier = key.get("bezier")
            if key["interpolacion"] == "bezier":
                if (
                    not isinstance(bezier, list) or len(bezier) != 4
                    or any(type(value) not in (int, float) or not math.isfinite(value) for value in bezier)
                    or not 0 <= bezier[0] <= 1 or not 0 <= bezier[2] <= 1
                    or not all(-2 <= value <= 2 for value in (bezier[1], bezier[3]))
                ):
                    invalid()
            elif bezier is not None:
                invalid()
