from django.db import migrations, models

import editor.scene


def inicializar_diapositivas(apps, schema_editor):
    Proyecto = apps.get_model("editor", "Proyecto")
    for proyecto in Proyecto.objects.using(schema_editor.connection.alias).all().iterator():
        proyecto.diapositivas = [{
            "id": f"slide-{proyecto.pk}-1",
            "objetos": proyecto.objetos,
            "fondo": proyecto.fondo,
            "duracion_frames": proyecto.duracion_frames,
        }]
        proyecto.save(update_fields=["diapositivas"])


class Migration(migrations.Migration):
    dependencies = [("editor", "0005_proyecto_fondo")]
    operations = [
        migrations.AddField(
            model_name="proyecto",
            name="diapositivas",
            field=models.JSONField(blank=True, default=list, validators=[editor.scene.validar_diapositivas]),
        ),
        migrations.RunPython(inicializar_diapositivas, migrations.RunPython.noop),
    ]
