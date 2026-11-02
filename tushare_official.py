"""官方 Tushare 客户端：实例专用 IPv4 连接池，保留域名和 TLS 校验。"""
from __future__ import annotations

import socket

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from tushare.pro.client import DataApi
from urllib3.connection import HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NameResolutionError, NewConnectionError
from urllib3.util.connection import create_connection

OFFICIAL_URL = "https://api.tushare.pro"


class _IPv4HTTPSConnection(HTTPSConnection):
    def _new_conn(self):
        """只筛选本连接的 IPv4 地址，TLS 仍使用原始 hostname/SNI。"""
        try:
            addresses = socket.getaddrinfo(
                self._dns_host, self.port, socket.AF_INET, socket.SOCK_STREAM
            )
            last_error = OSError("No IPv4 addresses returned")
            for _, _, _, _, address in addresses:
                try:
                    return create_connection(
                        (address[0], self.port), self.timeout,
                        source_address=self.source_address, socket_options=self.socket_options,
                    )
                except OSError as error:
                    last_error = error
            raise last_error
        except socket.gaierror as error:
            raise NameResolutionError(self.host, self, error) from error
        except socket.timeout as error:
            raise ConnectTimeoutError(self, "Official Tushare IPv4 connection timed out") from error
        except OSError as error:
            raise NewConnectionError(self, f"IPv4 connection failed: {error}") from error


class _IPv4HTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _IPv4HTTPSConnection


class _IPv4Adapter(HTTPAdapter):
    @staticmethod
    def _configure(manager):
        # urllib3 的默认映射是共享对象；复制后只改本 adapter 的 manager。
        manager.pool_classes_by_scheme = dict(manager.pool_classes_by_scheme)
        manager.pool_classes_by_scheme["https"] = _IPv4HTTPSPool

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        super().init_poolmanager(connections, maxsize, block=block, **kwargs)
        self._configure(self.poolmanager)

    def proxy_manager_for(self, proxy, **kwargs):
        manager = super().proxy_manager_for(proxy, **kwargs)
        self._configure(manager)
        return manager


class OfficialTushareClient(DataApi):
    """兼容 SDK 动态接口及 pro_bar(api=client)，不修改 SDK 或全局解析。"""

    def __init__(self, token, timeout=30):
        super().__init__(token, timeout=timeout)
        self._DataApi__http_url = OFFICIAL_URL
        self._session = requests.Session()
        self._session.mount(OFFICIAL_URL + "/", _IPv4Adapter())

    def query(self, api_name, fields="", **kwargs):
        """按官方根协议请求；HTTP/API 失败抛错，成功空表保留服务端字段。"""
        response = self._session.post(
            OFFICIAL_URL,
            json={"api_name": api_name, "token": self._DataApi__token,
                  "params": kwargs, "fields": fields},
            timeout=self._DataApi__timeout,
        )
        response.raise_for_status()
        result = response.json()
        if result["code"] != 0:
            raise RuntimeError(result["msg"])
        return pd.DataFrame(result["data"]["items"], columns=result["data"]["fields"])

    def close(self):
        """释放该客户端自己的连接池。"""
        self._session.close()
