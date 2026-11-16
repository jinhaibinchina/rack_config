"""局域网设备扫描。

用途：自动找到本机**被设置成静态 IP** 的那张网卡，得到它所在网段，
然后把该网段内所有在线设备的 IP / MAC 扫出来（机柜现场用来找设备）。

``scan()`` 有两条路径：

    同网段（二层直连，现场绝大多数情况，/24 约 1 秒）
        1. ``arp_prime()``   给每个地址发一个空 UDP 包，触发 ARP 请求
                             （不启动进程、不发 ICMP，比逐个 ping 快一个数量级）
        2. ``arp_map()``     读 ARP 表：有 MAC = 设备在线（ICMP 被拦也一样）
        3. ``ping_sweep()``  只对命中的地址复核一次，剔掉 ARP 里的陈旧条目

    跨网段（要走路由，ARP 拿不到对端）
        1. ``get_interfaces()``     解析 ipconfig /all（POSIX 用 ip / ifconfig），
                                    按 DHCP 是否启用来判定「静态 IP」网卡
        2. ``subnet_hosts()``       由 IP + 掩码算出网段内全部可用主机地址
        3. ``ping_sweep()``         多线程 ICMP 探测
        4. ``tcp_probe_hosts()``    对 ping 不通的地址补一次 TCP 端口探测
        5. ``arp_map()``            读 ARP 表补 MAC，合并成最终列表

相比旧实现（只读 ARP 缓存表）的改动：
    * ARP 缓存不会凭空出现设备，必须先有流量把邻居表「踩」热（见 ``arp_prime``）
    * 不再依赖 "动态" 这种本地化关键字，中英文系统都能解析
    * Windows 下 ping 收到「无法访问目标主机」也返回 0，必须看输出里有没有 TTL=
    * 优先挑静态 IP 的物理网卡，VMware/Hyper-V 等虚拟网卡排到最后
    * 输出按 IP 数值排序，过滤广播/组播 MAC，支持 JSON 供 Qt 侧直接消费

在 Qt 里调用（务必放到工作线程，不要阻塞 UI）：
    from search_ip import scan
    result = scan(progress=lambda done, total: ...)   # 回调里发信号回主线程
    for host in result.hosts:
        print(host.ip, host.mac)

命令行：
    python search_ip.py                       # 静态网卡所在网段全扫
    python search_ip.py --all                 # 每张网卡都扫
    python search_ip.py -s 192.168.1.0/24     # 指定网段
    python search_ip.py -t 1.0 --json         # 放宽超时 / 输出 JSON
    python search_ip.py --deep                # 强制完整 ICMP 扫描（慢但最严格）
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import locale
import os
import platform
import re
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

IS_WINDOWS = os.name == "nt"
# 不弹黑框（Windows 下从 Qt 里调 subprocess 时非常关键）
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_SYSTEM = platform.system().lower()

# 一次扫描最多处理多少个地址：/20 以上就拒绝，避免把 /16 扫成灾难
MAX_HOSTS = 4096
DEFAULT_TIMEOUT = 0.6      # 单次 ping 超时（秒）
DEFAULT_WORKERS = 64       # 并发数（Windows 下每个 ping 是一个进程，再往上加反而更慢）
# 补扫用的 TCP 端口：102=西门子 S7，502=Modbus，80/443=Web 配置页，22=SSH
TCP_PROBE_PORTS = (102, 502, 80, 443, 22)
TCP_PROBE_TIMEOUT = 0.25
# 触发 ARP 用的目标端口（随便挑一个基本不会开的高位端口）与等待应答的时间
ARP_PRIME_PORT = 33434
ARP_WAIT = 0.45


# --------------------------------------------------------------------------- #
# 子进程工具
# --------------------------------------------------------------------------- #
def _decode(raw: bytes) -> str:
    """按 utf-8 → 系统首选编码 → gbk 的顺序解码。

    中文 Windows 的 ipconfig / arp 输出是 GBK，直接 text=True 在部分环境下
    会抛 UnicodeDecodeError（或解出乱码导致正则匹配失败）。
    """
    if not raw:
        return ""
    for enc in ("utf-8", locale.getpreferredencoding(False), "gbk"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _run(cmd: Sequence[str], timeout: float = 20.0) -> str:
    """执行命令并返回解码后的 stdout，失败一律返回空串（不抛异常）。"""
    try:
        proc = subprocess.run(
            list(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=_NO_WINDOW,
        )
        return _decode(proc.stdout)
    except (OSError, subprocess.SubprocessError):
        return ""


def _is_valid_netmask(text: str) -> bool:
    """判断是否是连续的合法 IPv4 掩码（255.255.255.0 / 255.255.254.0 ...）。"""
    try:
        value = int(ipaddress.IPv4Address(text))
    except (ipaddress.AddressValueError, ValueError):
        return False
    if value in (0, 0xFFFFFFFF):
        return False
    inverse = (~value) & 0xFFFFFFFF
    return (inverse & (inverse + 1)) == 0


def prefix_from_mask(mask: str) -> int:
    """点分掩码 → 前缀长度。"""
    return ipaddress.IPv4Network("0.0.0.0/" + mask).prefixlen


# --------------------------------------------------------------------------- #
# 网卡信息
# --------------------------------------------------------------------------- #
@dataclass
class InterfaceInfo:
    """一张 IPv4 网卡。"""

    name: str
    ip: str
    netmask: str
    gateway: str = ""
    # True=DHCP，False=手工静态，None=未知（判断不出来的平台）
    dhcp: Optional[bool] = None
    mac: str = ""

    @property
    def prefix(self) -> int:
        return prefix_from_mask(self.netmask)

    @property
    def is_static(self) -> Optional[bool]:
        """本机这张网卡是不是被设置成了静态 IP。"""
        return None if self.dhcp is None else not self.dhcp

    @property
    def network(self) -> ipaddress.IPv4Network:
        return ipaddress.IPv4Network(f"{self.ip}/{self.netmask}", strict=False)

    @property
    def cidr(self) -> str:
        return str(self.network)


def _parse_ipconfig_all(text: str) -> List[InterfaceInfo]:
    """解析 ipconfig /all。不依赖标签语言，靠「值」的形状判断字段。"""
    blocks: List[Tuple[str, List[str]]] = []
    cur_name: Optional[str] = None
    cur_lines: List[str] = []

    for line in text.splitlines():
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")):
            # 适配器标题行，如 "以太网适配器 以太网:" / "Ethernet adapter Ethernet:"
            if cur_name is not None:
                blocks.append((cur_name, cur_lines))
            cur_name = line.strip().rstrip(":").strip()
            cur_lines = []
        elif cur_name is not None:
            cur_lines.append(line)
    if cur_name is not None:
        blocks.append((cur_name, cur_lines))

    result: List[InterfaceInfo] = []
    quad_re = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

    for name, lines in blocks:
        block = "\n".join(lines)
        if re.search(r"loopback|回环", name, re.I):
            continue

        # DHCP 是否启用：标签里含 DHCP + 启用的那一行，取冒号后的值
        dhcp: Optional[bool] = None
        for line in lines:
            if "dhcp" not in line.lower() or ":" not in line:
                continue
            label, _, value = line.rpartition(":")
            if re.search(r"启用|enabled", label, re.I):
                dhcp = not bool(re.match(r"\s*(否|no|false|off|关闭)", value.strip(), re.I))
                break

        quads = quad_re.findall(block)
        quads = [q for q in quads if q != "0.0.0.0"]
        if not quads:
            continue

        ip = quads[0]
        netmask = ""
        for quad in quads[1:]:
            if _is_valid_netmask(quad):
                netmask = quad
                break
        if not netmask:
            netmask = "255.255.255.0"

        gateway = ""
        try:
            start = quads.index(netmask) + 1
        except ValueError:
            start = 1
        for quad in quads[start:]:
            if quad in (ip, netmask) or _is_valid_netmask(quad):
                continue
            gateway = quad
            break

        if ip.startswith("127.") or ip.startswith("169.254."):
            continue
        mac = ""
        mac_match = re.search(r"\b(?:[0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2}\b", block)
        if mac_match:
            mac = _normalize_mac(mac_match.group(0))
        result.append(InterfaceInfo(name=name, ip=ip, netmask=netmask,
                                    gateway=gateway, dhcp=dhcp, mac=mac))
    return result


def _parse_ip_addr(text: str) -> List[InterfaceInfo]:
    """解析 Linux 的 ``ip -4 -o addr show``。"""
    gateways = _default_gateways_linux()
    macs = _mac_map_linux()
    result: List[InterfaceInfo] = []
    for line in text.splitlines():
        m = re.match(r"\s*\d+:\s+(\S+)\s+inet\s+((?:\d{1,3}\.){3}\d{1,3})/(\d+)", line)
        if not m:
            continue
        name, ip, prefix = m.group(1).split("@")[0], m.group(2), int(m.group(3))
        if ip.startswith(("127.", "169.254.")):
            continue
        netmask = str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)
        result.append(InterfaceInfo(name=name, ip=ip, netmask=netmask,
                                    gateway=gateways.get(name, ""), dhcp=None,
                                    mac=macs.get(name, "")))
    return result


def _mac_map_linux() -> Dict[str, str]:
    out = _run(["ip", "-o", "link", "show"])
    mapping: Dict[str, str] = {}
    for line in out.splitlines():
        m = re.match(r"\s*\d+:\s+(\S+):.*link/ether\s+([0-9a-fA-F:]{17})", line)
        if m:
            mapping[m.group(1).split("@")[0]] = _normalize_mac(m.group(2))
    return mapping


def _default_gateways_linux() -> Dict[str, str]:
    out = _run(["ip", "route", "show", "default"])
    mapping: Dict[str, str] = {}
    for line in out.splitlines():
        m = re.search(r"default via ((?:\d{1,3}\.){3}\d{1,3})(?:\s+dev\s+(\S+))?", line)
        if m:
            mapping[m.group(2) or ""] = m.group(1)
    return mapping


def _parse_ifconfig(text: str) -> List[InterfaceInfo]:
    """解析 macOS / BSD 的 ifconfig（netmask 是 0xffffff00 这种十六进制）。"""
    result: List[InterfaceInfo] = []
    cur: Optional[str] = None
    cur_mac = ""
    for line in text.splitlines():
        m = re.match(r"^(\w+):\s+flags", line)
        if m:
            cur = m.group(1)
            cur_mac = ""
            continue
        m = re.search(r"\bether\s+([0-9a-fA-F:]{17})", line)
        if m:
            cur_mac = _normalize_mac(m.group(1))
            continue
        m = re.search(r"inet\s+((?:\d{1,3}\.){3}\d{1,3})\s+netmask\s+(0x[0-9a-fA-F]+)", line)
        if not m or cur is None:
            continue
        ip, mask_hex = m.group(1), m.group(2)
        if ip.startswith(("127.", "169.254.")):
            continue
        netmask = str(ipaddress.IPv4Address(int(mask_hex, 16)))
        result.append(InterfaceInfo(name=cur, ip=ip, netmask=netmask,
                                    dhcp=None, mac=cur_mac))
    return result


def get_interfaces() -> List[InterfaceInfo]:
    """列出本机所有可用的 IPv4 网卡（已排除回环 / 169.254 自分配地址）。"""
    if IS_WINDOWS:
        text = _run(["ipconfig", "/all"])
        if not text:
            fallback = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                    "System32", "ipconfig.exe")
            text = _run([fallback, "/all"])
        return _parse_ipconfig_all(text)

    if _SYSTEM == "linux":
        return _parse_ip_addr(_run(["ip", "-4", "-o", "addr", "show"]))

    if _SYSTEM == "darwin":
        return _parse_ifconfig(_run(["ifconfig"]))

    return []


def get_static_interfaces() -> List[InterfaceInfo]:
    """只返回被显式设置成静态 IP 的网卡（DHCP 已启用=否）。"""
    return [nic for nic in get_interfaces() if nic.is_static]


# 现场机器上常装 VMware/VirtualBox/Hyper-V，这些虚拟网卡也在 ARP 表里刷存在感，
# 选「现场网线」时要排到最后。
_VIRTUAL_NIC_RE = re.compile(
    r"vmware|vmnet|virtualbox|vbox|hyper-?v|vethernet|loopback|tap|tun|docker|"
    r"wsl|npcap|bluetooth|蓝牙",
    re.I,
)


def _pick_primary(interfaces: Sequence[InterfaceInfo],
                  prefer_static: bool = True) -> Optional[InterfaceInfo]:
    """从网卡列表里挑一张「最像现场网线」的。

    优先级：非虚拟网卡 > 静态 IP > 有默认网关。
    """
    if not interfaces:
        return None

    def score(nic: InterfaceInfo) -> Tuple[int, int, int]:
        return (0 if _VIRTUAL_NIC_RE.search(nic.name) else 1,
                1 if (prefer_static and nic.is_static) else 0,
                1 if nic.gateway else 0)

    return max(interfaces, key=score)


def get_primary_interface(prefer_static: bool = True) -> Optional[InterfaceInfo]:
    """挑一张「最像现场网线」的网卡（详见 ``_pick_primary``）。"""
    return _pick_primary(get_interfaces(), prefer_static)


# --------------------------------------------------------------------------- #
# 网段
# --------------------------------------------------------------------------- #
def subnet_hosts(cidr: str, limit: int = MAX_HOSTS) -> Tuple[ipaddress.IPv4Network, List[str]]:
    """把 CIDR 展开成可用主机地址列表（去掉网络地址和广播地址）。"""
    try:
        net = ipaddress.IPv4Network(cidr, strict=False)
    except ValueError:
        raise ValueError(f"非法的网段: {cidr}") from None

    if net.num_addresses > limit + 2:
        raise ValueError(
            f"网段 {net} 太大（{net.num_addresses - 2} 个地址），"
            f"上限 {limit} 个；请用 --subnet 指定更小的范围"
        )
    if net.prefixlen >= 31:
        return net, [str(net.network_address)]
    return net, [str(host) for host in net.hosts()]


def ip_sort_key(ip: str) -> Tuple[int, ...]:
    try:
        return tuple(int(part) for part in ip.split("."))
    except ValueError:
        return (0, 0, 0, 0)


# --------------------------------------------------------------------------- #
# 在线探测
# --------------------------------------------------------------------------- #
def ping(ip: str, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """单地址 ICMP 探测。"""
    if IS_WINDOWS:
        cmd = ["ping", "-n", "1", "-w", str(max(1, int(timeout * 1000))), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, int(round(timeout)))), ip]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 2,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    if proc.returncode != 0:
        return False
    # Windows 上收到「无法访问目标主机 / TTL 传输中过期」也会返回 0，
    # 但那种回复里没有 TTL=，必须靠它排除假在线。
    return b"TTL=" in proc.stdout.upper()


def tcp_probe(ip: str, ports: Sequence[int] = TCP_PROBE_PORTS,
              timeout: float = TCP_PROBE_TIMEOUT) -> Optional[int]:
    """对若干常用端口做 TCP 连接探测，命中返回端口号（用于屏蔽 ICMP 的设备）。"""
    for port in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            if sock.connect_ex((ip, port)) == 0:
                return port
        except OSError:
            pass
        finally:
            sock.close()
    return None


def arp_prime(hosts: Iterable[str], port: int = ARP_PRIME_PORT) -> None:
    """给网段内每个地址发一个空 UDP 包，只为了触发 ARP 请求。

    同网段（二层直连）的设备即使关掉了 ICMP，也必须应答 ARP；
    所以「发 UDP → 等一会儿 → 读 ARP 表」比逐个 ping 快一个数量级，
    而且不用为每个 IP 创建一个 ping.exe 进程。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for ip in hosts:
            try:
                sock.sendto(b"", (ip, port))
            except OSError:
                continue
    finally:
        sock.close()


def ping_sweep(hosts: Iterable[str], timeout: float = DEFAULT_TIMEOUT,
               workers: int = DEFAULT_WORKERS,
               progress: Optional[Callable[[int, int], None]] = None) -> List[str]:
    """多线程 ping 扫描，返回响应的 IP 列表。

    ``progress(done, total)`` 每完成一个地址回调一次，方便 Qt 侧更新进度条
    （在工作线程里调用，回调中请用信号切回主线程再碰控件）。
    """
    targets = list(hosts)
    total = len(targets)
    if not total:
        return []

    alive: List[str] = []
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, min(workers, total))) as pool:
        futures = {pool.submit(ping, ip, timeout): ip for ip in targets}
        for future in as_completed(futures):
            done += 1
            if future.result():
                alive.append(futures[future])
            if progress is not None:
                progress(done, total)
    return alive


def tcp_probe_hosts(hosts: Iterable[str], ports: Sequence[int] = TCP_PROBE_PORTS,
                    timeout: float = TCP_PROBE_TIMEOUT, workers: int = DEFAULT_WORKERS
                    ) -> Dict[str, int]:
    """对多个地址并发做端口探测，返回 {ip: 命中的端口}。"""
    targets = list(hosts)
    if not targets:
        return {}

    hits: Dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(targets)))) as pool:
        futures = {pool.submit(tcp_probe, ip, ports, timeout): ip for ip in targets}
        for future in as_completed(futures):
            port = future.result()
            if port is not None:
                hits[futures[future]] = port
    return hits


# --------------------------------------------------------------------------- #
# ARP / 邻居表
# --------------------------------------------------------------------------- #
_ARP_ROW_RE = re.compile(
    r"^\s*((?:\d{1,3}\.){3}\d{1,3})\s+([0-9a-fA-F]{2}(?:[-:][0-9a-fA-F]{2}){5})\b"
)
_ARP_IFACE_RE = re.compile(r"(?:接口|Interface)\s*:\s*((?:\d{1,3}\.){3}\d{1,3})", re.I)
_IP_NEIGH_RE = re.compile(
    r"^((?:\d{1,3}\.){3}\d{1,3})\s+dev\s+(\S+)\s+(?:lladdr\s+([0-9a-fA-F:]{17}))?"
)
_ARP_AN_RE = re.compile(r"\(((?:\d{1,3}\.){3}\d{1,3})\)\s+at\s+([0-9a-fA-F:]{17})")


def _normalize_mac(mac: str) -> str:
    return mac.replace(":", "-").upper()


def _is_usable_mac(mac: str) -> bool:
    """过滤广播 / 全零 / 组播 MAC。"""
    hex_only = mac.replace("-", "").replace(":", "")
    if len(hex_only) != 12 or hex_only in ("000000000000", "FFFFFFFFFFFF"):
        return False
    try:
        first = int(hex_only[:2], 16)
    except ValueError:
        return False
    return not (first & 0x01)  # 第 1 位为 1 是组播/广播


def read_arp_table() -> List[Tuple[str, str, str]]:
    """读邻居表，返回 [(本机网卡 IP, 对端 IP, MAC)]。"""
    rows: List[Tuple[str, str, str]] = []

    if IS_WINDOWS:
        text = _run(["arp", "-a"])
        current_iface = ""
        for line in text.splitlines():
            m = _ARP_IFACE_RE.search(line)
            if m:
                current_iface = m.group(1)
                continue
            m = _ARP_ROW_RE.match(line)
            if m:
                rows.append((current_iface, m.group(1), _normalize_mac(m.group(2))))
        return rows

    if _SYSTEM == "linux":
        text = _run(["ip", "neigh", "show"])
        for line in text.splitlines():
            m = _IP_NEIGH_RE.match(line)
            if m and m.group(3):
                rows.append(("", m.group(1), _normalize_mac(m.group(3))))
        return rows

    text = _run(["arp", "-an"])
    for line in text.splitlines():
        m = _ARP_AN_RE.search(line)
        if m:
            rows.append(("", m.group(1), _normalize_mac(m.group(2))))
    return rows


def arp_map(iface_ip: Optional[str] = None) -> Dict[str, str]:
    """{ip: mac}。给了 ``iface_ip`` 就只取该网卡那一段。"""
    mapping: Dict[str, str] = {}
    for row_iface, ip, mac in read_arp_table():
        if iface_ip and row_iface and row_iface != iface_ip:
            continue
        if not _is_usable_mac(mac):
            continue
        mapping[ip] = mac
    return mapping


# --------------------------------------------------------------------------- #
# 扫描主体
# --------------------------------------------------------------------------- #
@dataclass
class Host:
    """一台扫到的设备。"""

    ip: str
    mac: str = ""
    via: str = "arp"      # 发现方式：icmp / tcp:<port> / arp
    is_self: bool = False

    def as_dict(self) -> Dict[str, object]:
        return {"ip": self.ip, "mac": self.mac, "via": self.via, "self": self.is_self}


@dataclass
class ScanResult:
    """一次扫描的结果。"""

    interface: Optional[InterfaceInfo] = None
    network: str = ""
    hosts: List[Host] = field(default_factory=list)
    duration: float = 0.0
    note: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {
            "interface": None if self.interface is None else {
                "name": self.interface.name,
                "ip": self.interface.ip,
                "netmask": self.interface.netmask,
                "gateway": self.interface.gateway,
                "mac": self.interface.mac,
                "static": self.interface.is_static,
            },
            "network": self.network,
            "duration": round(self.duration, 2),
            "count": len(self.hosts),
            "hosts": [host.as_dict() for host in self.hosts],
            "note": self.note,
        }

    @property
    def ips(self) -> List[str]:
        """全部 IP（含本机自己）。"""
        return [host.ip for host in self.hosts]

    @property
    def device_ips(self) -> List[str]:
        """只含「别的设备」的 IP 列表，不含本机自己。"""
        return [host.ip for host in self.hosts if not host.is_self]


def scan(cidr: Optional[str] = None, interface: Optional[InterfaceInfo] = None,
         timeout: float = DEFAULT_TIMEOUT, workers: int = DEFAULT_WORKERS,
         use_tcp: bool = True, deep: bool = False, limit: int = MAX_HOSTS,
         progress: Optional[Callable[[int, int], None]] = None) -> ScanResult:
    """扫描一个网段（默认取本机静态 IP 网卡所在网段）。

    参数：
        cidr      指定网段，如 ``192.168.1.0/24``；为空则自动取本机静态网卡
        interface 指定网卡（``get_interfaces()`` 的元素）；为空则自动挑
        timeout   单次 ping 超时（秒），现场无线/慢设备可调大到 1.0
        workers   并发数
        use_tcp   跨网段时对 ping 不通的地址是否补 TCP 端口探测（默认开）
        deep      True 则强制走完整 ICMP 扫描（慢，但能清掉 ARP 里的陈旧条目）
        progress  进度回调 ``(done, total)``

    两种模式：
        * 目标网段与本机网卡同网段（二层直连，机柜现场绝大多数情况）：
          发 UDP 触发 ARP → 读 ARP 表 → 只对命中的 IP 做一次 ping 复核。
          /24 通常 1 秒内出结果。
        * 目标网段在别处（要走路由）：只能 ICMP 全扫 + TCP 端口补扫。
    """
    started = time.time()
    result = ScanResult()
    interfaces = get_interfaces()          # 只取一次，ipconfig 本身要 ~0.5s

    if interface is None and not cidr:
        interface = _pick_primary(interfaces, prefer_static=True)

    if cidr:
        network, hosts = subnet_hosts(cidr, limit=limit)
    elif interface is not None:
        network, hosts = subnet_hosts(interface.cidr, limit=limit)
    else:
        result.note = "未找到可用的 IPv4 网卡，请用 --subnet 手动指定网段"
        result.duration = time.time() - started
        return result
    result.network = str(network)

    if interface is not None:
        result.interface = interface
        if interface.is_static is False:
            result.note = "该网卡为 DHCP 获取（非静态 IP）"

    if result.interface is None:
        # 手动指定网段时，尽量标注本机 IP 供上层判断
        local_ip = _guess_local_ip()
        if local_ip:
            for nic in interfaces:
                if nic.ip == local_ip:
                    result.interface = nic
                    break
    self_ip = result.interface.ip if result.interface else _guess_local_ip()
    iface_ip = result.interface.ip if result.interface else None

    # 目标网段是否与本机某张网卡同段（决定能不能用 ARP 快扫）
    same_link = False
    for nic in ([result.interface] if result.interface else []) + list(interfaces):
        if nic is None:
            continue
        try:
            if network.subnet_of(nic.network):   # py3.7+
                same_link = True
                break
        except (AttributeError, TypeError):
            if network.network_address in nic.network:
                same_link = True
                break

    ping_alive: set = set()
    tcp_alive: Dict[str, int] = {}

    if same_link and not deep:
        # 快扫：ARP 触发 + 只复核 MAC 已出现的地址
        arp_prime(hosts)
        time.sleep(ARP_WAIT)
        neigh = arp_map(iface_ip)
        candidates = [ip for ip in hosts if ip in neigh]
        total_ticks = len(hosts) + len(candidates)
        if progress is not None:
            progress(len(hosts), total_ticks)

        def _confirm_cb(done: int, _total: int) -> None:
            if progress is not None:
                progress(len(hosts) + done, total_ticks)

        # 复核用的超时放宽一点：ARP 刚建表时，第一次 ICMP 偶尔会被丢
        ping_alive = set(ping_sweep(candidates, timeout=max(timeout, 1.5),
                                    workers=workers,
                                    progress=_confirm_cb if progress else None))
    else:
        # 全扫：ICMP 把 ARP 表喂热，ARP 捞被防火墙拦掉 ICMP 的设备，再补 TCP
        ping_alive = set(ping_sweep(hosts, timeout=timeout, workers=workers,
                                    progress=progress))
        neigh = arp_map(iface_ip)
        if use_tcp:
            missing = [ip for ip in hosts if ip not in ping_alive and ip not in neigh]
            if missing:
                tcp_alive = tcp_probe_hosts(missing, timeout=TCP_PROBE_TIMEOUT,
                                            workers=workers)

    # 合并成结果
    for ip in hosts:
        mac = neigh.get(ip, "")
        if ip in ping_alive:
            via = "icmp"
        elif ip in tcp_alive:
            via = f"tcp:{tcp_alive[ip]}"
        elif mac:
            via = "arp"
        else:
            continue
        result.hosts.append(Host(ip=ip, mac=mac, via=via, is_self=(ip == self_ip)))

    # 本机自己不在 ARP 表里（自己不会给自己发 ARP），单独补一条
    if self_ip and self_ip in hosts:
        own = next((host for host in result.hosts if host.ip == self_ip), None)
        own_mac = result.interface.mac if result.interface else ""
        if own is None:
            result.hosts.append(Host(ip=self_ip, mac=own_mac, via="self", is_self=True))
        elif not own.mac and own_mac:
            own.mac = own_mac

    result.hosts.sort(key=lambda host: ip_sort_key(host.ip))
    result.duration = time.time() - started
    return result


def _guess_local_ip() -> str:
    """兜底：通过一次 UDP connect 猜出本机出口 IP（不发包）。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return ""


def scan_all(timeout: float = DEFAULT_TIMEOUT, workers: int = DEFAULT_WORKERS,
             use_tcp: bool = True, deep: bool = False) -> List[ScanResult]:
    """扫所有网卡各自的网段（多网卡机器一次扫全）。"""
    results: List[ScanResult] = []
    seen = set()
    for nic in get_interfaces():
        if nic.cidr in seen:
            continue
        seen.add(nic.cidr)
        results.append(scan(interface=nic, timeout=timeout, workers=workers,
                            use_tcp=use_tcp, deep=deep))
    return results


# --------------------------------------------------------------------------- #
# 兼容旧接口
# --------------------------------------------------------------------------- #
def scan_by_arp() -> List[str]:
    """旧接口保留：返回本机静态网卡网段内的设备 IP 列表。

    注意：**不含本机自己的 IP**，只返回网段里其它设备。
    """
    return scan().device_ips


def find_devices(cidr: Optional[str] = None, include_self: bool = False,
                 **kwargs) -> List[str]:
    """便捷函数：直接返回 IP 字符串列表（默认不含本机）。"""
    result = scan(cidr=cidr, **kwargs)
    return result.ips if include_self else result.device_ips


# --------------------------------------------------------------------------- #
# 命令行
# --------------------------------------------------------------------------- #
def _print_result(result: ScanResult) -> None:
    header = "本机网卡"
    if result.interface is not None:
        nic = result.interface
        kind = {True: "静态", False: "DHCP", None: "未知"}[nic.is_static]
        print(f"{header}: {nic.name}  {nic.ip}/{nic.prefix}  ({kind} IP)"
              + (f"  网关 {nic.gateway}" if nic.gateway else ""))
    print(f"扫描网段: {result.network}   用时 {result.duration:.1f}s   发现 {len(result.hosts)} 台")
    if result.note:
        print(f"提示: {result.note}")
    if not result.hosts:
        return

    print("-" * 62)
    print(f"{'IP':<16}{'MAC':<19}{'方式':<10}{'备注'}")
    print("-" * 62)
    for host in result.hosts:
        print(f"{host.ip:<16}{(host.mac or '-'):<19}{host.via:<10}"
              f"{'本机' if host.is_self else ''}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="扫描本机静态 IP 所在网段内的所有设备（IP + MAC）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-s", "--subnet", help="手动指定网段，如 192.168.1.0/24")
    parser.add_argument("-a", "--all", action="store_true", help="扫描所有网卡的网段")
    parser.add_argument("-t", "--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help="单次 ping 超时（秒）")
    parser.add_argument("-w", "--workers", type=int, default=DEFAULT_WORKERS,
                        help="并发线程数")
    parser.add_argument("--no-tcp", action="store_true", help="关闭 TCP 端口补扫")
    parser.add_argument("--deep", action="store_true",
                        help="强制完整 ICMP 扫描（慢，可清掉 ARP 陈旧条目）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args(argv)

    try:
        if args.all:
            results = scan_all(timeout=args.timeout, workers=args.workers,
                               use_tcp=not args.no_tcp, deep=args.deep)
        else:
            results = [scan(cidr=args.subnet, timeout=args.timeout,
                            workers=args.workers, use_tcp=not args.no_tcp,
                            deep=args.deep)]
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    if args.json:
        payload = [result.as_dict() for result in results]
        print(json.dumps(payload if args.all else payload[0],
                         ensure_ascii=False, indent=2))
        return 0

    for index, result in enumerate(results):
        if index:
            print()
        _print_result(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
