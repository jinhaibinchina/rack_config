"""OPC UA 通信层（asyncua 2.x 封装）。

与 ``common/com/snap7`` 的 ``PLCManager`` / ``DataBroker`` 职责对等，但接口
按 OPC UA 的习惯设计：

* **节点寻址**：用 NodeId 字符串（``ns=2;s=Channel1.Device1.Tag``）而不是
  DB 号 + 字节偏移；
* **订阅推送**：服务端变化才推，不在本地轮询。几十盏灯共用一条
  Subscription，比逐点 ``read`` 省得多；
* **断线重连交给 asyncua**：2.x 的 ``Client(auto_reconnect=True)`` 自带健康
  探测（watchdog）、指数退避和订阅重建，不需要像 snap7 那样手写重连线程。

对外只暴露**同步**接口（``read`` / ``write``），和 snap7 的 ``read_data`` /
``write_data`` 手感一致，业务层不用改成 asyncio 思维。内部把 asyncio 事件
循环放在独立的 daemon 线程里，用 ``run_coroutine_threadsafe().result()`` 桥接。

线程纪律
--------
* 所有 Signal 都从 worker 线程 emit，Qt 自动排队回主线程，安全；
* ``stop()`` 必须 join 线程后才允许本对象随宿主销毁。来不及退出时（多半卡在
  TCP 握手上），``keep_alive_until_stopped`` 会把它摘下来保活——和 snap7
  broker 那边同一个道理，否则 worker 醒来摸已释放的 QObject 就是段错误。

日志
----
asyncua 在「传输层已断、正在重连」的窗口里每秒撞一次 ``ConnectionError`` 并
打一整段 traceback：PLC 掉电十分钟就是六百段栈，控制台直接没法看。
``install_quiet_reconnect()``（构造函数里自动调用）按**异常类型**把这类记录
滤掉——连上期间的同类异常、以及 ServiceFault / 结构体解析失败等真问题照旧
打出来。要排查重连细节时设环境变量 ``OPCUA_LOG_NOISE=1``。

反过来，``Reconnect attempt failed: TimeoutError()`` 只给四个字、看不出卡在
哪一步；设 ``OPCUA_DEBUG_RECONNECT=1`` 会把每次重连失败的完整异常栈写到
``opcua_reconnect_trace.log``，并把 asyncua 的 DEBUG 日志写到
``opcua_reconnect.log``（GUI 也可加 ``--debug-reconnect``）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any, Mapping

from PySide6.QtCore import QObject, Signal

try:
    from asyncua import Client, ua
    from asyncua.client.ua_client import UaClientState
except ImportError as exc:  # pragma: no cover - 依赖缺失时的明确提示
    raise ImportError(
        "OPC UA 通信需要 asyncua，安装：.venv/Scripts/python.exe -m pip install asyncua"
    ) from exc

from .structure import (
    StructField,
    StructValue,
    StructureReader,
    is_builtin_datatype,
    is_struct_value,
)


# 轮询线程还没停、但已经不能随宿主销毁的 manager（见 keep_alive_until_stopped）
_ORPHANS: list = []

#: OPC UA Part 3 规定 AccessLevel 是 Byte **位掩码**：
#: CurrentRead=0x01, CurrentWrite=0x02, HistoryRead=0x04, ...
#:
#: 注意：**不能用 ``ua.AccessLevel.CurrentWrite``**。asyncua 把这套位标志生成成了
#: 普通 IntEnum（CurrentRead=0, CurrentWrite=1, HistoryWrite=3），值是**位序号**
#: 而不是掩码，拿它做 & 运算永远为真——只读节点也会被判成可写。
ACCESS_WRITE_BIT = 0x02


def is_writable(access: Any) -> bool:
    """判断 AccessLevel / UserAccessLevel 里有没有写权限。"""
    if access is None:
        return False
    try:
        return bool(int(access) & ACCESS_WRITE_BIT)
    except (TypeError, ValueError):
        return False


#: 标准命名空间（ns=0）里的内建类型/服务子树，浏览时应当剪掉——里面有几千个
#: 类型定义节点，翻不动，也没有现场关心。
#:
#: **只能按名字剪，不能按 `namespace == 0` 一刀切**。真实 PLC 的地址空间是混合
#: 命名空间的，S7-1500 典型结构是::
#:
#:     Objects(ns=0) -> DeviceSet(ns=0) -> S7-1500(ns=0/1)
#:         -> DataBlocksGlobal(ns=1) -> "DB_Rack"(ns=3) -> 变量(ns=3)
#:
#: 中间几层容器全是 ns=0。按命名空间剪枝会在第 1 层就把整棵树砍断，变量一个
#: 都扫不到（实测：depth=8 时变量 0 个、目录 4 个）。所以容器一律递归，只有
#: 下面这几个内建子树才跳过。
STANDARD_SUBTREES = frozenset(
    {
        "Server",
        "ServerInterfaces",
        "TypeHierarchy",
        "DataTypes",
        "EventTypes",
        "VariableTypes",
        "ObjectTypes",
        "ReferenceTypes",
        "Views",
    }
)


def is_standard_subtree(name: str, namespace: int) -> bool:
    """是不是 ns=0 的内建类型/服务子树（这种才该剪掉）。"""
    return namespace == 0 and name in STANDARD_SUBTREES


#: asyncua 在「传输层已断、supervisor 正在重连」的窗口里，publish 循环仍会
#: 每秒发一次请求、每秒撞一次 ``ConnectionError``，并用 ``logger.exception``
#: 打一整段 traceback。现场 PLC 掉电十分钟就是六百段栈，控制台没法看。
#:
#: 这类记录只在**传输层已经死掉**时才是纯噪声；连上时同样的异常是真问题，
#: 必须照旧打出来。所以按异常类型过滤，不按消息文本一刀切。
_NOISE_MESSAGES = frozenset(
    {
        "Publish iteration crashed; retrying in 1s",
        "Connection supervisor iteration crashed; retrying in 1s",
        # 掉线时关窗口：CloseSession / CloseSecureChannel 没人应答，asyncua
        # 在 disconnect() 里也是整段 traceback。同样只在传输层已死时发生。
        "close_session raised during disconnect; continuing teardown",
        "close_secure_channel raised during disconnect; continuing teardown",
    }
)

#: 固定文案、**没有异常**的协商/清理日志。asyncua 把这类 info 写成了 warning：
#: 会话失效后的 CloseSession / CloseSecureChannel 清理、以及服务器把发布间隔
#: 从 200ms 改成 1000ms 之类的参数协商。它们不代表故障，连上后照样会打一次，
#: 现场看着像报错。
_PLAIN_NOISE_MESSAGES = frozenset(
    {
        "close_session but connection wasn't established",
        "close_secure_channel was called but connection is closed",
    }
)
_PLAIN_NOISE_PREFIXES = (
    "Revised values returned differ from subscription values:",
    "Requested session timeout to be",
)

#: 传输层症状。``TimeoutError`` 也算：握手/CloseSession 等到超时，本质和
#: ``ConnectionError`` 一样，不是业务错误。
_NOISE_EXCEPTIONS = (ConnectionError, TimeoutError)

#: 会打这些记录的 logger（都是 asyncua 自己的）。
#:
#: 注意 publish 循环用的是**实例 logger** ``...ua_session.UaSession`` 而不是
#: 模块 logger：asyncua 在 ``UaSession.__init__`` 里才 ``getLogger``，那会儿
#: 我们早就装完了。``logging.getLogger`` 对同名 logger 是全局单例，所以这里
#: 提前把名字建出来挂过滤器，后面它取到的是同一个对象。
_NOISE_LOGGERS = (
    "asyncua.client.ua_session",
    "asyncua.client.ua_session.UaSession",
    "asyncua.client.client",
    "asyncua.client.ua_client.UaClient",
)

#: 过滤器打在这几个 logger 上的标记，用来保证幂等
_QUIET_FLAG = "_opcua_quiet"


class _ReconnectNoiseFilter(logging.Filter):
    """丢掉断线窗口里的预期日志，保留所有真错误。

    * 带 traceback 的：只丢固定文案 + 异常是 ``ConnectionError`` /
      ``TimeoutError``（传输层症状）；ServiceFault、结构体解析失败、用户回调
      异常等全部原样放行。
    * 不带异常的：只丢上面列明的协商/清理 warning。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 - 过滤本身出错绝不能吞掉日志
            return True
        exc = record.exc_info[1] if record.exc_info else None
        if msg in _NOISE_MESSAGES and isinstance(exc, _NOISE_EXCEPTIONS):
            return False
        if exc is None:
            if msg in _PLAIN_NOISE_MESSAGES or msg.startswith(_PLAIN_NOISE_PREFIXES):
                return False
        return True


def install_quiet_reconnect() -> None:
    """给 asyncua 的 logger 挂上断线噪声过滤器（幂等）。

    排查重连细节时可设环境变量 ``OPCUA_LOG_NOISE=1`` 关掉过滤。

    过滤器挂在 **logger** 上而不是 handler 上：``Logger.handle`` 里先跑
    filters、再进 handler，所以不管宿主有没有配 logging、配了几个 handler，
    都能拦住。
    """
    if os.environ.get("OPCUA_LOG_NOISE", "").strip() not in ("", "0"):
        return
    for name in _NOISE_LOGGERS:
        logger = logging.getLogger(name)
        if any(getattr(f, _QUIET_FLAG, False) for f in logger.filters):
            continue
        flt = _ReconnectNoiseFilter()
        setattr(flt, _QUIET_FLAG, True)
        logger.addFilter(flt)


#: 诊断输出（只在 OPCUA_DEBUG_RECONNECT=1 时产生）
_RECONNECT_LOG_PATH = os.path.join(os.getcwd(), "opcua_reconnect.log")
_RECONNECT_TRACE_PATH = os.path.join(os.getcwd(), "opcua_reconnect_trace.log")
_TRACE_FLAG = "_opcua_trace"
_TRACE_LOCK = threading.Lock()


class _ReconnectTraceFilter(logging.Filter):
    """把 ``Reconnect attempt failed: TimeoutError()`` 的完整栈捞出来。

    asyncua 打这条时用的是 ``_logger.warning("...%r...", exc, delay)``，
    **没有 exc_info**，所以控制台只有 ``TimeoutError()`` 四个字，看不出是卡在
    Hello / OpenSecureChannel / ActivateSession 哪一步。``record.args`` 里的
    异常对象还挂着 ``__traceback__``，这里落盘供现场排查。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not str(record.msg).startswith("Reconnect attempt failed:"):
            return True
        for arg in record.args or ():
            if not isinstance(arg, BaseException) or arg.__traceback__ is None:
                continue
            stack = "".join(
                traceback.format_exception(type(arg), arg, arg.__traceback__)
            )
            with _TRACE_LOCK, open(_RECONNECT_TRACE_PATH, "a", encoding="utf-8") as fp:
                fp.write(
                    f"{time.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"{type(arg).__name__}: {arg}\n{stack}\n"
                )
        return True


def install_reconnect_diagnostics() -> str:
    """开启重连诊断（``OPCUA_DEBUG_RECONNECT=1``），返回栈文件路径；未开启返回空串。

    幂等。产出两个文件：``opcua_reconnect.log``（asyncua 全量 DEBUG）和
    ``opcua_reconnect_trace.log``（每次重连失败的异常栈）。
    """
    if os.environ.get("OPCUA_DEBUG_RECONNECT", "").strip() in ("", "0"):
        return ""
    client_log = logging.getLogger("asyncua.client.client")
    if not any(getattr(f, _TRACE_FLAG, False) for f in client_log.filters):
        flt = _ReconnectTraceFilter()
        setattr(flt, _TRACE_FLAG, True)
        client_log.addFilter(flt)
    root = logging.getLogger("asyncua")
    if not any(getattr(h, _TRACE_FLAG, False) for h in root.handlers):
        handler = logging.FileHandler(_RECONNECT_LOG_PATH, encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        setattr(handler, _TRACE_FLAG, True)
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
    return _RECONNECT_TRACE_PATH


def _unwrap(val: Any) -> Any:
    """把 Variant / DataValue 剥成 Python 原生值。

    asyncua 的 ``datachange_notification`` 通常已经剥好了，但不同版本、不同
    服务端下偶尔仍会给回包装对象，这里统一兜一层。
    """
    if isinstance(val, ua.DataValue):
        inner = val.Value
        return inner.Value if isinstance(inner, ua.Variant) else inner
    if isinstance(val, ua.Variant):
        return val.Value
    return val


def _coerce(value: Any, vtype: ua.VariantType) -> Any:
    """按节点的实际 VariantType 收敛 Python 值。

    直接写 ``True`` 到 Int16 节点、或写 ``1`` 到 Boolean 节点，服务端会回
    ``BadTypeMismatch``。OPC UA 的写入类型必须和节点 DataType 对得上。
    """
    if vtype == ua.VariantType.Boolean:
        return bool(value)
    if vtype in (
        ua.VariantType.SByte,
        ua.VariantType.Byte,
        ua.VariantType.Int16,
        ua.VariantType.UInt16,
        ua.VariantType.Int32,
        ua.VariantType.UInt32,
        ua.VariantType.Int64,
        ua.VariantType.UInt64,
    ):
        return int(value)
    if vtype in (ua.VariantType.Float, ua.VariantType.Double):
        return float(value)
    if vtype == ua.VariantType.String:
        return str(value)
    return value


async def _cancel_publish_loop(client: Client) -> None:
    """收掉 asyncua 的 publish 常驻任务。

    ``UaSession.close_session()`` 只在「协议还在」时才 cancel 它；断线之后
    ``client.disconnect()`` 会走提前 return 的分支，任务就漏了下来。
    """
    try:
        task = client.uaclient._publish_task  # asyncua 2.1 的只读属性
    except Exception:  # noqa: BLE001 - 换版本拿不到就算了，不要卡住 stop
        return
    if task is None or task.done():
        return
    task.cancel()
    try:
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=1.0)
    except Exception:  # noqa: BLE001 - 超时也继续，别阻塞停机
        pass


@dataclass(frozen=True)
class OpcConfig:
    """连接参数。字段名尽量贴着 asyncua，方便对照文档。"""

    endpoint: str = "opc.tcp://127.0.0.1:4840"
    #: 账号密码。S7-1500 的 OPC UA Server 默认不允许匿名访问；留空则匿名。
    user: str = ""
    password: str = ""
    #: asyncua 底层**每个请求**等待应答的秒数，握手（Hello / OpenSecureChannel /
    #: CreateSession / ActivateSession）也用它。真机 PLC 忙时 4s 会把重连握手
    #: 直接掐成 TimeoutError，然后无限退避。默认放宽到 10s。
    timeout: float = 10.0
    #: UI 线程同步 read / write / browse 的桥接上限（秒）。和上面分开：界面不该
    #: 被一个慢请求卡十几秒，但后台重连握手需要更长的余量。
    operation_timeout: float = 5.0
    #: 健康探测周期（秒）。**同时也是探测的超时**：asyncua 内部写死
    #: ``probe_timeout = min(revised_session_timeout/2, watchdog_intervall)``，
    #: 我们传 1.0 就等于每秒读一次 ServerState 且只等 1 秒，真机偶发卡顿会
    #: 被误判成掉线、白白触发重连。服务器把会话超时压到 30s 时更明显。
    watchdog_interval: float = 5.0
    #: 订阅的发布间隔（毫秒）。S7-1500 的最小发布间隔常是 1000ms，请求 200ms
    #: 会被改成 1000 并额外触发一次 ModifySubscription 往返；直接按 1000 请求。
    publish_period_ms: int = 1000
    #: 断线重连的最大退避（秒）。
    reconnect_max_delay: float = 30.0


class _ChangeHandler:
    """订阅回调。asyncua 只按鸭子类型调用，不必继承 SubscriptionHandler。"""

    __slots__ = ("_owner",)

    def __init__(self, owner: "OpcUaManager") -> None:
        self._owner = owner

    def datachange_notification(self, node, val, data) -> None:
        self._owner._on_datachange(node, val)

    def status_change_notification(self, status) -> None:
        # 订阅被服务端撤销 / 转移时会走到这里
        try:
            text = getattr(status, "Status", None)
            name = getattr(getattr(text, "Name", None), "name", None) or str(text)
            self._owner.state_message.emit(f"订阅状态变化: {name}")
        except Exception:  # noqa: BLE001 - 回调里绝不能抛回 asyncua
            pass


class OpcUaManager(QObject):
    """OPC UA 客户端。一个实例对应一个 endpoint。"""

    connected_changed = Signal(bool)
    """连接状态变化（初次连上、断线、重连成功都会发）。"""

    state_message = Signal(str)
    """人可读的状态说明，适合丢进日志框。"""

    node_changed = Signal(str, object)
    """(key, value) —— 订阅到的节点值变化。"""

    node_error = Signal(str, str)
    """(key, 错误说明) —— 单点读写失败。"""

    def __init__(self, config: OpcConfig | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # 连上之前就把日志过滤器装好：_bootstrap 的第一轮失败也会走 asyncua
        # 的 logger，晚装就漏掉了。
        install_quiet_reconnect()
        self._trace_path = install_reconnect_diagnostics()
        self._cfg = config or OpcConfig()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: Client | None = None
        self._subscription = None

        self._alive = threading.Event()          # 线程存活
        self._stopping = threading.Event()       # 主动停机中
        self._lock = threading.Lock()            # 保护下面的字典

        self._desired: dict[str, str] = {}       # key -> node_id 字符串
        self._subscribed: dict[str, str] = {}    # 已成功订阅的 key -> node_id
        self._nodeid_key: dict[str, str] = {}    # nodeid.to_string() -> key
        self._nodes: dict[str, Any] = {}         # node_id -> Node
        self._vtypes: dict[str, ua.VariantType] = {}
        self._reader: StructureReader | None = None  # 结构体展开（带定义缓存）
        self._last_connected: bool = False
        self._tasks: list[asyncio.Task] = []     # 后台常驻任务，stop 时要取消

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def configure(self, config: OpcConfig) -> bool:
        """更新连接参数（端点 / 账号 / 周期）。只在未连接时生效。

        返回 False 表示当前正在连接，参数没变——调用方应先 ``stop()``。
        界面工具改端点走这里，不去摸 ``_cfg``。
        """
        if self._thread is not None and self._thread.is_alive():
            return False
        self._cfg = config
        return True

    def start(self) -> None:
        """启动后台事件循环并异步连接。**不阻塞**，连接结果走信号。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopping.clear()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop_main, name="OpcUaClient", daemon=True
        )
        self._thread.start()

    def _loop_main(self) -> None:
        loop = self._loop
        assert loop is not None
        asyncio.set_event_loop(loop)
        self._alive.set()
        self._tasks = [
            loop.create_task(self._state_watcher()),
            loop.create_task(self._bootstrap()),
        ]
        try:
            loop.run_forever()
        finally:
            try:
                loop.close()
            except Exception:  # noqa: BLE001
                pass
            self._alive.clear()

    async def _bootstrap(self) -> None:
        """首次连接。失败就退避重试——现场常见「先开软件、后给 PLC 上电」。

        asyncua 的 auto_reconnect 只在**首次连接成功之后**才接管；连不上时
        它不管，所以这里必须自己退避。
        """
        delay = 1.0
        while not self._stopping.is_set():
            try:
                await self._connect_async()
                return
            except Exception as exc:  # noqa: BLE001
                self._emit(
                    self.state_message,
                    f"连接失败: {type(exc).__name__}: {exc or '（无消息）'}"
                    f"（{delay:.0f}s 后重试）",
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 10.0)

    async def _connect_async(self) -> None:
        client = Client(
            url=self._cfg.endpoint,
            timeout=self._cfg.timeout,
            watchdog_intervall=self._cfg.watchdog_interval,
            auto_reconnect=True,
            reconnect_max_delay=self._cfg.reconnect_max_delay,
        )
        if self._cfg.user:
            client.set_user(self._cfg.user)
            client.set_password(self._cfg.password)
        await client.connect()
        if self._stopping.is_set():
            await client.disconnect()
            return
        # 断线立即上报：watcher 最慢要等一个轮询周期，而 UI 上"灯还绿着但
        # 数据已经不动了"比灯晚亮更难受。恢复走 watcher（asyncua 没有
        # "重连成功"回调）。
        client.connection_lost_callback = self._on_connection_lost
        self._client = client
        # 结构体定义缓存按连接作废：DataTypeDefinition 是服务端的地址空间内容，
        # 换了设备（重连到另一台 PLC）就不能再用旧定义去解 Body。
        self._reader = StructureReader(client)
        await self._apply_subscription()
        self._emit(self.state_message, f"已连接 {self._cfg.endpoint}")

    async def _on_connection_lost(self, exc: BaseException) -> None:
        if not self._last_connected:
            return
        self._last_connected = False
        self._emit(self.connected_changed, False)
        # 带上异常类名：TimeoutError() 这种空消息，不写类名就完全看不出
        # 是「健康探测超时误判」还是「TCP 真的断了」。
        self._emit(
            self.state_message,
            f"连接中断: {type(exc).__name__}: {exc or '（无消息）'}，正在自动重连…",
        )

    async def _state_watcher(self) -> None:
        """周期检查底层状态，把「连上 / 断开 / 重连成功」统一转成信号。

        asyncua 没有「重连成功」回调，靠轮询 state 最省事，也顺带兜住各种
        边界（服务端主动踢、watchdog 判定假死等）。
        """
        while not self._stopping.is_set():
            connected = self._query_connected()
            if connected != self._last_connected:
                self._last_connected = connected
                self._emit(self.connected_changed, connected)
                self._emit(
                    self.state_message,
                    "连接已建立" if connected else "连接已断开，正在自动重连…",
                )
            await asyncio.sleep(0.2)

    def _query_connected(self) -> bool:
        client = self._client
        if client is None:
            return False
        try:
            return client.state is UaClientState.CONNECTED
        except Exception:  # noqa: BLE001
            return False

    def is_connected(self) -> bool:
        return self._query_connected()

    @property
    def reconnect_trace_path(self) -> str:
        """重连异常栈文件路径；未开启 ``OPCUA_DEBUG_RECONNECT`` 时为空串。"""
        return self._trace_path

    def stop(self, wait_ms: int = 3000) -> bool:
        """断开并停掉后台线程。返回线程是否真的结束了。

        返回 False 表示等超时了（多半卡在 TCP 握手/断开上）：调用方**不能**
        让本对象随宿主销毁，应改用 :func:`keep_alive_until_stopped`。
        """
        self._stopping.set()
        loop = self._loop
        thread = self._thread
        if loop is None or thread is None:
            return True
        if thread.is_alive():
            try:
                fut = asyncio.run_coroutine_threadsafe(self._shutdown_async(), loop)
                fut.result(timeout=max(0.1, wait_ms / 1000.0 / 2))
            except Exception:  # noqa: BLE001 - 超时/已关闭都直接往下停 loop
                pass
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass
        thread.join(timeout=max(0.1, wait_ms / 1000.0))
        alive = thread.is_alive()
        if not alive:
            self._thread = None
            self._loop = None
            self._subscription = None
            self._reader = None
            # 订阅记录跟着这次连接一起作废：不清的话再次 start() 会认为
            # "已经订阅过"，跳过 _apply_subscription，新连接永远收不到推送。
            # （_desired 要保留——那是用户声明的意图，重连后还得按它订阅。）
            with self._lock:
                self._subscribed.clear()
                self._nodeid_key.clear()
                self._nodes.clear()
                self._vtypes.clear()
            self._last_connected = False
        return not alive

    async def _shutdown_async(self) -> None:
        try:
            if self._subscription is not None:
                await self._subscription.delete()
        except Exception:  # noqa: BLE001
            pass
        self._subscription = None
        # 先取消常驻任务：不取消的话 loop.stop() 之后它们仍挂起，
        # 解释器退出时会打 "Task was destroyed but it is pending!"。
        pending = [t for t in self._tasks if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks = []
        client, self._client = self._client, None
        if client is not None:
            # 断线途中 stop 的话，asyncua 的 close_session() 会因为「协议已经没了」
            # 提前 return，**跳过取消 publish 任务**那一步；任务留着就会在
            # loop.stop() 之后一直 pending，解释器退出时打
            # "Task was destroyed but it is pending!"。这里先手动收掉。
            await _cancel_publish_loop(client)
            try:
                await asyncio.wait_for(client.disconnect(), timeout=1.5)
            except Exception:  # noqa: BLE001
                pass
        self._last_connected = False

    # ------------------------------------------------------------------
    # 订阅
    # ------------------------------------------------------------------
    def subscribe(self, items: Mapping[str, str]) -> None:
        """声明要订阅的节点。``items`` 是 ``{业务 key: NodeId 字符串}``。

        可以在 :meth:`start` 之前调用（先配置、后连接是常态），连接建立时
        会自动补上；连接期间追加会增量订阅，不影响已有条目。

        例::

            mgr.subscribe({
                "lamp01": "ns=2;s=Rack.Lamp01",
                "count":  "ns=2;s=Rack.FullCount",
            })
        """
        with self._lock:
            self._desired.update(items)
        self._run(self._apply_subscription())

    def unsubscribe_all(self) -> None:
        with self._lock:
            self._desired.clear()
        self._run(self._reset_subscription())

    async def _reset_subscription(self) -> None:
        if self._subscription is not None:
            try:
                await self._subscription.delete()
            except Exception:  # noqa: BLE001
                pass
        self._subscription = None
        with self._lock:
            self._subscribed.clear()
            self._nodeid_key.clear()

    async def _apply_subscription(self) -> None:
        client = self._client
        if client is None:
            return
        with self._lock:
            pending = {k: v for k, v in self._desired.items() if k not in self._subscribed}
        if not pending:
            return
        if self._subscription is None:
            self._subscription = await client.create_subscription(
                self._cfg.publish_period_ms, _ChangeHandler(self)
            )
            self._emit(self.state_message, f"建立订阅（{self._cfg.publish_period_ms}ms）")
        nodes = []
        pairs = []
        for key, node_id in pending.items():
            node = self._node_of(node_id)
            nodes.append(node)
            pairs.append((key, node))
        await self._subscription.subscribe_data_change(nodes)
        with self._lock:
            for key, node in pairs:
                self._subscribed[key] = pending[key]
                self._nodeid_key[node.nodeid.to_string()] = key
        self._emit(self.state_message, f"已订阅 {len(pairs)} 个节点")

    def _on_datachange(self, node, val) -> None:
        try:
            nid = node.nodeid.to_string()
        except Exception:  # noqa: BLE001
            return
        with self._lock:
            key = self._nodeid_key.get(nid)
        if key is None:
            return
        self._emit(self.node_changed, key, _unwrap(val))

    # ------------------------------------------------------------------
    # 同步读写（给 UI 线程用，和 snap7 的 read_data / write_data 对等）
    # ------------------------------------------------------------------
    def read(self, key: str, timeout: float | None = None) -> Any:
        """读一个节点。失败返回 None（不抛，和 snap7 那边一致）。"""
        try:
            return self._run(self._read_async(key), timeout)
        except Exception as exc:  # noqa: BLE001
            self._emit(self.node_error, key, f"读取失败: {exc}")
            return None

    def write(self, key: str, value: Any, timeout: float | None = None) -> bool:
        """写一个节点，按节点 DataType 自动收敛 Variant 类型。"""
        try:
            return bool(self._run(self._write_async(key, value), timeout))
        except Exception as exc:  # noqa: BLE001
            self._emit(self.node_error, key, f"写入失败: {exc}")
            return False

    def node_type(self, node_id: str, timeout: float = 5.0) -> str:
        """查节点的数据类型名（``Boolean`` / ``Int16`` / ``String``…）。

        浏览树时不读这个——每个变量一次往返，展开大 DB 会慢到没法用。
        只在用户选中某个节点时按需查。
        """
        try:
            return self._run(self._node_type_async(node_id), timeout) or ""
        except Exception:  # noqa: BLE001
            return ""

    async def _node_type_async(self, node_id: str) -> str:
        node = self._node_of(node_id)
        vtype = await node.read_data_type_as_variant_type()
        return vtype.name

    def read_many(self, keys: list[str], timeout: float | None = None) -> dict[str, Any]:
        """批量读，返回 ``{key: value}``（失败的键不出现在结果里）。"""
        out: dict[str, Any] = {}
        for key in keys:
            val = self.read(key, timeout)
            if val is not None:
                out[key] = val
        return out

    async def _read_async(self, key: str) -> Any:
        node = self._node_for_key(key)
        dv = await node.read_data_value()
        inner = dv.Value
        if isinstance(inner, ua.Variant):
            with self._lock:
                self._vtypes[key] = inner.VariantType
            return inner.Value
        return inner

    async def _write_async(self, key: str, value: Any) -> bool:
        node = self._node_for_key(key)
        with self._lock:
            vtype = self._vtypes.get(key)
        if vtype is None:
            vtype = await node.read_data_type_as_variant_type()
            with self._lock:
                self._vtypes[key] = vtype
        await node.write_value(_coerce(value, vtype), vtype)
        return True

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _node_of(self, node_id: str):
        """按 NodeId 字符串拿 Node（带缓存，Node 只是句柄不占连接）。"""
        with self._lock:
            node = self._nodes.get(node_id)
        if node is not None:
            return node
        client = self._client
        if client is None:
            raise RuntimeError("未连接")
        node = client.get_node(node_id)
        with self._lock:
            self._nodes[node_id] = node
        return node

    def _node_for_key(self, key: str) -> Any:
        """key 优先按订阅清单解析；不在清单里就当成 NodeId 字符串直接用。

        这样临时点读一个没订阅的节点不用先 ``subscribe``。
        """
        with self._lock:
            node_id = self._desired.get(key, key)
        return self._node_of(node_id)

    def _run(self, coro, timeout: float | None = None):
        """在后台 loop 上跑协程并等结果。loop 没起时安全返回 None。"""
        loop = self._loop
        if loop is None or not self._alive.is_set() or self._stopping.is_set():
            coro.close()
            return None
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout if timeout is not None else self._cfg.operation_timeout)

    def _emit(self, signal, *args) -> None:
        """从 worker 线程发信号。宿主已析构时静默丢弃。"""
        try:
            signal.emit(*args)
        except (RuntimeError, ReferenceError):
            pass

    # ------------------------------------------------------------------
    # 地址空间浏览（给节点选择器 / 调试工具用）
    # ------------------------------------------------------------------
    def browse_children(self, node_id: str = "", timeout: float = 15.0) -> list[dict]:
        """列出某个节点的直接子节点，``node_id`` 传空表示从 ``Objects`` 根开始。

        返回::

            [{"node_id": "ns=2;s=Lamp01", "name": "Lamp01",
              "node_class": "Variable", "value": False,
              "writable": True, "has_children": False}, ...]

        展开一个目录只发 **四个** 请求：``get_children_descriptions``（拿
        name / NodeId / NodeClass）+ 三次批量 ``read_attributes``（值 / 两级
        权限）。逐个 ``read_value`` 的话，S7-1500 上一个几百变量的 DB 要跑
        几十秒——这是能不能做成顺手的浏览器的分水岭。
        """
        try:
            return self._run(self._browse_async(node_id), timeout) or []
        except Exception as exc:  # noqa: BLE001
            self._emit(self.node_error, node_id, f"浏览失败: {exc}")
            return []

    async def _browse_async(self, node_id: str) -> list[dict]:
        client = self._client
        if client is None:
            raise RuntimeError("未连接")
        node = client.nodes.objects if not node_id else self._node_of(node_id)
        refs = await node.get_children_descriptions()
        if not refs and node_id:
            # 变量展开走这里。服务端把结构体成员挂成子节点（Siemens 就是这样）时
            # 上面已经拿到 refs，返回真节点；只给整包 ExtensionObject 的服务端
            # 则退回按 DataTypeDefinition 解码。两条路对调用方是同一个接口。
            return await self._struct_children(node, node_id)

        out: list[dict] = []
        variables: list[ua.NodeId] = []
        by_id: dict[str, dict] = {}
        for ref in refs:
            try:
                cls = int(ref.NodeClass)
                name = ref.BrowseName.Name
                nid = ref.NodeId
            except Exception:  # noqa: BLE001
                continue
            is_var = cls == int(ua.NodeClass.Variable)
            key = nid.to_string()
            item = {
                "node_id": key,
                "name": name,
                "namespace": int(nid.NamespaceIndex),
                "node_class": ua.NodeClass(cls).name,
                "value": None,
                "writable": False,
                # 变量下面一般只挂 EngineeringUnits 这类 Property，不展开，
                # 否则树里全是噪音
                "has_children": not is_var,
            }
            out.append(item)
            by_id[key] = item
            if is_var:
                variables.append(nid)

        if variables:
            await self._fill_variable_meta(variables, by_id)
        return out

    async def _fill_variable_meta(
        self, node_ids: list[ua.NodeId], by_id: dict[str, dict]
    ) -> None:
        """批量补上变量的当前值和读写权限。失败就只丢值，树结构照常显示。"""
        client = self._client
        if client is None:
            return
        chunk = 400  # 服务端单次读有上限，切块更稳
        for start in range(0, len(node_ids), chunk):
            part = node_ids[start : start + chunk]
            try:
                values = await client.uaclient.read_attributes(part, ua.AttributeIds.Value)
                access = await client.uaclient.read_attributes(
                    part, ua.AttributeIds.AccessLevel
                )
                user_access = await client.uaclient.read_attributes(
                    part, ua.AttributeIds.UserAccessLevel
                )
            except Exception:  # noqa: BLE001
                continue
            for nid, dv, al, ual in zip(part, values, access, user_access):
                item = by_id.get(nid.to_string())
                if item is None:
                    continue
                try:
                    if dv.StatusCode.is_good():
                        item["value"] = _unwrap(dv)
                except Exception:  # noqa: BLE001
                    pass
                # 值是个 ExtensionObject 就说明是结构体：给它一个展开箭头，
                # 展开时先试真子节点、再退回解码（见 _browse_async）。
                if is_struct_value(item["value"]):
                    item["has_children"] = True
                    item["struct"] = True
                # 取交集：AccessLevel 是节点能力，UserAccessLevel 是本次会话
                # 权限，真实 PLC 上两者可能不同（节点可写但账号只给读）
                item["writable"] = is_writable(_unwrap(al.Value)) and is_writable(
                    _unwrap(ual.Value)
                )

    # ------------------------------------------------------------------
    # 结构体展开
    # ------------------------------------------------------------------
    def read_structure(self, node_id: str, timeout: float | None = None) -> dict:
        """把一个结构体变量展开成 ``{"type": ..., "fields": [...]}``。

        成员是**值快照**，不是节点：服务端没把成员暴露成子节点时，它们没有
        独立 NodeId，订阅不了也写不了。有真成员节点的设备请直接用
        ``browse_children``（能拿到真 NodeId 就一定优先用它）。

        字段树里 ``aggregate=True`` 的成员值在 ``children`` 里，``value`` 为 None。
        """
        try:
            result = self._run(self._read_structure_async(node_id), timeout)
        except Exception as exc:  # noqa: BLE001
            self._emit(self.node_error, node_id, f"结构体展开失败: {exc}")
            return {"type": "", "fields": [], "error": str(exc)}
        if result is None:
            return {"type": "", "fields": [], "error": "未连接"}
        return result.to_dict()

    async def _read_structure_async(self, node_id: str) -> StructValue:
        node = self._node_for_key(node_id)
        return await self._reader_or_new().read(node)

    async def _struct_children(self, node, node_id: str) -> list[dict]:
        """变量没有子节点时，按 DataTypeDefinition 把 Body 拆成成员列表。"""
        reader = self._reader_or_new()
        try:
            dt_id = await reader.datatype_of(node)
        except Exception:  # noqa: BLE001
            return []
        if is_builtin_datatype(dt_id):
            return []  # 普通标量变量，没什么可展开的
        result = await reader.read(node)
        if not result.fields:
            if result.error:
                self._emit(self.node_error, node_id, result.error)
            return []
        try:
            namespace = int(node.nodeid.NamespaceIndex)
        except Exception:  # noqa: BLE001
            namespace = 0
        return [self._struct_item(f, namespace) for f in result.fields]

    def _struct_item(self, f: StructField, namespace: int) -> dict:
        """把 ``StructField`` 转成和 ``browse_children`` 同构的字典。"""
        return {
            "node_id": "",
            "name": f.name,
            "namespace": namespace,
            "node_class": "Variable",
            "value": None if f.aggregate else f.value,
            "text": f.text(),
            "writable": False,
            "has_children": bool(f.children),
            "synthetic": True,
            "data_type": f.type_name,
            "value_rank": f.rank,
            "struct_error": f.error,
            "children": [self._struct_item(c, namespace) for c in f.children],
        }

    def _reader_or_new(self) -> StructureReader:
        reader = self._reader
        if reader is None:
            client = self._client
            if client is None:
                raise RuntimeError("未连接")
            reader = StructureReader(client)
            self._reader = reader
        return reader

    # ------------------------------------------------------------------
    # 诊断
    # ------------------------------------------------------------------
    def debug_state(self) -> dict:
        with self._lock:
            return {
                "endpoint": self._cfg.endpoint,
                "connected": self._query_connected(),
                "thread_alive": bool(self._thread and self._thread.is_alive()),
                "desired": dict(self._desired),
                "subscribed": dict(self._subscribed),
            }


def keep_alive_until_stopped(manager: "OpcUaManager") -> None:
    """把 manager 从宿主对象上摘下来保活，直到后台线程真正退出。

    与 ``snap7_data_broker.keep_alive_until_stopped`` 同一个理由：宿主窗口
    关闭时线程可能正卡在 TCP 握手上，来不及看到停止标志。这时一旦随窗口
    销毁，worker 醒来 emit 信号就是访问已释放的 C++ 对象——进程直接段错误。
    """
    try:
        manager.setParent(None)
    except RuntimeError:
        return
    if manager not in _ORPHANS:
        _ORPHANS.append(manager)


def _release_orphan(manager: "OpcUaManager") -> None:
    try:
        _ORPHANS.remove(manager)
    except ValueError:
        pass
