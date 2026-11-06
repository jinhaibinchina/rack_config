# -*- coding: utf-8 -*-
"""
Robot 指令编译器 v3.3 (AST 版)
================================
兼容汇川 AM521 PLC 解释器协议 (PopPick)，采用三段式编译架构：

    源码 ──> Lexer(词法分析) ──> Parser(语法分析 → AST) ──> CodeGenerator(代码生成) ──> List[Instruction]

与旧版（v2.x 正则行解析）的协议差异：
----------------------------------------------------------------
1. 控制流扁平化：IF 指令语义改为「条件不成立则跳转到 p5/p6 指定的绝对地址」，
   编译器不再生成 ELSE / ENDIF / WHILE / ENDWHILE / FOR / ENDFOR 指令，
   WHILE / FOR / BREAK / CONTINUE 均在编译期展开为 IF + JUMP。
2. 跳转地址为 16 位：p5 = 高 8 位，p6 = 低 8 位（0..65535），
   允许跳转到 len(program)（即程序末尾，等价于结束）。
3. 条件表达式支持 NOT / AND / OR 任意嵌套与括号分组：
       IF (V[0] == 1 OR V[1] == 2) AND NOT V[2] == 3 THEN
4. 赋值表达式支持 + - * /、括号、一元负号、常量折叠，
   并可内嵌 GET_DI() / GET_DO() / DISTANCE_TO() / IS_MOVING() / GET_OVERALL()：
       V[0] = (V[1] + 2) * 3 - V[2] / 4;
5. 比较条件两侧支持任意表达式（复杂表达式由编译器先算入临时寄存器）：
       IF V[0] + 1 > V[1] * 2 THEN
6. MOVJ/MOVL 支持 5 参数形式 MOVJ(P[n],Vxx,Cxx,acc,dec)，
   MOVC 支持 6 参数形式，acc/dec 存入指令 f1/f2。

编译器临时寄存器约定：
    V[60] ~ V[62] 为编译器临时寄存器区（表达式求值、FOR 步长累加使用），
    用户程序请优先使用 V[0] ~ V[59]；V[60]~V[62] 仅可安全地进行简单赋值，
    不能作为 FOR 循环变量，也不能在复杂表达式中读写混用。

v3.1 变量声明（纯编译期特性，PLC 解释器无需修改）：
    VAR count : INT = 0;        // 声明变量，编译器分配 V 寄存器（V[0] 起向上）
    CONST MAX_RETRY = 3;        // 常量，编译期直接替换，不占寄存器
    FOR i = 1 TO 10 DO          // 循环变量可用名字
    count = count + 1;          // 赋值/表达式/条件中可直接用名字
    - 名字大小写不敏感；必须先声明后使用；VAR/CONST 只能放在程序开头；
    - 布尔字面量 TRUE / FALSE；类型注解 INT/REAL/BOOL 仅作初值校验；
    - CONST 名字可用于一切整数位置（符号化地址）：
          GET_DI(DI_START) / SET_DO(DO_CLAMP) / P[HOME] / V[BUF] ...
    - RobotParser.parse_full(text) 可同时取回符号表（名字 → V[n] 映射），
      供示教器按名监视变量；RobotFormatter.format(program, symbols) 会在
      反汇编列表头部打印符号表。

v3.2 子程序（CALL / RET，需要配套 v3.2 版 PLC 解释器）：
    SUB 取箱流程:               // 子程序定义，必须放在主程序之后
        MOVJ P[10], V50, FINE;
        RET;                    // 可省略，END_SUB 会自动补齐返回
    END_SUB

    CALL 取箱流程;              // 主程序/子程序中均可调用（支持前向引用）

    - 指令编码：CALL = op 72（p5/p6 = 子程序入口 16 位绝对地址），RET = op 73；
    - PLC 侧维护深度 16 的调用栈，栈溢出/空栈返回均进入 ST_ERR；
    - 禁止递归与循环调用（编译期检测调用环，直接报错）；
    - 主程序末尾由编译器自动补一条 JUMP 到程序末尾，防止执行流跌入子程序区；
    - 子程序名大小写不敏感、允许中文，不能与变量/常量或其它子程序重名。

v3.4 带参数的子程序（纯编译期特性，PLC 解释器无需再改）：
    SUB 取箱(库位, 数量):
        MOVJ P[10], V50, FINE;
        V[0] = 库位 * 数量;     // 形参可读写（值传递，改形参不影响调用方）
    END_SUB

    CALL 取箱(3, cnt + 1);      // 实参可以是任意表达式，按序求值

    - 形参落在约定寄存器带：第一层被调子程序用 V[50]~V[54]，
      第二层被调子程序用 V[55]~V[59]（按调用图最深路径分带，同层子程序
      不会同时活跃，共享安全）；每个子程序最多 5 个形参；
    - 带参子程序最多嵌套 2 层调用（不带参的不限层数，运行栈深度 16）；
    - 编译器自动在 CALL 前生成实参求值指令；形参名只在子程序体内可见，
      不能与全局变量/常量重名。

v3.3 寄存器别名（MAP，纯编译期特性，PLC 解释器无需修改）：
    MAP 延时参数 TO V[40];    // 把 V[40] 绑定到名字，之后可用名字读写
    MOVJ_DO(P[1],V80,C0,延时参数,DO[2],1);   // 等价于 do_delay 写 V[40]
    - MAP 与 VAR/CONST 一样只能放在程序开头；不占新寄存器、不生成初始化指令；
    - 别名专用区：只能映射 V[40]~V[49]，且 VAR 自动分配会跳过整个专用区
      （用户变量可用区间：V[0]~V[39]、V[50]~V[59]，共 50 个）；
    - 一个寄存器只允许一个别名；别名是变量，不能用于整数索引位置（同 VAR）。

v3.5 源码级调试映射（SourceMap，纯编译期特性，PLC 解释器无需修改）：
    编译器自动生成 addr_to_line（指令地址 → 源码行号）和 sub_entries
    （子程序名 → 入口地址），供示教器实现源码级单步、断点与按名监视。
    - 下载程序时同时生成 .map 文件，与 .robot 同名；
    - 打开程序时自动加载 .map，恢复调试映射，无需重新编译；
    - 经 PeepholeOptimizer 压缩后，映射地址会自动重映射。

v3.6 设备描述表（DeviceProfile，纯编译期重构，行为与 v3.5 完全一致）：
    把设备相关的硬编码（指令关键字、过渡带/速度档、PR 分量、比较符表、
    寄存器上下限、MAP 专用区、形参寄存器带）收敛为 DeviceProfile 数据类；
    Lexer/Parser/CodeGenerator/RobotParser 均接受可选 profile 参数，
    不传则使用 DEFAULT_PROFILE（AM521）。换设备 = 提供新的 DeviceProfile
    （及相应的传输适配），编译核心与示教器 UI 全复用。

公开 API（与旧版兼容，示教器 GUI 直接 import 使用）：
    OpCode, OPCODE_NAMES, NAME_TO_OPCODE, CMP_NAMES, CMP_MAP,
    Instruction, ParseError, RobotParser, RobotFormatter, VarSymbol,
    SourceMap, DeviceProfile, DEFAULT_PROFILE, AM521_PROFILE, TEMP_VAR_INDEX, ...
    OpCode, OPCODE_NAMES, NAME_TO_OPCODE, CMP_NAMES, CMP_MAP,
    Instruction, ParseError, RobotParser, RobotFormatter, VarSymbol,
    SourceMap, TEMP_VAR_INDEX, TEMP_VAR_BOTTOM, MAX_VAR_INDEX, MAX_POINT_INDEX,
    MAX_PROGRAM_LEN, MAX_PR_INDEX
"""

from typing import List, Optional, Dict, Tuple, Any
from enum import IntEnum, Enum, auto
from dataclasses import dataclass, field

# ============================================================================
# 常量与 OpCode
# ============================================================================
class OpCode(IntEnum):
    NOP = 0
    MOVJ = 1; MOVL = 2; MOVC = 3
    MOVJ_DO = 4; MOVL_DO = 5; MOVC_DO = 6
    DELAY = 10
    SET_DO = 20; RESET_DO = 21; WAIT_DI = 22; GET_DI = 23; GET_DO = 24; ISIGNAL_DI = 26
    # 控制流改造：IF 变为「条件为假则跳转到 p5/p6 地址」，
    # 新编译器不再生成 ELSE/ENDIF/WHILE/ENDWHILE/FOR/ENDFOR
    IF = 30
    JUMP = 50
    CALL = 72; RET = 73   # v3.2 子程序调用/返回（p5/p6 = 入口绝对地址）
    STOP = 99
    ASSIGN = 40; ADD = 41; SUB = 42; MUL = 43; DIV = 44
    # 以下保留枚举值以兼容旧数据（例如从 PLC 上载的老程序），新编译器不再生成
    ELSE = 31; ENDIF = 32; WHILE = 33; ENDWHILE = 34
    FOR = 60; ENDFOR = 61; BREAK = 70; CONTINUE = 71
    LABEL = 100
    # PR (位置寄存器) 指令
    PR_CURPOS = 110; PR_ASSIGN_P = 111; PR_ADD_VEC = 112; PR_SUB_VEC = 113
    PR_SET_COMP = 114; P_ASSIGN_PR = 115; PR_MUL_SCALAR = 116
    SERVO_ON = 120; SERVO_OFF = 121; SET_ACCE = 122
    STOPON_DI = 130; IS_MOVING = 131
    DISTANCE_TO = 150
    WAIT_MOTION_DONE = 151   # 新增：等待运动完成
    SET_OVERALL = 160; GET_OVERALL = 161


OPCODE_NAMES: Dict[int, str] = {
    OpCode.NOP: "NOP", OpCode.MOVJ: "MOVJ", OpCode.MOVL: "MOVL", OpCode.MOVC: "MOVC",
    OpCode.MOVJ_DO: "MOVJ_DO", OpCode.MOVL_DO: "MOVL_DO", OpCode.MOVC_DO: "MOVC_DO",
    OpCode.DELAY: "DELAY", OpCode.SET_DO: "SET_DO", OpCode.RESET_DO: "RESET_DO",
    OpCode.WAIT_DI: "WAIT_DI", OpCode.GET_DI: "GET_DI", OpCode.GET_DO: "GET_DO",
    OpCode.ISIGNAL_DI: "ISIGNAL_DI",
    OpCode.IF: "IF", OpCode.JUMP: "JUMP", OpCode.STOP: "STOP",
    OpCode.CALL: "CALL", OpCode.RET: "RET",
    OpCode.ASSIGN: "ASSIGN", OpCode.ADD: "ADD", OpCode.SUB: "SUB",
    OpCode.MUL: "MUL", OpCode.DIV: "DIV",
    # 兼容旧协议
    OpCode.ELSE: "ELSE", OpCode.ENDIF: "ENDIF",
    OpCode.WHILE: "WHILE", OpCode.ENDWHILE: "ENDWHILE",
    OpCode.FOR: "FOR", OpCode.ENDFOR: "ENDFOR",
    OpCode.BREAK: "BREAK", OpCode.CONTINUE: "CONTINUE",
    OpCode.LABEL: "LABEL",
    OpCode.PR_CURPOS: "PR_CURPOS", OpCode.PR_ASSIGN_P: "PR_ASSIGN_P",
    OpCode.PR_ADD_VEC: "PR_ADD_VEC", OpCode.PR_SUB_VEC: "PR_SUB_VEC",
    OpCode.PR_SET_COMP: "PR_SET_COMP", OpCode.P_ASSIGN_PR: "P_ASSIGN_PR",
    OpCode.PR_MUL_SCALAR: "PR_MUL_SCALAR",
    OpCode.SERVO_ON: "SERVO_ON", OpCode.SERVO_OFF: "SERVO_OFF",
    OpCode.SET_ACCE: "SET_ACCE",
    OpCode.STOPON_DI: "STOPON_DI", OpCode.IS_MOVING: "IS_MOVING",
    OpCode.DISTANCE_TO: "DISTANCE_TO",
    OpCode.WAIT_MOTION_DONE: "WAIT_MOTION_DONE",
    OpCode.SET_OVERALL: "SET_OVERALL", OpCode.GET_OVERALL: "GET_OVERALL",
}
NAME_TO_OPCODE: Dict[str, int] = {v: k for k, v in OPCODE_NAMES.items()}

CMP_NAMES = {0: ">", 1: "<", 2: "==", 3: ">=", 4: "<=", 5: "!="}
CMP_MAP = {">": 0, "<": 1, "==": 2, ">=": 3, "<=": 4, "<>": 5, "!=": 5, "=": 2}
CMP_NEGATE = {0: 4, 1: 3, 2: 5, 3: 1, 4: 0, 5: 2}
CMP_SWAP = {">": "<", "<": ">", ">=": "<=", "<=": ">=", "==": "==", "!=": "!=", "=": "==", "<>": "!="}

TEMP_VAR_INDEX = 62
TEMP_VAR_BOTTOM = 60
MAP_VAR_BOTTOM = 40
MAP_VAR_TOP = 49
PARAM_VIRT_BASE = 100
PARAM_BAND_1 = 50
PARAM_BAND_2 = 55
PARAM_BAND_SIZE = 5
PARAM_MAX_DEPTH = 2
FAKE_IF_MARKER = -1
MAX_VAR_INDEX = 63
MAX_POINT_INDEX = 31
MAX_PROGRAM_LEN = 500
MAX_PR_INDEX = 15
MAX_IO_INDEX = 31


@dataclass
class Instruction:
    op: int = 0
    p1: int = 0
    p2: int = 0
    p3: int = 0
    p4: int = 0
    p5: int = 0
    p6: int = 0
    f1: float = 0.0
    f2: float = 0.0
    src_line: int = 0

    def to_regs(self) -> List[int]:
        def split_fixed(val: float):
            vi = int(val * 1000)
            if vi < 0:
                vi += 0x100000000
            low = vi & 0xFFFF
            high = (vi >> 16) & 0xFFFF
            return low, high
        l1, h1 = split_fixed(self.f1)
        l2, h2 = split_fixed(self.f2)
        return [
            self.op,
            (self.p1 << 8) | (self.p2 & 0xFF),
            (self.p3 << 8) | (self.p4 & 0xFF),
            (self.p5 << 8) | (self.p6 & 0xFF),
            l1, h1, l2, h2,
            self.src_line
        ]

    @classmethod
    def from_regs(cls, regs: List[int], src_line: int = 0) -> "Instruction":
        def combine(low: int, high: int) -> float:
            v = (high << 16) | low
            if v >= 0x80000000:
                v -= 0x100000000
            return v / 1000.0
        return cls(
            regs[0],
            (regs[1] >> 8) & 0xFF,
            regs[1] & 0xFF,
            (regs[2] >> 8) & 0xFF,
            regs[2] & 0xFF,
            (regs[3] >> 8) & 0xFF,
            regs[3] & 0xFF,
            combine(regs[4], regs[5]),
            combine(regs[6], regs[7]),
            src_line
        )

    def jump_addr(self) -> int:
        return (self.p5 << 8) | self.p6

    def set_jump_addr(self, addr: int):
        self.p5 = (addr >> 8) & 0xFF
        self.p6 = addr & 0xFF


class ParseError(Exception):
    def __init__(self, msg: str, line_no: int = 0):
        super().__init__(msg)
        self.line_no = line_no


# ============================================================================
# Token 定义
# ============================================================================
class TokenType(Enum):
    MOVJ = auto(); MOVL = auto(); MOVC = auto()
    MOVJ_DO = auto(); MOVL_DO = auto(); MOVC_DO = auto()
    DELAY = auto(); SET_DO = auto(); RESET_DO = auto(); WAIT_DI = auto()
    WAIT_MOTION_DONE = auto()
    GET_DI = auto(); GET_DO = auto(); ISIGNAL_DI = auto()
    IF = auto(); THEN = auto(); ELSE = auto(); ELSIF = auto(); END_IF = auto()
    WHILE = auto(); DO = auto(); END_WHILE = auto()
    FOR = auto(); TO = auto(); STEP = auto(); END_FOR = auto()
    BREAK = auto(); CONTINUE = auto(); JUMP = auto(); STOP = auto()
    VAR = auto(); CONST = auto()
    SUB = auto(); END_SUB = auto(); CALL = auto(); RET = auto()
    MAP = auto()
    SERVO = auto(); ON = auto(); OFF = auto()
    SET_ACCE = auto(); STOPON = auto()
    DISTANCE_TO = auto(); IS_MOVING = auto()
    SET_OVERALL = auto(); GET_OVERALL = auto()
    CURPOS = auto()
    AND = auto(); OR = auto(); NOT = auto()
    PR = auto(); P = auto(); V = auto(); DI = auto()
    X = auto(); Y = auto(); Z = auto(); J1 = auto(); J2 = auto(); J3 = auto()
    TRANSITION = auto()
    NUMBER = auto()
    LPAREN = auto(); RPAREN = auto()
    LBRACKET = auto(); RBRACKET = auto()
    COMMA = auto(); SEMI = auto()
    ASSIGN = auto()
    EQ = auto()
    EQEQ = auto(); NEQ = auto()
    GE = auto(); LE = auto(); GT = auto(); LT = auto()
    PLUS = auto(); MINUS = auto(); MUL = auto(); DIV = auto()
    DOT = auto(); COLON = auto()
    IDENT = auto()
    EOL = auto(); EOF = auto()


KEYWORDS = {
    'MOVJ': TokenType.MOVJ, 'MOVL': TokenType.MOVL, 'MOVC': TokenType.MOVC,
    'MOVJ_DO': TokenType.MOVJ_DO, 'MOVL_DO': TokenType.MOVL_DO, 'MOVC_DO': TokenType.MOVC_DO,
    'DELAY': TokenType.DELAY, 'SET_DO': TokenType.SET_DO, 'RESET_DO': TokenType.RESET_DO,
    'WAIT_DI': TokenType.WAIT_DI, 'WAIT_MOTION_DONE': TokenType.WAIT_MOTION_DONE,
    'GET_DI': TokenType.GET_DI, 'GET_DO': TokenType.GET_DO,
    'ISIGNAL_DI': TokenType.ISIGNAL_DI,
    'IF': TokenType.IF, 'THEN': TokenType.THEN, 'ELSE': TokenType.ELSE,
    'ELSIF': TokenType.ELSIF, 'ENDIF': TokenType.END_IF, 'END_IF': TokenType.END_IF,
    'WHILE': TokenType.WHILE, 'DO': TokenType.DO,
    'ENDWHILE': TokenType.END_WHILE, 'END_WHILE': TokenType.END_WHILE,
    'FOR': TokenType.FOR, 'TO': TokenType.TO, 'STEP': TokenType.STEP,
    'ENDFOR': TokenType.END_FOR, 'END_FOR': TokenType.END_FOR,
    'BREAK': TokenType.BREAK, 'CONTINUE': TokenType.CONTINUE,
    'JUMP': TokenType.JUMP, 'STOP': TokenType.STOP,
    'VAR': TokenType.VAR, 'CONST': TokenType.CONST,
    'SUB': TokenType.SUB, 'ENDSUB': TokenType.END_SUB, 'END_SUB': TokenType.END_SUB,
    'CALL': TokenType.CALL, 'RET': TokenType.RET,
    'MAP': TokenType.MAP,
    'ON': TokenType.ON, 'OFF': TokenType.OFF,
    'SET_ACCE': TokenType.SET_ACCE, 'STOPON': TokenType.STOPON,
    'DISTANCE_TO': TokenType.DISTANCE_TO, 'IS_MOVING': TokenType.IS_MOVING,
    'SET_OVERALL': TokenType.SET_OVERALL, 'GET_OVERALL': TokenType.GET_OVERALL,
    'CURPOS': TokenType.CURPOS,
    'AND': TokenType.AND, 'OR': TokenType.OR, 'NOT': TokenType.NOT,
    'PR': TokenType.PR, 'P': TokenType.P, 'V': TokenType.V,
    'DI': TokenType.DI, 'DO': TokenType.DO,
    'X': TokenType.X, 'Y': TokenType.Y, 'Z': TokenType.Z,
    'J1': TokenType.J1, 'J2': TokenType.J2, 'J3': TokenType.J3,
    'FINE': TokenType.TRANSITION,
    'C0': TokenType.TRANSITION, 'C25': TokenType.TRANSITION, 'C50': TokenType.TRANSITION,
    'C60': TokenType.TRANSITION, 'C70': TokenType.TRANSITION, 'C80': TokenType.TRANSITION,
    'C85': TokenType.TRANSITION, 'C90': TokenType.TRANSITION, 'C95': TokenType.TRANSITION,
    'C100': TokenType.TRANSITION,
}

TRANS_MAP = {'C0': 0, 'C25': 1, 'C50': 2, 'C60': 3, 'C70': 4,
             'C80': 5, 'C85': 6, 'C90': 7, 'C95': 8, 'C100': 9, 'FINE': 10}
SPEED_VALUES = (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
PR_COMP_MAP = {'X': 0, 'Y': 1, 'Z': 2, 'J1': 3, 'J2': 4, 'J3': 5}

# ============================================================================
# DeviceProfile（v3.6）：设备描述表 —— 换设备即换一张表
# ============================================================================
@dataclass
class DeviceProfile:
    """设备描述：指令关键字、过渡带/速度档、PR 分量、比较符表、
    寄存器模型与各上限。所有字段均为纯数据，编译器各阶段注入后
    不再引用模块级硬编码。dict 字段在构造默认实例时复制，
    保证各 profile 互不影响。"""
    name: str
    keywords: Dict[str, TokenType]     # 指令助记符 / 控制关键字 / 内建函数 → Token
    transition_map: Dict[str, int]     # FINE/C0..C100 → 过渡带编码
    speed_values: Tuple[int, ...]      # 合法速度档（V10..V100）
    pr_comp_map: Dict[str, int]        # PR 分量名 → 编号
    cmp_names: Dict[int, str]
    cmp_map: Dict[str, int]
    cmp_negate: Dict[int, int]
    cmp_swap: Dict[str, str]
    temp_var_bottom: int               # 编译器临时寄存器区下界
    temp_var_index: int                # 编译器临时寄存器区上界
    map_var_bottom: int                # MAP 别名专用区下界
    map_var_top: int                   # MAP 别名专用区上界
    param_virt_base: int               # 形参虚拟编号基址（纯编译期）
    param_band_1: int                  # 第一层被调子程序形参寄存器基址
    param_band_2: int                  # 第二层被调子程序形参寄存器基址
    param_band_size: int               # 每层形参寄存器带宽度
    param_max_depth: int               # 带参子程序最大嵌套层数
    max_var_index: int
    max_point_index: int
    max_program_len: int
    max_pr_index: int
    max_io_index: int


def _default_profile() -> DeviceProfile:
    """AM521（PopPick）设备描述表 —— 与 v3.5 及之前版本的硬编码完全一致"""
    return DeviceProfile(
        name="AM521",
        keywords=dict(KEYWORDS),
        transition_map=dict(TRANS_MAP),
        speed_values=tuple(SPEED_VALUES),
        pr_comp_map=dict(PR_COMP_MAP),
        cmp_names=dict(CMP_NAMES),
        cmp_map=dict(CMP_MAP),
        cmp_negate=dict(CMP_NEGATE),
        cmp_swap=dict(CMP_SWAP),
        temp_var_bottom=TEMP_VAR_BOTTOM,
        temp_var_index=TEMP_VAR_INDEX,
        map_var_bottom=MAP_VAR_BOTTOM,
        map_var_top=MAP_VAR_TOP,
        param_virt_base=PARAM_VIRT_BASE,
        param_band_1=PARAM_BAND_1,
        param_band_2=PARAM_BAND_2,
        param_band_size=PARAM_BAND_SIZE,
        param_max_depth=PARAM_MAX_DEPTH,
        max_var_index=MAX_VAR_INDEX,
        max_point_index=MAX_POINT_INDEX,
        max_program_len=MAX_PROGRAM_LEN,
        max_pr_index=MAX_PR_INDEX,
        max_io_index=MAX_IO_INDEX,
    )


DEFAULT_PROFILE = _default_profile()
# AM521 是默认设备，直接引用同一张表；接新设备时新建 DeviceProfile 注入即可
AM521_PROFILE = DEFAULT_PROFILE


@dataclass
class Token:
    type: TokenType
    value: Any
    line: int
    col: int


def _tok_desc(t: Token) -> str:
    if t.type == TokenType.NUMBER:
        return f"数字 {t.value}"
    if t.type == TokenType.EOF:
        return "文件结尾"
    if t.type == TokenType.EOL:
        return "换行"
    if t.type == TokenType.V and isinstance(t.value, int):
        return f"速度值 V{t.value}"
    return f"'{t.value}'"


# ============================================================================
# Lexer（词法分析）
# ============================================================================
class Lexer:
    def __init__(self, text: str, profile: "DeviceProfile" = None):
        self.profile = profile or DEFAULT_PROFILE
        self.text = text
        self.pos = 0
        self.line = 1
        self.col = 1

    def _advance(self):
        if self.pos < len(self.text):
            if self.text[self.pos] == '\n':
                self.line += 1
                self.col = 1
            else:
                self.col += 1
            self.pos += 1

    def _skip_whitespace(self):
        while self.pos < len(self.text) and self.text[self.pos] in ' \t\r':
            self._advance()

    def _skip_comment(self):
        while self.pos < len(self.text) and self.text[self.pos] != '\n':
            self._advance()

    def _read_number(self) -> Token:
        start_line, start_col = self.line, self.col
        num_str = ''
        has_dot = False
        has_exp = False
        while self.pos < len(self.text):
            c = self.text[self.pos]
            if c.isdigit():
                num_str += c
                self._advance()
            elif c == '.' and not has_dot and not has_exp:
                num_str += c
                has_dot = True
                self._advance()
            elif c in 'eE' and not has_exp and num_str and num_str != '.':
                p = self.pos + 1
                if p < len(self.text) and (
                    self.text[p].isdigit()
                    or (self.text[p] in '+-' and p + 1 < len(self.text) and self.text[p + 1].isdigit())
                ):
                    num_str += 'e'
                    has_exp = True
                    self._advance()
                    if self.pos < len(self.text) and self.text[self.pos] in '+-':
                        num_str += self.text[self.pos]
                        self._advance()
                else:
                    break
            else:
                break
        try:
            val = float(num_str)
        except ValueError:
            raise ParseError(f"无效数字: {num_str!r}", start_line)
        return Token(TokenType.NUMBER, val, start_line, start_col)

    def _read_identifier(self) -> Token:
        start_line, start_col = self.line, self.col
        ident = ''
        while self.pos < len(self.text):
            c = self.text[self.pos]
            if c.isalnum() or c == '_':
                ident += c
                self._advance()
            else:
                break
        upper = ident.upper()
        if upper == 'TRUE':
            return Token(TokenType.NUMBER, 1.0, start_line, start_col)
        if upper == 'FALSE':
            return Token(TokenType.NUMBER, 0.0, start_line, start_col)
        if upper.startswith('V') and len(upper) > 1 and upper[1:].isdigit():
            val = int(upper[1:])
            if val in self.profile.speed_values:
                return Token(TokenType.V, val, start_line, start_col)
            return Token(TokenType.IDENT, upper, start_line, start_col)
        if upper in ('SERVO_ON', 'SERVO_OFF'):
            return Token(TokenType.SERVO, upper, start_line, start_col)
        if upper == 'SERVO':
            self._skip_whitespace()
            p = self.pos
            word = ''
            while p < len(self.text) and self.text[p].isalpha():
                word += self.text[p].upper()
                p += 1
            if word in ('ON', 'OFF'):
                while self.pos < p:
                    self._advance()
                return Token(TokenType.SERVO, f'SERVO_{word}', start_line, start_col)
            return Token(TokenType.SERVO, 'SERVO', start_line, start_col)
        ttype = self.profile.keywords.get(upper, None)
        if ttype is None:
            return Token(TokenType.IDENT, upper, start_line, start_col)
        return Token(ttype, upper, start_line, start_col)

    def next_token(self) -> Token:
        while True:
            self._skip_whitespace()
            if self.pos >= len(self.text):
                return Token(TokenType.EOF, None, self.line, self.col)
            c = self.text[self.pos]
            c2 = self.text[self.pos:self.pos + 2]
            line, col = self.line, self.col
            if c == '\n':
                self._advance()
                return Token(TokenType.EOL, None, line, col)
            if c2 == '//' or c == '#':
                self._skip_comment()
                continue
            if c.isdigit() or (c == '.' and self.pos + 1 < len(self.text) and self.text[self.pos + 1].isdigit()):
                return self._read_number()
            if c.isalpha() or c == '_':
                return self._read_identifier()
            if c2 == ':=':
                self._advance(); self._advance()
                return Token(TokenType.ASSIGN, ':=', line, col)
            if c2 == '==':
                self._advance(); self._advance()
                return Token(TokenType.EQEQ, '==', line, col)
            if c2 == '!=':
                self._advance(); self._advance()
                return Token(TokenType.NEQ, '!=', line, col)
            if c2 == '<>':
                self._advance(); self._advance()
                return Token(TokenType.NEQ, '<>', line, col)
            if c2 == '>=':
                self._advance(); self._advance()
                return Token(TokenType.GE, '>=', line, col)
            if c2 == '<=':
                self._advance(); self._advance()
                return Token(TokenType.LE, '<=', line, col)
            sym_map = {
                '(': TokenType.LPAREN, ')': TokenType.RPAREN,
                '[': TokenType.LBRACKET, ']': TokenType.RBRACKET,
                ',': TokenType.COMMA, ';': TokenType.SEMI,
                '=': TokenType.EQ, '>': TokenType.GT, '<': TokenType.LT,
                '+': TokenType.PLUS, '-': TokenType.MINUS,
                '*': TokenType.MUL, '/': TokenType.DIV,
                '.': TokenType.DOT, ':': TokenType.COLON,
            }
            if c in sym_map:
                self._advance()
                return Token(sym_map[c], c, line, col)
            raise ParseError(f"非法字符: {c!r}", line)


# ============================================================================
# AST 节点
# ============================================================================
class ASTNode:
    pass


class Stmt(ASTNode):
    pass


class Expr(ASTNode):
    pass


class Condition(ASTNode):
    pass


@dataclass
class Program(ASTNode):
    stmts: List[Stmt]
    decls: List['VarDecl'] = field(default_factory=list)
    subs: List['SubDef'] = field(default_factory=list)


@dataclass
class MoveStmt(Stmt):
    op: str
    point: int
    speed: int
    trans: int
    mid_point: Optional[int] = None
    acc: Optional[float] = None
    dec: Optional[float] = None
    src_line: int = 0


@dataclass
class MoveDOStmt(Stmt):
    op: str
    point: int
    speed: int
    trans: int
    do_delay: Tuple[str, float]
    do_idx: int
    do_val: int
    mid_point: Optional[int] = None
    src_line: int = 0


@dataclass
class DelayStmt(Stmt):
    ms: float
    src_line: int = 0


@dataclass
class IOStmt(Stmt):
    op: str
    args: List[Any]
    src_line: int = 0


@dataclass
class GetIOStmt(Stmt):
    op: str
    dst_var: int
    io_idx: int
    src_line: int = 0


@dataclass
class AssignStmt(Stmt):
    dst: int
    expr: Expr
    src_line: int = 0


@dataclass
class VarDecl(Stmt):
    name: str
    index: int
    init: Optional[Expr] = None
    type_name: Optional[str] = None
    is_const: bool = False
    src_line: int = 0


@dataclass
class VarSymbol:
    name: str
    index: int
    is_const: bool
    const_val: float = 0.0
    type_name: Optional[str] = None
    src_line: int = 0
    is_map: bool = False


@dataclass
class SubDef(ASTNode):
    name: str
    body: List[Stmt]
    src_line: int = 0
    params: List[str] = field(default_factory=list)
    param_base: int = -1


@dataclass
class CallStmt(Stmt):
    name: str
    src_line: int = 0
    args: List[Expr] = field(default_factory=list)


@dataclass
class RetStmt(Stmt):
    src_line: int = 0


@dataclass
class IfStmt(Stmt):
    condition: Condition
    then_body: List[Stmt]
    else_body: List[Stmt]
    src_line: int = 0


@dataclass
class WhileStmt(Stmt):
    condition: Condition
    body: List[Stmt]
    src_line: int = 0


@dataclass
class ForStmt(Stmt):
    var: int
    start: Expr
    end: Expr
    step: float
    body: List[Stmt]
    src_line: int = 0


@dataclass
class BreakStmt(Stmt):
    src_line: int = 0


@dataclass
class ContinueStmt(Stmt):
    src_line: int = 0


@dataclass
class WaitMotionDoneStmt(Stmt):
    src_line: int = 0


@dataclass
class JumpStmt(Stmt):
    addr: int
    src_line: int = 0


@dataclass
class StopStmt(Stmt):
    src_line: int = 0


@dataclass
class ServoStmt(Stmt):
    on: bool
    src_line: int = 0


@dataclass
class SetAcceStmt(Stmt):
    acc: float
    dec: float
    src_line: int = 0


@dataclass
class StopOnStmt(Stmt):
    di_idx: int
    src_line: int = 0


@dataclass
class SetOverallStmt(Stmt):
    value: Expr
    src_line: int = 0


@dataclass
class PRStmt(Stmt):
    op: str
    args: List[Any]
    src_line: int = 0


@dataclass
class ConstExpr(Expr):
    val: float


@dataclass
class VarExpr(Expr):
    idx: int


@dataclass
class BinOpExpr(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass
class UnaryExpr(Expr):
    op: str
    operand: Expr


@dataclass
class GetDIExpr(Expr):
    idx: int


@dataclass
class GetDOExpr(Expr):
    idx: int


@dataclass
class DistanceToExpr(Expr):
    point: int


@dataclass
class IsMovingExpr(Expr):
    pass


@dataclass
class GetOverallExpr(Expr):
    pass


@dataclass
class CmpCondition(Condition):
    op: str
    left: Expr
    right: Expr


@dataclass
class AndCondition(Condition):
    left: Condition
    right: Condition


@dataclass
class OrCondition(Condition):
    left: Condition
    right: Condition


@dataclass
class NotCondition(Condition):
    cond: Condition


@dataclass
class ConstCondition(Condition):
    val: float


# ============================================================================
# 常量折叠与表达式工具
# ============================================================================
def _eval_const_cmp(op: str, a: float, b: float) -> bool:
    if op == '>':
        return a > b
    if op == '<':
        return a < b
    if op == '==':
        return abs(a - b) < 1e-9
    if op == '>=':
        return a > b or abs(a - b) < 1e-9
    if op == '<=':
        return a < b or abs(a - b) < 1e-9
    if op == '!=':
        return abs(a - b) >= 1e-9
    raise ValueError(f"无效比较符: {op}")


def fold_expr(expr: Expr, line: int = 0) -> Expr:
    if isinstance(expr, BinOpExpr):
        left = fold_expr(expr.left, line)
        right = fold_expr(expr.right, line)
        if isinstance(left, ConstExpr) and isinstance(right, ConstExpr):
            a, b = left.val, right.val
            if expr.op == '+':
                return ConstExpr(a + b)
            if expr.op == '-':
                return ConstExpr(a - b)
            if expr.op == '*':
                return ConstExpr(a * b)
            if expr.op == '/':
                if abs(b) < 1e-12:
                    raise ParseError("常量表达式除以 0", line)
                return ConstExpr(a / b)
        return BinOpExpr(expr.op, left, right)
    if isinstance(expr, UnaryExpr):
        operand = fold_expr(expr.operand, line)
        if isinstance(operand, ConstExpr):
            return ConstExpr(-operand.val if expr.op == '-' else operand.val)
        return UnaryExpr(expr.op, operand)
    return expr


def expr_var_refs(expr: Expr) -> set:
    refs = set()
    if isinstance(expr, VarExpr):
        refs.add(expr.idx)
    elif isinstance(expr, BinOpExpr):
        refs |= expr_var_refs(expr.left)
        refs |= expr_var_refs(expr.right)
    elif isinstance(expr, UnaryExpr):
        refs |= expr_var_refs(expr.operand)
    return refs


def fold_condition(cond: Condition, line: int = 0) -> Condition:
    if isinstance(cond, CmpCondition):
        left = fold_expr(cond.left, line)
        right = fold_expr(cond.right, line)
        if isinstance(left, ConstExpr) and isinstance(right, ConstExpr):
            return ConstCondition(1.0 if _eval_const_cmp(cond.op, left.val, right.val) else 0.0)
        return CmpCondition(cond.op, left, right)
    if isinstance(cond, NotCondition):
        inner = fold_condition(cond.cond, line)
        if isinstance(inner, ConstCondition):
            return ConstCondition(0.0 if inner.val != 0 else 1.0)
        return NotCondition(inner)
    if isinstance(cond, AndCondition):
        return AndCondition(fold_condition(cond.left, line), fold_condition(cond.right, line))
    if isinstance(cond, OrCondition):
        return OrCondition(fold_condition(cond.left, line), fold_condition(cond.right, line))
    return cond


# ============================================================================
# Parser（语法分析：Token 流 → AST）
# ============================================================================
_CALL_CMDS = (
    TokenType.MOVJ, TokenType.MOVL, TokenType.MOVC,
    TokenType.MOVJ_DO, TokenType.MOVL_DO, TokenType.MOVC_DO,
    TokenType.DELAY, TokenType.SET_DO, TokenType.RESET_DO, TokenType.WAIT_DI,
    TokenType.GET_DI, TokenType.GET_DO, TokenType.ISIGNAL_DI,
    TokenType.SET_ACCE, TokenType.SET_OVERALL,
)

_CMP_TOKEN_TO_STR = {
    TokenType.EQ: '==', TokenType.EQEQ: '==', TokenType.NEQ: '!=',
    TokenType.GE: '>=', TokenType.LE: '<=', TokenType.GT: '>', TokenType.LT: '<',
}


class Parser:
    def __init__(self, lexer: Lexer, profile: "DeviceProfile" = None):
        self.profile = profile or getattr(lexer, "profile", None) or DEFAULT_PROFILE
        self.lexer = lexer
        self.current = lexer.next_token()
        self.symbols: Dict[str, VarSymbol] = {}
        self._next_var_idx = 0
        self._mapped_indices: set = set()
        self.subs: Dict[str, SubDef] = {}
        self._call_sites: List[CallStmt] = []
        self._in_sub = False

    def advance(self):
        self.current = self.lexer.next_token()

    def expect(self, ttype: TokenType, hint: str = "") -> Token:
        if self.current.type == ttype:
            t = self.current
            self.advance()
            return t
        msg = f"期望 {hint or ttype.name}，但遇到 {_tok_desc(self.current)}"
        raise ParseError(msg, self.current.line)

    def match(self, *types: TokenType) -> Optional[Token]:
        if self.current.type in types:
            t = self.current
            self.advance()
            return t
        return None

    def _expect_stmt_end(self, line: int):
        if self.current.type in (TokenType.SEMI, TokenType.EOL, TokenType.EOF):
            return
        raise ParseError(
            f"语句结束后应为 ';' 或换行，但遇到 {_tok_desc(self.current)}",
            self.current.line)

    def _parse_int(self, what: str = "索引") -> int:
        if self.current.type == TokenType.IDENT:
            t = self.current
            sym = self.symbols.get(t.value)
            if sym is None:
                raise ParseError(
                    f"未声明的变量 '{t.value}'（请先在程序开头用 VAR/CONST 声明）", t.line)
            if not sym.is_const:
                raise ParseError(
                    f"{what}必须是整数常量；'{t.value}' 是变量（VAR/MAP），"
                    f"本语言不支持运行期间接寻址", t.line)
            if sym.const_val != int(sym.const_val):
                raise ParseError(
                    f"{what}必须是整数，常量 '{t.value}' = {sym.const_val}", t.line)
            self.advance()
            return int(sym.const_val)
        t = self.expect(TokenType.NUMBER, f"{what}（整数）")
        if t.value != int(t.value):
            raise ParseError(f"{what}必须是整数，得到 {t.value}", t.line)
        return int(t.value)

    def _parse_const_expr(self, what: str = "参数") -> float:
        line = self.current.line
        expr = fold_expr(self.parse_expr(), line)
        if not isinstance(expr, ConstExpr):
            raise ParseError(f"{what}必须是常量表达式", line)
        return expr.val

    def _parse_point_ref(self) -> int:
        self.expect(TokenType.P, "P[n]")
        self.expect(TokenType.LBRACKET, "'['")
        idx = self._parse_int("点位索引")
        self.expect(TokenType.RBRACKET, "']'")
        if idx > self.profile.max_point_index:
            raise ParseError(f"P[{idx}] 越界 [0..{self.profile.max_point_index}]", self.current.line)
        return idx

    def _parse_pr_ref(self) -> int:
        line = self.current.line
        self.expect(TokenType.PR, "PR[n]")
        self.expect(TokenType.LBRACKET, "'['")
        idx = self._parse_int("PR 索引")
        self.expect(TokenType.RBRACKET, "']'")
        if idx > self.profile.max_pr_index:
            raise ParseError(f"PR[{idx}] 越界 [0..{self.profile.max_pr_index}]", line)
        return idx

    def _parse_var_ref(self) -> int:
        line = self.current.line
        t = self.expect(TokenType.V, "V[n]")
        if isinstance(t.value, int):
            raise ParseError(f"速度值 V{t.value} 不能用在这里，变量请写作 V[n]", line)
        self.expect(TokenType.LBRACKET, "'['")
        idx = self._parse_int("变量索引")
        self.expect(TokenType.RBRACKET, "']'")
        if idx > self.profile.max_var_index:
            raise ParseError(f"V[{idx}] 越界 [0..{self.profile.max_var_index}]", line)
        return idx

    def _parse_speed(self) -> int:
        t = self.current
        if t.type != TokenType.V or not isinstance(t.value, int):
            raise ParseError(f"速度应为 V10~V100（如 V50），但遇到 {_tok_desc(t)}", t.line)
        self.advance()
        return (t.value // 10) - 1

    def _parse_trans(self) -> int:
        t = self.current
        if t.type != TokenType.TRANSITION:
            raise ParseError(f"过渡模式应为 C0/C25/.../C100/FINE，但遇到 {_tok_desc(t)}", t.line)
        self.advance()
        return self.profile.transition_map[t.value]

    def _parse_do_ref(self) -> int:
        self.expect(TokenType.DO, "DO[n]")
        self.expect(TokenType.LBRACKET, "'['")
        idx = self._parse_int("DO 索引")
        self.expect(TokenType.RBRACKET, "']'")
        if idx > self.profile.max_io_index:
            raise ParseError(f"DO[{idx}] 越界 [0..{self.profile.max_io_index}]", self.current.line)
        return idx

    def _parse_di_ref(self) -> int:
        self.expect(TokenType.DI, "DI[n]")
        self.expect(TokenType.LBRACKET, "'['")
        idx = self._parse_int("DI 索引")
        self.expect(TokenType.RBRACKET, "']'")
        if idx > self.profile.max_io_index:
            raise ParseError(f"DI[{idx}] 越界 [0..{self.profile.max_io_index}]", self.current.line)
        return idx

    def _alloc_var(self, name: str, line: int) -> int:
        idx = self._next_var_idx
        while idx in self._mapped_indices or self.profile.map_var_bottom <= idx <= self.profile.map_var_top:
            idx += 1
        if idx >= self.profile.temp_var_bottom:
            raise ParseError(
                f"变量声明过多：用户变量最多 50 个"
                f"（V[0]~V[39]、V[50]~V[59]；V[40]~V[49] 为 MAP 别名专用区），"
                f"声明 '{name}' 时已用尽", line)
        self._next_var_idx = idx + 1
        return idx

    def _resolve_read(self, name: str, line: int) -> Expr:
        sym = self.symbols.get(name)
        if sym is None:
            raise ParseError(
                f"未声明的变量 '{name}'（请先在程序开头用 VAR {name} = ... 声明，"
                f"或直接使用 V[n]）", line)
        if sym.is_const:
            return ConstExpr(sym.const_val)
        return VarExpr(sym.index)

    def _resolve_write(self, name: str, line: int) -> int:
        sym = self.symbols.get(name)
        if sym is None:
            raise ParseError(
                f"未声明的变量 '{name}'（请先在程序开头用 VAR {name} = ... 声明，"
                f"或直接使用 V[n]）", line)
        if sym.is_const:
            raise ParseError(f"'{name}' 是常量（CONST），不能赋值", line)
        return sym.index

    @staticmethod
    def _check_decl_type(name: str, type_name: Optional[str], val: float, line: int):
        if type_name == 'BOOL' and val not in (0.0, 1.0):
            raise ParseError(
                f"BOOL 变量 '{name}' 的初值只能是 0/1 或 TRUE/FALSE，得到 {val}", line)
        if type_name == 'INT' and val != int(val):
            raise ParseError(f"INT 变量 '{name}' 的初值必须是整数，得到 {val}", line)

    def parse_var_decl(self) -> VarDecl:
        line = self.current.line
        is_const = self.current.type == TokenType.CONST
        self.advance()
        name_tok = self.expect(TokenType.IDENT, "变量名（标识符）")
        name = name_tok.value
        if name in self.symbols:
            prev = self.symbols[name]
            raise ParseError(
                f"变量 '{name}' 重复声明（首次声明在第 {prev.src_line} 行）", line)
        type_name: Optional[str] = None
        if self.match(TokenType.COLON):
            tt = self.expect(TokenType.IDENT, "类型名（INT / REAL / BOOL）")
            type_name = tt.value
            if type_name not in ('INT', 'REAL', 'BOOL'):
                raise ParseError(
                    f"未知类型 '{type_name}'，支持 INT / REAL / BOOL", tt.line)
        init: Optional[Expr] = None
        if self.match(TokenType.EQ, TokenType.ASSIGN):
            init = self.parse_expr()
        elif is_const:
            raise ParseError(f"常量 '{name}' 必须初始化（CONST name = 常量表达式）", line)
        self._expect_stmt_end(line)
        if is_const:
            folded = fold_expr(init, line)
            if not isinstance(folded, ConstExpr):
                raise ParseError(
                    f"常量 '{name}' 的初值必须是常量表达式（不能引用变量）", line)
            self._check_decl_type(name, type_name, folded.val, line)
            self.symbols[name] = VarSymbol(name, -1, True, folded.val, type_name, line)
            return VarDecl(name, -1, folded, type_name, True, line)
        idx = self._alloc_var(name, line)
        if init is not None:
            folded_init = fold_expr(init, line)
            if isinstance(folded_init, ConstExpr):
                self._check_decl_type(name, type_name, folded_init.val, line)
        self.symbols[name] = VarSymbol(name, idx, False, 0.0, type_name, line)
        return VarDecl(name, idx, init, type_name, False, line)

    def parse_map_decl(self) -> VarDecl:
        line = self.current.line
        self.expect(TokenType.MAP)
        name_tok = self.expect(TokenType.IDENT, "变量名（标识符）")
        name = name_tok.value
        if name in self.symbols:
            prev = self.symbols[name]
            raise ParseError(
                f"变量 '{name}' 重复声明（首次声明在第 {prev.src_line} 行）", line)
        self.expect(TokenType.TO, "'TO'")
        idx = self._parse_var_ref()
        if not (self.profile.map_var_bottom <= idx <= self.profile.map_var_top):
            raise ParseError(
                f"MAP 只能映射 V[{self.profile.map_var_bottom}]~V[{self.profile.map_var_top}]（别名专用区），"
                f"V[{idx}] 不在范围内", line)
        for s in self.symbols.values():
            if s.is_map and s.index == idx:
                raise ParseError(
                    f"V[{idx}] 已被别名 '{s.name}' 映射（第 {s.src_line} 行），"
                    f"一个寄存器只能有一个别名", line)
        self._expect_stmt_end(line)
        self._mapped_indices.add(idx)
        self.symbols[name] = VarSymbol(name, idx, False, 0.0, None, line, is_map=True)
        return VarDecl(name, idx, None, None, False, line)

    def parse_named_assign(self) -> AssignStmt:
        line = self.current.line
        name = self.current.value
        self.advance()
        dst = self._resolve_write(name, line)
        if not self.match(TokenType.EQ, TokenType.ASSIGN):
            if self.current.type in _CMP_TOKEN_TO_STR:
                raise ParseError(
                    "赋值应使用 = 或 :=（比较运算符只能在 IF/WHILE 条件中使用）",
                    self.current.line)
            raise ParseError(f"变量 '{name}' 后应为赋值号 = 或 :=", self.current.line)
        expr = self.parse_expr()
        self._expect_stmt_end(line)
        return AssignStmt(dst=dst, expr=expr, src_line=line)

    def parse_sub_def(self) -> SubDef:
        line = self.current.line
        self.expect(TokenType.SUB)
        name_tok = self.expect(TokenType.IDENT, "子程序名（标识符）")
        name = name_tok.value
        if name in self.subs:
            raise ParseError(
                f"子程序 '{name}' 重复定义（首次定义在第 {self.subs[name].src_line} 行）",
                line)
        if name in self.symbols:
            raise ParseError(
                f"子程序名 '{name}' 与已声明的变量/常量重名，请换一个名字", line)
        params: List[str] = []
        if self.match(TokenType.LPAREN):
            if self.current.type != TokenType.RPAREN:
                while True:
                    ptok = self.expect(TokenType.IDENT, "形参名")
                    pname = ptok.value
                    if pname in params:
                        raise ParseError(f"形参 '{pname}' 重复", ptok.line)
                    if pname in self.symbols:
                        raise ParseError(
                            f"形参 '{pname}' 与全局变量/常量重名，请换一个名字", ptok.line)
                    params.append(pname)
                    if not self.match(TokenType.COMMA):
                        break
            self.expect(TokenType.RPAREN, "')'")
        if len(params) > self.profile.param_band_size:
            raise ParseError(
                f"子程序 '{name}' 的形参最多 {self.profile.param_band_size} 个（得到 {len(params)} 个），"
                f"参数寄存器带为 V[{self.profile.param_band_1}]~V[{self.profile.param_band_2 + self.profile.param_band_size - 1}]",
                line)
        self.match(TokenType.COLON)
        self._expect_stmt_end(line)
        for k, pname in enumerate(params):
            self.symbols[pname] = VarSymbol(pname, self.profile.param_virt_base + k, False,
                                            0.0, None, line)
        self._in_sub = True
        try:
            body = self.parse_stmt_list((TokenType.END_SUB,))
            if self.current.type != TokenType.END_SUB:
                raise ParseError(f"子程序 '{name}' 缺少 END_SUB", line)
            self.advance()
        finally:
            self._in_sub = False
            for pname in params:
                del self.symbols[pname]
        self._expect_stmt_end(line)
        sub = SubDef(name=name, body=body, src_line=line, params=params)
        self.subs[name] = sub
        return sub

    def parse_call_sub(self) -> CallStmt:
        line = self.current.line
        self.expect(TokenType.CALL)
        name = self.expect(TokenType.IDENT, "子程序名").value
        args: List[Expr] = []
        if self.match(TokenType.LPAREN):
            if self.current.type != TokenType.RPAREN:
                while True:
                    args.append(self.parse_expr())
                    if not self.match(TokenType.COMMA):
                        break
            self.expect(TokenType.RPAREN, "')'")
        self._expect_stmt_end(line)
        node = CallStmt(name=name, src_line=line, args=args)
        self._call_sites.append(node)
        return node

    def _collect_calls(self, stmts: List[Stmt], out: List[CallStmt]):
        for s in stmts:
            if isinstance(s, CallStmt):
                out.append(s)
            elif isinstance(s, IfStmt):
                self._collect_calls(s.then_body, out)
                self._collect_calls(s.else_body, out)
            elif isinstance(s, (WhileStmt, ForStmt)):
                self._collect_calls(s.body, out)

    def _remap_idx(self, idx: int, base: int) -> int:
        return base + (idx - self.profile.param_virt_base) if idx >= self.profile.param_virt_base else idx

    def _remap_expr(self, e: Expr, base: int):
        if isinstance(e, VarExpr):
            e.idx = self._remap_idx(e.idx, base)
        elif isinstance(e, BinOpExpr):
            self._remap_expr(e.left, base)
            self._remap_expr(e.right, base)
        elif isinstance(e, UnaryExpr):
            self._remap_expr(e.operand, base)

    def _remap_cond(self, c: Condition, base: int):
        if isinstance(c, CmpCondition):
            self._remap_expr(c.left, base)
            self._remap_expr(c.right, base)
        elif isinstance(c, (AndCondition, OrCondition)):
            self._remap_cond(c.left, base)
            self._remap_cond(c.right, base)
        elif isinstance(c, NotCondition):
            self._remap_cond(c.cond, base)

    def _remap_stmts(self, stmts: List[Stmt], base: int):
        for s in stmts:
            if isinstance(s, AssignStmt):
                s.dst = self._remap_idx(s.dst, base)
                self._remap_expr(s.expr, base)
            elif isinstance(s, MoveDOStmt):
                if s.do_delay[0] == 'var':
                    s.do_delay = ('var', self._remap_idx(int(s.do_delay[1]), base))
            elif isinstance(s, GetIOStmt):
                s.dst_var = self._remap_idx(s.dst_var, base)
            elif isinstance(s, IfStmt):
                self._remap_cond(s.condition, base)
                self._remap_stmts(s.then_body, base)
                self._remap_stmts(s.else_body, base)
            elif isinstance(s, WhileStmt):
                self._remap_cond(s.condition, base)
                self._remap_stmts(s.body, base)
            elif isinstance(s, ForStmt):
                s.var = self._remap_idx(s.var, base)
                self._remap_expr(s.start, base)
                self._remap_expr(s.end, base)
                self._remap_stmts(s.body, base)
            elif isinstance(s, SetOverallStmt):
                self._remap_expr(s.value, base)
            elif isinstance(s, CallStmt):
                for a in s.args:
                    self._remap_expr(a, base)

    def _check_calls(self, main_stmts: List[Stmt]):
        for c in self._call_sites:
            sub = self.subs.get(c.name)
            if sub is None:
                raise ParseError(
                    f"调用了未定义的子程序 '{c.name}'（请在主程序之后用 SUB {c.name}: ... "
                    f"END_SUB 定义）", c.src_line)
            if len(c.args) != len(sub.params):
                raise ParseError(
                    f"子程序 '{c.name}' 需要 {len(sub.params)} 个参数"
                    f"（{', '.join(sub.params)}），但调用给了 {len(c.args)} 个",
                    c.src_line)
        graph: Dict[str, List[CallStmt]] = {}
        for sname, sub in self.subs.items():
            calls: List[CallStmt] = []
            self._collect_calls(sub.body, calls)
            graph[sname] = calls
        visiting: List[str] = []

        def dfs(node: str, line: int):
            if node in visiting:
                cycle = " -> ".join(visiting[visiting.index(node):] + [node])
                raise ParseError(
                    f"检测到子程序循环调用（不支持递归）: {cycle}", line)
            visiting.append(node)
            for nxt in graph.get(node, []):
                dfs(nxt.name, nxt.src_line)
            visiting.pop()

        for sname, sub in self.subs.items():
            dfs(sname, sub.src_line)
        callers: Dict[str, List[Optional[str]]] = {n: [] for n in self.subs}
        main_calls: List[CallStmt] = []
        self._collect_calls(main_stmts, main_calls)
        for c in main_calls:
            callers[c.name].append(None)
        for caller_name, calls in graph.items():
            for c in calls:
                callers[c.name].append(caller_name)
        depth_memo: Dict[str, int] = {}

        def depth_of(name: str) -> int:
            if name in depth_memo:
                return depth_memo[name]
            d = 0
            for caller in callers[name]:
                d = max(d, 1 if caller is None else depth_of(caller) + 1)
            depth_memo[name] = d
            return d

        for sname, sub in self.subs.items():
            if not sub.params:
                continue
            d = depth_of(sname)
            if d > PARAM_MAX_DEPTH:
                raise ParseError(
                    f"带参数的子程序 '{sname}' 被嵌套在第 {d} 层调用：参数寄存器区 "
                    f"V[{self.profile.param_band_1}]~V[{self.profile.param_band_2 + self.profile.param_band_size - 1}] 只分 "
                    f"{PARAM_MAX_DEPTH} 层（第一层 V[{self.profile.param_band_1}]~"
                    f"V[{self.profile.param_band_1 + self.profile.param_band_size - 1}]，第二层 V[{self.profile.param_band_2}]~"
                    f"V[{self.profile.param_band_2 + self.profile.param_band_size - 1}]），"
                    f"请去掉该子程序的形参，或改由主程序/第一层子程序调用它",
                    sub.src_line)
            base = self.profile.param_band_1 + (d - 1) * self.profile.param_band_size
            sub.param_base = base
            self._remap_stmts(sub.body, base)

    def parse(self) -> Program:
        decls: List[VarDecl] = []
        while True:
            while self.current.type in (TokenType.EOL, TokenType.SEMI):
                self.advance()
            if self.current.type in (TokenType.VAR, TokenType.CONST):
                decls.append(self.parse_var_decl())
            elif self.current.type == TokenType.MAP:
                decls.append(self.parse_map_decl())
            else:
                break
        stmts = []
        while self.current.type != TokenType.EOF:
            if self.current.type in (TokenType.EOL, TokenType.SEMI):
                self.advance()
                continue
            if self.current.type in (TokenType.VAR, TokenType.CONST):
                raise ParseError(
                    "变量声明（VAR/CONST）只能放在程序开头、所有执行语句之前",
                    self.current.line)
            if self.current.type == TokenType.SUB:
                break
            stmts.append(self.parse_stmt())
        subs: List[SubDef] = []
        while True:
            while self.current.type in (TokenType.EOL, TokenType.SEMI):
                self.advance()
            if self.current.type != TokenType.SUB:
                break
            subs.append(self.parse_sub_def())
        if self.current.type != TokenType.EOF:
            raise ParseError(
                f"子程序定义（SUB）之后不允许再出现语句，意外的 {_tok_desc(self.current)}",
                self.current.line)
        self._check_calls(stmts)
        return Program(stmts, decls, subs)

    def parse_stmt_list(self, end_types) -> List[Stmt]:
        stmts = []
        while self.current.type not in end_types:
            if self.current.type == TokenType.EOF:
                return stmts
            if self.current.type in (TokenType.EOL, TokenType.SEMI):
                self.advance()
                continue
            stmts.append(self.parse_stmt())
        return stmts

    def parse_stmt(self) -> Stmt:
        t = self.current
        line = t.line
        tt = t.type
        if tt == TokenType.IF:
            return self.parse_if_stmt()
        if tt == TokenType.WHILE:
            return self.parse_while_stmt()
        if tt == TokenType.FOR:
            return self.parse_for_stmt()
        if tt == TokenType.BREAK:
            self.advance()
            self._expect_stmt_end(line)
            return BreakStmt(src_line=line)
        if tt == TokenType.CONTINUE:
            self.advance()
            self._expect_stmt_end(line)
            return ContinueStmt(src_line=line)
        if tt == TokenType.STOP:
            self.advance()
            self._expect_stmt_end(line)
            return StopStmt(src_line=line)
        if tt == TokenType.WAIT_MOTION_DONE:
            self.advance()
            self._expect_stmt_end(line)
            return WaitMotionDoneStmt(src_line=line)
        if tt == TokenType.JUMP:
            return self.parse_jump_stmt()
        if tt == TokenType.SERVO:
            val = t.value
            if val not in ('SERVO_ON', 'SERVO_OFF'):
                raise ParseError("SERVO 后应为 ON 或 OFF", line)
            self.advance()
            self._expect_stmt_end(line)
            return ServoStmt(on=(val == 'SERVO_ON'), src_line=line)
        if tt == TokenType.V:
            return self.parse_v_assign()
        if tt == TokenType.IDENT:
            return self.parse_named_assign()
        if tt in (TokenType.VAR, TokenType.CONST, TokenType.MAP):
            raise ParseError(
                "变量声明（VAR/CONST/MAP）只能放在程序开头、所有执行语句之前", line)
        if tt == TokenType.P:
            return self.parse_p_assign()
        if tt == TokenType.PR:
            return self.parse_pr_stmt()
        if tt == TokenType.STOPON:
            return self.parse_stopon_stmt()
        if tt == TokenType.CALL:
            return self.parse_call_sub()
        if tt == TokenType.RET:
            if not self._in_sub:
                raise ParseError("RET 只能在子程序（SUB ... END_SUB）内使用", line)
            self.advance()
            self._expect_stmt_end(line)
            return RetStmt(src_line=line)
        if tt == TokenType.SUB:
            raise ParseError("子程序定义（SUB）不能嵌套，也不能出现在主程序语句中间", line)
        if tt == TokenType.END_SUB:
            raise ParseError("END_SUB 没有匹配的 SUB", line)
        if tt in _CALL_CMDS:
            return self.parse_call_stmt()
        if tt in (TokenType.ELSE, TokenType.ELSIF, TokenType.END_IF):
            raise ParseError(f"{t.value} 没有匹配的 IF", line)
        if tt == TokenType.END_WHILE:
            raise ParseError(f"{t.value} 没有匹配的 WHILE", line)
        if tt == TokenType.END_FOR:
            raise ParseError(f"{t.value} 没有匹配的 FOR", line)
        if tt in (TokenType.DISTANCE_TO, TokenType.IS_MOVING, TokenType.GET_OVERALL):
            raise ParseError(f"{t.value} 只能用于赋值语句右侧，如 V[0] = {t.value}(...)", line)
        raise ParseError(f"无法识别的语句，意外的 {_tok_desc(t)}", line)

    def parse_if_stmt(self) -> IfStmt:
        line = self.current.line
        self.expect(TokenType.IF)
        cond = self.parse_condition()
        self.expect(TokenType.THEN, "'THEN'")
        self._expect_stmt_end(line)
        then_body = self.parse_stmt_list(
            (TokenType.ELSE, TokenType.ELSIF, TokenType.END_IF))
        elsif_clauses = []
        while self.current.type == TokenType.ELSIF:
            eline = self.current.line
            self.advance()
            econd = self.parse_condition()
            self.expect(TokenType.THEN, "'THEN'")
            self._expect_stmt_end(eline)
            ebody = self.parse_stmt_list(
                (TokenType.ELSE, TokenType.ELSIF, TokenType.END_IF))
            elsif_clauses.append((econd, ebody, eline))
        else_body: List[Stmt] = []
        if self.current.type == TokenType.ELSE:
            self.advance()
            self._expect_stmt_end(line)
            else_body = self.parse_stmt_list((TokenType.END_IF,))
        if self.current.type != TokenType.END_IF:
            raise ParseError(f"第 {line} 行 IF 缺少 END_IF", line)
        self.advance()
        self._expect_stmt_end(line)
        nested = else_body
        for econd, ebody, eline in reversed(elsif_clauses):
            nested = [IfStmt(condition=econd, then_body=ebody,
                             else_body=nested, src_line=eline)]
        return IfStmt(condition=cond, then_body=then_body,
                      else_body=nested, src_line=line)

    def parse_while_stmt(self) -> WhileStmt:
        line = self.current.line
        self.expect(TokenType.WHILE)
        cond = self.parse_condition()
        self.expect(TokenType.DO, "'DO'")
        self._expect_stmt_end(line)
        body = self.parse_stmt_list((TokenType.END_WHILE,))
        if self.current.type != TokenType.END_WHILE:
            raise ParseError(f"第 {line} 行 WHILE 缺少 END_WHILE", line)
        self.advance()
        self._expect_stmt_end(line)
        return WhileStmt(condition=cond, body=body, src_line=line)

    def parse_for_stmt(self) -> ForStmt:
        line = self.current.line
        self.expect(TokenType.FOR)
        if self.current.type == TokenType.IDENT:
            var_idx = self._resolve_write(self.current.value, self.current.line)
            self.advance()
        else:
            var_idx = self._parse_var_ref()
        if var_idx >= self.profile.temp_var_bottom:
            raise ParseError(
                f"FOR 循环变量不能使用 V[{self.profile.temp_var_bottom}]~V[{self.profile.temp_var_index}]"
                f"（编译器临时寄存器区）", line)
        if not self.match(TokenType.EQ, TokenType.ASSIGN):
            raise ParseError("FOR 循环变量后应为 '='，格式: FOR V[n] = start TO end [STEP step] DO",
                             self.current.line)
        start = self.parse_expr()
        self.expect(TokenType.TO, "'TO'")
        end = fold_expr(self.parse_expr(), line)
        if not isinstance(end, (ConstExpr, VarExpr)):
            raise ParseError("FOR 的 TO 值只能是常量或 V[n] 变量", line)
        step = 1.0
        if self.match(TokenType.STEP):
            step = self._parse_const_expr("STEP 步长")
            if step == 0:
                raise ParseError("STEP 不能为 0", line)
        self.expect(TokenType.DO, "'DO'")
        self._expect_stmt_end(line)
        body = self.parse_stmt_list((TokenType.END_FOR,))
        if self.current.type != TokenType.END_FOR:
            raise ParseError(f"第 {line} 行 FOR 缺少 END_FOR", line)
        self.advance()
        self._expect_stmt_end(line)
        return ForStmt(var=var_idx, start=start, end=end, step=step,
                       body=body, src_line=line)

    def parse_jump_stmt(self) -> JumpStmt:
        line = self.current.line
        self.advance()
        if self.match(TokenType.LPAREN):
            addr = self._parse_int("跳转地址")
            self.expect(TokenType.RPAREN, "')'")
        else:
            addr = self._parse_int("跳转地址")
        self._expect_stmt_end(line)
        return JumpStmt(addr=addr, src_line=line)

    def parse_stopon_stmt(self) -> StopOnStmt:
        line = self.current.line
        self.advance()
        if self.match(TokenType.LPAREN):
            di_idx = self._parse_int("DI 索引")
            self.expect(TokenType.RPAREN, "')'")
        else:
            di_idx = self._parse_di_ref()
        self._expect_stmt_end(line)
        return StopOnStmt(di_idx=di_idx, src_line=line)

    def parse_v_assign(self) -> AssignStmt:
        line = self.current.line
        t = self.current
        if isinstance(t.value, int):
            raise ParseError(
                f"速度值 V{t.value} 不能作为语句开头"
                f"（变量写作 V[n]，速度值仅用于运动指令）", line)
        dst = self._parse_var_ref()
        if not self.match(TokenType.EQ, TokenType.ASSIGN):
            if self.current.type in _CMP_TOKEN_TO_STR:
                raise ParseError("赋值应使用 = 或 :=（比较运算符只能在 IF/WHILE 条件中使用）",
                                 self.current.line)
            raise ParseError(f"V[{dst}] 后应为赋值号 = 或 :=", self.current.line)
        expr = self.parse_expr()
        self._expect_stmt_end(line)
        return AssignStmt(dst=dst, expr=expr, src_line=line)

    def parse_p_assign(self) -> PRStmt:
        line = self.current.line
        p_idx = self._parse_point_ref()
        if not self.match(TokenType.EQ, TokenType.ASSIGN):
            raise ParseError(f"P[{p_idx}] 后应为 '='（仅支持 P[n] = PR[m]）",
                             self.current.line)
        pr_idx = self._parse_pr_ref()
        self._expect_stmt_end(line)
        return PRStmt(op='P_ASSIGN_PR', args=[p_idx, pr_idx], src_line=line)

    def parse_pr_stmt(self) -> PRStmt:
        line = self.current.line
        pr_idx = self._parse_pr_ref()
        if self.match(TokenType.DOT):
            comp_tok = self.current
            comp_map = {TokenType.X: 0, TokenType.Y: 1, TokenType.Z: 2,
                        TokenType.J1: 3, TokenType.J2: 4, TokenType.J3: 5}
            if comp_tok.type not in comp_map:
                raise ParseError(f"PR 分量应为 X/Y/Z/J1/J2/J3，但遇到 {_tok_desc(comp_tok)}",
                                 comp_tok.line)
            self.advance()
            if not self.match(TokenType.EQ, TokenType.ASSIGN):
                raise ParseError("PR 分量后应为 '='", self.current.line)
            val = self._parse_const_expr("PR 分量赋值")
            self._expect_stmt_end(line)
            return PRStmt(op='SET_COMP', args=[pr_idx, comp_map[comp_tok.type], val],
                          src_line=line)
        if not self.match(TokenType.EQ, TokenType.ASSIGN):
            raise ParseError("PR[n] 后应为 '=' 或 '.分量'", self.current.line)
        if self.current.type == TokenType.CURPOS:
            self.advance()
            self.expect(TokenType.LPAREN, "'('")
            self.expect(TokenType.RPAREN, "')'")
            self._expect_stmt_end(line)
            return PRStmt(op='CURPOS', args=[pr_idx], src_line=line)
        if self.current.type == TokenType.P:
            p_idx = self._parse_point_ref()
            self._expect_stmt_end(line)
            return PRStmt(op='ASSIGN_P', args=[pr_idx, p_idx], src_line=line)
        if self.current.type == TokenType.PR:
            pr_a = self._parse_pr_ref()
            if self.match(TokenType.PLUS):
                pr_b = self._parse_pr_ref()
                self._expect_stmt_end(line)
                return PRStmt(op='ADD_VEC', args=[pr_idx, pr_a, pr_b], src_line=line)
            if self.match(TokenType.MINUS):
                pr_b = self._parse_pr_ref()
                self._expect_stmt_end(line)
                return PRStmt(op='SUB_VEC', args=[pr_idx, pr_a, pr_b], src_line=line)
            if self.match(TokenType.MUL):
                val = self._parse_const_expr("PR 标量乘法系数")
                self._expect_stmt_end(line)
                return PRStmt(op='MUL_SCALAR', args=[pr_idx, pr_a, val], src_line=line)
            raise ParseError("PR 运算仅支持 PR[a]+PR[b] / PR[a]-PR[b] / PR[a]*常数",
                             self.current.line)
        raise ParseError(
            "无法识别的 PR 赋值，支持: PR[n]=CURPOS() / PR[n]=P[m] / "
            "PR[n]=PR[a]+PR[b] / PR[n]=PR[a]-PR[b] / PR[n]=PR[a]*常数 / PR[n].X=常数",
            self.current.line)

    def parse_call_stmt(self) -> Stmt:
        t = self.current
        line = t.line
        tt = t.type
        if tt in (TokenType.MOVJ, TokenType.MOVL, TokenType.MOVC):
            return self._parse_move_cmd(t.value, line)
        if tt in (TokenType.MOVJ_DO, TokenType.MOVL_DO, TokenType.MOVC_DO):
            return self._parse_move_do_cmd(t.value, line)

        self.advance()
        self.expect(TokenType.LPAREN, "'('")

        if tt == TokenType.DELAY:
            ms = self._parse_const_expr("DELAY 毫秒数")
            if ms < 0:
                raise ParseError("DELAY 毫秒数不能为负", line)
            self.expect(TokenType.RPAREN, "')'")
            self._expect_stmt_end(line)
            return DelayStmt(ms=ms, src_line=line)

        if tt in (TokenType.SET_DO, TokenType.RESET_DO):
            idx = self._parse_int("DO 索引")
            if idx > self.profile.max_io_index:
                raise ParseError(f"DO[{idx}] 越界 [0..{self.profile.max_io_index}]", line)
            self.expect(TokenType.RPAREN, "')'")
            self._expect_stmt_end(line)
            return IOStmt(op=t.value, args=[idx], src_line=line)

        if tt == TokenType.WAIT_DI:
            idx = self._parse_int("DI 索引")
            if idx > self.profile.max_io_index:
                raise ParseError(f"DI[{idx}] 越界 [0..{self.profile.max_io_index}]", line)
            timeout = 0.0
            if self.match(TokenType.COMMA):
                timeout = self._parse_const_expr("WAIT_DI 超时时间")
            self.expect(TokenType.RPAREN, "')'")
            self._expect_stmt_end(line)
            return IOStmt(op='WAIT_DI', args=[idx, timeout], src_line=line)

        if tt in (TokenType.GET_DI, TokenType.GET_DO):
            first = self._parse_int("参数")
            if self.match(TokenType.COMMA):
                dst, io_idx = first, self._parse_int("IO 索引")
            else:
                dst, io_idx = 0, first
            if dst > self.profile.max_var_index:
                raise ParseError(f"V[{dst}] 越界 [0..{self.profile.max_var_index}]", line)
            if io_idx > self.profile.max_io_index:
                raise ParseError(f"IO 索引 {io_idx} 越界 [0..{self.profile.max_io_index}]", line)
            self.expect(TokenType.RPAREN, "')'")
            self._expect_stmt_end(line)
            return GetIOStmt(op=t.value, dst_var=dst, io_idx=io_idx, src_line=line)

        if tt == TokenType.ISIGNAL_DI:
            if self.current.type == TokenType.DI:
                di_idx = self._parse_di_ref()
            else:
                di_idx = self._parse_int("DI 索引")
                if di_idx > self.profile.max_io_index:
                    raise ParseError(f"DI[{di_idx}] 越界 [0..{self.profile.max_io_index}]", line)
            self.expect(TokenType.COMMA, "','")
            val = self._parse_int("信号值")
            if val not in (0, 1):
                raise ParseError("ISIGNAL_DI 第二个参数应为 0 或 1", line)
            self.expect(TokenType.RPAREN, "')'")
            self._expect_stmt_end(line)
            return IOStmt(op='ISIGNAL_DI', args=[di_idx, val], src_line=line)

        if tt == TokenType.SET_ACCE:
            acc = self._parse_const_expr("加速度")
            self.expect(TokenType.COMMA, "','")
            dec = self._parse_const_expr("减速度")
            if acc < 0 or dec < 0:
                raise ParseError("SET_ACCE 参数不能为负", line)
            self.expect(TokenType.RPAREN, "')'")
            self._expect_stmt_end(line)
            return SetAcceStmt(acc=acc, dec=dec, src_line=line)

        if tt == TokenType.SET_OVERALL:
            if self.current.type == TokenType.V:
                var_idx = self._parse_var_ref()
                value: Expr = VarExpr(var_idx)
            elif (self.current.type == TokenType.IDENT
                  and self.current.value in self.symbols
                  and not self.symbols[self.current.value].is_const):
                value = self._resolve_read(self.current.value, self.current.line)
                self.advance()
            else:
                val = self._parse_const_expr("SET_OVERALL 倍率")
                if val < 0 or val > 100:
                    raise ParseError("SET_OVERALL 参数范围 0~100", line)
                value = ConstExpr(val)
            self.expect(TokenType.RPAREN, "')'")
            self._expect_stmt_end(line)
            return SetOverallStmt(value=value, src_line=line)

        raise ParseError(f"未知指令 '{t.value}'", line)

    def _parse_move_cmd(self, cmd: str, line: int) -> MoveStmt:
        self.advance()
        self.expect(TokenType.LPAREN, "'('")
        point = self._parse_point_ref()
        mid_point = None
        if cmd == 'MOVC':
            self.expect(TokenType.COMMA, "','")
            mid_point = self._parse_point_ref()
        self.expect(TokenType.COMMA, "','")
        speed = self._parse_speed()
        self.expect(TokenType.COMMA, "','")
        trans = self._parse_trans()
        acc = dec = None
        if self.match(TokenType.COMMA):
            acc = self._parse_const_expr("加速度")
            self.expect(TokenType.COMMA, "','")
            dec = self._parse_const_expr("减速度")
            if acc < 0 or dec < 0:
                raise ParseError(f"{cmd} 的 acc/dec 不能为负", line)
        self.expect(TokenType.RPAREN, "')'")
        self._expect_stmt_end(line)
        return MoveStmt(op=cmd, point=point, speed=speed, trans=trans,
                        mid_point=mid_point, acc=acc, dec=dec, src_line=line)

    def _parse_move_do_cmd(self, cmd: str, line: int) -> MoveDOStmt:
        self.advance()
        self.expect(TokenType.LPAREN, "'('")
        point = self._parse_point_ref()
        mid_point = None
        if cmd == 'MOVC_DO':
            self.expect(TokenType.COMMA, "','")
            mid_point = self._parse_point_ref()
        self.expect(TokenType.COMMA, "','")
        speed = self._parse_speed()
        self.expect(TokenType.COMMA, "','")
        trans = self._parse_trans()
        self.expect(TokenType.COMMA, "','")
        if self.current.type == TokenType.V:
            var_idx = self._parse_var_ref()
            do_delay: Tuple[str, float] = ('var', var_idx)
        elif (self.current.type == TokenType.IDENT
              and self.current.value in self.symbols
              and not self.symbols[self.current.value].is_const):
            var_idx = self._resolve_write(self.current.value, self.current.line)
            self.advance()
            do_delay = ('var', var_idx)
        else:
            delay_val = self._parse_const_expr("DO 延时")
            if delay_val < 0:
                raise ParseError("DO 延时不能为负", line)
            do_delay = ('const', delay_val)
        self.expect(TokenType.COMMA, "','")
        do_idx = self._parse_do_ref()
        self.expect(TokenType.COMMA, "','")
        do_val = self._parse_int("DO 输出值")
        if do_val > self.profile.max_io_index:
            raise ParseError(f"DO 输出值 {do_val} 越界 [0..{self.profile.max_io_index}]", line)
        self.expect(TokenType.RPAREN, "')'")
        self._expect_stmt_end(line)
        return MoveDOStmt(op=cmd, point=point, speed=speed, trans=trans,
                          do_delay=do_delay, do_idx=do_idx, do_val=do_val,
                          mid_point=mid_point, src_line=line)

    def parse_condition(self) -> Condition:
        return self._parse_or()

    def _parse_or(self) -> Condition:
        left = self._parse_and()
        while self.current.type == TokenType.OR:
            self.advance()
            left = OrCondition(left, self._parse_and())
        return left

    def _parse_and(self) -> Condition:
        left = self._parse_not()
        while self.current.type == TokenType.AND:
            self.advance()
            left = AndCondition(left, self._parse_not())
        return left

    def _parse_not(self) -> Condition:
        if self.current.type == TokenType.NOT:
            self.advance()
            return NotCondition(self._parse_not())
        return self._parse_cmp()

    def _parse_cmp(self) -> Condition:
        line = self.current.line
        if self.current.type == TokenType.LPAREN:
            self.advance()
            inner = self._parse_or()
            self.expect(TokenType.RPAREN, "')'")
            return inner
        left = self.parse_expr()
        if self.current.type in _CMP_TOKEN_TO_STR:
            op = _CMP_TOKEN_TO_STR[self.current.type]
            self.advance()
            right = self.parse_expr()
            return CmpCondition(op, left, right)
        folded = fold_expr(left, line)
        if isinstance(folded, ConstExpr):
            return ConstCondition(folded.val)
        return CmpCondition('!=', folded, ConstExpr(0.0))

    def parse_expr(self) -> Expr:
        left = self._parse_term()
        while self.current.type in (TokenType.PLUS, TokenType.MINUS):
            op = '+' if self.current.type == TokenType.PLUS else '-'
            self.advance()
            left = BinOpExpr(op, left, self._parse_term())
        return left

    def _parse_term(self) -> Expr:
        left = self._parse_factor()
        while self.current.type in (TokenType.MUL, TokenType.DIV):
            op = '*' if self.current.type == TokenType.MUL else '/'
            self.advance()
            left = BinOpExpr(op, left, self._parse_factor())
        return left

    def _parse_factor(self) -> Expr:
        t = self.current
        line = t.line
        if t.type == TokenType.MINUS:
            self.advance()
            return UnaryExpr('-', self._parse_factor())
        if t.type == TokenType.PLUS:
            self.advance()
            return self._parse_factor()
        if t.type == TokenType.NUMBER:
            self.advance()
            return ConstExpr(t.value)
        if t.type == TokenType.V:
            if isinstance(t.value, int):
                raise ParseError(f"速度值 V{t.value} 不能用在表达式中（变量写作 V[n]）", line)
            idx = self._parse_var_ref()
            return VarExpr(idx)
        if t.type == TokenType.IDENT:
            self.advance()
            return self._resolve_read(t.value, line)
        if t.type == TokenType.LPAREN:
            self.advance()
            e = self.parse_expr()
            self.expect(TokenType.RPAREN, "')'")
            return e
        if t.type == TokenType.GET_DI:
            self.advance()
            self.expect(TokenType.LPAREN, "'('")
            idx = self._parse_int("DI 索引")
            self.expect(TokenType.RPAREN, "')'")
            if idx > self.profile.max_io_index:
                raise ParseError(f"DI[{idx}] 越界 [0..{self.profile.max_io_index}]", line)
            return GetDIExpr(idx)
        if t.type == TokenType.GET_DO:
            self.advance()
            self.expect(TokenType.LPAREN, "'('")
            idx = self._parse_int("DO 索引")
            self.expect(TokenType.RPAREN, "')'")
            if idx > self.profile.max_io_index:
                raise ParseError(f"DO[{idx}] 越界 [0..{self.profile.max_io_index}]", line)
            return GetDOExpr(idx)
        if t.type == TokenType.DISTANCE_TO:
            self.advance()
            self.expect(TokenType.LPAREN, "'('")
            p_idx = self._parse_point_ref()
            self.expect(TokenType.RPAREN, "')'")
            return DistanceToExpr(p_idx)
        if t.type == TokenType.IS_MOVING:
            self.advance()
            self.expect(TokenType.LPAREN, "'('")
            self.expect(TokenType.RPAREN, "')'")
            return IsMovingExpr()
        if t.type == TokenType.GET_OVERALL:
            self.advance()
            self.expect(TokenType.LPAREN, "'('")
            self.expect(TokenType.RPAREN, "')'")
            return GetOverallExpr()
        raise ParseError(f"表达式中出现意外的 {_tok_desc(t)}", line)


# ============================================================================
# CodeGenerator（AST → 指令序列，控制流扁平化 + 标签地址解析）
# ============================================================================
class CodeGenerator:
    TEMP_TOP = TEMP_VAR_INDEX      # 类级回退值；实例属性由注入的 profile 覆盖
    TEMP_BOTTOM = TEMP_VAR_BOTTOM  # 类级回退值；实例属性由注入的 profile 覆盖

    def __init__(self, profile: "DeviceProfile" = None):
        self.profile = profile or DEFAULT_PROFILE
        # 实例级临时寄存器区界（覆盖类级回退值，类级值仅为默认 profile 的常量别名）
        self.TEMP_TOP = self.profile.temp_var_index
        self.TEMP_BOTTOM = self.profile.temp_var_bottom
        self.program: List[Instruction] = []
        self._labels: Dict[int, int] = {}
        self._fixups: List[Tuple[int, int, int]] = []
        self._label_cnt = 0
        self._loop_stack: List[Tuple[int, int]] = []
        self._temp_used = 0
        self._sub_labels: Dict[str, int] = {}
        # v3.5 源码级调试映射
        self.addr_to_line: Dict[int, int] = {}
        self.sub_entries: Dict[str, int] = {}

    def new_label(self) -> int:
        lid = self._label_cnt
        self._label_cnt += 1
        return lid

    def place_label(self, lid: int):
        self._labels[lid] = len(self.program)

    def emit(self, inst: Instruction) -> int:
        self.program.append(inst)
        if inst.src_line > 0:
            self.addr_to_line[len(self.program) - 1] = inst.src_line
        return len(self.program) - 1

    def emit_jump(self, label: int, line: int):
        idx = self.emit(Instruction(OpCode.JUMP, src_line=line))
        self._fixups.append((idx, label, line))

    def _emit_if(self, var: int, cmp_op: int, mode: int, val: float,
                 label: int, line: int):
        idx = self.emit(Instruction(OpCode.IF, var, cmp_op, mode,
                                    f1=val, src_line=line))
        self._fixups.append((idx, label, line))

    def _resolve_fixups(self):
        for idx, label, line in self._fixups:
            if label not in self._labels:
                raise ParseError("内部错误：标签未定义", line)
            target = self._labels[label]
            if target > 0xFFFF:
                raise ParseError(f"跳转地址 {target} 超出 16 位范围", line)
            self.program[idx].set_jump_addr(target)

    def alloc_temp(self, line: int) -> int:
        idx = self.TEMP_TOP - self._temp_used
        if idx < self.TEMP_BOTTOM:
            raise ParseError(
                f"表达式过于复杂：临时寄存器 V[{self.TEMP_BOTTOM}]~V[{self.TEMP_TOP}] "
                f"已用尽，请拆分为多条赋值语句", line)
        self._temp_used += 1
        return idx

    def generate(self, ast: Program) -> List[Instruction]:
        for d in ast.decls:
            if d.is_const or d.init is None:
                continue
            init = fold_expr(d.init, d.src_line)
            if isinstance(init, ConstExpr) and init.val == 0:
                continue
            self._gen_expr(init, d.index, d.src_line)
        sub_labels: Dict[str, int] = {s.name: self.new_label() for s in ast.subs}
        self._sub_labels = sub_labels
        self._sub_defs: Dict[str, SubDef] = {s.name: s for s in ast.subs}
        for stmt in ast.stmts:
            self.gen_stmt(stmt)
        if ast.subs:
            end_label = self.new_label()
            self.emit_jump(end_label, ast.subs[0].src_line)
            for sub in ast.subs:
                self.place_label(sub_labels[sub.name])
                # v3.5 记录子程序入口地址（优化前地址，由 PeepholeOptimizer 重映射）
                self.sub_entries[sub.name] = len(self.program)
                self.gen_stmts(sub.body)
                self.emit(Instruction(OpCode.RET, src_line=sub.src_line))
            self.place_label(end_label)
        self._resolve_fixups()
        return self.program

    def gen_stmts(self, stmts: List[Stmt]):
        for stmt in stmts:
            self.gen_stmt(stmt)

    def gen_stmt(self, stmt: Stmt):
        self._temp_used = 0
        line = stmt.src_line

        if isinstance(stmt, VarDecl):
            return
        if isinstance(stmt, MoveStmt):
            op_map = {'MOVJ': OpCode.MOVJ, 'MOVL': OpCode.MOVL, 'MOVC': OpCode.MOVC}
            self.emit(Instruction(op_map[stmt.op], stmt.point, stmt.speed, stmt.trans,
                                  p4=stmt.mid_point or 0,
                                  f1=stmt.acc or 0.0, f2=stmt.dec or 0.0,
                                  src_line=line))
        elif isinstance(stmt, MoveDOStmt):
            op_map = {'MOVJ_DO': OpCode.MOVJ_DO, 'MOVL_DO': OpCode.MOVL_DO,
                      'MOVC_DO': OpCode.MOVC_DO}
            if stmt.do_delay[0] == 'var':
                f1, f2 = 0.0, float(int(stmt.do_delay[1]) + 1)
            else:
                f1, f2 = float(stmt.do_delay[1]), 0.0
            self.emit(Instruction(op_map[stmt.op], stmt.point, stmt.speed, stmt.trans,
                                  p4=stmt.mid_point or 0,
                                  p5=stmt.do_idx, p6=stmt.do_val,
                                  f1=f1, f2=f2, src_line=line))
        elif isinstance(stmt, DelayStmt):
            self.emit(Instruction(OpCode.DELAY, f1=stmt.ms, src_line=line))
        elif isinstance(stmt, IOStmt):
            if stmt.op == 'SET_DO':
                self.emit(Instruction(OpCode.SET_DO, stmt.args[0], src_line=line))
            elif stmt.op == 'RESET_DO':
                self.emit(Instruction(OpCode.RESET_DO, stmt.args[0], src_line=line))
            elif stmt.op == 'WAIT_DI':
                self.emit(Instruction(OpCode.WAIT_DI, stmt.args[0],
                                      f1=stmt.args[1], src_line=line))
            elif stmt.op == 'ISIGNAL_DI':
                self.emit(Instruction(OpCode.ISIGNAL_DI, stmt.args[0], stmt.args[1],
                                      src_line=line))
            else:
                raise ParseError(f"内部错误：未知 IO 指令 {stmt.op}", line)
        elif isinstance(stmt, GetIOStmt):
            op = OpCode.GET_DI if stmt.op == 'GET_DI' else OpCode.GET_DO
            self.emit(Instruction(op, stmt.dst_var, stmt.io_idx, src_line=line))
        elif isinstance(stmt, AssignStmt):
            self._gen_assign(stmt)
        elif isinstance(stmt, IfStmt):
            self._gen_if(stmt)
        elif isinstance(stmt, WhileStmt):
            self._gen_while(stmt)
        elif isinstance(stmt, ForStmt):
            self._gen_for(stmt)
        elif isinstance(stmt, BreakStmt):
            if not self._loop_stack:
                raise ParseError("BREAK 必须在 WHILE/FOR 循环内", line)
            self.emit_jump(self._loop_stack[-1][0], line)
        elif isinstance(stmt, ContinueStmt):
            if not self._loop_stack:
                raise ParseError("CONTINUE 必须在 WHILE/FOR 循环内", line)
            self.emit_jump(self._loop_stack[-1][1], line)
        elif isinstance(stmt, JumpStmt):
            inst = Instruction(OpCode.JUMP, src_line=line)
            inst.set_jump_addr(stmt.addr)
            self.emit(inst)
        elif isinstance(stmt, CallStmt):
            base = self._sub_defs[stmt.name].param_base
            for k, arg in enumerate(stmt.args):
                self._temp_used = 0
                self._gen_expr(arg, base + k, stmt.src_line)
            idx = self.emit(Instruction(OpCode.CALL, src_line=line))
            self._fixups.append((idx, self._sub_labels[stmt.name], line))
        elif isinstance(stmt, RetStmt):
            self.emit(Instruction(OpCode.RET, src_line=line))
        elif isinstance(stmt, StopStmt):
            self.emit(Instruction(OpCode.STOP, src_line=line))
        elif isinstance(stmt, WaitMotionDoneStmt):
            self.emit(Instruction(OpCode.WAIT_MOTION_DONE, src_line=line))
        elif isinstance(stmt, ServoStmt):
            self.emit(Instruction(OpCode.SERVO_ON if stmt.on else OpCode.SERVO_OFF,
                                  src_line=line))
        elif isinstance(stmt, SetAcceStmt):
            self.emit(Instruction(OpCode.SET_ACCE, f1=stmt.acc, f2=stmt.dec,
                                  src_line=line))
        elif isinstance(stmt, StopOnStmt):
            self.emit(Instruction(OpCode.STOPON_DI, stmt.di_idx, src_line=line))
        elif isinstance(stmt, SetOverallStmt):
            value = fold_expr(stmt.value, line)
            if isinstance(value, VarExpr):
                self.emit(Instruction(OpCode.SET_OVERALL, p1=value.idx, p3=1,
                                      src_line=line))
            elif isinstance(value, ConstExpr):
                self.emit(Instruction(OpCode.SET_OVERALL, f1=value.val, p3=0,
                                      src_line=line))
            else:
                raise ParseError("SET_OVERALL 参数只能是常量或 V[n]", line)
        elif isinstance(stmt, PRStmt):
            self._gen_pr(stmt)
        else:
            raise ParseError(f"内部错误：未知语句节点 {type(stmt).__name__}", line)

    def _gen_pr(self, stmt: PRStmt):
        line = stmt.src_line
        a = stmt.args
        if stmt.op == 'CURPOS':
            self.emit(Instruction(OpCode.PR_CURPOS, a[0], src_line=line))
        elif stmt.op == 'ASSIGN_P':
            self.emit(Instruction(OpCode.PR_ASSIGN_P, a[0], a[1], src_line=line))
        elif stmt.op == 'ADD_VEC':
            self.emit(Instruction(OpCode.PR_ADD_VEC, a[0], a[1], a[2], src_line=line))
        elif stmt.op == 'SUB_VEC':
            self.emit(Instruction(OpCode.PR_SUB_VEC, a[0], a[1], a[2], src_line=line))
        elif stmt.op == 'MUL_SCALAR':
            self.emit(Instruction(OpCode.PR_MUL_SCALAR, a[0], a[1], f1=a[2], src_line=line))
        elif stmt.op == 'SET_COMP':
            self.emit(Instruction(OpCode.PR_SET_COMP, a[0], a[1], f1=a[2], src_line=line))
        elif stmt.op == 'P_ASSIGN_PR':
            self.emit(Instruction(OpCode.P_ASSIGN_PR, a[0], a[1], src_line=line))
        else:
            raise ParseError(f"内部错误：未知 PR 操作 {stmt.op}", line)

    def _gen_assign(self, stmt: AssignStmt):
        line = stmt.src_line
        expr = fold_expr(stmt.expr, line)
        if (self.profile.temp_var_bottom <= stmt.dst <= self.profile.temp_var_index
                and stmt.dst in expr_var_refs(expr)
                and not self._is_trivial_expr(expr)):
            raise ParseError(
                f"V[{stmt.dst}] 位于编译器临时寄存器区 "
                f"V[{self.profile.temp_var_bottom}]~V[{self.profile.temp_var_index}]，不能在复杂表达式中读写混用",
                line)
        self._gen_expr(expr, stmt.dst, line)

    @staticmethod
    def _is_trivial_expr(expr: Expr) -> bool:
        if isinstance(expr, (ConstExpr, VarExpr, GetDIExpr, GetDOExpr,
                             DistanceToExpr, IsMovingExpr, GetOverallExpr)):
            return True
        if isinstance(expr, BinOpExpr):
            return isinstance(expr.left, VarExpr) and isinstance(expr.right, VarExpr)
        return False

    def _gen_expr(self, expr: Expr, dst: int, line: int):
        expr = fold_expr(expr, line)
        if isinstance(expr, ConstExpr):
            self.emit(Instruction(OpCode.ASSIGN, dst, f1=expr.val, src_line=line))
        elif isinstance(expr, VarExpr):
            if expr.idx == dst:
                return
            t = self.alloc_temp(line)
            self.emit(Instruction(OpCode.ASSIGN, t, f1=0.0, src_line=line))
            self.emit(Instruction(OpCode.ADD, dst, expr.idx, t, src_line=line))
            self._temp_used -= 1
        elif isinstance(expr, GetDIExpr):
            self.emit(Instruction(OpCode.GET_DI, dst, expr.idx, src_line=line))
        elif isinstance(expr, GetDOExpr):
            self.emit(Instruction(OpCode.GET_DO, dst, expr.idx, src_line=line))
        elif isinstance(expr, DistanceToExpr):
            self.emit(Instruction(OpCode.DISTANCE_TO, dst, expr.point, src_line=line))
        elif isinstance(expr, IsMovingExpr):
            self.emit(Instruction(OpCode.IS_MOVING, dst, src_line=line))
        elif isinstance(expr, GetOverallExpr):
            self.emit(Instruction(OpCode.GET_OVERALL, dst, src_line=line))
        elif isinstance(expr, UnaryExpr):
            self._gen_expr(expr.operand, dst, line)
            t = self.alloc_temp(line)
            self.emit(Instruction(OpCode.ASSIGN, t, f1=0.0, src_line=line))
            self.emit(Instruction(OpCode.SUB, dst, t, dst, src_line=line))
            self._temp_used -= 1
        elif isinstance(expr, BinOpExpr):
            self._gen_binop(expr, dst, line)
        else:
            raise ParseError(f"内部错误：未知表达式节点 {type(expr).__name__}", line)

    def _gen_binop(self, expr: BinOpExpr, dst: int, line: int):
        op_map = {'+': OpCode.ADD, '-': OpCode.SUB, '*': OpCode.MUL, '/': OpCode.DIV}
        mark = self._temp_used
        lv = self._expr_as_var(expr.left, line)
        rv = self._expr_as_var(expr.right, line)
        self.emit(Instruction(op_map[expr.op], dst, lv, rv, src_line=line))
        self._temp_used = mark

    def _expr_as_var(self, expr: Expr, line: int) -> int:
        expr = fold_expr(expr, line)
        if isinstance(expr, VarExpr):
            return expr.idx
        t = self.alloc_temp(line)
        self._gen_expr(expr, t, line)
        return t

    def _gen_if(self, stmt: IfStmt):
        line = stmt.src_line
        mark = self._temp_used
        if stmt.else_body:
            l_else = self.new_label()
            l_end = self.new_label()
            self.gen_cond_false(stmt.condition, l_else, line)
            self._temp_used = mark
            self.gen_stmts(stmt.then_body)
            self.emit_jump(l_end, line)
            self.place_label(l_else)
            self.gen_stmts(stmt.else_body)
            self.place_label(l_end)
        else:
            l_end = self.new_label()
            self.gen_cond_false(stmt.condition, l_end, line)
            self._temp_used = mark
            self.gen_stmts(stmt.then_body)
            self.place_label(l_end)

    def _gen_while(self, stmt: WhileStmt):
        line = stmt.src_line
        l_start = self.new_label()
        l_end = self.new_label()
        self.place_label(l_start)
        mark = self._temp_used
        self.gen_cond_false(stmt.condition, l_end, line)
        self._temp_used = mark
        self._loop_stack.append((l_end, l_start))
        self.gen_stmts(stmt.body)
        self._loop_stack.pop()
        self.emit_jump(l_start, line)
        self.place_label(l_end)

    def _gen_for(self, stmt: ForStmt):
        line = stmt.src_line
        start = fold_expr(stmt.start, line)
        if not (isinstance(start, VarExpr) and start.idx == stmt.var):
            self._gen_expr(start, stmt.var, line)
        l_start = self.new_label()
        l_cont = self.new_label()
        l_end = self.new_label()
        self.place_label(l_start)
        cmp_op = '<=' if stmt.step > 0 else '>='
        end = fold_expr(stmt.end, line)
        cond = CmpCondition(cmp_op, VarExpr(stmt.var), end)
        mark = self._temp_used
        self.gen_cond_false(cond, l_end, line)
        self._temp_used = mark
        self._loop_stack.append((l_end, l_cont))
        self.gen_stmts(stmt.body)
        self._loop_stack.pop()
        self.place_label(l_cont)
        t = self.alloc_temp(line)
        self.emit(Instruction(OpCode.ASSIGN, t, f1=stmt.step, src_line=line))
        self.emit(Instruction(OpCode.ADD, stmt.var, stmt.var, t, src_line=line))
        self._temp_used -= 1
        self.emit_jump(l_start, line)
        self.place_label(l_end)

    def gen_cond_false(self, cond: Condition, label: int, line: int):
        cond = fold_condition(cond, line)
        if isinstance(cond, ConstCondition):
            if cond.val == 0:
                self.emit_jump(label, line)
            return
        if isinstance(cond, NotCondition):
            self.gen_cond_true(cond.cond, label, line)
            return
        if isinstance(cond, AndCondition):
            self.gen_cond_false(cond.left, label, line)
            self.gen_cond_false(cond.right, label, line)
            return
        if isinstance(cond, OrCondition):
            l_skip = self.new_label()
            self.gen_cond_true(cond.left, l_skip, line)
            self.gen_cond_false(cond.right, label, line)
            self.place_label(l_skip)
            return
        if isinstance(cond, CmpCondition):
            self._emit_cmp_jump(cond, label, line, negate=False)
            return
        raise ParseError(f"内部错误：未知条件节点 {type(cond).__name__}", line)

    def gen_cond_true(self, cond: Condition, label: int, line: int):
        cond = fold_condition(cond, line)
        if isinstance(cond, ConstCondition):
            if cond.val != 0:
                self.emit_jump(label, line)
            return
        if isinstance(cond, NotCondition):
            self.gen_cond_false(cond.cond, label, line)
            return
        if isinstance(cond, AndCondition):
            l_next = self.new_label()
            self.gen_cond_false(cond.left, l_next, line)
            self.gen_cond_true(cond.right, label, line)
            self.place_label(l_next)
            return
        if isinstance(cond, OrCondition):
            self.gen_cond_true(cond.left, label, line)
            self.gen_cond_true(cond.right, label, line)
            return
        if isinstance(cond, CmpCondition):
            self._emit_cmp_jump(cond, label, line, negate=True)
            return
        raise ParseError(f"内部错误：未知条件节点 {type(cond).__name__}", line)

    def _emit_cmp_jump(self, cond: CmpCondition, label: int, line: int, negate: bool):
        left = fold_expr(cond.left, line)
        right = fold_expr(cond.right, line)
        op = cond.op
        if isinstance(left, ConstExpr) and isinstance(right, ConstExpr):
            result = _eval_const_cmp(op, left.val, right.val)
            should_jump = result if negate else (not result)
            if should_jump:
                self.emit_jump(label, line)
            return
        if isinstance(left, ConstExpr):
            left, right = right, left
            op = CMP_SWAP[op]
        if isinstance(left, VarExpr):
            lidx = left.idx
        else:
            lidx = self._expr_as_var(left, line)
        if isinstance(right, ConstExpr):
            mode, rval = 0, right.val
        elif isinstance(right, VarExpr):
            mode, rval = 1, float(right.idx)
        else:
            ridx = self._expr_as_var(right, line)
            mode, rval = 1, float(ridx)
        cmp_int = CMP_MAP[op]
        if negate:
            cmp_int = CMP_NEGATE[cmp_int]
        self._emit_if(lidx, cmp_int, mode, rval, label, line)


# ============================================================================
# Peephole Optimizer（窥孔优化，v3.5 支持 SourceMap 重映射）
# ============================================================================
class PeepholeOptimizer:
    _V_WRITES = {
        OpCode.ASSIGN, OpCode.ADD, OpCode.SUB, OpCode.MUL, OpCode.DIV,
        OpCode.GET_DI, OpCode.GET_DO, OpCode.IS_MOVING,
        OpCode.DISTANCE_TO, OpCode.GET_OVERALL,
    }

    def __init__(self, program: List[Instruction],
                 addr_to_line: Optional[Dict[int, int]] = None,
                 sub_entries: Optional[Dict[str, int]] = None):
        self.program = program
        self.n = len(program)
        self.addr_to_line = addr_to_line or {}
        self.sub_entries = sub_entries or {}

    def optimize(self) -> Tuple[List[Instruction], Dict[int, int], Dict[str, int]]:
        changed = True
        rounds = 0
        while changed and rounds < 5:
            changed = False
            changed |= self._eliminate_redundant_store()
            changed |= self._fold_jump_chains()
            changed |= self._eliminate_jumps_to_next()
            changed |= self._eliminate_unreachable()
            rounds += 1
        return self._compact()

    def _eliminate_redundant_store(self) -> bool:
        changed = False
        for i in range(self.n - 1):
            a, b = self.program[i], self.program[i + 1]
            if a.op in self._V_WRITES and b.op in self._V_WRITES and a.p1 == b.p1:
                if not self._inst_reads_v(b, a.p1):
                    self._nop(a)
                    changed = True
        return changed

    @staticmethod
    def _inst_reads_v(inst: Instruction, reg: int) -> bool:
        if inst.op in (OpCode.ADD, OpCode.SUB, OpCode.MUL, OpCode.DIV):
            return inst.p2 == reg or inst.p3 == reg
        return False

    def _fold_jump_chains(self) -> bool:
        changed = False
        for inst in self.program:
            if inst.op in (OpCode.JUMP, OpCode.IF, OpCode.CALL):
                target = inst.jump_addr()
                visited = set()
                while 0 <= target < self.n and self.program[target].op == OpCode.JUMP:
                    if target in visited:
                        break
                    visited.add(target)
                    target = self.program[target].jump_addr()
                if target != inst.jump_addr():
                    inst.set_jump_addr(target)
                    changed = True
        return changed

    def _eliminate_jumps_to_next(self) -> bool:
        changed = False
        for i, inst in enumerate(self.program):
            if inst.op == OpCode.JUMP and inst.jump_addr() == i + 1:
                self._nop(inst)
                changed = True
        return changed

    def _eliminate_unreachable(self) -> bool:
        reachable = [False] * self.n
        self._dfs_reachable(0, reachable)
        changed = False
        for i in range(self.n):
            if not reachable[i] and self.program[i].op != OpCode.NOP:
                self._nop(self.program[i])
                changed = True
        return changed

    def _dfs_reachable(self, addr: int, reachable: List[bool]):
        while 0 <= addr < self.n and not reachable[addr]:
            reachable[addr] = True
            inst = self.program[addr]
            if inst.op in (OpCode.JUMP, OpCode.IF, OpCode.CALL):
                target = inst.jump_addr()
                if 0 <= target < self.n:
                    self._dfs_reachable(target, reachable)
                if inst.op == OpCode.JUMP:
                    break
            elif inst.op in (OpCode.RET, OpCode.STOP):
                break
            addr += 1

    def _compact(self) -> Tuple[List[Instruction], Dict[int, int], Dict[str, int]]:
        old_to_new: Dict[int, int] = {}
        new_program: List[Instruction] = []
        for i, inst in enumerate(self.program):
            if inst.op != OpCode.NOP:
                old_to_new[i] = len(new_program)
                new_program.append(inst)
        end_addr = len(new_program)
        for inst in new_program:
            if inst.op in (OpCode.JUMP, OpCode.IF, OpCode.CALL):
                old_target = inst.jump_addr()
                if old_target == self.n:
                    inst.set_jump_addr(end_addr)
                elif old_target in old_to_new:
                    inst.set_jump_addr(old_to_new[old_target])
                else:
                    inst.set_jump_addr(end_addr)
        # 重映射 addr_to_line
        new_addr_to_line = {}
        for old_addr, line in self.addr_to_line.items():
            if old_addr in old_to_new:
                new_addr_to_line[old_to_new[old_addr]] = line
        # 重映射 sub_entries
        new_sub_entries = {}
        for name, old_addr in self.sub_entries.items():
            if old_addr in old_to_new:
                new_sub_entries[name] = old_to_new[old_addr]
            else:
                new_sub_entries[name] = end_addr
        return new_program, new_addr_to_line, new_sub_entries

    @staticmethod
    def _nop(inst: Instruction):
        inst.op = OpCode.NOP
        inst.p1 = inst.p2 = inst.p3 = inst.p4 = inst.p5 = inst.p6 = 0
        inst.f1 = inst.f2 = 0.0


# ============================================================================
# SourceMap（源码级调试映射）
# ============================================================================
@dataclass
class SourceMap:
    """源码级调试映射表：指令地址 → 源码位置 / 子程序入口 / 变量符号"""
    addr_to_line: Dict[int, int]
    sub_entries: Dict[str, int]
    symbols: List[VarSymbol]

    def lookup_line(self, addr: int) -> Optional[int]:
        """根据指令地址查源码行号"""
        return self.addr_to_line.get(addr)

    def lookup_sub(self, name: str) -> Optional[int]:
        """根据子程序名查入口地址"""
        return self.sub_entries.get(name.upper())


# ============================================================================
# RobotParser：编译入口门面（词法 → 语法 → 代码生成 → 校验）
# ============================================================================
class RobotParser:
    @staticmethod
    def parse(text: str) -> List[Instruction]:
        program, _symbols, _source_map = RobotParser.parse_full(text)
        return program

    @staticmethod
    def parse_full(text: str, profile: "DeviceProfile" = None) -> Tuple[List[Instruction], List[VarSymbol], SourceMap]:
        """编译并同时返回符号表 + 源码级调试映射（可注入 DeviceProfile，默认 AM521）"""
        profile = profile or DEFAULT_PROFILE
        lexer = Lexer(text, profile)
        parser = Parser(lexer, profile)
        ast = parser.parse()
        gen = CodeGenerator(profile)
        program = gen.generate(ast)
        program, new_addr_to_line, new_sub_entries = PeepholeOptimizer(
            program, gen.addr_to_line, gen.sub_entries
        ).optimize()
        RobotParser._validate(program, profile)
        source_map = SourceMap(
            addr_to_line=new_addr_to_line,
            sub_entries=new_sub_entries,
            symbols=list(parser.symbols.values())
        )
        return program, source_map.symbols, source_map

    @staticmethod
    def _validate(program: List[Instruction], profile: "DeviceProfile" = None):
        profile = profile or DEFAULT_PROFILE
        n = len(program)
        for i, inst in enumerate(program):
            op = inst.op
            if op == OpCode.IF:
                if inst.p3 not in (0, 1, 2):
                    raise ParseError(f"指令{i}: IF 比较模式无效", inst.src_line)
                if inst.p3 in (0, 1) and (inst.p1 < 0 or inst.p1 > profile.max_var_index):
                    raise ParseError(f"指令{i}: 变量索引 V[{inst.p1}] 越界", inst.src_line)
                if not (0 <= inst.p2 <= 5):
                    raise ParseError(f"指令{i}: IF 比较符无效", inst.src_line)
                addr = inst.jump_addr()
                if not (0 <= addr <= n):
                    raise ParseError(f"指令{i}: IF 跳转地址 {addr} 越界 [0..{n}]",
                                     inst.src_line)
            if op == OpCode.JUMP:
                addr = inst.jump_addr()
                if not (0 <= addr <= n):
                    raise ParseError(f"指令{i}: JUMP 目标 {addr} 越界 [0..{n}]",
                                     inst.src_line)
            if op == OpCode.CALL:
                addr = inst.jump_addr()
                if not (0 <= addr < n):
                    raise ParseError(f"指令{i}: CALL 目标 {addr} 越界 [0..{n - 1}]",
                                     inst.src_line)
            if op == OpCode.ASSIGN:
                if inst.p1 < 0 or inst.p1 > profile.max_var_index:
                    raise ParseError(f"指令{i}: 变量索引 V[{inst.p1}] 越界", inst.src_line)
            if op in (OpCode.ADD, OpCode.SUB, OpCode.MUL, OpCode.DIV):
                for p in (inst.p1, inst.p2, inst.p3):
                    if p < 0 or p > profile.max_var_index:
                        raise ParseError(f"指令{i}: 运算变量索引越界", inst.src_line)
            if op in (OpCode.MOVJ, OpCode.MOVL, OpCode.MOVC):
                if inst.p1 < 0 or inst.p1 > profile.max_point_index:
                    raise ParseError(
                        f"指令{i}: 点位索引 P[{inst.p1}] 越界 [0..{profile.max_point_index}]",
                        inst.src_line)
                if op == OpCode.MOVC and (inst.p4 < 0 or inst.p4 > profile.max_point_index):
                    raise ParseError(
                        f"指令{i}: MOVC 过渡点索引 P[{inst.p4}] 越界 [0..{profile.max_point_index}]",
                        inst.src_line)
            do_ops = {OpCode.MOVJ_DO, OpCode.MOVL_DO, OpCode.MOVC_DO}
            if op in do_ops:
                if inst.p1 < 0 or inst.p1 > profile.max_point_index:
                    raise ParseError(f"指令{i}: 点位索引 P[{inst.p1}] 越界", inst.src_line)
                if op == OpCode.MOVC_DO and (inst.p4 < 0 or inst.p4 > profile.max_point_index):
                    raise ParseError(f"指令{i}: MOVC_DO 过渡点索引 P[{inst.p4}] 越界",
                                     inst.src_line)
                if inst.f2 > 0:
                    var_idx = int(inst.f2) - 1
                    if var_idx < 0 or var_idx > profile.max_var_index:
                        raise ParseError(f"指令{i}: DO 延时变量索引 V[{var_idx}] 越界",
                                         inst.src_line)
            if op == OpCode.SET_ACCE:
                if inst.f1 < 0 or inst.f2 < 0:
                    raise ParseError(f"指令{i}: SET_ACCE 参数不能为负", inst.src_line)
            pr_ops = {OpCode.PR_CURPOS, OpCode.PR_ASSIGN_P, OpCode.PR_ADD_VEC,
                      OpCode.PR_SUB_VEC, OpCode.PR_SET_COMP, OpCode.PR_MUL_SCALAR}
            if op in pr_ops and (inst.p1 < 0 or inst.p1 > profile.max_pr_index):
                raise ParseError(
                    f"指令{i}: PR 索引 PR[{inst.p1}] 越界 [0..{profile.max_pr_index}]",
                    inst.src_line)
            if op == OpCode.PR_ASSIGN_P and (inst.p2 < 0 or inst.p2 > profile.max_point_index):
                raise ParseError(f"指令{i}: 点位索引 P[{inst.p2}] 越界", inst.src_line)
            if op in (OpCode.PR_ADD_VEC, OpCode.PR_SUB_VEC):
                if (inst.p2 < 0 or inst.p2 > profile.max_pr_index
                        or inst.p3 < 0 or inst.p3 > profile.max_pr_index):
                    raise ParseError(f"指令{i}: PR 运算索引越界", inst.src_line)
            if op == OpCode.PR_SET_COMP and (inst.p2 < 0 or inst.p2 > 5):
                raise ParseError(
                    f"指令{i}: PR 分量索引无效 {inst.p2} (0=X,1=Y,2=Z,3=J1,4=J2,5=J3)",
                    inst.src_line)
            if op == OpCode.PR_MUL_SCALAR and (inst.p2 < 0 or inst.p2 > profile.max_pr_index):
                raise ParseError(f"指令{i}: PR 运算索引越界", inst.src_line)
            if op == OpCode.P_ASSIGN_PR:
                if inst.p1 < 0 or inst.p1 > profile.max_point_index:
                    raise ParseError(
                        f"指令{i}: 点位索引 P[{inst.p1}] 越界 [0..{profile.max_point_index}]",
                        inst.src_line)
                if inst.p2 < 0 or inst.p2 > profile.max_pr_index:
                    raise ParseError(
                        f"指令{i}: PR 索引 PR[{inst.p2}] 越界 [0..{profile.max_pr_index}]",
                        inst.src_line)
            if op == OpCode.DISTANCE_TO:
                if inst.p1 < 0 or inst.p1 > profile.max_var_index:
                    raise ParseError(f"指令{i}: 变量索引 V[{inst.p1}] 越界", inst.src_line)
                if inst.p2 < 0 or inst.p2 > profile.max_point_index:
                    raise ParseError(
                        f"指令{i}: 点位索引 P[{inst.p2}] 越界 [0..{profile.max_point_index}]",
                        inst.src_line)
            if op == OpCode.IS_MOVING:
                if inst.p1 < 0 or inst.p1 > profile.max_var_index:
                    raise ParseError(f"指令{i}: 变量索引 V[{inst.p1}] 越界", inst.src_line)
            if op == OpCode.SET_OVERALL:
                if inst.p3 == 1:
                    if inst.p1 < 0 or inst.p1 > profile.max_var_index:
                        raise ParseError(f"指令{i}: 变量索引 V[{inst.p1}] 越界",
                                         inst.src_line)
                elif inst.f1 < 0 or inst.f1 > 100:
                    raise ParseError(f"指令{i}: SET_OVERALL 参数范围 0~100", inst.src_line)
            if op == OpCode.GET_OVERALL:
                if inst.p1 < 0 or inst.p1 > profile.max_var_index:
                    raise ParseError(f"指令{i}: 变量索引 V[{inst.p1}] 越界", inst.src_line)
        if n > profile.max_program_len:
            raise ParseError(f"程序过长: {n} 条，最大 {profile.max_program_len} 条")


# ============================================================================
# RobotFormatter：反汇编（指令序列 → 带地址与标签的列表）
# ============================================================================
class RobotFormatter:
    @staticmethod
    def format(program: List[Instruction],
               symbols: Optional[List[VarSymbol]] = None) -> str:
        n = len(program)
        targets = set()
        for inst in program:
            if inst.op == OpCode.IF:
                targets.add(inst.jump_addr())
            elif inst.op == OpCode.JUMP:
                targets.add(RobotFormatter._jump_target(inst))
            elif inst.op == OpCode.CALL:
                targets.add(inst.jump_addr())
        targets.discard(n + 1)
        lines = [
            "// ============ 反汇编列表（v3.3 协议） ============",
            "// IF = 条件不成立则跳转; JUMP/IF 目标为绝对地址",
            "// 注意: 本列表仅供查看，不能直接重新编译",
        ]
        if symbols:
            lines.append("// ---- 符号表 ----")
            for s in symbols:
                if s.is_const:
                    t = f" : {s.type_name}" if s.type_name else ""
                    lines.append(f"//   CONST {s.name}{t} = {s.const_val}")
                elif s.is_map:
                    lines.append(f"//   MAP   {s.name} -> V[{s.index}]（别名）")
                else:
                    t = f" : {s.type_name}" if s.type_name else ""
                    lines.append(f"//   VAR   {s.name}{t} -> V[{s.index}]")
            lines.append("// -----------------")
        for i, inst in enumerate(program):
            if i in targets:
                lines.append(f"L_{i:04d}:")
            text = RobotFormatter._fmt(inst, i, n)
            if not text:
                continue
            if inst.src_line > 0:
                text += f"   // 源行 {inst.src_line}"
            lines.append(f"{i:04d}: {text}")
        return "\n".join(lines)

    @staticmethod
    def _jump_target(inst: Instruction) -> int:
        t = inst.jump_addr()
        if t == 0 and inst.p1 != 0:
            return inst.p1
        return t

    @staticmethod
    def _fmt(inst: Instruction, addr: int, prog_len: int) -> str:
        op = inst.op
        L = lambda t: f"L_{t:04d}" if t < prog_len else "程序末尾"
        if op == OpCode.NOP:
            return "NOP;"
        if op == OpCode.MOVJ:
            s = f"MOVJ(P[{inst.p1}],V{_v(inst.p2)},{_t(inst.p3)}"
            s += f",{_fmt_num(inst.f1)},{_fmt_num(inst.f2)});" if (inst.f1 or inst.f2) else ");"
            return s
        if op == OpCode.MOVL:
            s = f"MOVL(P[{inst.p1}],V{_v(inst.p2)},{_t(inst.p3)}"
            s += f",{_fmt_num(inst.f1)},{_fmt_num(inst.f2)});" if (inst.f1 or inst.f2) else ");"
            return s
        if op == OpCode.MOVC:
            s = f"MOVC(P[{inst.p1}],P[{inst.p4}],V{_v(inst.p2)},{_t(inst.p3)}"
            s += f",{_fmt_num(inst.f1)},{_fmt_num(inst.f2)});" if (inst.f1 or inst.f2) else ");"
            return s
        if op == OpCode.DELAY:
            return f"DELAY({_fmt_num(inst.f1)});"
        if op == OpCode.SET_DO:
            return f"SET_DO({inst.p1});"
        if op == OpCode.RESET_DO:
            return f"RESET_DO({inst.p1});"
        if op == OpCode.WAIT_DI:
            return (f"WAIT_DI({inst.p1},{_fmt_num(inst.f1)});" if inst.f1 > 0
                    else f"WAIT_DI({inst.p1});")
        if op == OpCode.GET_DI:
            return f"V[{inst.p1}] = GET_DI({inst.p2});"
        if op == OpCode.GET_DO:
            return f"V[{inst.p1}] = GET_DO({inst.p2});"
        if op == OpCode.ISIGNAL_DI:
            return f"ISIGNAL_DI(DI[{inst.p1}],{inst.p2});"
        if op == OpCode.IF:
            cmp_str = _c(inst.p2)
            if inst.p3 == 2:
                cond = f"常量 {_fmt_num(inst.f1)}"
            elif inst.p3 == 1:
                cond = f"V[{inst.p1}] {cmp_str} V[{int(inst.f1)}]"
            else:
                cond = f"V[{inst.p1}] {cmp_str} {_fmt_num(inst.f1)}"
            return f"IF {cond}  ; 不成立则跳转 {L(inst.jump_addr())}"
        if op == OpCode.JUMP:
            return f"JUMP {L(RobotFormatter._jump_target(inst))};"
        if op == OpCode.CALL:
            return f"CALL {L(inst.jump_addr())};"
        if op == OpCode.RET:
            return "RET;"
        if op == OpCode.STOP:
            return "STOP;"
        if op == OpCode.WAIT_MOTION_DONE:
            return "WAIT_MOTION_DONE;"
        if op == OpCode.STOPON_DI:
            return f"STOPON DI[{inst.p1}];"
        if op == OpCode.ASSIGN:
            return f"V[{inst.p1}] = {_fmt_num(inst.f1)};"
        if op == OpCode.ADD:
            return f"V[{inst.p1}] = V[{inst.p2}] + V[{inst.p3}];"
        if op == OpCode.SUB:
            return f"V[{inst.p1}] = V[{inst.p2}] - V[{inst.p3}];"
        if op == OpCode.MUL:
            return f"V[{inst.p1}] = V[{inst.p2}] * V[{inst.p3}];"
        if op == OpCode.DIV:
            return f"V[{inst.p1}] = V[{inst.p2}] / V[{inst.p3}];"
        if op == OpCode.ELSE:
            return "ELSE;  // 旧协议"
        if op == OpCode.ENDIF:
            return "END_IF;  // 旧协议"
        if op == OpCode.WHILE:
            cmp_str = _c(inst.p2)
            if inst.p3 == 2:
                cond = f"常量 {_fmt_num(inst.f1)}"
            elif inst.p3 == 1:
                cond = f"V[{inst.p1}] {cmp_str} V[{int(inst.f1)}]"
            else:
                cond = f"V[{inst.p1}] {cmp_str} {_fmt_num(inst.f1)}"
            return f"WHILE {cond} DO  // 旧协议"
        if op == OpCode.ENDWHILE:
            return "END_WHILE;  // 旧协议"
        if op == OpCode.FOR:
            return (f"FOR V[{inst.p1}] = {_fmt_num(inst.f1)} TO {_fmt_num(inst.f2)}"
                    f" DO  // 旧协议")
        if op == OpCode.ENDFOR:
            return f"END_FOR (step={_fmt_num(inst.f1)});  // 旧协议"
        if op == OpCode.BREAK:
            return f"BREAK -> {inst.p1};  // 旧协议"
        if op == OpCode.CONTINUE:
            return f"CONTINUE -> {inst.p1};  // 旧协议"
        if op == OpCode.LABEL:
            return f"// LABEL {inst.p1}"
        if op == OpCode.PR_CURPOS:
            return f"PR[{inst.p1}] = CURPOS();"
        if op == OpCode.PR_ASSIGN_P:
            return f"PR[{inst.p1}] = P[{inst.p2}];"
        if op == OpCode.PR_ADD_VEC:
            return f"PR[{inst.p1}] = PR[{inst.p2}] + PR[{inst.p3}];"
        if op == OpCode.PR_SUB_VEC:
            return f"PR[{inst.p1}] = PR[{inst.p2}] - PR[{inst.p3}];"
        if op == OpCode.PR_MUL_SCALAR:
            return f"PR[{inst.p1}] = PR[{inst.p2}] * {_fmt_num(inst.f1)};"
        if op == OpCode.PR_SET_COMP:
            comp_names = {0: "X", 1: "Y", 2: "Z", 3: "J1", 4: "J2", 5: "J3"}
            return f"PR[{inst.p1}].{comp_names.get(inst.p2, '?')} = {_fmt_num(inst.f1)};"
        if op == OpCode.P_ASSIGN_PR:
            return f"P[{inst.p1}] = PR[{inst.p2}];"
        if op == OpCode.SERVO_ON:
            return "SERVO ON;"
        if op == OpCode.SERVO_OFF:
            return "SERVO OFF;"
        if op == OpCode.SET_ACCE:
            return f"SET_ACCE({_fmt_num(inst.f1)},{_fmt_num(inst.f2)});"
        if op == OpCode.MOVJ_DO:
            return RobotFormatter._fmt_mov_do("MOVJ_DO", inst)
        if op == OpCode.MOVL_DO:
            return RobotFormatter._fmt_mov_do("MOVL_DO", inst)
        if op == OpCode.MOVC_DO:
            return RobotFormatter._fmt_mov_do("MOVC_DO", inst)
        if op == OpCode.DISTANCE_TO:
            return f"V[{inst.p1}] = DISTANCE_TO(P[{inst.p2}]);"
        if op == OpCode.IS_MOVING:
            return f"V[{inst.p1}] = IS_MOVING();"
        if op == OpCode.SET_OVERALL:
            if inst.p3 == 1:
                return f"SET_OVERALL(V[{inst.p1}]);"
            return f"SET_OVERALL({_fmt_num(inst.f1)});"
        if op == OpCode.GET_OVERALL:
            return f"V[{inst.p1}] = GET_OVERALL();"
        return f"// UNKNOWN OP {op}"

    @staticmethod
    def _fmt_mov_do(name: str, inst: Instruction) -> str:
        delay = f"V[{int(inst.f2) - 1}]" if inst.f2 > 0 else _fmt_num(inst.f1)
        pts = f"P[{inst.p1}],"
        if name == "MOVC_DO":
            pts += f"P[{inst.p4}],"
        return (f"{name}({pts}V{_v(inst.p2)},{_t(inst.p3)},{delay},"
                f"DO[{inst.p5}],{inst.p6});")


# ============================================================================
# RobotSourceFormatter：源码格式化器（自动缩进、关键字大写、操作符规范化）
# ============================================================================
class RobotSourceFormatter:
    KEYWORDS_UPPER = frozenset([
        "MOVJ", "MOVL", "MOVC", "MOVJ_DO", "MOVL_DO", "MOVC_DO",
        "DELAY", "SET_DO", "RESET_DO", "WAIT_DI", "WAIT_MOTION_DONE", "GET_DI", "GET_DO",
        "ISIGNAL_DI", "STOPON", "SET_ACCE", "SET_OVERALL", "GET_OVERALL",
        "DISTANCE_TO", "IS_MOVING", "CURPOS", "SERVO", "ON", "OFF",
        "IF", "ELSIF", "ELSE", "END_IF", "ENDIF", "WHILE", "END_WHILE", "ENDWHILE",
        "FOR", "END_FOR", "ENDFOR", "TO", "STEP", "DO", "THEN",
        "BREAK", "CONTINUE", "JUMP", "STOP", "AND", "OR", "NOT",
        "VAR", "CONST", "TRUE", "FALSE", "INT", "REAL", "BOOL", "MAP",
        "SUB", "END_SUB", "ENDSUB", "CALL", "RET",
        "PR", "P", "V", "DI", "X", "Y", "Z", "J1", "J2", "J3",
        "FINE", "C0", "C25", "C50", "C60", "C70", "C80", "C85",
        "C90", "C95", "C100",
    ])

    INDENT_INCREASE = frozenset(["IF", "WHILE", "FOR", "SUB", "ELSE", "ELSIF"])
    INDENT_DECREASE = frozenset([
        "ELSE", "ELSIF", "END_IF", "ENDIF", "END_WHILE", "ENDWHILE",
        "END_FOR", "ENDFOR", "END_SUB", "ENDSUB", "RET"
    ])

    @staticmethod
    def format(text: str) -> str:
        lines = text.splitlines()
        result = []
        indent = 0
        prev_empty = False

        for raw_line in lines:
            line, comment = RobotSourceFormatter._split_comment(raw_line)
            line_stripped = line.strip()

            if not line_stripped:
                if comment:
                    result.append("    " * indent + comment)
                    prev_empty = False
                elif not prev_empty and result:
                    result.append("")
                    prev_empty = True
                continue

            prev_empty = False

            first_word = line_stripped.split(None, 1)[0].upper().rstrip(";")
            if first_word in RobotSourceFormatter.INDENT_DECREASE:
                indent = max(0, indent - 1)

            formatted = RobotSourceFormatter._format_line(line_stripped)

            if comment:
                result.append("    " * indent + formatted + " " + comment)
            else:
                result.append("    " * indent + formatted)

            if (first_word in RobotSourceFormatter.INDENT_INCREASE
                    and not first_word.startswith("END_")
                    and first_word not in ("ENDIF", "ENDWHILE", "ENDFOR", "ENDSUB")):
                indent += 1

        while result and not result[-1].strip():
            result.pop()

        return "\n".join(result)

    @staticmethod
    def _split_comment(line: str) -> Tuple[str, str]:
        for marker in ("//", "#"):
            idx = line.find(marker)
            if idx >= 0:
                return line[:idx].rstrip(), line[idx:]
        return line.rstrip(), ""

    @staticmethod
    def _tokenize(line: str) -> List[str]:
        tokens = []
        i = 0
        while i < len(line):
            if line[i].isspace():
                i += 1
                continue
            if i + 1 < len(line) and line[i:i+2] in (":=", "==", "!=", "<>", ">=", "<="):
                tokens.append(line[i:i+2].upper())
                i += 2
                continue
            if line[i] in "()[];,:=+-*/<>.":
                tokens.append(line[i])
                i += 1
                continue
            j = i
            while j < len(line) and (line[j].isalnum() or line[j] == '_'):
                j += 1
            word = line[i:j]
            if word.upper() in RobotSourceFormatter.KEYWORDS_UPPER:
                tokens.append(word.upper())
            else:
                tokens.append(word)
            i = j
        return tokens

    @staticmethod
    def _format_line(line: str) -> str:
        tokens = RobotSourceFormatter._tokenize(line)
        if not tokens:
            return ""
        formatted = []
        no_space_before = {",", ";", ")", "]", "."}
        no_space_after = {"(", "[", "."}

        for idx, tok in enumerate(tokens):
            if idx == 0:
                formatted.append(tok)
                continue

            prev = tokens[idx - 1]
            need_space = True

            if tok in no_space_before:
                need_space = False
            elif prev in no_space_after:
                need_space = False
            elif tok in ("(", "["):
                need_space = False
            elif tok in ("+", "-") and prev in ("=", "(", "[", ",", ":", ":="):
                need_space = False

            if need_space:
                formatted.append(" ")
            formatted.append(tok)

        return "".join(formatted)


# ============================================================================
# 辅助函数
# ============================================================================
def _v(idx: int) -> str:
    return str((idx + 1) * 10) if 0 <= idx <= 9 else str(idx)


def _t(idx: int) -> str:
    names = {0: "C0", 1: "C25", 2: "C50", 3: "C60", 4: "C70",
             5: "C80", 6: "C85", 7: "C90", 8: "C95", 9: "C100", 10: "FINE"}
    return names.get(idx, f"C{idx}")


def _c(idx: int) -> str:
    return CMP_NAMES.get(idx, "?")


def _fmt_num(val: float) -> str:
    if val == int(val):
        return str(int(val))
    return f"{val:.3g}"