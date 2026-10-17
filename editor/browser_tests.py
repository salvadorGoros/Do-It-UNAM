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

from .models import Proyecto

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
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.wait_for_function(
                "() => getComputedStyle(document.querySelector('#editor-shell > aside')).flexDirection === 'column'"
            )
            page.locator(".share-menu summary").click()
            self.assertEqual(page.locator(".share-menu-items a").count(), 3)
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
            page.locator("#next-slide").click()
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
            self.assertGreater(page.locator(".text-object").first.evaluate("el => el.getAnimations().length"), 0)
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
