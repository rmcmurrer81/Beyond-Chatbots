"""Self-authored CC0 synthetic PDFs and annotation truth; stdlib only.

No external/private documents or borrowed graphs. The fixtures are generated at
test time. Annotation envelopes locate native text objects, not glyph-perfect
number boxes. PDF text relationships and reading order are deliberately unclaimed.
"""
from pathlib import Path
import zlib

ALPHA = [
    ("ALPHA01", "bolt length 12.5 mm"),
    ("ALPHA02", "rated voltage 11.1 V"),
    ("ALPHA03", "temperature offset -3.25 C"),
    ("ALPHA04", "mass 0.075 kg"),
    ("ALPHA05", "frequency 2.4e3 Hz"),
    ("ALPHA06", "diameter range 8-10 mm"),
    ("ALPHA07", "ratio 3:1"),
    ("ALPHA08", "current 1.20 A"),
    ("ALPHA09", "clearance 0.50 mm"),
    ("ALPHA10", "duration 45 s"),
]
BETA = [
    ("BETA01", "bolt length 99.0 mm"),
    ("BETA02", "rated voltage 24.0 V"),
    ("BETA03", "temperature offset -0.50 C"),
    ("BETA04", "mass 7.125 kg"),
    ("BETA05", "frequency 6.5e2 Hz"),
    ("BETA06", "diameter range 20-22 mm"),
    ("BETA07", "ratio 7:2"),
    ("BETA08", "current 0.08 A"),
    ("BETA09", "clearance 4.00 mm"),
    ("BETA10", "duration 180 s"),
]


def _literal(value):
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _stream(raw, extra=b""):
    return b"<< /Length " + str(len(raw)).encode() + extra + b" >>\nstream\n" + raw + b"\nendstream"


def _document(objects):
    result = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(str(number).encode() + b" 0 obj\n" + obj + b"\nendobj\n")
    xref = len(result)
    result.extend(b"xref\n0 " + str(len(objects) + 1).encode() + b"\n")
    result.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(b"trailer\n<< /Size " + str(len(objects) + 1).encode() +
                  b" /Root 1 0 R >>\nstartxref\n" + str(xref).encode() + b"\n%%EOF\n")
    return bytes(result)


def native_pdf(rows, *, rotation=0, crop=None, form=False):
    """Two pages/five objects each; returns bytes and authored truth envelopes."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"]
    pages, truth = [], []
    for offset in range(0, len(rows), 5):
        page_number = len(pages) + 1
        page_index = len(objects) + 1
        objects.append(b"")
        content_index = len(objects) + 1
        objects.append(b"")
        annotations, lines = [], []
        for object_index, (anchor, value) in enumerate(rows[offset:offset + 5]):
            y = 700 - object_index * 60
            text = anchor + " " + value + "."
            lines.append(f"BT /F1 12 Tf 1 0 0 1 50 {y} Tm ({_literal(text)}) Tj ET")
            envelope = [49, y - 5, 565, y + 15]
            annotation_index = len(objects) + 1
            objects.append((f"<< /Type /Annot /Subtype /Square /Rect [49 {y-5} 565 {y+15}] "
                            f"/C [0 0 1] /Contents ({anchor} source envelope) >>").encode())
            annotations.append(f"{annotation_index} 0 R")
            truth.append({"question": f"What does {anchor} state?",
                          "anchor": anchor, "expected": text, "page": page_number,
                          "object_index": object_index, "envelope": envelope})
        raw = "\n".join(lines).encode("ascii")
        resources = "/Font << /F1 3 0 R >>"
        if form:
            form_index = len(objects) + 1
            objects.append(_stream(raw, b" /Type /XObject /Subtype /Form /BBox [0 0 612 792]"
                                   b" /Resources << /Font << /F1 3 0 R >> >>"))
            raw = b"/Fm1 Do"
            resources += f" /XObject << /Fm1 {form_index} 0 R >>"
        objects[content_index - 1] = _stream(raw)
        crop_text = "" if crop is None else " /CropBox [" + " ".join(map(str, crop)) + "]"
        objects[page_index - 1] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Rotate {rotation}"
            f"{crop_text} /Resources << {resources} >> /Contents {content_index} 0 R "
            f"/Annots [{' '.join(annotations)}] >>").encode()
        pages.append(f"{page_index} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(pages)}] /Count {len(pages)} >>".encode()
    return _document(objects), truth


def scanned_pdf():
    """Image-only negative: a self-authored bitmap pattern, no native text."""
    width, height = 64, 16
    pixels = bytes(0 if ((x // 4 + y // 4) % 2) else 255
                   for y in range(height) for x in range(width))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources"
        b" << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>",
        _stream(b"q 256 0 0 64 50 600 cm /Im1 Do Q"),
        _stream(zlib.compress(pixels), b" /Type /XObject /Subtype /Image /Width 64"
                b" /Height 16 /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode"),
    ]
    return _document(objects)


def write_fixtures(folder):
    """Create local files and truth dictionaries; never upload the generated PDFs."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    output = []
    for name, rows in (("alpha", ALPHA), ("beta", BETA)):
        raw, truth = native_pdf(rows)
        path = folder / (name + ".pdf")
        path.write_bytes(raw)
        output.append((path, truth))
    scanned = folder / "scanned.pdf"
    scanned.write_bytes(scanned_pdf())
    return output, scanned
