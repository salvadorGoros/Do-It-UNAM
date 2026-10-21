from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
import editor.validators


def crear_roles(apps, schema_editor):
    Rol = apps.get_model("editor", "Rol")
    for clave, nombre, cuota in [
        ("alumno", "Alumno", 10_000),
        ("docente", "Docente", 50_000),
        ("administrador", "Administrador", 200_000),
    ]:
        Rol.objects.update_or_create(
            clave=clave,
            defaults={"nombre": nombre, "cuota_tokens_dia": cuota},
        )


def eliminar_roles(apps, schema_editor):
    apps.get_model("editor", "Rol").objects.filter(
        clave__in=["alumno", "docente", "administrador"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("editor", "0008_usoia"),
    ]

    operations = [
        migrations.CreateModel(
            name="Rol",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("clave", models.CharField(choices=[("alumno", "Alumno"), ("docente", "Docente"), ("administrador", "Administrador")], max_length=20, unique=True)),
                ("nombre", models.CharField(max_length=30, unique=True)),
                ("cuota_tokens_dia", models.PositiveIntegerField(default=10000, help_text="Límite total diario para operaciones de IA.", validators=[django.core.validators.MinValueValidator(0)])),
            ],
            options={"ordering": ["pk"]},
        ),
        migrations.CreateModel(
            name="PerfilUsuario",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("numero_cuenta", models.CharField(blank=True, max_length=15, null=True, unique=True, validators=[editor.validators.validar_numero_cuenta])),
                ("correo_institucional", models.EmailField(max_length=150, unique=True, validators=[editor.validators.validar_correo_institucional])),
                ("fecha_registro", models.DateTimeField(auto_now_add=True)),
                ("rol", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="perfiles", to="editor.rol")),
                ("usuario", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="perfil_institucional", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["usuario__username"]},
        ),
        migrations.RunPython(crear_roles, eliminar_roles),
    ]
