# Tushare Official Client

一个很小的官方 Tushare Python 客户端，保留官方接口调用方式。
仅自己的 HTTPS 连接池使用 IPv4 并复用连接；不修改系统 DNS、Clash、socket 全局函数或其他 HTTP 客户端。

## 安装

```bash
pip install git+https://github.com/wujiancheng622/tushare-official-client.git
```

Python 3.11+。已有本地源码时也可 `pip install .`，或直接复用 `tushare_official.py`。

## 使用

Token 放在本地环境变量 `TUSHARE_OFFICIAL_TOKEN`，不要提交真实凭据。

```python
import os
import tushare as ts
from tushare_official import OfficialTushareClient

pro = OfficialTushareClient(os.environ["TUSHARE_OFFICIAL_TOKEN"])
try:
    daily = pro.daily(ts_code="000001.SZ", start_date="20261001", end_date="20261030")
    adjusted = ts.pro_bar(api=pro, ts_code="000001.SZ", start_date="20261001", end_date="20261030", adj="qfq")
finally:
    pro.close()
```

`fund_daily`、`fund_adj`、`trade_cal` 等仍按 Tushare 官方接口手册调用。
地址固定为 `https://api.tushare.pro`，不支持第三方数据代理，也不会自动切换数据源。
HTTP/API 失败抛错；成功空表保留服务端字段。默认超时30秒，`timeout=`可调整。
权限、限频、字段单位、分页和历史数据质量仍需依据官方文档与实际返回处理。

## 边界

- 一个客户端持有自己的 Session；多线程使用时每线程创建一个实例。
- 保留原始域名、TLS SNI 和证书校验，不固定服务器 IP。
- 普通 `ts.pro_api()` 创建的其他客户端不会自动获得此修复。
- IPv4 不可用时会报错，不自动回退 IPv6。
- 仅提供连接与官方协议访问；不包含采集调度、数据库、策略、QMT或8002服务。

## 测试

```bash
pip install -e '.[test]'
python -m pytest tests -q
```

测试覆盖连接隔离、HTTP/API错误、成功空表及真实SDK pro_bar接口组合；测试使用合成回包，不需要真实Token。
代码最初用于ETF采集器的官方连接修复，独立出来供其他策略复用。
