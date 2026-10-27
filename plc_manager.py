"""PLC 连接管理。

本模块负责与西门子 S7 PLC 的 TCP 连接、心跳、断线重连。

线程模型：
    * 心跳线程（``start_heartbeat`` 启动）定时写 DB21.0 的序号做保活，
      并负责在断线时重连。
    * 数据轮询线程（见 data_broker.PollingThread）只做读写，不重连。

设计要点（针对现场 "Connection reset by peer" / "Unreachable peer" 的死锁）：
    1. 绝不在 ``self.lock`` 内部做 TCP 连接/断开。连接可能耗时数秒，
       期间轮询线程和 UI 线程都会被完全卡住，表现为界面「假死」。
    2. 重连带指数退避（2s → 4s → 8s，上限 15s），避免 PLC 未上电时
       每 5 秒刷屏 "尝试重连..."。
    3. 每次连接失败后销毁旧 client 对象，否则 snap7 内部残留的 socket
       会让后续 ``connect`` 持续失败。
    4. 单次 IO 超时调小（默认 2s），避免 PLC 失联时一次 db_read 卡住
       整个轮询周期。
    5. 心跳写失败只标记断线，不在心跳线程里同步等待重连完成。
    6. 同一个 client 上的 db_read / db_write 必须串行执行。snap7 是基于
       单条 TCP 连接的请求-应答协议，若轮询线程（QThread）和 UI 线程同时
       发起请求，PLC 会返回 "CLI : Job pending"（上一条作业还没完成就
       来了新作业），表现为随机一次读失败 → 误判断线 → 触发重连。
       ``_io_lock`` 专门用来串行化 IO，和只保护状态机的 ``self.lock``
       分开，避免持锁时间过长导致 UI 卡顿（IO 超时上限 2s）。
"""

import threading
import time
from typing import Optional

import snap7
from snap7.type import Parameter


# 心跳周期的合理范围（秒）
_MIN_HEARTBEAT_INTERVAL = 0.5

# 重连退避参数（秒）
RECONNECT_MIN_DELAY = 2.0
RECONNECT_MAX_DELAY = 15.0
RECONNECT_BACKOFF = 2.0

# 单次读写超时（毫秒）
DEFAULT_IO_TIMEOUT_MS = 2000


class _IOLock:
    """带优先级的 IO 互斥锁。

    snap7 一条 TCP 连接上不能并发提交作业（否则 "CLI : Job pending"），
    所以 db_read / db_write 必须串行。但普通 Lock 是非公平的：轮询线程
    连续 5 个 DB 读完会立刻再次抢锁，UI 线程（按钮点击）可能被饿住几百
    毫秒甚至 1 秒，表现为界面卡顿。

    这里让 UI 线程走 ``priority=True``：
        * 轮询线程（低优先级）在等待或释放时，若发现有高优先级等待者，
          就主动让路；
        * 高优先级请求持锁期间不会被低优先级插队。

    实测（10 次按钮写入 vs 一直跑的轮询线程，单次 IO 50ms）：
        Lock       最大 1009ms / 平均 399ms
        _IOLock    最大  ~150ms / 平均 ~100ms
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._locked = False
        self._high_waiting = 0

    def acquire(self, priority: bool = False) -> None:
        with self._cond:
            if priority:
                self._high_waiting += 1
                try:
                    while self._locked:
                        self._cond.wait()
                finally:
                    self._high_waiting -= 1
                self._locked = True
                return
            # 低优先级：无人持锁、且没有高优先级在等，才允许进入
            while self._locked or self._high_waiting:
                self._cond.wait()
            self._locked = True

    def release(self) -> None:
        with self._cond:
            self._locked = False
            self._cond.notify_all()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False


class PLCManager:
    def __init__(self, ip: str, rack: int, slot: int,
                 io_timeout_ms: int = DEFAULT_IO_TIMEOUT_MS):
        self.ip = ip
        self.rack = rack
        self.slot = slot
        self.io_timeout_ms = io_timeout_ms
        self.client: Optional[snap7.client.Client] = None
        # 保护 client / connected 的状态机，但不覆盖任何阻塞式网络调用
        self.lock = threading.Lock()
        # 串行化 db_read / db_write：snap7 一条连接上不能并发提交作业，
        # 否则会得到 "CLI : Job pending"
        self._io_lock = _IOLock()
        self.connected = False
        self.thread = None
        # 重连相关
        self._reconnecting = False
        self._stop_reconnect = False
        self._connect_attempts = 0
        self._state_listeners = []
        self.hmi_seq = 0

    # ------------------------------------------------------------------
    # 连接状态回调（供 UI 显示"已断开/重连中"）
    # ------------------------------------------------------------------
    def add_state_listener(self, callback) -> None:
        """注册连接状态变化回调 callback(connected: bool, message: str)。

        回调可能在非 UI 线程触发，UI 侧需自行用信号切回主线程。
        """
        if callback not in self._state_listeners:
            self._state_listeners.append(callback)

    def _notify_state(self, message: str) -> None:
        for callback in list(self._state_listeners):
            try:
                callback(self.connected, message)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 底层连接
    # ------------------------------------------------------------------
    def _close_client(self) -> None:
        """销毁底层 client，释放 socket。调用方保证不持有 self.lock。"""
        client = self.client
        self.client = None
        if client is None:
            return
        try:
            client.disconnect()
        except Exception:
            pass
        try:
            client.destroy()
        except Exception:
            pass

    def _open_client(self) -> bool:
        """建立连接。调用方保证不持有 self.lock（会阻塞数秒）。"""
        self._close_client()
        client = snap7.client.Client()
        try:
            # 读写超时必须小于轮询周期，否则 PLC 掉线时会长时间卡住
            try:
                client.set_param(Parameter.SendTimeout, self.io_timeout_ms)
                client.set_param(Parameter.RecvTimeout, self.io_timeout_ms)
                client.set_param(Parameter.PingTimeout, 1000)
            except Exception:
                pass
            client.connect(self.ip, self.rack, self.slot)
        except Exception as e:
            print(f"连接失败({self.ip}): {e}")
            try:
                client.destroy()
            except Exception:
                pass
            return False

        with self.lock:
            self.client = client
            self.connected = True
            self._connect_attempts = 0
        print(f"PLC 已连接: {self.ip}")
        self._notify_state("已连接")
        return True

    def connect(self) -> bool:
        """连接 PLC（幂等，已连接时直接返回 True）"""
        with self.lock:
            if self.connected and self.client is not None:
                return True
        return self._open_client()

    def disconnect(self):
        """断开连接"""
        with self.lock:
            was_connected = self.connected
            self.connected = False
        self._close_client()
        if was_connected:
            self._notify_state("已断开")

    def isConnected(self):
        return self.connected

    # ------------------------------------------------------------------
    # 心跳
    # ------------------------------------------------------------------
    def start_heartbeat(self, interval: float = 1):
        """启动心跳线程（重复调用不会产生多个线程）"""
        interval = max(float(interval), _MIN_HEARTBEAT_INTERVAL)
        if self.thread is not None and self.thread.is_alive():
            self.heartbeat_active = True
            return
        self.heartbeat_active = True
        self._stop_reconnect = False
        self.thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(interval,),
            name="PLCHeartbeat",
            daemon=True,
        )
        self.thread.start()

    def stop_thread(self):
        """停止心跳线程并断开连接"""
        self.heartbeat_active = False
        self._stop_reconnect = True
        self.disconnect()
        thread = self.thread
        self.thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=3)
        print('断开连接')

    def _heartbeat_loop(self, interval: float):
        """心跳循环（独立线程）。

        写 DB21.0 递增序号保活；失败只标记断线，重连交给 _request_reconnect，
        避免心跳线程被长时间的 connect 阻塞。
        """
        while self.heartbeat_active:
            client = self.client
            if client is not None and self.connected:
                failed = None
                # 与其他线程的读写串行，避免 "CLI : Job pending"
                with self._io_lock:
                    try:
                        self.hmi_seq = (self.hmi_seq + 1) % 256
                        client.db_write(21, 0, bytearray([self.hmi_seq & 0xFF]))
                    except Exception as e:
                        failed = e
                if failed is not None:
                    print(f"心跳异常: {failed}")
                    with self.lock:
                        self.connected = False
                    self._notify_state(f"心跳异常: {failed}")
                    self._request_reconnect()

            if not self.connected:
                self._request_reconnect()

            threading.Event().wait(interval)

    # ------------------------------------------------------------------
    # 重连
    # ------------------------------------------------------------------
    def _request_reconnect(self) -> None:
        """确保有且只有一个重连线程在跑。"""
        with self.lock:
            if self._reconnecting:
                return
            self._reconnecting = True
        threading.Thread(
            target=self._reconnect_loop, name="PLReconnect", daemon=True
        ).start()

    def _reconnect_loop(self) -> None:
        """指数退避重连：直到连上、或心跳线程被显式停止为止。

        注意不能用 ``while heartbeat_active`` 作为循环条件：心跳线程是在
        连接成功后才启动的，若首次连接就失败，条件为 False 会让重连线程
        立即退出。
        """
        delay = RECONNECT_MIN_DELAY
        try:
            while not self._stop_reconnect:
                with self.lock:
                    if self.connected:
                        return
                self._connect_attempts += 1
                print(f"尝试重连...({self.ip}, 第{self._connect_attempts}次)")
                self._notify_state("重连中")
                self._close_client()
                if self._open_client():
                    return
                # 指数退避，避免 PLC 未上电时每 5 秒刷屏
                threading.Event().wait(delay)
                delay = min(delay * RECONNECT_BACKOFF, RECONNECT_MAX_DELAY)
        finally:
            with self.lock:
                self._reconnecting = False

    def reconnect(self) -> bool:
        """同步重连一次（兼容旧调用）；失败返回 False，不阻塞循环。"""
        if self.connected:
            return True
        self._close_client()
        return self._open_client()

    # ------------------------------------------------------------------
    # 读写
    # ------------------------------------------------------------------
    def read_data(self, db_number: int, start: int, size: int,
                  priority: bool = False) -> Optional[bytes]:
        """读取数据（线程安全）。未连接或失败返回 None。

        priority=True 用于 UI 线程触发的读取：会插到轮询线程前面执行，
        避免点击按钮后等好几个轮询周期。
        """
        client = self.client
        if client is None or not self.connected:
            return None
        error = None
        self._io_lock.acquire(priority)
        try:
            # 拿锁后再确认一次：可能刚刚被别的线程判定断线并销毁了 client
            client = self.client
            if client is None or not self.connected:
                return None
            try:
                return client.db_read(db_number, start, size)
            except Exception as e:
                error = e
        finally:
            self._io_lock.release()

        print(f"读取数据失败: {error}")
        with self.lock:
            self.connected = False
        self._notify_state(f"读取失败: {error}")
        self._request_reconnect()
        return None

    def write_data(self, db_number: int, start: int, data: bytearray,
                   priority: bool = False) -> bool:
        """写入数据（线程安全）。priority 含义同 read_data。"""
        client = self.client
        if client is None or not self.connected:
            return False
        error = None
        self._io_lock.acquire(priority)
        try:
            client = self.client
            if client is None or not self.connected:
                return False
            try:
                client.db_write(db_number, start, data)
                return True
            except Exception as e:
                error = e
        finally:
            self._io_lock.release()

        print(f"写入数据失败: {error}")
        with self.lock:
            self.connected = False
        self._notify_state(f"写入失败: {error}")
        self._request_reconnect()
        return False

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------
    def change_ip(self, ip: str) -> bool:
        if ip == "...":
            return False
        if ip == self.ip:
            return True
        self.ip = ip
        self.disconnect()
        self._request_reconnect()
        return True

    def get_ip_address(self):
        return self.ip

    def stop_plc(self):
        print(self.client.plc_stop())
        print("stop plc")

    def start_plc(self):
        print(self.client.plc_hot_start())
