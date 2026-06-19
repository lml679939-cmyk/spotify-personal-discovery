"""
Y2K / Retro Pop theme for Spotify Personal Discovery.
All CSS, SVG assets, and HTML helpers live here.
"""

import html as html_mod
import streamlit as st

# ── SVG Assets ────────────────────────────────────────────

SVG_CASSETTE = '''<svg viewBox="0 0 120 80" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="5" width="110" height="70" rx="12" fill="#FFD700" stroke="#2D1B4E" stroke-width="3"/>
  <rect x="20" y="18" width="80" height="32" rx="6" fill="#FFFDF7" stroke="#2D1B4E" stroke-width="2"/>
  <circle cx="42" cy="34" r="10" fill="none" stroke="#FF69B4" stroke-width="2"/>
  <circle cx="78" cy="34" r="10" fill="none" stroke="#00D4AA" stroke-width="2"/>
  <circle cx="42" cy="34" r="4" fill="#FF69B4"/>
  <circle cx="78" cy="34" r="4" fill="#00D4AA"/>
  <line x1="52" y1="34" x2="68" y2="34" stroke="#2D1B4E" stroke-width="1.5"/>
  <rect x="30" y="58" width="60" height="8" rx="4" fill="#2D1B4E" opacity="0.15"/>
  <rect x="35" y="60" width="50" height="4" rx="2" fill="#9B59B6" opacity="0.4"/>
</svg>'''

SVG_VINYL = '''<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <circle cx="50" cy="50" r="45" fill="#2D1B4E"/>
  <circle cx="50" cy="50" r="38" fill="none" stroke="#9B59B6" stroke-width="0.8" opacity="0.5"/>
  <circle cx="50" cy="50" r="30" fill="none" stroke="#FF69B4" stroke-width="0.6" opacity="0.4"/>
  <circle cx="50" cy="50" r="22" fill="none" stroke="#9B59B6" stroke-width="0.8" opacity="0.5"/>
  <circle cx="50" cy="50" r="15" fill="#FF69B4"/>
  <circle cx="50" cy="50" r="10" fill="#FFD700"/>
  <circle cx="50" cy="50" r="4" fill="#2D1B4E"/>
</svg>'''

SVG_NOTES = '''<svg viewBox="0 0 80 60" xmlns="http://www.w3.org/2000/svg">
  <g fill="#FF69B4">
    <ellipse cx="18" cy="45" rx="7" ry="5" transform="rotate(-20 18 45)"/>
    <rect x="24" y="12" width="3" height="34" rx="1.5"/>
    <path d="M25 12 Q35 8 40 15 Q35 12 27 14Z"/>
  </g>
  <g fill="#00D4AA">
    <ellipse cx="48" cy="42" rx="7" ry="5" transform="rotate(-15 48 42)"/>
    <rect x="54" y="10" width="3" height="33" rx="1.5"/>
    <ellipse cx="65" cy="38" rx="7" ry="5" transform="rotate(-15 65 38)"/>
    <rect x="71" y="6" width="3" height="33" rx="1.5"/>
    <rect x="55.5" y="6" width="17" height="3.5" rx="1.5" fill="#00D4AA"/>
  </g>
</svg>'''

SVG_BOOMBOX = '''<svg viewBox="0 0 140 90" xmlns="http://www.w3.org/2000/svg">
  <rect x="5" y="15" width="130" height="65" rx="10" fill="#00D4AA" stroke="#2D1B4E" stroke-width="3"/>
  <rect x="45" y="5" width="50" height="18" rx="5" fill="#FFD700" stroke="#2D1B4E" stroke-width="2"/>
  <circle cx="35" cy="52" r="18" fill="#FFD700" stroke="#2D1B4E" stroke-width="2.5"/>
  <circle cx="35" cy="52" r="10" fill="#FFFDF7" stroke="#2D1B4E" stroke-width="1.5"/>
  <circle cx="35" cy="52" r="4" fill="#FF69B4"/>
  <circle cx="105" cy="52" r="18" fill="#FFD700" stroke="#2D1B4E" stroke-width="2.5"/>
  <circle cx="105" cy="52" r="10" fill="#FFFDF7" stroke="#2D1B4E" stroke-width="1.5"/>
  <circle cx="105" cy="52" r="4" fill="#FF69B4"/>
  <rect x="55" y="35" width="30" height="18" rx="4" fill="#FFFDF7" stroke="#2D1B4E" stroke-width="1.5"/>
  <rect x="60" y="58" width="8" height="5" rx="2" fill="#9B59B6"/>
  <rect x="72" y="58" width="8" height="5" rx="2" fill="#FF69B4"/>
</svg>'''

SVG_SPARKLE = '''<svg viewBox="0 0 30 30" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 2 L17.5 12 L28 15 L17.5 18 L15 28 L12.5 18 L2 15 L12.5 12Z" fill="{color}"/>
</svg>'''

def _sparkle(color="#FFD700", size=20):
    svg = SVG_SPARKLE.replace("{color}", color)
    return f'<span style="display:inline-block;width:{size}px;height:{size}px;vertical-align:middle">{svg}</span>'


def _svg_inline(svg_str, width=60):
    return f'<span style="display:inline-block;width:{width}px;vertical-align:middle">{svg_str}</span>'




# ── CSS ───────────────────────────────────────────────────

def _build_global_css():
    return f"""
@import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;700;900&display=swap');

:root {{
    --y2k-cyan: #00D4AA;
    --y2k-pink: #FF69B4;
    --y2k-yellow: #FFD700;
    --y2k-purple: #9B59B6;
    --y2k-deep-purple: #2D1B4E;
    --y2k-cream: #FFFDF7;
    --y2k-lavender: #FFF0F5;
    --y2k-border-radius: 18px;
    --y2k-shadow: 4px 4px 0px;
}}

/* ── Global ─────────────────── */
.stApp, [data-testid="stAppViewContainer"] {{
    font-family: 'Nunito', 'Noto Sans TC', sans-serif !important;
    background-color: var(--y2k-cream) !important;
}}
.main .block-container {{
    max-width: 1000px;
    font-family: 'Nunito', 'Noto Sans TC', sans-serif !important;
    padding-top: 0.5rem !important;
}}
h1, h2, h3, [data-testid="stHeading"] {{
    font-family: 'Nunito', 'Noto Sans TC', sans-serif !important;
    font-weight: 900 !important;
    color: var(--y2k-deep-purple) !important;
}}
h1 {{
    background: linear-gradient(135deg, var(--y2k-pink), var(--y2k-purple), var(--y2k-cyan));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}}
p, li, label, [data-testid="stText"],
[data-testid="stCaptionContainer"] {{
    font-family: 'Nunito', 'Noto Sans TC', sans-serif !important;
}}
span:not(.material-symbols-rounded):not(.material-symbols-outlined):not([class*="material"]):not([data-testid="stIconMaterial"]) {{
    font-family: 'Nunito', 'Noto Sans TC', sans-serif !important;
}}

/* ── Sidebar ────────────────── */
[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, #FFE4F0 0%, var(--y2k-lavender) 50%, #E8F8F5 100%) !important;
    border-right: 4px solid var(--y2k-pink) !important;
}}
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {{
    -webkit-text-fill-color: var(--y2k-deep-purple) !important;
    background: none !important;
}}

/* ── Dividers ───────────────── */
[data-testid="stMain"] hr {{
    border: none !important;
    height: 3px !important;
    background: linear-gradient(90deg, var(--y2k-cyan), var(--y2k-pink), var(--y2k-yellow)) !important;
    border-radius: 2px !important;
    margin: 1.5rem 0 !important;
}}

/* ── Alert boxes ────────────── */
[data-testid="stAlert"] {{
    border-radius: var(--y2k-border-radius) !important;
    border-left: 5px solid var(--y2k-cyan) !important;
    font-family: 'Nunito', 'Noto Sans TC', sans-serif !important;
}}

/* ── Buttons ────────────────── */
.stButton > button,
[data-testid="stBaseButton-primary"],
[data-testid="stBaseButton-secondary"] {{
    border-radius: 25px !important;
    font-weight: 700 !important;
    font-family: 'Nunito', 'Noto Sans TC', sans-serif !important;
    letter-spacing: 0.5px;
    transition: all 0.15s ease !important;
    border: 3px solid var(--y2k-deep-purple) !important;
}}
[data-testid="stBaseButton-primary"] {{
    box-shadow: var(--y2k-shadow) var(--y2k-purple) !important;
}}
[data-testid="stBaseButton-primary"]:hover {{
    box-shadow: 2px 2px 0px var(--y2k-purple) !important;
    transform: translate(2px, 2px);
}}
[data-testid="stBaseButton-primary"]:active {{
    box-shadow: 0px 0px 0px var(--y2k-purple) !important;
    transform: translate(4px, 4px);
}}
[data-testid="stBaseButton-secondary"],
.stButton > button:not([data-testid="stBaseButton-primary"]) {{
    background: var(--y2k-cream) !important;
    color: var(--y2k-deep-purple) !important;
    box-shadow: var(--y2k-shadow) var(--y2k-cyan) !important;
}}
[data-testid="stBaseButton-secondary"]:hover,
.stButton > button:not([data-testid="stBaseButton-primary"]):hover {{
    box-shadow: 2px 2px 0px var(--y2k-cyan) !important;
    transform: translate(2px, 2px);
    background: #E8FFF8 !important;
}}

/* ── Link buttons ───────────── */
.stLinkButton > a {{
    border-radius: 25px !important;
    font-weight: 700 !important;
    font-family: 'Nunito', 'Noto Sans TC', sans-serif !important;
    border: 3px solid var(--y2k-deep-purple) !important;
    box-shadow: var(--y2k-shadow) var(--y2k-purple) !important;
    transition: all 0.15s ease !important;
}}
.stLinkButton > a:hover {{
    box-shadow: 2px 2px 0px var(--y2k-purple) !important;
    transform: translate(2px, 2px);
}}

/* ── Download buttons ───────── */
[data-testid="stDownloadButton"] > button {{
    border-radius: 25px !important;
    font-weight: 700 !important;
    font-family: 'Nunito', 'Noto Sans TC', sans-serif !important;
    border: 3px solid var(--y2k-deep-purple) !important;
    background: linear-gradient(135deg, var(--y2k-cyan), var(--y2k-pink)) !important;
    color: white !important;
    box-shadow: var(--y2k-shadow) var(--y2k-purple) !important;
    transition: all 0.15s ease !important;
}}
[data-testid="stDownloadButton"] > button:hover {{
    box-shadow: 2px 2px 0px var(--y2k-purple) !important;
    transform: translate(2px, 2px);
}}

/* ── Sliders ────────────────── */
[data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {{
    width: 22px !important;
    height: 22px !important;
    box-shadow: 2px 2px 0px var(--y2k-deep-purple) !important;
    border: 3px solid var(--y2k-deep-purple) !important;
}}
[data-testid="stSlider"] label {{
    font-weight: 700 !important;
}}

/* ── Pills ──────────────────── */
[data-testid="stPills"] button {{
    border-radius: 20px !important;
    font-weight: 700 !important;
    font-family: 'Nunito', 'Noto Sans TC', sans-serif !important;
    border: 2.5px solid var(--y2k-deep-purple) !important;
    transition: all 0.15s ease !important;
}}
[data-testid="stPills"] button:nth-child(4n+1) {{
    box-shadow: 2px 2px 0px var(--y2k-cyan) !important;
}}
[data-testid="stPills"] button:nth-child(4n+2) {{
    box-shadow: 2px 2px 0px var(--y2k-pink) !important;
}}
[data-testid="stPills"] button:nth-child(4n+3) {{
    box-shadow: 2px 2px 0px var(--y2k-yellow) !important;
}}
[data-testid="stPills"] button:nth-child(4n+4) {{
    box-shadow: 2px 2px 0px var(--y2k-purple) !important;
}}
[data-testid="stPills"] button[aria-checked="true"],
[data-testid="stPills"] button[data-selected="true"] {{
    border-color: var(--y2k-pink) !important;
    font-weight: 900 !important;
}}

/* ── Expanders ──────────────── */
[data-testid="stExpander"] {{
    border: 3px solid var(--y2k-deep-purple) !important;
    border-left: 6px solid var(--y2k-cyan) !important;
    border-radius: var(--y2k-border-radius) !important;
    overflow: hidden;
    box-shadow: 3px 3px 0px rgba(155,89,182,0.2) !important;
}}
[data-testid="stExpander"] summary {{
    font-weight: 700 !important;
    font-family: 'Nunito', 'Noto Sans TC', sans-serif !important;
}}

/* ── Text inputs ────────────── */
.stTextInput input, .stTextArea textarea,
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea {{
    border: 3px solid var(--y2k-deep-purple) !important;
    border-radius: 14px !important;
    font-family: 'Nunito', 'Noto Sans TC', sans-serif !important;
    transition: all 0.2s ease !important;
}}
.stTextInput input:focus, .stTextArea textarea:focus,
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {{
    border-color: var(--y2k-pink) !important;
    box-shadow: 0 0 0 3px rgba(255,105,180,0.25) !important;
}}

/* ── Selectbox ──────────────── */
[data-testid="stSelectbox"] [data-baseweb="select"] > div {{
    border: 3px solid var(--y2k-deep-purple) !important;
    border-radius: 14px !important;
    font-family: 'Nunito', 'Noto Sans TC', sans-serif !important;
}}

/* ── File uploader ──────────── */
[data-testid="stFileUploader"] {{
    border: 3px dashed var(--y2k-cyan) !important;
    border-radius: var(--y2k-border-radius) !important;
    padding: 1rem !important;
    transition: all 0.2s ease !important;
}}
[data-testid="stFileUploader"]:hover {{
    background: rgba(0,212,170,0.06) !important;
    border-color: var(--y2k-pink) !important;
}}

/* ── Toggle ─────────────────── */
[data-testid="stCheckbox"] label {{
    font-weight: 700 !important;
}}

/* ── Radio buttons ──────────── */
[data-testid="stRadio"] label {{
    font-weight: 700 !important;
    font-family: 'Nunito', 'Noto Sans TC', sans-serif !important;
}}

/* ── Sticker label (custom) ─── */
.y2k-sticker-label {{
    display: inline-block;
    padding: 2px 12px;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 700;
    border: 2px solid var(--y2k-deep-purple);
    font-family: 'Nunito', 'Noto Sans TC', sans-serif;
}}

/* ── Status container ───────── */
[data-testid="stStatusWidget"], [data-testid="stStatus"] {{
    border-radius: var(--y2k-border-radius) !important;
    border: 3px solid var(--y2k-deep-purple) !important;
    box-shadow: var(--y2k-shadow) rgba(155,89,182,0.2) !important;
}}
"""


# ── HTML helpers ──────────────────────────────────────────

_ACCENT_COLORS = ["#00D4AA", "#FF69B4", "#FFD700", "#9B59B6"]


def section_header_html(text, icon="notes"):
    svg_map = {"notes": SVG_NOTES, "vinyl": SVG_VINYL, "cassette": SVG_CASSETTE, "boombox": SVG_BOOMBOX}
    svg = svg_map.get(icon, SVG_NOTES)
    return f"""<div style="display:flex;align-items:center;gap:12px;margin:1.2rem 0 0.6rem 0">
  <span style="display:inline-block;width:50px">{svg}</span>
  <span style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:900;font-size:1.4rem;color:#2D1B4E">{html_mod.escape(text)}</span>
  {_sparkle('#FFD700', 18)}{_sparkle('#FF69B4', 14)}
</div>"""


def login_hero_html():
    return f"""<div style="text-align:center;padding:0 1rem 1rem 1rem">
  <div style="display:flex;justify-content:center;align-items:center;gap:16px;margin-bottom:0.8rem">
    <span style="display:inline-block;width:70px">{SVG_CASSETTE}</span>
    <span style="display:inline-block;width:80px">{SVG_BOOMBOX}</span>
    <span style="display:inline-block;width:60px">{SVG_VINYL}</span>
  </div>
  <h1 style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:900;font-size:2.4rem;
    background:linear-gradient(135deg,#FF69B4,#9B59B6,#00D4AA);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
    margin:0 0 0.3rem 0;line-height:1.2">
    Spotify Personal Discovery
  </h1>
  <p style="font-family:'Nunito','Noto Sans TC',sans-serif;color:#2D1B4E;font-size:1.05rem;opacity:0.8;margin:0;text-align:center">
    {_sparkle('#FFD700', 16)} 根據你的聆聽習慣與當下情境，發現從未聽過的好歌 {_sparkle('#FF69B4', 16)}
  </p>
</div>"""


def _method_card_html(title, description, border_color, icon_svg):
    return f"""<div style="border:3px solid #2D1B4E;border-left:6px solid {border_color};
  border-radius:18px;padding:1.2rem 1.4rem 0.8rem 1.4rem;margin:0.8rem 0;
  min-height:130px;box-sizing:border-box;
  box-shadow:4px 4px 0px {border_color}33;background:white">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:0.4rem">
    <span style="display:inline-block;width:36px">{icon_svg}</span>
    <span style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:900;font-size:1.15rem;color:#2D1B4E">
      {html_mod.escape(title)}
    </span>
  </div>
  <p style="font-family:'Nunito','Noto Sans TC',sans-serif;color:#2D1B4E;opacity:0.75;font-size:0.92rem;margin:0 0 0.5rem 0">
    {html_mod.escape(description)}
  </p>
</div>"""


def login_spotify_card():
    return _method_card_html(
        "方式一：用 Spotify 登入（個人化推薦）",
        "讀取你的聆聽紀錄，交給 Gemini AI 生成「你沒聽過、但會喜歡」的推薦。",
        "#00D4AA",
        SVG_VINYL,
    )


def login_guest_card():
    return _method_card_html(
        "方式二：不登入，直接推薦（訪客模式）",
        "不需要 Spotify 帳號，根據你描述的情境與偏好推薦音樂。",
        "#FFD700",
        SVG_BOOMBOX,
    )


def divider_html():
    return f"""<div style="display:flex;align-items:center;justify-content:center;gap:8px;margin:1.2rem 0;opacity:0.5">
  <div style="flex:1;height:2px;background:linear-gradient(90deg,transparent,#FF69B4)"></div>
  <span style="display:inline-block;width:40px">{SVG_NOTES}</span>
  <div style="flex:1;height:2px;background:linear-gradient(90deg,#00D4AA,transparent)"></div>
</div>"""


def context_interpretation_html(text):
    escaped = html_mod.escape(text)
    return f"""<div style="border:3px solid #2D1B4E;border-left:6px solid #9B59B6;
  border-radius:18px;padding:1.2rem 1.4rem;margin:0.8rem 0;
  box-shadow:4px 4px 0px rgba(155,89,182,0.2);
  background:linear-gradient(135deg,#FFF0F5,#FFFDF7)">
  <div style="display:flex;align-items:flex-start;gap:10px">
    <span style="font-size:1.6rem;line-height:1">💭</span>
    <div>
      <span style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:700;font-size:0.8rem;
        color:#9B59B6;text-transform:uppercase;letter-spacing:1px">AI 情境解讀</span>
      <p style="font-family:'Nunito','Noto Sans TC',sans-serif;color:#2D1B4E;margin:0.3rem 0 0 0;
        font-size:0.95rem;line-height:1.6">{escaped}</p>
    </div>
  </div>
</div>"""


def track_card_html(track, index):
    accent = _ACCENT_COLORS[index % 4]
    name = html_mod.escape(track.get("name", ""))
    artist = html_mod.escape(track.get("artist", ""))
    album = html_mod.escape(track.get("album", ""))
    reason = html_mod.escape(track.get("reason", ""))
    cover_url = track.get("cover", "")

    cover_html = (
        f'<img src="{html_mod.escape(cover_url)}" '
        f'style="width:100%;aspect-ratio:1;object-fit:cover;border-radius:12px;'
        f'border:3px solid #2D1B4E;display:block" />'
        if cover_url
        else '<div style="width:100%;aspect-ratio:1;background:#FFF0F5;border-radius:12px;'
        'border:3px solid #2D1B4E;display:flex;align-items:center;justify-content:center;'
        'font-size:2rem">🎵</div>'
    )

    album_html = (
        f'<div style="font-size:0.75rem;color:#9B59B6;margin-top:2px">💿 {album}</div>'
        if album
        else ""
    )

    return f"""<div style="border:3px solid #2D1B4E;border-radius:18px;padding:10px;
  box-shadow:4px 4px 0px {accent};background:white;margin-bottom:8px;
  transition:transform 0.15s ease,box-shadow 0.15s ease">
  {cover_html}
  <div style="padding:6px 2px 2px 2px">
    <div style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:900;font-size:0.88rem;
      color:#2D1B4E;line-height:1.3;overflow:hidden;display:-webkit-box;
      -webkit-line-clamp:2;-webkit-box-orient:vertical">{name}</div>
    <div style="font-family:'Nunito','Noto Sans TC',sans-serif;font-size:0.78rem;color:#666;
      margin-top:2px">{artist}</div>
    {album_html}
    <div style="margin-top:5px">
      <span style="display:inline-block;padding:2px 8px;border-radius:10px;font-size:0.7rem;
        font-weight:700;color:white;background:{accent};font-family:'Nunito','Noto Sans TC',sans-serif;
        border:1.5px solid #2D1B4E;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
        💡 {reason}
      </span>
    </div>
  </div>
</div>"""


def track_list_html(track, index):
    accent = _ACCENT_COLORS[index % 4]
    name = html_mod.escape(track.get("name", ""))
    artist = html_mod.escape(track.get("artist", ""))
    album = html_mod.escape(track.get("album", ""))
    reason = html_mod.escape(track.get("reason", ""))
    cover_url = track.get("cover", "")
    num = index + 1

    cover_html = (
        f'<img src="{html_mod.escape(cover_url)}" '
        f'style="width:60px;height:60px;object-fit:cover;border-radius:10px;'
        f'border:3px solid #2D1B4E;display:block" />'
        if cover_url
        else '<div style="width:60px;height:60px;background:#FFF0F5;border-radius:10px;'
        'border:3px solid #2D1B4E;display:flex;align-items:center;justify-content:center;'
        'font-size:1.4rem">🎵</div>'
    )

    album_part = f"💿 {album}　·　" if album else ""

    return f"""<div style="display:flex;align-items:center;gap:14px;padding:10px 14px;
  border-left:5px solid {accent};border-radius:0 14px 14px 0;margin-bottom:6px;
  background:white;border:2px solid #2D1B4E20;border-left:5px solid {accent};
  box-shadow:2px 2px 0px {accent}33">
  <span style="font-family:'Nunito',sans-serif;font-weight:900;font-size:1.1rem;color:{accent};
    min-width:24px;text-align:center">{num}</span>
  {cover_html}
  <div style="flex:1;min-width:0">
    <div style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:900;font-size:0.92rem;
      color:#2D1B4E;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{name}
      <span style="font-weight:400;color:#666"> — {artist}</span>
    </div>
    <div style="font-family:'Nunito','Noto Sans TC',sans-serif;font-size:0.78rem;color:#888;margin-top:2px">
      {album_part}💡 {reason}
    </div>
  </div>
</div>"""


def results_header_html(count):
    return f"""<div style="display:flex;align-items:center;gap:12px;margin:1.2rem 0 0.8rem 0">
  <span style="display:inline-block;width:45px">{SVG_VINYL}</span>
  <span style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:900;font-size:1.5rem;color:#2D1B4E">
    推薦歌單</span>
  <span style="display:inline-flex;align-items:center;justify-content:center;
    width:36px;height:36px;border-radius:50%;background:#FF69B4;color:white;
    font-family:'Nunito',sans-serif;font-weight:900;font-size:1rem;
    border:2.5px solid #2D1B4E;box-shadow:2px 2px 0px #9B59B6">
    {count}
  </span>
  {_sparkle('#FFD700', 20)}{_sparkle('#00D4AA', 14)}
</div>"""


# ── BYOK Guide ───────────────────────────────────────────

def byok_spotify_steps_html(redirect_uri: str) -> str:
    """Render a visual step-by-step guide for obtaining Spotify API keys."""
    escaped_uri = html_mod.escape(redirect_uri)

    steps = [
        (
            "#00D4AA",
            "1",
            "🌐",
            "開啟 Spotify Developer Dashboard",
            f'前往 <a href="https://developer.spotify.com/dashboard" target="_blank" '
            f'style="color:#00D4AA;font-weight:700;text-decoration:none">'
            f'developer.spotify.com/dashboard</a> 並登入你的 Spotify 帳號。',
        ),
        (
            "#FF69B4",
            "2",
            "➕",
            "建立新 App",
            '點擊右上角 <strong>Create App</strong>，'
            'App Name 和 Description 隨意填寫都沒關係。',
        ),
        (
            "#FFD700",
            "3",
            "🔗",
            "設定 Redirect URI（最重要！）",
            f'在 <strong>Redirect URIs</strong> 欄位填入以下網址，'
            f'必須<strong>一字不差</strong>：'
            f'<div style="margin-top:8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
            f'  <code style="background:#2D1B4E;color:#FFD700;padding:6px 12px;border-radius:8px;'
            f'font-size:0.88rem;font-family:monospace;flex:1;min-width:0;word-break:break-all">'
            f'{escaped_uri}</code>'
            f'  <button onclick="navigator.clipboard.writeText(\'{escaped_uri}\').then(()=>{{'
            f'this.textContent=\'✅ 已複製!\';setTimeout(()=>{{this.textContent=\'📋 複製\';}},2000);}})" '
            f'style="cursor:pointer;padding:6px 14px;border-radius:20px;border:2.5px solid #2D1B4E;'
            f'background:#FFD700;color:#2D1B4E;font-weight:700;font-family:Nunito,sans-serif;'
            f'font-size:0.82rem;white-space:nowrap;box-shadow:2px 2px 0 #2D1B4E;'
            f'transition:all 0.15s ease">📋 複製</button>'
            f'</div>',
        ),
        (
            "#9B59B6",
            "4",
            "☑️",
            "勾選 Web API",
            '在 <strong>Which API/SDKs are you planning to use?</strong> 區塊，'
            '勾選 <strong>Web API</strong>，然後儲存。',
        ),
        (
            "#00D4AA",
            "5",
            "🔑",
            "複製 Client ID 和 Client Secret",
            '建立完成後，在 App 的 Settings 頁面就能看到 '
            '<strong>Client ID</strong> 和 <strong>Client Secret</strong>，複製後貼到下方欄位。',
        ),
    ]

    steps_html = ""
    for color, num, icon, title, desc in steps:
        steps_html += f"""
<div style="display:flex;gap:12px;align-items:flex-start;padding:12px 0;
  border-bottom:2px dashed {color}33">
  <div style="flex-shrink:0;width:36px;height:36px;border-radius:50%;
    background:{color};border:2.5px solid #2D1B4E;
    display:flex;align-items:center;justify-content:center;
    font-family:'Nunito',sans-serif;font-weight:900;font-size:1rem;color:#2D1B4E;
    box-shadow:2px 2px 0 #2D1B4E">{num}</div>
  <div style="flex:1;min-width:0">
    <div style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:900;
      font-size:0.95rem;color:#2D1B4E;margin-bottom:4px">{icon} {title}</div>
    <div style="font-family:'Nunito','Noto Sans TC',sans-serif;font-size:0.87rem;
      color:#444;line-height:1.6">{desc}</div>
  </div>
</div>"""

    return f"""
<div style="border:3px solid #2D1B4E;border-left:6px solid #1DB954;
  border-radius:18px;padding:16px 18px;margin:8px 0;
  box-shadow:4px 4px 0px rgba(29,185,84,0.25);background:white">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
    <svg viewBox='0 0 24 24' width='28' fill='#1DB954' xmlns='http://www.w3.org/2000/svg'>
      <circle cx='12' cy='12' r='12' fill='#1DB954'/>
      <path d='M17.9 10.9C14.7 9 9.35 8.8 6.3 9.75c-.5.15-1-.15-1.15-.6-.15-.5.15-1 .6-1.15
        3.55-1.05 9.4-.85 13.1 1.35.45.25.6.85.35 1.3-.25.35-.85.5-1.3.25zm-.1 2.8
        c-.25.35-.7.5-1.05.25-2.7-1.65-6.8-2.15-9.95-1.15-.4.1-.85-.1-.95-.5-.1-.4.1-.85.5-.95
        3.65-1.1 8.15-.55 11.25 1.35.3.15.45.65.2 1zm-1.2 2.75c-.2.3-.55.4-.85.2
        -2.35-1.45-5.3-1.75-8.8-.95-.35.1-.65-.15-.75-.45-.1-.35.15-.65.45-.75
        3.8-.85 7.1-.5 9.7 1.1.35.15.4.55.25.85z' fill='white'/>
    </svg>
    <span style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:900;
      font-size:1.05rem;color:#2D1B4E">Spotify API — 5 分鐘快速申請</span>
    <a href="https://developer.spotify.com/dashboard" target="_blank"
      style="margin-left:auto;font-family:'Nunito',sans-serif;font-size:0.8rem;
      color:#1DB954;font-weight:700;text-decoration:none">前往 Dashboard →</a>
  </div>
  {steps_html}
</div>"""


def byok_gemini_section_html() -> str:
    """Render the Gemini API key guide section."""
    return f"""
<div style="border:3px solid #2D1B4E;border-left:6px solid #4285F4;
  border-radius:18px;padding:16px 18px;margin:8px 0;
  box-shadow:4px 4px 0px rgba(66,133,244,0.2);background:white">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
    <svg viewBox='0 0 48 48' width='28' xmlns='http://www.w3.org/2000/svg'>
      <circle cx='24' cy='24' r='24' fill='#4285F4'/>
      <path d='M24 12 C24 12 30 20 30 24 C30 28 24 36 24 36
               C24 36 18 28 18 24 C18 20 24 12 24 12Z' fill='white' opacity='0.9'/>
      <path d='M12 24 C12 24 20 18 24 18 C28 18 36 24 36 24
               C36 24 28 30 24 30 C20 30 12 24 12 24Z' fill='white' opacity='0.7'/>
      <circle cx='24' cy='24' r='4' fill='white'/>
    </svg>
    <span style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:900;
      font-size:1.05rem;color:#2D1B4E">Gemini API — 免費申請</span>
    <a href="https://aistudio.google.com/apikey" target="_blank"
      style="margin-left:auto;font-family:'Nunito',sans-serif;font-size:0.8rem;
      color:#4285F4;font-weight:700;text-decoration:none">前往 AI Studio →</a>
  </div>
  <div style="display:flex;gap:12px;align-items:flex-start">
    <div style="flex-shrink:0;width:36px;height:36px;border-radius:50%;
      background:#4285F4;border:2.5px solid #2D1B4E;
      display:flex;align-items:center;justify-content:center;
      font-family:'Nunito',sans-serif;font-weight:900;font-size:0.9rem;color:white;
      box-shadow:2px 2px 0 #2D1B4E">1</div>
    <div style="font-family:'Nunito','Noto Sans TC',sans-serif;font-size:0.87rem;
      color:#444;line-height:1.7">
      前往 <a href="https://aistudio.google.com/apikey" target="_blank"
      style="color:#4285F4;font-weight:700;text-decoration:none">Google AI Studio</a>，
      用 Google 帳號登入 → 點擊 <strong>Create API Key</strong> → 複製後貼到下方欄位。
      <br><span style="font-size:0.8rem;color:#888">✨ 免費 Tier 每分鐘可呼叫 15 次，個人使用完全夠用。</span>
    </div>
  </div>
</div>"""


def byok_privacy_badge_html() -> str:
    return """
<div style="display:flex;align-items:center;gap:8px;padding:10px 14px;
  border-radius:12px;background:#F0FFF8;border:2px solid #00D4AA;margin-top:8px">
  <span style="font-size:1.2rem">🔒</span>
  <span style="font-family:'Nunito','Noto Sans TC',sans-serif;font-size:0.83rem;
    color:#2D1B4E;line-height:1.5">
    所有 Keys 僅存在你的<strong>瀏覽器分頁記憶體</strong>中，關閉分頁即消失，不會傳送到任何伺服器。
  </span>
</div>"""


# ── Inject ────────────────────────────────────────────────

def inject_global_css():
    st.markdown(f"<style>{_build_global_css()}</style>", unsafe_allow_html=True)
