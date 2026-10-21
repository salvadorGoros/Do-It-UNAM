"""Prueba opcional: manage.py test editor.browser_tests (requiere Chromium y Playwright)."""
import base64
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from PIL import Image

from .models import PerfilUsuario, Proyecto, Rol

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


@unittest.skipUnless(sync_playwright, "Instala requirements-dev.txt para probar Chromium")
class EditorBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        super().setUp()
        self.media_directory = tempfile.TemporaryDirectory()
        self.media_settings = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.media_settings.enable()

    def tearDown(self):
        self.media_settings.disable()
        self.media_directory.cleanup()
        super().tearDown()

    def test_registro_institucional_e_inicio_con_numero_de_cuenta(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 360, "height": 800})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + "/cuentas/registro/")
            self.assertLessEqual(
                page.locator("html").evaluate("el => el.scrollWidth"),
                page.locator("html").evaluate("el => el.clientWidth"),
            )
            self.assertTrue(page.locator(".register-page .auth-shell").is_visible())
            page.locator('[name="correo_institucional"]').fill("nueva@comunidad.unam.mx")
            page.locator('[name="numero_cuenta"]').fill("31-2345-699")
            page.locator('[name="password1"]').fill("Browser-test-123!")
            page.locator('[name="password2"]').fill("Browser-test-123!")
            page.get_by_role("button", name="Crear cuenta", exact=True).click()
            page.wait_for_url(self.live_server_url + "/")
            self.assertIn("Alumno", page.locator(".account").inner_text())
            page.get_by_role("button", name="Cerrar sesión", exact=True).click()
            page.wait_for_selector(".login-page .auth-shell")
            self.assertLessEqual(
                page.locator("html").evaluate("el => el.scrollWidth"),
                page.locator("html").evaluate("el => el.clientWidth"),
            )
            page.locator('[name="username"]').fill("312345699")
            page.locator('[name="password"]').fill("Browser-test-123!")
            page.get_by_role("button", name="Entrar", exact=True).click()
            page.wait_for_url(self.live_server_url + "/")
            self.assertEqual(errors, [])
            browser.close()

    def test_panel_de_proyectos_filtra_y_se_adapta_a_movil(self):
        user = get_user_model().objects.create_user("projects-browser-test", password="Browser-test-123!")
        role_values = [
            (Rol.Clave.ALUMNO, "Alumno", 10_000),
            (Rol.Clave.DOCENTE, "Docente", 50_000),
            (Rol.Clave.ADMINISTRADOR, "Administrador", 200_000),
        ]
        roles = {}
        for key, name, quota in role_values:
            roles[key], _ = Rol.objects.get_or_create(
                clave=key,
                defaults={"nombre": name, "cuota_tokens_dia": quota},
            )
        PerfilUsuario.objects.create(
            usuario=user,
            rol=roles[Rol.Clave.ADMINISTRADOR],
            correo_institucional="projects-browser-test@comunidad.unam.mx",
            numero_cuenta="312345690",
        )
        Proyecto.objects.create(
            nombre="Biología celular",
            propietario=user,
            diapositivas=[{
                "id": "slide-1",
                "color_fondo": "#dbeafe",
                "fondo": "",
                "duracion_frames": 300,
                "objetos": [{
                    "id": "text-1", "texto": "La célula", "x": 80, "y": 90,
                    "ancho": 420, "alto": 90, "tamano": 42, "color": "#0b3b60",
                    "fuente": "Poppins", "negrita": True, "cursiva": False,
                    "subrayado": False, "alineacion": "left",
                    "fotogramas": [{
                        "frame": 0, "x": 80, "y": 90, "giro": 0,
                        "opacidad": 1, "interpolacion": "lineal",
                    }],
                }],
            }],
        )
        Proyecto.objects.create(nombre="Historia universal", propietario=user)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + "/")
            page.locator('[name="username"]').fill("projects-browser-test")
            page.locator('[name="password"]').fill("Browser-test-123!")
            page.get_by_role("button", name="Entrar", exact=True).click()
            page.wait_for_url(self.live_server_url + "/")

            self.assertEqual(page.locator(".project-card").count(), 2)
            self.assertTrue(page.locator(".admin-access").is_visible())
            self.assertEqual(page.locator(".admin-access").get_attribute("href"), "/administracion/")
            self.assertEqual(page.locator(".preview-text").first.inner_text(), "La célula")
            page.locator("#project-search").fill("biologia")
            self.assertEqual(page.locator(".project-card:visible").count(), 1)
            page.locator("#project-search").fill("inexistente")
            self.assertTrue(page.locator("#project-search-empty").is_visible())

            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("#project-search").fill("")
            self.assertLessEqual(
                page.locator("html").evaluate("el => el.scrollWidth"),
                page.locator("html").evaluate("el => el.clientWidth"),
            )
            self.assertTrue(page.locator(".admin-access").is_visible())
            page.locator(".admin-access").click()
            page.wait_for_url(self.live_server_url + "/administracion/")
            self.assertTrue(page.locator(".admin-dashboard").is_visible())
            self.assertLessEqual(
                page.locator("html").evaluate("el => el.scrollWidth"),
                page.locator("html").evaluate("el => el.clientWidth"),
            )
            page.locator(".create-user-panel summary").click()
            self.assertTrue(page.locator(".create-user-popover").is_visible())
            create_panel = page.locator(".create-user-popover").bounding_box()
            self.assertGreaterEqual(create_panel["x"], 0)
            self.assertLessEqual(create_panel["x"] + create_panel["width"], 390)
            page.locator(".create-user-close").click()
            self.assertTrue(page.locator(".create-user-popover").is_hidden())
            self.assertEqual(errors, [])
            browser.close()

    @override_settings(GEMINI_API_KEY="")
    def test_panel_ia_indica_configuracion_pendiente_sin_errores(self):
        user = get_user_model().objects.create_user("ai-browser-test", password="Browser-test-123!")
        proyecto = Proyecto.objects.create(nombre="IA", propietario=user)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + f"/proyectos/{proyecto.pk}/")
            page.locator('[name="username"]').fill("ai-browser-test")
            page.locator('[name="password"]').fill("Browser-test-123!")
            page.get_by_role("button", name="Entrar", exact=True).click()
            page.wait_for_selector("#ai-tool")
            page.locator("#ai-tool").click()
            page.wait_for_function(
                "() => document.querySelector('#ai-connection-text').textContent.includes('GEMINI_API_KEY')"
            )
            self.assertTrue(page.locator('[data-gallery="ia"]').is_visible())
            self.assertTrue(page.locator("#ai-generate-presentation").is_disabled())
            self.assertTrue(page.locator(".ai-hero").is_visible())
            self.assertGreaterEqual(page.locator("#asset-panel").bounding_box()["width"], 290)
            cards = page.locator("details.ai-card")
            self.assertEqual(cards.count(), 4)
            self.assertTrue(cards.nth(0).evaluate("card => card.open"))
            cards.nth(2).locator("summary").click()
            self.assertFalse(cards.nth(0).evaluate("card => card.open"))
            self.assertTrue(cards.nth(2).evaluate("card => card.open"))
            page.locator("#ai-slide-notes").fill("Guion guardado desde el panel de IA")
            page.wait_for_function(
                "() => document.querySelector('#save-status').textContent.includes('Guardado automáticamente')"
            )
            page.reload()
            page.wait_for_selector("#ai-tool")
            page.locator("#ai-tool").click()
            page.locator("details.ai-card").nth(2).locator("summary").click()
            self.assertEqual(page.locator("#ai-slide-notes").input_value(), "Guion guardado desde el panel de IA")
            self.assertEqual(errors, [])
            browser.close()

    @override_settings(GEMINI_API_KEY="prueba")
    def test_panel_ia_muestra_pantalla_de_carga_hasta_recibir_respuesta(self):
        user = get_user_model().objects.create_user("ai-loading-test", password="Browser-test-123!")
        proyecto = Proyecto.objects.create(nombre="Carga IA", propietario=user)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors = []
            pending_routes = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/ia/generar/", lambda route: pending_routes.append(route))
            page.goto(self.live_server_url + f"/proyectos/{proyecto.pk}/")
            page.locator('[name="username"]').fill("ai-loading-test")
            page.locator('[name="password"]').fill("Browser-test-123!")
            page.get_by_role("button", name="Entrar", exact=True).click()
            page.locator("#ai-tool").click()
            page.wait_for_function("() => !document.querySelector('#ai-generate-text').disabled")
            self.assertTrue(page.locator(".ai-hero").is_visible())
            self.assertLessEqual(
                page.locator("html").evaluate("el => el.scrollWidth"),
                page.locator("html").evaluate("el => el.clientWidth"),
            )
            self.assertEqual(page.locator("#ai-quota-meter").get_attribute("aria-valuenow"), "0")
            page.locator("details.ai-card").nth(2).locator("summary").click()
            page.locator("#ai-text-source").fill("Contenido que Gemini debe resumir")

            with page.expect_request("**/ia/generar/"):
                page.locator("#ai-generate-text").click()
            page.wait_for_selector("#ai-loading-screen", state="visible")
            page.wait_for_function("() => document.activeElement?.id === 'ai-loading-screen'")
            self.assertEqual(len(pending_routes), 1)
            loading_screen = page.locator("#ai-loading-screen").bounding_box()
            loading_card = page.locator(".ai-loading-card").bounding_box()
            self.assertEqual(page.locator("#ai-loading-screen").evaluate("el => getComputedStyle(el).position"), "fixed")
            self.assertAlmostEqual(loading_screen["width"], 390, delta=1)
            self.assertLessEqual(loading_card["width"], 390 - 32)
            self.assertIn("Gemini", page.locator("#ai-loading-title").inner_text())
            self.assertEqual(page.locator('[data-gallery="ia"]').get_attribute("aria-busy"), "true")
            self.assertTrue(page.locator("body").evaluate("el => el.classList.contains('ai-request-pending')"))
            self.assertTrue(page.locator(".ai-primary").evaluate_all("buttons => buttons.every(button => button.disabled)"))

            pending_routes[0].fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "type": "text",
                    "text": "Resumen generado correctamente.",
                    "usage": {"input": 10, "output": 4, "total": 14},
                    "state": {
                        "configured": True,
                        "text_model": "gemini-test",
                        "quota": {"used": 14, "limit": 100000, "remaining": 99986},
                        "role": {"name": "Cuenta"},
                    },
                }),
            )
            page.wait_for_selector("#ai-loading-screen", state="hidden")
            self.assertEqual(page.locator('[data-gallery="ia"]').get_attribute("aria-busy"), "false")
            self.assertFalse(page.locator("body").evaluate("el => el.classList.contains('ai-request-pending')"))
            self.assertEqual(page.locator("#ai-text-output").input_value(), "Resumen generado correctamente.")
            page.wait_for_function("() => document.activeElement?.id === 'ai-generate-text'")

            with page.expect_request("**/ia/generar/"):
                page.locator("#ai-generate-text").click()
            page.wait_for_selector("#ai-loading-screen", state="visible")
            self.assertEqual(len(pending_routes), 2)
            pending_routes[1].fulfill(
                status=502,
                content_type="application/json",
                body=json.dumps({"error": "Gemini no pudo completar la solicitud. Intenta nuevamente."}),
            )
            page.wait_for_selector("#ai-loading-screen", state="hidden")
            self.assertTrue(page.locator("#ai-message").evaluate("el => el.classList.contains('error')"))
            self.assertIn("Intenta nuevamente", page.locator("#ai-message").inner_text())
            self.assertEqual(errors, [])
            browser.close()

    def test_color_de_fondo_por_diapositiva(self):
        user = get_user_model().objects.create_user("slide-color-test", email="slide-color@example.com")
        user.set_password("Browser-test-123!")
        user.save()
        proyecto = Proyecto.objects.create(nombre="Colores", propietario=user)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(self.live_server_url + f"/proyectos/{proyecto.pk}/")
            page.locator('[name="username"]').fill("slide-color-test")
            page.locator('[name="password"]').fill("Browser-test-123!")
            page.get_by_role("button", name="Entrar", exact=True).click()
            page.wait_for_selector("#slide-color-toolbar", state="visible")
            toolbar_bounds = page.locator("#slide-color-toolbar").bounding_box()
            stage_bounds = page.locator("#stage").bounding_box()
            self.assertLess(toolbar_bounds["y"], stage_bounds["y"])
            self.assertLess(toolbar_bounds["y"], page.locator(".slide-footer").bounding_box()["y"])
            self.assertEqual(
                page.locator("#slide-color-toolbar").evaluate("el => getComputedStyle(el).top"),
                page.locator("#text-toolbar").evaluate("el => getComputedStyle(el).top"),
            )
            page.locator("#slide-custom-color").fill("#ff00aa")
            self.assertEqual(page.locator("#stage").evaluate("el => el.style.backgroundColor"), "rgb(255, 0, 170)")
            page.locator('[data-slide-color="#3b82f6"]').click()
            self.assertEqual(page.locator("#stage").evaluate("el => el.style.backgroundColor"), "rgb(59, 130, 246)")
            self.assertEqual(page.locator(".slide-thumb-preview").first.evaluate("el => el.style.backgroundColor"), "rgb(59, 130, 246)")
            page.locator("#text-tool").click()
            self.assertTrue(page.locator("#slide-color-toolbar").is_hidden())
            page.locator("#stage").click(position={"x": 10, "y": 10})
            self.assertFalse(page.locator("#slide-color-toolbar").is_hidden())

            page.locator("#slide-list .slide-insert").last.click()
            self.assertEqual(page.locator("#stage").evaluate("el => el.style.backgroundColor"), "rgb(255, 255, 255)")
            page.locator("#slide-list .slide-thumb").first.click()
            self.assertEqual(page.locator("#stage").evaluate("el => el.style.backgroundColor"), "rgb(59, 130, 246)")
            page.wait_for_function(
                "() => document.querySelector('#save-status').textContent.includes('Guardado automáticamente')"
            )
            saved_color = json.loads(page.locator("#id_diapositivas").input_value())[0]["color_fondo"]
            self.assertEqual(saved_color, "#3b82f6")
            page.reload()
            page.wait_for_selector("#slide-color-toolbar", state="visible")
            self.assertEqual(page.locator("#stage").evaluate("el => el.style.backgroundColor"), "rgb(59, 130, 246)")
            browser.close()

    def test_muchas_diapositivas_mantienen_el_editor_y_usan_scroll(self):
        user = get_user_model().objects.create_user("many-slides-test", password="Browser-test-123!")
        slides = [{
            "id": f"slide-{index}",
            "objetos": [],
            "fondo": "",
            "color_fondo": "#ffffff",
            "audio": "",
            "audios": [],
            "marcadores": [],
            "notas": "",
            "duracion_frames": 300,
        } for index in range(1, 101)]
        proyecto = Proyecto.objects.create(nombre="Muchas diapositivas", propietario=user, diapositivas=slides)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + f"/proyectos/{proyecto.pk}/")
            page.locator('[name="username"]').fill("many-slides-test")
            page.locator('[name="password"]').fill("Browser-test-123!")
            page.get_by_role("button", name="Entrar", exact=True).click()
            page.wait_for_selector(".slide-thumb")
            self.assertEqual(page.locator(".slide-thumb").count(), 100)

            normal = page.evaluate("() => ({workspace:document.querySelector('.editor-workspace').getBoundingClientRect().toJSON(), footer:document.querySelector('.slide-footer').getBoundingClientRect().toJSON(), list:{rect:document.querySelector('.slide-list').getBoundingClientRect().toJSON(), sw:document.querySelector('.slide-list').scrollWidth,cw:document.querySelector('.slide-list').clientWidth}})")
            self.assertLessEqual(normal["workspace"]["right"], 1440)
            self.assertLessEqual(normal["footer"]["right"], normal["workspace"]["right"])
            self.assertGreater(normal["list"]["sw"], normal["list"]["cw"])
            self.assertLessEqual(normal["list"]["rect"]["right"], normal["footer"]["right"])

            page.locator("#elements-tool").click()
            with_panel = page.evaluate("() => ({panel:document.querySelector('#asset-panel').getBoundingClientRect().toJSON(), workspace:document.querySelector('.editor-workspace').getBoundingClientRect().toJSON(), list:{sw:document.querySelector('.slide-list').scrollWidth,cw:document.querySelector('.slide-list').clientWidth}})")
            self.assertLessEqual(with_panel["workspace"]["right"], 1440)
            self.assertLessEqual(with_panel["workspace"]["width"], 1100)
            self.assertGreater(with_panel["list"]["sw"], with_panel["list"]["cw"])
            self.assertLessEqual(with_panel["panel"]["right"], with_panel["workspace"]["left"])
            page.locator("#close-asset-panel").click()

            page.locator("#toggle-timeline").click()
            timeline_layout = page.evaluate("() => ({workspace:document.querySelector('.editor-workspace').getBoundingClientRect().toJSON(), area:document.querySelector('.stage-area').getBoundingClientRect().toJSON(), timeline:document.querySelector('#timeline-panel').getBoundingClientRect().toJSON(), footer:document.querySelector('.slide-footer').getBoundingClientRect().toJSON(), list:{rect:document.querySelector('.slide-list').getBoundingClientRect().toJSON(), sh:document.querySelector('.slide-list').scrollHeight,ch:document.querySelector('.slide-list').clientHeight}})")
            self.assertLessEqual(timeline_layout["workspace"]["right"], 1440)
            self.assertGreater(timeline_layout["list"]["sh"], timeline_layout["list"]["ch"])
            self.assertLessEqual(timeline_layout["list"]["rect"]["bottom"], timeline_layout["footer"]["bottom"])
            self.assertLessEqual(timeline_layout["footer"]["bottom"], timeline_layout["timeline"]["top"])
            self.assertAlmostEqual(timeline_layout["timeline"]["bottom"], timeline_layout["workspace"]["bottom"], delta=1)
            page.locator(".slide-thumb").last.click()
            self.assertEqual(page.locator(".slide-thumb").last.get_attribute("aria-current"), "true")
            page.set_viewport_size({"width": 390, "height": 844})
            mobile = page.evaluate("() => ({workspace:document.querySelector('.editor-workspace').getBoundingClientRect().toJSON(), timeline:document.querySelector('#timeline-panel').getBoundingClientRect().toJSON(), footer:document.querySelector('.slide-footer').getBoundingClientRect().toJSON(), list:{rect:document.querySelector('.slide-list').getBoundingClientRect().toJSON(), sh:document.querySelector('.slide-list').scrollHeight,ch:document.querySelector('.slide-list').clientHeight}})")
            self.assertLessEqual(mobile["workspace"]["right"], 390)
            self.assertGreater(mobile["list"]["sh"], mobile["list"]["ch"])
            self.assertLessEqual(mobile["list"]["rect"]["bottom"], mobile["footer"]["bottom"])
            self.assertLessEqual(mobile["footer"]["bottom"], mobile["timeline"]["top"])
            self.assertAlmostEqual(mobile["timeline"]["bottom"], mobile["workspace"]["bottom"], delta=1)
            self.assertEqual(errors, [])
            browser.close()

    def test_objetos_se_redimensionan_por_todos_los_lados_y_salen_del_marco(self):
        user = get_user_model().objects.create_user("resize-test", email="resize-test@example.com")
        user.set_password("Browser-test-123!")
        user.save()
        proyecto = Proyecto.objects.create(nombre="Redimensionar", propietario=user)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + f"/proyectos/{proyecto.pk}/")
            page.locator('[name="username"]').fill("resize-test")
            page.locator('[name="password"]').fill("Browser-test-123!")
            page.get_by_role("button", name="Entrar", exact=True).click()
            page.wait_for_selector("#text-tool", state="attached")
            self.assertEqual(errors, [])
            page.locator("#text-tool").click()
            page.locator(".text-object textarea").fill("Redimensionable")
            page.locator(".text-object textarea").press("Escape")
            directions = {
                "n": (0, -20), "ne": (20, -20), "e": (20, 0), "se": (20, 20),
                "s": (0, 20), "sw": (-20, 20), "w": (-20, 0), "nw": (-20, -20),
            }
            self.assertEqual(page.locator(".text-object.selected .resize-handle").count(), 8)
            handles_fit_frame = page.locator(".text-object.selected").evaluate("""el => {
                const frame = el.getBoundingClientRect();
                return [...el.querySelectorAll(".resize-handle")].every(handle => {
                    const point = handle.getBoundingClientRect();
                    return point.left >= frame.left && point.top >= frame.top
                        && point.right <= frame.right && point.bottom <= frame.bottom;
                });
            }""")
            self.assertTrue(handles_fit_frame)
            for direction, (dx, dy) in directions.items():
                before = json.loads(page.locator("#id_objetos").input_value())[0]
                handle = page.locator(f'.text-object.selected [data-handle="{direction}"]')
                bounds = handle.bounding_box()
                scale = page.locator("#stage").bounding_box()["width"] / 800
                page.mouse.move(bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2)
                page.mouse.down()
                page.mouse.move(
                    bounds["x"] + bounds["width"] / 2 + dx * scale,
                    bounds["y"] + bounds["height"] / 2 + dy * scale,
                    steps=4,
                )
                page.mouse.up()
                after = json.loads(page.locator("#id_objetos").input_value())[0]
                if dx:
                    self.assertGreater(after["ancho"], before["ancho"])
                else:
                    self.assertEqual(after["ancho"], before["ancho"])
                if dy:
                    self.assertGreater(after["alto"], before["alto"])
                else:
                    self.assertEqual(after["alto"], before["alto"])

            box = page.locator(".text-object.selected")
            rotate_handle = box.locator(".rotate-handle")
            rotate_bounds = rotate_handle.bounding_box()
            box_bounds = box.bounding_box()
            center_x = box_bounds["x"] + box_bounds["width"] / 2
            center_y = box_bounds["y"] + box_bounds["height"] / 2
            start_x = rotate_bounds["x"] + rotate_bounds["width"] / 2
            start_y = rotate_bounds["y"] + rotate_bounds["height"] / 2
            radius = ((start_x - center_x) ** 2 + (start_y - center_y) ** 2) ** 0.5
            page.mouse.move(start_x, start_y)
            page.mouse.down()
            page.mouse.move(center_x + radius, center_y, steps=8)
            self.assertEqual(page.locator(".rotation-angle-label").text_content(), "90°")
            self.assertTrue(page.locator(".rotation-angle-label").evaluate("el => el.classList.contains('is-aligned')"))
            self.assertTrue(page.locator(".rotation-guide-line").evaluate(
                "el => Number.parseFloat(getComputedStyle(el).opacity) > 0"
            ))
            page.mouse.up()
            self.assertTrue(page.locator(".rotation-guide").is_hidden())
            rotated = json.loads(page.locator("#id_objetos").input_value())[0]
            self.assertAlmostEqual(rotated["fotogramas"][0]["giro"], 90, delta=5)
            self.assertIn("rotate(9", box.evaluate("el => el.style.transform"))
            rotate_handle.focus()
            page.keyboard.press("ArrowRight")
            rotated = json.loads(page.locator("#id_objetos").input_value())[0]
            self.assertAlmostEqual(rotated["fotogramas"][0]["giro"], 105, delta=5)

            page.locator("#elements-tool").click()
            page.locator("#asset-panel .asset-category-choice").first.click()
            page.locator('#asset-panel .asset-category:not([hidden]) [data-asset-path]').first.click()
            image = page.locator(".image-object.selected")
            self.assertEqual(image.locator(".resize-handle").count(), 8)
            rotate_bounds = image.locator(".rotate-handle").bounding_box()
            image_bounds = image.bounding_box()
            image_center_x = image_bounds["x"] + image_bounds["width"] / 2
            image_center_y = image_bounds["y"] + image_bounds["height"] / 2
            rotate_x = rotate_bounds["x"] + rotate_bounds["width"] / 2
            rotate_y = rotate_bounds["y"] + rotate_bounds["height"] / 2
            radius = ((rotate_x - image_center_x) ** 2 + (rotate_y - image_center_y) ** 2) ** 0.5
            page.mouse.move(rotate_x, rotate_y)
            page.mouse.down()
            page.mouse.move(image_center_x + radius, image_center_y, steps=8)
            page.mouse.up()
            image_data = json.loads(page.locator("#id_objetos").input_value())[-1]
            self.assertAlmostEqual(image_data["fotogramas"][0]["giro"], 90, delta=5)
            stage_bounds = page.locator("#stage").bounding_box()
            image_bounds = image.bounding_box()
            page.mouse.move(
                image_bounds["x"] + image_bounds["width"] / 2,
                image_bounds["y"] + image_bounds["height"] / 2,
            )
            page.mouse.down()
            page.mouse.move(stage_bounds["x"] - 40, stage_bounds["y"] - 20, steps=5)
            page.mouse.up()
            image_data = json.loads(page.locator("#id_objetos").input_value())[-1]
            self.assertLess(image_data["x"], 0)
            self.assertLess(image_data["y"], 0)
            self.assertEqual(page.locator("#stage").evaluate("el => getComputedStyle(el).overflow"), "hidden")
            browser.close()

    def test_deshacer_rehacer_edicion_movimiento_y_eliminacion(self):
        user = get_user_model().objects.create_user("history-test", password="Browser-test-123!")
        proyecto = Proyecto.objects.create(nombre="Historial", propietario=user)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + f"/proyectos/{proyecto.pk}/")
            page.locator('[name="username"]').fill("history-test")
            page.locator('[name="password"]').fill("Browser-test-123!")
            page.get_by_role("button", name="Entrar", exact=True).click()
            page.wait_for_selector("#text-tool")
            self.assertTrue(page.locator("#text-toolbar").is_hidden())
            self.assertTrue(page.locator("#save-status").is_hidden())
            self.assertFalse(page.locator(".editor-help").count())
            page.wait_for_function(
                "() => Number(document.querySelector('#stage').style.transform.match(/^scale\\(([^)]+)\\)/)[1]) > 1"
            )
            initial_stage_rect = page.locator("#stage").bounding_box()
            initial_stage_scale = page.locator("#stage").evaluate("el => el.style.transform")
            self.assertIn("logo.png?v=4", page.locator(".projects-logo img").get_attribute("src"))
            self.assertFalse(page.locator(".export-menu").count())
            self.assertLess(
                page.locator("#undo-action").bounding_box()["x"],
                page.locator("#project-form").bounding_box()["x"],
            )
            self.assertLess(
                page.locator("#project-form").bounding_box()["x"],
                page.locator("#present-button").bounding_box()["x"],
            )
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_function(
                "() => getComputedStyle(document.querySelector('#editor-shell > aside')).flexDirection === 'row'"
            )
            self.assertLessEqual(
                page.locator("html").evaluate("el => el.scrollWidth"),
                page.locator("html").evaluate("el => el.clientWidth"),
            )
            mobile_stage = page.locator("#stage").bounding_box()
            mobile_area = page.locator(".stage-area").bounding_box()
            self.assertLessEqual(mobile_stage["width"], mobile_area["width"])
            self.assertLessEqual(mobile_stage["height"], mobile_area["height"])
            self.assertGreaterEqual(page.locator("#text-tool").bounding_box()["height"], 44)

            page.locator("#elements-tool").click()
            asset_panel = page.locator("#asset-panel").bounding_box()
            self.assertGreaterEqual(asset_panel["x"], 0)
            self.assertLessEqual(asset_panel["x"] + asset_panel["width"], 390)
            page.locator("#close-asset-panel").click()

            page.locator("#toggle-timeline").click()
            timeline = page.locator("#timeline-panel").bounding_box()
            timeline_area = page.locator(".stage-area").bounding_box()
            slide_rail = page.locator(".slide-footer").bounding_box()
            workspace = page.locator(".editor-workspace").bounding_box()
            self.assertLessEqual(timeline["height"], 250)
            self.assertGreaterEqual(timeline["x"], 0)
            self.assertLessEqual(timeline["x"] + timeline["width"], 390)
            self.assertEqual(page.locator("#timeline-panel").evaluate("el => getComputedStyle(el).position"), "relative")
            self.assertTrue(page.locator("#toggle-timeline").is_hidden())
            self.assertTrue(page.locator("body").evaluate("el => el.classList.contains('timeline-open')"))
            self.assertGreaterEqual(slide_rail["x"] + 1, timeline_area["x"] + timeline_area["width"])
            self.assertLessEqual(slide_rail["y"] + slide_rail["height"], timeline["y"] + 1)
            self.assertAlmostEqual(timeline["y"] + timeline["height"], workspace["y"] + workspace["height"], delta=2)
            page.locator("#close-timeline").click()
            self.assertTrue(page.locator("#toggle-timeline").is_visible())
            self.assertFalse(page.locator("body").evaluate("el => el.classList.contains('timeline-open')"))

            self.assertTrue(page.locator(".slide-options-trigger").first.is_visible())
            page.locator(".slide-options-trigger").first.click()
            menu = page.locator("#slide-context-menu").bounding_box()
            self.assertGreaterEqual(menu["x"], 0)
            self.assertLessEqual(menu["x"] + menu["width"], 390)
            page.keyboard.press("Escape")

            page.set_viewport_size({"width": 844, "height": 390})
            page.wait_for_function(
                "() => getComputedStyle(document.querySelector('#editor-shell > aside')).flexDirection === 'row'"
            )
            self.assertLessEqual(
                page.locator("html").evaluate("el => el.scrollWidth"),
                page.locator("html").evaluate("el => el.clientWidth"),
            )
            landscape_stage = page.locator("#stage").bounding_box()
            landscape_area = page.locator(".stage-area").bounding_box()
            self.assertLessEqual(landscape_stage["width"], landscape_area["width"])
            self.assertLessEqual(landscape_stage["height"], landscape_area["height"])
            page.locator("#toggle-timeline").click()
            landscape_timeline = page.locator("#timeline-panel").bounding_box()
            landscape_area = page.locator(".stage-area").bounding_box()
            landscape_rail = page.locator(".slide-footer").bounding_box()
            self.assertLessEqual(landscape_timeline["height"], 210)
            self.assertGreaterEqual(landscape_rail["x"] + 1, landscape_area["x"] + landscape_area["width"])
            self.assertLessEqual(landscape_rail["y"] + landscape_rail["height"], landscape_timeline["y"] + 1)
            self.assertTrue(page.locator("#toggle-timeline").is_hidden())
            page.locator("#close-timeline").click()
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.wait_for_function(
                "() => getComputedStyle(document.querySelector('#editor-shell > aside')).flexDirection === 'column'"
            )
            page.locator(".share-menu summary").click()
            self.assertEqual(page.locator(".share-menu-items a").count(), 5)
            self.assertTrue(page.get_by_role("link", name="Descargar PDF").is_visible())
            page.locator(".share-menu summary").click()

            page.locator("#text-tool").click()
            self.assertTrue(page.locator("#text-toolbar").is_visible())
            red_swatch = page.locator('.recommended-colors [data-text-color="#ef4444"]')
            self.assertEqual(
                red_swatch.evaluate("el => getComputedStyle(el).backgroundColor"),
                "rgb(239, 68, 68)",
            )
            self.assertEqual(page.locator("#stage").evaluate("el => el.style.transform"), initial_stage_scale)
            selected_stage_rect = page.locator("#stage").bounding_box()
            for dimension in ("x", "y", "width", "height"):
                self.assertAlmostEqual(selected_stage_rect[dimension], initial_stage_rect[dimension], delta=1)
            textarea = page.locator(".text-object textarea").first
            textarea.fill("Texto inicial")
            textarea.press("Escape")
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_function(
                "() => parseFloat(getComputedStyle(document.querySelector('.resize-se')).width) >= 24"
            )
            handle = page.locator(".resize-se").bounding_box()
            self.assertGreaterEqual(handle["width"], 18)
            self.assertGreaterEqual(handle["height"], 18)
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.wait_for_function(
                "() => getComputedStyle(document.querySelector('#editor-shell > aside')).flexDirection === 'column'"
            )
            page.wait_for_timeout(600)
            textarea.press("Enter")
            textarea.fill("Texto actualizado")
            page.wait_for_timeout(600)
            textarea.press("Control+z")
            self.assertEqual(textarea.input_value(), "Texto inicial")
            textarea.press("Control+Shift+z")
            self.assertEqual(textarea.input_value(), "Texto actualizado")
            textarea.press("Escape")
            page.locator("#stage").click(position={"x": 20, "y": 20})
            self.assertTrue(page.locator("#text-toolbar").is_hidden())

            obj = page.locator(".text-object").first
            before = json.loads(page.locator("#id_objetos").input_value())[0]["x"]
            rect = obj.bounding_box()
            scale = page.locator("#stage").bounding_box()["width"] / 800
            page.mouse.move(rect["x"] + 20, rect["y"] + 20)
            page.mouse.down()
            page.mouse.move(rect["x"] + 80 * scale, rect["y"] + 50 * scale, steps=6)
            page.mouse.up()
            moved = json.loads(page.locator("#id_objetos").input_value())[0]["x"]
            self.assertNotEqual(moved, before)
            page.keyboard.press("Control+z")
            self.assertEqual(json.loads(page.locator("#id_objetos").input_value())[0]["x"], before)
            page.keyboard.press("Control+y")
            self.assertEqual(json.loads(page.locator("#id_objetos").input_value())[0]["x"], moved)

            page.locator(".text-object").first.focus()
            page.keyboard.press("Delete")
            self.assertEqual(page.locator(".text-object").count(), 0)
            page.locator("#undo-action").click()
            self.assertEqual(page.locator(".text-object").count(), 1)
            page.locator("#redo-action").click()
            self.assertEqual(page.locator(".text-object").count(), 0)
            page.wait_for_function(
                "() => document.querySelector('#save-status').textContent.includes('Guardado automáticamente')"
            )
            page.reload()
            page.wait_for_selector("#text-tool")
            self.assertEqual(page.locator(".text-object").count(), 0)

            page.locator("#text-tool").click()
            first_text = page.locator(".text-object textarea").first
            first_text.fill("Texto hoja uno")
            first_text.press("Escape")
            page.wait_for_timeout(600)
            page.locator("#slide-list .slide-insert").last.click()
            page.locator("#text-tool").click()
            second_text = page.locator(".text-object textarea").first
            second_text.fill("Texto hoja dos")
            second_text.press("Escape")
            page.wait_for_timeout(600)
            page.locator("#slide-list .slide-insert").last.click()
            page.locator("#slide-list .slide-insert").last.click()
            page.locator("#text-tool").click()
            fourth_text = page.locator(".text-object textarea").first
            fourth_text.fill("Texto hoja cuatro")
            fourth_text.press("Escape")
            page.wait_for_timeout(600)

            page.locator("#slide-list .slide-thumb").first.click()
            first_text = page.locator(".text-object textarea").first
            page.locator(".text-object").first.click()
            page.locator("#edit-text").click()
            first_text.fill("Texto hoja uno editado")
            first_text.press("Escape")
            page.wait_for_timeout(600)
            page.locator("#slide-list .slide-thumb").nth(3).click()
            fourth_text = page.locator(".text-object textarea").first
            page.locator(".text-object").first.click()
            page.locator("#edit-text").click()
            fourth_text.fill("Texto hoja cuatro editado")
            fourth_text.press("Escape")
            page.wait_for_timeout(600)
            page.locator(".text-object").first.focus()
            fourth_x_before_move = json.loads(page.locator("#id_objetos").input_value())[0]["x"]
            page.keyboard.press("ArrowRight")
            fourth_x_after_move = json.loads(page.locator("#id_objetos").input_value())[0]["x"]
            self.assertNotEqual(fourth_x_before_move, fourth_x_after_move)
            page.wait_for_timeout(600)

            page.locator("#slide-list .slide-thumb").nth(1).click()
            page.locator("#undo-action").click()
            self.assertEqual(page.locator("#slide-list .slide-thumb").nth(1).get_attribute("aria-current"), "true")
            page.locator("#slide-list .slide-thumb").nth(3).click()
            self.assertEqual(json.loads(page.locator("#id_objetos").input_value())[0]["x"], fourth_x_before_move)
            self.assertEqual(page.locator(".text-object textarea").first.input_value(), "Texto hoja cuatro editado")
            page.locator("#slide-list .slide-thumb").nth(1).click()
            page.locator("#redo-action").click()
            self.assertEqual(page.locator("#slide-list .slide-thumb").nth(1).get_attribute("aria-current"), "true")
            page.locator("#slide-list .slide-thumb").nth(3).click()
            self.assertEqual(json.loads(page.locator("#id_objetos").input_value())[0]["x"], fourth_x_after_move)
            page.locator("#slide-list .slide-thumb").nth(1).click()
            page.locator("#undo-action").click()
            page.locator("#undo-action").click()
            self.assertEqual(page.locator("#slide-list .slide-thumb").nth(1).get_attribute("aria-current"), "true")
            page.locator("#slide-list .slide-thumb").nth(3).click()
            self.assertEqual(page.locator(".text-object textarea").first.input_value(), "Texto hoja cuatro")
            page.locator("#slide-list .slide-thumb").nth(1).click()
            page.locator("#redo-action").click()
            page.locator("#redo-action").click()
            self.assertEqual(page.locator("#slide-list .slide-thumb").nth(1).get_attribute("aria-current"), "true")
            page.locator("#slide-list .slide-thumb").nth(3).click()
            self.assertEqual(page.locator(".text-object textarea").first.input_value(), "Texto hoja cuatro editado")
            self.assertEqual(json.loads(page.locator("#id_objetos").input_value())[0]["x"], fourth_x_after_move)
            self.assertEqual(errors, [])
            browser.close()

    def test_diapositivas_independientes_duplicado_orden_copia_presentacion_y_animacion(self):
        user = get_user_model().objects.create_user("slides-test", password="Browser-test-123!")
        proyecto = Proyecto.objects.create(nombre="Diapositivas", propietario=user)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + f"/proyectos/{proyecto.pk}/")
            page.locator('[name="username"]').fill("slides-test")
            page.locator('[name="password"]').fill("Browser-test-123!")
            page.get_by_role("button", name="Entrar", exact=True).click()
            page.wait_for_selector("#text-tool")

            page.locator("#text-tool").click()
            page.locator(".text-object textarea").fill("Primera hoja")
            page.locator(".text-object textarea").press("Escape")
            page.locator("#stage .text-object").first.click()
            page.locator('[data-text-color="#3b82f6"]').click()
            first_id = json.loads(page.locator("#id_objetos").input_value())[0]["id"]
            self.assertEqual(json.loads(page.locator("#id_objetos").input_value())[0]["color"], "#3b82f6")
            self.assertTrue(page.locator('[data-gallery="animaciones"] #slide-duration').count())
            self.assertFalse(page.locator(".slide-footer #slide-duration").count())
            page.locator("#animation-tool").click()
            page.locator("#slide-duration").fill("4")
            page.locator("#slide-duration").press("Tab")
            page.locator("#animation-tool").click()
            page.locator("#slide-list .slide-insert").last.click()
            self.assertEqual(json.loads(page.locator("#id_diapositivas").input_value())[0]["duracion_frames"], 120)
            self.assertEqual(page.locator("#slide-duration").input_value(), "10")
            page.locator("#slide-list .slide-thumb").first.click()
            self.assertEqual(page.locator("#slide-duration").input_value(), "4")
            page.locator("#slide-list .slide-thumb").nth(1).click()
            self.assertEqual(page.locator("#slide-duration").input_value(), "10")
            self.assertEqual(page.locator("#stage .text-object").count(), 0)
            page.locator("#text-tool").click()
            page.locator(".text-object textarea").fill("Segunda hoja")
            page.locator(".text-object textarea").press("Escape")
            second_id = json.loads(page.locator("#id_objetos").input_value())[0]["id"]
            self.assertNotEqual(first_id, second_id)

            insert_buttons = page.locator("#slide-list .slide-insert")
            self.assertEqual(insert_buttons.nth(1).evaluate("el => getComputedStyle(el).opacity"), "0")
            insert_buttons.nth(1).hover()
            page.wait_for_timeout(200)
            self.assertEqual(insert_buttons.nth(1).evaluate("el => getComputedStyle(el).opacity"), "1")
            insert_buttons.nth(1).click()
            self.assertEqual(page.locator("#slide-list .slide-thumb").count(), 3)
            self.assertEqual(page.locator("#slide-list .slide-thumb").nth(1).get_attribute("aria-current"), "true")
            page.locator("#slide-list .slide-thumb").nth(1).click(button="right")
            page.locator("#delete-slide").click()
            self.assertEqual(page.locator("#slide-list .slide-thumb").count(), 2)
            page.locator("#slide-list .slide-insert").first.click()
            self.assertEqual(page.locator("#slide-list .slide-thumb").count(), 3)
            self.assertEqual(page.locator("#slide-list .slide-thumb").first.get_attribute("aria-current"), "true")
            page.locator("#slide-list .slide-thumb").first.click()
            page.keyboard.press("Delete")
            self.assertEqual(page.locator("#slide-list .slide-thumb").count(), 2)
            self.assertEqual(page.locator("#slide-list .slide-thumb").first.get_attribute("aria-current"), "true")

            original_order = [slide["id"] for slide in json.loads(page.locator("#id_diapositivas").input_value())]
            page.locator("#slide-list .slide-thumb").nth(1).drag_to(
                page.locator("#slide-list .slide-insert").first
            )
            reordered = [slide["id"] for slide in json.loads(page.locator("#id_diapositivas").input_value())]
            self.assertEqual(reordered, [original_order[1], original_order[0]])
            page.locator("#slide-list .slide-thumb").first.click(button="right")
            page.locator("#duplicate-slide").click()
            self.assertEqual(page.locator("#slide-list .slide-thumb").count(), 3)
            duplicate_id = json.loads(page.locator("#id_objetos").input_value())[0]["id"]
            self.assertNotEqual(duplicate_id, second_id)
            page.locator("#slide-list .slide-thumb").nth(2).click(button="right")
            page.locator("#copy-slide").click()
            page.keyboard.press("Control+v")
            self.assertEqual(page.locator("#slide-list .slide-thumb").count(), 4)
            page.locator("#stage .text-object").first.click()
            page.locator("#copy-object").click()
            page.locator("#paste-object").click()
            self.assertEqual(len(json.loads(page.locator("#id_objetos").input_value())), 2)

            page.locator("#animation-tool").click()
            page.locator("#animation-scope").select_option("presentacion")
            page.locator('[data-animation="zoom"]').click()
            slides = json.loads(page.locator("#id_diapositivas").input_value())
            self.assertTrue(all(
                obj["animacion"] == "zoom"
                for slide in slides
                for obj in slide["objetos"]
            ))
            page.locator("#slide-list .slide-thumb").last.click(button="right")
            page.locator("#delete-slide").click()
            self.assertEqual(page.locator("#slide-list .slide-thumb").count(), 3)
            self.assertEqual(page.locator("#stage .text-object").count(), 1)
            page.locator("#slide-list .slide-thumb").first.click()
            page.locator("#present-button").click()
            self.assertTrue(page.locator("body").evaluate("el => el.classList.contains('presenting')"))
            self.assertTrue(page.locator("#presentation-chrome").is_visible())
            self.assertTrue(page.locator("#previous-slide").is_disabled())
            self.assertEqual(page.locator("#presentation-count").inner_text(), "1 / 3")
            self.assertIn("MODO PRESENTACIÓN", page.locator(".presentation-topbar").inner_text().upper())
            page.locator("#toggle-presentation-play").click()
            self.assertIn("En pausa", page.locator("#presentation-playback-state").inner_text())
            self.assertEqual(page.locator("#toggle-presentation-play").get_attribute("aria-label"), "Reanudar presentación")
            page.locator("#toggle-presentation-play").click()
            self.assertIn("Reproduciendo", page.locator("#presentation-playback-state").inner_text())
            page.locator("#stage").focus()
            page.wait_for_function("() => document.body.classList.contains('presentation-ui-hidden')", timeout=4500)
            page.mouse.move(200, 200)
            page.wait_for_function("() => !document.body.classList.contains('presentation-ui-hidden')")
            page.locator("#next-slide").click()
            self.assertEqual(page.locator("#presentation-count").inner_text(), "2 / 3")
            page.set_viewport_size({"width": 390, "height": 844})
            mobile_controls = page.locator("#presentation-controls").bounding_box()
            self.assertGreaterEqual(mobile_controls["x"], 0)
            self.assertLessEqual(mobile_controls["x"] + mobile_controls["width"], 390)
            self.assertLessEqual(page.locator(".presentation-topbar").bounding_box()["width"], 390)
            page.locator("#exit-presentation").click()
            self.assertFalse(page.locator("body").evaluate("el => el.classList.contains('presenting')"))
            page.wait_for_function(
                "() => document.querySelector('#save-status').textContent.includes('Guardado automáticamente')"
            )
            expected_slides = json.loads(page.locator("#id_diapositivas").input_value())
            page.reload()
            page.wait_for_selector("#text-tool")
            self.assertEqual(json.loads(page.locator("#id_diapositivas").input_value()), expected_slides)
            self.assertEqual(errors, [])
            browser.close()
        proyecto.refresh_from_db()
        self.assertEqual(proyecto.diapositivas, expected_slides)

    def test_elementos_y_fondos_en_chromium(self):
        user = get_user_model().objects.create_user("assets-test", password="Browser-test-123!")
        proyecto = Proyecto.objects.create(nombre="Recursos", propietario=user)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + f"/proyectos/{proyecto.pk}/")
            page.locator('[name="username"]').fill("assets-test")
            page.locator('[name="password"]').fill("Browser-test-123!")
            page.get_by_role("button", name="Entrar", exact=True).click()
            page.wait_for_selector("#text-tool")

            page.locator("#elements-tool").click()
            category_choices = page.locator(".asset-category-choice")
            self.assertEqual(
                set(category_choices.locator("span").all_text_contents()),
                {"Formas", "Números", "Personajes de la FESC"},
            )
            category_choices.filter(has_text="Personajes de la FESC").click()
            self.assertEqual(
                page.locator('[data-gallery="elementos"] .asset-category:not([hidden])').count(),
                1,
            )
            element_choice = page.locator(
                '[data-gallery="elementos"] .asset-category:not([hidden]) .asset-choice'
            ).first
            self.assertTrue(element_choice.get_attribute("data-asset-path").startswith("elementos/Personajes de la FESC/"))
            element_path = element_choice.get_attribute("data-asset-path")
            element_choice.click()
            image = page.locator("#stage .image-object img")
            image.wait_for()
            self.assertGreater(image.evaluate("img => img.naturalWidth"), 0)
            saved_objects = json.loads(page.locator("#id_objetos").input_value())
            self.assertEqual(saved_objects[0]["tipo"], "imagen")
            self.assertEqual(saved_objects[0]["imagen"], element_path)

            page.locator("#background-tool").click()
            background_choice = page.locator('[data-gallery="fondos"] .asset-choice').first
            background_path = background_choice.get_attribute("data-asset-path")
            background_choice.click()
            self.assertEqual(page.locator("#id_fondo").input_value(), background_path)
            self.assertIn(background_path, page.locator("#stage").evaluate("el => el.style.backgroundImage"))

            page.wait_for_function(
                "() => document.querySelector('#save-status').textContent.includes('Guardado automáticamente')"
            )
            self.assertEqual(page.locator("#id_fondo").input_value(), background_path)
            self.assertEqual(json.loads(page.locator("#id_objetos").input_value())[0]["imagen"], element_path)
            self.assertGreater(page.locator("#stage .image-object img").evaluate("img => img.naturalWidth"), 0)

            page.locator("#clear-background").click()
            self.assertEqual(page.locator("#id_fondo").input_value(), "")
            self.assertEqual(page.locator("#stage").evaluate("el => el.style.backgroundImage"), "none")
            page.wait_for_function(
                "() => document.querySelector('#save-status').textContent.includes('Guardado automáticamente')"
            )
            self.assertEqual(page.locator("#id_fondo").input_value(), "")

            self.assertEqual(errors, [])
            browser.close()
        proyecto.refresh_from_db()
        self.assertEqual(proyecto.fondo, "")
        self.assertEqual(proyecto.objetos[0]["imagen"], element_path)

    def test_imagenes_se_suben_y_persisten_en_biblioteca(self):
        user = get_user_model().objects.create_user("upload-test", email="upload-test@example.com")
        user.set_password("Browser-test-123!")
        user.save()
        proyecto = Proyecto.objects.create(nombre="Mis imágenes", propietario=user)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + f"/proyectos/{proyecto.pk}/")
            page.locator('[name="username"]').fill("upload-test")
            page.locator('[name="password"]').fill("Browser-test-123!")
            page.get_by_role("button", name="Entrar", exact=True).click()
            page.wait_for_selector("#text-tool")
            page.locator("#images-tool").click()

            image_data = BytesIO()
            Image.new("RGB", (16, 12), "purple").save(image_data, format="PNG")
            image_bytes = image_data.getvalue()
            page.locator("#image-file-input").set_input_files({
                "name": "seleccionada.png",
                "mimeType": "image/png",
                "buffer": image_bytes,
            })
            uploaded_choices = page.locator('[data-gallery="imagenes"] .asset-choice')
            page.wait_for_function(
                """() => document.querySelector('[data-gallery="imagenes"] .asset-choice')
                    || document.querySelector('#image-upload-status').textContent"""
            )
            self.assertGreater(
                uploaded_choices.count(),
                0,
                page.locator("#image-upload-status").text_content(),
            )
            uploaded_choices.first.click()
            page.wait_for_function(
                "() => document.querySelector('#stage .image-object img')?.naturalWidth > 0"
            )
            saved_upload_path = json.loads(page.locator("#id_objetos").input_value())[0]["imagen"]
            self.assertTrue(saved_upload_path.startswith("uploads/"))
            page.wait_for_function(
                "() => document.querySelector('#save-status').textContent.includes('Guardado automáticamente')"
            )

            page.locator("#image-drop-zone").evaluate(
                """(zone, encoded) => {
                    const bytes = Uint8Array.from(atob(encoded), character => character.charCodeAt(0));
                    const transfer = new DataTransfer();
                    transfer.items.add(new File([bytes], "arrastrada.png", {type: "image/png"}));
                    zone.dispatchEvent(new DragEvent("drop", {
                        bubbles: true, cancelable: true, dataTransfer: transfer
                    }));
                }""",
                base64.b64encode(image_bytes).decode("ascii"),
            )
            page.wait_for_function(
                "() => document.querySelectorAll('[data-gallery=\"imagenes\"] .asset-choice').length === 2"
            )
            page.wait_for_function(
                "() => document.querySelector('#image-upload-status').textContent.includes('guardada')"
            )
            page.reload()
            page.wait_for_selector("#text-tool")
            page.locator("#images-tool").click()
            page.wait_for_function(
                "() => document.querySelectorAll('[data-gallery=\"imagenes\"] .asset-choice').length === 2"
            )
            self.assertEqual(errors, [])
            browser.close()
        proyecto.refresh_from_db()
        self.assertTrue(proyecto.objetos[0]["imagen"].startswith("uploads/"))

    def test_texto_arrastre_autoguardado_y_animacion_predefinida(self):
        user = get_user_model().objects.create_user("browser-test", password="Browser-test-123!")
        proyecto = Proyecto.objects.create(nombre="Animación", propietario=user)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + f"/proyectos/{proyecto.pk}/")
            page.locator('[name="username"]').fill("browser-test")
            page.locator('[name="password"]').fill("Browser-test-123!")
            page.get_by_role("button", name="Entrar", exact=True).click()
            page.wait_for_selector("#text-tool")
            self.assertEqual(page.locator(".text-object").count(), 0)
            page.locator("#text-tool").click()
            text = page.locator(".text-object textarea").first
            text.fill("Mi primera animación\nTexto independiente")
            text.press("Escape")
            page.locator("#font-size").fill("28")
            page.locator("#font-family").select_option("Arial")
            page.locator("#bold").click()
            page.locator("#font-color").fill("#ffff00")
            scene = lambda: json.loads(page.locator("#id_objetos").input_value())
            first_id = scene()[0]["id"]
            box = page.locator(".text-object").first
            rect = box.bounding_box()
            before = scene()[0]
            scale = page.locator("#stage").bounding_box()["width"] / 800
            page.mouse.move(rect["x"] + 20, rect["y"] + 20)
            page.mouse.down()
            page.mouse.move(rect["x"] + 20 - 100 * scale, rect["y"] + 20 - 60 * scale, steps=8)
            page.mouse.up()
            self.assertAlmostEqual(scene()[0]["x"], before["x"] - 100, delta=2)
            self.assertAlmostEqual(scene()[0]["y"], before["y"] - 60, delta=2)
            handle = box.locator('[data-handle="se"]').bounding_box()
            handle_x = handle["x"] + handle["width"] / 2
            handle_y = handle["y"] + handle["height"] / 2
            page.mouse.move(handle_x, handle_y)
            page.mouse.down()
            page.mouse.move(handle_x + 60 * scale, handle_y + 40 * scale, steps=8)
            page.mouse.up()
            self.assertAlmostEqual(scene()[0]["ancho"], before["ancho"] + 60, delta=2)
            self.assertAlmostEqual(scene()[0]["alto"], before["alto"] + 40, delta=2)
            page.locator("#animation-tool").click()
            page.locator('[data-animation="subir"]').click()
            self.assertEqual(scene()[0]["animacion"], "subir")
            page.locator("#preview-animation").click()
            page.wait_for_function("() => !document.querySelector('#timeline-time').textContent.endsWith('F0')")
            page.locator("#text-tool").click()
            second = page.locator(".text-object textarea").last
            second.fill("Segundo cuadro")
            second.press("Escape")
            second_id = scene()[1]["id"]
            self.assertNotEqual(first_id, second_id)
            self.assertEqual(scene()[0]["tamano"], 28)
            self.assertEqual(scene()[1]["tamano"], 36)
            self.assertEqual(scene()[1]["animacion"], "ninguna")
            self.assertEqual(page.locator("#timeline-scroll").count(), 0)
            screenshot = Path(tempfile.gettempdir()) / "doit-cuadros.png"
            page.screenshot(path=str(screenshot))
            print(f"Captura: {screenshot}")
            expected = scene()
            page.wait_for_function(
                "() => document.querySelector('#save-status').textContent.includes('Guardado automáticamente')"
            )
            page.reload()
            page.wait_for_selector(".text-object")
            self.assertEqual(scene(), expected)
            # Doble clic, texto plano y salto de línea; sin ejecutar HTML.
            box = page.locator(f'.text-object[data-id="{second_id}"]')
            box.dblclick()
            self.assertFalse(box.locator("textarea").evaluate("el => el.readOnly"))
            box.locator("textarea").fill('<img src=x onerror=alert(1)>')
            self.assertEqual(page.locator("#stage img").count(), 0)
            box.locator("textarea").press("Escape")
            page.locator("#delete-text").click()
            self.assertEqual(len(scene()), 1)
            page.wait_for_function(
                "() => document.querySelector('#save-status').textContent.includes('Guardado automáticamente')"
            )
            self.assertEqual(len(scene()), 1)
            self.assertEqual(scene()[0]["id"], first_id)
            self.assertEqual(errors, [])
            browser.close()
        proyecto.refresh_from_db()
        self.assertEqual(proyecto.objetos, [expected[0]])

    def test_audio_se_asigna_a_una_diapositiva_y_persiste(self):
        user = get_user_model().objects.create_user("audio-test", password="Browser-test-123!")
        proyecto = Proyecto.objects.create(nombre="Audio", propietario=user)
        audio_data = (
            b"RIFF" + (36).to_bytes(4, "little") + b"WAVE"
            + b"fmt " + (16).to_bytes(4, "little")
            + (1).to_bytes(2, "little") + (1).to_bytes(2, "little")
            + (8000).to_bytes(4, "little") + (8000).to_bytes(4, "little")
            + (1).to_bytes(2, "little") + (8).to_bytes(2, "little")
            + b"data" + (0).to_bytes(4, "little")
        )
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + f"/proyectos/{proyecto.pk}/")
            page.locator('[name="username"]').fill("audio-test")
            page.locator('[name="password"]').fill("Browser-test-123!")
            page.get_by_role("button", name="Entrar", exact=True).click()
            page.wait_for_selector("#audio-tool")

            page.locator("#slide-list .slide-insert").last.click()
            page.locator("#slide-list .slide-insert").last.click()
            self.assertEqual(page.locator("#slide-list .slide-thumb").count(), 3)
            page.locator("#slide-list .slide-thumb").first.click()
            page.locator("#audio-tool").click()
            page.locator("#audio-file-input").set_input_files({
                "name": "narracion.wav",
                "mimeType": "audio/wav",
                "buffer": audio_data,
            })
            page.wait_for_selector("#uploaded-audio-list .audio-select")
            page.locator("#uploaded-audio-list .audio-select").click()
            page.wait_for_function(
                "() => JSON.parse(document.querySelector('#id_diapositivas').value)[0].audio"
            )
            audio_path = json.loads(page.locator("#id_diapositivas").input_value())[0]["audio"]
            page.locator("#apply-audio-all").click()
            page.wait_for_function(
                "() => JSON.parse(document.querySelector('#id_diapositivas').value).every(slide => slide.audios.length === 1)"
            )
            slides_with_audio = json.loads(page.locator("#id_diapositivas").input_value())
            self.assertTrue(all(slide["audio"] == audio_path for slide in slides_with_audio))
            self.assertEqual(len({slide["audios"][0]["id"] for slide in slides_with_audio}), 3)
            self.assertTrue(page.locator("#apply-audio-all").is_disabled())
            self.assertIn("3 diapositivas", page.locator("#audio-scope-summary").inner_text())
            self.assertTrue(audio_path.startswith(f"audio_uploads/{user.pk}/"))
            self.assertFalse(page.locator("#selected-audio-preview").is_hidden())
            page.wait_for_function(
                "() => document.querySelector('#save-status').textContent.includes('Guardado automáticamente')"
            )

            page.reload()
            page.wait_for_selector("#audio-tool")
            self.assertEqual(
                json.loads(page.locator("#id_diapositivas").input_value())[0]["audio"],
                audio_path,
            )
            page.locator("#audio-tool").click()
            self.assertFalse(page.locator("#clear-audio").is_disabled())
            page.locator("#clear-audio").click()
            self.assertEqual(json.loads(page.locator("#id_diapositivas").input_value())[0]["audio"], "")
            self.assertEqual(
                sum(bool(slide["audio"]) for slide in json.loads(page.locator("#id_diapositivas").input_value())),
                2,
            )
            page.locator("#slide-list .slide-thumb").nth(1).click()
            page.locator("#remove-audio-all").click()
            self.assertTrue(all(
                not slide["audios"]
                for slide in json.loads(page.locator("#id_diapositivas").input_value())
            ))
            page.wait_for_function(
                "() => document.querySelector('#save-status').textContent.startsWith('Guardado ')"
            )
            self.assertEqual(errors, [])
            browser.close()

    def test_linea_de_tiempo_fotogramas_marcador_y_plantilla(self):
        user = get_user_model().objects.create_user("timeline-test", password="Browser-test-123!")
        proyecto = Proyecto.objects.create(nombre="Línea de tiempo", propietario=user)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + f"/proyectos/{proyecto.pk}/")
            page.locator('[name="username"]').fill("timeline-test")
            page.locator('[name="password"]').fill("Browser-test-123!")
            page.get_by_role("button", name="Entrar", exact=True).click()
            page.locator("#text-tool").click()
            page.locator(".text-object textarea").fill("Objeto interactivo")
            page.locator(".text-object textarea").press("Escape")

            page.locator("#toggle-timeline").click()
            self.assertTrue(page.locator("#timeline-panel").is_visible())
            self.assertLessEqual(page.locator("#timeline-panel").bounding_box()["height"], 268)
            self.assertTrue(page.locator("#toggle-timeline").is_hidden())
            timeline = page.locator("#timeline-panel").bounding_box()
            timeline_area = page.locator(".stage-area").bounding_box()
            slide_rail = page.locator(".slide-footer").bounding_box()
            workspace = page.locator(".editor-workspace").bounding_box()
            self.assertGreaterEqual(slide_rail["x"] + 1, timeline_area["x"] + timeline_area["width"])
            self.assertLessEqual(slide_rail["y"] + slide_rail["height"], timeline["y"] + 1)
            self.assertAlmostEqual(timeline["x"], workspace["x"], delta=1)
            self.assertAlmostEqual(timeline["width"], workspace["width"], delta=1)
            self.assertEqual(page.locator(".timeline-ruler-corner").inner_text(), "PISTAS")
            page.locator("#animation-tool").click()
            page.locator('[data-keyframe-preset="subir"]').click()
            scene = lambda: json.loads(page.locator("#id_diapositivas").input_value())[0]
            self.assertEqual(len(scene()["objetos"][0]["fotogramas"]), 2)

            page.locator(".timeline-keyframe").last.click()
            self.assertTrue(page.locator("#keyframe-inspector-panel").evaluate("el => el.open"))
            page.locator("#keyframe-opacity").fill("0.65")
            page.locator("#keyframe-opacity").press("Enter")
            page.locator("#keyframe-easing").select_option("bezier")
            page.locator("#bezier-y1").fill("1.4")
            page.locator("#bezier-y1").press("Enter")
            page.locator("#timeline-zoom").fill("180")
            self.assertEqual(
                page.locator("#timeline-panel").evaluate("el => el.style.getPropertyValue('--timeline-second')"),
                "180px",
            )
            page.locator("#timeline-add-marker").click()
            self.assertEqual(len(scene()["marcadores"]), 1)
            self.assertEqual(scene()["marcadores"][0]["objeto_id"], scene()["objetos"][0]["id"])
            self.assertEqual(scene()["objetos"][0]["fotogramas"][-1]["opacidad"], 0.65)
            self.assertEqual(scene()["objetos"][0]["fotogramas"][-1]["bezier"][1], 1.4)

            page.locator("#animation-template-panel summary").click()
            page.locator("#animation-template-name").fill("Entrada privada")
            page.locator("#save-animation-template").click()
            page.wait_for_selector("#animation-template-list .template-item")
            self.assertIn("Entrada privada", page.locator("#animation-template-list").inner_text())

            page.locator("#slide-duration").fill("2")
            page.locator("#slide-duration").press("Enter")
            page.locator("#present-button").click()
            presentation_area = page.locator(".stage-area").bounding_box()
            self.assertAlmostEqual(presentation_area["width"], 1440, delta=1)
            self.assertAlmostEqual(presentation_area["height"], 1100, delta=1)
            page.wait_for_selector(".click-wait-target", timeout=5000)
            self.assertTrue(page.locator("body").evaluate("el => el.classList.contains('presentation-awaiting-click')"))
            self.assertIn("elemento resaltado", page.locator("#presentation-hint").inner_text())
            self.assertIn("Interacción", page.locator("#presentation-playback-state").inner_text())
            page.locator(".click-wait-target").click()
            page.wait_for_selector(".click-wait-target", state="detached")
            self.assertFalse(page.locator("body").evaluate("el => el.classList.contains('presentation-awaiting-click')"))
            page.locator("#exit-presentation").click()
            page.wait_for_function(
                "() => document.querySelector('#save-status').textContent.startsWith('Guardado autom')"
            )
            page.reload()
            page.wait_for_selector("#toggle-timeline")
            persisted = scene()
            self.assertEqual(len(persisted["marcadores"]), 1)
            self.assertEqual(persisted["objetos"][0]["fotogramas"][-1]["opacidad"], 0.65)
            self.assertEqual(errors, [])
            browser.close()
