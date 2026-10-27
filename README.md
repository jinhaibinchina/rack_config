# rack_config — 料架 PLC 配置工具

> 面向工业自动化场景的 PySide6 GUI 工具，用于 S7 PLC 料架系统的参数配置、实时监控与可视化调试。

---

## 目录

- [项目概述](#项目概述)
- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [技术栈](#技术栈)
- [核心模块](#核心模块)
- [打包部署](#打包部署)
- [配置说明](#配置说明)
- [许可证](#许可证)

---

## 项目概述

本项目是一套 **料架 PLC 配置工具**（V3.3.2），基于 PySide6 开发，通过 snap7 库与西门子 S7 系列 PLC（S7-1200/1500）进行 S7 协议通信。主要服务于锂电池生产线的料架系统调试与运维，支持阴极冷压、阳极冷压、阴极模切、阳极模切四种工艺类型的料架配置。

---

## 功能特性

### 🔍 PLC 设备自动发现
- 基于 ARP 扫描自动发现局域网内的 S7 PLC
- 显示 PLC IP 地址与 CPU 序列号
- 双击设备即可打开配置界面

### ⚙️ 料架参数配置
- **料架类型**：阴极冷压 / 阳极冷压 / 阴极模切 / 阳极模切
- **主机编号**：支持 1~70 号主机连续配置
- **仓位数量**：每主机 1~8 个仓位独立配置
- **排列方式**：10 组料架布局排列配置
- **写保护**：仅 admin 用户可写入参数，写入后需重启 PLC 生效

### 📊 实时数据监控
- **DataBroker 多线程轮询**：同时读取 DB21 / DB12 / DB24 / DB25
- **仓位状态可视化**：
  - 🟢 绿色 — 运行中
  - 🔴 红色 — 故障/报警
  - ⚪ 灰色 — 空闲
- **IO 模块状态**：A/B 模块实时指示灯
- **LED 控制**：红 / 绿 / 蓝 / 复位指示灯状态与手动控制
- **气缸控制**：前侧/后侧气缸伸出/缩回手动测试

### 🤖 AGV 交互监控
- 料架与 AGV 的任务状态实时显示
- 托盘状态（A/B 侧）、物料属性、滚筒类型
- 入料/出料请求信号监控

### 🕐 翻牌时钟
- PySide6 动画驱动的机械翻页时钟
- 支持本地时间或同步 PLC 时间显示
- 可缩放尺寸适配不同界面布局

### 🎨 料架布局设计器（myDesigner）
- 图形化料架仓位编辑
- 支持拖拽、吸附对齐
- 数据持久化存储

### 🔐 用户权限管理
- 登录/登出功能
- `admin` 用户拥有写参数权限
- 普通用户仅可查看状态

---

## 快速开始

### 环境要求

- Python 3.10+
- Windows（snap7.dll 为 Windows 版本）

### 安装依赖

```bash
pip install PySide6 snap7
```

### 运行程序

```bash
python main.py
```

### 基本操作流程

1. **扫描设备**：点击左侧 "设备列表" 旁的刷新按钮，自动扫描局域网 PLC
2. **选择设备**：双击列表中的 PLC IP，打开配置窗口
3. **读取参数**：点击 "读取参数" 加载当前 PLC 料架配置
4. **修改配置**：选择料架类型、主机编号、仓位数量等
5. **写入参数**：点击 "写入参数"（需 admin 登录），重启 PLC 生效
6. **监控状态**：实时查看仓位状态、IO 状态、报警信息

---

## 项目结构

```
rack_config/
├── main.py                     # 主入口程序
├── plc_window.py               # PLC 配置窗口（核心界面）
├── plc_manager.py              # PLC 通信管理器（snap7 封装）
├── data_broker.py              # 数据代理（多线程轮询）
├── login_window.py             # 用户登录对话框
├── flip_clock.py               # 翻牌时钟组件
├── tabbed_wigdet.py            # 标签页容器组件
├── global_config.py            # 全局配置
├── resource_manager.py         # 资源管理器（UI/图标路径解析）
├── load_ui.py                  # UI 文件加载器
├── search_ip.py                # IP 扫描工具
├── convert.py                  # 数据转换工具
├── common.py                   # 通用工具函数
├── packTool.py                 # 打包辅助脚本
│
├── myDesigner/                 # 料架布局设计器
│   ├── rack_store_widget.py    # 料架仓位控件
│   ├── myGraphicsScene.py      # 图形场景
│   ├── mySnapSystem.py         # 吸附对齐系统
│   ├── my_elements.py          # 可拖拽元素
│   ├── my_transform.py         # 变换工具
│   └── data.json               # 设计器数据
│
├── ui/                         # Qt Designer UI 文件
│   ├── main.ui                 # 主窗口布局
│   ├── rack_config.ui          # 料架配置界面
│   ├── agv_interface.ui        # AGV 交互界面
│   ├── hmi_config.ui           # HMI 配置界面
│   ├── Recipe.ui               # 配方界面
│   ├── rcd.ui / rcd.qss        # 日志查看器
│   └── ...
│
├── cfg/                        # 配置文件
├── ico/                        # 图标资源
├── widget_icons/               # 控件图标
├── snap7.dll                   # S7 通信库（Windows DLL）
├── hook-snap7.py               # PyInstaller 运行时钩子
├── rack_config.spec            # PyInstaller 打包配置
└── 打包说明.md                  # 打包部署文档
```

---

## 技术栈

| 技术 | 用途 |
|------|------|
| PySide6 | GUI 框架（窗口、控件、信号槽） |
| Qt Designer | UI 界面设计（.ui 文件） |
| python-snap7 | 西门子 S7 PLC 通信 |
| QThread | 后台数据轮询线程 |
| QPropertyAnimation | 翻牌时钟动画效果 |
| PyInstaller | 打包为独立可执行程序 |

---

## 核心模块

### PLCManager (`plc_manager.py`)

封装 snap7 客户端，提供：
- `connect()` / `disconnect()` — PLC 连接管理
- `read_data(db, start, size)` — 读取 DB 块数据（线程安全）
- `write_data(db, start, data)` — 写入 DB 块数据（线程安全）
- `start_heartbeat()` — 启动心跳线程（防止 HMI 断线）
- `reconnect()` — 自动断线重连

### DataBroker (`data_broker.py`)

基于 QThread 的数据采集代理：
- 轮询间隔可配置（默认 200ms）
- 同时读取 4 个 DB 块：
  - **DB21** — PLC 基本信息、运行时间、状态灯
  - **DB12** — 仓位状态、IO 状态、报警信息
  - **DB24** — AGV 交互数据
  - **DB25** — 扩展数据
- 通过 `pyqtSignal` 发射数据到 UI 线程

### PLC 配置窗口 (`plc_window.py`)

核心配置界面，包含：
- **基本信息**：PLC 名称、版本号、校验码、运行时间
- **参数配置**：料架类型、主机编号、仓位数量、排列方式
- **状态监控**：
  - 10×8 仓位状态矩阵
  - IO 模块 A/B 状态
  - 16 路 IO 输入/输出状态
  - LED / 气缸手动测试
- **HMI 配置**：触摸屏关联主机设置
- **AGV 交互**：料架 ↔ AGV 任务状态监控

### 翻牌时钟 (`flip_clock.py`)

机械翻页风格时钟组件：
- `FlipDigit_top` / `FlipDigit_bottom` — 上下翻页动画
- `FlipDigit_Time_display` — 完整时钟（时:分:秒）
- 支持 `update_time_by_plc()` 同步 PLC 时间

---

## 打包部署

### 使用 PyInstaller 打包

```bash
# 安装 PyInstaller
pip install pyinstaller

# 使用 spec 文件打包（推荐）
pyinstaller rack_config.spec

# 或重新生成 spec 文件
pyinstaller --name="料架PLC配置工具" --windowed main.py
```

### 打包输出

- `dist/料架PLC配置工具/` — 可执行程序文件夹
- `build/` — 构建临时文件（可删除）

### 关键配置项

| 配置 | 说明 |
|------|------|
| `snap7.dll` | PLC 通信库，必须包含在打包目录中 |
| `hook-snap7.py` | 运行时钩子，自动配置 DLL 搜索路径 |
| `ui/*.ui` | Qt Designer 界面文件 |
| `ico/*.png` | 图标资源 |

### 常见问题

- **DLL 加载失败**：确保 `snap7.dll` 与 exe 同目录，或使用 `hook-snap7.py` 钩子
- **UI 文件找不到**：`resource_manager.py` 已处理 `sys._MEIPASS` 路径适配

> 详细打包说明请参考 [打包说明.md](打包说明.md)

---

## 配置说明

### PLC 通信参数

```python
# plc_manager.py 默认配置
ip   = "192.168.1.10"   # PLC IP 地址（由扫描结果决定）
rack = 0                 # 机架号
slot = 1                 # 插槽号（S7-1200 通常为 1）
```

### DB 块数据映射

| DB 块 | 用途 | 关键数据 |
|-------|------|---------|
| DB21 | 系统信息 | 运行时间、PLC 时间、LED 状态 |
| DB22 | 控制命令 | 仓位选择、LED 控制、气缸控制、复位 |
| DB12 | 状态监控 | 仓位故障/运行状态、IO 模块状态、报警文本 |
| DB24 | AGV 交互 | 料架/AGV 任务状态、托盘信息 |

### 料架类型与编号范围

| 类型 | 编号范围 | 说明 |
|------|---------|------|
| 阴极冷压 | 1~14 | 主机号上限 14 |
| 阳极冷压 | 1~12 | 主机号上限 12 |
| 阴极模切 | 1~70 | V5+ 软件支持上限 70 |
| 阳极模切 | 1~70 | V5+ 软件支持上限 70 |

---

## 许可证

本项目为私有仓库，仅供内部开发使用。

---

> 💡 **提示**：运行前请确保 `snap7.dll` 位于程序目录或系统 PATH 中。首次使用建议先通过 ARP 扫描确认 PLC 网络连通性。
