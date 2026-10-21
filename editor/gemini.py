"""Integración de servidor con Gemini para el editor.

Este módulo no conoce peticiones HTTP ni guarda datos. Mantener ese límite evita
que la clave de Gemini termine accidentalmente en una plantilla o respuesta JSON.
"""

import base64
import json
from dataclasses import dataclass

from django.conf import settings


class GeminiNotConfigured(Exception):
    """La aplicación no tiene una clave configurada."""


class GeminiServiceError(Exception):
    """Gemini no pudo entregar una respuesta utilizable."""


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class GeminiResult:
    data: object
    usage: TokenUsage


PRESENTATION_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "slides": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "bullets": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "items": {"type": "string"},
                    },
                    "speaker_notes": {"type": "string"},
                    "visual_suggestion": {"type": "string"},
                },
                "required": ["title", "bullets", "speaker_notes", "visual_suggestion"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "slides"],
    "additionalProperties": False,
}

TEXT_SCHEMA = {
    "type": "object",
    "properties": {"response": {"type": "string"}},
    "required": ["response"],
    "additionalProperties": False,
}

TEXT_ACTIONS = {
    "resumir": "Resume el contenido conservando los conceptos y datos esenciales.",
    "mejorar": "Mejora claridad, ortografía, cohesión y tono académico sin cambiar el sentido.",
    "vinetas": "Convierte el contenido en viñetas breves, claras y listas para una diapositiva.",
    "guion": "Redacta un guion oral natural para explicar la diapositiva sin limitarte a leerla.",
}


def is_configured():
    return bool(settings.GEMINI_API_KEY)


def _sdk():
    if not is_configured():
        raise GeminiNotConfigured("Gemini no está configurado.")
    try:
        from google import genai
        from google.genai import types
    except ImportError as error:
        raise GeminiNotConfigured("El SDK de Gemini no está instalado.") from error
    return genai, types


def _usage(response):
    metadata = getattr(response, "usage_metadata", None)
    input_tokens = int(getattr(metadata, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(metadata, "candidates_token_count", 0) or 0)
    total_tokens = int(getattr(metadata, "total_token_count", 0) or 0)
    return TokenUsage(input_tokens, output_tokens, total_tokens or input_tokens + output_tokens)


def _parsed_json(response):
    parsed = getattr(response, "parsed", None)
    if hasattr(parsed, "model_dump"):
        parsed = parsed.model_dump()
    if isinstance(parsed, dict):
        return parsed
    text = getattr(response, "text", "")
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError) as error:
        raise GeminiServiceError("Gemini devolvió una respuesta con formato inválido.") from error


def _clean_text(value, maximum, field):
    if not isinstance(value, str):
        raise GeminiServiceError(f"Gemini devolvió un valor inválido para {field}.")
    value = value.strip()
    if not value or len(value) > maximum:
        raise GeminiServiceError(f"Gemini devolvió un valor inválido para {field}.")
    return value


def _validate_presentation(data, expected_slides):
    if not isinstance(data, dict) or set(data) != {"title", "slides"}:
        raise GeminiServiceError("Gemini devolvió una presentación inválida.")
    slides = data["slides"]
    if not isinstance(slides, list) or len(slides) != expected_slides:
        raise GeminiServiceError("Gemini no generó el número solicitado de diapositivas.")
    cleaned = []
    for slide in slides:
        required = {"title", "bullets", "speaker_notes", "visual_suggestion"}
        if not isinstance(slide, dict) or set(slide) != required:
            raise GeminiServiceError("Gemini devolvió una diapositiva inválida.")
        bullets = slide["bullets"]
        if not isinstance(bullets, list) or not 1 <= len(bullets) <= 8:
            raise GeminiServiceError("Gemini devolvió viñetas inválidas.")
        cleaned.append({
            "title": _clean_text(slide["title"], 120, "el título"),
            "bullets": [_clean_text(item, 500, "una viñeta") for item in bullets],
            "speaker_notes": _clean_text(slide["speaker_notes"], 5000, "el guion"),
            "visual_suggestion": _clean_text(slide["visual_suggestion"], 500, "la sugerencia visual"),
        })
    return {"title": _clean_text(data["title"], 150, "el título general"), "slides": cleaned}


def _presentation_config(types):
    return types.GenerateContentConfig(
        system_instruction=(
            "Eres un asistente de diseño instruccional para estudiantes y docentes de la UNAM. "
            "Responde en español claro, académico e inclusivo. El contenido debe quedar listo "
            "para editarse en un lienzo de presentación. No inventes fuentes, citas ni datos."
        ),
        response_mime_type="application/json",
        response_json_schema=PRESENTATION_SCHEMA,
        temperature=0.35,
    )


def _document_prompt(slide_count, audience, style):
    return (
        f"Convierte el documento proporcionado en exactamente {slide_count} diapositivas editables.\n"
        f"Audiencia: {audience}. Estilo: {style}.\n"
        "Identifica y organiza las ideas esenciales del documento. Cada diapositiva debe tener "
        "de 2 a 6 viñetas concisas, un guion del expositor y una sugerencia visual. "
        "No agregues hechos que no aparezcan en el documento."
    )


def generate_presentation(topic, slide_count, audience, style):
    genai, types = _sdk()
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    prompt = (
        f"Crea exactamente {slide_count} diapositivas sobre: {topic}\n"
        f"Audiencia: {audience}. Estilo: {style}.\n"
        "Cada diapositiva debe aportar una idea distinta, de 3 a 6 viñetas concisas, "
        "un guion del expositor y una sugerencia visual. No inventes fuentes, citas ni datos."
    )
    try:
        response = client.models.generate_content(
            model=settings.GEMINI_TEXT_MODEL,
            contents=prompt,
            config=_presentation_config(types),
        )
        data = _validate_presentation(_parsed_json(response), slide_count)
        return GeminiResult(data, _usage(response))
    except GeminiServiceError:
        raise
    except Exception as error:
        raise GeminiServiceError("Gemini no pudo generar la presentación. Intenta de nuevo.") from error
    finally:
        client.close()


def generate_presentation_from_pdf(file_object, slide_count, audience, style):
    """Usa la comprensión visual nativa de Gemini para PDF y elimina el archivo remoto al terminar."""
    genai, types = _sdk()
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    uploaded = None
    try:
        raw_file = getattr(file_object, "file", file_object)
        raw_file.seek(0)
        uploaded = client.files.upload(
            file=raw_file,
            config=types.UploadFileConfig(mime_type="application/pdf"),
        )
        document_part = types.Part.from_uri(
            file_uri=uploaded.uri,
            mime_type=uploaded.mime_type or "application/pdf",
        )
        response = client.models.generate_content(
            model=settings.GEMINI_TEXT_MODEL,
            contents=[document_part, _document_prompt(slide_count, audience, style)],
            config=_presentation_config(types),
        )
        data = _validate_presentation(_parsed_json(response), slide_count)
        return GeminiResult(data, _usage(response))
    except GeminiServiceError:
        raise
    except Exception as error:
        raise GeminiServiceError("Gemini no pudo convertir el PDF. Intenta de nuevo.") from error
    finally:
        if uploaded and getattr(uploaded, "name", None):
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass
        client.close()


def generate_presentation_from_extracted_document(content, slide_count, audience, style):
    """Convierte el contenido extraído de un PPTX sin subir el archivo original."""
    genai, types = _sdk()
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    prompt = f"{_document_prompt(slide_count, audience, style)}\n\nCONTENIDO EXTRAÍDO:\n{content}"
    try:
        response = client.models.generate_content(
            model=settings.GEMINI_TEXT_MODEL,
            contents=prompt,
            config=_presentation_config(types),
        )
        data = _validate_presentation(_parsed_json(response), slide_count)
        return GeminiResult(data, _usage(response))
    except GeminiServiceError:
        raise
    except Exception as error:
        raise GeminiServiceError("Gemini no pudo convertir el PPTX. Intenta de nuevo.") from error
    finally:
        client.close()


def transform_text(action, source, instruction=""):
    if action not in TEXT_ACTIONS:
        raise ValueError("Acción de texto no admitida.")
    genai, types = _sdk()
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    prompt = (
        f"Tarea: {TEXT_ACTIONS[action]}\n"
        f"Indicaciones adicionales: {instruction or 'Ninguna.'}\n\n"
        f"Contenido:\n{source}"
    )
    try:
        response = client.models.generate_content(
            model=settings.GEMINI_TEXT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "Eres un asistente académico de la UNAM. Conserva hechos, cifras y significado. "
                    "No agregues citas o referencias inexistentes y responde en español."
                ),
                response_mime_type="application/json",
                response_json_schema=TEXT_SCHEMA,
                temperature=0.35,
            ),
        )
        data = _parsed_json(response)
        if not isinstance(data, dict) or set(data) != {"response"}:
            raise GeminiServiceError("Gemini devolvió texto con formato inválido.")
        return GeminiResult(_clean_text(data["response"], 15000, "la respuesta"), _usage(response))
    except GeminiServiceError:
        raise
    except Exception as error:
        raise GeminiServiceError("Gemini no pudo procesar el texto. Intenta de nuevo.") from error
    finally:
        client.close()


def generate_image(prompt, image_type, aspect_ratio):
    genai, types = _sdk()
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    full_prompt = (
        f"Genera un {image_type} educativo y original para una presentación académica. "
        f"Tema y requisitos: {prompt}. Diseño limpio, legible y sin logotipos institucionales inventados."
    )
    try:
        response = client.models.generate_content(
            model=settings.GEMINI_IMAGE_MODEL,
            contents=full_prompt,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
            ),
        )
        candidates = getattr(response, "candidates", None) or []
        parts = getattr(getattr(candidates[0], "content", None), "parts", []) if candidates else []
        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            data = getattr(inline_data, "data", None)
            if not data:
                continue
            if isinstance(data, str):
                data = base64.b64decode(data)
            mime_type = getattr(inline_data, "mime_type", None) or "image/png"
            return GeminiResult({"bytes": bytes(data), "mime_type": mime_type}, _usage(response))
        raise GeminiServiceError("Gemini no devolvió una imagen. Ajusta la descripción e intenta de nuevo.")
    except GeminiServiceError:
        raise
    except Exception as error:
        raise GeminiServiceError("Gemini no pudo generar la imagen. Intenta de nuevo.") from error
    finally:
        client.close()
