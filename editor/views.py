import json
import logging
import mimetypes
import re
from pathlib import Path
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from PIL import Image, UnidentifiedImageError

from .forms import EditorForm, ProyectoForm, RegistroForm
from .exports import exportar_imagenes, exportar_pdf, exportar_pptx
from .models import Proyecto
from .scene import UPLOADED_IMAGE_PATTERN, imagenes_disponibles, imagenes_pertenecen_usuario

logger = logging.getLogger(__name__)
MAX_UPLOADED_IMAGE_SIZE = 15 * 1024 * 1024
MAX_UPLOADED_IMAGE_PIXELS = 40_000_000
IMAGE_FORMATS = {
    "PNG": "png",
    "JPEG": "jpg",
    "WEBP": "webp",
}


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
        "duracion_frames": proyecto.duracion_frames,
    }]


def _imagenes_validas_para_usuario(form, usuario):
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


@require_http_methods(["GET", "POST"])
def registro(request):
    if request.user.is_authenticated:
        return redirect("editor:index")

    form = RegistroForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario = form.save()
        login(request, usuario)
        return redirect("editor:index")
    return render(request, "registration/registro.html", {"form": form})


@login_required
@require_GET
def index(request):
    return render(request, "editor/proyectos.html", {
        "proyectos": Proyecto.objects.filter(propietario=request.user),
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
        "proyectos": Proyecto.objects.filter(propietario=request.user),
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
            if _imagenes_validas_para_usuario(form, request.user):
                form.save()
                return JsonResponse({"saved": True})
        return JsonResponse({"errors": form.errors.get_json_data()}, status=400)
    if form.is_valid():
        if _imagenes_validas_para_usuario(form, request.user):
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
        else:
            raise Http404
    except (OSError, ValueError):
        logger.exception("No se pudo exportar el proyecto %s en formato %s", proyecto.pk, formato)
        return HttpResponse("No se pudo exportar. Verifica que las imágenes de la presentación sigan disponibles.", status=400)
    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="presentacion.{extension}"'
    return response
