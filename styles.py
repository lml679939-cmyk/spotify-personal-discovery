"""
Y2K / Retro Pop theme for SoundCurator.
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
  <!-- 符桿右緣要落在符頭橢圓「裡面」（右緣距圓心 6.0，橢圓在該角度的極值是 7.29），
       桿底收到符頭中心高度；桿底兩角超出橢圓就會像原本那樣從符頭右下角凸出來 -->
  <g fill="#FF69B4">
    <ellipse cx="17" cy="45.5" rx="7.5" ry="5.5" transform="rotate(-20 17 45.5)"/>
    <rect x="19.6" y="12" width="3.4" height="33.5" rx="1.7"/>
    <!-- 符尾尖端做成小圓頭：兩條曲線收在同一個點時，抗鋸齒會在尖端留下幾個孤立像素 -->
    <path d="M22.5 12 C30.5 14.5 35 19 31.9 25.4 C31.6 26.1 31 26 30.8 25.3
             C32.2 20 28.8 17 22.5 18.6 Z"/>
  </g>
  <!-- 兩根符桿頂端高度不同，符桁必須是斜的平行四邊形才蓋得住兩端 -->
  <g fill="#00D4AA">
    <ellipse cx="47" cy="43.5" rx="7.5" ry="5.5" transform="rotate(-20 47 43.5)"/>
    <ellipse cx="66" cy="39.5" rx="7.5" ry="5.5" transform="rotate(-20 66 39.5)"/>
    <rect x="49.6" y="9" width="3.4" height="34.5" rx="1.7"/>
    <rect x="68.6" y="5" width="3.4" height="34.5" rx="1.7"/>
    <path d="M49.6 8 L72 4 L72 9.5 L49.6 13.5 Z"/>
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

# ── Y2K 圖示系統（2026-08-21 提案定案）────────────────────
# 造型文法：糖果色填色＋深紫描邊、一主色至多一輔色（與卡帶／黑膠同一家）。
# 設計稿：https://claude.ai/code/artifact/d2fc1112-59da-4c0b-8fd7-e63461e53725
SVG_CLIPBOARD = '''<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
  <rect x="8" y="7" width="32" height="36" rx="6" fill="#FFD700" stroke="#2D1B4E" stroke-width="2.5"/>
  <rect x="13" y="13" width="22" height="26" rx="3" fill="#FFFDF7" stroke="#2D1B4E" stroke-width="2"/>
  <rect x="17" y="3.5" width="14" height="9" rx="4" fill="#FF69B4" stroke="#2D1B4E" stroke-width="2.5"/>
  <line x1="17.5" y1="21" x2="30.5" y2="21" stroke="#9B59B6" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="17.5" y1="27" x2="30.5" y2="27" stroke="#9B59B6" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="17.5" y1="33" x2="25.5" y2="33" stroke="#00D4AA" stroke-width="2.5" stroke-linecap="round"/>
</svg>'''

# 對話氣泡：情境輸入標題用（與下面的題目氣泡同一個外形、換色換內容＝姊妹圖示）
SVG_CHAT = '''<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
  <path d="M24 6 C13.5 6 6 12.8 6 21.5 C6 27 9 31.5 13.5 34.2 L11.5 41.5 L20 37 C21.3 37.2 22.6 37.3 24 37.3 C34.5 37.3 42 30.4 42 21.6 C42 12.8 34.5 6 24 6 Z" fill="#FF69B4" stroke="#2D1B4E" stroke-width="2.5" stroke-linejoin="round"/>
  <line x1="15" y1="18.5" x2="33" y2="18.5" stroke="#FFFDF7" stroke-width="3.2" stroke-linecap="round"/>
  <line x1="15" y1="25.5" x2="27" y2="25.5" stroke="#FFFDF7" stroke-width="3.2" stroke-linecap="round"/>
</svg>'''

# 題目氣泡：投射問題的統一圖示（原本 30 題每題一顆 emoji，定案改一致性優先）。
# 問號用 <path> 不用 <text>——SVG text 依賴頁面字型載入時序，位置也會隨字型抖動
# 鎖頭：隱私徽章用。鎖環用「深紫粗線墊底＋黃色細線疊上」畫出帶描邊的管子
# （聯集畫法的線條版）；鎖環兩端收在鎖身上緣之下，被鎖身蓋住＝無接縫
SVG_LOCK = '''<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
  <path d="M15 22 L15 16 C15 10.5 19 7 24 7 C29 7 33 10.5 33 16 L33 22" fill="none" stroke="#2D1B4E" stroke-width="5.4" stroke-linecap="round"/>
  <path d="M15 22 L15 16 C15 10.5 19 7 24 7 C29 7 33 10.5 33 16 L33 22" fill="none" stroke="#FFD700" stroke-width="2.4" stroke-linecap="round"/>
  <rect x="9" y="20" width="30" height="22" rx="7" fill="#FFD700" stroke="#2D1B4E" stroke-width="2.5"/>
  <circle cx="24" cy="29.5" r="3.2" fill="#2D1B4E"/>
  <rect x="22.6" y="31" width="2.8" height="6.5" rx="1.4" fill="#2D1B4E"/>
</svg>'''

SVG_QUESTION = '''<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
  <path d="M24 6 C13.5 6 6 12.8 6 21.5 C6 27 9 31.5 13.5 34.2 L11.5 41.5 L20 37 C21.3 37.2 22.6 37.3 24 37.3 C34.5 37.3 42 30.4 42 21.6 C42 12.8 34.5 6 24 6 Z" fill="#00D4AA" stroke="#2D1B4E" stroke-width="2.5" stroke-linejoin="round"/>
  <path d="M18.5 18.5 C18.5 15 21 13 24.2 13 C27.4 13 29.8 15 29.8 18 C29.8 20.3 28.5 21.5 26.9 22.6 C25.5 23.6 25 24.3 25 26 L22.3 26 C22.3 23.4 23.2 22.2 24.9 21 C26.3 20 26.9 19.2 26.9 18 C26.9 16.5 25.8 15.6 24.2 15.6 C22.5 15.6 21.4 16.6 21.3 18.5 Z" fill="#2D1B4E"/>
  <circle cx="23.7" cy="30" r="1.9" fill="#2D1B4E"/>
</svg>'''

def _sparkle(color="#FFD700", size=20):
    svg = SVG_SPARKLE.replace("{color}", color)
    return f'<span style="display:inline-block;width:{size}px;height:{size}px;vertical-align:middle">{svg}</span>'


def _svg_inline(svg_str, width=60):
    return f'<span style="display:inline-block;width:{width}px;vertical-align:middle">{svg_str}</span>'


def _mini_vinyl(size=12):
    """行內迷你黑膠（取代 💿）：填滿行內小方框、對齊專輯名的視覺墨水中心。

    ⚠️ 兩件事都是量測結果（先量再改），缺一不可——之前只調 vertical-align 沒調第①點，
    使用者 reboot 兩次都說「沒有置中」，根因就在這：
    ① `SVG_VINYL` 預設 display:inline，會坐在文字 baseline 上、在 span 內偏低 4.7px（實測），
       所以黑膠中心根本不在 span 中心，vertical-align 再怎麼算都白校。**注入 display:block**
       讓 SVG 以區塊填滿並置中 span（實測 svg 中心 == span 中心、殘差 0）才有意義。
       登入 hero 的黑膠 o、表單 hero 的裝飾黑膠早就這樣做（那些 SVG 都帶 display:block）。
    ② display:block 之後版面才線性可算：實測「黑膠中心 − x-height 中心 = -vertical-align - 3」(px)。
       目標放在**文字墨水光學中心**（含大寫/上緣，比 x-height 中心高 1–2px）：
       -2px → 正中拉丁專輯名墨水中心、CJK 名只低 1px（雙向最大偏差 1px，實測最佳折衷）。
       -3px＝落在 x-height 中心，拉丁/CJK 都偏低 1–2px（看起來偏低）。改 size 或專輯字級要重量。
    """
    svg = SVG_VINYL.replace(
        "<svg ", '<svg style="display:block;width:100%;height:100%" ', 1)
    return (f'<span style="display:inline-block;width:{size}px;height:{size}px;'
            f'vertical-align:-2px">{svg}</span>')




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
/* ⚠️ 排除清單漏掉任何一種 Material 圖示 span，那種圖示就會被 Nunito 蓋掉字型、
   連字失效顯示成文字（例如「music_note」）。目前已知三種變體（都實測踩過）：
   ① pills/按鈕的 stIconMaterial ② expander 的 stExpanderIcon
   ③ markdown 行內（caption/標籤/標題內的 :material/xxx:）＝無 class 無 testid，
     只有 translate="no" 屬性可以認 */
span:not(.material-symbols-rounded):not(.material-symbols-outlined):not([class*="material"]):not([data-testid="stIconMaterial"]):not([data-testid="stExpanderIcon"]):not([translate="no"]) {{
    font-family: 'Nunito', 'Noto Sans TC', sans-serif !important;
}}

/* 區塊之間的呼吸空間：桌機小、手機大（見檔案最後的 media query）*/

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
/* 題目改成氣泡＋文字的 <div> 後沒有 <p> 的 16px 下邊距可以抵銷 stMarkdownContainer
   的 -16px 負邊界，內容盒矮了 16px、欄位置中因此歪 8px——把負邊界歸零。
   情境標題（y2k-ctx-label）同一個機制：不歸零的話 textarea 會上移 16px 蓋到標題 */
.st-key-proj_row [data-testid="stMarkdownContainer"],
[data-testid="stMarkdownContainer"]:has(.y2k-ctx-label) {{
    margin-bottom: 0 !important;
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
/* 同意提示卡（結果區頂端）：柔和粉底＋標準細框——取代 st.info 突兀的藍，與品牌粉呼應、
   不搶生成 CTA。行內 :material: 圖示的上下置中靠全域規則，這裡只管卡片外觀與內距。 */
.st-key-consent_banner {{
    background: rgba(255, 105, 180, 0.10);
    border: 2px solid rgba(45, 27, 78, 0.28);
    border-radius: 14px;
    padding: 0.9rem 1.15rem;
    margin: 0.25rem 0 1rem;
}}
/* 歌單評分卡：上緣被 caption 的 -16px 負邊界吸近上方分隔線（實測 top gap 24 vs bottom 40），
   補 16px 讓上下間距對稱（先量再改）。 */
.st-key-playlist_rating {{ margin-top: 16px; }}
/* hero 的 markdown container 帶 -16px 負邊界，會把下面的第一個元件吸上來 */
[data-testid="stMarkdownContainer"]:has(.y2k-form-title) {{ margin-bottom: 0 !important; }}
/* 登入 hero（Option C）：min-height 117 對齊表單 hero，但 stMarkdownContainer 的 -16px
   會把 block 縮成 101、下方登入卡片被吸上來、看起來比表單 hero 矮——同樣歸零 */
[data-testid="stMarkdownContainer"]:has(.y2k-login-hero) {{ margin-bottom: 0 !important; }}
/* ⚠️ Streamlit 自己的 .stMarkdown h2 是 2.25rem，單一 class 選擇器蓋不過去——
   一定要寫成 h2.y2k-form-title 並加 !important */
h2.y2k-form-title {{ font-size: 2.9rem !important; }}

/* 標題裡不想被拆散的補充片語（例如括號說明）：整段當一個字，
   要換行就整段換到下一行，不會斷成「…給 AI / 分析）」 */
.y2k-keep {{ display: inline-block; }}

/* 右欄上傳區的隱形標題（見 app.py 的 ctx_label_spacer）：佔高度但不顯示。
   ⚠️ 只寫在容器上沒用——Streamlit 自己對 stMarkdownContainer 設了 visibility:visible，
   會把繼承來的 hidden 蓋掉，文字照樣顯示出來。必須連子孫一起 !important。 */
.st-key-ctx_label_spacer,
.st-key-ctx_label_spacer * {{ visibility: hidden !important; }}

/* ── BYOK 步驟卡：上半 + st.code(Redirect URI) + 下半，接成一張卡 ──
   為什麼要拆：自製的複製按鈕是死的（Streamlit 會濾掉 onclick），改用 st.code() 才真的
   能複製；順帶讓 redirect_uri 完全不經過 unsafe_allow_html。但 Streamlit 每個元件各自
   一個容器，HTML 標籤跨不過去，所以只能「畫成」一張卡：
     上半 → 無下框線、只有上圓角     中間 → 補左右框線、無圓角     下半 → 無上框線、只有下圓角
   陰影同理要拆：上半與中間只給右側（4px 0），下半才給右+下（4px 4px），
   否則接縫處會出現兩道重疊的投影。 */
/* ⚠️ 這兩條要成對出現，少一條就會有縫或重疊（量出來的，別憑感覺調）：
   ① gap 要下在 .st-key-byok_steps **自己**身上——它本身就是那個 stVerticalBlock，
      寫成後代選擇器 `.st-key-byok_steps [data-testid="stVerticalBlock"]` 選不到自己，
      外層仍是 16px。
   ② 同時要歸零 stMarkdownContainer 的 -16px 負邊界。原本 head→mid 量到 0 是**碰巧**
      ——那 16px 剛好被負邊界抵銷；只設 gap:0 的話負邊界就變成 16px 重疊。
   實測：修好前 head→mid 0 / mid→tail 16，修好後兩處都是 0。 */
.st-key-byok_steps {{ gap: 0 !important; }}
.st-key-byok_steps [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
.y2k-byok-card {{
    border: 3px solid var(--y2k-deep-purple);
    background: white;
    padding: 16px 18px;
    box-sizing: border-box;
}}
.y2k-byok-head {{
    border-bottom: none;
    border-radius: var(--y2k-border-radius) var(--y2k-border-radius) 0 0;
    box-shadow: 4px 0 0 rgba(29,185,84,0.25);
    padding-bottom: 4px;
}}
.y2k-byok-tail {{
    border-top: none;
    border-radius: 0 0 var(--y2k-border-radius) var(--y2k-border-radius);
    box-shadow: 4px 4px 0 rgba(29,185,84,0.25);
    padding-top: 4px;
}}
/* 中段（st.code）：補上左右框線，讓上下兩半連起來 */
.st-key-byok_uri {{
    border-left: 3px solid var(--y2k-deep-purple);
    border-right: 3px solid var(--y2k-deep-purple);
    background: white;
    box-shadow: 4px 0 0 rgba(29,185,84,0.25);
    padding: 0 18px 8px 18px;
}}
/* stCode 預設有 margin-bottom，會在中段底部撐出一條白縫 */
.st-key-byok_uri [data-testid="stCode"],
.st-key-byok_uri pre {{ margin-bottom: 0 !important; }}

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

/* ── Material 圖示染色（B 層圖示系統）─────────
   原生元件（pills/按鈕/expander）塞不進自繪 SVG，只吃 :material/xxx:，
   用 CSS 統一染色讓它們跟 A 層貼紙同一家。預設繼承文字色（深紫／主 CTA 白），
   四個摺疊區各配一個糖果色。selector 綁 key，改 key 名要一起改這裡。
   ⚠️ expander 圖示的 testid 是 stExpanderIcon（不是 stIconMaterial）——
   它的字型由上方 span 全域規則的 :not() 排除清單保護，見那條規則的註解 */
/* 圖示行高固定 1：行高繼承 1.6 會把連字字圖抬離盒中心，按鈕裡看起來偏上 */
[data-testid="stIconMaterial"], [data-testid="stExpanderIcon"] {{ line-height: 1 !important; }}
/* markdown 行內圖示（:material/xxx: 寫在 st.write / st.caption / ### 裡，例如生成敘事行、
   隱私/歷史/額度 caption）與後面文字實測 gap=0、緊貼在一起。補右邊距拉開。
   ⚠️ 這種變體無 testid、只有 translate="no"，且**必須**排除按鈕(stIconMaterial)與
   expander(stExpanderIcon)——它們也帶 translate="no"、是 flex 版、間距由 flex 自理，
   加 margin 會多推一截。上下置中實測本來就 OK（icon 中心僅低文字 0.7px），故不動垂直。 */
span[translate="no"]:not([data-testid="stIconMaterial"]):not([data-testid="stExpanderIcon"]) {{
    margin-right: 0.4em;
}}
.st-key-exp_songs [data-testid="stExpanderIcon"] {{ color: var(--y2k-pink) !important; }}
.st-key-exp_music [data-testid="stExpanderIcon"] {{ color: #00A88A !important; }}
.st-key-exp_mood [data-testid="stExpanderIcon"] {{ color: #E0A800 !important; }}
.st-key-exp_traits [data-testid="stExpanderIcon"] {{ color: var(--y2k-purple) !important; }}

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
    h2.y2k-form-title {{ font-size: 2rem !important; }}
    /* 表單 hero 的漂浮裝飾在 375px 會蓋到縮小的標題/溢出——手機直接收掉，
       只留大標題＋標題尾那顆星芒（它在標題 div 內、不是 .y2k-decor，會保留）；
       hero 也不用 min-height 撐裝飾空間了 */
    .y2k-decor {{ display: none !important; }}
    .y2k-form-hero {{ min-height: 0 !important; }}
    /* 舊圖示列規則（現在無圖示，留著無害）：
       ⚠️ 選擇器一定要限定在圖示列——Streamlit 會在 <h2> 裡再包一層 span，
       寫成 .y2k-form-hero span 會連標題文字一起被縮小。 */
    .y2k-form-icons > span {{ transform: scale(0.82); }}
    /* 手機上兩欄會堆疊，不需要對齊佔位。整個 layout wrapper 一起收掉——
       只把裡面的 vertical block 設 display:none 的話，wrapper 仍是 flex item，
       上下各吃掉一個 16px gap，量到文字框與上傳區之間多出 32px */
    [data-testid="stLayoutWrapper"]:has(> .st-key-ctx_label_spacer) {{ display: none !important; }}
    .st-key-ctx_label_spacer {{ display: none !important; }}
    /* 換一題換行掉到下一行時，貼著題目而不是浮在中間 */
    .st-key-proj_row [data-testid="stHorizontalBlock"] {{ row-gap: 8px !important; }}
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

# 「出圈」標籤刻意用固定色（不跟著 _ACCENT_COLORS 輪替）——它是語意標記不是裝飾，
# 顏色一變就沒有辨識度了。青底配深紫字，對比 9.6:1。
_DISCOVERY_BG = "#00D4AA"
_DISCOVERY_FG = "#2D1B4E"


def _discovery_badge_html(track, *, floating: bool, compact: bool = False) -> str:
    """「這首來自你沒接觸過的音樂人」的標記。floating=True 是浮貼在封面上的版本。

    ⚠️ 標籤寬度固定，但網格愈密卡片愈窄。每列 10 首時封面只有 58px、標籤 54px——
    會超出封面邊界還蓋掉 35% 的專輯圖。所以密集網格改用 compact（只留指南針圖示）。
    """
    if not track.get("_discovery"):
        return ""
    pos = ("position:absolute;top:6px;left:6px;z-index:2;" if floating
           else "display:inline-block;vertical-align:1px;margin-right:6px;")
    pad = "1px 4px" if compact else "1px 7px"
    text = "🧭" if compact else "🧭 出圈"
    return (
        f'<span title="來自你沒接觸過的音樂人" style="{pos}padding:{pad};border-radius:9px;'
        f'font-size:0.62rem;font-weight:900;color:{_DISCOVERY_FG};background:{_DISCOVERY_BG};'
        f"border:2px solid #2D1B4E;font-family:'Nunito','Noto Sans TC',sans-serif;"
        f'white-space:nowrap">{text}</span>'
    )


def context_label_html():
    """情境輸入的標題列：對話氣泡＋粗體文案（與投射問題同一套版式）。

    不收參數＝沒有注入面。右欄的隱藏對齊佔位（ctx_label_spacer）**必須用同一個
    helper**——兩邊內容完全相同，換行行為才一致、兩個輸入框頂端才會永遠對齊。
    括號補充照舊包在 .y2k-keep 裡（窄螢幕整段一起換行）。
    """
    # ⚠️ align-items 要用 flex-start 不是 center：文字折成兩行時（手機必發生），
    # center 會讓氣泡浮在兩行中間、離第一行中心 13px。flex-start 讓 26px 的圖示
    # 對齊 25.6px 的第一行行框（line-height 1.6 × 16px），單行與多行都置中（量測 ±1px）
    return (
        '<div class="y2k-ctx-label" style="display:flex;align-items:flex-start;gap:10px">'
        f'<span style="display:inline-block;width:26px;height:26px;flex:0 0 auto">{SVG_CHAT}</span>'
        '<span style="font-family:\'Nunito\',\'Noto Sans TC\',sans-serif;font-weight:900;font-size:1rem;color:#2D1B4E">'
        '分享一下你的日常吧<span class="y2k-keep">（也可以上傳圖片給 AI 分析）</span></span>'
        "</div>"
    )


def projective_question_html(question):
    """投射問題那一行：統一的題目氣泡 + 粗體題目文字。

    題目來自我們自己的常數，但照樣 escape——哪天題目改成可自訂就不會變成注入面。
    輸出保持單行、無縮排（Streamlit 會把縮排行當程式碼區塊）。
    """
    q = html_mod.escape(question)
    # flex-start 不是 center：長題目在手機折行時，center 會讓氣泡浮在兩行中間
    # （同 context_label_html 的註解，26px 圖示天然對齊 25.6px 行框）
    return (
        '<div style="display:flex;align-items:flex-start;gap:10px">'
        f'<span style="display:inline-block;width:26px;height:26px;flex:0 0 auto">{SVG_QUESTION}</span>'
        f'<span style="font-family:\'Nunito\',\'Noto Sans TC\',sans-serif;font-weight:900;font-size:1rem;color:#2D1B4E">{q}</span>'
        "</div>"
    )


def section_header_html(text, icon="notes"):
    svg_map = {"notes": SVG_NOTES, "vinyl": SVG_VINYL, "cassette": SVG_CASSETTE,
               "boombox": SVG_BOOMBOX, "clipboard": SVG_CLIPBOARD}
    svg = svg_map.get(icon, SVG_NOTES)
    return f"""<div style="display:flex;align-items:center;gap:12px;margin:1.2rem 0 0.6rem 0">
  <span style="display:inline-block;width:50px">{svg}</span>
  <span style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:900;font-size:1.4rem;color:#2D1B4E">{html_mod.escape(text)}</span>
  {_sparkle('#FFD700', 18)}{_sparkle('#FF69B4', 14)}
</div>"""


def login_hero_html():
    # Option C（Vinyl-O Logomark，2026-08-22，取代舊的「三貼紙圖示＋漸層字」）：
    # 黑膠當成 Sound 的「o」，Sound 深紫、Curator 紫，下方一句 tagline。
    # ⚠️ h1 一定要 margin:0;padding:0——Streamlit 的 .stMarkdown h1 預設帶 padding-top。
    # ⚠️ 黑膠中心用奶油色當「o 的洞」，不能用深紫（會跟字連成一塊、看不出是 o）。
    # ⚠️ 黑膠靠行內 vertical-align:baseline + translateY 對齊，不是 flex——Streamlit 會把
    #    h1 內容包進一個 <span id=":r0:">，h1 的 display:flex 只作用到那層包裝、碰不到內層 span。
    # ⚠️ translateY(0.075em) 是量測校準值：baseline 對齊時黑膠中心比「und」墨水中心高 1.88px
    #    （@2.6rem），往下推到殘差 ~0。改字級要重量（用瀏覽器量 svg vs und range 的 centerY）。
    # ⚠️ 注入 HTML 內部各行不要縮排——Streamlit markdown 會把縮排行當程式碼區塊。
    vinyl_o = ('<svg viewBox="0 0 100 100" style="width:100%;height:auto;display:block" '
               'xmlns="http://www.w3.org/2000/svg">'
               '<circle cx="50" cy="50" r="48" fill="#2D1B4E"/>'
               '<circle cx="50" cy="50" r="40" fill="none" stroke="#9B59B6" stroke-width="1.2" opacity="0.55"/>'
               '<circle cx="50" cy="50" r="31" fill="none" stroke="#FF69B4" stroke-width="1" opacity="0.5"/>'
               '<circle cx="50" cy="50" r="22" fill="none" stroke="#9B59B6" stroke-width="1.2" opacity="0.55"/>'
               '<circle cx="50" cy="50" r="15" fill="#FF69B4"/>'
               '<circle cx="50" cy="50" r="10" fill="#FFD700"/>'
               '<circle cx="50" cy="50" r="4" fill="#FFFDF7"/></svg>')
    return f"""<div class="y2k-login-hero" style="text-align:center;padding:0 1rem;min-height:117px;box-sizing:border-box;display:flex;flex-direction:column;align-items:center;justify-content:center">
<h1 style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:900;font-size:2.6rem;line-height:1;letter-spacing:-1px;color:#2D1B4E;margin:0;padding:0;text-align:center">
<span>S</span><span style="display:inline-block;width:0.8em;height:0.8em;margin:0 0.03em;transform:translateY(0.075em)">{vinyl_o}</span><span>und</span><span style="color:#9B59B6">Curator</span>
</h1>
<div style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:700;font-size:0.98rem;letter-spacing:2px;color:#2D1B4E;opacity:0.62;margin-top:0.55rem">不推弟，只推歌。還不快叫我乾歌</div>
</div>"""


def form_hero_html():
    """主表單頁的標題：放大漸層字＋小圖示漂浮裝飾、左對齊（2026-08-22，使用者定案）。

    C·非對稱漂浮 ＋ A·標題尾星芒：黑膠＋星芒漂左上、音符＋星芒漂右下、標題尾綴一顆星芒。
    圖示是「縮小的精緻裝飾」不是主角——`position:absolute` 定在 hero 四角留白、z-index 低於標題。
    ⚠️ 字級走 CSS 的 `h2.y2k-form-title`（!important，桌機 2.9rem／手機 2rem）。
    ⚠️ 標題左對齊、左緣對齊表單元素；裝飾用 `.y2k-decor` 類別方便手機 media query 收掉/縮小。
    ⚠️ hero 用 `position:relative`＋`min-height` 撐出裝飾空間，容器要包住裝飾才不會蓋到下面表單。
    """
    _vinyl = ('<svg viewBox="0 0 100 100" style="width:100%;height:auto;display:block" xmlns="http://www.w3.org/2000/svg">'
              '<circle cx="50" cy="50" r="45" fill="#2D1B4E"/>'
              '<circle cx="50" cy="50" r="30" fill="none" stroke="#FF69B4" stroke-width="0.6" opacity="0.4"/>'
              '<circle cx="50" cy="50" r="22" fill="none" stroke="#9B59B6" stroke-width="0.8" opacity="0.5"/>'
              '<circle cx="50" cy="50" r="15" fill="#FF69B4"/><circle cx="50" cy="50" r="10" fill="#FFD700"/>'
              '<circle cx="50" cy="50" r="4" fill="#2D1B4E"/></svg>')
    _notes = ('<svg viewBox="0 0 80 60" style="width:100%;height:auto;display:block" xmlns="http://www.w3.org/2000/svg">'
              '<g fill="#FF69B4"><ellipse cx="17" cy="45.5" rx="7.5" ry="5.5" transform="rotate(-20 17 45.5)"/>'
              '<rect x="19.6" y="12" width="3.4" height="33.5" rx="1.7"/>'
              '<path d="M22.5 12 C30.5 14.5 35 19 31.9 25.4 C31.6 26.1 31 26 30.8 25.3 C32.2 20 28.8 17 22.5 18.6 Z"/></g>'
              '<g fill="#00D4AA"><ellipse cx="47" cy="43.5" rx="7.5" ry="5.5" transform="rotate(-20 47 43.5)"/>'
              '<ellipse cx="66" cy="39.5" rx="7.5" ry="5.5" transform="rotate(-20 66 39.5)"/>'
              '<rect x="49.6" y="9" width="3.4" height="34.5" rx="1.7"/><rect x="68.6" y="5" width="3.4" height="34.5" rx="1.7"/>'
              '<path d="M49.6 8 L72 4 L72 9.5 L49.6 13.5 Z"/></g></svg>')

    def _spark(c):
        return ('<svg viewBox="0 0 30 30" style="width:100%;height:auto;display:block" xmlns="http://www.w3.org/2000/svg">'
                f'<path d="M15 2 L17.5 12 L28 15 L17.5 18 L15 28 L12.5 18 L2 15 L12.5 12Z" fill="{c}"/></svg>')

    return _tidy(f"""<div class="y2k-form-hero" style="position:relative;min-height:148px;box-sizing:border-box;display:flex;align-items:center;padding:0.2rem 0">
<span class="y2k-decor" style="position:absolute;top:6px;left:2px;width:30px;transform:rotate(-10deg)">{_vinyl}</span>
<span class="y2k-decor" style="position:absolute;top:18px;left:46px;width:17px">{_spark('#00D4AA')}</span>
<div style="position:relative;z-index:2;display:flex;align-items:center;gap:9px">
<h2 class="y2k-form-title" style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:900;background:linear-gradient(135deg,#FF69B4,#9B59B6,#00D4AA);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin:0;padding:0;line-height:1.15;text-align:left">想成為你專屬的歌單</h2>
<span style="width:22px;flex:none;align-self:flex-start;margin-top:2px">{_spark('#FFD700')}</span>
<span class="y2k-decor" style="width:38px;flex:none;align-self:flex-end;margin-bottom:4px;transform:rotate(8deg)">{_notes}</span>
<span class="y2k-decor" style="width:16px;flex:none;align-self:flex-start;margin-top:10px">{_spark('#9B59B6')}</span>
</div>
</div>""")


def _method_card_html(title, description, border_color, icon_svg):
    # 標題單行呈現。舊版有「手機在全形冒號後強制換行」的 y2k-mbr 機制——那是
    # 標題還叫「方式一：直接開始（推薦，免登入）」時防止斷在詞中間用的；
    # 標題縮短後手機也放得下單行，2026-08-22 依使用者指示移除
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
        "方式一：直接開始",
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
  border-radius:18px;padding:1.2rem 1.4rem;margin:0.8rem 0 1rem 0;
  box-shadow:4px 4px 0px rgba(155,89,182,0.2);
  background:linear-gradient(135deg,#FFF0F5,#FFFDF7)">
  <div style="display:flex;align-items:center;gap:10px">
    <span style="display:flex;align-items:center;transform:translateY(-1.5px)">{_sparkle('#9B59B6', 24)}</span>
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


def track_card_html(track, index, compact_badge=False):
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
        'border:3px solid #2D1B4E;display:flex;align-items:center;justify-content:center">'
        f'<span style="display:inline-block;width:55%">{SVG_NOTES}</span></div>'
    )

    album_html = (
        f'<div style="font-size:0.75rem;color:#9B59B6;margin-top:2px;'
        f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'
        f'{_mini_vinyl()} {album}</div>'
        if album
        else ""
    )

    # 沒有理由文字時整塊不畫——否則會留下一個只有 💡 的空標籤（密集網格會把 reason 清掉）
    # ⚠️ padding 上4下1 刻意不對稱：CJK 字在行框裡偏上（實測墨水中心比對稱 padding 的 pill 中心高
    #    1.56px），多給上邊距把字壓下來才視覺置中（先量再改，pad 4/1 量到殘差 -0.06px）。
    reason_html = (
        f'<div style="margin-top:5px">'
        f'<span style="display:inline-block;padding:4px 8px 1px 8px;border-radius:10px;font-size:0.7rem;'
        f"font-weight:700;color:{accent_text};background:{accent};"
        f"font-family:'Nunito','Noto Sans TC',sans-serif;"
        f'border:1.5px solid #2D1B4E;max-width:100%;overflow:hidden;'
        f'text-overflow:ellipsis;white-space:nowrap">{reason}</span></div>'
        if reason
        else ""
    )

    # 標籤浮貼在封面左上角，不佔垂直空間——卡片要等高，多一列就會讓 ▶ Spotify 按鈕跑掉
    cover_block = (
        f'<div style="position:relative">'
        f'{_discovery_badge_html(track, floating=True, compact=compact_badge)}{cover_html}</div>'
    )

    return _tidy(f"""<div style="border:3px solid #2D1B4E;border-radius:18px;padding:10px;
  box-shadow:4px 4px 0px {accent};background:white;margin-bottom:8px;
  height:100%;box-sizing:border-box;
  transition:transform 0.15s ease,box-shadow 0.15s ease">
  {cover_block}
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
        'border:3px solid #2D1B4E;display:flex;align-items:center;justify-content:center">'
        f'<span style="display:inline-block;width:34px">{SVG_NOTES}</span></div>'
    )

    album_part = f"{_mini_vinyl()} {album}　·　" if album else ""
    disc_part = _discovery_badge_html(track, floating=False)

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
      {disc_part}{album_part}{reason}
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

# BYOK 步驟卡刻意拆成上下兩半，中間讓 app.py 夾一個原生的 st.code(redirect_uri)。
#
# 為什麼不把網址直接畫進 HTML：
#  ① 之前那顆自製的「📋 複製」按鈕**根本是死的**——Streamlit 的 markdown 管線
#     （rehype-raw → React）會把 onclick 這類事件處理器整個濾掉（實測整頁 0 個元素
#     帶 onclick）。按鈕有 cursor:pointer，看起來可點卻毫無反應。
#     st.code() 有 Streamlit 原生的複製圖示，是真的能複製（分享歌單那區同一個做法）。
#  ② 順帶把注入面整個移除：redirect_uri 是使用者可填的值，改由 st.code() 呈現之後
#     **完全不再經過 unsafe_allow_html**，不必再煩惱 HTML/JS 情境該用哪種跳脫。
#
# ⚠️ 兩半要看起來像一張完整的卡片，靠的是 _build_global_css() 裡的 .st-key-byok_steps
#    規則（上半無下框線、下半無上框線、中間補左右框線、垂直 gap 歸零）。
#    改這裡的圓角/框線寬度，那邊要一起改，改完務必用瀏覽器量過接縫。

_BYOK_STEPS_HEAD = (
    ("#00D4AA", "1", "🌐", "開啟 Spotify Developer Dashboard",
     '前往 <a href="https://developer.spotify.com/dashboard" target="_blank" '
     'style="color:#00D4AA;font-weight:700;text-decoration:none">'
     'developer.spotify.com/dashboard</a> 並登入你的 Spotify 帳號。'),
    ("#FF69B4", "2", "➕", "建立新 App",
     '點擊右上角 <strong>Create App</strong>，'
     'App Name 和 Description 隨意填寫都沒關係。'),
    ("#FFD700", "3", "🔗", "設定 Redirect URI（最重要！）",
     '在 <strong>Redirect URIs</strong> 欄位填入下面這個網址，必須<strong>一字不差</strong>'
     '（點右上角圖示可一鍵複製）：'),
)

_BYOK_STEPS_TAIL = (
    ("#9B59B6", "4", "☑️", "勾選 Web API",
     '在 <strong>Which API/SDKs are you planning to use?</strong> 區塊，'
     '勾選 <strong>Web API</strong>，然後儲存。'),
    ("#00D4AA", "5", "🔑", "複製 Client ID 和 Client Secret",
     '建立完成後，在 App 的 Settings 頁面就能看到 '
     '<strong>Client ID</strong> 和 <strong>Client Secret</strong>，複製後貼到下方欄位。'),
)


def _byok_step_rows(steps, *, last_has_border: bool = True) -> str:
    rows = ""
    for i, (color, num, icon, title, desc) in enumerate(steps):
        last = i == len(steps) - 1
        border = "none" if (last and not last_has_border) else f"2px dashed {color}33"
        rows += f"""
<div style="display:flex;gap:12px;align-items:flex-start;padding:12px 0;
  border-bottom:{border}">
  <div style="flex-shrink:0;width:36px;height:36px;border-radius:50%;
    background:{color};border:2.5px solid #2D1B4E;
    display:flex;align-items:center;justify-content:center;
    font-family:'Nunito',sans-serif;font-weight:900;font-size:1rem;color:#2D1B4E;
    box-shadow:2px 2px 0 #2D1B4E">{num}</div>
  <div style="flex:1;min-width:0">
    <div style="font-family:'Nunito','Noto Sans TC',sans-serif;font-weight:900;
      font-size:0.95rem;color:#2D1B4E;margin-bottom:4px">{title}</div>
    <div style="font-family:'Nunito','Noto Sans TC',sans-serif;font-size:0.87rem;
      color:#444;line-height:1.6">{desc}</div>
  </div>
</div>"""
    return rows


def byok_spotify_steps_head_html() -> str:
    """步驟卡上半：標題 + 步驟 1–3。後面緊接著 app.py 的 st.code(redirect_uri)。"""
    return f"""
<div class="y2k-byok-card y2k-byok-head">
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
  {_byok_step_rows(_BYOK_STEPS_HEAD, last_has_border=False)}
</div>"""


def byok_spotify_steps_tail_html() -> str:
    """步驟卡下半：步驟 4–5。接在 st.code(redirect_uri) 之後。"""
    return f"""
<div class="y2k-byok-card y2k-byok-tail">
  {_byok_step_rows(_BYOK_STEPS_TAIL, last_has_border=False)}
</div>"""


def byok_privacy_badge_html() -> str:
    return f"""
<div style="display:flex;align-items:center;gap:8px;padding:10px 14px;
  border-radius:12px;background:#F0FFF8;margin:8px 0 4px 0">
  <span style="display:inline-block;width:22px;flex:0 0 auto">{SVG_LOCK}</span>
  <span style="font-family:'Nunito','Noto Sans TC',sans-serif;font-size:0.83rem;
    color:#2D1B4E;line-height:1.5">
    你填的 Keys 僅存在<strong>瀏覽器分頁記憶體</strong>中，關閉分頁即消失，不會被儲存下來。
  </span>
</div>"""


# ── Inject ────────────────────────────────────────────────

def inject_global_css():
    st.markdown(f"<style>{_build_global_css()}</style>", unsafe_allow_html=True)
