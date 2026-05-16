"""
Generate IG-Story-friendly share images for AI music discovery.

Outputs 1080x1920 (9:16) PNGs in two modes:
- "single": one combined card with all info
- "deck": 4 separate slides (cover, grid, tracklist, gemini quote)

Palette is picked randomly per call (or seeded for reproducibility).
"""
from __future__ import annotations

import io
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

_FONTS_DIR = Path(__file__).parent / "fonts"

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

CANVAS_W = 1080
CANVAS_H = 1920

# ── Palettes (analogous / tonal — same color family per palette) ──
# Each palette stays inside ONE hue family. accent1 is the main "pop"
# (lightest on dark bg / darkest on light bg). accent2-4 are tonal
# variations used for borders, numbers, and sparkles. text/muted picked
# so contrast against bg is comfortable.
PALETTES = [
    {
        "name": "Burgundy",
        "bg": (95, 35, 50),
        "accent1": (255, 210, 215),
        "accent2": (210, 110, 130),
        "accent3": (240, 170, 180),
        "accent4": (160, 70, 90),
        "text": (255, 245, 245),
        "muted": (215, 170, 180),
    },
    {
        "name": "Indigo",
        "bg": (35, 30, 90),
        "accent1": (220, 215, 255),
        "accent2": (140, 130, 220),
        "accent3": (180, 170, 235),
        "accent4": (95, 85, 180),
        "text": (250, 250, 255),
        "muted": (170, 165, 210),
    },
    {
        "name": "Rose",
        "bg": (215, 100, 130),
        "accent1": (255, 240, 240),
        "accent2": (255, 200, 210),
        "accent3": (160, 60, 90),
        "accent4": (240, 175, 185),
        "text": (255, 250, 250),
        "muted": (255, 215, 225),
    },
    {
        "name": "Mustard",
        "bg": (220, 170, 60),
        "accent1": (75, 40, 10),
        "accent2": (180, 110, 40),
        "accent3": (240, 200, 100),
        "accent4": (140, 85, 25),
        "text": (50, 25, 0),
        "muted": (130, 90, 35),
    },
    {
        "name": "Sage",
        "bg": (70, 100, 80),
        "accent1": (225, 240, 225),
        "accent2": (130, 175, 145),
        "accent3": (180, 210, 185),
        "accent4": (100, 145, 115),
        "text": (250, 255, 250),
        "muted": (185, 210, 190),
    },
    {
        "name": "Lilac",
        "bg": (175, 160, 210),
        "accent1": (60, 30, 100),
        "accent2": (110, 80, 160),
        "accent3": (145, 120, 190),
        "accent4": (85, 55, 135),
        "text": (40, 20, 70),
        "muted": (115, 95, 150),
    },
    {
        "name": "Ocean",
        "bg": (30, 60, 95),
        "accent1": (200, 230, 250),
        "accent2": (110, 160, 210),
        "accent3": (160, 195, 230),
        "accent4": (75, 115, 175),
        "text": (245, 250, 255),
        "muted": (170, 195, 220),
    },
]


def _adaptive_shift(bg: tuple, amount: int = 32) -> tuple:
    """Slightly lighten dark bg or darken light bg — used for card fills."""
    lum = sum(bg) / 3
    delta = amount if lum < 140 else -amount
    return tuple(max(0, min(c + delta, 255)) for c in bg)


def pick_palette(seed: str | None = None) -> dict:
    rng = random.Random(seed) if seed else random
    return rng.choice(PALETTES)


# ── Font loading ──────────────────────────────────────────────
def _load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """Load font: bundled fonts/  >  Windows fonts  >  PIL default."""
    if bold:
        candidates = [
            _FONTS_DIR / "NotoSansTC-Bold.ttf",
            _FONTS_DIR / "NotoSansTC-VariableFont_wght.ttf",
            "C:/Windows/Fonts/msjhbd.ttc",
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/arialbd.ttf",
        ]
    else:
        candidates = [
            _FONTS_DIR / "NotoSansTC-Regular.ttf",
            _FONTS_DIR / "NotoSansTC-VariableFont_wght.ttf",
            "C:/Windows/Fonts/msjh.ttc",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/arial.ttf",
        ]
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return ImageFont.load_default()


# ── Helpers ───────────────────────────────────────────────────
def _fetch_cover(url: str, size: int) -> Image.Image | None:
    try:
        r = requests.get(url, timeout=10)
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        return img.resize((size, size), Image.LANCZOS)
    except Exception:
        return None


def _measure(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _wrap_text(draw, text: str, font, max_width: int) -> list[str]:
    """Character-level wrap (works for CJK + English mix)."""
    lines = []
    current = ""
    for ch in text:
        test = current + ch
        w, _ = _measure(draw, test, font)
        if w > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def _draw_wrapped(draw, text, font, x, y, max_width, fill, line_gap=10, max_lines=None):
    lines = _wrap_text(draw, text, font, max_width)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and _measure(draw, last + "…", font)[0] > max_width:
            last = last[:-1]
        lines[-1] = last + "…"
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        _, h = _measure(draw, line, font)
        y += h + line_gap
    return y


def _sparkles(draw, palette: dict, rng: random.Random, count: int, region: tuple,
              avoid: tuple | None = None):
    """Draw decorative sparkles. `avoid` is an optional (x1,y1,x2,y2) box to skip."""
    colors = [palette["accent1"], palette["accent2"], palette["accent3"], palette["accent4"]]
    x1, y1, x2, y2 = region
    placed = 0
    attempts = 0
    while placed < count and attempts < count * 10:
        attempts += 1
        cx = rng.randint(x1, x2)
        cy = rng.randint(y1, y2)
        size = rng.randint(6, 18)
        if avoid:
            ax1, ay1, ax2, ay2 = avoid
            # treat the avoid box with a sparkle-sized buffer
            if (ax1 - size <= cx <= ax2 + size) and (ay1 - size <= cy <= ay2 + size):
                continue
        col = rng.choice(colors)
        placed += 1
        # 4-point star (diamond + cross)
        draw.polygon(
            [
                (cx, cy - size),
                (cx + size * 0.25, cy - size * 0.25),
                (cx + size, cy),
                (cx + size * 0.25, cy + size * 0.25),
                (cx, cy + size),
                (cx - size * 0.25, cy + size * 0.25),
                (cx - size, cy),
                (cx - size * 0.25, cy - size * 0.25),
            ],
            fill=col,
        )


def _new_canvas(palette: dict) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), palette["bg"])
    return img, ImageDraw.Draw(img)


def _draw_cover_with_border(canvas: Image.Image, cover: Image.Image, x: int, y: int,
                             size: int, border_color: tuple, border: int = 12,
                             rotate: float = 0.0):
    """Paste a cover with a colored border, optionally rotated.

    Uses RGBA rotation so the expanded corners are transparent rather than black
    (important on light-bg palettes).
    """
    bg = Image.new("RGB", (size + border * 2, size + border * 2), border_color)
    bg.paste(cover, (border, border))
    if rotate:
        rgba = bg.convert("RGBA")
        rotated = rgba.rotate(rotate, expand=True, resample=Image.BICUBIC)
        canvas.paste(rotated, (x, y), rotated)
    else:
        canvas.paste(bg, (x, y))


# ── Slide builders ────────────────────────────────────────────
def _build_cover_slide(palette: dict, context_interp: str, tracks: list[dict],
                        rng: random.Random,
                        local_now: datetime | None = None) -> Image.Image:
    num_tracks = len(tracks)
    now = local_now or datetime.now()
    img, draw = _new_canvas(palette)
    _sparkles(draw, palette, rng, count=22,
              region=(60, 60, CANVAS_W - 60, CANVAS_H - 260),
              avoid=(50, 220, 760, 900))

    # ── Title block ──
    title_font = _load_font(132, bold=True)
    sub_title_font = _load_font(76, bold=True)
    label_font = _load_font(34, bold=True)
    body_font = _load_font(34, bold=False)

    draw.text((70, 240), "SPOTIFY", font=title_font, fill=palette["accent1"])
    draw.text((70, 400), "PERSONAL", font=sub_title_font, fill=palette["text"])
    draw.text((70, 490), "DISCOVERY", font=sub_title_font, fill=palette["accent2"])

    # Underline accent bar
    draw.rectangle([(70, 620), (380, 640)], fill=palette["accent3"])

    # ── Context interpretation (compact, max 3 lines) ──
    if context_interp:
        draw.text((70, 700), "GEMINI 怎麼讀你", font=label_font, fill=palette["accent4"])
        _draw_wrapped(
            draw,
            context_interp,
            body_font,
            70,
            760,
            max_width=CANVAS_W - 140,
            fill=palette["text"],
            line_gap=10,
            max_lines=3,
        )

    # ── TOP 3 cover thumbnails ──
    if num_tracks >= 1:
        top_n = min(3, num_tracks)
        cover_size = 240
        gap = 36
        total_w = top_n * cover_size + (top_n - 1) * gap
        start_x = (CANVAS_W - total_w) // 2
        covers_y = 1050

        draw.text((70, covers_y - 70), "TOP PICKS", font=label_font, fill=palette["accent4"])

        rank_font = _load_font(56, bold=True)
        name_font = _load_font(24, bold=True)
        artist_font = _load_font(22, bold=False)

        for i in range(top_n):
            t = tracks[i]
            x = start_x + i * (cover_size + gap)
            cover = _fetch_cover(t.get("cover", ""), cover_size)
            if cover is None:
                cover = Image.new("RGB", (cover_size, cover_size), palette["muted"])
            _draw_cover_with_border(
                img, cover, x - 6, covers_y - 6, cover_size,
                palette["accent2"], border=8, rotate=rng.uniform(-3, 3),
            )
            d = ImageDraw.Draw(img)
            # rank number below cover
            rank_str = f"#{i + 1}"
            rw, _ = _measure(d, rank_str, rank_font)
            d.text((x + (cover_size - rw) // 2, covers_y + cover_size + 12),
                   rank_str, font=rank_font, fill=palette["accent1"])
            # track name + artist (truncate to cover_size)
            name = t.get("name", "")
            while name and _measure(d, name, name_font)[0] > cover_size:
                name = name[:-1]
            if name != t.get("name", ""):
                name = name + "…"
            nw, _ = _measure(d, name, name_font)
            d.text((x + (cover_size - nw) // 2, covers_y + cover_size + 88),
                   name, font=name_font, fill=palette["text"])
            artist = t.get("artist", "")
            while artist and _measure(d, artist, artist_font)[0] > cover_size:
                artist = artist[:-1]
            if artist != t.get("artist", ""):
                artist = artist + "…"
            aw, _ = _measure(d, artist, artist_font)
            d.text((x + (cover_size - aw) // 2, covers_y + cover_size + 124),
                   artist, font=artist_font, fill=palette["muted"])
        draw = ImageDraw.Draw(img)

    # ── Stats row at bottom ──
    stat_label_font = _load_font(24, bold=False)
    stat_value_font = _load_font(72, bold=True)
    stats_y = CANVAS_H - 180

    stats = [
        (str(num_tracks), "TRACKS"),
        (now.strftime("%m.%d"), "DATE"),
        (now.strftime("%H:%M"), "TIME"),
    ]
    section_w = CANVAS_W // len(stats)
    for i, (value, lbl) in enumerate(stats):
        cx = section_w * i + section_w // 2
        v_w, _ = _measure(draw, value, stat_value_font)
        l_w, _ = _measure(draw, lbl, stat_label_font)
        draw.text((cx - v_w // 2, stats_y), value, font=stat_value_font,
                  fill=palette["accent1"])
        draw.text((cx - l_w // 2, stats_y + 92), lbl, font=stat_label_font,
                  fill=palette["muted"])

    return img


def _build_grid_slide(palette: dict, tracks: list[dict], rng: random.Random) -> Image.Image:
    img, draw = _new_canvas(palette)
    _sparkles(draw, palette, rng, count=14, region=(40, 40, CANVAS_W - 40, 290),
              avoid=(50, 90, 620, 290))

    title_font = _load_font(96, bold=True)
    draw.text((70, 110), "TOP PICKS", font=title_font, fill=palette["accent1"])
    sub_font = _load_font(36, bold=False)
    draw.text((70, 230), f"AI 為你挑的 {len(tracks)} 首", font=sub_font, fill=palette["muted"])

    # Dynamic grid sizing — show ALL tracks, scale covers to fit
    n = len(tracks)
    if n <= 9:
        cols, rows = 3, 3
    elif n <= 12:
        cols, rows = 3, 4
    elif n <= 16:
        cols, rows = 4, 4
    elif n <= 20:
        cols, rows = 4, 5
    elif n <= 25:
        cols, rows = 5, 5
    else:
        cols, rows = 5, 6

    # actual cells used
    needed_rows = (n + cols - 1) // cols
    rows = min(rows, needed_rows)

    margin_x = 60
    grid_top = 330
    grid_bottom = CANVAS_H - 60
    available_w = CANVAS_W - margin_x * 2
    available_h = grid_bottom - grid_top
    gap = 24
    cover_size = min(
        (available_w - (cols - 1) * gap) // cols,
        (available_h - (rows - 1) * gap) // rows,
    )
    # If the grid is narrower than the available vertical space, stretch the
    # vertical gap so rows breathe and fill the slide rather than clumping.
    grid_w = cols * cover_size + (cols - 1) * gap
    naive_h = rows * cover_size + (rows - 1) * gap
    if rows > 1 and naive_h < available_h:
        gap_y = gap + (available_h - naive_h) // (rows - 1)
        # Cap so rows don't get absurdly far apart on small grids
        gap_y = min(gap_y, cover_size // 2 + gap)
    else:
        gap_y = gap
    grid_h = rows * cover_size + (rows - 1) * gap_y
    start_x = (CANVAS_W - grid_w) // 2
    start_y = grid_top + (available_h - grid_h) // 2

    border_colors = [palette["accent1"], palette["accent2"], palette["accent3"], palette["accent4"]]
    border_px = max(5, cover_size // 30)

    for idx, t in enumerate(tracks):
        row = idx // cols
        col = idx % cols
        x = start_x + col * (cover_size + gap)
        y = start_y + row * (cover_size + gap_y)
        cover = _fetch_cover(t.get("cover", ""), cover_size)
        if cover is None:
            cover = Image.new("RGB", (cover_size, cover_size), palette["muted"])
        border_col = border_colors[idx % len(border_colors)]
        rotation = rng.uniform(-3.5, 3.5)
        _draw_cover_with_border(img, cover, x - border_px // 2, y - border_px // 2,
                                cover_size, border_col, border=border_px, rotate=rotation)

    return img


def _build_tracklist_slide(palette: dict, tracks: list[dict], rng: random.Random) -> Image.Image:
    img, draw = _new_canvas(palette)
    _sparkles(draw, palette, rng, count=10, region=(40, 40, CANVAS_W - 40, 290),
              avoid=(50, 90, 720, 290))

    title_font = _load_font(96, bold=True)
    sub_font = _load_font(36, bold=False)
    draw.text((70, 110), "TRACKLIST", font=title_font, fill=palette["accent1"])
    draw.text((70, 230), f"AI 為你挑的 {len(tracks)} 首", font=sub_font, fill=palette["muted"])

    # Dynamic row sizing — fit ALL tracks within the available vertical space
    list_top = 330
    list_bottom = CANVAS_H - 60
    available = list_bottom - list_top
    n = max(1, len(tracks))
    row_h = max(48, available // n)
    # Cap row height so a small tracklist doesn't get absurdly large rows
    row_h = min(row_h, 100)

    track_font_size = max(20, int(row_h * 0.40))
    artist_font_size = max(16, int(row_h * 0.32))
    num_font_size = max(22, int(row_h * 0.46))
    track_font = _load_font(track_font_size, bold=True)
    artist_font = _load_font(artist_font_size, bold=False)
    num_font = _load_font(num_font_size, bold=True)

    # Vertical accent bar
    draw.rectangle([(70, list_top), (78, list_top + n * row_h)], fill=palette["accent2"])

    accent_cycle = [palette["accent2"], palette["accent3"], palette["accent4"], palette["accent1"]]
    title_max = CANVAS_W - 240
    y = list_top + 6

    for i, t in enumerate(tracks, 1):
        num_color = accent_cycle[(i - 1) % len(accent_cycle)]
        num_str = f"{i:02d}"
        draw.text((110, y), num_str, font=num_font, fill=num_color)

        name = t.get("name", "")
        artist = t.get("artist", "")

        name_line = name
        while name_line and _measure(draw, name_line + "…", track_font)[0] > title_max:
            name_line = name_line[:-1]
        if name_line != name:
            name_line = name_line + "…"
        draw.text((200, y - 2), name_line, font=track_font, fill=palette["text"])

        artist_line = artist
        while artist_line and _measure(draw, artist_line + "…", artist_font)[0] > title_max:
            artist_line = artist_line[:-1]
        if artist_line != artist:
            artist_line = artist_line + "…"
        # Position artist directly under track name, scaled to row_h
        artist_y_offset = max(track_font_size + 4, int(row_h * 0.5))
        draw.text((200, y + artist_y_offset), artist_line, font=artist_font, fill=palette["muted"])

        y += row_h

    return img


def _build_quote_slide(palette: dict, context_interp: str, rng: random.Random) -> Image.Image:
    img, draw = _new_canvas(palette)
    _sparkles(draw, palette, rng, count=18, region=(40, 40, CANVAS_W - 40, CANVAS_H - 200),
              avoid=(80, 520, CANVAS_W - 80, 1100))

    label_font = _load_font(46, bold=True)
    quote_mark_font = _load_font(360, bold=True)
    quote_font = _load_font(60, bold=True)

    # Big opening quote mark
    draw.text((60, 200), "“", font=quote_mark_font, fill=palette["accent2"])

    draw.text((100, 540), "GEMINI 怎麼讀你", font=label_font, fill=palette["accent1"])

    # Quote text
    _draw_wrapped(
        draw,
        context_interp or "你的當下，值得一首好歌。",
        quote_font,
        100,
        640,
        max_width=CANVAS_W - 200,
        fill=palette["text"],
        line_gap=18,
        max_lines=8,
    )

    # Closing quote mark, mirrored
    close = Image.new("RGB", (300, 300), palette["bg"])
    close_draw = ImageDraw.Draw(close)
    close_draw.text((-30, -90), "”", font=quote_mark_font, fill=palette["accent4"])
    img.paste(close, (CANVAS_W - 320, CANVAS_H - 460))

    draw = ImageDraw.Draw(img)
    return img


# ── Public API ────────────────────────────────────────────────
def generate_deck(tracks: list[dict], context_interp: str,
                   seed: str | None = None,
                   local_now: datetime | None = None) -> list[tuple[str, Image.Image]]:
    """Returns 4 named slides as (name, PIL.Image) tuples."""
    palette = pick_palette(seed)
    rng = random.Random(seed) if seed else random.Random()
    return [
        ("封面", _build_cover_slide(palette, context_interp, tracks, rng, local_now=local_now)),
        ("Top Picks", _build_grid_slide(palette, tracks, rng)),
        ("推薦清單", _build_tracklist_slide(palette, tracks, rng)),
        ("Gemini 解讀", _build_quote_slide(palette, context_interp, rng)),
    ], palette["name"]


def generate_single(tracks: list[dict], context_interp: str,
                     seed: str | None = None,
                     local_now: datetime | None = None) -> tuple[Image.Image, str]:
    """One combined 1080x1920 card: cover mosaic as background, tracklist on top, Gemini box."""
    palette = pick_palette(seed)
    rng = random.Random(seed) if seed else random.Random()

    # ── Base canvas ──
    img, _ = _new_canvas(palette)

    # ── Cover mosaic background (blur + low opacity blend) ──
    cover_imgs: list[Image.Image] = []
    for t in tracks[:9]:
        c = _fetch_cover(t.get("cover", ""), 360)
        if c:
            cover_imgs.append(c)

    if cover_imgs:
        cell = CANVAS_W // 3  # 360px per cell
        rows_bg = -(-CANVAS_H // cell)  # ceiling: how many rows to fill 1920px
        mosaic = Image.new("RGB", (CANVAS_W, rows_bg * cell), palette["bg"])
        for r in range(rows_bg):
            for c_idx in range(3):
                idx = (r * 3 + c_idx) % len(cover_imgs)
                tile = cover_imgs[idx].resize((cell, cell), Image.LANCZOS)
                mosaic.paste(tile, (c_idx * cell, r * cell))
        mosaic = mosaic.crop((0, 0, CANVAS_W, CANVAS_H))
        mosaic = mosaic.filter(ImageFilter.GaussianBlur(radius=14))
        bg_base = Image.new("RGB", (CANVAS_W, CANVAS_H), palette["bg"])
        img = Image.blend(bg_base, mosaic, alpha=0.28)

    draw = ImageDraw.Draw(img)
    _sparkles(draw, palette, rng, count=18, region=(40, 30, CANVAS_W - 40, 310),
              avoid=(50, 60, 660, 305))

    # ── Header (y: 80–290) ──
    title_font = _load_font(92, bold=True)
    sub_title_font = _load_font(52, bold=True)
    draw.text((70, 80), "SPOTIFY", font=title_font, fill=palette["accent1"])
    draw.text((70, 200), "Personal Discovery", font=sub_title_font, fill=palette["text"])
    draw.rectangle([(70, 280), (340, 296)], fill=palette["accent3"])

    # ── Semi-transparent panel behind tracklist for readability ──
    _panel = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(_panel).rounded_rectangle(
        [(50, 300), (CANVAS_W - 50, 1548)],
        radius=18,
        fill=(*palette["bg"], 185),
    )
    img = Image.alpha_composite(img.convert("RGBA"), _panel).convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── Tracklist (y: 315–1535) ── moved up; dynamic sizing to fit all tracks
    sect_font = _load_font(52, bold=True)
    draw.text((70, 315), "TRACKLIST", font=sect_font, fill=palette["accent1"])

    list_top = 395
    list_bottom = 1535
    available = list_bottom - list_top          # ~1140 px
    n_tracks = len(tracks)
    max_in_card = min(n_tracks, 15)
    row_h = max(60, min(100, available // max(1, max_in_card)))

    track_font_size = max(22, int(row_h * 0.40))
    artist_font_size = max(16, int(row_h * 0.30))
    num_font_size = max(24, int(row_h * 0.44))
    track_font = _load_font(track_font_size, bold=True)
    artist_font = _load_font(artist_font_size, bold=False)
    num_font = _load_font(num_font_size, bold=True)

    accent_cycle = [palette["accent2"], palette["accent3"], palette["accent4"], palette["accent1"]]
    title_max = CANVAS_W - 220
    y = list_top

    for i, t in enumerate(tracks[:max_in_card], 1):
        num_color = accent_cycle[(i - 1) % len(accent_cycle)]
        draw.text((80, y), f"{i:02d}", font=num_font, fill=num_color)

        name = t.get("name", "")
        name_lines = _wrap_text(draw, name, track_font, title_max)
        nl = name_lines[0]
        if len(name_lines) > 1:
            while nl and _measure(draw, nl + "…", track_font)[0] > title_max:
                nl = nl[:-1]
            nl += "…"
        draw.text((160, y - 2), nl, font=track_font, fill=palette["text"])

        al = t.get("artist", "")
        while al and _measure(draw, al, artist_font)[0] > title_max:
            al = al[:-1]
        if al != t.get("artist", ""):
            al += "…"
        draw.text((160, y + track_font_size + 4), al, font=artist_font, fill=palette["muted"])

        y += row_h

    if n_tracks > max_in_card:
        more_font = _load_font(28, bold=False)
        draw.text((80, y + 4), f"+ {n_tracks - max_in_card} 首更多…",
                  font=more_font, fill=palette["accent1"])

    # ── Gemini quote (y: 1555–1875, narrower box — 130px side margins) ──
    if context_interp:
        card_fill = _adaptive_shift(palette["bg"], amount=32)
        cx1, cx2 = 130, CANVAS_W - 130      # narrower: 130px margins vs original 60px
        card_y1, card_y2 = 1555, 1875
        draw.rounded_rectangle(
            [(cx1, card_y1), (cx2, card_y2)],
            radius=28, fill=card_fill, outline=palette["accent2"], width=3,
        )
        label_font = _load_font(26, bold=True)
        quote_font = _load_font(30, bold=True)
        draw.text((cx1 + 30, card_y1 + 24), "GEMINI 對此刻的解讀",
                  font=label_font, fill=palette["accent2"])
        _draw_wrapped(
            draw,
            context_interp,
            quote_font,
            cx1 + 30,
            card_y1 + 76,
            max_width=cx2 - cx1 - 60,
            fill=palette["text"],
            line_gap=10,
            max_lines=4,
        )

    return img, palette["name"]
