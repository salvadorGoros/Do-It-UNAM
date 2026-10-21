import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Sum
from django.utils import timezone

from . import gemini as gemini_service
from .documents import DocumentValidationError, extract_pptx_text
from .models import TrabajoConversion, UsoIA


logger = logging.getLogger(__name__)


def _quota_available(user):
    now = timezone.localtime()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    used = UsoIA.objects.filter(usuario=user, creado__gte=start).aggregate(
        total=Sum("tokens_totales")
    )["total"] or 0
    try:
        limit = user.perfil_institucional.cuota_tokens_dia
    except ObjectDoesNotExist:
        limit = settings.GEMINI_DAILY_TOKEN_LIMIT
    return used < limit


def _record_usage(job, usage=None, error=""):
    UsoIA.objects.create(
        usuario=job.usuario,
        proyecto=job.proyecto,
        accion=UsoIA.Accion.DOCUMENTO,
        modelo=settings.GEMINI_TEXT_MODEL,
        tokens_entrada=usage.input_tokens if usage else 0,
        tokens_salida=usage.output_tokens if usage else 0,
        tokens_totales=usage.total_tokens if usage else 0,
        exitoso=not error,
        categoria_error=error,
    )


def _is_cancelled(job_id):
    return TrabajoConversion.objects.filter(
        pk=job_id,
        cancelacion_solicitada=True,
    ).exists()


def _fail(job, message, category):
    TrabajoConversion.objects.filter(pk=job.pk).update(
        estado=TrabajoConversion.Estado.FALLIDO,
        progreso=100,
        mensaje="No se pudo completar la conversión",
        error=message,
        terminado=timezone.now(),
    )
    _record_usage(job, error=category)


@shared_task(bind=True, name="editor.convertir_documento")
def convertir_documento(self, job_id):
    try:
        job = TrabajoConversion.objects.select_related(
            "documento", "usuario", "proyecto", "usuario__perfil_institucional__rol"
        ).get(pk=job_id)
    except TrabajoConversion.DoesNotExist:
        return {"state": "missing"}

    if job.cancelacion_solicitada or job.estado == TrabajoConversion.Estado.CANCELADO:
        return {"state": "cancelled"}

    if not _quota_available(job.usuario):
        _fail(job, "Alcanzaste el límite diario de IA.", "DailyQuotaExceeded")
        return {"state": "failed"}

    TrabajoConversion.objects.filter(pk=job.pk).update(
        estado=TrabajoConversion.Estado.PROCESANDO,
        progreso=10,
        mensaje="Preparando el documento",
        error="",
        iniciado=timezone.now(),
        celery_task_id=self.request.id or job.celery_task_id,
    )

    try:
        job.documento.archivo.open("rb")
        if job.documento.tipo == job.documento.Tipo.PDF:
            TrabajoConversion.objects.filter(pk=job.pk).update(
                progreso=30,
                mensaje="Gemini está analizando el PDF",
            )
            result = gemini_service.generate_presentation_from_pdf(
                job.documento.archivo.file,
                job.numero_diapositivas,
                job.audiencia,
                job.estilo,
            )
        else:
            content = extract_pptx_text(job.documento.archivo.file)
            if _is_cancelled(job.pk):
                return {"state": "cancelled"}
            TrabajoConversion.objects.filter(pk=job.pk).update(
                progreso=40,
                mensaje="Gemini está organizando la presentación",
            )
            result = gemini_service.generate_presentation_from_extracted_document(
                content,
                job.numero_diapositivas,
                job.audiencia,
                job.estilo,
            )
        if _is_cancelled(job.pk):
            return {"state": "cancelled"}
        TrabajoConversion.objects.filter(pk=job.pk).update(
            estado=TrabajoConversion.Estado.COMPLETADO,
            progreso=100,
            mensaje="Conversión lista para agregar al proyecto",
            error="",
            resultado=result.data,
            terminado=timezone.now(),
        )
        _record_usage(job, result.usage)
        return {"state": "completed"}
    except (DocumentValidationError, gemini_service.GeminiServiceError) as error:
        _fail(job, str(error), type(error).__name__)
        logger.warning("Falló la conversión %s (%s).", job.pk, type(error).__name__)
        return {"state": "failed"}
    except gemini_service.GeminiNotConfigured:
        _fail(job, "Gemini no está configurado en el servidor.", "GeminiNotConfigured")
        return {"state": "failed"}
    except SoftTimeLimitExceeded:
        _fail(job, "La conversión excedió el tiempo permitido.", "SoftTimeLimitExceeded")
        return {"state": "failed"}
    except Exception:
        _fail(job, "Ocurrió un error interno durante la conversión.", "UnexpectedError")
        logger.exception("Error inesperado al convertir el documento %s.", job.pk)
        return {"state": "failed"}
    finally:
        try:
            job.documento.archivo.close()
        except Exception:
            pass
