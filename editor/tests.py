import json
import tempfile
from io import BytesIO
from zipfile import ZipFile
from copy import deepcopy
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from pptx import Presentation

from .exports import exportar_imagenes
from .models import Proyecto
from .scene import imagenes_disponibles, validar_diapositivas


class ProyectoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user("ana", password="Prueba-local-123!")
        cls.otro = get_user_model().objects.create_user("luis", password="Prueba-local-456!")
        cls.proyecto = Proyecto.objects.create(nombre="Proyecto de Ana", propietario=cls.usuario)
        cls.ajeno = Proyecto.objects.create(nombre="Privado de Luis", propietario=cls.otro)

    def setUp(self):
        self.client.force_login(self.usuario)
        self.detalle = reverse("editor:detalle", args=[self.proyecto.pk])
        self.guardar = reverse("editor:guardar", args=[self.proyecto.pk])
        self.crear = reverse("editor:crear")

    def test_rutas_requieren_sesion(self):
        self.client.logout()
        for url, method in [("/", "get"), (self.detalle, "get"), (self.crear, "post"), (self.guardar, "post")]:
            with self.subTest(url=url):
                response = getattr(self.client, method)(url)
                self.assertRedirects(response, reverse("login") + "?next=" + url)

    def test_login_y_logout_solo_post(self):
        self.client.logout()
        response = self.client.post(reverse("login"), {"username": "ana", "password": "incorrecta"})
        self.assertTrue(response.context["form"].errors)
        response = self.client.post(reverse("login"), {
            "username": "ana", "password": "Prueba-local-123!", "next": self.detalle,
        })
        self.assertRedirects(response, self.detalle)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_no_redirige_a_sitio_externo(self):
        self.client.logout()
        response = self.client.post(reverse("login"), {
            "username": "ana", "password": "Prueba-local-123!", "next": "https://example.com/",
        })
        self.assertRedirects(response, "/")

    def test_registro_crea_usuario_inicia_sesion_y_separa_proyectos(self):
        self.client.logout()
        url = reverse("editor:registro")
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {
            "username": "mariana",
            "password1": "Registro-Segura-456!",
            "password2": "Registro-Segura-456!",
        })
        self.assertRedirects(response, reverse("editor:index"))

        usuario = get_user_model().objects.get(username="mariana")
        self.assertTrue(usuario.check_password("Registro-Segura-456!"))
        self.assertIn("_auth_user_id", self.client.session)

        listado = self.client.get(reverse("editor:index"))
        self.assertNotContains(listado, self.proyecto.nombre)
        self.assertNotContains(listado, self.ajeno.nombre)
        creado = self.client.post(reverse("editor:crear"), {"nombre": "Proyecto de Mariana"})
        proyecto = Proyecto.objects.get(nombre="Proyecto de Mariana")
        self.assertEqual(proyecto.propietario, usuario)
        self.assertRedirects(creado, reverse("editor:detalle", args=[proyecto.pk]))

    def test_registro_rechaza_usuario_repetido_y_contraseñas_distintas(self):
        self.client.logout()
        url = reverse("editor:registro")
        datos = {
            "username": "ana",
            "password1": "Registro-Segura-456!",
            "password2": "Registro-Segura-456!",
        }
        response = self.client.post(url, datos)
        self.assertEqual(response.status_code, 200)
        self.assertIn("username", response.context["form"].errors)
        self.assertEqual(get_user_model().objects.filter(username="ana").count(), 1)

        datos["username"] = "nueva"
        datos["password2"] = "Otra-Segura-456!"
        response = self.client.post(url, datos)
        self.assertEqual(response.status_code, 200)
        self.assertIn("password2", response.context["form"].errors)
        self.assertFalse(get_user_model().objects.filter(username="nueva").exists())

    def test_listado_solo_propios_y_orden_modificacion(self):
        nuevo = Proyecto.objects.create(nombre="Otro de Ana", propietario=self.usuario)
        Proyecto.objects.filter(pk=self.proyecto.pk).update(modificado=timezone.now() - timedelta(days=1))
        response = self.client.get("/")
        self.assertQuerySetEqual(response.context["proyectos"], [nuevo, self.proyecto])
        self.assertNotContains(response, self.ajeno.nombre)
        self.client.post(self.guardar, {"nombre": "Ahora más reciente"})
        self.assertEqual(self.client.get("/").context["proyectos"][0].pk, self.proyecto.pk)

    def test_estado_vacio(self):
        self.usuario.proyectos.all().delete()
        self.assertContains(self.client.get("/"), "Aún no tienes proyectos")

    def test_logo_enlace_y_favicon_en_editor_y_proyectos(self):
        logo = "/static/editor/images/logo.png?v=4"
        proyectos = self.client.get("/")
        editor = self.client.get(self.detalle)
        favicon = '<link rel="icon" type="image/png" href="/static/editor/images/favicon.png?v=2">'
        self.assertContains(proyectos, favicon)
        self.assertContains(proyectos, f'<img class="brand-logo" src="{logo}" alt="DO IT UNAM" width="52" height="52">')
        self.assertContains(editor, favicon)
        self.assertContains(editor, f'<img src="{logo}" alt="DO IT UNAM" width="52" height="52">')
        self.assertContains(editor, 'href="/" class="projects-logo" aria-label="Regresar a Mis proyectos"')

    def test_crear_ignora_propietario_enviado_y_permite_repetidos(self):
        for _ in range(2):
            response = self.client.post(self.crear, {"nombre": "  Diseño nuevo  ", "propietario": self.otro.pk})
            proyecto = Proyecto.objects.filter(propietario=self.usuario).first()
            self.assertEqual(proyecto.nombre, "Diseño nuevo")
            self.assertRedirects(response, reverse("editor:detalle", args=[proyecto.pk]))
        self.assertEqual(self.usuario.proyectos.filter(nombre="Diseño nuevo").count(), 2)

    def test_guardar_persiste_y_muestra_confirmacion(self):
        creado = self.proyecto.creado
        response = self.client.post(self.guardar, {"nombre": "  Nuevo nombre  ", "propietario": self.otro.pk}, follow=True)
        self.assertContains(response, "Proyecto guardado")
        self.proyecto.refresh_from_db()
        self.assertEqual(self.proyecto.nombre, "Nuevo nombre")
        self.assertEqual(self.proyecto.propietario, self.usuario)
        self.assertEqual(self.proyecto.creado, creado)
        self.assertContains(self.client.get(self.detalle), 'value="Nuevo nombre"')

    def test_nombres_invalidos_no_escriben_y_conservan_entrada(self):
        for nombre in ["", "   ", "x" * 151]:
            for url in [self.crear, self.guardar]:
                with self.subTest(nombre=nombre, url=url):
                    cantidad = Proyecto.objects.count()
                    response = self.client.post(url, {"nombre": nombre})
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("nombre", response.context["form"].errors)
                    self.assertEqual(response.context["form"]["nombre"].value(), nombre)
                    self.assertEqual(Proyecto.objects.count(), cantidad)
                    self.proyecto.refresh_from_db()
                    self.assertEqual(self.proyecto.nombre, "Proyecto de Ana")

    def test_limite_y_escape_html(self):
        self.assertEqual(self.client.post(self.guardar, {"nombre": "á" * 150}).status_code, 302)
        response = self.client.post(self.guardar, {"nombre": '<script>alert("x")</script>'}, follow=True)
        self.assertNotContains(response, '<script>alert("x")</script>')
        self.assertContains(response, "&lt;script&gt;")

    def test_ajenos_e_inexistentes_devuelven_404(self):
        for pk in [self.ajeno.pk, 99999]:
            with self.subTest(pk=pk):
                self.assertEqual(self.client.get(reverse("editor:detalle", args=[pk])).status_code, 404)
                self.assertEqual(self.client.post(reverse("editor:guardar", args=[pk]), {"nombre": "Intrusión"}).status_code, 404)
        self.ajeno.refresh_from_db()
        self.assertEqual(self.ajeno.nombre, "Privado de Luis")

    def test_get_no_modifica_proyectos(self):
        estado = list(Proyecto.objects.values())
        for url in [self.crear, self.guardar]:
            self.assertEqual(self.client.get(url, {"nombre": "Cambio"}).status_code, 405)
        self.client.get("/")
        self.client.get(self.detalle)
        self.assertEqual(list(Proyecto.objects.values()), estado)

    def test_csrf_en_creacion_guardado_logout_y_login(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.usuario)
        for url in [self.crear, self.guardar, reverse("logout"), reverse("editor:registro")]:
            self.assertEqual(client.post(url, {"nombre": "Sin token"}).status_code, 403)
        client.get(self.detalle)
        token = client.cookies["csrftoken"].value
        response = client.post(self.guardar, {"nombre": "Con token", "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 302)
        client.logout()
        self.assertEqual(client.post(reverse("login"), {"username": "ana", "password": "Prueba-local-123!"}).status_code, 403)

    def cuadro(self, **changes):
        obj = {"id": "cuadro-1", "texto": "Hola\nmundo", "x": 50, "y": 60,
                "ancho": 300, "alto": 150, "fuente": "Poppins", "tamano": 36,
                "color": "#ffffff", "negrita": False, "cursiva": False,
                "subrayado": False, "alineacion": "center", **changes}
        obj.setdefault("fotogramas", [dict(frame=0, x=obj["x"], y=obj["y"], giro=0, opacidad=1, interpolacion="lineal")])
        return obj

    def test_proyecto_nuevo_sin_textos_fijos(self):
        self.assertEqual(self.proyecto.objetos, [])
        response = self.client.get(self.detalle)
        self.assertContains(response, 'id="text-tool"')
        self.assertNotContains(response, 'id="id_titulo"')

    def test_galerias_muestran_imagenes_disponibles(self):
        response = self.client.get(self.detalle)
        elementos = imagenes_disponibles("elementos")
        fondos = imagenes_disponibles("fondos")
        self.assertTrue(elementos)
        self.assertTrue(fondos)
        self.assertEqual(sum(len(grupo["assets"]) for grupo in response.context["elementos"]), len(elementos))
        self.assertEqual(sum(len(grupo["assets"]) for grupo in response.context["fondos"]), len(fondos))
        self.assertContains(response, f'data-asset-path="elementos/{elementos[0]}"')
        self.assertContains(response, f'data-asset-path="fondos/{fondos[0]}"')
        self.assertIn("Personajes de la FESC", [grupo["categoria"] for grupo in response.context["elementos"]])

    def test_subir_imagen_persiste_en_biblioteca_privada(self):
        image_data = BytesIO()
        Image.new("RGB", (12, 8), "red").save(image_data, format="PNG")
        image_data.seek(0)
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse("editor:subir_imagen", args=[self.proyecto.pk]),
                {"images": SimpleUploadedFile("mifoto.png", image_data.getvalue(), content_type="image/png")},
            )
            self.assertEqual(response.status_code, 201)
            uploaded = response.json()["images"][0]
            self.assertRegex(
                uploaded["path"],
                rf"^uploads/{self.usuario.pk}/[a-f0-9]{{32}}(?:_[a-zA-Z0-9_-]{{1,60}})?\.png$",
            )
            library = self.client.get(reverse("editor:imagenes_subidas"))
            self.assertEqual(library["Cache-Control"], "private, no-store")
            self.assertEqual(library.json()["images"], [uploaded])
            image_response = self.client.get(uploaded["url"])
            self.assertEqual(image_response.status_code, 200)
            self.assertEqual(image_response["Content-Type"], "image/png")
            self.assertEqual(b"".join(image_response.streaming_content), image_data.getvalue())

            objeto = self.cuadro(tipo="imagen", imagen=uploaded["path"], texto="")
            exported = exportar_imagenes([{
                "objetos": [objeto],
                "fondo": "",
                "color_fondo": "#ffffff",
            }])
            with ZipFile(BytesIO(exported)) as archive:
                with Image.open(BytesIO(archive.read("diapositiva-1.png"))) as slide_image:
                    self.assertEqual(slide_image.size, (1600, 900))

            otro_cliente = Client()
            otro_cliente.force_login(self.otro)
            self.assertEqual(otro_cliente.get(uploaded["url"]).status_code, 404)
            self.client.logout()
            self.assertEqual(self.client.get(uploaded["url"]).status_code, 302)

    def test_subida_rechaza_archivos_que_no_sean_imagenes(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse("editor:subir_imagen", args=[self.proyecto.pk]),
                {"images": SimpleUploadedFile("imagen.png", b"esto no es una imagen", content_type="image/png")},
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("imagen válida", response.json()["error"])
            self.assertEqual(self.client.get(reverse("editor:imagenes_subidas")).json()["images"], [])

    def test_guardado_rechaza_imagen_subida_de_otro_usuario(self):
        image_data = BytesIO()
        Image.new("RGB", (4, 4), "blue").save(image_data, format="PNG")
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            otro_cliente = Client()
            otro_cliente.force_login(self.otro)
            upload = otro_cliente.post(
                reverse("editor:subir_imagen", args=[self.ajeno.pk]),
                {"images": SimpleUploadedFile("ajena.png", image_data.getvalue(), content_type="image/png")},
            )
            image_path = upload.json()["images"][0]["path"]
            objeto = self.cuadro(tipo="imagen", imagen=image_path, texto="")
            response = self.client.post(self.guardar, {"nombre": "Imagen ajena", "objetos": json.dumps([objeto])})
            self.assertEqual(response.status_code, 200)
            self.assertIn("no pertenece", response.context["form"].errors["diapositivas"][0])
            self.proyecto.refresh_from_db()
            self.assertEqual(self.proyecto.objetos, [])

    def test_elementos_y_fondos_se_guardan_y_recuperan(self):
        elemento = self.cuadro(tipo="imagen", imagen=f"elementos/{imagenes_disponibles('elementos')[0]}", texto="")
        fondo = f"fondos/{imagenes_disponibles('fondos')[0]}"
        response = self.client.post(self.guardar, {
            "nombre": "Escena con imágenes",
            "objetos": json.dumps([elemento]),
            "fondo": fondo,
        })
        self.assertRedirects(response, self.detalle)
        self.proyecto.refresh_from_db()
        self.assertEqual(self.proyecto.objetos, [elemento])
        self.assertEqual(self.proyecto.fondo, fondo)
        editor = self.client.get(self.detalle)
        self.assertEqual(editor.context["form"]["fondo"].value(), fondo)
        self.assertContains(editor, f'data-asset-path="{elemento["imagen"]}"')

    def test_diapositivas_guardan_contenido_independiente_y_duracion(self):
        primero = self.cuadro(texto="Primera hoja")
        segundo = self.cuadro(id="cuadro-2", texto="Segunda hoja", x=300)
        slides = [
            {"id": "slide-1", "objetos": [primero], "fondo": "", "color_fondo": "#dbeafe", "duracion_frames": 300},
            {"id": "slide-2", "objetos": [segundo], "fondo": "", "duracion_frames": 600},
        ]
        response = self.client.post(self.guardar, {
            "nombre": "Presentación",
            "objetos": json.dumps([primero]),
            "fondo": "",
            "duracion_frames": 300,
            "diapositivas": json.dumps(slides),
            "diapositiva_activa": 0,
        })
        self.assertRedirects(response, self.detalle)
        self.proyecto.refresh_from_db()
        self.assertEqual(self.proyecto.diapositivas, slides)
        self.assertEqual(self.proyecto.objetos, [primero])

    def test_color_de_diapositiva_es_opcional_compatible_y_validado(self):
        slide = {"id": "slide-1", "objetos": [], "fondo": "", "duracion_frames": 300}
        validar_diapositivas([slide])
        validar_diapositivas([{**slide, "color_fondo": "#dbeafe"}])
        for color in ("blue", "#fff", 123):
            with self.subTest(color=color), self.assertRaises(ValidationError):
                validar_diapositivas([{**slide, "color_fondo": color}])

    def test_exporta_todas_las_diapositivas_en_pdf_pptx_y_png(self):
        fondo = f"fondos/{imagenes_disponibles('fondos')[0]}"
        objeto = self.cuadro(texto="Editable en PowerPoint")
        objeto["fotogramas"][0]["giro"] = 90
        self.proyecto.diapositivas = [
            {"id": "slide-1", "objetos": [objeto], "fondo": fondo, "color_fondo": "#dbeafe", "duracion_frames": 300},
            {"id": "slide-2", "objetos": [], "fondo": "", "color_fondo": "#fef9c3", "duracion_frames": 600},
        ]
        self.proyecto.save()

        pdf = self.client.get(reverse("editor:exportar", args=[self.proyecto.pk, "pdf"]))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        pptx = self.client.get(reverse("editor:exportar", args=[self.proyecto.pk, "pptx"]))
        deck = Presentation(BytesIO(pptx.content))
        self.assertEqual(len(deck.slides), 2)
        self.assertIn("Editable en PowerPoint", deck.slides[0].shapes[1].text)
        self.assertEqual(deck.slides[0].shapes[1].rotation, 90)
        self.assertEqual(tuple(deck.slides[0].background.fill.fore_color.rgb), (219, 234, 254))
        self.assertEqual(tuple(deck.slides[1].background.fill.fore_color.rgb), (254, 249, 195))
        images = self.client.get(reverse("editor:exportar", args=[self.proyecto.pk, "png"]))
        with ZipFile(BytesIO(images.content)) as archive:
            self.assertEqual(archive.namelist(), ["diapositiva-1.png", "diapositiva-2.png"])
            rotated_png = archive.read("diapositiva-1.png")
            with Image.open(BytesIO(archive.read("diapositiva-2.png"))) as slide_image:
                self.assertEqual(slide_image.getpixel((0, 0)), (254, 249, 195))
        object_without_rotation = deepcopy(objeto)
        object_without_rotation["fotogramas"][0]["giro"] = 0
        unrotated_slides = [dict(self.proyecto.diapositivas[0], objetos=[object_without_rotation])]
        with ZipFile(BytesIO(exportar_imagenes(unrotated_slides))) as archive:
            unrotated_png = archive.read("diapositiva-1.png")
        self.assertNotEqual(rotated_png, unrotated_png)

    def test_exportacion_requiere_propietario_y_formato_valido(self):
        self.client.force_login(self.otro)
        self.assertEqual(self.client.get(reverse("editor:exportar", args=[self.proyecto.pk, "pdf"])).status_code, 404)
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse("editor:exportar", args=[self.proyecto.pk, "exe"])).status_code, 404)

    def test_autoguardado_ajax_guarda_y_reporta_errores(self):
        objeto = self.cuadro(animacion="subir")
        response = self.client.post(
            self.guardar,
            {
                "nombre": "Guardado automático",
                "objetos": json.dumps([objeto]),
                "fondo": "",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"saved": True})
        self.proyecto.refresh_from_db()
        self.assertEqual(self.proyecto.nombre, "Guardado automático")
        self.assertEqual(self.proyecto.objetos, [objeto])

        objeto["animacion"] = "efecto-inexistente"
        response = self.client.post(
            self.guardar,
            {"nombre": "No guardar", "objetos": json.dumps([objeto]), "fondo": ""},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("objetos", response.json()["errors"])
        self.proyecto.refresh_from_db()
        self.assertEqual(self.proyecto.nombre, "Guardado automático")

    def test_editor_muestra_animaciones_predefinidas_sin_linea_de_tiempo(self):
        response = self.client.get(self.detalle)
        for preset in ["ninguna", "aparecer", "subir", "zoom", "girar", "rebote"]:
            self.assertContains(response, f'data-animation="{preset}"')
        self.assertContains(response, 'id="animation-tool"')
        self.assertContains(response, 'id="preview-animation"')
        self.assertNotContains(response, 'id="timeline-scroll"')
        self.assertNotContains(response, 'id="commit-key"')

    def test_rechaza_rutas_de_imagenes_que_no_pertenecen_a_las_galerias(self):
        objeto = self.cuadro(tipo="imagen", imagen="../logo.png", texto="")
        response = self.client.post(self.guardar, {
            "nombre": "No guardar",
            "objetos": json.dumps([objeto]),
            "fondo": "",
        })
        self.assertIn("objetos", response.context["form"].errors)
        fondo_invalido = self.client.post(self.guardar, {
            "nombre": "No guardar",
            "objetos": "[]",
            "fondo": "elementos/bola.png",
        })
        self.assertIn("fondo", fondo_invalido.context["form"].errors)
        self.proyecto.refresh_from_db()
        self.assertEqual(self.proyecto.objetos, [])
        self.assertEqual(self.proyecto.fondo, "")

    def test_formulario_antiguo_conserva_fondo(self):
        fondo = f"fondos/{imagenes_disponibles('fondos')[0]}"
        self.proyecto.fondo = fondo
        self.proyecto.save()
        response = self.client.post(self.guardar, {"nombre": "Solo nombre"})
        self.assertRedirects(response, self.detalle)
        self.proyecto.refresh_from_db()
        self.assertEqual(self.proyecto.fondo, fondo)

    def test_guardar_cuadros_independientes_y_recuperar(self):
        objetos = [self.cuadro(), self.cuadro(id="cuadro-2", texto="Segundo", x=400, tamano=24, negrita=True)]
        response = self.client.post(self.guardar, {"nombre": "Escena", "objetos": json.dumps(objetos)}, follow=True)
        self.assertContains(response, "Proyecto guardado")
        self.proyecto.refresh_from_db()
        self.assertEqual(self.proyecto.objetos, objetos)
        self.assertEqual(self.client.get(self.detalle).context["objetos"], objetos)
        self.assertEqual(self.ajeno.objetos, [])

    def test_guardar_eliminacion_y_texto_vacio(self):
        for objetos in [[self.cuadro(texto="")], []]:
            self.assertEqual(self.client.post(self.guardar, {"nombre": "Escena", "objetos": json.dumps(objetos)}).status_code, 302)
            self.proyecto.refresh_from_db()
            self.assertEqual(self.proyecto.objetos, objetos)

    def test_rechaza_escenas_invalidas_sin_modificar_proyecto(self):
        invalidos = [None, {}, "texto", [self.cuadro(x=-8001)], [self.cuadro(x=8001)],
            [self.cuadro(ancho=8001)], [self.cuadro(alto=4501)],
            [self.cuadro(tamano=121)], [self.cuadro(tamano=True)], [self.cuadro(x=float("nan"))],
            [self.cuadro(fuente="<script>")], [self.cuadro(color="red")],
            [self.cuadro(texto="a" * 5001)], [self.cuadro(alto=0)],
            [self.cuadro(negrita="true")], [self.cuadro(id="<script>")],
            [self.cuadro(), self.cuadro()], [self.cuadro(extra="propiedad")],
            [self.cuadro(id=f"id-{i}") for i in range(101)]]
        # null es una entrada inválida: para vaciar el lienzo se envía [].
        for objetos in invalidos:
            with self.subTest(objetos=str(objetos)[:80]):
                response = self.client.post(self.guardar, {"nombre": "No guardar", "objetos": json.dumps(objetos)})
                self.assertIn("objetos", response.context["form"].errors)
                self.proyecto.refresh_from_db()
                self.assertEqual(self.proyecto.nombre, "Proyecto de Ana")
                self.assertEqual(self.proyecto.objetos, [])

    def test_objetos_y_fotogramas_pueden_salir_del_marco(self):
        objeto = self.cuadro(x=-120, y=470, ancho=1000, alto=600)
        objeto["fotogramas"][0].update(x=-120, y=470)
        response = self.client.post(self.guardar, {
            "nombre": "Objeto fuera del marco",
            "objetos": json.dumps([objeto]),
        })
        self.assertEqual(response.status_code, 302)
        self.proyecto.refresh_from_db()
        self.assertEqual(self.proyecto.objetos, [objeto])

    def test_json_roto_y_error_nombre_conservan_cuadros(self):
        response = self.client.post(self.guardar, {"nombre": "Escena", "objetos": "{roto"})
        self.assertIn("objetos", response.context["form"].errors)
        objetos = [self.cuadro()]
        response = self.client.post(self.guardar, {"nombre": "", "objetos": json.dumps(objetos)})
        self.assertEqual(response.context["objetos"], objetos)
        self.proyecto.refresh_from_db()
        self.assertEqual(self.proyecto.objetos, [])

    def test_html_en_cuadros_se_serializa_sin_ejecutar(self):
        texto = '</script><img src=x onerror=alert(1)>'
        response = self.client.post(self.guardar, {"nombre": "Escena", "objetos": json.dumps([self.cuadro(texto=texto)])}, follow=True)
        self.assertNotContains(response, texto)
        self.proyecto.refresh_from_db()
        self.assertEqual(self.proyecto.objetos[0]["texto"], texto)

    def test_nombre_solo_no_borra_cuadros_y_ajeno_no_puede_guardar(self):
        self.proyecto.objetos = [self.cuadro()]
        self.proyecto.save()
        self.client.post(self.guardar, {"nombre": "Solo nombre"})
        self.proyecto.refresh_from_db()
        self.assertEqual(self.proyecto.objetos, [self.cuadro()])

    def test_animacion_y_duracion_persisten(self):
        objeto = self.cuadro()
        objeto["fotogramas"].append(dict(frame=600, x=300, y=200, giro=-180, opacidad=0.25, interpolacion="suave"))
        response = self.client.post(self.guardar, {"nombre": "Animación", "objetos": json.dumps([objeto]), "duracion_frames": 900})
        self.assertEqual(response.status_code, 302)
        self.proyecto.refresh_from_db()
        self.assertEqual(self.proyecto.duracion_frames, 900)
        self.assertEqual(self.proyecto.objetos, [objeto])

    def test_rechaza_fotogramas_invalidos(self):
        base = self.cuadro()
        key = base["fotogramas"][0]
        invalidos = [[], [key, key], [{**key, "frame": -1}], [{**key, "frame": 1.5}],
            [{**key, "frame": True}], [{**key, "frame": 3601}], [{**key, "x": 8001}],
            [{**key, "giro": 361}], [{**key, "opacidad": -0.1}], [{**key, "opacidad": float("nan")}],
            [{**key, "opacidad": True}], [{**key, "interpolacion": "desconocida"}],
            [{**key, "frame": 10}, key], [{**key, "extra": 3}]]
        for keys in invalidos:
            with self.subTest(keys=keys):
                response = self.client.post(self.guardar, {"nombre": "Inválido", "objetos": json.dumps([{**base, "fotogramas": keys}])})
                self.assertTrue(response.context["form"].errors)
                self.proyecto.refresh_from_db()
                self.assertEqual(self.proyecto.objetos, [])

    def test_duracion_invalida_no_guarda_ningun_cambio(self):
        objeto = self.cuadro()
        objeto["fotogramas"].append({**objeto["fotogramas"][0], "frame": 300})
        for duracion in [29, 3601, 60, "abc", 30.5]:
            response = self.client.post(self.guardar, {"nombre": "Inválido", "objetos": json.dumps([objeto]), "duracion_frames": duracion})
            self.assertIn("duracion_frames", response.context["form"].errors)
            self.proyecto.refresh_from_db()
            self.assertEqual(self.proyecto.nombre, "Proyecto de Ana")

    def test_formulario_antiguo_conserva_pistas_por_id(self):
        objeto = self.cuadro()
        objeto["fotogramas"].append(dict(frame=100, x=200, y=100, giro=90, opacidad=0.5, interpolacion="lineal"))
        self.proyecto.objetos = [objeto]
        self.proyecto.duracion_frames = 600
        self.proyecto.save()
        anterior = deepcopy(objeto)
        del anterior["fotogramas"]
        anterior["texto"] = "Edición desde pestaña antigua"
        response = self.client.post(self.guardar, {"nombre": "Antiguo", "objetos": json.dumps([anterior])})
        self.assertEqual(response.status_code, 302)
        self.proyecto.refresh_from_db()
        self.assertEqual(self.proyecto.objetos[0]["fotogramas"], objeto["fotogramas"])
        self.assertEqual(self.proyecto.duracion_frames, 600)

    def test_ajeno_no_puede_cambiar_duracion_ni_pistas(self):
        self.client.force_login(self.otro)
        response = self.client.post(self.guardar, {"nombre": "Ajeno", "duracion_frames": 900, "objetos": json.dumps([self.cuadro()])})
        self.assertEqual(response.status_code, 404)
        self.proyecto.refresh_from_db()
        self.assertEqual(self.proyecto.objetos, [])
        self.assertEqual(self.proyecto.duracion_frames, 300)
