from __future__ import annotations

from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
import zipfile

from PIL import Image, ImageOps


REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
IMAGE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
XML_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
EMU_PER_INCH = 914400


def compose_word_format(
    template_path: Path,
    credential_image_path: Path,
    identification_image_path: Path,
    output_path: Path,
) -> Path:
    if not template_path.exists():
        raise FileNotFoundError(f"No se encontró el formato Word: {template_path}")
    if not credential_image_path.exists():
        raise FileNotFoundError(f"No se encontró la credencial generada: {credential_image_path}")
    if not identification_image_path.exists():
        raise FileNotFoundError(f"No se encontró la identificación original: {identification_image_path}")

    with zipfile.ZipFile(template_path, "r") as source:
        document_xml = source.read("word/document.xml")
        rels_xml = source.read("word/_rels/document.xml.rels")
        drawings = _extract_picture_drawings(document_xml)
        if len(drawings) < 2:
            raise ValueError("El formato Word debe contener al menos dos imágenes placeholder.")

        top, bottom = sorted(drawings[:2], key=lambda item: item["y"])
        credential_bytes = _image_as_placeholder_jpeg(
            credential_image_path,
            aspect_ratio=top["cx"] / top["cy"],
        )
        identification_bytes = _image_as_placeholder_jpeg(
            identification_image_path,
            aspect_ratio=bottom["cx"] / bottom["cy"],
            force_landscape=True,
            rotate_180=True,
        )
        rels_patched, credential_rid, identification_rid = _add_image_relationships(rels_xml)
        document_patched = _replace_image_refs_by_document_order(
            document_xml,
            drawings=drawings[:2],
            top_y=top["y"],
            top_rid=credential_rid,
            bottom_rid=identification_rid,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for item in source.infolist():
                if item.filename in {
                    "word/document.xml",
                    "word/_rels/document.xml.rels",
                    "word/media/cruztitla_credential.jpeg",
                    "word/media/cruztitla_identification.jpeg",
                }:
                    continue
                target.writestr(item, source.read(item.filename))

            target.writestr("word/document.xml", document_patched)
            target.writestr("word/_rels/document.xml.rels", rels_patched)
            target.writestr("word/media/cruztitla_credential.jpeg", credential_bytes)
            target.writestr("word/media/cruztitla_identification.jpeg", identification_bytes)

    return output_path


def _extract_picture_drawings(document_xml: bytes) -> list[dict[str, int | str]]:
    root = ET.fromstring(document_xml)
    drawings: list[dict[str, int | str]] = []
    for drawing in root.findall(".//w:drawing", XML_NS):
        extent = drawing.find(".//wp:extent", XML_NS)
        blip = drawing.find(".//a:blip", XML_NS)
        if extent is None or blip is None:
            continue
        rid = blip.attrib.get(f"{{{XML_NS['r']}}}embed")
        if not rid:
            continue
        drawings.append(
            {
                "rid": rid,
                "cx": int(extent.attrib["cx"]),
                "cy": int(extent.attrib["cy"]),
                "y": _drawing_vertical_position(drawing),
            }
        )
    return drawings


def _drawing_vertical_position(drawing: ET.Element) -> int:
    pos_v = drawing.find(".//wp:positionV", XML_NS)
    if pos_v is None:
        return 0
    offset = pos_v.find(".//wp:posOffset", XML_NS)
    if offset is None or offset.text is None:
        return 0
    return int(offset.text)


def _image_as_placeholder_jpeg(
    image_path: Path,
    aspect_ratio: float,
    *,
    force_landscape: bool = False,
    rotate_180: bool = False,
) -> bytes:
    canvas_width = 1800
    canvas_height = max(1, round(canvas_width / aspect_ratio))

    image = Image.open(image_path)
    image = ImageOps.exif_transpose(image).convert("RGB")
    if force_landscape and image.height > image.width:
        image = image.rotate(-90, expand=True)
    if rotate_180:
        image = image.rotate(180, expand=True)
    image = _fit_cover(image, (canvas_width, canvas_height))

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=94, optimize=True)
    return buffer.getvalue()


def _fit_cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    src_w, src_h = image.size
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        crop_w = round(src_h * target_ratio)
        left = max(0, (src_w - crop_w) // 2)
        box = (left, 0, left + crop_w, src_h)
    else:
        crop_h = round(src_w / target_ratio)
        top = max(0, (src_h - crop_h) // 2)
        box = (0, top, src_w, top + crop_h)

    return image.crop(box).resize(size, Image.Resampling.LANCZOS)


def _add_image_relationships(rels_xml: bytes) -> tuple[bytes, str, str]:
    root = ET.fromstring(rels_xml)
    existing_ids = [rel.attrib.get("Id", "") for rel in root.findall(f"{{{REL_NS}}}Relationship")]
    next_number = _next_relationship_number(existing_ids)
    credential_rid = f"rId{next_number}"
    identification_rid = f"rId{next_number + 1}"

    additions = (
        f'<Relationship Id="{credential_rid}" Type="{IMAGE_REL_TYPE}" '
        'Target="media/cruztitla_credential.jpeg"/>'
        f'<Relationship Id="{identification_rid}" Type="{IMAGE_REL_TYPE}" '
        'Target="media/cruztitla_identification.jpeg"/>'
    ).encode("utf-8")
    return rels_xml.replace(b"</Relationships>", additions + b"</Relationships>", 1), credential_rid, identification_rid


def _next_relationship_number(existing_ids: list[str]) -> int:
    numbers = []
    for rid in existing_ids:
        if rid.startswith("rId") and rid[3:].isdigit():
            numbers.append(int(rid[3:]))
    return (max(numbers) if numbers else 0) + 1


def _replace_image_refs_by_document_order(
    document_xml: bytes,
    *,
    drawings: list[dict[str, int | str]],
    top_y: int,
    top_rid: str,
    bottom_rid: str,
) -> bytes:
    patched = document_xml
    for drawing in drawings:
        replacement = top_rid if drawing["y"] == top_y else bottom_rid
        old = f'r:embed="{drawing["rid"]}"'.encode("utf-8")
        new = f'r:embed="{replacement}"'.encode("utf-8")
        if old not in patched:
            old = f'embed="{drawing["rid"]}"'.encode("utf-8")
            new = f'embed="{replacement}"'.encode("utf-8")
        if old not in patched:
            raise ValueError("No se pudo ubicar la referencia de imagen en el formato Word.")
        patched = patched.replace(old, new, 1)
    return patched
