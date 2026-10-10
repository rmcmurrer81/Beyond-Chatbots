"""Owned isolated perception worker. Never import this script to invoke OCR.

The parent creates this Python process in a Windows Job before its first instruction.
Pillow import/decoding and the one Tesseract child are inside that same owned Job.
"""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import warnings


def _native_tsv(engine, derived, model, api):
    """Bound both pipes during production; never communicate() unbounded output."""
    environment = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH", "TMP", "TEMP")
                   if key in os.environ}
    environment.update({"OMP_THREAD_LIMIT": "1", "OMP_NUM_THREADS": "1"})
    argv = [str(engine), str(derived), "stdout", "--tessdata-dir", str(model.parent),
            "-l", "eng", "--oem", "1", "--psm", "11", "-c", "tessedit_create_tsv=1",
            "-c", "load_system_dawg=0", "-c", "load_freq_dawg=0"]
    process = subprocess.Popen(argv, executable=str(engine), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True, shell=False,
        cwd=str(derived.parent), env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    overflow, failures = threading.Event(), []
    def drain(stream, name, maximum):
        try:
            while True:
                block = stream.read(4096)
                if not block:
                    break
                if len(chunks[name]) + len(block) > maximum:
                    overflow.set()
                    break
                chunks[name].extend(block)
        except Exception:
            failures.append(name)
            overflow.set()
        finally:
            stream.close()
    threads = [
        threading.Thread(target=drain, args=(process.stdout, "stdout", api.MAX_TSV), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, "stderr", 16384), daemon=True),
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 4.0
    refused = False
    try:
        while process.poll() is None:
            if overflow.is_set() or time.monotonic() >= deadline:
                refused = True
                process.kill()  # This returned owned native child only; parent Job owns descendants.
                break
            time.sleep(0.01)
        process.wait(timeout=0.5)
        for thread in threads:
            thread.join(timeout=0.25)
        if refused or overflow.is_set() or failures or any(thread.is_alive() for thread in threads):
            raise api.OcrError("Native output or timeout bound")
        if process.returncode != 0:
            raise api.OcrError("Native engine refused the image")
        return bytes(chunks["stdout"])
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=0.5)


class _BoundedBuffer(io.BytesIO):
    def __init__(self, maximum):
        super().__init__()
        self.maximum = maximum

    def write(self, value):
        if self.tell() + len(value) > self.maximum:
            raise ValueError("Derived byte bound")
        return super().write(value)


def _perceive(request_path):
    # -I -S excludes ambient module paths/site customization; use only pinned code and Pillow root.
    directory = Path(__file__).absolute().parent
    sys.path.insert(0, str(directory))
    import photo_ocr as api
    request_path = api._local(request_path)
    if request_path.name != "request.json" or Path.cwd().resolve() != request_path.parent.resolve():
        raise api.OcrError("Worker request location")
    request = api.decode_json(api._read(request_path, 8192), 8192)
    api._keys(request, {"format", "input_sha256", "input_bytes", "media_type", "engine", "model",
                       "pillow_root", "pillow_version", "engine_sha256", "model_sha256"})
    if request["format"] != "photo-ocr.worker-request.v1":
        raise api.OcrError("Worker format")
    api._hash(request["input_sha256"])
    api._integer(request["input_bytes"], 1, api.MAX_IMAGE)
    api._choice(request["media_type"], {"image/png", "image/jpeg", "image/webp"})
    engine, model, pillow_root = (api._local(request[x]) for x in ("engine", "model", "pillow_root"))
    if model.name != "eng.traineddata":
        raise api.OcrError("Model identity")
    for path, name, maximum in ((engine, "engine_sha256", 128 * 1048576),
                                (model, "model_sha256", 16 * 1048576)):
        if hashlib.sha256(api._read(path, maximum)).hexdigest() != api._hash(request[name]):
            raise api.OcrError("Worker runtime pin mismatch")
    original = api._read(request_path.parent / "input.bin", api.MAX_IMAGE)
    if len(original) != request["input_bytes"] or hashlib.sha256(original).hexdigest() != request["input_sha256"]:
        raise api.OcrError("Worker original pin mismatch")
    signatures = {
        "image/png": original.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": original.startswith(b"\xff\xd8\xff"),
        "image/webp": len(original) >= 12 and original[:4] == b"RIFF" and original[8:12] == b"WEBP",
    }
    if not signatures[request["media_type"]]:
        raise api.OcrError("Image signature mismatch")
    sys.path.insert(0, str(pillow_root))
    import PIL
    from PIL import Image
    if PIL.__version__ != request["pillow_version"]:
        raise api.OcrError("Pillow version mismatch")
    try:
        Path(PIL.__file__).resolve().relative_to(pillow_root.resolve())
    except ValueError as exc:
        raise api.OcrError("Pillow location mismatch") from exc
    Image.MAX_IMAGE_PIXELS = api.MAX_PIXELS
    expected = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}[request["media_type"]]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with Image.open(io.BytesIO(original), formats=["PNG", "JPEG", "WEBP"]) as image:
            width, height = image.size
            api._integer(width, 1, api.MAX_PIXELS)
            api._integer(height, 1, api.MAX_PIXELS)
            if width * height > api.MAX_PIXELS or image.format != expected:
                raise api.OcrError("Image geometry or format bound")
            if getattr(image, "n_frames", 1) != 1:
                raise api.OcrError("Multiframe image unsupported")
            # Size/frame checks precede load; no EXIF orientation inference or user metadata is retained.
            image.load()
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                white.alpha_composite(rgba)
                rgb = white.convert("RGB")
            else:
                rgb = image.convert("RGB")
            # Fresh pixel object has no copied EXIF, comments, label metadata, or filename.
            clean = Image.frombytes("RGB", (width, height), rgb.tobytes())
            derived_buffer = _BoundedBuffer(api.MAX_DERIVED)
            clean.save(derived_buffer, format="PNG", optimize=False, compress_level=6)
            derived = derived_buffer.getvalue()
    derived_path = request_path.parent / "derived.png"
    api._write_new(derived_path, derived, api.MAX_DERIVED)
    raw_tsv = _native_tsv(engine, derived_path, model, api)
    words = api.parse_tsv(raw_tsv, width, height)
    return {"format": "photo-ocr.worker-result.v1", "input_sha256": request["input_sha256"],
            "input_bytes": request["input_bytes"], "derived_sha256": hashlib.sha256(derived).hexdigest(),
            "width": width, "height": height, "transform": "identity-no-exif",
            "tsv_sha256": hashlib.sha256(raw_tsv).hexdigest(), "words": words}


def main():
    if os.name != "nt" or len(sys.argv) != 2:
        raise ValueError("Supported isolated Windows worker invocation required")
    value = _perceive(Path(sys.argv[1]))
    # Import is already pinned and has no native initialization.
    import photo_ocr as api
    sys.stdout.buffer.write(api.canonical_bytes(value))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Private original/recognized text/path data never leaks into exception messages.
        sys.stderr.write("Local perception worker refused the request.\n")
        raise SystemExit(2)
