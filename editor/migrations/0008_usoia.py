from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("editor", "0007_plantillaanimacion_ampliar_duracion"),
    ]

    operations = [
        migrations.CreateModel(
            name="UsoIA",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("accion", models.CharField(choices=[("presentacion", "Presentación"), ("texto", "Texto"), ("imagen", "Imagen")], max_length=20)),
                ("modelo", models.CharField(max_length=100)),
                ("tokens_entrada", models.PositiveIntegerField(default=0)),
                ("tokens_salida", models.PositiveIntegerField(default=0)),
                ("tokens_totales", models.PositiveIntegerField(default=0)),
                ("exitoso", models.BooleanField(default=True)),
                ("categoria_error", models.CharField(blank=True, default="", max_length=60)),
                ("creado", models.DateTimeField(auto_now_add=True)),
                ("proyecto", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="usos_ia", to="editor.proyecto")),
                ("usuario", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="usos_ia", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-creado", "-pk"]},
        ),
        migrations.AddIndex(
            model_name="usoia",
            index=models.Index(fields=["usuario", "creado"], name="editor_uso_usuario_fecha"),
        ),
    ]
