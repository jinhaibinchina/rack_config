# AGENTS.md — 项目说明（供 AI 编码代理阅读）

## 项目概述

**PopPick / Robot Teach Pendant** 是一个面向三轴直角坐标机械臂（桁架机器人）的**离线编程 / 示教器桌面工具**，使用 **Python 3.12 + PySide6** 开发，运行在 Windows 上。

它实现了一门自定义的机器人脚本语言（类似 CodeSys / 工业机器人指令集：`MOVJ`、`MOVL`、`MOVC`、`IF/WHILE/FOR`、`SET_DO`、`PR` 位置寄存器等），包含：

- **编译器**（`complier.py`，注意拼写是 complier 不是 compiler）：源码 → 词法分析 → 语法分析（AST）→ 代码生成，输出指令列表 `List[Instruction]`；
- **示教器 GUI**（`robot_teach_pendant.py`）：代码编辑器（语法高亮、行号、CodeSys 风格自动补全/签名提示）、点位表、3D 可视化、程序下载/上载；
- **PLC 通信**（`com.py`）：通过 **Modbus TCP（pymodbus）** 与**汇川 AM521 PLC** 通信，下载编译后的程序、读写点位、轮询实时 TCP 坐标。

目标设备协议称为 **PopPick 解释器协议**（当前编译器 v3.1 AST 版，在 v3.0 基础上新增 VAR/CONST 变量声明与符号表）。仓库中的 `PopPick_V1.9.0.robot` / `PopPick_V1.9.1.robot` / `PopPick_V1.9.9.robot` 是该语言的示例程序，PLC 侧解释器源码见 `FB_RobotInterpreter_v2.0_新协议.st`。

## 运行环境与技术栈

- Python 3.12，虚拟环境在项目根目录 `.venv/`（已装好依赖，**没有 requirements.txt / pyproject.toml**，依赖以 `.venv` 为准）：
  - `PySide6`（含 `QtWebEngineWidgets`，用于内嵌 3D 视图）
  - `pymodbus 3.11.0`（Modbus TCP 客户端）
  - `PyInstaller 6.x`（打包）
  - `numpy`、`matplotlib`、`Pillow` 等（辅助）
- 3D 可视化基于 **Three.js**：`robot3D.py` 生成内嵌 HTML（引用本地 `three.min.js`），在 `QWebEngineView` 中渲染。

## 代码组织与模块划分

| 文件 | 职责 |
|---|---|
| `complier.py` | 编译器核心（约 2400 行）：`OpCode` 枚举、`Instruction` 数据类（含 `to_regs()`/`from_regs()` 与 PLC 寄存器布局互转）、`Lexer` → `Parser` → `CodeGenerator` 三段式编译、`RobotParser` / `RobotFormatter` 对外 API；v3.1 新增 `VarSymbol` 符号表、`VAR`/`CONST` 声明、`ELSIF`、`END_IF`/`END_WHILE`/`END_FOR` 别名与中文标识符支持。 |
| `robot_teach_pendant.py` | 主程序 / GUI 入口（约 1750 行）：`QMainWindow` 示教器界面、`CodeEditor`（补全、语法高亮、行号、变量悬停/重命名）、点位表、程序树、下载/上载逻辑。**这是 PyInstaller 打包的入口脚本。** |
| `com.py` | `ModbusClient`（寄存器地址规划、float32↔寄存器转换、程序/点位/WSTRING 文本读写，兼容多个 pymodbus 版本的参数名 `slave`/`unit`/`unit_id`）、`SignalBridge`、`TcpPositionWorker`（后台线程轮询 PLC TCP 坐标与系统状态）。 |
| `robot3D.py` | 3D 视图配置与内嵌 Three.js HTML 模板；行程范围常量（X/Y/Z_MIN/MAX_3D）对应真实设备。 |
| `FB_RobotInterpreter_v2.0_新协议.st` | 汇川 AM521 PLC 侧解释器源码（结构化文本，约 920 行，2026-09）：指令执行状态机 + `ParseCmdSeq`，适配新协议的 `IF` 条件跳转 + `JUMP` 16 位绝对地址；`ELSE/ENDIF/WHILE/FOR` 等旧指令视为 Obsolete。**PLC 上实际运行的程序，编译协议必须与它保持一致。** |
| `test_complier.py` | 编译器测试套件（见下）。 |
| `packTool.py` | 独立的 PyInstaller 可视化打包工具（通用工具，非本项目核心逻辑）。 |
| `PopPick.spec` | PyInstaller spec 文件，入口 `robot_teach_pendant.py`，产物名 `PopPick`（console=True）。**注意 spec 里的 `pathex` 是旧路径 `C:/Users/GPD/Desktop/3AxisRobot`，移动目录后需修正。** |
| `bf/` | 旧版本备份（`complier.py`、`robot_teach_pendant.py` 的旧拷贝，与根目录当前版本有差异），不要修改，也不要 import。 |
| `build/`、`dist/`、`__pycache__/` | 构建产物，已在 `.gitignore` 中。 |

### Modbus 寄存器地址规划（`com.py` 中的常量）

- 程序区：`41000`–`45000`（每条指令 8 个寄存器，`45000` 写 `[程序长度, 1]`）
- 点位区：`45100` 起，每点 12 寄存器（x,y,z,j1,j2,j3 各为 float32 占 2 寄存器）
- 系统输入 `46000` / 系统输出 `46100` / 实时 TCP 坐标 `46200`（float32×3）
- 文本行（WSTRING 数组）：`47000` 起，步长 151 寄存器，UTF-16-BE
- 默认 PLC 地址 `192.168.1.88:502`

### 编译器 v3.1 协议要点（修改编译器前必读 `complier.py` 文件头注释）

- 控制流扁平化：`IF` = 条件不成立则跳转（p5/p6 为 16 位绝对地址的高/低 8 位）；`WHILE`/`FOR`/`BREAK`/`CONTINUE`/`ELSIF` 在编译期展开为 `IF + JUMP`，不再生成对应指令（枚举值保留仅为兼容 PLC 上载的旧程序）。`END_IF`/`END_WHILE`/`END_FOR` 与 `ENDIF`/`ENDWHILE`/`ENDFOR` 等价。
- 变量声明（v3.1，纯编译期特性，PLC 解释器无需修改）：`VAR name [: INT|REAL|BOOL] = 初值;` 分配 V 寄存器（V[0] 起向上）；`CONST name = 常量表达式;` 编译期替换、不占寄存器，可用作符号化地址（如 `GET_DI(DI_START)`/`P[HOME]`）。标识符大小写不敏感、支持中文；`RobotParser.parse_full()` 返回 `(program, symbols)`，`RobotFormatter.format(program, symbols)` 在反汇编头部打印符号表。
- 编译器临时寄存器约定：**V[60]~V[62] 为编译器保留**，用户变量用 V[0]~V[59]；上限见 `MAX_VAR_INDEX=63`、`MAX_POINT_INDEX=31`、`MAX_PROGRAM_LEN=500`、`MAX_PR_INDEX=15`、`MAX_IO_INDEX=255`。

## 构建与测试命令

```bash
# 激活环境（Git Bash）
source .venv/Scripts/activate

# 运行测试（compile 编译器测试套件，自带指令级 VM 做语义验证）
# 注意：Windows 控制台默认 GBK 编码，必须加 PYTHONUTF8=1 否则打印 ✓ 会 UnicodeEncodeError
PYTHONUTF8=1 .venv/Scripts/python.exe test_complier.py
# 期望输出结尾：全部测试通过 ✔

# 运行 GUI（无 PLC 也能启动，Modbus 连接失败仅影响下载/实时坐标）
.venv/Scripts/python.exe robot_teach_pendant.py

# 打包 exe（产物在 dist/）
.venv/Scripts/python.exe -m PyInstaller PopPick.spec
```

## 代码风格与开发约定

- **注释、文档字符串、GUI 文案均为中文**，提交信息/文档也用中文；修改代码时保持这一惯例。
- 文件头统一 `# -*- coding: utf-8 -*-`。
- 代码风格：类型标注（`typing.List/Dict/Optional`）、`dataclass`、`IntEnum`；编译器内用全大写常量集中管理协议参数。
- 三个模块间是紧耦合的星型依赖：GUI `import *` 自 `complier` 和 `robot3D`，`com.py` 只依赖 `complier.Instruction`。修改 `complier.py` 的公开 API（文件头列出的名字）会同时影响 GUI 与测试。
- `bf/` 目录是历史快照，不要把它当作可复用代码来源。
- 注释掉的旧实现（如 `com.py` 中旧版 `write_text_lines`）是有意保留的协议参考，不要随意删除。

## 测试策略

- 只有一套测试：`test_complier.py`，**直接以脚本方式运行**（非 pytest），内置 `vm_run()` 指令级虚拟机按新协议语义（IF=条件不成立跳转 + JUMP）执行编译产物做端到端验证，并覆盖词法/语法/代码生成/边界校验/反汇编、变量声明（`test_var_decl`）与 GUI 的 32 个代码模板。
- **修改 `complier.py` 后必须运行该测试并保持全绿**；新增语言特性时应同步在测试套件与 GUI 的补全/模板数据中补充用例。
- 通信层（`com.py`）与 GUI 无自动化测试，依赖真实汇川 AM521 PLC 联调验证。

## 安全与部署注意事项

- 默认直连内网 PLC（`192.168.1.88:502`），程序会在 `write_program` 时**覆盖 PLC 程序区与文本区寄存器**——调试下载功能时注意目标设备是否在生产运行。
- `packTool.py` / PyInstaller 打包输出到 `dist/`；`PopPick.spec` 中硬编码了旧的绝对路径 `pathex`，换机器/换目录打包前先修正。
- 仓库无密钥类敏感文件；`.venv`、`build/`、`dist/` 已在 `.gitignore`。
