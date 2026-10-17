from io import BytesIO
from contextlib import contextmanager
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from django.core.files.storage import default_storage
from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps
from pptx import Presentation
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor

from .scene import IMAGE_DIRECTORY


WIDTH, HEIGHT = 800, 450
EXPORT_WIDTH, EXPORT_HEIGHT = 1600, 900
PPT_WIDTH, PPT_HEIGHT = 13.333333, 7.5


@contextmanager
def _open_image(relative_path):
    if relative_path.startswith("uploads/"):
        with default_storage.open(relative_path, "rb") as image_file:
            yield image_file
    else:
        with (IMAGE_DIRECTORY / relative_path).open("rb") as image_file:
            yield image_file


def _image_bytes(relative_path):
    with _open_image(relative_path) as image_file, Image.open(image_file) as image:
        output = BytesIO()
        image.convert("RGBA").save(output, format="PNG")
    return output.getvalue()


def _font_path(bold=False, italic=False):
    name = {
        (False, False): "arial.ttf",
        (True, False): "arialbd.ttf",
        (False, True): "ariali.ttf",
        (True, True): "arialbi.ttf",
    }[(bold, italic)]
    linux_name = {
        (False, False): ("DejaVuSans.ttf", "LiberationSans-Regular.ttf"),
        (True, False): ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"),
        (False, True): ("DejaVuSans-Oblique.ttf", "LiberationSans-Italic.ttf"),
        (True, True): ("DejaVuSans-BoldOblique.ttf", "LiberationSans-BoldItalic.ttf"),
    }[(bold, italic)]
    candidates = [
        Path("C:/Windows/Fonts") / name,
        Path("/usr/share/fonts/truetype/dejavu") / linux_name[0],
        Path("/usr/share/fonts/truetype/liberation2") / linux_name[1],
    ]
    return next((path for path in candidates if path.is_file()), None)


def _load_pil_font(size, bold=False, italic=False):
    path = _font_path(bold, italic)
    return ImageFont.truetype(str(path), size) if path else ImageFont.load_default(size=size)


def _wrap_lines(text, max_width, measure):
    output = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for char in paragraph:
            if line and measure(line + char) > max_width:
                output.append(line)
                line = ""
            line += char
        output.append(line)
    return output


def _pdf_font(bold, italic):
    name = f"EditorFont{int(bold)}{int(italic)}"
    if name not in pdfmetrics.getRegisteredFontNames():
        path = _font_path(bold, italic)
        if path:
            pdfmetrics.registerFont(TTFont(name, str(path)))
        else:
            return "Helvetica-BoldOblique" if bold and italic else (
                "Helvetica-Bold" if bold else "Helvetica-Oblique" if italic else "Helvetica"
            )
    return name


def _cover_background(canvas_image, relative_path):
    if not relative_path:
        return
    with _open_image(relative_path) as image_file, Image.open(image_file) as background:
        fitted = ImageOps.fit(background.convert("RGB"), canvas_image.size)
    canvas_image.paste(fitted)


def _slide_color(slide_data):
    return slide_data.get("color_fondo", "#ffffff")


def _object_rotation(item):
    return next(
        (frame["giro"] for frame in item["fotogramas"] if frame["frame"] == 0),
        0,
    )


def _composite_rotated(canvas_image, layer, x, y, width, height, rotation):
    if rotation:
        layer = layer.rotate(-rotation, expand=True, resample=Image.Resampling.BICUBIC)
    left = round(x + (width - layer.width) / 2)
    top = round(y + (height - layer.height) / 2)
    source_left = max(0, -left)
    source_top = max(0, -top)
    source_right = min(layer.width, canvas_image.width - left)
    source_bottom = min(layer.height, canvas_image.height - top)
    if source_left >= source_right or source_top >= source_bottom:
        return
    canvas_image.alpha_composite(
        layer.crop((source_left, source_top, source_right, source_bottom)),
        (max(0, left), max(0, top)),
    )


def _cover_image_bytes(relative_path):
    with _open_image(relative_path) as image_file, Image.open(image_file) as image:
        fitted = ImageOps.fit(image.convert("RGB"), (EXPORT_WIDTH, EXPORT_HEIGHT))
        output = BytesIO()
        fitted.save(output, format="PNG")
    return output.getvalue()


def _render_slide(slide_data):
    image = Image.new("RGBA", (EXPORT_WIDTH, EXPORT_HEIGHT), ImageColor.getrgb(_slide_color(slide_data)))
    _cover_background(image, slide_data["fondo"])
    scale = EXPORT_WIDTH / WIDTH
    for item in slide_data["objetos"]:
        x, y = round(item["x"] * scale), round(item["y"] * scale)
        width, height = round(item["ancho"] * scale), round(item["alto"] * scale)
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        if item.get("tipo") == "imagen":
            with _open_image(item["imagen"]) as image_file, Image.open(image_file) as source:
                source = source.convert("RGBA")
                source.thumbnail((width, height), Image.Resampling.LANCZOS)
                layer.alpha_composite(source, ((width - source.width) // 2, (height - source.height) // 2))
        else:
            draw = ImageDraw.Draw(layer)
            font_size = max(1, round(item["tamano"] * scale))
            font = _load_pil_font(font_size, item["negrita"], item["cursiva"])
            line_height = font_size * 1.2
            lines = _wrap_lines(item["texto"], width - 8 * scale, lambda line: draw.textlength(line, font=font))
            for index, line in enumerate(lines[:max(1, int(height / line_height))]):
                line_width = draw.textlength(line, font=font)
                text_x = {"left": 0, "center": (width - line_width) / 2, "right": width - line_width}[item["alineacion"]]
                text_y = 4 * scale + index * line_height
                draw.text((text_x, text_y), line, font=font, fill=item["color"])
                if item["subrayado"]:
                    draw.line((text_x, text_y + font_size, text_x + line_width, text_y + font_size), fill=item["color"], width=max(1, round(scale)))
        _composite_rotated(image, layer, x, y, width, height, _object_rotation(item))
    return image.convert("RGB")


def exportar_imagenes(diapositivas):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for index, diapositiva in enumerate(diapositivas, start=1):
            buffer = BytesIO()
            _render_slide(diapositiva).save(buffer, format="PNG")
            archive.writestr(f"diapositiva-{index}.png", buffer.getvalue())
    return output.getvalue()


def exportar_pdf(nombre, diapositivas):
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=(PPT_WIDTH * 72, PPT_HEIGHT * 72), pageCompression=1)
    scale = PPT_WIDTH * 72 / WIDTH
    for diapositiva in diapositivas:
        pdf.setFillColor(HexColor(_slide_color(diapositiva)))
        pdf.rect(0, 0, PPT_WIDTH * 72, PPT_HEIGHT * 72, fill=1, stroke=0)
        if diapositiva["fondo"]:
            pdf.drawImage(
                ImageReader(BytesIO(_cover_image_bytes(diapositiva["fondo"]))),
                0, 0, width=PPT_WIDTH * 72, height=PPT_HEIGHT * 72,
                preserveAspectRatio=False, mask="auto",
            )
        for item in diapositiva["objetos"]:
            x, y = item["x"] * scale, (HEIGHT - item["y"] - item["alto"]) * scale
            rotation = _object_rotation(item)
            pdf.saveState()
            pdf.translate(x + item["ancho"] * scale / 2, y + item["alto"] * scale / 2)
            pdf.rotate(-rotation)
            if item.get("tipo") == "imagen":
                pdf.drawImage(
                    ImageReader(BytesIO(_image_bytes(item["imagen"]))),
                    -item["ancho"] * scale / 2, -item["alto"] * scale / 2,
                    width=item["ancho"] * scale, height=item["alto"] * scale,
                    preserveAspectRatio=True, anchor="c", mask="auto",
                )
                pdf.restoreState()
                continue
            font_name = _pdf_font(item["negrita"], item["cursiva"])
            pdf.setFont(font_name, item["tamano"] * scale)
            pdf.setFillColor(item["color"])
            lines = _wrap_lines(
                item["texto"],
                item["ancho"] * scale * 72 - 6,
                lambda line: pdfmetrics.stringWidth(line, font_name, item["tamano"] * scale),
            )
            for line_index, line in enumerate(lines[:max(1, int(item["alto"] / (item["tamano"] * 1.2)))]):
                line_y = item["alto"] * scale / 2 - (line_index + 1) * item["tamano"] * 1.2 * scale
                if item["alineacion"] == "center":
                    pdf.drawCentredString(0, line_y, line)
                elif item["alineacion"] == "right":
                    pdf.drawRightString(item["ancho"] * scale / 2, line_y, line)
                else:
                    pdf.drawString(-item["ancho"] * scale / 2, line_y, line)
            pdf.restoreState()
        pdf.showPage()
    pdf.setTitle(nombre)
    pdf.save()
    return output.getvalue()


def _add_picture(slide, relative_path, x, y, width, height):
    with _open_image(relative_path) as image_file, Image.open(image_file) as source:
        image_width, image_height = source.size
    scale = min(width / image_width, height / image_height)
    fitted_width, fitted_height = width * scale, height * scale
    return slide.shapes.add_picture(
        BytesIO(_image_bytes(relative_path)),
        Inches(x + (width - fitted_width) / 2),
        Inches(y + (height - fitted_height) / 2),
        width=Inches(fitted_width),
        height=Inches(fitted_height),
    )


def exportar_pptx(nombre, diapositivas):
    presentation = Presentation()
    presentation.slide_width = Inches(PPT_WIDTH)
    presentation.slide_height = Inches(PPT_HEIGHT)
    blank_layout = presentation.slide_layouts[6]
    scale = PPT_WIDTH / WIDTH
    alignments = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}
    for data in diapositivas:
        slide = presentation.slides.add_slide(blank_layout)
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string(_slide_color(data).lstrip("#"))
        if data["fondo"]:
            slide.shapes.add_picture(
                BytesIO(_cover_image_bytes(data["fondo"])), 0, 0,
                width=presentation.slide_width, height=presentation.slide_height,
            )
        for item in data["objetos"]:
            x, y = item["x"] * scale, item["y"] * scale
            width, height = item["ancho"] * scale, item["alto"] * scale
            if item.get("tipo") == "imagen":
                picture = _add_picture(slide, item["imagen"], x, y, width, height)
                picture.rotation = _object_rotation(item)
                continue
            shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(width), Inches(height))
            shape.rotation = _object_rotation(item)
            frame = shape.text_frame
            frame.clear()
            frame.word_wrap = True
            frame.margin_left = Pt(3)
            frame.margin_right = Pt(3)
            frame.margin_top = Pt(3)
            frame.margin_bottom = Pt(3)
            frame.vertical_anchor = MSO_ANCHOR.TOP
            for line_index, line in enumerate(item["texto"].splitlines() or [""]):
                paragraph = frame.paragraphs[0] if line_index == 0 else frame.add_paragraph()
                paragraph.text = line
                paragraph.alignment = alignments[item["alineacion"]]
                paragraph.font.name = item["fuente"]
                paragraph.font.size = Pt(item["tamano"] * scale * 72)
                paragraph.font.bold = item["negrita"]
                paragraph.font.italic = item["cursiva"]
                paragraph.font.underline = item["subrayado"]
                paragraph.font.color.rgb = RGBColor.from_string(item["color"].lstrip("#"))
    presentation.core_properties.title = nombre
    output = BytesIO()
    presentation.save(output)
    return output.getvalue()
