import django.core.validators
import django.db.models.deletion
import editor.scene
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("editor", "0006_proyecto_diapositivas"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="proyecto",
            name="duracion_frames",
            field=models.PositiveIntegerField(
                default=300,
                validators=[
                    django.core.validators.MinValueValidator(30),
                    django.core.validators.MaxValueValidator(108000),
                ],
            ),
        ),
        migrations.CreateModel(
            name="PlantillaAnimacion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombre", models.CharField(max_length=100)),
                ("datos", models.JSONField(validators=[editor.scene.validar_plantilla_animacion])),
                ("creado", models.DateTimeField(auto_now_add=True)),
                ("modificado", models.DateTimeField(auto_now=True)),
                (
                    "propietario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="plantillas_animacion",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["nombre", "pk"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("propietario", "nombre"),
                        name="plantilla_animacion_nombre_por_usuario",
                    ),
                ],
            },
        ),
    ]
