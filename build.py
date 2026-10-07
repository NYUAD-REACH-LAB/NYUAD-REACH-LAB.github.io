#!/usr/bin/env python3
"""Build the REACH Lab website from data/*.json and src/templates/.

    python3 build.py            build, run the leak test, write pages to this folder
    python3 build.py --test     build into a temporary directory, run the leak test, keep nothing

Both commands build into a temporary directory first. The leak test reads the
lab's private records (default: the parent folder, or --records PATH) to learn
what must never appear, and fails on any hit. On failure the real build also
deletes the pages it owns in this folder, so a stale page can never be pushed.

Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import math
import posixpath
import re
import shutil
import struct
import sys
import tempfile
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

SITE = Path(__file__).resolve().parent
DATA = SITE / "data"
TEMPLATES = SITE / "src" / "templates"
ASSETS = SITE / "src" / "assets"
BRAND = SITE / "src" / "brand"
BRAND_WEB = BRAND / "web"
PHOTOS = SITE / "src" / "photos"

# Everything the build writes at the site root. Nothing else is ever touched.
OWNED = ["index.html", "404.html", "assets", "research", "people", "publications",
         "news", "join", "resources", "teaching", "contact"]

PAGES = {
    "home": ("index.html", "Home"),
    "research": ("research/index.html", "Research"),
    "people": ("people/index.html", "People"),
    "publications": ("publications/index.html", "Publications"),
    "news": ("news/index.html", "News"),
    "join": ("join/index.html", "Join"),
    "resources": ("resources/index.html", "Resources"),
    "teaching": ("teaching/index.html", "Teaching"),
    "contact": ("contact/index.html", "Contact"),
    "404": ("404.html", "Not found"),
}
NAV = ["research", "people", "publications", "news", "join", "resources", "teaching", "contact"]
MAX_PAGE_BYTES = 300_000


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------

def load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------
# BibTeX: written from the publication records only. Nothing is added that the record does not say.
# ----------------------------------------------------------------------------

# Family names of more than one word; every other author is "Given Names Family" with a one-word family.
BIB_FAMILY = {"A. Del Prete": "Del Prete", "M. Dalle Vedove": "Dalle Vedove", "R. I. Cabral Muchacho": "Cabral Muchacho"}


def bib_text(text: str) -> str:
    """Escape what BibTeX treats as markup; dashes become their TeX forms."""
    for old, new in (("\\", "\\textbackslash{}"), ("&", "\\&"), ("%", "\\%"), ("#", "\\#"), ("_", "\\_"),
                     ("$", "\\$"), ("³", "\\textsuperscript{3}"), ("—", "---"), ("–", "--")):
        text = text.replace(old, new)
    return text


def bib_author(literal: str) -> str:
    family = BIB_FAMILY.get(literal) or literal.split()[-1]
    given = literal[: len(literal) - len(family)].strip()
    return f"{family}, {given}" if given else family


def bib_ascii(text: str) -> str:
    text = text.replace("ı", "i").replace("İ", "I")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if c.isascii() and c.isalnum()).lower()


def bib_key(rec, used: set) -> str:
    family = bib_ascii(bib_author(rec["author"][0]["literal"]).split(",")[0])
    word = next((bib_ascii(w) for w in re.findall(r"\w[\w-]*", rec["title"])
                 if re.search(r"[^\W\d_]", w) and w.casefold() not in {"a", "an", "the", "on", "of", "for", "and", "in", "to"}), "")
    base = f"{family}{rec['year']}{word}"
    key, n = base, 0
    while key in used:
        n += 1
        key = base + chr(96 + n)
    used.add(key)
    return key


def bib_entry(rec, key: str, addresses: dict, details: dict) -> str:
    venue = rec["display-venue"]
    links = {l["label"]: l["URL"] for l in rec["links"]}
    fields: list[tuple[str, str]] = [("author", " and ".join(bib_author(a["literal"]) for a in rec["author"])),
                                     ("title", "{" + bib_text(rec["title"]) + "}")]
    if rec["status"] == "preprint":
        kind = "misc"
        archive, location = rec.get("archive", ""), rec.get("archive_location", "")
        if archive == "arXiv":
            fields += [("year", str(rec["year"])), ("eprint", location), ("archivePrefix", "arXiv")]
        else:
            fields += [("year", str(rec["year"])), ("howpublished", f"{archive} {location}".strip())]
        fields.append(("note", "Preprint, not yet peer-reviewed"))
        url = next((u for lab, u in links.items() if lab in ("arXiv", "HAL")), "")
        if url:
            fields.append(("url", url))
    else:
        series = publisher = address = ""
        if " — " in venue:                                   # "Series (Publisher) — conference name"
            head, venue = venue.split(" — ", 1)
            m = re.match(r"(.*?)\s*\((.*)\)$", head)
            series, publisher = (m.group(1), m.group(2)) if m else (head, "")
        volume = number = pages = ""
        m = re.search(r",\s*pp\.\s*([\w–-]+)\s*$", venue)
        if m:
            pages, venue = m.group(1).replace("–", "--"), venue[: m.start()]
        m = re.search(r",\s*no\.\s*(\w+)\s*$", venue)
        if m:
            number, venue = m.group(1), venue[: m.start()]
        m = re.search(r",\s*vol\.\s*(\w+)\s*$", venue)
        if m:
            volume, venue = m.group(1), venue[: m.start()]
        is_conference = bool(re.search(r"Conference|Jornadas|ANTS", venue))
        extra = details.get(rec["id"], {})                 # volume, number, pages, publisher, editor the record does not carry
        volume, number, pages = (extra.get(k, v) for k, v in (("volume", volume), ("number", number), ("pages", pages)))
        if is_conference:
            kind = "inproceedings"
            m = re.match(r"(.*\([^)]*\)),\s*(.+)$", venue)          # "Name (ACRONYM), City, Country"
            if m:
                venue, address = m.group(1), m.group(2)
            known = addresses.get(venue, {}).get(str(rec["year"]))
            if known:
                address = known
                city = known.split(",")[0]
                if venue.endswith(", " + city):                   # the city is the address, not part of the title
                    venue = venue[: -len(city) - 2]
            else:
                print(f"warning: no address for {venue} ({rec['year']}); add it to data/conference-addresses.json",
                      file=sys.stderr)
            publisher = extra.get("publisher", publisher)
            fields += [("booktitle", bib_text(venue)), ("year", str(rec["year"]))]
            order = (("editor", extra.get("editor", "")), ("volume", volume), ("series", series),
                     ("pages", pages), ("publisher", publisher), ("address", address))
        else:
            kind = "article"
            fields += [("journal", bib_text(re.sub(r"\s*\([^)]*\)$", "", venue))), ("year", str(rec["year"]))]
            order = (("volume", volume), ("number", number), ("pages", pages))
        fields += [(name, bib_text(value)) for name, value in order if value]
        if "DOI" in links:
            fields.append(("doi", links["DOI"].removeprefix("https://doi.org/")))
        m = re.match(r"https://arxiv\.org/abs/(.+)$", links.get("arXiv", ""))
        if m:
            fields += [("eprint", m.group(1)), ("archivePrefix", "arXiv")]
        if "DOI" not in links:
            other = next((u for lab, u in links.items() if lab not in ("arXiv", "Code", "Project page", "PDF")), "")
            if other:
                fields.append(("url", other))
    width = max(len(k) for k, _ in fields)
    body = ",\n".join(f"  {k.ljust(width)} = {{{v}}}" for k, v in fields)
    return f"@{kind}{{{key},\n{body}\n}}"


def make_bibtex(records, addresses: dict, details: dict) -> dict:
    used: set = set()
    return {rec["id"]: bib_entry(rec, bib_key(rec, used), addresses, details) for rec in records}


class Site:
    def __init__(self) -> None:
        self.site = load("site.json")
        self.research = load("research.json")
        self.people = load("people.json")
        self.news = load("news.json")
        self.join = load("join.json")
        self.resources = load("resources.json")
        self.teaching = load("teaching.json")
        self.pub_fields = load("publication-fields.json")
        self.csl = load("publications.csl.json")
        withheld = set(self.site.get("withheld_fields", []))
        self.fields = [f for f in self.research["fields"] if f["number"] not in withheld]
        self.field_by_number = {f["number"]: f for f in self.fields}
        for f in self.fields:
            PAGES[f"field:{f['slug']}"] = (f"research/{f['slug']}/index.html", f["title"])
        build = self.site["build"]
        self.built = set(PAGES) if build == "all" else set(build)
        if not self.teaching.get("courses"):
            self.built.discard("teaching")
        unknown = self.built - set(PAGES)
        if unknown:
            raise SystemExit(f"site.json build lists unknown pages: {sorted(unknown)}")
        pubs_cfg = self.site["publications"]
        withheld_links = set(pubs_cfg.get("withheld_links", []))
        self.publications = []
        for rec in self.csl:
            year = rec["issued"]["date-parts"][0][0]
            if year < pubs_cfg["from_year"]:
                continue
            if rec["id"] not in self.pub_fields:
                raise SystemExit(f"publication-fields.json has no entry for {rec['id']}")
            rec = dict(rec, year=year,
                       links=[l for l in rec["links"] if l["URL"] not in withheld_links],
                       fields=[n for n in self.pub_fields[rec["id"]] if n in self.field_by_number])
            self.publications.append(rec)
        self.publications.sort(key=lambda r: (r["status"] != "preprint", r["year"]), reverse=True)
        self.bibtex = make_bibtex(self.publications, load("conference-addresses.json"), load("bibtex-details.json"))

    def href(self, page: str, key: str, fragment: str = "") -> str | None:
        """Relative link from page to key, or None when key is not built."""
        if key not in self.built:
            return None
        src = PAGES[page][0]
        dst = PAGES[key][0]
        rel = posixpath.relpath(dst, posixpath.dirname(src) or ".")
        return rel + fragment

    def root(self, page: str) -> str:
        depth = PAGES[page][0].count("/")
        return "../" * depth


# ----------------------------------------------------------------------------
# Templates: {{name}} is escaped, {{{name}}} is inserted as is.
# ----------------------------------------------------------------------------

def render(template: str, **ctx) -> str:
    text = (TEMPLATES / template).read_text(encoding="utf-8")

    def sub(m: re.Match) -> str:
        key = m.group(1) or m.group(2)
        if key not in ctx:
            raise KeyError(f"{template}: no value for {key!r}")
        return str(ctx[key]) if m.group(1) else html.escape(str(ctx[key]))

    return re.sub(r"\{\{\{\s*(\w+)\s*\}\}\}|\{\{\s*(\w+)\s*\}\}", sub, text)


e = html.escape


def a(href: str | None, label: str, cls: str = "", external: bool = False) -> str:
    c = f' class="{cls}"' if cls else ""
    if href is None:
        return f"<span{c}>{label}</span>"
    rel = ' rel="noopener"' if external else ""
    return f'<a{c} href="{e(href, quote=True)}"{rel}>{label}</a>'


# ----------------------------------------------------------------------------
# Motif — tangent geometry. Orthographic views of manifolds, geodesics,
# tangent planes and contact normals, computed rather than drawn by hand.
# ----------------------------------------------------------------------------

def v_add(p, q): return tuple(x + y for x, y in zip(p, q))
def v_sub(p, q): return tuple(x - y for x, y in zip(p, q))
def v_mul(p, s): return tuple(x * s for x in p)
def v_dot(p, q): return sum(x * y for x, y in zip(p, q))
def v_cross(p, q): return (p[1] * q[2] - p[2] * q[1], p[2] * q[0] - p[0] * q[2], p[0] * q[1] - p[1] * q[0])
def v_norm(p):
    n = math.sqrt(v_dot(p, p))
    return tuple(x / n for x in p)


def latlon(lat: float, lon: float):
    la, lo = math.radians(lat), math.radians(lon)
    return (math.cos(la) * math.sin(lo), math.sin(la), math.cos(la) * math.cos(lo))


def slerp(p, q, t):
    om = math.acos(max(-1.0, min(1.0, v_dot(p, q))))
    if om < 1e-9:
        return p
    s = math.sin(om)
    return v_add(v_mul(p, math.sin((1 - t) * om) / s), v_mul(q, math.sin(t * om) / s))


def tangent_basis(p):
    up = (0.0, 1.0, 0.0) if abs(p[1]) < 0.9 else (1.0, 0.0, 0.0)
    e1 = v_norm(v_cross(up, p))
    return e1, v_cross(p, e1)


def small_circle(c, rho, n=48):
    e1, e2 = tangent_basis(c)
    return [v_add(v_mul(c, math.cos(rho)),
                  v_mul(v_add(v_mul(e1, math.cos(t)), v_mul(e2, math.sin(t))), math.sin(rho)))
            for t in (2 * math.pi * i / n for i in range(n + 1))]


class View:
    """Orthographic camera: yaw about y, then pitch about x; +z faces the viewer."""

    def __init__(self, cx, cy, r, yaw, pitch):
        self.cx, self.cy, self.r = cx, cy, r
        cy_, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
        ry = ((cy_, 0, sy), (0, 1, 0), (-sy, 0, cy_))
        rx = ((1, 0, 0), (0, cp, -sp), (0, sp, cp))
        self.m = tuple(tuple(sum(rx[i][k] * ry[k][j] for k in range(3)) for j in range(3)) for i in range(3))

    def rot(self, v):
        return tuple(v_dot(row, v) for row in self.m)

    def unrot(self, w):
        return tuple(sum(self.m[i][j] * w[i] for i in range(3)) for j in range(3))

    def p(self, v):
        w = self.rot(v)
        return (self.cx + self.r * w[0], self.cy - self.r * w[1], w[2])


def f1(x: float) -> str:
    s = f"{x:.1f}"
    return s[:-2] if s.endswith(".0") else s


def d_of(points) -> str:
    return "M" + "L".join(f"{f1(x)} {f1(y)}" for x, y, *_ in points)


def split(view: View, pts3):
    """Path data for the visible (front) and hidden (back) parts of a curve on the unit sphere."""
    front, back, run, vis = [], [], [], None
    for v in pts3:
        x, y, z = view.p(v)
        now = z >= 0
        if vis is None or now == vis:
            run.append((x, y))
        else:
            (front if vis else back).append(run)
            run = [run[-1], (x, y)]
        vis = now
    if run:
        (front if vis else back).append(run)
    fd = "".join(d_of(r) for r in front if len(r) > 1)
    bd = "".join(d_of(r) for r in back if len(r) > 1)
    return fd, bd


def path(d: str, cls: str, extra: str = "") -> str:
    return f'<path class="{cls}" d="{d}"{extra}/>' if d else ""


def sphere_curve(view, pts3, cls, back_cls="a-back", extra=""):
    fd, bd = split(view, pts3)
    return (path(bd, back_cls) if back_cls else "") + path(fd, cls, extra)


def globe(view: View, lats=(-60, -30, 0, 30, 60), lons=(0, 30, 60, 90, 120, 150), n=48) -> str:
    out = []
    for lat in lats:
        out.append(sphere_curve(view, [latlon(lat, 360 * i / n) for i in range(n + 1)], "a-grid"))
    for lon in lons:
        lo = math.radians(lon)
        pts = [(math.cos(t) * math.sin(lo), math.sin(t), math.cos(t) * math.cos(lo))
               for t in (2 * math.pi * i / n for i in range(n + 1))]
        out.append(sphere_curve(view, pts, "a-grid"))
    out.append(f'<circle class="a-rim" cx="{f1(view.cx)}" cy="{f1(view.cy)}" r="{f1(view.r)}"/>')
    return "".join(out)


def geodesic(p, q, n=64):
    return [slerp(p, q, i / n) for i in range(n + 1)]


def arrow(x1, y1, x2, y2, cls, head=7.0) -> str:
    ang = math.atan2(y2 - y1, x2 - x1)
    hx1, hy1 = x2 - head * math.cos(ang - 0.45), y2 - head * math.sin(ang - 0.45)
    hx2, hy2 = x2 - head * math.cos(ang + 0.45), y2 - head * math.sin(ang + 0.45)
    return (f'<path class="{cls}" d="M{f1(x1)} {f1(y1)}L{f1(x2)} {f1(y2)}'
            f'M{f1(hx1)} {f1(hy1)}L{f1(x2)} {f1(y2)}L{f1(hx2)} {f1(hy2)}"/>')


def plane(view: View, p, size, e1=None, e2=None) -> str:
    if e1 is None:
        e1, e2 = tangent_basis(p)
    corners = [v_add(p, v_add(v_mul(e1, sx * size), v_mul(e2, sy * size)))
               for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    return f'<path class="a-plane" d="{d_of([view.p(c) for c in corners])}Z"/>'


def dot(view: View, p, cls="a-dot", r=3.5) -> str:
    x, y, _ = view.p(p)
    return f'<circle class="{cls}" cx="{f1(x)}" cy="{f1(y)}" r="{r}"/>'


def log_arrow(view: View, p, q, scale, cls="a-acc") -> str:
    direction = v_norm(v_sub(q, v_mul(p, v_dot(p, q))))
    tip = v_add(p, v_mul(direction, scale))
    x1, y1, _ = view.p(p)
    x2, y2, _ = view.p(tip)
    return arrow(x1, y1, x2, y2, cls)


def svg(width: int, height: int, body: str, label: str | None = None, cls: str = "art") -> str:
    if label:
        head = f'<svg class="{cls}" viewBox="0 0 {width} {height}" role="img" aria-label="{e(label, quote=True)}"><title>{e(label)}</title>'
    else:
        head = f'<svg class="{cls}" viewBox="0 0 {width} {height}" aria-hidden="true" focusable="false">'
    return head + body + "</svg>"


def art_hero(label: str) -> str:
    v = View(300, 280, 230, -4, 18)
    a_, b_ = latlon(-30, -46), latlon(-6, 50)
    body = [globe(v)]
    # a fan of geodesics leaving the start point: the exponential map
    e1, e2 = tangent_basis(a_)
    for k in range(7):
        ang = -0.9 + 0.3 * k
        d = v_add(v_mul(e1, math.cos(ang)), v_mul(e2, math.sin(ang)))
        pts = [v_add(v_mul(a_, math.cos(t)), v_mul(d, math.sin(t))) for t in (1.6 * i / 40 for i in range(41))]
        body.append(sphere_curve(v, pts, "a-soft", back_cls=None))
    body.append(plane(v, a_, 0.36))
    body.append(plane(v, b_, 0.26))
    xa, ya, _ = v.p(a_)
    xb, yb, _ = v.p(b_)
    body.append(f'<path class="a-chord" d="M{f1(xa)} {f1(ya)}L{f1(xb)} {f1(yb)}"/>')
    body.append(sphere_curve(v, geodesic(a_, b_), "a-acc a-draw", extra=' pathLength="1"'))
    body.append(log_arrow(v, a_, b_, 0.42))
    xn, yn, _ = v.p(v_mul(b_, 1.3))
    body.append(arrow(xb, yb, xn, yn, "a-limit"))
    body.append(dot(v, a_, "a-dot"))
    body.append(dot(v, b_, "a-dot-acc", 4.5))
    return svg(600, 560, "".join(body), label, "art art-hero")


def art_geometric(label):
    v = View(240, 152, 128, -4, 30)
    a_, b_ = latlon(-16, -50), latlon(8, 50)
    body = [globe(v), plane(v, a_, 0.33)]
    xa, ya, _ = v.p(a_)
    xb, yb, _ = v.p(b_)
    body.append(f'<path class="a-chord" d="M{f1(xa)} {f1(ya)}L{f1(xb)} {f1(yb)}"/>')
    body.append(sphere_curve(v, geodesic(a_, b_), "a-acc"))
    # a tangent vector carried along the geodesic by parallel transport
    for t in (0.3, 0.55, 0.8):
        p = slerp(a_, b_, t)
        tan = v_norm(v_sub(slerp(a_, b_, t + 0.01), p))
        nrm = v_cross(p, tan)
        vec = v_add(v_mul(tan, math.cos(1.1)), v_mul(nrm, math.sin(1.1)))
        x1, y1, _ = v.p(p)
        x2, y2, _ = v.p(v_add(p, v_mul(vec, 0.22)))
        body.append(arrow(x1, y1, x2, y2, "a-ink", 5))
    body.append(log_arrow(v, a_, b_, 0.4))
    body += [dot(v, a_), dot(v, b_, "a-dot-acc", 4)]
    return svg(480, 300, "".join(body), label)


# ---- Planar drawings (fields 2–7). Same strokes and classes as the sphere artwork. ----

def poly_d(points, close=False) -> str:
    return d_of(points) + ("Z" if close else "")


def smooth_d(points) -> str:
    """Catmull-Rom through the points, written as cubic Béziers."""
    if len(points) < 3:
        return d_of(points)
    out = [f"M{f1(points[0][0])} {f1(points[0][1])}"]
    for i in range(len(points) - 1):
        p0 = points[i - 1] if i else points[0]
        p1, p2 = points[i], points[i + 1]
        p3 = points[i + 2] if i + 2 < len(points) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        out.append(f"C{f1(c1[0])} {f1(c1[1])} {f1(c2[0])} {f1(c2[1])} {f1(p2[0])} {f1(p2[1])}")
    return "".join(out)


def normals(points):
    """Unit normals (left of travel) at each point of a polyline."""
    out = []
    for i in range(len(points)):
        a_ = points[max(i - 1, 0)]
        b_ = points[min(i + 1, len(points) - 1)]
        dx, dy = b_[0] - a_[0], b_[1] - a_[1]
        n = math.hypot(dx, dy) or 1.0
        out.append((-dy / n, dx / n))
    return out


def ribbon(points, widths) -> str:
    """Closed band of half-width widths[i] around a polyline."""
    ns = normals(points)
    left = [(p[0] + n[0] * w, p[1] + n[1] * w) for p, n, w in zip(points, ns, widths)]
    right = [(p[0] - n[0] * w, p[1] - n[1] * w) for p, n, w in zip(points, ns, widths)]
    return poly_d(left + right[::-1], close=True)


def hatch_circle(cx, cy, r, spacing=7.0, angle=45.0) -> str:
    ux, uy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    nx, ny = -uy, ux
    segs = []
    s = -r + spacing / 2
    while s < r:
        h = math.sqrt(max(r * r - s * s, 0.0))
        x0, y0 = cx + nx * s, cy + ny * s
        segs.append(f"M{f1(x0 - ux * h)} {f1(y0 - uy * h)}L{f1(x0 + ux * h)} {f1(y0 + uy * h)}")
        s += spacing
    return "".join(segs)


def ground_ticks(points, step=14, length=11, skip=None) -> str:
    segs = []
    last = -1e9
    for x, y in points:
        if x - last < step or (skip and skip[0] <= x <= skip[1]):
            continue
        segs.append(f"M{f1(x)} {f1(y)}L{f1(x - length * 0.7)} {f1(y + length)}")
        last = x
    return "".join(segs)


def cdot(x, y, cls="a-dot", r=3.5) -> str:
    return f'<circle class="{cls}" cx="{f1(x)}" cy="{f1(y)}" r="{r}"/>'


def bezier(p0, p1, p2, p3, n=40):
    pts = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        pts.append((mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t ** 3 * p3[0],
                    mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t ** 3 * p3[1]))
    return pts


def art_safe(label):
    """A bowl seen from above: level curves, an inward spiral, a hatched region it bends around."""
    cx, cy = 205, 158
    fx, fy, fr = 352, 92, 44

    def inside_forbidden(x, y, margin=0.0):
        return math.hypot(x - fx, y - fy) < fr + margin

    def level(k, th):
        rr = k * 23 * (1 + 0.1 * math.sin(2 * th + 0.6) + 0.05 * math.cos(3 * th))
        return cx + 1.4 * rr * math.cos(th), cy + rr * math.sin(th)

    body = []
    for k in (1, 2, 3, 4, 5, 6):
        runs, run = [], []
        for i in range(97):
            x, y = level(k, 2 * math.pi * i / 96)
            if inside_forbidden(x, y, 2):
                if len(run) > 1:
                    runs.append(run)
                run = []
            else:
                run.append((x, y))
        if len(run) > 1:
            runs.append(run)
        body.append("".join(path(d_of(r), "a-grid") for r in runs))
    body.append(f'<circle class="a-body" cx="{fx}" cy="{fy}" r="{fr}"/>')
    body.append(path(hatch_circle(fx, fy, fr), "a-hatch"))
    body.append(f'<circle class="a-limit a-dash" cx="{fx}" cy="{fy}" r="{fr}"/>')
    pts = []
    margin = 16
    for i in range(161):
        t = i / 160
        k = 5.7 * (1 - t) ** 1.25
        th = -2.2 + 4.1 * math.pi * t
        x, y = level(k, th)
        d = math.hypot(x - fx, y - fy)
        if d < fr + margin:
            x = fx + (x - fx) / d * (fr + margin)
            y = fy + (y - fy) / d * (fr + margin)
        pts.append((x, y))
    body.append(path(smooth_d(pts[::4] + [pts[-1]]), "a-acc"))
    ax, ay = pts[96]
    bx, by = pts[100]
    body.append(arrow(ax, ay, bx, by, "a-acc", 8))
    body += [cdot(*pts[0]), cdot(cx, cy, "a-dot-acc", 5)]
    return svg(480, 300, "".join(body), label)


def art_demonstration(label):
    """Thin demonstrations and their variance band converging into one bold reproduction."""
    x0, x1 = 78, 424

    def mean(u):
        return 226 - 124 * (3 * u * u - 2 * u ** 3) - 20 * math.sin(math.pi * u)

    def sigma(u):
        return 30 * (1 - u) ** 1.4 + 1.0

    us = [i / 60 for i in range(61)]
    xs = [x0 + (x1 - x0) * u for u in us]
    body = []
    centre = [(x, mean(u)) for x, u in zip(xs, us)]
    body.append(f'<path class="a-band" d="{ribbon(centre, [1.55 * sigma(u) for u in us])}"/>')
    for k, z in enumerate((-1.25, -0.6, 0.1, 0.75, 1.3)):
        pts = [(x, mean(u) + sigma(u) * z * (1 + 0.35 * math.sin(6 * u + 1.7 * k))) for x, u in zip(xs, us)]
        body.append(path(smooth_d(pts[::3] + [pts[-1]]), "a-ink a-thin a-faint"))
    body.append(path(smooth_d(centre[::3] + [centre[-1]]), "a-acc"))
    gx, gy = centre[-1]
    body.append(f'<circle class="a-ink a-thin" cx="{f1(gx)}" cy="{f1(gy)}" r="11"/>')
    body.append(cdot(gx, gy, "a-dot-acc", 4.5))
    sx, sy = centre[0]
    # a guiding hand: the demonstrator's push at the start
    body.append(path(smooth_d([(sx - 64, sy + 46), (sx - 44, sy + 22), (sx - 14, sy + 6)]), "a-limit"))
    body.append(arrow(sx - 24, sy + 11, sx - 11, sy + 5, "a-limit", 9))
    body.append(path(f"M{f1(sx - 70)} {f1(sy + 26)}L{f1(sx - 58)} {f1(sy + 18)}M{f1(sx - 52)} {f1(sy + 50)}L{f1(sx - 40)} {f1(sy + 42)}", "a-ink a-thin"))
    body.append(cdot(sx, sy, "a-dot", 4))
    return svg(480, 300, "".join(body), label)


def art_contact(label):
    """A fingertip denting a surface, the contact force, and a spring–damper for impedance."""
    cx = 240
    base_y, dent, width = 206, 14, 26
    surface = [(x, base_y + dent * math.exp(-((x - cx) / width) ** 2)) for x in range(34, 447, 4)]
    tip_y = base_y + dent
    r = 18
    body = []
    body.append(path(ground_ticks(surface, skip=(cx - 16, cx + 16)), "a-hatch"))
    for rx, ry in ((32, 9), (50, 17)):
        arc = [(cx + rx * math.cos(t), tip_y + 3 + ry * math.sin(t)) for t in (math.pi * i / 24 for i in range(25))]
        body.append(path(d_of(arc), "a-grid"))
    body.append(path(d_of(surface), "a-ink"))
    # fixed support and the impedance: spring (left) and damper (right) in parallel
    top, mount = 34, 104
    body.append(path(f"M{cx - 46} {top}L{cx + 46} {top}", "a-ink"))
    body.append(path("".join(f"M{x} {top}L{x + 8} {top - 10}" for x in range(cx - 42, cx + 43, 10)), "a-hatch"))
    sx = cx - 26
    zig = [(sx, top), (sx, top + 10)]
    for i in range(6):
        zig.append((sx + (9 if i % 2 == 0 else -9), top + 14 + i * 8))
    zig += [(sx, top + 62), (sx, mount)]
    body.append(path(d_of(zig), "a-ink"))
    dx = cx + 26
    body.append(path(f"M{dx} {top}L{dx} {top + 26}M{dx - 8} {top + 26}L{dx + 8} {top + 26}"
                     f"M{dx - 12} {top + 16}L{dx - 12} {top + 52}L{dx + 12} {top + 52}L{dx + 12} {top + 16}"
                     f"M{dx} {top + 52}L{dx} {mount}", "a-ink"))
    body.append(path(f"M{cx - 38} {mount}L{cx + 38} {mount}", "a-ink"))
    # the finger, pressing into the dent
    finger = (f"M{cx - r} {mount}L{cx - r} {tip_y - r}A{r} {r} 0 0 0 {cx + r} {tip_y - r}L{cx + r} {mount}Z")
    body.append(f'<path class="a-body a-ink" d="{finger}"/>')
    body.append(path(f"M{cx - 9} {tip_y - r - 4}A10 7 0 0 0 {cx + 9} {tip_y - r - 4}", "a-grid"))
    body.append(arrow(cx, tip_y + 2, cx, tip_y + 62, "a-acc", 10))
    return svg(480, 300, "".join(body), label)


def art_soft(label):
    """A tapered continuum arm wrapping around an object: backbone and cross-sections."""
    ox, oy, orad = 312, 150, 46
    wrap_r = orad + 22
    wrap = [(ox + wrap_r * math.cos(math.radians(a)), oy - wrap_r * math.sin(math.radians(a)))
            for a in (180 - 235 * i / 60 for i in range(61))]
    # the arm rises beside the object and meets the wrap where its tangent points straight up
    base = (176.0, 276.0)
    lead = bezier(base, (176, 226), (wrap[0][0], wrap[0][1] + 70), wrap[0], 30)
    pts = lead + wrap[1:]
    lengths = [0.0]
    for a_, b_ in zip(pts, pts[1:]):
        lengths.append(lengths[-1] + math.hypot(b_[0] - a_[0], b_[1] - a_[1]))
    total = lengths[-1]
    widths = [16 * (1 - 0.72 * (s / total)) + 1.5 for s in lengths]
    ns = normals(pts)
    body = []
    body.append(f'<circle class="a-body" cx="{ox}" cy="{oy}" r="{orad}"/>')
    body.append(path(hatch_circle(ox, oy, orad), "a-hatch"))
    body.append(f'<circle class="a-ink" cx="{ox}" cy="{oy}" r="{orad}"/>')
    body.append(path("M146 276L206 276", "a-ink") + path("".join(f"M{x} 276L{x - 7} 286" for x in range(152, 207, 9)), "a-hatch"))
    left = [(p[0] + n[0] * w, p[1] + n[1] * w) for p, n, w in zip(pts, ns, widths)]
    right = [(p[0] - n[0] * w, p[1] - n[1] * w) for p, n, w in zip(pts, ns, widths)]
    body.append(f'<path class="a-body a-ink" d="{poly_d(left + right[::-1], close=True)}"/>')
    target = 0.0
    for i, s in enumerate(lengths):
        if s >= target and 0 < i < len(pts) - 2:
            (px, py), (nx, ny), w = pts[i], ns[i], widths[i]
            ring = [(px + nx * w * math.cos(t) + ny * 0.38 * w * math.sin(t),
                     py + ny * w * math.cos(t) - nx * 0.38 * w * math.sin(t))
                    for t in (2 * math.pi * k / 24 for k in range(25))]
            body.append(path(d_of(ring), "a-ink a-thin"))
            target += total / 11
    body.append(path(smooth_d(pts[::3] + [pts[-1]]), "a-acc"))
    body.append(cdot(*pts[-1], "a-dot-acc", 4))
    return svg(480, 300, "".join(body), label)


def art_uncertainty(label):
    """A fan of candidate futures with widening cones; one chosen branch."""
    ox, oy = 62, 160
    ends = [52, 104, 148, 204, 258]
    chosen = 1
    body = []
    branches = []
    for k, ye in enumerate(ends):
        pts = bezier((ox, oy), (170, oy), (300, ye + (oy - ye) * 0.3), (430, ye), 40)
        branches.append(pts)
        if k != chosen:
            widths = [2 + 20 * (i / 40) ** 1.2 for i in range(41)]
            body.append(f'<path class="a-cone" d="{ribbon(pts, widths)}"/>')
    widths = [1.5 + 13 * (i / 40) ** 1.2 for i in range(41)]
    body.append(f'<path class="a-band" d="{ribbon(branches[chosen], widths)}"/>')
    for k, pts in enumerate(branches):
        if k != chosen:
            body.append(path(smooth_d(pts[::4] + [pts[-1]]), "a-ink a-thin a-faint"))
            body.append(f'<circle class="a-ink a-thin" cx="{f1(pts[-1][0])}" cy="{f1(pts[-1][1])}" r="4"/>')
    pts = branches[chosen]
    body.append(path(smooth_d(pts[::4] + [pts[-1]]), "a-acc"))
    body.append(arrow(pts[-6][0], pts[-6][1], pts[-1][0] + 6, pts[-1][1], "a-acc", 9))
    body.append(cdot(ox, oy, "a-dot", 5))
    return svg(480, 300, "".join(body), label)


def art_neural(label):
    """EMG from a forearm drives a hand that flexes; feedback closes the loop to the arm."""
    body = []
    # forearm, residual limb seen from the side
    arm = "M14 168C74 158 132 162 172 176C190 190 190 220 172 234C132 250 74 252 14 242"
    body.append(f'<path class="a-body a-ink" d="{arm}"/>')
    for ex in (78, 122):
        body.append(f'<rect class="a-body a-ink" x="{ex - 9}" y="154" width="18" height="9" rx="2"/>')
    # EMG trace, rising from the electrodes and running to the hand
    seed = 11

    def rnd():
        nonlocal seed
        seed = (seed * 1103515245 + 12345) % 2 ** 31
        return seed / 2 ** 31 - 0.5

    trace = [(100.0, 150.0), (100.0, 84.0)]
    for i in range(1, 106):
        x = 100 + 2 * i
        env = 4 + 30 * math.exp(-((x - 205) / 42) ** 2)
        trace.append((x, 84 + env * (0.7 * math.sin(1.7 * i) + 0.6 * rnd())))
    body.append(path(d_of(trace), "a-acc a-signal"))
    body.append(path(smooth_d([(312, 84), (336, 86), (352, 98), (358, 118)]), "a-acc"))
    body.append(arrow(357, 106, 358, 120, "a-acc", 9))
    # the hand: palm and cuff, fingers as jointed chains — extended (ghost) and flexed
    body.append(f'<path class="a-body a-ink" d="M318 150L402 150Q412 150 412 160L412 212Q412 224 400 224L330 224Q318 224 318 212Z"/>')
    body.append(path("M338 224L338 252L392 252L392 224", "a-ink"))

    def chain(x, y, angles, lengths):
        pts = [(x, y)]
        a_ = 0.0
        for ang, ln in zip(angles, lengths):
            a_ += ang
            x += ln * math.cos(math.radians(a_))
            y += ln * math.sin(math.radians(a_))
            pts.append((x, y))
        return pts

    lengths = (30, 24, 18)
    bases = (330, 352, 374, 396)
    for bx in bases:
        body.append(path(d_of(chain(bx, 150, (-90, 0, 0), lengths)), "a-grid a-dash"))
    for j, bx in enumerate(bases):
        flexed = chain(bx, 150, (-80 + 3 * j, 62, 56), lengths)
        body.append(path(d_of(flexed), "a-ink a-finger"))
        body += [cdot(px, py, "a-dot", 3) for px, py in flexed[:-1]]
    thumb = chain(412, 204, (-20, 42), (22, 17))
    body.append(path(d_of(thumb), "a-ink a-finger"))
    body += [cdot(px, py, "a-dot", 3) for px, py in thumb[:-1]]
    body.append(path("M446 104A40 40 0 0 1 462 150", "a-ink a-thin"))
    body.append(arrow(459, 140, 462, 153, "a-ink", 7))
    # feedback back to the arm
    body.append(path("M364 262C336 296 184 292 124 256", "a-limit a-dash"))
    body.append(arrow(142, 268, 126, 257, "a-limit", 9))
    return svg(480, 300, "".join(body), label)


FIELD_ART = {
    "geometric": art_geometric,
    "safe-control": art_safe,
    "demonstration": art_demonstration,
    "contact-rich": art_contact,
    "soft-robotics": art_soft,
    "uncertainty": art_uncertainty,
    "neural-interfaces": art_neural,
}


def initials(name: str) -> str:
    parts = [p for p in name.split() if p[:1].isupper() and not p.endswith(".")]
    return (parts[0][0] + parts[-1][0]) if len(parts) > 1 else parts[0][:2]


def monogram(person_id: str, name: str, size_cls: str = "monogram") -> str:
    h = int(hashlib.sha256(person_id.encode()).hexdigest()[:8], 16)
    start = (h % 360)
    sweep = 70
    r = 27

    def pt(deg):
        rad = math.radians(deg)
        return 32 + r * math.cos(rad), 32 + r * math.sin(rad)

    x1, y1 = pt(start)
    x2, y2 = pt(start + sweep)
    tx = -math.sin(math.radians(start + sweep))
    ty = math.cos(math.radians(start + sweep))
    return (f'<svg class="{size_cls}" viewBox="0 0 64 64" aria-hidden="true" focusable="false">'
            f'<circle class="mg-ring" cx="32" cy="32" r="{r}"/>'
            f'<path class="mg-arc" d="M{f1(x1)} {f1(y1)}A{r} {r} 0 0 1 {f1(x2)} {f1(y2)}"/>'
            f'<path class="mg-tan" d="M{f1(x2)} {f1(y2)}L{f1(x2 + 9 * tx)} {f1(y2 + 9 * ty)}"/>'
            f'<circle class="mg-dot" cx="{f1(x2)}" cy="{f1(y2)}" r="2.6"/>'
            f'<text class="mg-text" x="32" y="33" text-anchor="middle" dominant-baseline="middle">{e(initials(name))}</text></svg>')


# ----------------------------------------------------------------------------
# Components
# ----------------------------------------------------------------------------

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def news_date(value: str) -> tuple[str, str]:
    parts = value.split("-")
    if len(parts) == 1:
        return value, value
    label = f"{MONTHS[int(parts[1]) - 1]} {parts[0]}"
    if len(parts) == 3:
        label = f"{int(parts[2])} {label}"
    return value, label


def news_key(item) -> tuple:
    parts = [int(x) for x in item["date"].split("-")] + [0, 0]
    return tuple(parts[:3])


def news_items(site: Site, limit: int | None = None) -> str:
    return news_list(sorted(site.news["items"], key=news_key, reverse=True)[:limit])


def news_list(items) -> str:
    out = []
    for it in items:
        iso, label = news_date(it["date"])
        link = ""
        if it.get("link"):
            link = " " + a(it["link"]["url"], e(it["link"]["label"]), "inline-link", external=True)
        out.append(f'<li class="news-item"><time class="news-date" datetime="{iso}">{label}</time>'
                   f'<p class="news-text"><span class="kind kind-{e(it["kind"])}">{e(it["kind"])}</span> {e(it["text"])}{link}</p></li>')
    return '<ol class="news-list">' + "".join(out) + "</ol>"


def authors_html(rec) -> str:
    names = []
    for au in rec["author"]:
        n = e(au["literal"])
        names.append(f"<strong>{n}</strong>" if "abu-dakka" in au["literal"].casefold() else n)
    return ", ".join(names)


def field_chips(site: Site, page: str, numbers, cls="chips") -> str:
    items = []
    for n in numbers:
        f = site.field_by_number.get(n)
        if not f:
            continue
        items.append("<li>" + a(site.href(page, f"field:{f['slug']}"), e(f["title"]), "chip") + "</li>")
    return f'<ul class="{cls}">' + "".join(items) + "</ul>" if items else ""


def bib_block(site: Site, rec) -> str:
    """The entry's BibTeX, hidden; the page script adds a "Copy BibTeX" button that copies it."""
    return f'<pre class="pub-bib" data-bib hidden>{e(site.bibtex[rec["id"]])}</pre>'


def pub_item(site: Site, page: str, rec, chips=True, heading="h3", bib=False) -> str:
    title = e(rec["title"]).replace("³", "<sup>3</sup>")
    links = "".join("<li>" + a(l["URL"], e(l["label"]), "link-badge", external=True) + "</li>" for l in rec["links"])
    links_html = f'<ul class="pub-links">{links}</ul>' if links else ""
    fields_attr = " ".join(str(n) for n in rec["fields"])
    status = '<span class="pub-status">Preprint</span> ' if rec["status"] == "preprint" else ""
    return (f'<li class="pub" data-fields="{fields_attr}"><{heading} class="pub-title">{title}</{heading}>'
            f'<p class="pub-venue">{status}{e(rec["display-venue"])}</p>'
            f'<p class="pub-authors">{authors_html(rec)}</p>{links_html}'
            f'{field_chips(site, page, rec["fields"], "chips chips-small") if chips else ""}'
            f'{bib_block(site, rec) if bib else ""}</li>')


def avatar(site: Site, page: str, person_id: str, name: str, size_cls: str = "monogram") -> str:
    """The member's photo (src/photos/<id>.jpg) when one is supplied, otherwise the monogram."""
    if (PHOTOS / f"{person_id}.jpg").is_file():
        return (f'<img class="{size_cls} photo" src="{site.root(page)}assets/photo-{person_id}.jpg" '
                f'width="384" height="384" alt="{e(name, quote=True)}">')
    return monogram(person_id, name, size_cls)


PROFILE_LINKS = (("scholar", "Google Scholar"), ("orcid", "ORCID"), ("linkedin", "LinkedIn"))


def profile_links(person) -> str:
    """The member's own public profiles, in a fixed order; only those supplied are shown."""
    links = person.get("links", {})
    items = "".join(f'<li>{a(links[k], label, external=True)}</li>' for k, label in PROFILE_LINKS if links.get(k))
    return f'<ul class="person-links">{items}</ul>' if items else ""


def person_card(site: Site, page: str, person, role_label: str, chips=True) -> str:
    paras = "".join(f"<p>{e(p)}</p>" for p in person.get("bio", []))
    bio = f'<div class="person-bio">{paras}</div>' if paras else ""
    return (f'<li class="person">{avatar(site, page, person["id"], person["name"])}'
            f'<div class="person-body"><h3 class="person-name">{e(person["name"])}</h3>'
            f'<p class="person-meta">{e(role_label)} <span aria-hidden="true">·</span> since {person["since"]}</p>'
            f'<p class="person-topic">{e(person["topic"])}</p>'
            f'{bio}'
            f'{profile_links(person)}'
            f'{field_chips(site, page, person["fields"], "chips chips-small") if chips else ""}</div></li>')


def nav_html(site: Site, page: str) -> str:
    items = []
    for key in NAV:
        href = site.href(page, key)
        if href is None:
            continue
        current = page == key or (key == "research" and page.startswith("field:"))
        aria = ' aria-current="page"' if page == key else ""
        cls = "nav-link is-current" if current else "nav-link"
        items.append(f'<li><a class="{cls}" href="{href}"{aria}>{PAGES[key][1]}</a></li>')
    return '<ul class="nav-list">' + "".join(items) + "</ul>"


def png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"not a PNG: {path}")
    return struct.unpack(">II", head[16:24])


def logo_html(site: Site, page: str, cls: str = "") -> str:
    root = site.root(page)
    alt = e(site.site["title"], quote=True)
    w, h = png_size(BRAND_WEB / "logo.png")
    return (f'<img class="logo logo-light{cls}" src="{root}assets/logo.png" width="{w}" height="{h}" alt="{alt}">'
            f'<img class="logo logo-dark{cls}" src="{root}assets/logo-dark.png" width="{w}" height="{h}" alt="{alt}">')


def layout(site: Site, page: str, title: str, description: str, content: str, body_class: str = "") -> str:
    s = site.site
    footer_nav = "".join(f'<li><a href="{site.href(page, key)}">{PAGES[key][1]}</a></li>'
                         for key in NAV if site.href(page, key))
    address = "".join(f"<br>{e(line)}" for line in s.get("address", []))
    return render(
        "base.html",
        title=title,
        description=description,
        root=site.root(page),
        body_class=body_class,
        home=site.href(page, "home"),
        logo=logo_html(site, page),
        nav=nav_html(site, page),
        content=content,
        footer_nav=footer_nav,
        name=s["name"],
        full_name=s["full_name"],
        affiliation=s["affiliation"],
        address=address,
        email=s["email"],
        github=s["github"],
        pi_name=s["pi"]["name"],
        pi_site=s["pi"]["website"],
        year=dt.date.today().year,
    )


def page_head(eyebrow: str, title: str, lede: str) -> str:
    lede_html = f'<p class="lede">{lede}</p>' if lede else ""
    return f'<header class="wrap page-head"><p class="eyebrow">{e(eyebrow)}</p><h1>{e(title)}</h1>{lede_html}</header>'


def mailto(site: Site) -> str:
    return f"mailto:{site.site['email']}?subject=REACH%20Lab%20enquiry"


# ----------------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------------

HERO_LABEL = ("A sphere with latitude and longitude lines. A geodesic runs between two points, with tangent planes "
              "at both ends, a fan of paths leaving the start and a contact normal at the goal.")


def page_home(site: Site) -> str:
    s = site.site
    page = "home"
    join = site.join
    audiences = "".join(
        f'<li class="join-card"><h3>{e(x["title"])}</h3><p>{e(x["text"])}</p></li>' for x in join["audiences"])
    tiles = []
    for f in site.fields:
        title = a(site.href(page, f"field:{f['slug']}"), e(f["title"]), "tile-link")
        tiles.append(f'<li class="tile is-linked"><div class="tile-art">{FIELD_ART[f["slug"]](None)}</div>'
                     f'<h3 class="tile-title">{title}</h3><p>{e(f["summary"])}</p></li>')
    members = site.people["members"]
    group_words = []
    for g in site.people["groups"]:
        n = sum(1 for m in members if m["group"] == g["key"])
        if n:
            group_words.append(f"{n} {g['one'] if n == 1 else g['many']}")
    people_sentence = (", ".join(group_words[:-1]) + " and " + group_words[-1]) if len(group_words) > 1 else group_words[0]
    monos = "".join(f'<li title="{e(m["name"], quote=True)}">{avatar(site, page, m["id"], m["name"], "monogram monogram-sm")}'
                    f'<span class="visually-hidden">{e(m["name"])}</span></li>'
                    for m in [dict(id=s["pi"]["id"], name=s["pi"]["name"])] + members)
    recent = [r for r in site.publications if r["status"] == "published"][:4]
    content = render(
        "home.html",
        eyebrow=s["affiliation"],
        headline=s["headline"],
        mission=s["mission"],
        join_primary=a(site.href(page, "join"), "Join the lab", "btn btn-primary"),
        research_link=a(site.href(page, "research"), "Our research", "btn"),
        hero_art=art_hero(HERO_LABEL),
        join_heading="Work with us",
        join_lede=join["lede"],
        join_cards=audiences,
        join_cta=a(site.href(page, "join"), "What to include in your email", "btn btn-primary"),
        tiles="".join(tiles),
        cross_cutting=s["cross_cutting"],
        news=news_items(site, 5),
        news_more=a(site.href(page, "news"), "All news", "more"),
        pubs="".join(pub_item(site, page, r, chips=False) for r in recent),
        pubs_more=a(site.href(page, "publications"), f"All publications since {s['publications']['from_year']}", "more"),
        people_sentence=f"{people_sentence}, led by {s['pi']['name']}.",
        monograms=monos,
        people_more=a(site.href(page, "people"), "Meet the people", "more"),
    )
    return layout(site, page, s["title"],
                  f"{s['title']}, {s['affiliation']}: robot learning and control that combines control theory, "
                  "differential geometry and machine learning.",
                  content, "page-home")


def page_research(site: Site) -> str:
    page = "research"
    s = site.site
    rows = []
    for f in site.fields:
        n_people = sum(1 for m in site.people["members"] if f["number"] in m["fields"])
        n_pubs = sum(1 for r in site.publications if f["number"] in r["fields"])
        counts = []
        if n_people:
            counts.append(f"{n_people} {'person' if n_people == 1 else 'people'}")
        if n_pubs:
            counts.append(f"{n_pubs} publication{'' if n_pubs == 1 else 's'} since {s['publications']['from_year']}")
        href = site.href(page, f"field:{f['slug']}")
        counts_html = f'<p class="counts">{" · ".join(counts)}</p>' if counts else ""
        rows.append(f'<li class="field-row"><div class="field-row-art">{FIELD_ART[f["slug"]](None)}</div>'
                    f'<div><h2>{a(href, e(f["title"]))}</h2><p>{e(f["summary"])}</p>{counts_html}</div></li>')
    content = (page_head("Research", "Research", e(s["research_intro"]) + " " + e(s["cross_cutting"]))
               + f'<div class="wrap"><ol class="field-list">{"".join(rows)}</ol></div>')
    return layout(site, page, f"Research · {s['name']}",
                  f"The research fields of {s['title']}: " + "; ".join(f["title"] for f in site.fields) + ".",
                  content, "page-research")


def page_field(site: Site, field) -> str:
    page = f"field:{field['slug']}"
    s = site.site
    roles = {g["key"]: g["role"] for g in site.people["groups"]}
    people = [m for m in site.people["members"] if field["number"] in m["fields"]]
    people_html = "".join(person_card(site, page, m, roles[m["group"]], chips=False) for m in people)
    pubs = [r for r in site.publications if field["number"] in r["fields"]]
    others = "".join("<li>" + a(site.href(page, f"field:{f['slug']}"), e(f["title"]), "chip") + "</li>"
                     for f in site.fields if f is not field)
    content = render(
        "field.html",
        crumbs=a(site.href(page, "research"), "Research"),
        title=field["title"],
        summary=field["summary"],
        body=field["body"],
        art=FIELD_ART[field["slug"]](field["art_label"]),
        people=(f'<section class="section-tight"><h2>People</h2>'
                f'<ul class="person-grid person-grid-compact">{people_html}</ul></section>') if people else "",
        pubs=(f'<section class="section-tight"><h2>Publications since {s["publications"]["from_year"]}</h2>'
              f'<ol class="pub-list">{"".join(pub_item(site, page, r, chips=False, bib=True) for r in pubs)}</ol></section>') if pubs else "",
        others=others,
    )
    return layout(site, page, f"{field['title']} · {s['name']}", f"{field['title']} at {s['name']}: {field['summary']}",
                  content, "page-field")


def page_people(site: Site) -> str:
    page = "people"
    s = site.site
    pi = s["pi"]
    sections = []
    for g in site.people["groups"]:
        members = sorted((m for m in site.people["members"] if m["group"] == g["key"]), key=lambda m: (m["since"], m["name"]))
        if not members:
            continue
        cards = "".join(person_card(site, page, m, g["role"]) for m in members)
        sections.append(f'<section class="section-tight" aria-labelledby="g-{g["key"]}"><h2 id="g-{g["key"]}">{e(g["heading"])}</h2>'
                        f'<ul class="person-grid">{cards}</ul></section>')
    roles = {g["key"]: g["role"] for g in site.people["groups"]}
    alumni = "".join(f'<li><span class="alum-name">{e(p["name"])}</span> <span class="alum-meta">{e(roles[p["group"]])}'
                     f'{", " + str(p["since"]) + "–" if p.get("since") else ", until "}{p["until"]}</span></li>'
                     for p in sorted(site.people["alumni"], key=lambda p: (-p["until"], p["name"])))
    pi_card = render(
        "pi-card.html",
        monogram=avatar(site, page, pi["id"], pi["name"], "monogram monogram-lg"),
        name=pi["name"],
        role=pi["role"],
        title=pi["title"],
        website=pi["website"],
        scholar=pi["scholar"],
        orcid=pi["orcid"],
        linkedin=pi["linkedin"],
        bio='<div class="person-bio">' + "".join(f"<p>{e(p)}</p>" for p in pi.get("bio", [])) + "</div>",
        email=s["email"],
    )
    content = render(
        "people.html",
        lede=f"Postdoctoral researchers, PhD students and undergraduate researchers working with {pi['name']} at {s['affiliation']}.",
        pi_card=pi_card,
        sections="".join(sections),
        alumni=(f'<section class="section-tight" aria-labelledby="g-alumni"><h2 id="g-alumni">Alumni</h2>'
                f'<ul class="alumni">{alumni}</ul></section>') if alumni else "",
    )
    return layout(site, page, f"People · {s['name']}",
                  f"Postdoctoral researchers, PhD students, undergraduate researchers and alumni of {s['title']}.",
                  content, "page-people")


def page_publications(site: Site) -> str:
    page = "publications"
    s = site.site
    from_year = s["publications"]["from_year"]
    groups = []
    preprints = [r for r in site.publications if r["status"] == "preprint"]
    if preprints:
        groups.append(("preprints", "Preprints", preprints))
    published = [r for r in site.publications if r["status"] == "published"]
    for year in sorted({r["year"] for r in published}, reverse=True):
        groups.append((f"y{year}", str(year), [r for r in published if r["year"] == year]))
    sections = "".join(
        f'<section class="pub-year" data-year-group aria-labelledby="{gid}"><h2 id="{gid}">{e(label)}</h2>'
        f'<ol class="pub-list">{"".join(pub_item(site, page, r, bib=True) for r in recs)}</ol></section>'
        for gid, label, recs in groups)
    options = [f'<label><input type="radio" name="field" value="all" checked> All fields</label>']
    for f in site.fields:
        n = sum(1 for r in site.publications if f["number"] in r["fields"])
        if n:
            options.append(f'<label><input type="radio" name="field" value="{f["number"]}"> {e(f["title"])} ({n})</label>')
    total = len(site.publications)
    filter_html = (f'<form class="pub-filter" data-pub-filter hidden><fieldset><legend>Show publications in</legend>'
                   f'<div class="filter-options">{"".join(options)}</div></fieldset>'
                   f'<p class="filter-count" data-pub-count aria-live="polite">{total} publications</p></form>')
    earlier = a(s["publications"]["earlier_work_url"], f"{e(s['pi']['name'])}’s publication list", external=True)
    lede = (f"Publications since {from_year}, when {e(s['pi']['name'])} joined {e(s['affiliation'])}, newest first. "
            f"Earlier work is on {earlier}.")
    content = page_head("Publications", "Publications", lede) + f'<div class="wrap">{filter_html}{sections}</div>'
    return layout(site, page, f"Publications · {s['name']}",
                  f"Publications of {s['title']} since {from_year}, by year and research field.", content, "page-publications")


def page_news(site: Site) -> str:
    page = "news"
    s = site.site
    items = sorted(site.news["items"], key=news_key, reverse=True)
    years = []
    for year in sorted({news_key(i)[0] for i in items}, reverse=True):
        years.append(f'<section class="news-year" aria-labelledby="n{year}"><h2 id="n{year}">{year}</h2>'
                     f'{news_list([i for i in items if news_key(i)[0] == year])}</section>')
    content = page_head("News", "News", f"Papers, awards, talks and people joining {e(s['name'])}.") + \
        f'<div class="wrap narrow">{"".join(years)}</div>'
    return layout(site, page, f"News · {s['name']}", f"News from {s['title']}: papers, awards, talks and new members.",
                  content, "page-news")


def page_join(site: Site) -> str:
    page = "join"
    s = site.site
    j = site.join
    def card_links(x) -> str:
        links = x.get("links") or []
        if not links:
            return ""
        return '<p class="join-links">' + " · ".join(a(l["url"], e(l["label"]), external=True) for l in links) + "</p>"
    cards = "".join(f'<li class="join-card"><h2>{e(x["title"])}</h2><p>{e(x["text"])}</p>{card_links(x)}</li>'
                    for x in j["audiences"])
    checklist = "".join(f"<li><span>{e(x)}</span></li>" for x in j["include"])
    closing = e(j["closing"])
    pubs = site.href(page, "publications")
    if pubs:
        closing = closing.replace("recent publications", a(pubs, "recent publications"), 1)
    content = (page_head("Join", j["heading"], e(j["lede"]))
               + f'<div class="wrap join-page"><ul class="join-cards">{cards}</ul>'
               + f'<section class="section-tight" aria-labelledby="include"><h2 id="include">{e(j["include_heading"])}</h2>'
               + f'<ol class="checklist">{checklist}</ol>'
               + f'<p class="actions"><a class="btn btn-primary" href="{mailto(site)}">Email {e(s["email"])}</a></p>'
               + f'<p class="lede">{closing}</p></section></div>')
    return layout(site, page, f"Join · {s['name']}",
                  f"How to join {s['title']}: who we welcome and what to include in your email.", content, "page-join")


def page_resources(site: Site) -> str:
    page = "resources"
    s = site.site
    groups = "".join(
        f'<section class="resource-group" aria-labelledby="r{i}"><h2 id="r{i}">{e(g["heading"])}</h2><ul class="resource-list">'
        + "".join(f'<li><h3>{e(it["name"])}</h3><p>{e(it["text"])}</p></li>' for it in g["items"])
        + "</ul></section>"
        for i, g in enumerate(site.resources["groups"]))
    content = page_head("Resources", "Resources", f"The robots, sensors and machines {e(s['name'])} works with.") + \
        f'<div class="wrap">{groups}</div>'
    return layout(site, page, f"Resources · {s['name']}", f"Robots, sensing, fabrication and compute at {s['title']}.",
                  content, "page-resources")


def page_teaching(site: Site) -> str:
    page = "teaching"
    s = site.site
    t = site.teaching
    items = []
    for c in t["courses"]:
        meta = " · ".join(e(str(c[k])) for k in ("code", "level", "terms") if c.get(k))
        meta_html = f'<p class="course-meta">{meta}</p>' if meta else ""
        text_html = f"<p>{e(c['text'])}</p>" if c.get("text") else ""
        items.append(f'<li><h2>{e(c["title"])}</h2>{meta_html}{text_html}</li>')
    content = page_head("Teaching", "Teaching", e(t.get("lede", ""))) + \
        f'<div class="wrap narrow"><ul class="course-list">{"".join(items)}</ul></div>'
    return layout(site, page, f"Teaching · {s['name']}", f"Courses taught by members of {s['title']}.", content, "page-teaching")


def map_embed(map_url: str, embed_url: str) -> str:
    """A small map window. The whole window is one link that opens Google Maps in a new tab; the frame is
    the only third-party request on the site and is loaded lazily, on the Contact page only."""
    u, em = e(map_url, quote=True), e(embed_url, quote=True)
    return (f'<div class="map-embed"><iframe src="{em}" title="Map of NYU Abu Dhabi" loading="lazy" '
            f'referrerpolicy="no-referrer" tabindex="-1" aria-hidden="true"></iframe>'
            f'<a class="map-embed-link" href="{u}" target="_blank" rel="noopener" '
            f'aria-label="Open the NYU Abu Dhabi map in Google Maps (opens in a new tab)"></a></div>'
            f'<p class="map-caption">{a(map_url, "Open in Google Maps", external=True).replace("<a ", "<a target=\"_blank\" ", 1)}</p>')


def page_contact(site: Site) -> str:
    page = "contact"
    s = site.site
    rows = [("Email", f'<a href="mailto:{e(s["email"])}">{e(s["email"])}</a>'),
            ("Lab", f'{e(s["title"])}<br>{e(s["affiliation"])}' + "".join(f"<br>{e(x)}" for x in s.get("address", []))),
            *([("Map", map_embed(s["map_url"], s["map_embed_url"]))] if s.get("map_url") and s.get("map_embed_url") else
              [("Map", a(s["map_url"], "NYU Abu Dhabi on Google Maps", external=True))] if s.get("map_url") else []),
            ("Code", a(s["github"], "The lab on GitHub", external=True))]
    join = site.href(page, "join")
    dl = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in rows)
    lede = "Write to us by email." + (f" If you would like to work with us, read {a(join, 'how to join')} first." if join else "")
    content = page_head("Contact", "Contact", lede) + f'<div class="wrap"><dl class="contact-list">{dl}</dl></div>'
    return layout(site, page, f"Contact · {s['name']}", f"How to reach {s['title']} at {s['affiliation']}.", content, "page-contact")


def page_404(site: Site) -> str:
    page = "404"
    s = site.site
    links = "".join("<li>" + a(site.href(page, k), PAGES[k][1], "chip") + "</li>" for k in ["home"] + NAV if site.href(page, k))
    content = (f'<div class="wrap not-found"><p class="eyebrow">Error 404</p><h1>Page not found</h1>'
               f'<p class="lede">There is no page at this address. It may have moved; these pages are a good place to start.</p>'
               f'<ul class="chips">{links}</ul></div>')
    return layout(site, page, f"Page not found · {s['name']}", f"The page you asked for is not on the {s['title']} website.",
                  content, "page-404")


BUILDERS = {
    "home": page_home, "research": page_research, "people": page_people, "publications": page_publications,
    "news": page_news, "join": page_join, "resources": page_resources, "teaching": page_teaching,
    "contact": page_contact, "404": page_404,
}


def build(out: Path, site: Site) -> list[Path]:
    written = []
    for key in sorted(site.built):
        if key.startswith("field:"):
            field = next(f for f in site.fields if f"field:{f['slug']}" == key)
            text = page_field(site, field)
        else:
            text = BUILDERS[key](site)
        target = out / PAGES[key][0]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        written.append(target)
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for src in sorted(list(ASSETS.iterdir()) + list(BRAND_WEB.iterdir())):
        if src.is_file():
            shutil.copy2(src, assets / src.name)
    if PHOTOS.is_dir():
        for src in sorted(PHOTOS.glob("*.jpg")):
            shutil.copy2(src, assets / f"photo-{src.name}")
    return written


# ----------------------------------------------------------------------------
# Leak test
# ----------------------------------------------------------------------------

WORDS = ["visa", "immigration", "IRB", "reject", "withdraw", "declin", "salary", "funding", "budget",
         "submitted", "under review", "proposal", "sponsor", "confidential", "decision", "checker",
         "Codex", "Claude"]
PATH_RE = re.compile(r"\b(lab|people|research|funding|operations|playbooks|scripts)/", re.I)
REGEXES = [
    ("record id D##", re.compile(r"\bD\d{2}\b", re.I)),
    ("dollar amount", re.compile(r"\$\s?\d")),
    ("netid", re.compile(r"\bnetid\b", re.I)),
]
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# Exact phrases exempt from the word list (the bare word stays forbidden). Approved by Fares, 2026-09-13:
# "decision-making" is the public name of research field 6.
EXEMPT_PHRASES = [re.compile(r"decision-making", re.I)]
INVISIBLE = dict.fromkeys(map(ord, "­​‌‍⁠﻿"), None)


def split_list(inner: str) -> list[str]:
    """Split the inside of a flow-style YAML list `[a, "b, c", 'd']` into items.

    A quoted item is one item, commas inside the quotes included; `\\"` and `\\\\` inside
    double quotes and `''` inside single quotes stand for one quote or backslash. Unquoted
    items end at the next comma. Empty items are dropped.
    """
    items: list[str] = []
    i, n = 0, len(inner)
    while i < n:
        c = inner[i]
        if c in " \t,":
            i += 1
        elif c in "\"'":
            buf: list[str] = []
            j = i + 1
            while j < n:
                d = inner[j]
                if c == '"' and d == "\\" and j + 1 < n and inner[j + 1] in '"\\':
                    buf.append(inner[j + 1])
                    j += 2
                elif c == "'" and d == "'" and j + 1 < n and inner[j + 1] == "'":
                    buf.append("'")
                    j += 2
                elif d == c:
                    break
                else:
                    buf.append(d)
                    j += 1
            items.append("".join(buf))
            i = j + 1
        else:
            j = inner.find(",", i)
            if j < 0:
                j = n
            items.append(inner[i:j].strip())
            i = j
    return [s for s in items if s]


def selftest_split_list() -> None:
    """Run by --test: a quoted item with a comma inside must stay one item, also after ", "."""
    cases = {
        '"a, b", c': ["a, b", "c"],
        '"a, b", "c, d"': ["a, b", "c, d"],
        "'x, y', z": ["x, y", "z"],
        'a,"b",c': ["a", "b", "c"],
        r'"say \"hi\", ok"': ['say "hi", ok'],
        "'it''s', b": ["it's", "b"],
        '  "a"  , , b  ': ["a", "b"],
        "": [],
    }
    for inner, want in cases.items():
        got = split_list(inner)
        assert got == want, f"split_list({inner!r}) = {got!r}, want {want!r}"


def front_matter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    data = {}
    for line in text[4:end].splitlines():
        m = re.match(r"^([A-Za-z_]+):\s*(.*?)\s*(#.*)?$", line)
        if not m:
            continue
        key, value = m.group(1), m.group(2)
        if value.startswith("[") and value.endswith("]"):
            data[key] = split_list(value[1:-1])
        else:
            data[key] = value.strip().strip('"').strip("'")
    return data


def forbidden_strings(records: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for proposal in sorted(records.glob("funding/**/proposal.md")):
        if "_TEMPLATE" in str(proposal):
            continue
        fm = front_matter(proposal)
        rel = proposal.relative_to(records)
        for key in ("title", "id", "sponsor"):
            if fm.get(key):
                out.append((fm[key], f"{rel} {key}"))
        for alias in fm.get("aliases", []):
            out.append((alias, f"{rel} alias"))
    for person in sorted(records.glob("people/former/*.md")):
        fm = front_matter(person)
        if fm.get("status") == "did-not-join":
            rel = person.relative_to(records)
            for key in ("name", "id"):
                if fm.get(key):
                    out.append((fm[key], f"{rel} {key} (did-not-join)"))
            for m in fm.get("misspellings", []):
                out.append((m, f"{rel} misspelling (did-not-join)"))
    for person in sorted(records.glob("people/**/*.md")):
        fm = front_matter(person)
        if fm.get("public") == "no":
            rel = person.relative_to(records)
            for key in ("name", "id"):
                if fm.get(key):
                    out.append((fm[key], f"{rel} {key} (public: no)"))
            for m in fm.get("misspellings", []):
                out.append((m, f"{rel} misspelling (public: no)"))
    skip = {"personal-website", "reachLab-website", ".git", ".codex", ".agents"}
    for md in sorted(records.rglob("*.md")):
        if skip & set(md.relative_to(records).parts):
            continue
        for ev in front_matter(md).get("evidence", []):
            out.append((ev, f"{md.relative_to(records)} evidence"))
    return [(s, why) for s, why in out if s.strip()]


def token_pattern(s: str) -> re.Pattern:
    body = r"\s+".join(re.escape(part) for part in s.split())
    return re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", re.I)


class Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.in_title = False
        self.description = None
        self.h1 = 0
        self.problems: list[str] = []
        self.urls: list[str] = []
        self.ids: set[str] = set()
        self.text: list[str] = []
        self.svg_title_depth = 0

    def handle_starttag(self, tag, attrs):
        at = dict(attrs)
        if "id" in at:
            self.ids.add(at["id"])
        if tag == "title" and self.svg_title_depth == 0:
            self.in_title = True
        if tag == "svg":
            self.svg_title_depth += 1
            if at.get("aria-hidden") != "true" and not at.get("aria-label"):
                self.problems.append("svg without aria-label or aria-hidden")
        if tag == "meta" and at.get("name") == "description":
            self.description = at.get("content") or ""
        if tag == "h1":
            self.h1 += 1
        if tag == "img" and not (at.get("alt") or "").strip():
            self.problems.append(f"img without alt text: {at.get('src')}")
        for key in ("href", "src"):
            if key in at and at[key] is not None:
                self.urls.append(at[key])
        for key in ("alt", "title", "aria-label", "content"):
            if at.get(key):
                self.text.append(at[key])

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag == "svg":
            self.svg_title_depth -= 1

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        self.text.append(data)


def is_external(url: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I))


def leak_test(out: Path, records: Path, site: Site) -> list[str]:
    hits: list[str] = []
    pi_email = site.site["email"].casefold()
    patterns = [(token_pattern(s), s, why) for s, why in forbidden_strings(records)]
    files = sorted(p for p in out.rglob("*") if p.suffix in {".html", ".css", ".js", ".svg", ".json", ".txt"})
    css_js = sum(p.stat().st_size for p in files if p.suffix in {".css", ".js"})
    for f in files:
        rel = f.relative_to(out).as_posix()
        raw = f.read_text(encoding="utf-8")
        scan_text = raw
        if f.suffix == ".html":
            scan = Scan()
            scan.feed(raw)
            if not scan.title.strip():
                hits.append(f"{rel}: no <title>")
            if not (scan.description or "").strip():
                hits.append(f"{rel}: no meta description")
            if scan.h1 != 1:
                hits.append(f"{rel}: {scan.h1} h1 elements (expected 1)")
            hits += [f"{rel}: {p}" for p in scan.problems]
            internal_ok = set()
            for url in scan.urls:
                if url.startswith("/"):
                    hits.append(f"{rel}: path starts with '/': {url}")
                    continue
                if is_external(url):
                    continue
                if url.startswith("#"):
                    if url[1:] and url[1:] not in scan.ids:
                        hits.append(f"{rel}: anchor does not exist: {url}")
                    continue
                target_rel = url.split("#")[0].split("?")[0]
                target = (f.parent / target_rel)
                if target_rel.endswith("/") or target.is_dir():
                    target = target / "index.html"
                if not target.resolve().is_file() or out.resolve() not in target.resolve().parents:
                    hits.append(f"{rel}: link does not resolve: {url}")
                else:
                    internal_ok.add(url)
            if f.stat().st_size + css_js > MAX_PAGE_BYTES:
                hits.append(f"{rel}: {f.stat().st_size + css_js} bytes with CSS and JS (limit {MAX_PAGE_BYTES})")
            visible = " ".join(scan.text)
            # The site's own sections (research/, people/) are required URLs; an internal
            # link that resolves to a built file is structure, not a record path.
            path_text = raw
            for url in sorted(internal_ok, key=len, reverse=True):
                path_text = path_text.replace(f'"{url}"', '""')
            scan_text = raw + "\n" + html.unescape(raw) + "\n" + visible
        else:
            path_text = raw
            if re.search(r"url\(\s*['\"]?/", raw):
                hits.append(f"{rel}: CSS url() starts with '/'")
        norm = scan_text.translate(INVISIBLE)
        path_text = path_text.translate(INVISIBLE)
        found: set[str] = set()
        word_text = norm
        for rx in EXEMPT_PHRASES:
            word_text = rx.sub(" ", word_text)
        for word in WORDS:
            if word.casefold() in word_text.casefold():
                found.add(f"word {word!r}")
        for m in PATH_RE.finditer(path_text):
            found.add(f"record path {m.group(0)!r}")
        for label, rx in REGEXES:
            for m in rx.finditer(norm):
                found.add(f"{label} {m.group(0)!r}")
        for m in EMAIL_RE.finditer(norm):
            if m.group(0).casefold() != pi_email:
                found.add(f"email {m.group(0)!r}")
        for rx, s, why in patterns:
            if rx.search(norm):
                found.add(f"record string {s!r} ({why})")
        hits += [f"{rel}: {x}" for x in sorted(found)]
    hits += consistency(records, site)
    return hits


def consistency(records: Path, site: Site) -> list[str]:
    """People on the site must match the records' front matter."""
    problems = []
    groups = {"postdoc": "postdocs", "phd": "phd", "undergrad": "undergrads"}
    for m in site.people["members"]:
        rec = records / "people" / groups[m["group"]] / f"{m['id']}.md"
        fm = front_matter(rec) if rec.is_file() else {}
        if fm.get("status") != "active":
            problems.append(f"people.json: {m['id']} is not an active record in {groups[m['group']]}/")
        if fm.get("public") == "no":
            problems.append(f"people.json: {m['id']} is marked public: no and must not be listed")
    for p in site.people["alumni"]:
        rec = records / "people" / "former" / f"{p['id']}.md"
        fm = front_matter(rec) if rec.is_file() else {}
        if fm.get("status") not in {"alumni", "departed"}:
            problems.append(f"people.json: alumnus {p['id']} is not an alumni/departed record")
        if fm.get("public") == "no":
            problems.append(f"people.json: alumnus {p['id']} is marked public: no and must not be listed")
    return problems


# ----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--test", action="store_true", help="build to a temporary directory and run the leak test only")
    parser.add_argument("--records", type=Path, default=SITE.parent, help="REACH-Lab records root (default: parent folder)")
    args = parser.parse_args()
    records = args.records.resolve()
    for need in ("people/former", "funding", "lab/pi.md"):
        if not (records / need).exists():
            print(f"records not found: {records / need} (pass --records)", file=sys.stderr)
            return 2

    if args.test:
        selftest_split_list()
    site = Site()
    with tempfile.TemporaryDirectory(prefix="reach-site-") as tmp:
        out = Path(tmp)
        written = build(out, site)
        hits = leak_test(out, records, site)
        synced = (records / "personal-website/data/publications.csl.json")
        if synced.is_file() and synced.read_bytes() != (DATA / "publications.csl.json").read_bytes():
            print("warning: data/publications.csl.json differs from personal-website/data/publications.csl.json — re-sync it")
        for logo in sorted(BRAND.glob("*.png")):
            record = records / "lab/brand/nyuad-variants" / logo.name
            if not record.is_file() or record.read_bytes() != logo.read_bytes():
                print(f"warning: src/brand/{logo.name} differs from lab/brand/nyuad-variants/{logo.name} — re-copy it and regenerate src/brand/web/")
        print(f"built {len(written)} page(s): " + ", ".join(p.relative_to(out).as_posix() for p in written))
        if hits:
            print(f"LEAK TEST FAILED — {len(hits)} hit(s):")
            for h in hits:
                print(f"  {h}")
            if not args.test:
                removed = remove_owned()
                print(f"output deleted: {', '.join(removed) or 'nothing to delete'}")
            return 1
        print("leak test passed: 0 hits")
        if args.test:
            return 0
        remove_owned()
        for name in OWNED:
            src = out / name
            if src.is_dir():
                shutil.copytree(src, SITE / name)
            elif src.is_file():
                shutil.copy2(src, SITE / name)
        (SITE / ".nojekyll").touch()
        print(f"wrote site to {SITE}")
    return 0


def remove_owned() -> list[str]:
    removed = []
    for name in OWNED:
        target = SITE / name
        assert target.parent == SITE
        if target.is_dir():
            shutil.rmtree(target)
            removed.append(name + "/")
        elif target.exists():
            target.unlink()
            removed.append(name)
    return removed


if __name__ == "__main__":
    raise SystemExit(main())
