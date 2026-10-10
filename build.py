"""ADK Workshop sitesini üretir: works/ klasöründeki resimler → docs/ (GitHub Pages).

Klasör düzeni (ayrıntılar README.md'de):
  works/<kategori>/<eser>.jpg              tek resimli eser
  works/<kategori>/<eser>.txt              (isteğe bağlı) başlık, açıklama, yıl, etiketler
  works/<kategori>/<eser klasörü>/*.jpg    çok resimli eser (ilk resim kapak) + info.txt
  works/<kategori>/_category.txt           (isteğe bağlı) kategori adı en/tr, sıra

Kullanım: python build.py [--works <klasör>] [--out <klasör>]
Resimler bir kez küçültülür (640 ve 1600 px WebP, EXIF/GPS bilgisi atılır); kaynak değişmedikçe yeniden üretilmez.
"""
import argparse
import datetime
import html
import json
import os
import re
import shutil
import sys
import unicodedata

from PIL import Image, ImageOps

ROOT = os.path.dirname(os.path.abspath(__file__))
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff", ".bmp"}
SIZES = (640, 1600)
LANGS = ("en", "tr")

T = {
    "en": {"home": "Home", "works": "Works", "all": "All", "about": "About", "contact": "Contact",
           "featured": "Selected works", "see_all": "See all works", "categories": "Categories",
           "made": "Made in the workshop", "tools": "Tools we build", "visit": "Visit site",
           "prev": "Previous", "next": "Next", "back": "Back to", "n_works": "{n} works", "one_work": "1 work",
           "empty": "The gallery is being prepared. New works are coming soon.", "lang": "Türkçe",
           "nf_title": "Page not found", "nf_text": "The page you are looking for does not exist.",
           "write": "Write to us"},
    "tr": {"home": "Ana sayfa", "works": "İşler", "all": "Tümü", "about": "Hakkında", "contact": "İletişim",
           "featured": "Seçilmiş işler", "see_all": "Bütün işleri gör", "categories": "Kategoriler",
           "made": "Atölyede yapılanlar", "tools": "Geliştirdiğimiz araçlar", "visit": "Siteye git",
           "prev": "Önceki", "next": "Sonraki", "back": "Geri:", "n_works": "{n} iş", "one_work": "1 iş",
           "empty": "Galeri hazırlanıyor. Yeni işler çok yakında.", "lang": "English",
           "nf_title": "Sayfa bulunamadı", "nf_text": "Aradığın sayfa yok.",
           "write": "Bize yaz"},
}


# ------------------------------------------------------------------ yardımcılar
def esc(s):
    return html.escape(str(s or ""), quote=True)


def fold(s):
    s = s.replace("ı", "i").replace("İ", "i")
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-")
    return s or "is"


DATE_RX = re.compile(r"^(\d{4})(?:[-_.](\d{1,2}))?(?:[-_.](\d{1,2}))?[-_. ]*")
ORDER_RX = re.compile(r"^(\d{1,3})[-_. ]+(?=\D)")
CAT_ORDER_RX = re.compile(r"^(\d{1,3})[-_. ]+(?=.)")   # kategori klasörü sıra öneki: "03-3d-prints"


def nice_name(stem):
    """'2024-05_red-dragon_bust' → 'Red Dragon Bust'"""
    s = DATE_RX.sub("", stem) if DATE_RX.match(stem) else ORDER_RX.sub("", stem)
    s = re.sub(r"[-_]+", " ", s).strip() or stem
    return " ".join(w[:1].upper() + w[1:] for w in s.split()) if s.islower() else s


KEYS = {"title": "title", "baslik": "title_tr", "desc": "desc", "description": "desc", "aciklama": "desc_tr",
        "year": "year", "yil": "year", "tags": "tags", "etiketler": "tags", "featured": "featured",
        "one cikan": "featured", "onecikan": "featured", "order": "order", "sira": "order",
        "en": "en", "tr": "tr", "date": "date", "tarih": "date", "cover": "cover", "kapak": "cover"}


def read_meta(path):
    """'anahtar: değer' satırları; anahtarsız satırlar bir önceki anahtara eklenir (çok satırlı açıklama)."""
    meta, last = {}, None
    if not path or not os.path.isfile(path):
        return meta
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            m = re.match(r"^\s*([^:]{1,20}):\s*(.*)$", line)
            key = KEYS.get(fold(m.group(1)).strip()) if m else None
            if key:
                meta[key] = m.group(2).strip()
                last = key
            elif last and last.startswith("desc"):
                meta[last] += "\n" + line.strip()
    return meta


def truthy(v):
    return fold(str(v or "")).strip() in ("1", "yes", "evet", "true", "x", "e", "y")


def paragraphs(text):
    parts = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    return "".join(f"<p>{esc(p).replace(chr(10), '<br>')}</p>" for p in parts)


# ------------------------------------------------------------------ içerik
class Work:
    pass


def scan(works_dir):
    cats, works, used = [], [], set()
    if not os.path.isdir(works_dir):
        return cats, works
    for cname in sorted(os.listdir(works_dir)):
        cdir = os.path.join(works_dir, cname)
        if not os.path.isdir(cdir) or cname.startswith((".", "_")):
            continue
        cm = read_meta(os.path.join(cdir, "_category.txt"))
        om = CAT_ORDER_RX.match(cname)
        plain = CAT_ORDER_RX.sub("", cname)
        cat = {"dir": cname, "slug": slugify(plain),
               "en": cm.get("en") or cm.get("title") or nice_name(plain),
               "order": int(cm.get("order") or (om.group(1) if om else 999))}
        cat["tr"] = cm.get("tr") or cm.get("title_tr") or cat["en"]
        cat["works"] = []
        for name in sorted(os.listdir(cdir)):
            p = os.path.join(cdir, name)
            stem, ext = os.path.splitext(name)
            if name.startswith((".", "_")):
                continue
            if os.path.isdir(p):
                imgs = sorted(os.path.join(p, f) for f in os.listdir(p)
                              if os.path.splitext(f)[1].lower() in IMG_EXT and not f.startswith("."))
                txts = [os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(".txt")]
                meta = read_meta(os.path.join(p, "info.txt") if os.path.isfile(os.path.join(p, "info.txt"))
                                 else (txts[0] if txts else None))
                stem = name
            elif ext.lower() in IMG_EXT:
                imgs = [p]
                meta = read_meta(os.path.join(cdir, stem + ".txt"))
            else:
                continue
            if not imgs:
                continue
            if meta.get("cover"):
                imgs.sort(key=lambda x: os.path.basename(x).lower() != meta["cover"].lower())
            w = Work()
            w.cat, w.images, w.src_name = cat, imgs, stem
            w.title = {"en": meta.get("title") or nice_name(stem)}
            w.title["tr"] = meta.get("title_tr") or w.title["en"]
            w.desc = {"en": meta.get("desc", ""), "tr": meta.get("desc_tr") or meta.get("desc", "")}
            w.tags = [t.strip() for t in meta.get("tags", "").split(",") if t.strip()]
            w.featured = truthy(meta.get("featured"))
            dm = DATE_RX.match(meta.get("date") or stem)
            if dm:
                w.date = (int(dm.group(1)), int(dm.group(2) or 1), int(dm.group(3) or 1))
            else:
                t = datetime.date.fromtimestamp(min(os.path.getmtime(i) for i in imgs))
                w.date = (t.year, t.month, t.day)
            w.year = meta.get("year") or str(w.date[0])
            base = cat["slug"] + "-" + slugify(nice_name(stem))
            slug, n = base, 2
            while slug in used:
                slug, n = f"{base}-{n}", n + 1
            used.add(slug)
            w.slug = slug
            cat["works"].append(w)
            works.append(w)
        cat["works"].sort(key=lambda w: w.date, reverse=True)
        if cat["works"]:
            cats.append(cat)
    cats.sort(key=lambda c: (c["order"], fold(c["en"])))
    works.sort(key=lambda w: w.date, reverse=True)
    return cats, works


def make_images(works, out):
    """Her resim için 640/1600 px WebP; kaynak değişmediyse dokunma. Kullanılmayanları sil."""
    img_root = os.path.join(out, "img")
    keep = set()
    made = 0
    for w in works:
        w.pics = []
        for i, src in enumerate(w.images, 1):
            st = os.path.getmtime(src)
            files = {}
            for size in SIZES:
                rel = f"img/{w.slug}/{i}-{size}.webp"
                dst = os.path.join(out, rel)
                keep.add(os.path.normpath(dst))
                files[size] = rel
                if os.path.isfile(dst) and os.path.getmtime(dst) >= st:
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with Image.open(src) as im:
                    im.seek(0)
                    im = ImageOps.exif_transpose(im)
                    alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
                    im = im.convert("RGBA" if alpha else "RGB")
                    if max(im.size) > size:
                        im.thumbnail((size, size), Image.LANCZOS)
                    im.save(dst, "WEBP", quality=84 if size > 1000 else 80, method=5)  # EXIF yazılmaz
                made += 1
            with Image.open(os.path.join(out, files[SIZES[-1]])) as im:
                w.pics.append({"s": files[SIZES[0]], "l": files[SIZES[-1]], "w": im.width, "h": im.height})
    removed = 0
    if os.path.isdir(img_root):
        for dp, dn, fn in os.walk(img_root, topdown=False):
            for f in fn:
                p = os.path.normpath(os.path.join(dp, f))
                if p not in keep:
                    os.remove(p)
                    removed += 1
            if dp != img_root and not os.listdir(dp):
                os.rmdir(dp)
    return made, removed


# ------------------------------------------------------------------ sayfalar
def page(cfg, lang, path, title, body, alt_path, desc="", image=""):
    """path: sitedeki yol (ör. 'works/' ya da 'tr/works/'); göreli bağlantılar için kök öneki hesaplanır."""
    depth = path.count("/")
    r = "../" * depth
    other = "tr" if lang == "en" else "en"
    lp = "" if lang == "en" else "tr/"
    t = T[lang]
    url = cfg["url"].rstrip("/") + "/"
    full_title = esc(title + " · " + cfg["name"]) if title != cfg["name"] else esc(cfg["name"])
    d = esc(desc or cfg["tagline"][lang])
    og = f'<meta property="og:image" content="{url}{image}">' if image else ""
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{full_title}</title>
<meta name="description" content="{d}">
<meta property="og:title" content="{full_title}">
<meta property="og:description" content="{d}">
<meta property="og:type" content="website">
{og}
<link rel="alternate" hreflang="{lang}" href="{url}{path}">
<link rel="alternate" hreflang="{other}" href="{url}{alt_path}">
<link rel="icon" href="{r}assets/favicon.png">
<link rel="stylesheet" href="{r}assets/style.css">
</head>
<body>
<header class="top"><div class="wrap">
  <a class="brand" href="{r}{lp}">{esc(cfg["name"])}</a>
  <nav>
    <a href="{r}{lp}works/">{t["works"]}</a>
    <a href="{r}{lp}#about">{t["about"]}</a>
    <a href="{r}{lp}#contact">{t["contact"]}</a>
    <a class="lang" href="{r}{alt_path}" lang="{other}">{t["lang"]}</a>
  </nav>
</div></header>
<main>
{body}
</main>
<footer><div class="wrap">
  <span>© {datetime.date.today().year} {esc(cfg["name"])}</span>
  <div class="links">{links_html(cfg)}<a href="mailto:{esc(cfg["email"])}">{esc(cfg["email"])}</a></div>
</div></footer>
<div class="lightbox" id="lb"><img alt=""></div>
<script src="{r}assets/site.js"></script>
</body>
</html>
"""


def links_html(cfg):
    return "".join(f'<a href="{esc(l["url"])}" rel="me">{esc(l["name"])}</a>' for l in cfg.get("links", []) if l.get("url"))


def tile(w, lang, r, lp):
    p = w.pics[0]
    more = f'<span class="count">{len(w.pics)}</span>' if len(w.pics) > 1 else ""
    return (f'<a class="tile" href="{r}{lp}w/{w.slug}/"><img src="{r}{p["s"]}" width="{p["w"]}" height="{p["h"]}" '
            f'loading="lazy" alt="{esc(w.title[lang])}">{more}<span class="cap"><b>{esc(w.title[lang])}</b>'
            f'<small>{esc(w.cat[lang])} · {esc(w.year)}</small></span></a>')


def count_txt(lang, n):
    return T[lang]["one_work"] if n == 1 else T[lang]["n_works"].format(n=n)


def build_pages(cfg, cats, works, out):
    pages = {}
    # önce "featured" işaretliler, kalan yer en yeni işlerle dolar
    feat = ([w for w in works if w.featured] + [w for w in works if not w.featured])[: int(cfg.get("featured_count", 9))]
    for lang in LANGS:
        t, lp = T[lang], ("" if lang == "en" else "tr/")
        alt = lambda p: ("tr/" + p) if lang == "en" else p[3:]          # noqa: E731

        # ana sayfa
        r = "../" * lp.count("/")
        hero_img = f'<div class="hero-art" style="background-image:url({r}{feat[0].pics[0]["l"]})"></div>' if feat else ""
        if works:
            grid = f'<div class="masonry">{"".join(tile(w, lang, r, lp) for w in feat)}</div>' \
                   f'<p class="more"><a class="btn" href="{r}{lp}works/">{t["see_all"]} →</a></p>'
            catcards = "".join(
                f'<a class="catcard" href="{r}{lp}works/{c["slug"]}/"><img src="{r}{c["works"][0].pics[0]["s"]}" '
                f'loading="lazy" alt=""><span><b>{esc(c[lang])}</b><small>{count_txt(lang, len(c["works"]))}</small></span></a>'
                for c in cats)
            gallery = f"""<section><div class="wrap">
  <h2>{t["featured"]}</h2>{grid}
</div></section>
<section class="alt"><div class="wrap">
  <h2>{t["categories"]}</h2><div class="cats">{catcards}</div>
</div></section>"""
        else:
            gallery = f'<section><div class="wrap"><p class="empty">{t["empty"]}</p></div></section>'
        prods = "".join(
            f'<a class="product" href="{esc(p["url"])}"><img src="{r}assets/{esc(p["icon"])}" alt="">'
            f'<span><b>{esc(p["name"])}</b><small>{esc(p["text"][lang])}</small><em>{t["visit"]} →</em></span></a>'
            for p in cfg.get("products", []))
        body = f"""<div class="hero">{hero_img}<div class="wrap">
  <h1>{esc(cfg["name"])}</h1>
  <p class="lead">{esc(cfg["tagline"][lang])}</p>
</div></div>
{gallery}
<section id="about"><div class="wrap narrow">
  <h2>{t["about"]}</h2>{paragraphs(cfg["about"][lang])}
</div></section>
<section class="alt"><div class="wrap">
  <h2>{t["tools"]}</h2><div class="products">{prods}</div>
</div></section>
<section id="contact"><div class="wrap narrow center">
  <h2>{t["contact"]}</h2>
  <p><a class="btn primary" href="mailto:{esc(cfg["email"])}">{t["write"]}: {esc(cfg["email"])}</a></p>
  <p class="social">{links_html(cfg)}</p>
</div></section>"""
        pages[lp] = page(cfg, lang, lp, cfg["name"], body, alt(lp) if lp else "tr/",
                         image=feat[0].pics[0]["l"] if feat else "")

        # bütün işler + kategori sayfaları
        for c in [None] + cats:
            path = lp + "works/" + (c["slug"] + "/" if c else "")
            r = "../" * path.count("/")
            items = c["works"] if c else works
            chips = f'<a class="chip{" on" if not c else ""}" href="{r}{lp}works/">{t["all"]} <small>{len(works)}</small></a>' + "".join(
                f'<a class="chip{" on" if c is k else ""}" href="{r}{lp}works/{k["slug"]}/">{esc(k[lang])} <small>{len(k["works"])}</small></a>'
                for k in cats)
            head = esc(c[lang]) if c else t["works"]
            grid = (f'<div class="masonry">{"".join(tile(w, lang, r, lp) for w in items)}</div>'
                    if items else f'<p class="empty">{t["empty"]}</p>')
            body = f"""<section class="page"><div class="wrap">
  <h1>{head}</h1>
  <nav class="chips">{chips}</nav>
  {grid}
</div></section>"""
            pages[path] = page(cfg, lang, path, head if c else t["works"], body, alt(path) if lang == "tr" else "tr/" + path,
                               image=items[0].pics[0]["l"] if items else "")

        # eser sayfaları
        for c in cats:
            ws = c["works"]
            for i, w in enumerate(ws):
                path = lp + f"w/{w.slug}/"
                r = "../" * path.count("/")
                imgs = "".join(
                    f'<a class="big" href="{r}{p["l"]}"><img src="{r}{p["l"]}" width="{p["w"]}" height="{p["h"]}" '
                    f'{"" if k == 0 else "loading=lazy "}alt="{esc(w.title[lang])}{"" if k == 0 else f" ({k + 1})"}"></a>'
                    for k, p in enumerate(w.pics))
                tags = "".join(f'<span class="tag">{esc(x)}</span>' for x in w.tags)
                nav = ""
                if i > 0:
                    nav += f'<a href="{r}{lp}w/{ws[i - 1].slug}/">← {esc(ws[i - 1].title[lang])}</a>'
                nav += f'<a class="mid" href="{r}{lp}works/{c["slug"]}/">{esc(c[lang])}</a>'
                if i < len(ws) - 1:
                    nav += f'<a href="{r}{lp}w/{ws[i + 1].slug}/">{esc(ws[i + 1].title[lang])} →</a>'
                body = f"""<article class="work"><div class="wrap">
  <header>
    <p class="crumb"><a href="{r}{lp}works/{c["slug"]}/">{esc(c[lang])}</a> · {esc(w.year)}</p>
    <h1>{esc(w.title[lang])}</h1>
    {paragraphs(w.desc[lang])}
    {f'<p class="tags">{tags}</p>' if tags else ""}
  </header>
  <div class="images">{imgs}</div>
  <nav class="prevnext">{nav}</nav>
</div></article>"""
                pages[path] = page(cfg, lang, path, w.title[lang], body, alt(path) if lang == "tr" else "tr/" + path,
                                   desc=(w.desc[lang] or "").split("\n")[0][:200], image=w.pics[0]["l"])

    # 404 (GitHub Pages kökten sunar; mutlak yollar)
    body = f'<section class="page"><div class="wrap narrow center"><h1>{T["en"]["nf_title"]}</h1><p>{T["en"]["nf_text"]}</p>' \
           f'<p><a class="btn" href="/">{T["en"]["home"]}</a> <a class="btn" href="/tr/">{T["tr"]["home"]}</a></p></div></section>'
    pages["404.html"] = page(cfg, "en", "", T["en"]["nf_title"], body, "tr/").replace('href="assets/', 'href="/assets/').replace('src="assets/', 'src="/assets/')
    return pages


def write_site(cfg, cats, works, out):
    pages = build_pages(cfg, cats, works, out)
    # eski sayfaları temizle (img/ ve assets/ hariç)
    for name in ("works", "w", "tr"):
        shutil.rmtree(os.path.join(out, name), ignore_errors=True)
    for path, text in pages.items():
        fn = os.path.join(out, path if path.endswith(".html") else os.path.join(path, "index.html"))
        os.makedirs(os.path.dirname(fn) or out, exist_ok=True)
        with open(fn, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    # sabit dosyalar
    adir = os.path.join(out, "assets")
    os.makedirs(adir, exist_ok=True)
    theme = os.path.join(ROOT, "theme")
    for f in os.listdir(theme):
        shutil.copy2(os.path.join(theme, f), os.path.join(adir, f))
    url = cfg["url"].rstrip("/") + "/"
    host = re.sub(r"^https?://", "", url).strip("/")
    with open(os.path.join(out, "CNAME"), "w") as f:
        f.write(host + "\n")
    with open(os.path.join(out, ".nojekyll"), "w") as f:
        f.write("")
    with open(os.path.join(out, "robots.txt"), "w") as f:
        f.write(f"User-agent: *\nAllow: /\nSitemap: {url}sitemap.xml\n")
    with open(os.path.join(out, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for p in sorted(pages):
            if p != "404.html":
                f.write(f"  <url><loc>{esc(url + p)}</loc></url>\n")
        f.write("</urlset>\n")
    return len(pages)


def folder_size(p):
    return sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fn in os.walk(p) for f in fn)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--works")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs"))
    a = ap.parse_args()
    with open(os.path.join(ROOT, "site.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    works_dir = a.works or os.path.join(ROOT, os.path.expandvars(cfg.get("works_dir", "works")))
    os.makedirs(works_dir, exist_ok=True)
    cats, works = scan(works_dir)
    os.makedirs(a.out, exist_ok=True)
    made, removed = make_images(works, a.out)
    n = write_site(cfg, cats, works, a.out)
    mb = folder_size(a.out) / 1e6
    print(f"{len(works)} eser, {len(cats)} kategori · {made} resim üretildi, {removed} eski resim silindi · {n} sayfa · {mb:.0f} MB")
    for c in cats:
        print(f"  {c['en']}: {len(c['works'])}")
    if mb > 800:
        print("UYARI: site 800 MB'ı geçti (GitHub Pages sınırı ~1 GB).")


if __name__ == "__main__":
    sys.exit(main())
