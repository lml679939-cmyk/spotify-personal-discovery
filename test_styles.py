"""styles.py 的 HTML 產出測試（不渲染，只檢查字串）。

執行：python -m pytest test_styles.py -q
"""

import styles

DISCOVERY = {"name": "Piano Song", "artist": "Hania Rani", "album": "Esja",
             "reason": "與你聽的 dream pop 同樣的空間感", "cover": "http://x/c.jpg",
             "_discovery": True}
FAMILIAR = {**DISCOVERY, "_discovery": False}


def test_discovery_badge_only_on_discovery_tracks():
    assert "🧭" in styles.track_card_html(DISCOVERY, 0)
    assert "🧭" not in styles.track_card_html(FAMILIAR, 0)
    assert "🧭" in styles.track_list_html(DISCOVERY, 0)
    assert "🧭" not in styles.track_list_html(FAMILIAR, 0)


def test_badge_shrinks_to_icon_only_on_dense_grid():
    # 標籤寬度固定但卡片會變窄：每列 10 首時封面只有 58px、完整標籤 54px，
    # 會超出封面邊界還蓋掉 35% 專輯圖。密集網格要縮成只有圖示
    full = styles.track_card_html(DISCOVERY, 0, compact_badge=False)
    compact = styles.track_card_html(DISCOVERY, 0, compact_badge=True)
    assert "🧭 出圈" in full
    assert "🧭 出圈" not in compact and "🧭" in compact


def test_badge_keeps_a_tooltip_when_text_is_hidden():
    # 縮成圖示後，意思要靠 title 屬性補回來
    assert 'title="來自你沒接觸過的音樂人"' in styles.track_card_html(DISCOVERY, 0, compact_badge=True)


def test_card_html_has_no_indented_lines():
    # Streamlit 的 markdown 會把縮排 4 空白的行當成程式碼區塊印出原始碼
    for html in (styles.track_card_html(DISCOVERY, 0),
                 styles.track_card_html({**DISCOVERY, "album": "", "reason": ""}, 1)):
        assert not any(line.startswith((" ", "\t")) for line in html.splitlines())
        assert "" not in html.splitlines(), "空行也會觸發同樣的問題"


# ── 注入防護：BYOK 步驟卡的 Redirect URI ────────────────────
# 步驟卡已拆成上下兩半，中間由 app.py 夾一個原生的 st.code(redirect_uri)。
# 這樣做的副作用是**注入面整個消失**：使用者可填的 redirect_uri 從此完全不經過
# unsafe_allow_html，不必再煩惱 HTML 屬性 / JS 字串該用哪種跳脫。
# 這幾條測試就是釘住這件事——別哪天為了方便又把網址塞回 HTML 裡。


def test_step_card_html_takes_no_user_data_at_all():
    """兩個 helper 都不收參數：沒有輸入，就沒有注入。"""
    import inspect
    for fn in (styles.byok_spotify_steps_head_html, styles.byok_spotify_steps_tail_html):
        assert not inspect.signature(fn).parameters, f"{fn.__name__} 不該接受任何參數"


# ── Y2K 圖示系統（2026-08-21）─────────────────────────────
def test_projective_question_html_uses_bubble_and_escapes():
    out = styles.projective_question_html("你窗外現在看到什麼？")
    assert "svg" in out and "你窗外現在看到什麼？" in out
    # 題目雖然是自家常數，仍要 escape——哪天改成可自訂就不會變成注入面
    evil = styles.projective_question_html('<img src=x onerror="alert(1)">')
    assert "<img" not in evil and "&lt;img" in evil


def test_projective_question_html_no_codeblock_trigger():
    # Streamlit 會把縮排 4 空白的行當程式碼區塊、空行會斷開 HTML
    out = styles.projective_question_html("題目")
    assert not any(line.startswith(("    ", "\t")) for line in out.splitlines())
    assert "" not in out.splitlines()


def test_section_header_supports_clipboard_icon():
    out = styles.section_header_html("複製歌單", icon="clipboard")
    assert "複製歌單" in out
    assert 'viewBox="0 0 48 48"' in out   # 用的是新剪貼板，不是 fallback 的音符


def test_redirect_uri_appears_nowhere_in_the_injected_html():
    combined = styles.byok_spotify_steps_head_html() + styles.byok_spotify_steps_tail_html()
    for marker in ("127.0.0.1", "streamlit.app", "redirect_uri", "data-copy-uri"):
        assert marker not in combined


def test_no_event_handler_attributes_remain():
    """自製 onclick 一律無效（Streamlit 會濾掉），留著只會誤導後人以為有作用。"""
    combined = styles.byok_spotify_steps_head_html() + styles.byok_spotify_steps_tail_html()
    for handler in ("onclick=", "onload=", "onerror=", "onmouseover="):
        assert handler not in combined


def test_the_two_halves_carry_the_seam_classes():
    """接縫是靠 class + CSS 畫出來的，class 名改了 CSS 要一起改。"""
    head = styles.byok_spotify_steps_head_html()
    tail = styles.byok_spotify_steps_tail_html()
    assert "y2k-byok-card" in head and "y2k-byok-head" in head
    assert "y2k-byok-card" in tail and "y2k-byok-tail" in tail
    css = styles._build_global_css()
    for sel in (".y2k-byok-head", ".y2k-byok-tail", ".st-key-byok_uri", ".st-key-byok_steps"):
        assert sel in css, f"CSS 少了 {sel}"


def test_all_five_steps_are_still_present_across_the_two_halves():
    """拆卡片時最容易掉步驟——五步一步都不能少。"""
    combined = styles.byok_spotify_steps_head_html() + styles.byok_spotify_steps_tail_html()
    for n, title in ((">1<", "開啟 Spotify Developer Dashboard"),
                     (">2<", "建立新 App"),
                     (">3<", "設定 Redirect URI"),
                     (">4<", "勾選 Web API"),
                     (">5<", "複製 Client ID 和 Client Secret")):
        assert n in combined and title in combined
