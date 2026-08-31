"""app.py 內 context helper 的單元測試。

執行：python -m pytest test_app.py -q

⚠️ 本檔 import app，而 app.py 有 module-level 的 Streamlit 程式碼——import 會把登入頁
渲染一遍（實測約 5 秒，不發網路請求）。所以這裡只放**非放不可**的東西：
純邏輯請放 recommend.py + test_recommend.py，那邊 import 是即時的。
"""

import pathlib

import pytest

import app


class _FakeContext:
    def __init__(self, headers):
        self.headers = headers


@pytest.fixture
def xff(monkeypatch):
    """把 X-Forwarded-For 換成指定值；傳 None 代表讀 header 會炸（無 script context）。"""
    def _set(value):
        if value is None:
            class _Boom:
                @property
                def headers(self):
                    raise RuntimeError("no script run context")
            monkeypatch.setattr(app.st, "context", _Boom())
        else:
            monkeypatch.setattr(app.st, "context", _FakeContext({"X-Forwarded-For": value}))
    return _set


def test_real_public_ip_is_used(xff):
    xff("8.8.8.8")
    assert app._client_ip() == "8.8.8.8"


def test_leftmost_hop_is_taken_from_a_proxy_chain(xff):
    # 代理鏈是「使用者, proxy1, proxy2」，最左邊那個才是使用者自己
    xff("8.8.8.8, 70.41.3.18, 150.172.238.178")
    assert app._client_ip() == "8.8.8.8"


def test_ipv6_is_accepted_and_normalised(xff):
    xff("2606:4700:4700:0000:0000:0000:0000:1111")
    assert app._client_ip() == "2606:4700:4700::1111"


@pytest.mark.parametrize("hostile", [
    "../../admin",                      # 路徑穿越
    "'; DROP TABLE x--",
    "evil.example/x",                   # 想換掉查詢目標
    "8.8.8.8 OR 1=1",
    "<script>alert(1)</script>",
    "%0d%0aX-Injected: 1",              # CRLF
    "not-an-ip",
    "",
])
def test_non_ip_values_are_rejected(xff, hostile):
    """這個值會被拼進 https://ipwho.is/{ip} 的路徑。host 改不掉（不是 SSRF），
    但沒驗證的話任意字串都會被送進網址——一律要求解析得出 IP 才採用。"""
    xff(hostile)
    assert app._client_ip() == ""


@pytest.mark.parametrize("local", [
    "127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.1.1", "::1",
    # ⚠️ RFC 文件保留範圍在 Python 3.12+ 也算 private，寫測試時很容易踩到
    "203.0.113.7", "198.51.100.1", "192.0.2.1", "2001:db8::1",
])
def test_non_global_addresses_are_skipped(xff, local):
    # 查不到有意義的地理資訊（本機開發就是這種），省下一個請求
    xff(local)
    assert app._client_ip() == ""


def test_missing_header_or_no_context_is_blank(xff, monkeypatch):
    xff(None)
    assert app._client_ip() == ""
    monkeypatch.setattr(app.st, "context", _FakeContext({}))
    assert app._client_ip() == ""


def test_only_validated_ip_can_reach_the_geo_url(monkeypatch):
    """端到端：不管 header 塞什麼，實際送出的網址永遠是 ipwho.is 這個 host。"""
    seen = []

    class _Resp:
        ok = False
        headers = {}

    def _fake_get(url, *a, **kw):
        seen.append(url)
        return _Resp()

    monkeypatch.setattr(app.requests, "get", _fake_get)

    app._geo_weather_blocking("8.8.8.8")
    assert seen == ["https://ipwho.is/8.8.8.8"]


def test_no_client_ip_means_no_geo_request_at_all(monkeypatch):
    """驗不過 / 拿不到 IP 時**完全不發請求**。

    以前會打不帶 IP 的 `https://ipwho.is`，那等於叫對方定位「發請求的這台機器」——
    也就是雲端伺服器。實測使用者在台北卻顯示「The Dalles, United States｜08:27（清晨）」，
    時刻判斷跟著全錯。回退到 DEFAULT_TZ_OFFSET 至少時間是對的。
    """
    seen = []
    monkeypatch.setattr(app.requests, "get", lambda url, *a, **kw: seen.append(url))

    value, tz = app._geo_weather_blocking("")
    assert seen == [], "沒有可用的使用者 IP 就不該發任何請求"
    assert value == ""
    assert tz == app.DEFAULT_TZ_OFFSET


@pytest.mark.parametrize("mins,expected", [
    (-480, 28800),    # 台北 UTC+8：JS 回報「落後 -480 分」
    (0, 0),           # UTC+0——⚠️ 不能用 `or` 判斷，0 是 falsy
    (300, -18000),    # 紐約 UTC-5
    (None, None),
    ("-480", None),   # 型別不對就當拿不到
    (True, None),     # bool 是 int 的子類別，要擋掉
])
def test_browser_tz_offset_converts_minutes_behind_to_seconds_ahead(monkeypatch, mins, expected):
    class _Ctx:
        timezone_offset = mins
    monkeypatch.setattr(app.st, "context", _Ctx())
    assert app._browser_tz_offset() == expected


def test_browser_timezone_wins_over_ip(monkeypatch):
    """瀏覽器時區優先：雲端拿不到 client IP，而且使用者掛 VPN 時 IP 的時區是錯的。"""
    class _Ctx:
        timezone_offset = -480
    monkeypatch.setattr(app.st, "context", _Ctx())
    state = {}
    monkeypatch.setattr(app.st, "session_state", state)
    app.sync_browser_timezone()
    assert state["geo_tz_offset"] == 28800


def test_local_dev_may_still_geolocate_itself(monkeypatch):
    """本機開發是唯一例外：伺服器就是開發者自己的機器，定位自己才是對的。

    不開這個例外的話，本機開發會完全看不到位置與天氣（雲端才需要擋）。
    """
    seen = []

    class _Resp:
        ok = False
        headers = {}

    monkeypatch.setattr(app.requests, "get", lambda url, *a, **kw: (seen.append(url), _Resp())[1])
    app._geo_weather_blocking("", allow_self_lookup=True)
    assert seen == ["https://ipwho.is"], "本機開發要允許不帶 IP 的自我定位"


@pytest.mark.parametrize("host,expected", [
    ("127.0.0.1:8501", True),
    ("localhost:8599", True),
    ("::1", True),
    ("soundcurator.streamlit.app", False),
    ("", False),
])
def test_is_local_dev_reads_host_header(monkeypatch, host, expected):
    monkeypatch.setattr(app.st, "context", _FakeContext({"Host": host}))
    assert app._is_local_dev() is expected


# ── 投射問題的洗牌輪替 ────────────────────────────────────
def test_projective_pool_is_expanded_and_unique():
    assert len(app.PROJECTIVE_QUESTIONS) >= 30
    assert len(set(app.PROJECTIVE_QUESTIONS)) == len(app.PROJECTIVE_QUESTIONS)


def test_projective_rotation_covers_whole_pool_without_repeat():
    # 一輪剛好每題各出現一次——random.choice 的舊版做不到這件事
    seen, order, cur = [], [], None
    for _ in range(len(app.PROJECTIVE_QUESTIONS)):
        cur, order = app._rotate_projective(order, cur)
        seen.append(cur)
    assert sorted(seen) == sorted(app.PROJECTIVE_QUESTIONS)


def test_projective_reshuffle_guard_when_first_equals_current(monkeypatch):
    # 跨輪邊界：重洗出來的第一題剛好撞上當前題時，要移到隊尾（不能連兩題相同）
    pool = app.PROJECTIVE_QUESTIONS
    monkeypatch.setattr(app.random, "sample", lambda p, k: list(p))  # 「洗」出原順序
    nxt, rest = app._rotate_projective([], current=pool[0])
    assert nxt == pool[1]        # 撞題的第一題被跳過
    assert rest[-1] == pool[0]   # 移到隊尾，本輪最後才會再出現


# ── 節流訊息（HIGH-2 全站閘門）────────────────────────────
def test_human_wait_never_prints_raw_seconds_for_long_waits():
    """全站日窗的等待是小時級，照秒印會變成「請等 41231 秒」＝看起來像壞了。"""
    assert app._human_wait(20) == "20 秒"
    assert "秒" not in app._human_wait(600)          # 10 分鐘
    assert "小時" in app._human_wait(41231)


def test_rate_limit_warning_says_something_different_for_each_cause():
    """四種原因對使用者的下一步完全不同，訊息不能共用一句。"""
    msgs = {
        why: app._rate_limit_warning(why, 3600)
        for why in ("global_day", "global_hour", "daily", "cooldown")
    }
    assert len(set(msgs.values())) == 4
    assert "明天" in msgs["global_day"]              # 今天沒救了 → 明天再來
    assert "人比較多" in msgs["global_hour"]          # 等一下就好
    assert "24 小時" in msgs["daily"]                # 自己的額度會慢慢回來


# ── 訪客匿名代號的驗證（MED-5）────────────────────────────
# localStorage 的值完全由瀏覽器端控制，是本站少數跨越信任邊界的輸入之一。
# 元件端的 JS 也驗一次，但那只是自我修復——攻擊者可以完全繞過我們的 JS，
# 所以 Python 這一關才是真正的邊界。

_GOOD_UUID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
_TAMPERED = [
    "",
    "lqk2j3-a8f7d2b1",                           # 舊版 Date.now()+Math.random() 的格式
    "3F2504E0-4F89-41D3-9A0C-0305E82C3301",      # 大寫：同一個 id 會算出兩把 user_key
    "3f2504e0-4f89-41d3-9a0c-0305e82c330",       # 少一碼
    "3f2504e04f8941d39a0c0305e82c3301",          # 沒有連字號
    _GOOD_UUID + chr(10) + "injected",                   # ⚠️ 尾端換行：用 $ 而非 \Z 就會放行
    "x" * 10_000,                                # 塞超長字串，每次 render 都往伺服器送
    {"not": "a string"},
    12345,
]


@pytest.fixture
def browser_id(monkeypatch):
    """把元件換成回傳指定值的假物件，跑一次 _resolve_browser_id()，回傳解析結果。"""
    app.st.session_state.pop("browser_id", None)

    def _resolve(value, *, raises=False):
        if raises:
            def _boom(**kw):
                raise RuntimeError("component died")
            monkeypatch.setattr(app, "_guest_id_component", _boom)
        else:
            monkeypatch.setattr(app, "_guest_id_component", lambda **kw: value)
        app._resolve_browser_id()
        return app._browser_id()

    yield _resolve
    app.st.session_state.pop("browser_id", None)


def test_resolve_keeps_pending_apart_from_unavailable(browser_id):
    """⚠️ 這個差別是 OAuth 綁定的關鍵：None＝再等一輪，unavailable＝直接判失敗。
    兩者混為一談的話，正常使用者會在首輪就被誤判成攻擊、登入永遠完不成。"""
    assert browser_id(None) is None, "元件還沒回傳＝pending，不能當成失敗"
    assert browser_id("unavailable") == app._BROWSER_ID_UNAVAILABLE


def test_resolve_accepts_a_canonical_uuid(browser_id):
    assert browser_id(_GOOD_UUID) == _GOOD_UUID
    assert app._guest_local_id() == _GOOD_UUID


@pytest.mark.parametrize("bad", _TAMPERED)
def test_resolve_treats_tampered_values_as_unavailable(browser_id, bad):
    """形式不對＝被竄改，當作這個瀏覽器給不了代號——不要拿去 HMAC，
    那等於讓人自訂身分命名空間。"""
    assert browser_id(bad) == app._BROWSER_ID_UNAVAILABLE
    assert app._guest_local_id() is None


def test_resolve_survives_a_broken_component(browser_id):
    assert browser_id(None, raises=True) == app._BROWSER_ID_UNAVAILABLE
    assert app._guest_local_id() is None


def test_pending_does_not_clobber_an_already_resolved_id(browser_id):
    """元件在後續 rerun 回 None 時，不能把已經解析好的代號洗掉——
    洗掉的話 OAuth 驗證會在來回途中失去綁定對象。"""
    assert browser_id(_GOOD_UUID) == _GOOD_UUID
    assert browser_id(None) == _GOOD_UUID


def test_guest_local_id_rejects_unavailable(browser_id):
    """拿不到代號時訪客降級成 session 級——**絕不退回固定字串**。"""
    browser_id("unavailable")
    assert app._guest_local_id() is None


def test_guest_id_component_generates_with_a_csprng():
    """⚠️ 別再退回 Date.now()／Math.random()——兩者都可預測，等於別人可以枚舉出
    訪客身分、讀到他的回饋與歷史。這個 id 就是訪客的身分憑證。

    註解裡刻意留著舊做法當教訓，所以先把整行註解剝掉再檢查（同 test_share_card
    當初改用 AST 的理由：子字串檢查會被說明文字誤中）。
    """
    src = (pathlib.Path(app._GUEST_ID_DIR) / "index.html").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("//"))
    assert "getRandomValues" in code, "沒有 CSPRNG 的產生路徑"
    assert "Math.random" not in code
    assert "Date.now" not in code


# ── 上傳圖片的檔頭嗅探（LOW-10）──────────────────────────
# file_uploader 的 type= 只比對副檔名、uploaded.type 是瀏覽器宣告的值，兩者都由
# 使用者控制。叫 x.png 但內容是 EPS/JPEG2000 的檔案照樣會被對應解碼器解析。

def test_sniff_reads_real_file_headers():
    """三種格式用 Pillow 真的產生，不是拿寫死的常數自我驗證。"""
    import io
    from PIL import Image
    for fmt, want in (("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")):
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (200, 60, 140)).save(buf, format=fmt)
        assert app._sniff_image_mime(buf.getvalue()) == want, fmt


@pytest.mark.parametrize("data, label", [
    (b"%!PS-Adobe-3.0 EPSF-3.0", "EPS"),                       # Pillow CVE 的來源之一
    (bytes([0, 0, 0, 12]) + b"jP  ", "JPEG2000"),              # 同上
    (b"GIF89a", "GIF"),
    (b"<svg xmlns=", "SVG"),
    (b"RIFF____NOPE", "RIFF 但不是 WEBP"),
    (b"", "空檔"),
    (bytes([0xFF, 0xD8]), "JPEG 檔頭只有一半"),
])
def test_sniff_rejects_anything_that_is_not_jpeg_png_webp(data, label):
    assert app._sniff_image_mime(data) is None, label
