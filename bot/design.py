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


def render(headline: str, category: str, source: str, settings: dict, handle: str, out_path: Path) -> Path:
    d = settings["design"]
    bg, accent, fg, muted = _hex(d["background"]), _hex(d["accent"]), _hex(d["text"]), _hex(d["muted"])

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
        a = int(70 * (y / H))
        gd.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    img = Image.alpha_composite(img, grad)

    # Decorative "wheels": faint concentric rings with spokes (only when there's no logo).
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    cx, cy = W - 120, 250
    for r, width, alpha in ((330, 10, 40), (300, 3, 28), (95, 6, 36)):
        dd.ellipse([cx - r, cy - r, cx + r, cy + r], outline=accent[:3] + (alpha,), width=width)
    import math
    for k in range(16):
        ang = 2 * math.pi * k / 16
        dd.line([(cx + 95 * math.cos(ang), cy + 95 * math.sin(ang)),
                 (cx + 300 * math.cos(ang + 0.35), cy + 300 * math.sin(ang + 0.35))],
                fill=accent[:3] + (18,), width=2)
    if logo is None:
        img = Image.alpha_composite(img, deco)

    draw = ImageDraw.Draw(img)

    # Top bar: page name + optional logo.
    draw.rectangle([MARGIN, MARGIN, MARGIN + 64, MARGIN + 10], fill=accent)
    draw.text((MARGIN, MARGIN + 30), settings["page"]["name"].upper(), font=bold_font(34), fill=fg)
    if logo is not None:
        img.alpha_composite(logo, (W - MARGIN - logo.width, MARGIN))

    # Headline block, anchored above the footer.
    footer_top = H - MARGIN - 90
    max_w = W - 2 * MARGIN
    font, lines, line_h = _fit_headline(draw, headline, max_w, 620)
    block_h = len(lines) * line_h
    y = footer_top - 70 - block_h

    # Category tag.
    tag_font = bold_font(32)
    tag = category.upper()
    tw = draw.textlength(tag, font=tag_font)
    tag_y = y - 100
    draw.rounded_rectangle([MARGIN, tag_y, MARGIN + tw + 44, tag_y + 60], radius=8, fill=accent)
    draw.text((MARGIN + 22, tag_y + 10), tag, font=tag_font, fill=bg)

    for line in lines:
        draw.text((MARGIN, y), line, font=font, fill=fg)
        y += line_h

    # Footer: accent rule, source (left) and date (right). Handle sits top-right.
    draw.rectangle([MARGIN, footer_top, W - MARGIN, footer_top + 4], fill=accent[:3] + (200,))
    small = regular_font(30)
    date_txt = dt.date.today().strftime("%d %b %Y")
    if handle and logo is not None:
        date_txt = f"{handle}  ·  {date_txt}"
    date_w = draw.textlength(date_txt, font=small)
    src_txt = f"Source: {source}"
    while draw.textlength(src_txt, font=small) > max_w - date_w - 40 and len(src_txt) > 12:
        src_txt = src_txt[:-2].rstrip() + "…" if not src_txt.endswith("…") else src_txt[:-2] + "…"
    draw.text((MARGIN, footer_top + 30), src_txt, font=small, fill=muted)
    draw.text((W - MARGIN - date_w, footer_top + 30), date_txt, font=small, fill=muted)
    if handle and logo is None:
        hf = regular_font(30)
        draw.text((W - MARGIN - draw.textlength(handle, font=hf), MARGIN + 34), handle, font=hf, fill=muted)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, "JPEG", quality=92)
    return out_path
