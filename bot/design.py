"""Draws the branded 1080x1350 post graphic with Pillow (no third-party photos)."""
import datetime as dt
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import ROOT

W, H = 1080, 1350
MARGIN = 84
FONTS = ROOT / "assets" / "fonts"


def _font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for n in names:
        p = FONTS / n
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size=size)


def headline_font(size):
    # Anton is downloaded by the workflow if available; DejaVu is bundled as a fallback.
    return _font(["Anton-Regular.ttf", "DejaVuSansCondensed-Bold.ttf"], size)


def bold_font(size):
    return _font(["DejaVuSansCondensed-Bold.ttf", "DejaVuSans-Bold.ttf"], size)


def regular_font(size):
    return _font(["DejaVuSans.ttf"], size)


def _hex(c: str, alpha: int = 255):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def _wrap(draw, text, font, max_width):
    words, lines, line = text.split(), [], ""
    for w in words:
        test = f"{line} {w}".strip()
        if draw.textlength(test, font=font) <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def _fit_headline(draw, text, max_width, max_height):
    uses_anton = (FONTS / "Anton-Regular.ttf").exists()
    if uses_anton:
        text = text.upper()
    for size in range(112, 50, -4):
        font = headline_font(size)
        lines = _wrap(draw, text, font, max_width)
        line_h = int(size * (1.08 if uses_anton else 1.15))
        if len(lines) * line_h <= max_height and all(draw.textlength(l, font=font) <= max_width for l in lines):
            return font, lines, line_h
    font = headline_font(52)
    lines = _wrap(draw, text, font, max_width)[:7]
    return font, lines, 60


def _base(settings: dict, deco_wheel: bool = True):
    """Background, gradient, optional decoration, top bar and logo. Returns (img, draw, colors, logo)."""
    d = settings["design"]
    colors = {k: _hex(d[k]) for k in ("background", "accent", "text", "muted")}
    bg, accent, fg = colors["background"], colors["accent"], colors["text"]

    img = Image.new("RGBA", (W, H), bg)

    logo = None
    logo_path = ROOT / d.get("logo", "")
    if d.get("logo") and logo_path.is_file():
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo.thumbnail((230, 140))
        except Exception:
            logo = None

    # Soft vertical gradient for depth.
    grad = Image.new("RGBA", (W, H))
    gd = ImageDraw.Draw(grad)
    for y in range(H):
        gd.line([(0, y), (W, y)], fill=(0, 0, 0, int(70 * (y / H))))
    img = Image.alpha_composite(img, grad)

    # Decorative "wheel": faint rings with spokes (only when there's no logo).
    if logo is None and deco_wheel:
        import math
        deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dd = ImageDraw.Draw(deco)
        cx, cy = W - 120, 250
        for r, width, alpha in ((330, 10, 40), (300, 3, 28), (95, 6, 36)):
            dd.ellipse([cx - r, cy - r, cx + r, cy + r], outline=accent[:3] + (alpha,), width=width)
        for k in range(16):
            ang = 2 * math.pi * k / 16
            dd.line([(cx + 95 * math.cos(ang), cy + 95 * math.sin(ang)),
                     (cx + 300 * math.cos(ang + 0.35), cy + 300 * math.sin(ang + 0.35))],
                    fill=accent[:3] + (18,), width=2)
        img = Image.alpha_composite(img, deco)

    draw = ImageDraw.Draw(img)
    draw.rectangle([MARGIN, MARGIN, MARGIN + 64, MARGIN + 10], fill=accent)
    draw.text((MARGIN, MARGIN + 30), settings["page"]["name"].upper(), font=bold_font(34), fill=fg)
    if logo is not None:
        img.alpha_composite(logo, (W - MARGIN - logo.width, MARGIN))
    return img, draw, colors, logo


def _footer(draw, colors, source, handle, logo, right_text=None):
    footer_top = H - MARGIN - 90
    max_w = W - 2 * MARGIN
    draw.rectangle([MARGIN, footer_top, W - MARGIN, footer_top + 4], fill=colors["accent"][:3] + (200,))
    small = regular_font(30)
    if right_text is None:
        right_text = dt.date.today().strftime("%d %b %Y")
        if handle and logo is not None:
            right_text = f"{handle}  ·  {right_text}"
    right_font = bold_font(30) if right_text.startswith("Swipe") else small
    right_color = colors["accent"] if right_text.startswith("Swipe") else colors["muted"]
    rw = draw.textlength(right_text, font=right_font)
    src_txt = f"Source: {source}"
    while draw.textlength(src_txt, font=small) > max_w - rw - 40 and len(src_txt) > 12:
        src_txt = src_txt[:-2].rstrip() + "…" if not src_txt.endswith("…") else src_txt[:-2] + "…"
    draw.text((MARGIN, footer_top + 30), src_txt, font=small, fill=colors["muted"])
    draw.text((W - MARGIN - rw, footer_top + 30), right_text, font=right_font, fill=right_color)
    return footer_top


def _save(img, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, "JPEG", quality=92)
    return out_path


def render(headline: str, category: str, source: str, settings: dict, handle: str, out_path: Path,
           swipe: bool = False) -> Path:
    """The cover / single-image post: category tag + big headline."""
    img, draw, colors, logo = _base(settings)
    bg, accent, fg = colors["background"], colors["accent"], colors["text"]
    footer_top = _footer(draw, colors, source, handle, logo, right_text="Swipe for the story  →" if swipe else None)
    if handle and logo is None:
        hf = regular_font(30)
        draw.text((W - MARGIN - draw.textlength(handle, font=hf), MARGIN + 34), handle, font=hf, fill=colors["muted"])

    max_w = W - 2 * MARGIN
    font, lines, line_h = _fit_headline(draw, headline, max_w, 620)
    y = footer_top - 70 - len(lines) * line_h

    tag_font = bold_font(32)
    tag = category.upper()
    tw = draw.textlength(tag, font=tag_font)
    tag_y = y - 100
    draw.rounded_rectangle([MARGIN, tag_y, MARGIN + tw + 44, tag_y + 60], radius=8, fill=accent)
    draw.text((MARGIN + 22, tag_y + 10), tag, font=tag_font, fill=bg)

    for line in lines:
        draw.text((MARGIN, y), line, font=font, fill=fg)
        y += line_h
    return _save(img, out_path)


def render_slide(number: int, total: int, title: str, text: str, source: str, settings: dict,
                 handle: str, out_path: Path) -> Path:
    """A story slide in a carousel: slide counter, short title and body text."""
    img, draw, colors, logo = _base(settings, deco_wheel=False)
    accent, fg = colors["accent"], colors["text"]
    last = number == total
    footer_top = _footer(draw, colors, source, handle, logo,
                         right_text=None if last else "Swipe  →")

    max_w = W - 2 * MARGIN
    top = MARGIN + 200

    # Title.
    y = top + 40
    tf_size = 72
    while tf_size > 40:
        tf = bold_font(tf_size)
        t_lines = _wrap(draw, title, tf, max_w)
        if len(t_lines) <= 3:
            break
        tf_size -= 4
    for line in t_lines:
        draw.text((MARGIN, y), line, font=tf, fill=fg)
        y += int(tf_size * 1.18)
    y += 36
    draw.rectangle([MARGIN, y, MARGIN + 90, y + 8], fill=accent)
    y += 56

    # Body text, shrunk until it fits above the footer.
    room = footer_top - (130 if last else 50) - y
    for size in range(48, 28, -2):
        bf = regular_font(size)
        b_lines = []
        for para in text.split("\n"):
            b_lines += _wrap(draw, para, bf, max_w) or [""]
        lh = int(size * 1.42)
        if len(b_lines) * lh <= room:
            break
    for line in b_lines:
        draw.text((MARGIN, y), line, font=bf, fill=colors["text"][:3] + (235,))
        y += lh

    # Last slide: a follow prompt just above the footer, if there's room.
    if last and handle:
        cta = f"Follow {handle} for daily cycling news"
        cf2 = bold_font(36)
        if draw.textlength(cta, font=cf2) > max_w:
            cta = f"Follow {handle}"
        if y < footer_top - 110:
            draw.text((MARGIN, footer_top - 80), cta, font=cf2, fill=accent)
    return _save(img, out_path)
