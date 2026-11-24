"""纯 Python 版的 ``grpcio`` 桩,用于绕过 Smart App Control 拦截 ``cygrpc``.

背景:
    ``qdrant-client`` 1.16 即使只用 HTTP(REST)传输,也会在包导入时无条件
    ``from qdrant_client import grpc`` → ``import grpc`` → ``grpc._cython.cygrpc``
    (未签名的 11MB 原生扩展)。本机 SAC 处于强制模式,会时不时间歇性拦截
    ``cygrpc.cp312-win_amd64.pyd``,报:

        ImportError: DLL load failed while importing cygrpc: 应用程序控制策略已阻止此文件。

    本项目的 Qdrant 访问全部走 REST(``AsyncQdrantClient(url=...)``,
    ``prefer_grpc`` 默认 False),并不需要真正的 gRPC 传输。

做法:
    ``.venv/Lib/site-packages/sac_grpc_shim.pth`` 在解释器启动时 import 本模块。
    本模块只在 ``sys.meta_path`` 最前面挂一个 finder,拦截顶级 ``grpc`` 的导入:
    - 真实扩展能加载 → 原样放行,本模块完全不介入,零运行时开销;
    - 加载时抛 ImportError(被 SAC 拦截)→ 用一个纯 Python 桩模块接管,
      满足 qdrant-client 导入期需要的 API 面(拦截器基类、Compression、
      StatusCode 等),任何真正使用 gRPC 传输的调用都会抛出明确异常。

    如果哪天关闭了 SAC,真正的扩展能加载,这里会自动让路,无需改动。

注意: 重建 venv(删除 .venv)后需要重新创建那个 .pth 文件。
"""

from __future__ import annotations

import importlib.machinery
import sys
import types
from enum import Enum

__all__ = ["install"]

# SAC/WDAC 拦截原生扩展时可能出现的报错特征
_BLOCK_MARKERS = (
    "DLL load failed",
    "WinError 4551",
    "应用程序控制策略",
    "Application Control",
)


def _looks_like_blocked_native(exc: BaseException) -> bool:
    message = str(exc)
    return isinstance(exc, ImportError) and any(m in message for m in _BLOCK_MARKERS)


class _StatusCode(Enum):
    OK = 0
    CANCELLED = 1
    UNKNOWN = 2
    INVALID_ARGUMENT = 3
    DEADLINE_EXCEEDED = 4
    NOT_FOUND = 5
    ALREADY_EXISTS = 6
    PERMISSION_DENIED = 7
    RESOURCE_EXHAUSTED = 8
    FAILED_PRECONDITION = 9
    ABORTED = 10
    OUT_OF_RANGE = 11
    UNIMPLEMENTED = 12
    INTERNAL = 13
    UNAVAILABLE = 14
    DATA_LOSS = 15
    UNAUTHENTICATED = 16


class _Compression(Enum):
    NoCompression = 0
    Deflate = 1
    Gzip = 2


def _unavailable(*_args, **_kwargs):
    raise RuntimeError(
        "gRPC transport is unavailable: the grpcio native extension (cygrpc) "
        "is blocked by Windows Smart App Control. This project uses the Qdrant "
        "HTTP transport (prefer_grpc=False), so gRPC functionality is not needed."
    )


class _Missing:
    """未知属性的占位类:可作为基类/类型注解使用,实例化时才报错。"""

    def __init__(self, *_args, **_kwargs):
        _unavailable()


class _RpcError(Exception):
    pass


class _AioRpcError(_RpcError):
    def code(self):
        return _StatusCode.UNKNOWN


class _Channel:
    pass


class _ClientCallDetails:
    pass


class _ServerInterceptor:
    pass


# 必须是彼此独立的类:qdrant_client.connection 里的拦截器同时继承这四个基类
class _UnaryUnaryInterceptor:
    pass


class _UnaryStreamInterceptor:
    pass


class _StreamUnaryInterceptor:
    pass


class _StreamStreamInterceptor:
    pass


_INTERCEPTORS = {
    "UnaryUnaryClientInterceptor": _UnaryUnaryInterceptor,
    "UnaryStreamClientInterceptor": _UnaryStreamInterceptor,
    "StreamUnaryClientInterceptor": _StreamUnaryInterceptor,
    "StreamStreamClientInterceptor": _StreamStreamInterceptor,
}


def _stub_attributes() -> dict:
    aio = types.ModuleType("grpc.aio")
    for name, cls in _INTERCEPTORS.items():
        setattr(aio, name, cls)
    aio.ServerInterceptor = _ServerInterceptor
    aio.Channel = _Channel
    aio.ClientCallDetails = _ClientCallDetails
    aio.AioRpcError = _AioRpcError
    aio.RpcError = _RpcError
    aio.insecure_channel = _unavailable
    aio.secure_channel = _unavailable
    aio.__getattr__ = _aio_missing  # PEP 562

    return {
        **_INTERCEPTORS,
        "__version__": "0.0.0+sac-stub",
        "_sac_fallback": True,
        "StatusCode": _StatusCode,
        "Compression": _Compression,
        "Channel": _Channel,
        "ClientCallDetails": _ClientCallDetails,
        "ServerInterceptor": _ServerInterceptor,
        "RpcError": _RpcError,
        "RpcContext": _Missing,
        "Call": _Missing,
        "insecure_channel": _unavailable,
        "secure_channel": _unavailable,
        "unary_unary_rpc_method_handler": _unavailable,
        "unary_stream_rpc_method_handler": _unavailable,
        "stream_unary_rpc_method_handler": _unavailable,
        "stream_stream_rpc_method_handler": _unavailable,
        "method_handlers_generic_handler": _unavailable,
        "experimental": types.SimpleNamespace(),
        "aio": aio,
    }


def _aio_missing(name: str):
    if name.startswith("__"):
        raise AttributeError(name)
    return _Missing


def _missing(name: str):
    """模块级 PEP 562 兜底:返回占位类,实例化/调用时抛出明确异常。"""
    if name.startswith("__"):
        raise AttributeError(name)
    return _Missing


def _install_stub(module: types.ModuleType) -> None:
    # 清掉真实 grpc 导入失败时留下的残缺子模块
    for name in [n for n in sys.modules if n == "grpc" or n.startswith("grpc.")]:
        sys.modules.pop(name, None)

    attributes = _stub_attributes()
    aio = attributes.pop("aio")
    module.__dict__.update(attributes)
    module.__dict__["__getattr__"] = _missing
    sys.modules["grpc"] = module
    sys.modules["grpc.aio"] = aio
    aio.__package__ = "grpc"
    aio.__spec__ = importlib.machinery.ModuleSpec("grpc.aio", None, is_package=True)
    setattr(module, "aio", aio)


class _FallbackLoader:
    """先执行真实的 grpc 包;只有原生扩展被 SAC 拦截时才换成纯 Python 桩。"""

    def __init__(self, real_loader):
        self._real = real_loader

    def create_module(self, spec):
        create = getattr(self._real, "create_module", None)
        if create is None:
            return None
        return create(spec)

    def exec_module(self, module):
        try:
            self._real.exec_module(module)
        except ImportError as exc:
            if not _looks_like_blocked_native(exc):
                raise
            _install_stub(module)


class _Finder:
    def find_spec(self, fullname, path=None, target=None):
        # 只接管顶级 grpc(子模块由真正的包/桩模块自行处理)
        if fullname != "grpc" or path is not None:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return None
        spec.loader = _FallbackLoader(spec.loader)
        return spec


def install() -> None:
    if not any(isinstance(finder, _Finder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _Finder())


install()
