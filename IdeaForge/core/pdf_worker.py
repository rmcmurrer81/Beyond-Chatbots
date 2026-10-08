"""Task-owned model-free PDF worker. No network, OCR, rendering or model calls."""
from __future__ import annotations

import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import sys
import time

SCHEMA = "ideaforge.local-pdf.v1"
BACKEND_VERSION = "5.14.0"


class UnsupportedPDF(ValueError):
    pass


def _finite_box(value):
    values = [float(v) for v in value]
    if (len(values) != 4 or not all(math.isfinite(v) for v in values) or
            values[0] >= values[2] or values[1] >= values[3]):
        raise UnsupportedPDF("invalid_native_box")
    return values


def extract(source, limits):
    """Only top-level axis-aligned objects on uncropped zero-origin pages."""
    if version("pypdfium2") != BACKEND_VERSION:
        raise UnsupportedPDF("unsupported_backend_version")
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw_pdfium

    deadline = time.monotonic() + limits["seconds"]

    def check():
        if time.monotonic() > deadline:
            raise UnsupportedPDF("native_deadline_exceeded")

    with Path(source).open("rb") as stream:
        source_bytes = stream.read(limits["file_bytes"] + 1)
    if len(source_bytes) > limits["file_bytes"]:
        raise UnsupportedPDF("file_byte_limit")
    check()
    pages = []
    total_chars = total_passages = 0
    # Bind immutable in-memory bytes, not a file that might change under PDFium.
    with pdfium.PdfDocument(source_bytes) as document:
        if not 1 <= len(document) <= limits["pages"]:
            raise UnsupportedPDF("page_limit")
        for page_number in range(len(document)):
            check()
            with document[page_number] as page:
                if page.get_rotation() != 0:
                    raise UnsupportedPDF("rotated_page_unsupported")
                page_box = _finite_box(page.get_bbox())
                media = page.get_mediabox(fallback_ok=False)
                if media is None:
                    raise UnsupportedPDF("inherited_media_box_unverified")
                media = _finite_box(media)
                if (page_box[0] != 0 or page_box[1] != 0 or
                        any(abs(a - b) > .0001 for a, b in zip(page_box, media))):
                    raise UnsupportedPDF("crop_or_page_origin_unsupported")
                passages = []
                with page.get_textpage() as textpage:
                    character_count = textpage.count_chars()
                    if character_count > limits["total_chars"]:
                        raise UnsupportedPDF("native_character_limit")
                    # Unicode decoding success alone cannot detect bad font maps.
                    for index in range(character_count):
                        if index % 256 == 0:
                            check()
                        mapping = raw_pdfium.FPDFText_HasUnicodeMapError(textpage, index)
                        if mapping != 0:
                            raise UnsupportedPDF("unicode_mapping_unverified")
                    # Do not filter to TEXT: FORM objects must remain detectable.
                    for object_index, obj in enumerate(page.get_objects(
                            max_depth=1, textpage=textpage)):
                        check()
                        if object_index >= limits["objects_per_page"]:
                            raise UnsupportedPDF("native_object_limit")
                        if obj.type == raw_pdfium.FPDF_PAGEOBJ_FORM:
                            raise UnsupportedPDF("form_xobject_unsupported")
                        if obj.type != raw_pdfium.FPDF_PAGEOBJ_TEXT:
                            continue
                        matrix = obj.get_matrix()
                        if (not all(math.isfinite(v) for v in
                                    (matrix.a, matrix.b, matrix.c, matrix.d,
                                     matrix.e, matrix.f)) or
                                matrix.a <= 0 or matrix.d <= 0 or
                                abs(matrix.b) > .0001 or abs(matrix.c) > .0001):
                            raise UnsupportedPDF("text_transform_unsupported")
                        # extract() uses strict UTF-16; retain its string verbatim.
                        text = obj.extract()
                        if not text:
                            continue
                        text.encode("utf-8", errors="strict")
                        if len(text) > limits["object_chars"]:
                            raise UnsupportedPDF("native_object_text_limit")
                        total_chars += len(text)
                        if total_chars > limits["total_chars"]:
                            raise UnsupportedPDF("native_character_limit")
                        box = _finite_box(obj.get_bounds())
                        if (box[0] < page_box[0] or box[1] < page_box[1] or
                                box[2] > page_box[2] or box[3] > page_box[3]):
                            raise UnsupportedPDF("clipped_text_object_unsupported")
                        passages.append({"object_index": object_index,
                                         "text": text, "bbox": box})
                        total_passages += 1
                pages.append({"page": page_number + 1, "bbox": page_box,
                              "rotation": 0, "passages": passages,
                              "native_text_status": ("native_text_present" if passages else
                                  "no_extractable_native_text_unsupported_image_or_blank")})
    if not total_passages:
        raise UnsupportedPDF("no_native_text_scanned_or_image_only_unsupported")
    check()
    return {"schema": SCHEMA, "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "backend": {"package": "pypdfium2", "version": BACKEND_VERSION,
                        "pdfium_version": str(pdfium.PDFIUM_INFO)},
            "pages": pages}


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 3:
        return 2
    source, output, serialized_limits = arguments
    try:
        limits = json.loads(serialized_limits)
        # Parent validates Limits; independently reject arbitrary direct-worker input.
        caps = {"file_bytes": 8_000_000, "pages": 25, "objects_per_page": 2000,
                "object_chars": 2000, "total_chars": 100_000,
                "result_bytes": 2_000_000, "seconds": 30.0}
        if not isinstance(limits, dict) or set(limits) != set(caps):
            raise UnsupportedPDF("invalid_limits")
        for name, cap in caps.items():
            value = limits[name]
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                    not 0 < value <= cap or (isinstance(value, float) and not math.isfinite(value)) or
                    (name != "seconds" and not isinstance(value, int))):
                raise UnsupportedPDF("invalid_limits")
        result = {"ok": True, "report": extract(source, limits)}
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > limits["result_bytes"]:
            raise UnsupportedPDF("extraction_result_byte_limit")
        Path(output).write_bytes(encoded)
        return 0
    except UnsupportedPDF as exc:
        error = str(exc)
    except (UnicodeError,):
        error = "native_unicode_decode_failed"
    except Exception:
        # Never expose native exception strings or private text in worker failures.
        error = "native_extraction_failed_or_dependency_unavailable"
    Path(output).write_text(json.dumps({"ok": False, "error": error}), encoding="utf-8")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
