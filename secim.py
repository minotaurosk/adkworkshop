"""Eser seçim aracı: kaynak klasörlerdeki (Google Drive) fotoğraflardan eserleri seçip works/'e aktarır.

  python secim.py        → http://127.0.0.1:8771/ tarayıcıda açılır (sadece bu bilgisayardan erişilir)

Seçimler secim.json'da durur (eserler, kategoriler; yollar kaynak adıyla başlar: "Workshop Studies/Wooden/x.jpg").
"works'e aktar" her eseri works/<NN-kategori>/ altına kopyalar (+ info.txt); aracın kendi yazdıklarını
works/.secim-manifest.json'da tutar, bir sonraki aktarımda sadece onları günceller/siler (elle eklenenlere dokunmaz).
"""
import hashlib
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageOps

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(ROOT, "secim.json")
CACHE = os.path.join(ROOT, ".cache", "thumbs")
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff", ".bmp"}
PORT = 8771

DEFAULT_CATS = [
    ("wood-sculpture", "Wood Sculpture", "Ahşap Heykel"),
    ("olive-wood", "Olive Wood", "Zeytin Ağacı"),
    ("jewelry", "Jewelry", "Takı"),
    ("resin-furniture", "Resin & Furniture", "Reçine ve Mobilya"),
    ("clay", "Clay & Ceramics", "Kil ve Seramik"),
    ("miniatures", "Miniatures & Painting", "Minyatür ve Boyama"),
    ("models-props", "Models, Toys & Props", "Maket, Oyuncak ve Kostüm"),
    ("casting-signs", "Casting & Signs", "Döküm ve Tabela"),
    ("drawings", "Drawings", "Çizimler"),
    ("ai", "AI Studies", "Yapay Zekâ Çalışmaları"),
]

# Kendi fotoğrafı gibi duran adlar (kamera / telefon / tarihli) — bunlar dışındakiler "referans olabilir" işareti alır
OWN_RX = re.compile(r"^(img|dsc|dscn|dji|pxl|vid|mvimg|_mg|p\d{6,}|\d{8}|\d{4}[-_.]\d{2}[-_.]\d{2}|img-\d{8}|screenshot|\d{6}_)", re.I)
REF_RX = re.compile(r"(il_\d+x|_orig\b|thumb|[0-9a-f]{16,}|^\d{5,}[-_]|-\d{3,4}x\d{3,4}|pinterest|etsy|amazon)", re.I)


def load_cfg():
    with open(os.path.join(ROOT, "site.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    src = cfg.get("sources") or {}
    if not src and cfg.get("source_dir"):
        src = {os.path.basename(cfg["source_dir"].rstrip("\\/")): cfg["source_dir"]}
    return cfg, src


CFG, SOURCES = load_cfg()
LOCK = threading.Lock()


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    st.setdefault("categories", [{"id": i, "en": e, "tr": t} for i, e, t in DEFAULT_CATS])
    st.setdefault("works", [])
    return st


def save_state(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def real(p):
    """'Kaynak adı/alt/yol' → gerçek yol; kaynak dışına çıkamaz."""
    p = p.replace("\\", "/").strip("/")
    name, _, rest = p.partition("/")
    base = SOURCES.get(name)
    if not base:
        raise ValueError("bilinmeyen kaynak")
    full = os.path.normpath(os.path.join(base, rest))
    if os.path.commonpath([os.path.normpath(base), full]) != os.path.normpath(base):
        raise ValueError("yol dışarıda")
    return full


def suspect(name):
    stem = os.path.splitext(name)[0]
    if OWN_RX.match(stem):
        return False
    return bool(REF_RX.search(stem)) or os.path.splitext(name)[1].lower() in (".png", ".gif", ".webp") and not re.search(r"\d{4}", stem)


_TREE = {"t": None}


def tree():
    """Klasör ağacı: [{path, name, n (doğrudan resim sayısı), total, kids}]"""
    if _TREE["t"] is not None:
        return _TREE["t"]

    def walk(path, rel):
        try:
            entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
        except OSError:
            return None
        kids, n = [], 0
        for e in entries:
            if e.name.startswith((".", "$")) or e.name.lower() == "desktop.ini":
                continue
            if e.is_dir():
                k = walk(e.path, rel + "/" + e.name)
                if k and k["total"]:
                    kids.append(k)
            elif os.path.splitext(e.name)[1].lower() in IMG_EXT:
                n += 1
        return {"path": rel, "name": rel.rsplit("/", 1)[-1], "n": n, "total": n + sum(k["total"] for k in kids), "kids": kids}

    out = [t for t in (walk(base, name) for name, base in SOURCES.items()) if t]
    _TREE["t"] = out
    return out


def folder(rel):
    full = real(rel)
    out = []
    for e in sorted(os.scandir(full), key=lambda e: e.name.lower()):
        if e.is_file() and os.path.splitext(e.name)[1].lower() in IMG_EXT:
            st = e.stat()
            out.append({"path": rel + "/" + e.name, "name": e.name, "size": st.st_size, "ref": suspect(e.name)})
    return out


def thumb(rel, size):
    full = real(rel)
    st = os.stat(full)
    key = hashlib.sha1(f"{full}|{st.st_size}|{int(st.st_mtime)}|{size}".encode()).hexdigest()
    fn = os.path.join(CACHE, key[:2], key + ".jpg")
    if not os.path.isfile(fn):
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        with Image.open(full) as im:
            im.seek(0)
            if im.format == "JPEG":
                im.draft("RGB", (size * 2, size * 2))
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", im.size, (240, 240, 240))
                im = im.convert("RGBA")
                bg.paste(im, mask=im.split()[-1])
                im = bg
            im = im.convert("RGB")
            im.thumbnail((size, size), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=82)
        with open(fn + ".tmp", "wb") as f:
            f.write(buf.getvalue())
        os.replace(fn + ".tmp", fn)
    return fn


# ------------------------------------------------------------------ works/'e aktarma
def slug(s):
    s = s.replace("ı", "i").replace("İ", "i")
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "eser"


def export(st):
    works_dir = os.path.join(ROOT, os.path.expandvars(CFG.get("works_dir", "works")))
    os.makedirs(works_dir, exist_ok=True)
    man_path = os.path.join(works_dir, ".secim-manifest.json")
    try:
        with open(man_path, encoding="utf-8") as f:
            old = set(json.load(f))
    except (OSError, ValueError):
        old = set()
    cats = {c["id"]: (i + 1, c) for i, c in enumerate(st["categories"])}
    written, copied, used_names = set(), 0, set()

    def put(src_rel, dst):
        nonlocal copied
        written.add(os.path.relpath(dst, works_dir))
        src = real(src_rel)
        if os.path.isfile(dst) and os.path.getsize(dst) == os.path.getsize(src):
            return
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1

    def put_text(dst, text):
        written.add(os.path.relpath(dst, works_dir))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            with open(dst, encoding="utf-8") as f:
                if f.read() == text:
                    return
        except OSError:
            pass
        with open(dst, "w", encoding="utf-8") as f:
            f.write(text)

    for cid, (order, c) in cats.items():
        if any(w["cat"] == cid for w in st["works"]):
            cdir = os.path.join(works_dir, f"{order:02d}-{c['id']}")
            put_text(os.path.join(cdir, "_category.txt"), f"en: {c['en']}\ntr: {c['tr']}\n")
    for w in st["works"]:
        if w["cat"] not in cats or not w["images"]:
            continue
        order, c = cats[w["cat"]]
        cdir = os.path.join(works_dir, f"{order:02d}-{c['id']}")
        y = str(w.get("year") or "").strip()
        base = (f"{y}_" if y else "") + slug(w.get("title") or "eser")
        name, n = base, 2
        while (cdir, name) in used_names:
            name, n = f"{base}-{n}", n + 1
        used_names.add((cdir, name))
        info = [f"title: {w.get('title', '')}"]
        for k, lab in (("title_tr", "başlık"), ("year", "year"), ("tags", "tags"), ("desc", "desc"), ("desc_tr", "açıklama")):
            if str(w.get(k) or "").strip():
                info.append(f"{lab}: {str(w[k]).strip()}")
        if w.get("featured"):
            info.append("featured: yes")
        text = "\n".join(info) + "\n"
        if len(w["images"]) == 1:
            ext = os.path.splitext(w["images"][0])[1].lower()
            put(w["images"][0], os.path.join(cdir, name + ext))
            put_text(os.path.join(cdir, name + ".txt"), text)
        else:
            d = os.path.join(cdir, name)
            for i, p in enumerate(w["images"], 1):
                put(p, os.path.join(d, f"{i:02d}{os.path.splitext(p)[1].lower()}"))
            put_text(os.path.join(d, "info.txt"), text)
    removed = 0
    for rel in old - written:
        p = os.path.join(works_dir, rel)
        if os.path.isfile(p):
            os.remove(p)
            removed += 1
    for dp, dn, fn in os.walk(works_dir, topdown=False):
        if dp != works_dir and not os.listdir(dp):
            os.rmdir(dp)
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(sorted(written), f, ensure_ascii=False, indent=0)
    return {"works": sum(1 for w in st["works"] if w["images"]), "copied": copied, "removed": removed}


# ------------------------------------------------------------------ sunucu
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8", cache=False):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def file(self, fn, cache=True):
        with open(fn, "rb") as f:
            data = f.read()
        self.send(200, data, mimetypes.guess_type(fn)[0] or "application/octet-stream", cache)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path == "/":
                return self.file(os.path.join(ROOT, "tools", "secim.html"), cache=False)
            if u.path == "/api/tree":
                if q.get("fresh"):
                    _TREE["t"] = None
                return self.send(200, tree())
            if u.path == "/api/folder":
                return self.send(200, folder(q["p"]))
            if u.path == "/api/state":
                with LOCK:
                    return self.send(200, load_state())
            if u.path in ("/thumb", "/big"):
                return self.file(thumb(q["p"], 360 if u.path == "/thumb" else 1600))
            if u.path.startswith("/site/"):
                rel = urllib.parse.unquote(u.path[6:]) or "index.html"
                fn = os.path.normpath(os.path.join(ROOT, "docs", rel))
                if os.path.isdir(fn):
                    fn = os.path.join(fn, "index.html")
                if not fn.startswith(os.path.join(ROOT, "docs")) or not os.path.isfile(fn):
                    return self.send(404, "yok", "text/plain")
                return self.file(fn, cache=False)
            self.send(404, {"error": "yok"})
        except (ValueError, KeyError, OSError) as e:
            self.send(400, {"error": str(e)})

    def do_POST(self):
        if self.headers.get("X-Secim") != "1":           # başka sitelerden gelen istekleri reddet
            return self.send(403, {"error": "yasak"})
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        try:
            if self.path == "/api/state":
                with LOCK:
                    save_state(body)
                return self.send(200, {"ok": True})
            if self.path == "/api/export":
                with LOCK:
                    st = load_state()
                    res = export(st)
                r = subprocess.run([sys.executable, os.path.join(ROOT, "build.py")], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", cwd=ROOT)
                res["build"] = (r.stdout + r.stderr).strip()[-1500:]
                res["ok"] = r.returncode == 0
                return self.send(200, res)
            self.send(404, {"error": "yok"})
        except (ValueError, KeyError, OSError) as e:
            self.send(400, {"error": str(e)})


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    for name, p in SOURCES.items():
        print(f"Kaynak: {name} → {p}" + ("" if os.path.isdir(p) else "  (BULUNAMADI)"))
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Seçim aracı: {url}  (kapatmak için bu pencereyi kapat)")
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    srv.serve_forever()


if __name__ == "__main__":
    main()
