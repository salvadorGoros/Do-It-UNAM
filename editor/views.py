import json
import logging
import mimetypes
import re
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from PIL import Image, UnidentifiedImageError

from .forms import EditorForm, ProyectoForm, RegistroForm
from .exports import exportar_gif, exportar_imagenes, exportar_pdf, exportar_pptx, exportar_video
from . import gemini as gemini_service
from .documents import DocumentValidationError, validate_document
from .models import DocumentoFuente, PerfilUsuario, PlantillaAnimacion, Proyecto, Rol, TrabajoConversion, UsoIA
from .tasks import convertir_documento
from .scene import (
    UPLOADED_AUDIO_PATTERN,
    UPLOADED_IMAGE_PATTERN,
    audios_pertenecen_usuario,
    imagenes_disponibles,
    imagenes_pertenecen_usuario,
    validar_plantilla_animacion,
)

logger = logging.getLogger(__name__)
MAX_UPLOADED_IMAGE_SIZE = 15 * 1024 * 1024
MAX_UPLOADED_IMAGE_PIXELS = 40_000_000
MAX_UPLOADED_AUDIO_SIZE = 25 * 1024 * 1024
IMAGE_FORMATS = {
    "PNG": "png",
    "JPEG": "jpg",
    "WEBP": "webp",
}
AUDIO_CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "m4a": "audio/mp4",
}
AI_STYLES = {"academico", "visual", "minimalista", "narrativo"}
AI_IMAGE_TYPES = {"diagrama", "ilustracion", "infografia"}
AI_ASPECT_RATIOS = {"16:9", "4:3", "1:1"}


def _galeria(seccion):
    grupos = {}
    for nombre in imagenes_disponibles(seccion):
        ruta = Path(nombre)
        categoria = ruta.parent.as_posix()
        categoria = categoria if categoria != "." else "General"
        grupos.setdefault(categoria, []).append({
            "ruta": f"{seccion}/{nombre}",
            "nombre": ruta.stem,
        })
    return [
        {"categoria": categoria, "assets": assets}
        for categoria, assets in sorted(grupos.items(), key=lambda grupo: grupo[0].casefold())
    ]


def _contexto_galerias():
    return {
        "elementos": _galeria("elementos"),
        "fondos": _galeria("fondos"),
    }


def _diapositivas(proyecto):
    return proyecto.diapositivas or [{
        "id": "slide-1",
        "objetos": proyecto.objetos,
        "fondo": proyecto.fondo,
        "color_fondo": "#ffffff",
        "audio": "",
        "duracion_frames": proyecto.duracion_frames,
    }]


def _proyectos_con_preview(usuario):
    proyectos = Proyecto.objects.filter(propietario=usuario)
    for proyecto in proyectos:
        diapositivas = _diapositivas(proyecto)
        proyecto.preview_data = diapositivas[0]
        proyecto.preview_script_id = f"project-preview-{proyecto.pk}"
        proyecto.numero_diapositivas = len(diapositivas)
        proyecto.total_objetos = sum(len(slide.get("objetos", [])) for slide in diapositivas)
    return proyectos


def _recursos_validos_para_usuario(form, usuario):
    diapositivas = form.cleaned_data.get("diapositivas", [])
    if not imagenes_pertenecen_usuario(diapositivas, usuario.pk):
        form.add_error("diapositivas", "Una imagen subida no pertenece a tu biblioteca.")
        return False
    for slide in diapositivas:
        for obj in slide["objetos"]:
            ruta = obj.get("imagen", "")
            if ruta.startswith("uploads/") and not default_storage.exists(ruta):
                form.add_error("diapositivas", "Una imagen subida ya no está disponible.")
                return False
    if not audios_pertenecen_usuario(diapositivas, usuario.pk):
        form.add_error("diapositivas", "Un audio subido no pertenece a tu biblioteca.")
        return False
    for slide in diapositivas:
        audio_paths = [slide.get("audio", "")]
        audio_paths.extend(track["path"] for track in slide.get("audios", []))
        for audio in audio_paths:
            if audio and not default_storage.exists(audio):
                form.add_error("diapositivas", "Un audio seleccionado ya no está disponible.")
                return False
    return True


def _validar_archivo_imagen(uploaded_file):
    if uploaded_file.size > MAX_UPLOADED_IMAGE_SIZE:
        return None, "Cada imagen debe pesar 15 MB o menos."
    try:
        with Image.open(uploaded_file) as image:
            image_format = image.format
            width, height = image.size
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return None, "El archivo no es una imagen válida."
    if image_format not in IMAGE_FORMATS:
        return None, "Solo se admiten imágenes PNG, JPEG y WEBP."
    if width * height > MAX_UPLOADED_IMAGE_PIXELS:
        return None, "La imagen supera el límite de 40 megapíxeles."
    uploaded_file.seek(0)
    return IMAGE_FORMATS[image_format], None


def _imagen_serializada(relative_path, owner_id):
    filename = Path(relative_path).name
    name = re.sub(r"^[a-f0-9]{32}_?", "", Path(filename).stem)
    return {
        "path": relative_path,
        "url": reverse(
            "editor:imagen_subida",
            kwargs={"owner_id": owner_id, "filename": filename},
        ),
        "name": name,
    }


def _detectar_formato_audio(uploaded_file):
    header = uploaded_file.read(64)
    uploaded_file.seek(0)
    if header.startswith(b"ID3") or (
        len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
    ):
        return "mp3"
    if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        return "wav"
    if header.startswith(b"OggS"):
        return "ogg"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return "m4a"
    return None


def _validar_archivo_audio(uploaded_file):
    if uploaded_file.size > MAX_UPLOADED_AUDIO_SIZE:
        return None, "Cada audio debe pesar 25 MB o menos."
    extension = _detectar_formato_audio(uploaded_file)
    if extension is None:
        return None, "Solo se admiten audios MP3, WAV, OGG y M4A válidos."
    return extension, None


def _audio_serializado(relative_path, owner_id):
    filename = Path(relative_path).name
    name = re.sub(r"^[a-f0-9]{32}_?", "", Path(filename).stem)
    return {
        "path": relative_path,
        "url": reverse(
            "editor:audio_subido",
            kwargs={"owner_id": owner_id, "filename": filename},
        ),
        "name": name,
    }


def _uso_ia_hoy(usuario):
    now = timezone.localtime()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return UsoIA.objects.filter(usuario=usuario, creado__gte=start).aggregate(
        total=Sum("tokens_totales")
    )["total"] or 0


def _rol_y_limite_ia(usuario):
    try:
        profile = usuario.perfil_institucional
        return profile.rol, profile.cuota_tokens_dia
    except ObjectDoesNotExist:
        return None, settings.GEMINI_DAILY_TOKEN_LIMIT


def _trabajo_conversion_serializado(job):
    if not job:
        return None
    return {
        "id": str(job.pk),
        "status": job.estado,
        "progress": job.progreso,
        "message": job.mensaje,
        "error": job.error,
        "attempts": job.intentos,
        "filename": job.documento.nombre_original,
        "presentation": job.resultado if job.estado == TrabajoConversion.Estado.COMPLETADO else None,
        "status_url": reverse("editor:estado_conversion", kwargs={"pk": job.proyecto_id, "job_id": job.pk}),
        "cancel_url": reverse("editor:cancelar_conversion", kwargs={"pk": job.proyecto_id, "job_id": job.pk}),
        "retry_url": reverse("editor:reintentar_conversion", kwargs={"pk": job.proyecto_id, "job_id": job.pk}),
    }


def _estado_ia(usuario, proyecto=None):
    used = _uso_ia_hoy(usuario)
    role, limit = _rol_y_limite_ia(usuario)
    state = {
        "configured": gemini_service.is_configured(),
        "text_model": settings.GEMINI_TEXT_MODEL,
        "image_model": settings.GEMINI_IMAGE_MODEL,
        "role": {
            "key": role.clave if role else "legacy",
            "name": role.nombre if role else "Cuenta anterior",
        },
        "quota": {
            "used": used,
            "limit": limit,
            "remaining": max(0, limit - used),
        },
    }
    if proyecto is not None:
        latest = TrabajoConversion.objects.filter(
            usuario=usuario,
            proyecto=proyecto,
        ).select_related("documento").first()
        state["conversion"] = _trabajo_conversion_serializado(latest)
    return state


def _json_payload(request):
    if len(request.body) > 64 * 1024:
        raise ValueError("La solicitud es demasiado grande.")
    try:
        payload = json.loads(request.body or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Envía datos JSON válidos.") from error
    if not isinstance(payload, dict):
        raise ValueError("Envía un objeto JSON válido.")
    return payload


def _texto_requerido(payload, key, label, maximum, minimum=1):
    value = payload.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{label} no es válido.")
    value = value.strip()
    if len(value) < minimum:
        raise ValueError(f"{label} es obligatorio.")
    if len(value) > maximum:
        raise ValueError(f"{label} admite hasta {maximum} caracteres.")
    return value


def _uso_serializado(usage):
    return {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "total": usage.total_tokens,
    }


def _registrar_uso_ia(usuario, proyecto, action, model, usage=None, error=""):
    return UsoIA.objects.create(
        usuario=usuario,
        proyecto=proyecto,
        accion=action,
        modelo=model,
        tokens_entrada=usage.input_tokens if usage else 0,
        tokens_salida=usage.output_tokens if usage else 0,
        tokens_totales=usage.total_tokens if usage else 0,
        exitoso=not error,
        categoria_error=error,
    )


def _guardar_imagen_ia(image_data, usuario):
    raw = image_data["bytes"]
    try:
        with Image.open(BytesIO(raw)) as image:
            image_format = image.format
            width, height = image.size
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise gemini_service.GeminiServiceError("Gemini devolvió una imagen inválida.") from error
    if image_format not in IMAGE_FORMATS or width * height > MAX_UPLOADED_IMAGE_PIXELS:
        raise gemini_service.GeminiServiceError("La imagen generada no tiene un formato o tamaño admitido.")
    extension = IMAGE_FORMATS[image_format]
    filename = f"{uuid4().hex}_gemini.{extension}"
    relative_path = default_storage.save(
        f"uploads/{usuario.pk}/{filename}",
        ContentFile(raw),
    )
    image = _imagen_serializada(relative_path, usuario.pk)
    image["name"] = "Imagen generada con Gemini"
    return image


@require_http_methods(["GET", "POST"])
def registro(request):
    if request.user.is_authenticated:
        return redirect("editor:index")

    form = RegistroForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario = form.save()
        login(request, usuario, backend="django.contrib.auth.backends.ModelBackend")
        return redirect("editor:index")
    return render(request, "registration/registro.html", {"form": form})


def _puede_administrar(usuario):
    return usuario.is_authenticated and usuario.is_active and usuario.is_staff


@login_required
@require_http_methods(["GET", "POST"])
def administracion(request):
    if not _puede_administrar(request.user):
        raise PermissionDenied("No tienes permisos para administrar usuarios.")

    roles = list(Rol.objects.annotate(total_usuarios=Count("perfiles")).order_by("pk"))
    create_form = RegistroForm(prefix="nuevo")
    create_panel_open = False

    if request.method == "POST":
        action = request.POST.get("accion")
        if action == "crear_usuario":
            create_panel_open = True
            create_form = RegistroForm(request.POST, prefix="nuevo")
            if create_form.is_valid():
                usuario = create_form.save()
                profile = usuario.perfil_institucional
                messages.success(
                    request,
                    f"Se creó la cuenta {profile.correo_institucional} con el rol Alumno.",
                )
                return redirect("editor:administracion")
        elif action == "cambiar_rol":
            profile = get_object_or_404(
                PerfilUsuario.objects.select_related("usuario", "rol"),
                pk=request.POST.get("perfil_id"),
            )
            selected_role = get_object_or_404(Rol, pk=request.POST.get("rol_id"))
            removes_own_access = (
                profile.usuario_id == request.user.pk
                and profile.rol.clave == Rol.Clave.ADMINISTRADOR
                and selected_role.clave != Rol.Clave.ADMINISTRADOR
                and not request.user.is_superuser
            )
            if removes_own_access:
                messages.error(request, "No puedes retirar tu propio acceso administrativo.")
            else:
                profile.rol = selected_role
                profile.save()
                messages.success(
                    request,
                    f"{profile.correo_institucional} ahora tiene el rol {selected_role.nombre}.",
                )
            return redirect("editor:administracion")
        elif action == "actualizar_cuota":
            role = get_object_or_404(Rol, pk=request.POST.get("rol_id"))
            try:
                quota = int(request.POST.get("cuota_tokens_dia", ""))
                if not 0 <= quota <= 10_000_000:
                    raise ValueError
            except (TypeError, ValueError):
                messages.error(request, "La cuota debe estar entre 0 y 10,000,000 tokens.")
            else:
                role.cuota_tokens_dia = quota
                role.full_clean()
                role.save(update_fields=["cuota_tokens_dia"])
                messages.success(request, f"Se actualizó la cuota del rol {role.nombre}.")
            return redirect("editor:administracion")

    search = request.GET.get("q", "").strip()[:100]
    selected_role_key = request.GET.get("rol", "").strip()
    profiles = PerfilUsuario.objects.select_related("usuario", "rol")
    if search:
        profiles = profiles.filter(
            Q(correo_institucional__icontains=search)
            | Q(numero_cuenta__icontains=search)
            | Q(usuario__username__icontains=search)
        )
    if selected_role_key in Rol.Clave.values:
        profiles = profiles.filter(rol__clave=selected_role_key)
    profiles = profiles.order_by("correo_institucional")
    page_obj = Paginator(profiles, 20).get_page(request.GET.get("pagina"))
    today = timezone.localdate()
    tokens_today = UsoIA.objects.filter(creado__date=today).aggregate(total=Sum("tokens_totales"))["total"] or 0

    return render(request, "editor/administracion.html", {
        "roles": roles,
        "page_obj": page_obj,
        "create_form": create_form,
        "create_panel_open": create_panel_open,
        "search": search,
        "selected_role_key": selected_role_key,
        "total_users": PerfilUsuario.objects.count(),
        "active_users": PerfilUsuario.objects.filter(usuario__is_active=True).count(),
        "total_projects": Proyecto.objects.count(),
        "tokens_today": tokens_today,
    })


@login_required
@require_GET
def index(request):
    return render(request, "editor/proyectos.html", {
        "proyectos": _proyectos_con_preview(request.user),
        "form": ProyectoForm(),
    })


@login_required
@require_POST
def crear(request):
    form = ProyectoForm(request.POST)
    if form.is_valid():
        proyecto = form.save(commit=False)
        proyecto.propietario = request.user
        proyecto.save()
        return redirect("editor:detalle", pk=proyecto.pk)
    return render(request, "editor/proyectos.html", {
        "proyectos": _proyectos_con_preview(request.user),
        "form": form,
    })


@login_required
@require_GET
def detalle(request, pk):
    proyecto = get_object_or_404(Proyecto, pk=pk, propietario=request.user)
    diapositivas = _diapositivas(proyecto)
    return render(request, "editor/index.html", {
        "proyecto": proyecto,
        "form": EditorForm(instance=proyecto, initial={
            "diapositivas": diapositivas,
            "diapositiva_activa": 0,
        }),
        "objetos": diapositivas[0]["objetos"],
        "diapositivas": diapositivas,
        **_contexto_galerias(),
    })


@login_required
@require_POST
def guardar(request, pk):
    proyecto = get_object_or_404(Proyecto, pk=pk, propietario=request.user)
    data = request.POST.copy()
    # Un formulario anterior que envía solo nombre no borra la escena.
    if "objetos" not in data:
        data["objetos"] = json.dumps(proyecto.objetos)
    if "duracion_frames" not in data:
        data["duracion_frames"] = proyecto.duracion_frames
    if "fondo" not in data:
        data["fondo"] = proyecto.fondo
    objetos_guardados = proyecto.objetos
    form = EditorForm(data, instance=proyecto)
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        if form.is_valid():
            if _recursos_validos_para_usuario(form, request.user):
                form.save()
                return JsonResponse({"saved": True})
        return JsonResponse({"errors": form.errors.get_json_data()}, status=400)
    if form.is_valid():
        if _recursos_validos_para_usuario(form, request.user):
            form.save()
            messages.success(request, "Proyecto guardado")
            return redirect("editor:detalle", pk=proyecto.pk)
    return render(request, "editor/index.html", {
        "proyecto": proyecto, "form": form,
        "objetos": form.cleaned_data.get("objetos", objetos_guardados),
        "diapositivas": form.cleaned_data.get("diapositivas", _diapositivas(proyecto)),
        **_contexto_galerias(),
    })


@login_required
@require_GET
def imagenes_subidas(request):
    directory = f"uploads/{request.user.pk}"
    try:
        _, filenames = default_storage.listdir(directory)
    except FileNotFoundError:
        filenames = []
    images = [
        _imagen_serializada(f"{directory}/{filename}", request.user.pk)
        for filename in filenames
        if UPLOADED_IMAGE_PATTERN.fullmatch(f"{directory}/{filename}")
    ]
    images.sort(key=lambda image: image["name"].casefold())
    response = JsonResponse({"images": images})
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def subir_imagen(request, pk):
    get_object_or_404(Proyecto, pk=pk, propietario=request.user)
    uploads = request.FILES.getlist("images") or request.FILES.getlist("image")
    if not uploads:
        return JsonResponse({"error": "Selecciona al menos una imagen."}, status=400)
    if len(uploads) > 10:
        return JsonResponse({"error": "Puedes subir hasta 10 imágenes a la vez."}, status=400)

    validated = []
    for uploaded_file in uploads:
        extension, error = _validar_archivo_imagen(uploaded_file)
        if error:
            return JsonResponse({"error": error}, status=400)
        validated.append((uploaded_file, extension))

    directory = f"uploads/{request.user.pk}"
    images = []
    for uploaded_file, extension in validated:
        original_name = Path(uploaded_file.name).stem
        safe_name = slugify(original_name)[:60]
        filename = f"{uuid4().hex}_{safe_name}.{extension}" if safe_name else f"{uuid4().hex}.{extension}"
        relative_path = default_storage.save(
            f"{directory}/{filename}",
            uploaded_file,
        )
        image = _imagen_serializada(relative_path, request.user.pk)
        image["name"] = original_name or image["name"]
        images.append(image)
    return JsonResponse({"images": images}, status=201)


@login_required
@require_GET
def imagen_subida(request, owner_id, filename):
    relative_path = f"uploads/{owner_id}/{filename}"
    if owner_id != request.user.pk or not UPLOADED_IMAGE_PATTERN.fullmatch(relative_path):
        raise Http404
    try:
        image_file = default_storage.open(relative_path, "rb")
    except FileNotFoundError as error:
        raise Http404 from error
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    response = FileResponse(image_file, content_type=content_type)
    response["Cache-Control"] = "private, max-age=3600"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_GET
def audios_subidos(request):
    directory = f"audio_uploads/{request.user.pk}"
    try:
        _, filenames = default_storage.listdir(directory)
    except FileNotFoundError:
        filenames = []
    audios = [
        _audio_serializado(f"{directory}/{filename}", request.user.pk)
        for filename in filenames
        if UPLOADED_AUDIO_PATTERN.fullmatch(f"{directory}/{filename}")
    ]
    audios.sort(key=lambda audio: audio["name"].casefold())
    response = JsonResponse({"audios": audios})
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def subir_audio(request, pk):
    get_object_or_404(Proyecto, pk=pk, propietario=request.user)
    uploads = request.FILES.getlist("audios") or request.FILES.getlist("audio")
    if not uploads:
        return JsonResponse({"error": "Selecciona al menos un audio."}, status=400)
    if len(uploads) > 5:
        return JsonResponse({"error": "Puedes subir hasta 5 audios a la vez."}, status=400)

    validated = []
    for uploaded_file in uploads:
        extension, error = _validar_archivo_audio(uploaded_file)
        if error:
            return JsonResponse({"error": error}, status=400)
        validated.append((uploaded_file, extension))

    directory = f"audio_uploads/{request.user.pk}"
    audios = []
    for uploaded_file, extension in validated:
        original_name = Path(uploaded_file.name).stem
        safe_name = slugify(original_name)[:60]
        filename = f"{uuid4().hex}_{safe_name}.{extension}" if safe_name else f"{uuid4().hex}.{extension}"
        relative_path = default_storage.save(f"{directory}/{filename}", uploaded_file)
        audio = _audio_serializado(relative_path, request.user.pk)
        audio["name"] = original_name or audio["name"]
        audios.append(audio)
    return JsonResponse({"audios": audios}, status=201)


@login_required
@require_GET
def audio_subido(request, owner_id, filename):
    relative_path = f"audio_uploads/{owner_id}/{filename}"
    if owner_id != request.user.pk or not UPLOADED_AUDIO_PATTERN.fullmatch(relative_path):
        raise Http404
    try:
        audio_file = default_storage.open(relative_path, "rb")
    except FileNotFoundError as error:
        raise Http404 from error
    extension = Path(filename).suffix.lower().lstrip(".")
    response = FileResponse(audio_file, content_type=AUDIO_CONTENT_TYPES[extension])
    response["Cache-Control"] = "private, max-age=3600"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_GET
def plantillas_animacion(request):
    templates = [
        {"id": template.pk, "name": template.nombre, "data": template.datos}
        for template in PlantillaAnimacion.objects.filter(propietario=request.user)
    ]
    return JsonResponse({"templates": templates})


@login_required
@require_POST
def guardar_plantilla_animacion(request):
    nombre = request.POST.get("nombre", "").strip()
    if not nombre or len(nombre) > 100:
        return JsonResponse({"error": "Escribe un nombre de hasta 100 caracteres."}, status=400)
    try:
        datos = json.loads(request.POST.get("datos", ""))
        validar_plantilla_animacion(datos)
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError):
        return JsonResponse({"error": "La plantilla contiene datos inválidos."}, status=400)
    template, _ = PlantillaAnimacion.objects.update_or_create(
        propietario=request.user,
        nombre=nombre,
        defaults={"datos": datos},
    )
    return JsonResponse({
        "template": {"id": template.pk, "name": template.nombre, "data": template.datos},
    }, status=201)


@login_required
@require_POST
def eliminar_plantilla_animacion(request, pk):
    template = get_object_or_404(PlantillaAnimacion, pk=pk, propietario=request.user)
    template.delete()
    return JsonResponse({"deleted": True})


@login_required
@require_GET
def estado_ia(request, pk):
    proyecto = get_object_or_404(Proyecto, pk=pk, propietario=request.user)
    response = JsonResponse(_estado_ia(request.user, proyecto))
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def generar_ia(request, pk):
    proyecto = get_object_or_404(Proyecto, pk=pk, propietario=request.user)
    if not gemini_service.is_configured():
        return JsonResponse({
            "error": "Gemini aún no está configurado. Agrega GEMINI_API_KEY al archivo .env y reinicia Django."
        }, status=503)
    _, daily_limit = _rol_y_limite_ia(request.user)
    if _uso_ia_hoy(request.user) >= daily_limit:
        return JsonResponse({
            "error": "Alcanzaste el límite diario de IA.",
            "state": _estado_ia(request.user, proyecto),
        }, status=429)

    try:
        payload = _json_payload(request)
        action = payload.get("action")
        if action == "presentation":
            topic = _texto_requerido(payload, "topic", "El tema", 5000, 3)
            audience = _texto_requerido(payload, "audience", "La audiencia", 120)
            style = payload.get("style", "academico")
            if style not in AI_STYLES:
                raise ValueError("El estilo seleccionado no es válido.")
            try:
                slide_count = int(payload.get("slide_count", 5))
            except (TypeError, ValueError) as error:
                raise ValueError("El número de diapositivas no es válido.") from error
            if not 1 <= slide_count <= 20:
                raise ValueError("Puedes generar entre 1 y 20 diapositivas.")
            model = settings.GEMINI_TEXT_MODEL
            result = gemini_service.generate_presentation(topic, slide_count, audience, style)
            _registrar_uso_ia(request.user, proyecto, UsoIA.Accion.PRESENTACION, model, result.usage)
            return JsonResponse({
                "type": "presentation",
                "presentation": result.data,
                "usage": _uso_serializado(result.usage),
                "state": _estado_ia(request.user, proyecto),
            })

        if action == "text":
            source = _texto_requerido(payload, "source", "El contenido", 15000)
            text_action = payload.get("text_action")
            if text_action not in gemini_service.TEXT_ACTIONS:
                raise ValueError("La tarea de texto no es válida.")
            instruction = payload.get("instruction", "")
            if not isinstance(instruction, str) or len(instruction.strip()) > 2000:
                raise ValueError("Las indicaciones adicionales admiten hasta 2000 caracteres.")
            model = settings.GEMINI_TEXT_MODEL
            result = gemini_service.transform_text(text_action, source, instruction.strip())
            _registrar_uso_ia(request.user, proyecto, UsoIA.Accion.TEXTO, model, result.usage)
            return JsonResponse({
                "type": "text",
                "text": result.data,
                "usage": _uso_serializado(result.usage),
                "state": _estado_ia(request.user, proyecto),
            })

        if action == "image":
            prompt = _texto_requerido(payload, "prompt", "La descripción", 2000, 3)
            image_type = payload.get("image_type", "ilustracion")
            aspect_ratio = payload.get("aspect_ratio", "16:9")
            if image_type not in AI_IMAGE_TYPES or aspect_ratio not in AI_ASPECT_RATIOS:
                raise ValueError("Las opciones de imagen no son válidas.")
            model = settings.GEMINI_IMAGE_MODEL
            result = gemini_service.generate_image(prompt, image_type, aspect_ratio)
            image = _guardar_imagen_ia(result.data, request.user)
            _registrar_uso_ia(request.user, proyecto, UsoIA.Accion.IMAGEN, model, result.usage)
            return JsonResponse({
                "type": "image",
                "image": image,
                "usage": _uso_serializado(result.usage),
                "state": _estado_ia(request.user, proyecto),
            }, status=201)

        raise ValueError("Selecciona una herramienta de IA válida.")
    except ValueError as error:
        return JsonResponse({"error": str(error)}, status=400)
    except gemini_service.GeminiNotConfigured:
        return JsonResponse({
            "error": "No se pudo iniciar Gemini. Revisa la clave y las dependencias del servidor."
        }, status=503)
    except gemini_service.GeminiServiceError as error:
        action_value = {
            "presentation": UsoIA.Accion.PRESENTACION,
            "text": UsoIA.Accion.TEXTO,
            "image": UsoIA.Accion.IMAGEN,
        }.get(locals().get("action"))
        if action_value:
            model = settings.GEMINI_IMAGE_MODEL if action_value == UsoIA.Accion.IMAGEN else settings.GEMINI_TEXT_MODEL
            _registrar_uso_ia(request.user, proyecto, action_value, model, error=type(error).__name__)
        logger.warning("Falló una solicitud de Gemini (%s).", type(error).__name__)
        return JsonResponse({"error": str(error)}, status=502)


def _enqueue_conversion(job):
    try:
        async_result = convertir_documento.delay(str(job.pk))
    except Exception:
        logger.exception("No se pudo encolar la conversión %s.", job.pk)
        TrabajoConversion.objects.filter(pk=job.pk).update(
            estado=TrabajoConversion.Estado.FALLIDO,
            progreso=100,
            mensaje="No se pudo iniciar la conversión",
            error="El servicio de tareas no está disponible. Intenta de nuevo.",
            terminado=timezone.now(),
        )
        return False
    TrabajoConversion.objects.filter(pk=job.pk).update(celery_task_id=async_result.id or "")
    return True


@login_required
@require_POST
def subir_documento_ia(request, pk):
    proyecto = get_object_or_404(Proyecto, pk=pk, propietario=request.user)
    if not gemini_service.is_configured():
        return JsonResponse({
            "error": "Gemini aún no está configurado. Agrega GEMINI_API_KEY al archivo .env."
        }, status=503)
    _, daily_limit = _rol_y_limite_ia(request.user)
    if _uso_ia_hoy(request.user) >= daily_limit:
        return JsonResponse({"error": "Alcanzaste el límite diario de IA."}, status=429)

    uploaded_file = request.FILES.get("document")
    try:
        document_type = validate_document(uploaded_file)
        slide_count = int(request.POST.get("slide_count", "5"))
        if not 1 <= slide_count <= 20:
            raise ValueError("Puedes generar entre 1 y 20 diapositivas.")
        audience = request.POST.get("audience", "").strip()
        if not 1 <= len(audience) <= 120:
            raise ValueError("La audiencia es obligatoria y admite hasta 120 caracteres.")
        style = request.POST.get("style", "academico")
        if style not in AI_STYLES:
            raise ValueError("El estilo seleccionado no es válido.")
    except (DocumentValidationError, TypeError, ValueError) as error:
        return JsonResponse({"error": str(error)}, status=400)

    with transaction.atomic():
        document = DocumentoFuente.objects.create(
            usuario=request.user,
            proyecto=proyecto,
            archivo=uploaded_file,
            nombre_original=Path(uploaded_file.name).name[:255],
            tipo=document_type,
            tamano=uploaded_file.size,
        )
        job = TrabajoConversion.objects.create(
            usuario=request.user,
            proyecto=proyecto,
            documento=document,
            numero_diapositivas=slide_count,
            audiencia=audience,
            estilo=style,
        )
    queued = _enqueue_conversion(job)
    job.refresh_from_db()
    return JsonResponse(
        {"conversion": _trabajo_conversion_serializado(job)},
        status=202 if queued else 503,
    )


@login_required
@require_GET
def estado_conversion(request, pk, job_id):
    proyecto = get_object_or_404(Proyecto, pk=pk, propietario=request.user)
    job = get_object_or_404(
        TrabajoConversion.objects.select_related("documento"),
        pk=job_id,
        proyecto=proyecto,
        usuario=request.user,
    )
    response = JsonResponse({"conversion": _trabajo_conversion_serializado(job)})
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def cancelar_conversion(request, pk, job_id):
    proyecto = get_object_or_404(Proyecto, pk=pk, propietario=request.user)
    job = get_object_or_404(
        TrabajoConversion.objects.select_related("documento"),
        pk=job_id,
        proyecto=proyecto,
        usuario=request.user,
    )
    if job.estado in {TrabajoConversion.Estado.PENDIENTE, TrabajoConversion.Estado.PROCESANDO}:
        job.estado = TrabajoConversion.Estado.CANCELADO
        job.progreso = 100
        job.mensaje = "Conversión cancelada"
        job.error = ""
        job.cancelacion_solicitada = True
        job.terminado = timezone.now()
        job.save(update_fields=[
            "estado", "progreso", "mensaje", "error", "cancelacion_solicitada", "terminado",
        ])
    return JsonResponse({"conversion": _trabajo_conversion_serializado(job)})


@login_required
@require_POST
def reintentar_conversion(request, pk, job_id):
    proyecto = get_object_or_404(Proyecto, pk=pk, propietario=request.user)
    job = get_object_or_404(
        TrabajoConversion.objects.select_related("documento"),
        pk=job_id,
        proyecto=proyecto,
        usuario=request.user,
    )
    if job.estado not in {TrabajoConversion.Estado.FALLIDO, TrabajoConversion.Estado.CANCELADO}:
        return JsonResponse({"error": "Solo puedes reintentar una conversión fallida o cancelada."}, status=409)
    _, daily_limit = _rol_y_limite_ia(request.user)
    if _uso_ia_hoy(request.user) >= daily_limit:
        return JsonResponse({"error": "Alcanzaste el límite diario de IA."}, status=429)
    job.estado = TrabajoConversion.Estado.PENDIENTE
    job.progreso = 0
    job.mensaje = "En espera"
    job.error = ""
    job.resultado = None
    job.cancelacion_solicitada = False
    job.terminado = None
    job.intentos += 1
    job.save(update_fields=[
        "estado", "progreso", "mensaje", "error", "resultado",
        "cancelacion_solicitada", "terminado", "intentos",
    ])
    queued = _enqueue_conversion(job)
    job.refresh_from_db()
    return JsonResponse(
        {"conversion": _trabajo_conversion_serializado(job)},
        status=202 if queued else 503,
    )


@login_required
@require_GET
def exportar(request, pk, formato):
    proyecto = get_object_or_404(Proyecto, pk=pk, propietario=request.user)
    diapositivas = _diapositivas(proyecto)
    try:
        if formato == "pdf":
            data = exportar_pdf(proyecto.nombre, diapositivas)
            content_type, extension = "application/pdf", "pdf"
        elif formato == "pptx":
            data = exportar_pptx(proyecto.nombre, diapositivas)
            content_type, extension = (
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "pptx",
            )
        elif formato == "png":
            data = exportar_imagenes(diapositivas)
            content_type, extension = "application/zip", "zip"
        elif formato in {"mp4", "gif"}:
            resolution_text = request.GET.get("resolucion", "1080")
            if resolution_text not in {"1080", "720"}:
                return HttpResponse("La resolución debe ser 1080 o 720.", status=400)
            resolution = int(resolution_text)
            if formato == "mp4":
                data = exportar_video(diapositivas, resolution)
                content_type, extension = "video/mp4", "mp4"
            else:
                data = exportar_gif(diapositivas, resolution)
                content_type, extension = "image/gif", "gif"
        else:
            raise Http404
    except (OSError, ValueError, RuntimeError):
        logger.exception("No se pudo exportar el proyecto %s en formato %s", proyecto.pk, formato)
        return HttpResponse("No se pudo exportar. Verifica que las imágenes de la presentación sigan disponibles.", status=400)
    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="presentacion.{extension}"'
    return response
