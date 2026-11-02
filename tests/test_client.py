"""官方通道连接隔离、错误语义及实际 SDK 组合回归。"""
import socket
from types import SimpleNamespace

import pandas as pd
import pytest
import requests
import tushare as ts
from urllib3 import PoolManager
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NameResolutionError, NewConnectionError
from urllib3.util import connection as util_connection

import tushare_official as official


def test_adapter_is_owned_by_client_and_preserves_other_network_clients():
    resolver, allowed = socket.getaddrinfo, util_connection.allowed_gai_family
    shared = PoolManager().pool_classes_by_scheme
    first, second = official.OfficialTushareClient("test"), official.OfficialTushareClient("test")
    try:
        adapter = first._session.get_adapter(official.OFFICIAL_URL + "/")
        assert adapter.poolmanager.pool_classes_by_scheme is not shared
        assert shared["https"] is HTTPSConnectionPool
        assert adapter.poolmanager.pool_classes_by_scheme["https"] is official._IPv4HTTPSPool
        assert first._session is not second._session
        assert first._session.get_adapter("https://example.invalid/").poolmanager.pool_classes_by_scheme["https"] is HTTPSConnectionPool
        assert requests.Session().get_adapter(official.OFFICIAL_URL).poolmanager.pool_classes_by_scheme["https"] is HTTPSConnectionPool
        assert socket.getaddrinfo is resolver
        assert util_connection.allowed_gai_family is allowed
        assert first._session.verify is True
        manager = adapter.proxy_manager_for("http://localhost:9999")
        assert manager.pool_classes_by_scheme["https"] is official._IPv4HTTPSPool
        assert shared["https"] is HTTPSConnectionPool
    finally:
        first.close(); second.close()


def test_connection_uses_ipv4_without_replacing_tls_hostname(monkeypatch):
    seen = []
    def resolve(host, port, family, kind):
        assert (host, port, family, kind) == ("api.tushare.pro", 443, socket.AF_INET, socket.SOCK_STREAM)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.2", 443))]
    sentinel = object()
    def connect(address, timeout, **kwargs):
        seen.append((address, timeout, kwargs))
        if address[0] == "192.0.2.1":
            raise OSError("first address unavailable")
        return sentinel
    monkeypatch.setattr(official.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(official, "create_connection", connect)
    conn = official._IPv4HTTPSConnection("api.tushare.pro", timeout=3)
    assert conn._new_conn() is sentinel
    assert [x[0][0] for x in seen] == ["192.0.2.1", "192.0.2.2"]
    assert conn.host == conn._dns_host == "api.tushare.pro"
    assert seen[-1][1] == 3
    assert seen[-1][2]["socket_options"] == conn.socket_options


@pytest.mark.parametrize("error,expected", [
    (socket.gaierror("DNS unavailable"), NameResolutionError),
    (socket.timeout("connect timed out"), ConnectTimeoutError),
    (OSError("refused"), NewConnectionError),
])
def test_connection_failures_remain_transport_errors(monkeypatch, error, expected):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(official.socket, "getaddrinfo", fail)
    with pytest.raises(expected):
        official._IPv4HTTPSConnection("api.tushare.pro", timeout=1)._new_conn()




def test_query_uses_official_root_and_keeps_empty_schema(monkeypatch):
    client = official.OfficialTushareClient("test", timeout=7)
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {"code": 0, "data": {"fields": ["ts_code"], "items": []}})
    monkeypatch.setattr(client._session, "post", post)
    try:
        client._DataApi__http_url = "http://example.invalid"
        frame = client.fund_div(ts_code="510300.SH", fields="ts_code")
        assert frame.empty and list(frame.columns) == ["ts_code"]
        assert calls == [(official.OFFICIAL_URL, {"json": {"api_name": "fund_div", "token": "test",
                        "params": {"ts_code": "510300.SH"}, "fields": "ts_code"}, "timeout": 7})]
    finally:
        client.close()


@pytest.mark.parametrize("failure", ["http", "api", "malformed"])
def test_query_errors_are_never_silently_empty(monkeypatch, failure):
    client = official.OfficialTushareClient("test")
    def http_status():
        if failure == "http":
            raise requests.HTTPError("503")
    payload = {"code": 40203, "msg": "rate limited"} if failure == "api" else {}
    monkeypatch.setattr(client._session, "post", lambda *a, **kw: SimpleNamespace(
        raise_for_status=http_status, json=lambda: payload))
    try:
        with pytest.raises((requests.HTTPError, RuntimeError, KeyError)):
            client.trade_cal()
    finally:
        client.close()


@pytest.mark.parametrize("adjustment", [None, "qfq"])
def test_real_sdk_pro_bar_accepts_official_client(monkeypatch, adjustment):
    client = official.OfficialTushareClient("test")
    daily = pd.DataFrame({"ts_code": ["000001.SZ"] * 3,
        "trade_date": ["20250106", "20250103", "20250102"],
        "open": [10., 9., 8.], "high": [11., 10., 9.], "low": [9., 8., 7.],
        "close": [10., 9., 8.], "pre_close": [9., 8., 7.], "change": [1.] * 3,
        "pct_chg": [11., 12., 14.], "vol": [100.] * 3, "amount": [1000.] * 3})
    def post(url, **kwargs):
        api = kwargs["json"]["api_name"]
        if api == "daily":
            frame = daily
        elif api == "adj_factor":
            frame = daily[["ts_code", "trade_date"]].assign(adj_factor=[2., 1., 1.])
        else:
            raise AssertionError(api)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            "code": 0, "data": {"fields": list(frame.columns), "items": frame.values.tolist()}})
    monkeypatch.setattr(client._session, "post", post)
    try:
        frame = ts.pro_bar(api=client, ts_code="000001.SZ", start_date="20250102", end_date="20250106", adj=adjustment)
        assert frame is not None and len(frame) == 3
        assert frame.iloc[0]["close"] == 10.
        assert frame.iloc[-1]["close"] == (4. if adjustment else 8.)
    finally:
        client.close()
