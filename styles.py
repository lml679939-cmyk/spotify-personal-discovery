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
  <!-- 單獨的八分音符：符頭 → 符桿 → 符尾三段互相重疊，不留縫 -->
  <g fill="#FF69B4">
    <ellipse cx="17" cy="45.5" rx="7.5" ry="5.5" transform="rotate(-20 17 45.5)"/>
    <rect x="22.6" y="12" width="3.4" height="34" rx="1.7"/>
    <path d="M25.4 12 C33.5 14.5 38 19 34.2 26 C35.4 20 31.5 17 25.4 18.6 Z"/>
  </g>
  <!-- 連桁的兩個八分音符：符桿頂端高度不同，符桁必須是斜的平行四邊形才接得上 -->
  <g fill="#00D4AA">
    <ellipse cx="47" cy="43.5" rx="7.5" ry="5.5" transform="rotate(-20 47 43.5)"/>
    <ellipse cx="66" cy="39.5" rx="7.5" ry="5.5" transform="rotate(-20 66 39.5)"/>
    <rect x="52.6" y="9" width="3.4" height="35" rx="1.7"/>
    <rect x="71.6" y="5" width="3.4" height="35" rx="1.7"/>
    <path d="M52.6 8 L75 4 L75 9.5 L52.6 13.5 Z"/>
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
[data-testid="stDecoration"],
[data-testid="stDecorationLine"],
header [data-testid="stToolbar"] + div,
header::after,
.stDecorationLine,
div[class*="decoration"] {{
    display: none !important;
    height: 0 !important;
    visibility: hidden !important;
}}
/* Streamlit 會在標題尾端插入錨點連結圖示（inline-flex，佔行內寬度），
   置中標題換行時會被它推偏——這個 app 用不到錨點，直接隱藏 */
[data-testid="stHeaderActionElements"] {{
    display: none !important;
}}
[data-testid="stHeader"],
header {{
    display: none !important;
    height: 0 !important;
    overflow: hidden !important;
    visibility: hidden !important;
}}
.main .block-container {{
    max-width: 1000px;
    font-family: 'Nunito', 'Noto Sans TC', sans-serif !important;
    padding-top: 0 !important;
}}
/* 新版 Streamlit 沒有 .main 祖先，block-container 掛在 stMainBlockContainer testid 上；
   預設 padding-top 6rem 讓頁面頂部留白過大。
   0.8rem + 元件間隙 16px ≈ 29px，與 hero 下方間距（padding-bottom 16px + 卡片 margin 12.8px）對齊 */
[data-testid="stMainBlockContainer"] {{
    padding-top: 0.8rem !important;
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

/* 區塊之間的呼吸空間：桌機小、手機大（見檔案最後的 media query）*/
/* 只在手機生效的換行點，桌機停用 */
br.y2k-mbr {{ display: none; }}

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
/* 次要按鈕減重：粗框 + 彩色陰影只留給主要 CTA */
[data-testid="stBaseButton-secondary"],
.stButton > button:not([data-testid="stBaseButton-primary"]) {{
    background: var(--y2k-cream) !important;
    color: var(--y2k-deep-purple) !important;
    border: 2px solid rgba(45, 27, 78, 0.35) !important;
    box-shadow: none !important;
}}
[data-testid="stBaseButton-secondary"]:hover,
.stButton > button:not([data-testid="stBaseButton-primary"]):hover {{
    border-color: var(--y2k-pink) !important;
    background: #FFF0F5 !important;
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
/* 次要元件一律減重：粗框與彩色陰影只留給主要 CTA，畫面才有主次 */
[data-testid="stExpander"] {{
    border: 2px solid rgba(45, 27, 78, 0.28) !important;
    border-radius: var(--y2k-border-radius) !important;
    overflow: hidden;
    box-shadow: none !important;
    margin-bottom: 0 !important;   /* 間距一律交給 flex gap，見「垂直間距三級制」 */
}}
/* 摺疊內容不要貼著下框線（登入頁的隱私標示原本會黏在邊框上）。
   Streamlit 給 stMarkdownContainer 的 -16px 負邊界是用來抵銷段落 margin 的，
   但我們注入的自訂 HTML 沒有那個 margin，於是最後一塊內容會被拉去貼住框線 */
[data-testid="stExpanderDetails"] {{
    padding-top: 1.35rem !important;
    padding-bottom: 1.35rem !important;
}}
[data-testid="stExpanderDetails"] [data-testid="stElementContainer"]:last-of-type [data-testid="stMarkdownContainer"] {{
    margin-bottom: 0 !important;
}}
[data-testid="stExpander"] summary {{
    font-weight: 700 !important;
    font-family: 'Nunito', 'Noto Sans TC', sans-serif !important;
}}

/* ── 投射問題那一列：題目欄收成內容寬，按鈕才會緊跟在題目後面 ──
   （固定欄寬時短題目後面會空一大片，題目長度 170–403px 差很多） */
.st-key-proj_row [data-testid="stHorizontalBlock"] {{
    flex-wrap: wrap;
    gap: 1.25rem !important;   /* 量出來 20px：夠近，又不會黏在題號上 */
    align-items: center;
}}
.st-key-proj_row [data-testid="stColumn"] {{
    flex: 0 0 auto !important;
    width: auto !important;
    min-width: 0 !important;
}}

/* ── 垂直間距三級制（8 / 16 / 32）──────────────────
   原本混用了三套機制：Streamlit 垂直區塊的 flex gap(16px)、自己插的 .y2k-gap 空 div、
   還有 stMarkdownContainer 的 -16px 負邊界，相加後量到 16/20/26/32/41/49 六種間距。
   現在只留 flex gap 當基準（16px＝並列欄位），再用 widget 的 key class 加減出另外兩級：
     8px  組內（標題 → 它的輸入框、題目 → 回答框）
     32px 區塊之間（手機；桌機 24px）
   ⚠️ 這些 key 都必須跟 app.py 的 key= 對得上，改名要一起改。 */
/* ⚠️ 這裡的數字是「在 16px flex gap 之上再加減多少」，不是最終間距。
   桌機：區塊 16+8=24、CTA 16+8=24、組內 16-8=8。 */
.st-key-auto_ctx,
.st-key-proj_row,
.st-key-exp_songs,
.st-key-btn_generate {{ margin-top: 8px; }}
.st-key-auto_ctx {{ margin-bottom: -8px; }}
.st-key-text_ctx,
.st-key-ctx_image,
.st-key-projective_a {{ margin-top: -8px; }}
/* hero 的 markdown container 帶 -16px 負邊界，會把下面的第一個元件吸上來 */
[data-testid="stMarkdownContainer"]:has(.y2k-form-title) {{ margin-bottom: 0 !important; }}
h2.y2k-form-title {{ font-size: 2rem !important; }}

/* 標題裡不想被拆散的補充片語（例如括號說明）：整段當一個字，
   要換行就整段換到下一行，不會斷成「…給 AI / 分析）」 */
.y2k-keep {{ display: inline-block; }}

/* 右欄上傳區的隱形標題（見 app.py 的 ctx_label_spacer）：佔高度但不顯示。
   ⚠️ 只寫在容器上沒用——Streamlit 自己對 stMarkdownContainer 設了 visibility:visible，
   會把繼承來的 hidden 蓋掉，文字照樣顯示出來。必須連子孫一起 !important。 */
.st-key-ctx_label_spacer,
.st-key-ctx_label_spacer * {{ visibility: hidden !important; }}

/* ── 推薦網格：同一列的卡片等高，Spotify 按鈕才會對齊 ──
   歌名 1/2 行、專輯有無、理由有無都會讓卡片高度不同；
   把 column → verticalBlock → 第一個 elementContainer 這條鏈都拉成 flex 並給高度，
   卡片自己的 height:100% 才有依據（Streamlit 的 column 本來就會拉成該列最高） */
.st-key-track_grid [data-testid="stColumn"] {{
    display: flex;
}}
.st-key-track_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] {{
    flex: 1;
    display: flex;
    flex-direction: column;
}}
.st-key-track_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"]
    > [data-testid="stElementContainer"]:first-child {{
    flex: 1;
}}
/* elementContainer → stMarkdown → (emotion wrapper) → stMarkdownContainer → 卡片，
   中間任何一層漏掉 height:100%，卡片就只會長到內容高度（按鈕仍會齊，但短卡片下緣會縮） */
.st-key-track_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"]
    > [data-testid="stElementContainer"]:first-child [data-testid="stMarkdown"],
.st-key-track_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"]
    > [data-testid="stElementContainer"]:first-child [data-testid="stMarkdown"] > div,
.st-key-track_grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"]
    > [data-testid="stElementContainer"]:first-child [data-testid="stMarkdownContainer"] {{
    height: 100%;
}}

/* ── Text inputs ────────────── */
.stTextInput input, .stTextArea textarea,
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea {{
    border: 2px solid rgba(45, 27, 78, 0.28) !important;
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
    border: 2px solid rgba(45, 27, 78, 0.28) !important;
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
    border: 2px solid rgba(45, 27, 78, 0.28) !important;
    box-shadow: none !important;
}}

/* ── 手機版覆寫（必須放最後，同特異性下後定義者勝）───────── */
@media (max-width: 640px) {{
    /* 區塊之間拉開，讓堆疊後的版面有分組感 */
    /* 手機：區塊 16+16=32、CTA 16+8=24（數字同樣是「再加多少」）*/
    .st-key-auto_ctx,
    .st-key-proj_row,
    .st-key-exp_songs {{ margin-top: 16px !important; }}
    .st-key-btn_generate {{ margin-top: 8px !important; }}
    /* 兩欄堆疊後上傳區是獨立欄位，維持 16px（桌機的 -8 是要貼齊隱形標題）*/
    .st-key-ctx_image {{ margin-top: 0 !important; }}
    h2.y2k-form-title {{ font-size: 1.7rem !important; }}
    /* 手機上兩欄會堆疊，不需要對齊佔位。整個 layout wrapper 一起收掉——
       只把裡面的 vertical block 設 display:none 的話，wrapper 仍是 flex item，
       上下各吃掉一個 16px gap，量到文字框與上傳區之間多出 32px */
    [data-testid="stLayoutWrapper"]:has(> .st-key-ctx_label_spacer) {{ display: none !important; }}
    .st-key-ctx_label_spacer {{ display: none !important; }}
    /* 換一題換行掉到下一行時，貼著題目而不是浮在中間 */
    .st-key-proj_row [data-testid="stHorizontalBlock"] {{ row-gap: 8px !important; }}
    /* 登入卡片標題在手機上於「方式一：」後換行，避免硬斷在詞中間 */
    br.y2k-mbr {{ display: inline !important; }}
    /* 上傳區的說明文字在手機上佔一整行，收掉只留 Upload 按鈕 */
    [data-testid="stFileUploaderDropzoneInstructions"] {{ display: none !important; }}
    [data-testid="stFileUploaderDropzone"] {{ justify-content: center !important; }}
}}
"""


# ── HTML helpers ──────────────────────────────────────────

_ACCENT_COLORS = ["#00D4AA", "#FF69B4", "#FFD700", "#9B59B6"]
# 理由標籤的文字色要跟著底色走：白字壓在黃底上對比只有 1.4:1，幾乎看不見。
# 亮底（青/粉/黃）配深紫字（5.1–9.6:1），深底（紫）才配白字（4.7:1）。
_ACCENT_TEXT_COLORS = ["#2D1B4E", "#2D1B4E", "#2D1B4E", "#FFFFFF"]


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
    margin:0 0 0.3rem 0;line-height:1.2;text-align:center">Spotify Personal Discovery</h1>
</div>"""


def form_hero_html():
    """主表單頁的標題區：跟登入頁同一套視覺語言（圖示列 + 漸層字），字級小一階。

    用注入 HTML 而不是 st.subheader，是為了避開 Streamlit 插在標題尾端的錨點元素
    （inline-flex，會把置中標題推偏，手機換行時特別明顯）。
    """
    return _tidy(f"""<div style="text-align:center;padding:0.2rem 0 0 0">
  <div style="display:flex;justify-content:center;align-items:center;gap:14px;margin-bottom:0.5rem">
    <span style="display:inline-block;width:54px">{SVG_NOTES}</span>
    <span style="display:inline-block;width:60px">{SVG_CASSETTE}</span>
    <span style="display:inline-block;width:44px">{SVG_VINYL}</span>
  </div>
  <h2 class="y2k-form-title" style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:900;
    background:linear-gradient(135deg,#FF69B4,#9B59B6,#00D4AA);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
    margin:0;padding:0;line-height:1.25;text-align:center">打造專屬於你的歌單吧</h2>
</div>""")


def _method_card_html(title, description, border_color, icon_svg):
    # 手機上標題會從「方式一：直接開始（推薦，免」硬斷成兩行很難看。
    # 在全形冒號後插一個只在手機生效的 <br>（見 CSS 的 br.y2k-mbr），桌機仍維持單行。
    if "：" in title:
        _prefix, _rest = title.split("：", 1)
        title_html = (
            f"{html_mod.escape(_prefix)}：<br class=\"y2k-mbr\">{html_mod.escape(_rest)}"
        )
    else:
        title_html = html_mod.escape(title)
    return f"""<div style="border:3px solid #2D1B4E;
  border-radius:18px;padding:1rem 1.4rem;margin:0.8rem 0;
  min-height:130px;box-sizing:border-box;
  display:flex;flex-direction:column;justify-content:center;
  box-shadow:4px 4px 0px {border_color}33;background:white">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:0.4rem">
    <span style="display:inline-block;width:36px">{icon_svg}</span>
    <span style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:900;font-size:1.15rem;color:#2D1B4E">{title_html}</span>
  </div>
  <p style="font-family:'Nunito','Noto Sans TC',sans-serif;color:#2D1B4E;opacity:0.75;font-size:0.92rem;margin:0">{html_mod.escape(description)}</p>
</div>"""


def login_guest_card():
    return _method_card_html(
        "方式一：直接開始（推薦，免登入）",
        "不需要 Spotify 帳號、不用申請任何 API Key，描述當下情境就能拿到 AI 推薦歌單。",
        "#FFD700",
        SVG_BOOMBOX,
    )


def login_spotify_card():
    return _method_card_html(
        "方式二：連結 Spotify",
        "讀取你的聆聽紀錄，推薦「你沒聽過、但會喜歡」的歌，並可直接存成 Spotify 歌單。",
        "#00D4AA",
        SVG_VINYL,
    )


def divider_html():
    return f"""<div style="display:flex;align-items:center;justify-content:center;gap:8px;margin:1.2rem 0;opacity:0.5">
  <div style="flex:1;height:2px;background:linear-gradient(90deg,transparent,#FF69B4)"></div>
  <span style="display:inline-block;width:40px">{SVG_NOTES}</span>
  <div style="flex:1;height:2px;background:linear-gradient(90deg,#00D4AA,transparent)"></div>
</div>"""


def context_interpretation_html(text):
    escaped = html_mod.escape(text)
    return f"""<div style="border:3px solid #2D1B4E;
  border-radius:18px;padding:1.2rem 1.4rem;margin:0.8rem 0;
  box-shadow:4px 4px 0px rgba(155,89,182,0.2);
  background:linear-gradient(135deg,#FFF0F5,#FFFDF7)">
  <div style="display:flex;align-items:center;gap:10px">
    <span style="font-size:1.6rem;line-height:1;display:flex;align-items:center">💭</span>
    <span style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:700;font-size:0.8rem;
      color:#9B59B6;text-transform:uppercase;letter-spacing:1px;line-height:1">AI 情境解讀</span>
  </div>
  <p style="font-family:'Nunito','Noto Sans TC',sans-serif;color:#2D1B4E;margin:0.5rem 0 0 0;
    font-size:0.95rem;line-height:1.6">{escaped}</p>
</div>"""


def _tidy(html: str) -> str:
    """把注入用的 HTML 拉平成無縮排、無空行。

    Streamlit 的 markdown 會把「縮排 4 個空白」的行當成程式碼區塊。條件式片段
    （例如沒有專輯名時的 album_html）算出來是空字串時，那一行只剩縮排的空白＝空行，
    後面縮排 4 空白的 <div> 就被當成 code block 印出原始碼——就是「理由標籤變成程式碼」的 bug。
    """
    return "\n".join(stripped for line in html.splitlines() if (stripped := line.strip()))


def track_card_html(track, index):
    accent = _ACCENT_COLORS[index % 4]
    accent_text = _ACCENT_TEXT_COLORS[index % 4]
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
        f'<div style="font-size:0.75rem;color:#9B59B6;margin-top:2px;'
        f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap">💿 {album}</div>'
        if album
        else ""
    )

    # 沒有理由文字時整塊不畫——否則會留下一個只有 💡 的空標籤（密集網格會把 reason 清掉）
    reason_html = (
        f'<div style="margin-top:5px">'
        f'<span style="display:inline-block;padding:2px 8px;border-radius:10px;font-size:0.7rem;'
        f"font-weight:700;color:{accent_text};background:{accent};"
        f"font-family:'Nunito','Noto Sans TC',sans-serif;"
        f'border:1.5px solid #2D1B4E;max-width:100%;overflow:hidden;'
        f'text-overflow:ellipsis;white-space:nowrap">💡 {reason}</span></div>'
        if reason
        else ""
    )

    return _tidy(f"""<div style="border:3px solid #2D1B4E;border-radius:18px;padding:10px;
  box-shadow:4px 4px 0px {accent};background:white;margin-bottom:8px;
  height:100%;box-sizing:border-box;
  transition:transform 0.15s ease,box-shadow 0.15s ease">
  {cover_html}
  <div style="padding:6px 2px 2px 2px">
    <div style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:900;font-size:0.88rem;
      color:#2D1B4E;line-height:1.3;overflow:hidden;display:-webkit-box;
      -webkit-line-clamp:2;-webkit-box-orient:vertical">{name}</div>
    <div style="font-family:'Nunito','Noto Sans TC',sans-serif;font-size:0.78rem;color:#666;
      margin-top:2px">{artist}</div>
    {album_html}
    {reason_html}
  </div>
</div>""")


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
<div style="border:3px solid #2D1B4E;
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


def byok_privacy_badge_html() -> str:
    return """
<div style="display:flex;align-items:center;gap:8px;padding:10px 14px;
  border-radius:12px;background:#F0FFF8;margin:8px 0 4px 0">
  <span style="font-size:1.2rem">🔒</span>
  <span style="font-family:'Nunito','Noto Sans TC',sans-serif;font-size:0.83rem;
    color:#2D1B4E;line-height:1.5">
    你填的 Keys 僅存在<strong>瀏覽器分頁記憶體</strong>中，關閉分頁即消失，不會被儲存下來。
  </span>
</div>"""


# ── Inject ────────────────────────────────────────────────

def inject_global_css():
    st.markdown(f"<style>{_build_global_css()}</style>", unsafe_allow_html=True)
