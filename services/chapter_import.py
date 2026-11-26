"""Turns what the administrator uploads into an ordered list of web-ready JPEG pages.

Accepted: images (jpg, png, webp, gif, bmp), PDF, CBZ / ZIP, CBT / TAR (and a CBR that is really a ZIP, which is common).
A genuine RAR/CBR or 7z/CB7 archive cannot be opened on the server: the admin gets a clear message asking for CBZ.
"""
import io
import os
import re
import shutil
import tarfile
import tempfile
import zipfile

from PIL import Image, ImageChops, ImageOps

from config import Config

Image.MAX_IMAGE_PIXELS = 120_000_000          # refuse decompression bombs

IMAGE_EXT = {"jpg", "jpeg", "png", "webp", "gif", "bmp"}
MAX_PAGES = 400                                 # per upload (a chapter holds 500 at most)
MAX_UNPACKED = 700 * 1024 * 1024                # total size once an archive is opened
MAX_IMAGE_BYTES = 40 * 1024 * 1024
PDF_TARGET_WIDTH = 1400
WEBP_MAX_SIDE = 16383                           # WebP cannot encode a side longer than this: very tall webtoon strips fall back to JPEG
# Compression profiles for uploaded chapter pages: (max width in px, quality).  Webtoon pages are read on a phone: 900-1100 px is plenty.
PROFILES = {"eco": (900, 62), "normal": (1100, 72), "hd": (1400, 82)}
PROFILE_LABELS = {"eco": "Économique", "normal": "Équilibrée", "hd": "Haute qualité"}


class ImportFailure(Exception):
    """Message meant for the administrator (French)."""


class DiskFile:
    """An uploaded file saved to disk, with the small API of werkzeug's FileStorage that the readers use."""

    def __init__(self, path, filename):
        self.path, self.filename = path, filename
        self.stream = open(path, "rb")

    def save(self, dst):
        with open(self.path, "rb") as src:
            shutil.copyfileobj(src, dst)

    def close(self):
        try:
            self.stream.close()
        except Exception:
            pass


def natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def ext_of(name):
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _junk(name):
    parts = name.replace("\\", "/").split("/")
    return any(p.startswith(".") or p == "__MACOSX" or p.lower() in ("thumbs.db", "desktop.ini") for p in parts)


def optimise(data, max_width=None, quality=None):
    """-> (jpeg_bytes, width, height). Keeps a small JPEG untouched, otherwise recompresses (progressive JPEG)."""
    max_width = max_width or Config.PAGE_MAX_WIDTH
    quality = quality or Config.PAGE_JPEG_QUALITY
    if len(data) > MAX_IMAGE_BYTES:
        raise ImportFailure("Image trop lourde (40 Mo maximum par image).")
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        img.load()
    except Exception:
        raise ImportFailure("Fichier image illisible ou corrompu.")
    w, h = img.size
    if fmt == "JPEG" and w <= max_width and len(data) <= 350_000:     # already light: keep as is, anything bigger is recompressed
        return data, w, h
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    if img.width > max_width:
        img = img.resize((max_width, max(1, round(img.height * max_width / img.width))), Image.LANCZOS)
    if img.height > 65000:
        raise ImportFailure("Image trop haute (65 000 pixels maximum).")
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue(), img.width, img.height


def _flatten(img):
    """Orientation fixed, transparency flattened on white, always RGB (or L)."""
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img if img.mode in ("RGB", "L") else img.convert("RGB")


def _is_grayscale(img):
    """True for a black-and-white page stored as colour (very common for scans): saved as grey it is much lighter."""
    if img.mode == "L":
        return True
    t = img.resize((48, 48))
    r, g, b = t.split()
    return ImageChops.difference(r, g).getextrema()[1] <= 10 and ImageChops.difference(g, b).getextrema()[1] <= 10


def optimise_page(data, profile=None):
    """-> (bytes, width, height, mime). A chapter page converted for the database: resized to the profile's width, grey when the
    page has no colour, then WebP (or progressive JPEG when the strip is too tall for WebP). The original bytes are kept when they are
    already lighter than the conversion."""
    width, quality = PROFILES.get(profile) or PROFILES[Config.PAGE_PROFILE]
    if len(data) > MAX_IMAGE_BYTES:
        raise ImportFailure("Image trop lourde (40 Mo maximum par image).")
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        img.load()
    except Exception:
        raise ImportFailure("Fichier image illisible ou corrompu.")
    w0, h0 = img.size
    img = _flatten(img)
    if img.width > width:
        img = img.resize((width, max(1, round(img.height * width / img.width))), Image.LANCZOS)
    if img.height > 65000:
        raise ImportFailure("Image trop haute (65 000 pixels maximum).")
    if img.mode == "RGB" and _is_grayscale(img):
        img = img.convert("L")
    out = io.BytesIO()
    if img.height <= WEBP_MAX_SIDE:
        img.save(out, "WEBP", quality=quality, method=4)
        mime = "image/webp"
    else:
        img.save(out, "JPEG", quality=min(90, quality + 6), optimize=True, progressive=True)
        mime = "image/jpeg"
    result = out.getvalue()
    if fmt in ("JPEG", "WEBP") and w0 <= width and len(data) <= len(result):
        return data, w0, h0, "image/webp" if fmt == "WEBP" else "image/jpeg"      # the file was already lighter: keep it untouched
    return result, img.width, img.height, mime


# ------------------------------------------------------------------ readers (generators: one page in memory at a time)
def _from_zip(fobj):
    try:
        zf = zipfile.ZipFile(fobj)
    except zipfile.BadZipFile:
        raise ImportFailure("Archive ZIP/CBZ corrompue.")
    infos = [i for i in zf.infolist() if not i.is_dir() and not _junk(i.filename) and ext_of(i.filename) in IMAGE_EXT]
    if sum(i.file_size for i in infos) > MAX_UNPACKED:
        raise ImportFailure("Archive trop volumineuse une fois décompressée.")
    for info in sorted(infos, key=lambda i: natural_key(i.filename)):
        yield os.path.basename(info.filename), zf.read(info)


def _from_tar(fobj):
    try:
        tf = tarfile.open(fileobj=fobj)
    except tarfile.TarError:
        raise ImportFailure("Archive TAR/CBT illisible.")
    members = [m for m in tf.getmembers() if m.isfile() and not _junk(m.name) and ext_of(m.name) in IMAGE_EXT]
    if sum(m.size for m in members) > MAX_UNPACKED:
        raise ImportFailure("Archive trop volumineuse une fois décompressée.")
    for m in sorted(members, key=lambda m: natural_key(m.name)):
        yield os.path.basename(m.name), tf.extractfile(m).read()


def _from_pdf(file_storage):
    try:
        import pymupdf as fitz            # PyMuPDF >= 1.24.3
    except ImportError:
        try:
            import fitz
        except ImportError:
            raise ImportFailure("Le serveur ne sait pas encore lire les PDF (PyMuPDF manquant dans requirements.txt).")
    own = getattr(file_storage, "path", None)
    tmp = None if own else tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        if tmp:
            file_storage.save(tmp)
            tmp.close()
        try:
            doc = fitz.open(own or tmp.name)
        except Exception:
            raise ImportFailure("PDF illisible ou corrompu.")
        if doc.needs_pass:
            raise ImportFailure("Ce PDF est protégé par un mot de passe.")
        if doc.page_count > MAX_PAGES:
            raise ImportFailure(f"PDF trop long ({doc.page_count} pages, {MAX_PAGES} maximum par envoi).")
        for i in range(doc.page_count):
            page = doc.load_page(i)
            zoom = min(2.5, PDF_TARGET_WIDTH / max(page.rect.width, 1))
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            yield f"page-{i + 1:03d}.jpg", pix.tobytes("jpeg", jpg_quality=92)
        doc.close()
    finally:
        if tmp:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


def kind_of(file_storage):
    """'pdf' | 'zip' | 'tar' | 'image' | 'rar' | '7z' | None, from the file's magic bytes (extension as a fallback)."""
    s = file_storage.stream
    s.seek(0)
    head = s.read(8)
    s.seek(257)
    ustar = s.read(5)
    s.seek(0)
    name = file_storage.filename or ""
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        return "zip"
    if head.startswith(b"Rar!"):
        return "rar"
    if head.startswith(b"7z\xbc\xaf"):
        return "7z"
    if ustar == b"ustar" or head.startswith(b"\x1f\x8b"):
        return "tar"
    if ext_of(name) in IMAGE_EXT:
        return "image"
    return None


def ensure_supported(file_storage):
    """Raise ImportFailure right away (before any heavy work) for a format the server cannot open."""
    kind, name = kind_of(file_storage), file_storage.filename or "fichier"
    if kind in ("rar", "7z"):
        raise ImportFailure(f"« {name} » est une archive {kind.upper()} que le serveur ne peut pas ouvrir. "
                            "Convertis-la en CBZ (ZIP) ou en PDF, puis renvoie-la.")
    if kind is None:
        raise ImportFailure(f"Format non pris en charge : « {name} ». Formats : images, PDF, CBZ, ZIP, CBT.")
    return kind


def iter_pages(file_storage):
    """Yield (name, raw_image_bytes) in reading order for ONE uploaded file."""
    kind = kind_of(file_storage)
    name = file_storage.filename or "fichier"
    if kind == "pdf":
        yield from _from_pdf(file_storage)
    elif kind == "zip":
        yield from _from_zip(file_storage.stream)
    elif kind == "tar":
        yield from _from_tar(file_storage.stream)
    elif kind == "image":
        yield name, file_storage.stream.read()
    elif kind in ("rar", "7z"):
        raise ImportFailure(f"« {name} » est une archive {kind.upper()} que le serveur ne peut pas ouvrir. "
                            "Convertis-la en CBZ (ZIP) ou en PDF, puis renvoie-la.")
    else:
        raise ImportFailure(f"Format non pris en charge : « {name} ». Formats : images, PDF, CBZ, ZIP, CBT.")
