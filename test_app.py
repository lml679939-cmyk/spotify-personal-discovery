"""app.py 內 context helper 的單元測試。

執行：python -m pytest test_app.py -q

⚠️ 本檔 import app，而 app.py 有 module-level 的 Streamlit 程式碼——import 會把登入頁
渲染一遍（實測約 5 秒，不發網路請求）。所以這裡只放**非放不可**的東西：
純邏輯請放 recommend.py + test_recommend.py，那邊 import 是即時的。
"""

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
    ("spotify-lml.streamlit.app", False),
    ("", False),
])
def test_is_local_dev_reads_host_header(monkeypatch, host, expected):
    monkeypatch.setattr(app.st, "context", _FakeContext({"Host": host}))
    assert app._is_local_dev() is expected
