"""share_card.py 的單元測試——純邏輯＋渲染煙霧測試（全程不發網路請求）。"""
import io
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import share_card


def _tracks(n, cover=""):
    return [{"name": f"T{i}", "artist": "A", "cover": cover} for i in range(n)]


# ── 格數規則（畫布便利貼上的規格）───────────────────────────

@pytest.mark.parametrize("n,cols", [
    (5, 3), (9, 3), (10, 4), (15, 4), (16, 4), (17, 5), (25, 5), (26, 6), (30, 6),
])
def test_grid_columns(n, cols):
    assert share_card.grid_columns(n) == cols


def test_plan_cells_remainder_brand_last():
    # 品牌磚固定最後一格（右下角）、其餘空格是彩色磚
    assert share_card.plan_cells(15, 4) == ["brand"]
    assert share_card.plan_cells(13, 4) == ["accent", "accent", "brand"]


def test_plan_cells_exact_fit_no_brand():
    # 整除＝全封面，沒有品牌磚（16 首 4 欄）
    assert share_card.plan_cells(16, 4) == []
    assert share_card.plan_cells(12, 4) == []


# ── 標題 clamp 兩行（三行會撞進 IG 下方遮擋帶）─────────────────

def test_fit_title_clamps_to_two_lines():
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    _font, lines = share_card._fit_title(d, "很長的標題" * 30, 1000)
    assert len(lines) == 2
    assert lines[-1].endswith("…")


def test_fit_title_short_stays_full_size():
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    font, lines = share_card._fit_title(d, "深夜散步", 1000)
    assert lines == ["深夜散步"]
    assert font.size == 60  # 沒縮字級


# ── 渲染煙霧：三種樣式都要出得來（不給封面→佔位磚，零網路）──────

@pytest.mark.parametrize("style", share_card.STYLE_ORDER)
def test_render_all_styles(style):
    png = share_card.render_story_png(
        _tracks(15), {}, style=style, playlist_title="測試 // Test",
        discovery_count=8, when=datetime(2026, 8, 30))
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert Image.open(io.BytesIO(png)).size == (1080, 1920)


def test_render_without_badge_and_date():
    # 訪客（無 _discovery）＋不給時間：不畫徽章與日期，也不能炸
    png = share_card.render_story_png(_tracks(5), None, style="sticker",
                                      discovery_count=0, when=None)
    assert Image.open(io.BytesIO(png)).size == (1080, 1920)


def test_unknown_style_falls_back_to_sticker():
    png = share_card.render_story_png(_tracks(5), {}, style="nope", when=None)
    assert Image.open(io.BytesIO(png)).size == (1080, 1920)


def test_fullbleed_corner_is_deep_purple():
    png = share_card.render_story_png(_tracks(15), {}, style="fullbleed", when=None)
    assert Image.open(io.BytesIO(png)).getpixel((0, 0)) == share_card.DEEP


def test_corrupt_cover_falls_back_to_placeholder():
    # 快取裡是壞掉的 bytes 也只是變佔位磚，不中斷整張圖
    png = share_card.render_story_png(_tracks(5, cover="u"), {"u": b"not an image"},
                                      style="sticker", when=None)
    assert Image.open(io.BytesIO(png)).size == (1080, 1920)


# ── 模組紀律與快取 ───────────────────────────────────────

def test_module_never_imports_streamlit():
    # 同 recommend.py 的紀律：純邏輯模組，pytest 直接 import 不能拖進 streamlit。
    # 用 AST 查真正的 import 語句——docstring 裡提到「import streamlit」不算數
    import ast
    tree = ast.parse(Path(share_card.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[0] == "streamlit" for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "streamlit"


# ⚠️ 這兩條的網址必須是真的 Spotify CDN 形式：fetch_covers 會先過 _is_spotify_cdn
# 白名單，隨手寫的 http://x/a 會在發請求之前就被濾掉，測試看起來像「沒打請求」。
def test_fetch_covers_caches_and_skips_empty(monkeypatch):
    calls = []

    class _Resp:
        content = b"img-bytes"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(share_card.requests, "get",
                        lambda url, timeout, allow_redirects=True: calls.append(url) or _Resp())
    share_card._COVER_CACHE.clear()
    try:
        out = share_card.fetch_covers(["", "https://i.scdn.co/image/a", "https://i.scdn.co/image/a"])
        assert out == {"https://i.scdn.co/image/a": b"img-bytes"}
        assert calls == ["https://i.scdn.co/image/a"]          # 空網址不打、同網址只打一次
        out2 = share_card.fetch_covers(["https://i.scdn.co/image/a"])
        assert out2 == {"https://i.scdn.co/image/a": b"img-bytes"}
        assert len(calls) == 1                  # 第二輪走快取
    finally:
        share_card._COVER_CACHE.clear()


def test_fetch_covers_failure_not_cached(monkeypatch):
    calls = []

    def _boom(url, timeout, allow_redirects=True):
        calls.append(url)
        raise OSError("network down")

    monkeypatch.setattr(share_card.requests, "get", _boom)
    share_card._COVER_CACHE.clear()
    try:
        assert share_card.fetch_covers(["https://i.scdn.co/image/b"]) == {"https://i.scdn.co/image/b": None}
        share_card.fetch_covers(["https://i.scdn.co/image/b"])
        assert len(calls) == 2                  # 失敗不進快取，下次會重試
    finally:
        share_card._COVER_CACHE.clear()


# ── 封面只抓 Spotify CDN（LOW-8）─────────────────────────
@pytest.mark.parametrize("url, allowed", [
    ("https://i.scdn.co/image/ab67616d0000b273abc", True),
    ("https://mosaic.scdn.co/640/abc", True),
    ("https://scdn.co/image/abc", True),
    ("http://i.scdn.co/image/abc", False),          # 非 https
    ("https://evil-scdn.co/image/abc", False),      # ⚠️ 網域字尾偽裝：endswith("scdn.co") 會放行
    ("https://scdn.co.evil.com/x", False),
    ("https://169.254.169.254/latest/meta-data/", False),   # 雲端 metadata 端點
    ("https://localhost:8501/admin", False),
    ("", False),
    ("not a url", False),
])
def test_only_spotify_cdn_urls_are_fetched(url, allowed):
    assert share_card._is_spotify_cdn(url) is allowed, url
