"""纯 Python 版的 ``uuid_utils._uuid_utils``,用于绕过 Smart App Control 拦截.

背景:
    langchain-core 1.7.6 在 ``langchain_core/utils/uuid.py`` 里无条件下
    ``from uuid_utils.compat import uuid7``,而 ``uuid_utils`` 只提供 Rust 编译的
    ``_uuid_utils.pyd``(无签名)。本机 SAC 处于强制模式,会拦截未签名的原生扩展
    (日志: CodeIntegrity 3033/3077/3118),导致 import langchain 直接失败。

做法:
    ``.venv/Lib/site-packages/sac_uuid_utils_shim.pth`` 在解释器启动时 import 本模块。
    本模块先尝试加载真正的 ``uuid_utils._uuid_utils``;只有在它加载失败时才把一份
    纯 Python 实现注册到 ``sys.modules["uuid_utils._uuid_utils"]``。
    这样 ``uuid_utils`` 包自身的纯 Python 代码(``__init__.py`` / ``compat``)照常工作,
    langchain / langsmith / pydantic_extra_types 都能正常 import。

    如果哪天关闭了 SAC,真正的扩展能加载,这里会自动让路,无需改动。

注意: 重建 venv(删除 .venv)后需要重新创建那个 .pth 文件。
"""

from __future__ import annotations

import os as _os
import random as _random
import sys as _sys
import threading as _threading
import time as _time
import types as _types
import uuid as _uuid

# --------------------------------------------------------------------------- #
# 常量,与 uuid_utils 顶层 API 保持一致
# --------------------------------------------------------------------------- #
UUID = _uuid.UUID
NIL = _uuid.UUID(int=0)
MAX = _uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")

NAMESPACE_DNS = _uuid.NAMESPACE_DNS
NAMESPACE_OID = _uuid.NAMESPACE_OID
NAMESPACE_URL = _uuid.NAMESPACE_URL
NAMESPACE_X500 = _uuid.NAMESPACE_X500

RESERVED_NCS = _uuid.RESERVED_NCS
RFC_4122 = _uuid.RFC_4122
RESERVED_MICROSOFT = _uuid.RESERVED_MICROSOFT
RESERVED_FUTURE = _uuid.RESERVED_FUTURE

getnode = _uuid.getnode

try:  # 尽量和已安装的 uuid_utils 版本号保持一致
    from importlib.metadata import version as _dist_version

    __version__ = _dist_version("uuid-utils")
except Exception:  # pragma: no cover - 包没装时走这里
    __version__ = "0.0.0+pure"

# --------------------------------------------------------------------------- #
# v1 / v3 / v4 / v5 / v8
# --------------------------------------------------------------------------- #


def uuid1(node=None, clock_seq=None):
    return _uuid.uuid1(node, clock_seq)


def uuid3(namespace, name):
    return _uuid.uuid3(namespace, name)


def uuid4():
    return _uuid.uuid4()


def uuid5(namespace, name):
    return _uuid.uuid5(namespace, name)


def uuid8(data):
    """用调用方给出的字节生成 v8 UUID(截断/补零到 16 字节,然后写入版本位)。"""
    raw = bytes(data)
    if len(raw) > 16:
        raise ValueError("expected at most 16 bytes")
    buf = bytearray(raw.ljust(16, b"\x00"))
    buf[6] = (buf[6] & 0x0F) | 0x80  # version = 8
    buf[8] = (buf[8] & 0x3F) | 0x80  # variant = RFC 4122
    return _uuid.UUID(bytes=bytes(buf))


# --------------------------------------------------------------------------- #
# v6 / v7(本地实现,RFC 9562)
# --------------------------------------------------------------------------- #
_UUID_EPOCH_100NS = 0x01B21DD213814000  # 1582-10-15 到 1970-01-01 的 100ns 数

_MASK48 = (1 << 48) - 1
_COUNTER_BITS = 42
_COUNTER_MAX = (1 << (_COUNTER_BITS - 1)) - 1  # MSB 恒为 0
_COUNTER_MASK = (1 << _COUNTER_BITS) - 1

_LOCK = _threading.Lock()
_LAST_MS = -1
_COUNTER = 0


def _to_ns(timestamp, nanos):
    """timestamp=None 表示当前时间;timestamp 是秒(可为 float),nanos 是秒内纳秒。"""
    if timestamp is None:
        return _time.time_ns()
    if nanos is None:
        if isinstance(timestamp, float):
            return int(timestamp * 1_000_000_000)
        return int(timestamp) * 1_000_000_000
    return int(timestamp) * 1_000_000_000 + int(nanos)


def _uuid7_int(timestamp=None, nanos=None):
    """返回 v7 UUID 的 128 位整数。

    同一毫秒内递增 42 位计数器(RFC 9562 §6.2 Method 1),保证单进程内单调递增。
    显式传入 timestamp 时不参与全局单调状态,避免历史时间戳污染后续调用。
    """
    global _LAST_MS, _COUNTER

    ns = _to_ns(timestamp, nanos)
    ms = ns // 1_000_000

    with _LOCK:
        if timestamp is not None:
            counter = _random.getrandbits(_COUNTER_BITS - 1)
        elif _LAST_MS < ms:
            _LAST_MS = ms
            _COUNTER = _random.getrandbits(_COUNTER_BITS - 1)
            counter = _COUNTER
        else:
            # 时钟没走或回拨:沿用上次的毫秒,计数器 +1
            ms = _LAST_MS
            _COUNTER += 1
            if _COUNTER > _COUNTER_MAX:
                _LAST_MS += 1
                ms = _LAST_MS
                _COUNTER = _random.getrandbits(_COUNTER_BITS - 1)
            counter = _COUNTER
        rand_b = _random.getrandbits(32)

    value = (ms & _MASK48) << 80
    value |= 0x7 << 76                      # version 7
    value |= ((counter >> 30) & 0xFFF) << 64  # rand_a = counter 高 12 位
    value |= 0b10 << 62                      # variant
    value |= (counter & ((1 << 30) - 1)) << 32  # rand_b = counter 低 30 位 + 随机 32 位
    value |= rand_b
    return value


def uuid7(timestamp=None, nanos=None):
    return _uuid.UUID(int=_uuid7_int(timestamp, nanos))


def uuid6(node=None, timestamp=None):
    ns = _to_ns(timestamp, None)
    ts = ((ns // 100) + _UUID_EPOCH_100NS) & ((1 << 60) - 1)  # 100ns 精度的 60 位时间戳
    clock_seq = _random.getrandbits(14)
    if node is None:
        node = _uuid.getnode()
    node &= _MASK48

    value = (ts >> 28) << 96                  # time_high
    value |= ((ts >> 12) & 0xFFFF) << 80      # time_mid
    value |= 0x6 << 76                        # version 6
    value |= (ts & 0xFFF) << 64               # time_low
    value |= 0b10 << 62                       # variant
    value |= (clock_seq & 0x3FFF) << 48
    value |= node
    return _uuid.UUID(int=value)


# --------------------------------------------------------------------------- #
# 内部辅助函数,compat 模块会用到
# --------------------------------------------------------------------------- #


def _uuid4_int():
    return _uuid.uuid4().int


def reseed():
    """子进程 fork 后重置 RNG;纯 Python 实现里 random 自带 urandom 播种,这里补一刀。"""
    _random.seed(_os.urandom(16))


# --------------------------------------------------------------------------- #
# 注册:只有真正的扩展加载失败时才接管
# --------------------------------------------------------------------------- #
_EXPORTS = {
    "UUID": UUID,
    "NIL": NIL,
    "MAX": MAX,
    "NAMESPACE_DNS": NAMESPACE_DNS,
    "NAMESPACE_OID": NAMESPACE_OID,
    "NAMESPACE_URL": NAMESPACE_URL,
    "NAMESPACE_X500": NAMESPACE_X500,
    "RESERVED_NCS": RESERVED_NCS,
    "RFC_4122": RFC_4122,
    "RESERVED_MICROSOFT": RESERVED_MICROSOFT,
    "RESERVED_FUTURE": RESERVED_FUTURE,
    "getnode": getnode,
    "__version__": __version__,
    "uuid1": uuid1,
    "uuid3": uuid3,
    "uuid4": uuid4,
    "uuid5": uuid5,
    "uuid6": uuid6,
    "uuid7": uuid7,
    "uuid8": uuid8,
    "_uuid4_int": _uuid4_int,
    "_uuid7_int": _uuid7_int,
    "reseed": reseed,
}


def _install():
    try:
        import uuid_utils._uuid_utils  # noqa: F401

        return False  # 原生扩展可用,完全不介入
    except Exception:
        pass

    module = _types.ModuleType("uuid_utils._uuid_utils")
    module.__dict__.update(_EXPORTS)
    module.__doc__ = "Pure-Python fallback for the SAC-blocked uuid_utils Rust extension."
    _sys.modules["uuid_utils._uuid_utils"] = module
    return True


_USING_FALLBACK = _install()

if not _USING_FALLBACK:
    # 真正的扩展可用,把模块残留清理掉,保持环境干净
    del _EXPORTS
