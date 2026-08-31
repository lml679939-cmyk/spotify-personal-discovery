"""IG 限時動態分享圖卡（1080×1920）——2026-08-30 重做版。

三種樣式（設計稿：Claude Design 畫布 artifact d387af5f-9562-4176-8258-6f1733ef3d46）：
- sticker   糖果貼紙牆：奶油粉漸層底＋深紫貼紙框（最貼品牌）
- midnight  午夜霓虹：深紫夜色底＋青色發光框
- fullbleed 全出血拼貼：封面邊到邊、深紫頁首頁尾（stats.fm 風）

設計上的硬規則（跟畫布上的便利貼一致）：
- 內容從 y=200 開始、收在 y≈1665 之前——上 ~200px／下 ~250px 是 IG 介面遮擋區。
- 歌單標題 clamp 兩行內（超過先縮字級、再截斷加 …），三行會撞進下方遮擋帶。
- 格數規則：5–9 首 3 欄、10–16 首 4 欄、17–25 首 5 欄、26–30 首 6 欄；
  不整除時最後一格放「品牌磚」（黑膠＋SoundCurator）、其餘空格放彩色星芒磚。
- 出圈徽章固定青底紫字（語意色、不輪替）；指南針用向量畫（Pillow 沒有 emoji 字型，
  🧭 會變豆腐字）。

⚠️ 本模組不 import streamlit（同 recommend.py 的紀律）——pytest 可直接 import。
⚠️ 不用 datetime.now()：時間由呼叫端傳入（app.py 傳 _local_now()，雲端是 UTC 的老坑）。
舊版 share_card.py（隨機色盤、四張一組）在 git 歷史 72bf444 移除前，勿與本版混淆。
"""
from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

_FONTS_DIR = Path(__file__).parent / "fonts"

CANVAS_W, CANVAS_H = 1080, 1920
TOP_SAFE = 200          # IG 頭像列／進度條的遮擋帶下緣
FOOTER_BOTTOM = 1665    # 內容底線（再往下是 IG 回覆框）
SIDE = 40

# 品牌色（styles.py 的 :root 變數）
DEEP = (45, 27, 78)          # --y2k-deep-purple #2D1B4E
CREAM = (255, 253, 247)      # --y2k-cream #FFFDF7
PINK = (255, 105, 180)       # --y2k-pink #FF69B4
CYAN = (0, 212, 170)         # --y2k-cyan #00D4AA
GOLD = (255, 215, 0)         # --y2k-yellow #FFD700
PURPLE = (155, 89, 182)      # --y2k-purple #9B59B6
NIGHT = (28, 16, 48)         # #1C1030（黑膠碟面／午夜漸層頂）
NIGHT_BLUE = (16, 27, 46)    # #101B2E（午夜漸層底）

_ACCENTS = [CYAN, PINK, GOLD, PURPLE]

STYLE_ORDER = ["sticker", "midnight", "fullbleed"]
STYLES = {
    "sticker": {"label": "糖果貼紙牆", "caption": "奶油漸層底・最貼品牌"},
    "midnight": {"label": "午夜霓虹", "caption": "深紫夜色・晚上發限動更融入"},
    "fullbleed": {"label": "全出血拼貼", "caption": "封面最大張・stats.fm 風"},
}


# ── 純邏輯（測試主力）──────────────────────────────────────

def grid_columns(n: int) -> int:
    """封面牆欄數。依「總首數」決定（不是抓到封面的張數），同一份歌單欄數穩定。"""
    if n <= 9:
        return 3
    if n <= 16:
        return 4
    if n <= 25:
        return 5
    return 6


def plan_cells(n_cells: int, cols: int) -> list[str]:
    """不整除時要補的磚（接在封面後面）：品牌磚固定最後一格（右下角），
    其餘空格放彩色星芒磚。整除時回空清單（16 首 4 欄＝全封面、沒有品牌磚）。"""
    rem = (-n_cells) % cols
    if rem == 0:
        return []
    return ["accent"] * (rem - 1) + ["brand"]


def _blend(fg: tuple, bg: tuple, alpha: float) -> tuple:
    return tuple(round(f * alpha + b * (1 - alpha)) for f, b in zip(fg, bg))


def _lerp(c1: tuple, c2: tuple, t: float) -> tuple:
    return tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))


def _multi_lerp(stops: list[tuple], t: float) -> tuple:
    if t <= 0:
        return stops[0]
    if t >= 1:
        return stops[-1]
    seg = t * (len(stops) - 1)
    i = int(seg)
    return _lerp(stops[i], stops[i + 1], seg - i)


# ── 字型 ─────────────────────────────────────────────────

@lru_cache(maxsize=32)
def _load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """fonts/ 的 NotoSansTC（CJK＋拉丁都覆蓋）＞ Windows 系統字型 ＞ PIL 預設。"""
    names = (["NotoSansTC-Bold.ttf"] if bold else ["NotoSansTC-Regular.ttf"])
    candidates = [_FONTS_DIR / n for n in names]
    candidates += (["C:/Windows/Fonts/msjhbd.ttc", "C:/Windows/Fonts/arialbd.ttf"] if bold
                   else ["C:/Windows/Fonts/msjh.ttc", "C:/Windows/Fonts/arial.ttf"])
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return ImageFont.load_default()


def _measure(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _wrap_text(draw, text: str, font, max_width: int) -> list[str]:
    """逐字換行（CJK＋英文混排都對）。"""
    lines: list[str] = []
    current = ""
    for ch in text:
        test = current + ch
        if _measure(draw, test, font)[0] > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def _fit_title(draw, text: str, max_width: int,
               sizes: tuple = (60, 52, 46)) -> tuple:
    """標題 clamp 兩行：先縮字級、最小字級仍超過就截斷加 …。回 (font, lines)。"""
    for size in sizes:
        font = _load_font(size, bold=True)
        lines = _wrap_text(draw, text, font, max_width)
        if len(lines) <= 2:
            return font, lines
    font = _load_font(sizes[-1], bold=True)
    lines = _wrap_text(draw, text, font, max_width)[:2]
    last = lines[-1]
    while last and _measure(draw, last + "…", font)[0] > max_width:
        last = last[:-1]
    lines[-1] = last + "…"
    return font, lines


# ── 封面抓取 ──────────────────────────────────────────────

_COVER_CACHE: dict[str, bytes] = {}   # url → 原始 bytes。跨使用者共用（公開 CDN 圖）
_COVER_CACHE_MAX = 400


_CDN_SUFFIX = ".scdn.co"     # Spotify 圖片 CDN：i.scdn.co、mosaic.scdn.co…


def _is_spotify_cdn(url: str) -> bool:
    """只放行 Spotify 圖片 CDN 的 https 網址；其餘一律不抓（畫佔位磚）。

    封面網址目前只可能來自 Spotify 的 API 回應，所以這是縱深防禦——但成本近乎零：
    這個函式是唯一會對「資料裡帶來的網址」發請求的地方，鎖住它就沒有 SSRF 的餘地。

    ⚠️ 不能寫成 `endswith("scdn.co")`——`evil-scdn.co` 會過關。要比對**帶點的字尾**
    `.scdn.co`（或整串等於 `scdn.co`），網域字尾偽裝才擋得住。
    """
    if not url:
        return False
    try:
        u = urlparse(url)
    except Exception:
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host == "scdn.co" or host.endswith(_CDN_SUFFIX))


def fetch_covers(urls: list[str], timeout: float = 6.0) -> dict[str, bytes | None]:
    """平行抓封面 → {url: bytes|None}。失敗回 None（畫佔位磚）、不進快取（下次再試）。
    走 Spotify 的圖片 CDN（i.scdn.co），不吃 API 配額。"""
    todo = sorted({u for u in urls if _is_spotify_cdn(u) and u not in _COVER_CACHE})
    if todo:
        def _one(url):
            try:
                # ⚠️ allow_redirects=False：白名單只驗第一個網址，跟著轉址走等於白驗
                r = requests.get(url, timeout=timeout, allow_redirects=False)
                r.raise_for_status()
                return url, r.content
            except Exception:
                return url, None
        with ThreadPoolExecutor(max_workers=8) as pool:
            for url, data in pool.map(_one, todo):
                if data:
                    if len(_COVER_CACHE) >= _COVER_CACHE_MAX:
                        _COVER_CACHE.pop(next(iter(_COVER_CACHE)))
                    _COVER_CACHE[url] = data
    return {u: _COVER_CACHE.get(u) for u in urls if u}


# ── 圖元 ─────────────────────────────────────────────────

def _vgrad(w: int, h: int, stops: list[tuple]) -> Image.Image:
    strip = Image.new("RGB", (1, h))
    px = strip.load()
    for y in range(h):
        px[0, y] = _multi_lerp(stops, y / max(1, h - 1))
    return strip.resize((w, h))


def _hgrad(w: int, h: int, stops: list[tuple]) -> Image.Image:
    strip = Image.new("RGB", (w, 1))
    px = strip.load()
    for x in range(w):
        px[x, 0] = _multi_lerp(stops, x / max(1, w - 1))
    return strip.resize((w, h))


def _draw_gradient_text(canvas: Image.Image, xy: tuple, text: str, font,
                        stops: list[tuple]):
    """漸層字：文字當遮罩、把水平漸層貼進去（Pillow 沒有原生漸層字）。"""
    d = ImageDraw.Draw(canvas)
    bbox = d.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if w <= 0 or h <= 0:
        return
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((-bbox[0], -bbox[1]), text, font=font, fill=255)
    canvas.paste(_hgrad(w, h, stops), (xy[0] + bbox[0], xy[1] + bbox[1]), mask)


def _draw_vinyl(canvas: Image.Image, cx: float, cy: float, r: float, *,
                disc: tuple = DEEP, outer: tuple | None = None):
    """黑膠（照 styles.login_hero_html 的 SVG 比例）：碟面＋三圈溝紋＋粉/金/奶油標。
    溝紋的半透明用預先混色模擬（RGB 畫布上 ImageDraw 不做 alpha 混合）。"""
    d = ImageDraw.Draw(canvas)

    def ell(rr, **kw):
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], **kw)

    ell(r, fill=disc)
    lw = max(1, round(r * 0.05))
    ell(r * 0.83, outline=_blend(PURPLE, disc, 0.55), width=lw)
    ell(r * 0.65, outline=_blend(PINK, disc, 0.5), width=lw)
    ell(r * 0.46, outline=_blend(PURPLE, disc, 0.55), width=lw)
    ell(r * 0.31, fill=PINK)
    ell(r * 0.21, fill=GOLD)
    ell(max(2.0, r * 0.083), fill=CREAM)
    if outer:
        ell(r, outline=outer, width=max(2, lw))


def _draw_sparkle(d: ImageDraw.ImageDraw, cx: float, cy: float, s: float,
                  fill: tuple, outline: tuple | None = None):
    pts = [(cx, cy - s), (cx + s * 0.25, cy - s * 0.25), (cx + s, cy),
           (cx + s * 0.25, cy + s * 0.25), (cx, cy + s),
           (cx - s * 0.25, cy + s * 0.25), (cx - s, cy),
           (cx - s * 0.25, cy - s * 0.25)]
    d.polygon(pts, fill=fill, outline=outline, width=2)


def _draw_compass(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: tuple):
    """出圈徽章的指南針——向量畫，不用 🧭（NotoSansTC 沒有 emoji，會變豆腐）。"""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=3)
    n = r * 0.58
    d.polygon([(cx, cy - n), (cx + r * 0.26, cy), (cx, cy + n), (cx - r * 0.26, cy)],
              fill=color)


def _draw_wordmark(canvas: Image.Image, x: int, y: int, size: int, *,
                   main: tuple, curator: tuple, disc: tuple = DEEP,
                   outer: tuple | None = None) -> int:
    """S◉undCurator（黑膠當 o，同登入 hero）。y 是文字頂端，回傳結尾 x。"""
    d = ImageDraw.Draw(canvas)
    font = _load_font(size, bold=True)
    xc = float(x)
    d.text((xc, y), "S", font=font, fill=main)
    # 黑膠中心對齊大寫字母的**墨水中心**——用 textbbox 向實際字型量，不用固定係數。
    # NotoSansTC 的 ascent 很高（68/58），舊的 0.62×size 實測偏高 10px（@58px），
    # 正式站一眼就看得出 o 浮起來。量法：textbbox("S") 的 (y0+y1)/2 = 46.0 vs 36.0。
    cap_bb = d.textbbox((xc, y), "S", font=font)
    cap_cy = (cap_bb[1] + cap_bb[3]) / 2
    xc += d.textlength("S", font=font) + size * 0.04
    vr = size * 0.4
    _draw_vinyl(canvas, xc + vr, cap_cy, vr, disc=disc, outer=outer)
    xc += vr * 2 + size * 0.04
    d.text((xc, y), "und", font=font, fill=main)
    xc += d.textlength("und", font=font)
    d.text((xc, y), "Curator", font=font, fill=curator)
    return round(xc + d.textlength("Curator", font=font))


# ── 磚 ───────────────────────────────────────────────────

def _placeholder_tile(tile: int) -> Image.Image:
    """封面抓不到（或 _no_spotify）的佔位磚：深紫底＋黑膠。"""
    img = Image.new("RGB", (tile, tile), DEEP)
    _draw_vinyl(img, tile / 2, tile / 2, tile * 0.28, disc=NIGHT)
    return img


def _brand_tile(tile: int) -> Image.Image:
    img = Image.new("RGB", (tile, tile), NIGHT)
    _draw_vinyl(img, tile / 2, tile * 0.42, tile * 0.26, disc=DEEP)
    font = _load_font(max(16, round(tile * 0.095)), bold=True)
    d = ImageDraw.Draw(img)
    w = d.textlength("SoundCurator", font=font)
    d.text(((tile - w) / 2, tile * 0.7), "SoundCurator", font=font, fill=CREAM)
    return img


def _accent_tile(tile: int, color: tuple) -> Image.Image:
    img = Image.new("RGB", (tile, tile), color)
    _draw_sparkle(ImageDraw.Draw(img), tile / 2, tile / 2, tile * 0.18,
                  CREAM, outline=DEEP)
    return img


def _render_grid(cover_bytes: list[bytes | None], tile: int, cols: int) -> Image.Image:
    cells: list[Image.Image] = []
    for data in cover_bytes:
        if data:
            try:
                im = Image.open(io.BytesIO(data)).convert("RGB")
                cells.append(im.resize((tile, tile), Image.Resampling.LANCZOS))
                continue
            except Exception:
                pass
        cells.append(_placeholder_tile(tile))
    ai = 0
    for kind in plan_cells(len(cells), cols):
        if kind == "brand":
            cells.append(_brand_tile(tile))
        else:
            cells.append(_accent_tile(tile, _ACCENTS[ai % len(_ACCENTS)]))
            ai += 1
    rows = len(cells) // cols
    grid = Image.new("RGB", (tile * cols, tile * rows))
    for i, cell in enumerate(cells):
        grid.paste(cell, ((i % cols) * tile, (i // cols) * tile))
    return grid


def _rounded_paste(canvas: Image.Image, img: Image.Image, xy: tuple, radius: int):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.width - 1, img.height - 1],
                                           radius=radius, fill=255)
    canvas.paste(img, xy, mask)


# ── 主組版 ───────────────────────────────────────────────

def build_story_card(tracks: list[dict], covers: dict[str, bytes | None] | None = None,
                     *, style: str = "sticker", playlist_title: str = "",
                     discovery_count: int = 0, when=None) -> Image.Image:
    """組一張 1080×1920 圖卡。covers 用 fetch_covers() 先抓好傳入（測試可傳 {}）。
    when 是 datetime（app 傳 _local_now()）；None 就不印日期。"""
    if style not in STYLES:
        style = "sticker"
    covers = covers or {}
    n = len(tracks)
    cols = grid_columns(n)
    cover_bytes = [covers.get(t.get("cover") or "") for t in tracks]

    dark = style in ("midnight", "fullbleed")
    fg = CREAM if dark else DEEP
    curator = PINK if dark else PURPLE
    if style == "sticker":
        canvas = _vgrad(CANVAS_W, CANVAS_H,
                        [(255, 228, 240), (255, 240, 245), (232, 248, 245)]).convert("RGBA")
        bg_ref = (255, 240, 245)
        title_stops = [PINK, PURPLE, CYAN]
    elif style == "midnight":
        canvas = _vgrad(CANVAS_W, CANVAS_H, [NIGHT, DEEP, NIGHT_BLUE]).convert("RGBA")
        bg_ref = DEEP
        title_stops = [CYAN, PINK, GOLD]
    else:  # fullbleed
        canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), DEEP + (255,))
        bg_ref = DEEP
        title_stops = [CYAN, GOLD, PINK]
    muted = _blend(fg, bg_ref, 0.55)
    d = ImageDraw.Draw(canvas)
    side = 48 if style == "fullbleed" else SIDE

    # 裝飾星芒（framed 兩款；fullbleed 走素面）。頂上那顆刻意在遮擋帶內＝背景裝飾
    if style != "fullbleed":
        sp_outline = CREAM if dark else DEEP
        _draw_sparkle(d, 1006, 142, 22, GOLD, outline=sp_outline)
        _draw_sparkle(d, 992, 434, 15, PINK, outline=sp_outline)
        _draw_sparkle(d, 89, 1662, 17, CYAN, outline=sp_outline)

    # ── 頁首：wordmark ＋ 右側 meta ──
    wm_size = 54 if style == "fullbleed" else 58
    _draw_wordmark(canvas, side, TOP_SAFE, wm_size, main=fg, curator=curator,
                   disc=NIGHT if dark else DEEP,
                   outer=_blend(CREAM, bg_ref, 0.9) if dark else None)
    d.text((CANVAS_W - side, TOP_SAFE - 2), f"{n} 首推薦",
           font=_load_font(32, True), fill=fg, anchor="ra")
    if when is not None:
        d.text((CANVAS_W - side, TOP_SAFE + 40), when.strftime("%Y.%m.%d"),
               font=_load_font(23, False), fill=muted, anchor="ra")

    # ── 標題（漸層字、clamp 兩行）──
    title = (playlist_title or "").strip() or "我的專屬歌單"
    title_max_w = CANVAS_W - side * 2
    sizes = (54, 48, 42) if style == "fullbleed" else (60, 52, 46)
    t_font, t_lines = _fit_title(d, title, title_max_w, sizes)
    ty = TOP_SAFE + wm_size + (32 if style == "fullbleed" else 40)
    line_h = round(t_font.size * 1.2)
    for line in t_lines:
        _draw_gradient_text(canvas, (side, ty), line, t_font, title_stops)
        ty += line_h
    cursor = ty

    # ── 出圈徽章（登入模式才有 _discovery；0 就不畫）──
    if discovery_count > 0:
        cursor += 22
        b_font = _load_font(27, True)
        b_text = f"出圈 ×{discovery_count}"
        tw = d.textlength(b_text, font=b_font)
        ph, pr = 52, 14
        pw = round(20 + 30 + 10 + tw + 20)
        border = _blend(CREAM, bg_ref, 0.9) if dark else DEEP
        d.rounded_rectangle([side, cursor, side + pw, cursor + ph], radius=pr,
                            fill=CYAN, outline=border, width=3)
        pcy = cursor + ph / 2
        _draw_compass(d, side + 20 + 13, pcy, 13, DEEP)
        d.text((side + 20 + 30 + 8, pcy), b_text, font=b_font, fill=DEEP, anchor="lm")
        cursor += ph

    # ── 封面牆 ──
    if style == "fullbleed":
        tile = CANVAS_W // cols
        grid = _render_grid(cover_bytes, tile, cols)
        # 置中在徽章底與頁尾帶之間；下方至少留 100px 給網址列
        zone_bottom = FOOTER_BOTTOM - 100
        gy = cursor + max(46, (zone_bottom - cursor - grid.height) // 2)
        canvas.paste(grid, ((CANVAS_W - grid.width) // 2, gy))
        # 頁尾：黑膠＋網址，靠左（stats.fm 式落款）
        fy = gy + grid.height + 52
        _draw_vinyl(canvas, side + 22, fy + 22, 22, disc=NIGHT, outer=CYAN)
        u_font = _load_font(38, True)
        ux = side + 44 + 16
        d.text((ux, fy + 22), "soundcurator", font=u_font, fill=CREAM, anchor="lm")
        ux += d.textlength("soundcurator", font=u_font)
        d.text((ux, fy + 22), ".streamlit.app", font=u_font, fill=CYAN, anchor="lm")
        return canvas.convert("RGB")

    # framed 兩款：sticker（硬影＋深紫框）／midnight（青色光暈框）
    frame_border = 4
    tile = (1000 - frame_border * 2) // cols
    grid = _render_grid(cover_bytes, tile, cols)
    fw, fh = grid.width + frame_border * 2, grid.height + frame_border * 2
    gx = (CANVAS_W - fw) // 2
    # 頁尾（置中 tagline＋網址）先算高度，封面牆置中在徽章底與頁尾之間
    footer_top = FOOTER_BOTTOM - 84
    gy = cursor + max(44, (footer_top - 40 - cursor - fh) // 2)

    if style == "sticker":
        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            [gx + 10, gy + 10, gx + fw + 10, gy + fh + 10], radius=24,
            fill=DEEP + (38,))
        canvas = Image.alpha_composite(canvas, shadow)
    else:
        glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).rounded_rectangle(
            [gx - 2, gy - 2, gx + fw + 2, gy + fh + 2], radius=26,
            outline=CYAN + (110,), width=10)
        canvas = Image.alpha_composite(canvas, glow.filter(ImageFilter.GaussianBlur(12)))
    d = ImageDraw.Draw(canvas)   # alpha_composite 產生新物件，draw 要重建

    _rounded_paste(canvas, grid, (gx + frame_border, gy + frame_border), 20)
    d.rounded_rectangle([gx, gy, gx + fw - 1, gy + fh - 1], radius=24,
                        outline=CYAN if dark else DEEP, width=frame_border)

    # ── 頁尾 ──
    tag_font = _load_font(25, False)
    tag = "不 推 弟 ， 只 推 歌 。"   # letter-spacing 用全形空格近似
    tw = d.textlength(tag, font=tag_font)
    d.text(((CANVAS_W - tw) / 2, footer_top), tag, font=tag_font, fill=muted)
    u_font = _load_font(36, True)
    url = "soundcurator.streamlit.app"
    uw = d.textlength(url, font=u_font)
    row_w = 34 + 12 + uw
    ux = (CANVAS_W - row_w) / 2
    ucy = footer_top + 25 + 14 + 21
    _draw_vinyl(canvas, ux + 17, ucy, 17, disc=NIGHT if dark else DEEP,
                outer=CYAN if dark else None)
    d.text((ux + 34 + 12, ucy), url, font=u_font,
           fill=CYAN if dark else DEEP, anchor="lm")
    return canvas.convert("RGB")


def render_story_png(tracks: list[dict], covers: dict[str, bytes | None] | None = None,
                     *, style: str = "sticker", playlist_title: str = "",
                     discovery_count: int = 0, when=None) -> bytes:
    img = build_story_card(tracks, covers, style=style, playlist_title=playlist_title,
                           discovery_count=discovery_count, when=when)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
