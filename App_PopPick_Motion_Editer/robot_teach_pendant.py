#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Robot Teach Pendant v2.6 - 机械臂离线编程工具 (PySide6)
兼容汇川 AM521 PLC 解释器协议 (PopPick V1.6.8)

更新：
1. 移植 xyz_gantry_desktop7_v6 的 Modbus 实时坐标读取线程架构
2. 3D 视图支持 PLC 实时 TCP 坐标驱动
3. 点位表增加"点位示教"按钮，可将当前 PLC 坐标写入选中点位
4. 增加位置寄存器 PR 与向量运算指令
5. 支持 P[n] = PR[m] 反向写入点位表
6. v2.6: CodeSys 风格代码提示 —— 带说明的补全列表 / 代码片段(IF/WHILE/FOR 一键成框) /
   参数签名提示(输入括号后实时高亮当前参数) / 悬停文档 / 注释中不补全
"""

import sys
import os
import re

import csv
import time


from typing import List, Optional, Dict, Tuple


from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QSizePolicy,
    QTreeWidget, QTreeWidgetItem, QLabel, QLineEdit, QGroupBox,
    QPushButton, QMessageBox, QDialog, QFormLayout, QDialogButtonBox,
    QSplitter, QPlainTextEdit, QTextEdit, QInputDialog, QFileDialog,
    QComboBox, QMenu, QProgressDialog,
    QCompleter, QToolTip
)
from PySide6.QtCore import Qt, QTimer, QRect, QSize, Signal, QThread, QObject, QUrl, QStringListModel, QEvent
from PySide6.QtGui import (
    QColor, QBrush, QFont, QFontMetrics, QPainter, QTextFormat, QTextCharFormat,
    QSyntaxHighlighter, QKeyEvent, QAction, QTextCursor
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from .robot3D import *
from .complier import *
from .com import SignalBridge,TcpPositionWorker,ModbusClient

# 若 3D 视图仍频繁黑屏/崩溃（GPU 驱动问题），可强制 WebEngine 走软件渲染（SwiftShader，
# 速度较慢但极稳）。注意必须在 QApplication 创建之前设置：
# os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

class RobotHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules = []
        keyword_fmt = QTextCharFormat()
        keyword_fmt.setForeground(QColor("#0033B3"))
        keyword_fmt.setFontWeight(QFont.Weight.Bold)
        for kw in ["VAR","CONST","TRUE","FALSE","INT","REAL","BOOL","MAP",
                   "SUB","END_SUB","ENDSUB","CALL","RET",
                   "MOVJ","MOVL","MOVC","MOVJ_DO","MOVL_DO","MOVC_DO","SET_ACCE",
                   "DELAY","SET_DO","RESET_DO","WAIT_DI","WAIT_MOTION_DONE","GET_DI",
                   "IF","ELSE","ELSIF","ENDIF","WHILE","ENDWHILE","FOR","ENDFOR","END_FOR","JUMP","STOP","THEN","DO","TO","STEP","END_IF","END_WHILE","AND","OR","NOT","BREAK","CONTINUE",
                   "PR","CURPOS","SERVO ON","SERVO OFF","STOPON","GET_DO","ISIGNAL_DI","DISTANCE_TO","IS_MOVING","SET_OVERALL","GET_OVERALL"]:
            self._rules.append((re.compile(r"\b" + kw + r"\b", re.IGNORECASE), keyword_fmt))
        trans_fmt = QTextCharFormat()
        trans_fmt.setForeground(QColor("#067D17"))
        self._rules.append((re.compile(r"\b(C0|C25|C50|C60|C70|C80|C85|C90|C95|C100|FINE)\b", re.IGNORECASE), trans_fmt))
        vel_fmt = QTextCharFormat()
        vel_fmt.setForeground(QColor("#1750EB"))
        self._rules.append((re.compile(r"\bV(10|20|30|40|50|60|70|80|90|100)\b", re.IGNORECASE), vel_fmt))
        point_fmt = QTextCharFormat()
        point_fmt.setForeground(QColor("#7A3E9D"))
        self._rules.append((re.compile(r"\bP\[(\d+|[^\W\d]\w*)\]", re.IGNORECASE), point_fmt))
        

        di_fmt = QTextCharFormat()
        di_fmt.setForeground(QColor("#7A3E9D"))
        self._rules.append((re.compile(r"\bDI\[(\d+|[^\W\d]\w*)\]", re.IGNORECASE), di_fmt))

        do_fmt = QTextCharFormat()
        do_fmt.setForeground(QColor("#7A3E9D"))
        self._rules.append((re.compile(r"\bDO\[(\d+|[^\W\d]\w*)\]", re.IGNORECASE), do_fmt)) 

        var_fmt = QTextCharFormat()
        var_fmt.setForeground(QColor("#9C3BB3"))
        self._rules.append((re.compile(r"\bV\[(\d+|[^\W\d]\w*)\]", re.IGNORECASE), var_fmt))
        pr_fmt = QTextCharFormat()        
        pr_fmt.setForeground(QColor("#B26A00"))
        self._rules.append((re.compile(r"\bPR\[(\d+|[^\W\d]\w*)\]", re.IGNORECASE), pr_fmt))
        # 方括号内为标识符(CONST 常量名)时，标识符本身保持默认变量颜色，只高亮 "DI[" 和 "]"
        ident_default_fmt = QTextCharFormat()
        ident_default_fmt.setForeground(QColor("#2B2B2B"))
        self._rules.append((re.compile(r"(?<=\[)[^\W\d]\w*(?=\])"), ident_default_fmt))
        num_fmt = QTextCharFormat()
        num_fmt.setForeground(QColor("#1750EB"))
        self._rules.append((re.compile(r"\b\d+(\.\d+)?\b"), num_fmt))
        comment_fmt = QTextCharFormat()
        comment_fmt.setForeground(QColor("#949494"))
        self._rules.append((re.compile(r"//.*"), comment_fmt))
        self._rules.append((re.compile(r"#.*"), comment_fmt))

    def highlightBlock(self, text: str):
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)
    def paintEvent(self, event):
        self.editor.line_number_area_paint_event(event)


class CodeEditor(QPlainTextEdit):
    errorLineChanged = Signal(int)

    # ══════════════════════════════════════════════════════════
    # CodeSys 风格代码提示数据
    # ══════════════════════════════════════════════════════════
    # 补全项: (插入键, 弹窗显示文本)
    # 弹窗显示"关键字 + 中文说明/签名"；选中后按插入键查 SNIPPETS 插入代码片段
    COMPLETION_ITEMS = [
        ("MOVJ",       "MOVJ  关节运动  (P[n],Vxx,Cxx/FINE[,acc,dec])"),
        ("MOVL",       "MOVL  直线运动  (P[n],Vxx,Cxx/FINE[,acc,dec])"),
        ("MOVC",       "MOVC  圆弧运动  (P[end],P[mid],Vxx,Cxx/FINE)"),
        ("MOVJ_DO",    "MOVJ_DO  关节运动+DO输出"),
        ("MOVL_DO",    "MOVL_DO  直线运动+DO输出"),
        ("MOVC_DO",    "MOVC_DO  圆弧运动+DO输出"),
        ("DELAY",      "DELAY  延时(ms)"),
        ("SET_DO",     "SET_DO  置位数字输出"),
        ("RESET_DO",   "RESET_DO  复位数字输出"),
        ("WAIT_DI",    "WAIT_DI  等待数字输入 (idx[,timeout])"),
        ("WAIT_MOTION_DONE", "WAIT_MOTION_DONE  等待运动完成"),
        ("GET_DI",     "GET_DI  读取数字输入"),
        ("GET_DO",     "GET_DO  读取数字输出"),
        ("ISIGNAL_DI", "ISIGNAL_DI  设置DI中断信号 (DI[idx],0/1)"),
        ("STOPON",     "STOPON  DI[n]为1时中断当前运动"),
        ("SET_ACCE",   "SET_ACCE  设置全局加/减速度 (acc,dec)"),
        ("SET_OVERALL","SET_OVERALL  全局速度倍率 0~100"),
        ("GET_OVERALL","GET_OVERALL  读取全局倍率到变量"),
        ("VAR",        "VAR  声明变量  name [:INT/REAL/BOOL] = 初值"),
        ("CONST",      "CONST  声明常量（编译期替换，不占寄存器）"),
        ("MAP",        "MAP  寄存器别名  name TO V[40~49]"),
        ("TRUE",       "TRUE  布尔常量 1"),
        ("FALSE",      "FALSE  布尔常量 0"),
        ("IF",         "IF  条件分支 ┐"),
        ("ELSIF",      "ELSIF  否则如果 │"),
        ("ELSE",       "ELSE  否则      │ 多行模板"),
        ("END_IF",     "END_IF  条件结束 ┘"),
        ("WHILE",      "WHILE  条件循环（多行模板）"),
        ("END_WHILE",  "END_WHILE  循环结束"),
        ("FOR",        "FOR  计数循环（多行模板）"),
        ("END_FOR",    "END_FOR  循环结束"),
        ("BREAK",      "BREAK  跳出最内层循环"),
        ("CONTINUE",   "CONTINUE  跳过本次迭代"),
        ("JUMP",       "JUMP  无条件跳转到绝对地址"),
        ("STOP",       "STOP  停止程序"),
        ("SUB",        "SUB  定义子程序（主程序之后，多行模板）"),
        ("END_SUB",    "END_SUB  子程序结束"),
        ("CALL",       "CALL  调用子程序  name"),
        ("RET",        "RET  子程序返回（可省略，END_SUB 自动补）"),
        ("SERVO_ON",   "SERVO ON  上伺服"),
        ("SERVO_OFF",  "SERVO OFF  断伺服"),
        ("CURPOS",     "CURPOS()  当前TCP位置（用于 PR[n]=CURPOS()）"),
        ("DISTANCE_TO","DISTANCE_TO(P[n])  TCP到点位距离"),
        ("IS_MOVING",  "IS_MOVING()  读取运动状态"),
        ("P[",         "P[n]  点位 [0..31]"),
        ("V[",         "V[n]  变量 [0..63]"),
        ("PR[",        "PR[n]  位置寄存器 [0..15]"),
        ("DI[",        "DI[n]  数字输入"),
        ("DO[",        "DO[n]  数字输出"),
        ("AND", "AND  逻辑与"), ("OR", "OR  逻辑或"), ("NOT", "NOT  逻辑非"),
        ("THEN", "THEN"), ("TO", "TO"), ("STEP", "STEP"), ("DO", "DO"),
        ("FINE", "FINE  精确到位"), ("C0", "C0"), ("C25", "C25"), ("C50", "C50"),
        ("C60", "C60"), ("C70", "C70"), ("C80", "C80"), ("C85", "C85"),
        ("C90", "C90"), ("C95", "C95"), ("C100", "C100"),
        ("V10", "V10"), ("V20", "V20"), ("V30", "V30"), ("V40", "V40"),
        ("V50", "V50"), ("V60", "V60"), ("V70", "V70"), ("V80", "V80"),
        ("V90", "V90"), ("V100", "V100"),
        ("X", "X 分量"), ("Y", "Y 分量"), ("Z", "Z 分量"),
        ("J1", "J1 分量"), ("J2", "J2 分量"), ("J3", "J3 分量"),
    ]
    COMPLETION_DISPLAY = [disp for _, disp in COMPLETION_ITEMS]

    # 赋值/比较右侧（= := == 之后）的取值函数推荐
    VALUE_ITEMS = [
        ("GET_DI",      "GET_DI(idx)  读取数字输入"),
        ("GET_DO",      "GET_DO(idx)  读取数字输出"),
        ("DISTANCE_TO", "DISTANCE_TO(P[n])  到点位距离"),
        ("IS_MOVING",   "IS_MOVING()  运动状态"),
        ("GET_OVERALL", "GET_OVERALL()  全局倍率"),
        ("V[",          "V[n]  变量"),
    ]
    VALUE_DISPLAY = [disp for _, disp in VALUE_ITEMS]

    # 代码片段: '|' = 光标落点, '{I}' = 当前行缩进
    SNIPPETS = {
        "VAR": "VAR | = 0;", "CONST": "CONST | = ;",
        "MAP": "MAP | TO V[40];",
        "MOVJ": "MOVJ(|);", "MOVL": "MOVL(|);", "MOVC": "MOVC(|);",
        "MOVJ_DO": "MOVJ_DO(|);", "MOVL_DO": "MOVL_DO(|);", "MOVC_DO": "MOVC_DO(|);",
        "DELAY": "DELAY(|);", "SET_DO": "SET_DO(|);", "RESET_DO": "RESET_DO(|);",
        "WAIT_DI": "WAIT_DI(|);", 
        "WAIT_MOTION_DONE": "WAIT_MOTION_DONE;",
        "SET_ACCE": "SET_ACCE(|);",
        "SET_OVERALL": "SET_OVERALL(|);", "ISIGNAL_DI": "ISIGNAL_DI(|);",
        "STOPON": "STOPON DI[|];",
        "GET_DI": "GET_DI(|)", "GET_DO": "GET_DO(|)", "DISTANCE_TO": "DISTANCE_TO(|)",
        "IS_MOVING": "IS_MOVING()", "GET_OVERALL": "GET_OVERALL()", "CURPOS": "CURPOS()",
        "IF":    "IF | THEN\n{I}    \n{I}END_IF;",
        "ELSIF": "ELSIF | THEN",
        "ELSE":  "ELSE",
        "WHILE": "WHILE | DO\n{I}    \n{I}END_WHILE;",
        "FOR":   "FOR V[0] = 0 TO | DO\n{I}    \n{I}END_FOR;",
        "SERVO_ON": "SERVO ON", "SERVO_OFF": "SERVO OFF",
        "SUB": "SUB |():\n{I}    \n{I}END_SUB", "END_SUB": "END_SUB",
        "CALL": "CALL |;", "RET": "RET;",
        "P[": "P[|]", "V[": "V[|]", "DI[": "DI[|]", "DO[": "DO[|]", "PR[": "PR[|]",
    }

    # 参数签名（calltip）: 指令名 -> (参数列表, 说明)
    SIGNATURES = {
        "MOVJ":   (["P[n] 目标点位", "V10~V100 速度", "Cxx/FINE 过渡带",
                    "acc 加速度(可选)", "dec 减速度(可选)"], "关节空间运动"),
        "MOVL":   (["P[n] 目标点位", "V10~V100 速度", "Cxx/FINE 过渡带",
                    "acc 加速度(可选)", "dec 减速度(可选)"], "直线运动"),
        "MOVC":   (["P[end] 终点", "P[mid] 过渡点", "V10~V100 速度",
                    "Cxx/FINE 过渡带"], "圆弧运动"),
        "MOVJ_DO": (["P[n] 目标点位", "Vxx 速度", "Cxx/FINE 过渡",
                     "do_distance(mm)|V[n]", "DO[idx]", "do_val 0/1"], "关节运动+DO输出"),
        "MOVL_DO": (["P[n] 目标点位", "Vxx 速度", "Cxx/FINE 过渡",
                     "do_distance(mm)|V[n]", "DO[idx]", "do_val 0/1"], "直线运动+DO输出"),
        "MOVC_DO": (["P[end] 终点", "P[mid] 过渡点", "Vxx 速度", "Cxx/FINE 过渡",
                     "do_distance(mm)|V[n]", "DO[idx]", "do_val 0/1"], "圆弧运动+DO输出"),
        "DELAY":  (["ms 毫秒"], "延时"),
        "SET_DO": (["idx 输出索引"], "置位数字输出"),
        "RESET_DO": (["idx 输出索引"], "复位数字输出"),
        "WAIT_DI": (["idx 输入索引", "timeout 超时ms(可选)"], "等待数字输入"),
        "GET_DI": (["idx 输入索引"], "读取数字输入（语句形式默认写入V[0]）"),
        "GET_DO": (["idx 输出索引"], "读取数字输出（语句形式默认写入V[0]）"),
        "ISIGNAL_DI": (["DI[idx] 输入", "val 0/1"], "设置DI中断信号"),
        "SET_ACCE": (["acc 加速度", "dec 减速度"], "设置全局加/减速度"),
        "SET_OVERALL": (["value 0~100 | V[n]"], "设置全局速度倍率"),
        "DISTANCE_TO": (["P[n] 点位"], "计算TCP到点位的欧氏距离"),
    }

    # 悬停文档（Quick Info）：由补全说明派生 + 逻辑/结构关键字补充
    HOVER_DOCS = {key: disp.split("  ", 1)[-1] if "  " in disp else disp
                  for key, disp in COMPLETION_ITEMS}
    HOVER_DOCS.update({
        "VAR": "声明变量：VAR name [:INT/REAL/BOOL] = 初值;\n"
               "只能放在程序开头；编译器从 V[0] 起自动分配寄存器；名字大小写不敏感",
        "CONST": "声明常量：CONST name = 常量表达式;\n"
                 "编译期直接替换为数值，不占 V 寄存器；可引用先声明的 CONST",
        "TRUE": "布尔常量 1（可用于 VAR b:BOOL=TRUE / IF 条件 / 赋值）",
        "FALSE": "布尔常量 0",
        "INT": "整数类型注解：VAR count : INT = 0;（初值必须为整数）",
        "REAL": "浮点类型注解：VAR ratio : REAL = 0.5;（V 寄存器即 LREAL）",
        "BOOL": "布尔类型注解：VAR done : BOOL = FALSE;（初值只能 0/1 或 TRUE/FALSE）",
        "AND": "逻辑与：IF V[0]==1 AND V[1]==2 THEN",
        "OR": "逻辑或：IF V[0]==1 OR V[1]==2 THEN",
        "NOT": "逻辑非：IF NOT V[0]==1 THEN",
        "THEN": "IF 条件 THEN ... END_IF;",
        "TO": "FOR V[n] = start TO end [STEP step] DO",
        "STEP": "FOR 循环步长（可为负）",
        "END_IF": "IF 分支结束", "END_WHILE": "WHILE 循环结束", "END_FOR": "FOR 循环结束",
        "SUB": "定义子程序：SUB name(形参, ...)： ... END_SUB\n"
               "必须放在主程序之后；名字允许中文；形参最多 5 个，值传递",
        "END_SUB": "子程序结束（自动补 RET，可不写 RETURN）",
        "CALL": "调用子程序：CALL name(实参, ...);\n"
                "实参可为任意表达式；形参按调用深度落在 V[50]~V[54] / V[55]~V[59]",
        "RET": "从子程序返回（只能用在 SUB 体内；END_SUB 会自动补，可省略）",
        "MAP": "寄存器别名：MAP name TO V[40~49];\n"
               "之后可用名字代替该 V 寄存器读写；VAR 自动分配会跳过专用区",
    })

    # PR[n]. / P[n]. 后的分量补全
    COMPLETION_COMPONENTS = ["X", "Y", "Z", "J1", "J2", "J3"]

    # VAR/CONST 声明 ':' 后的类型关键字补全
    COMPLETION_TYPES = ["INT", "REAL", "BOOL"]

    # 单词输入结束（敲了分隔符）时自动转大写的关键字集合；变量名不在其中，保持用户输入
    AUTO_UPPER_WORDS = frozenset([
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

    # 扫描文档中的 VAR/CONST 声明（用于把已声明变量加入补全/悬停）
    # 标识符规则与编译器一致：字母/下划线/中文开头，可含字母数字下划线（Unicode）
    IDENT_PATTERN = r'[^\W\d]\w*'        # \w 在 Python3 默认匹配 Unicode（含中文）
    DECL_RE = re.compile(
        r'^\s*(VAR|CONST)\s+([^\W\d]\w*)'
        r'(?:\s*:\s*(INT|REAL|BOOL))?', re.IGNORECASE | re.MULTILINE)
    # 扫描文档中的 SUB 子程序定义（用于 CALL 补全/悬停/重命名）
    SUB_RE = re.compile(r'^\s*SUB\s+([^\W\d]\w*)', re.IGNORECASE | re.MULTILINE)
    # 扫描 MAP 别名声明：MAP name TO V[40];
    MAP_RE = re.compile(r'^\s*MAP\s+([^\W\d]\w*)\s+TO\s+V\[(\d+)\]',
                        re.IGNORECASE | re.MULTILINE)

    def __init__(self, parent=None):
        super().__init__(parent)
        # 在线监视占位状态（CodeSys 方式）：干净源码备份 + 占位表，
        # 更新时整文原子替换、退出时整体还原，不做增量坐标编辑（杜绝文本错乱）
        self._source_backup: Optional[str] = None                   # 干净源码备份
        self._padded_spans: Optional[List[Tuple[int, int]]] = None  # [(占位起点, 空格数)]（干净坐标）
        self._padding_sig: Optional[List[Tuple[int, int]]] = None
        self._in_padding_update = False
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.setFont(QFont("Consolas", 11))
        self.update_line_number_area_width(0)   # 需在 setFont 之后，宽度按实际字体计算
        self.highlighter = RobotHighlighter(self.document())
        self.setStyleSheet("QPlainTextEdit { background-color: #FFFFFF; color: #2B2B2B; }")
        self._error_line = -1
        self._exec_line = -1
        self._init_completer()
        self._init_calltip()
        self.setMouseTracking(False)   # 悬停文档走 ToolTip 事件，无需追踪移动
        # 光标移动 / 文本变化时刷新参数提示（CodeSys 签名帮助）
        self.cursorPositionChanged.connect(self._update_calltip)
        self.textChanged.connect(self._update_calltip)
        # 已声明变量缓存：供补全列表与悬停文档使用
        self._declared_vars = []          # [(name, kind, type_or_None)]
        self._declared_subs = []          # [子程序名]（保持定义时的大小写）
        self.textChanged.connect(self._refresh_declared_vars)
        self._refresh_declared_vars()
        # 在线监视：变量当前值（由主窗口轮询 PLC 后注入）
        self._var_values: Optional[Dict[int, float]] = None
        self._var_symbol_map: Dict[str, dict] = {}   # 名字(大写) -> {name,index,is_const,const_val}
        self._io_values: Optional[Dict[str, Dict[int, int]]] = None  # {"di":{idx:val},"do":{idx:val}}
        # 占位跟随文本/数值/字号变化自动重算
        self.textChanged.connect(self._update_monitor_padding)

    # ════════════════ 补全（IntelliSense 列表 + 代码片段） ════════════════
    def _init_completer(self):
        self.completer = QCompleter(self)
        self.completer.setWidget(self)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setModel(QStringListModel(self.COMPLETION_DISPLAY, self.completer))
        self.completer.activated.connect(self._insert_completion)

    def _insert_completion(self, completion: str):
        """选中补全项：关键字直接插入；在 SNIPPETS 中的插入代码片段并定位光标"""
        tc = self.textCursor()
        prefix_len = len(self.completer.completionPrefix())
        if prefix_len > 0:
            tc.movePosition(QTextCursor.MoveOperation.Left,
                            QTextCursor.MoveMode.KeepAnchor, prefix_len)
            tc.removeSelectedText()
        # 显示文本 → 插入键（显示文本的第一个空白前 token 不一定是键，做反查）
        key = self._display_to_key(completion)
        snippet = self.SNIPPETS.get(key)
        if snippet is None:
            tc.insertText(key)
            self.setTextCursor(tc)
            return
        block_text = tc.block().text()
        indent = block_text[:len(block_text) - len(block_text.lstrip())]
        body = snippet.replace("{I}", indent)
        cursor_off = body.find("|")
        body = body.replace("|", "")
        start_pos = tc.position()
        tc.insertText(body)
        if cursor_off >= 0:
            tc.setPosition(start_pos + cursor_off)
            self.setTextCursor(tc)
        # 插入函数/指令片段后光标落在括号内 → 立即弹出参数提示
        self._update_calltip()

    def _display_to_key(self, display: str) -> str:
        for key, disp in self.COMPLETION_ITEMS + self.VALUE_ITEMS:
            if disp == display:
                return key
        if display in self.COMPLETION_COMPONENTS:
            return display
        return display.split(" ", 1)[0]

    def _identifier_at(self, pos=None) -> str:
        """取 pos 处的完整标识符（字母/数字/下划线/中文）。
        不能用 Qt 的 WordUnderCursor：它按 Unicode 断词规则把每个汉字拆成单独的词。"""
        doc = self.document().toPlainText()
        if pos is None:
            pos = self.textCursor().position()
        pos = min(pos, len(doc))
        s = pos
        while s > 0 and (doc[s - 1].isalnum() or doc[s - 1] == '_'):
            s -= 1
        e = pos
        while e < len(doc) and (doc[e].isalnum() or doc[e] == '_'):
            e += 1
        return doc[s:e]

    def _text_under_cursor(self) -> str:
        return self._identifier_at()

    def _cursor_prefix(self) -> str:
        """光标前的连续前缀（扫描 [ ] . 字母数字下划线）"""
        tc = self.textCursor()
        pos = tc.position()
        doc = self.document().toPlainText()
        start = pos
        while start > 0:
            c = doc[start - 1]
            if c.isalnum() or c in '[]_.':
                start -= 1
            else:
                break
        return doc[start:pos]

    def _line_upto_cursor(self) -> str:
        cursor = self.textCursor()
        return cursor.block().text()[:cursor.positionInBlock()]

    def _in_comment(self) -> bool:
        """光标处于行注释中时不提供补全（CodeSys 行为）"""
        line = self._line_upto_cursor()
        return "//" in line or "#" in line

    def _show_completer(self):
        self._trigger_auto_complete(force=True)

    def _popup_completer(self, words, prefix):
        self.completer.setModel(QStringListModel(words, self.completer))
        self.completer.setCompletionPrefix(prefix)
        if self.completer.completionCount() > 0:
            cr = self.cursorRect()
            cr.setWidth(self.completer.popup().sizeHintForColumn(0) + 20)
            self.completer.complete(cr)
        else:
            self.completer.popup().hide()

    def _refresh_declared_vars(self):
        """扫描文档中的 VAR/CONST 声明，缓存 (名字, 类别, 类型)，供补全与悬停使用"""
        decls = []
        text = self.document().toPlainText()
        for m in self.DECL_RE.finditer(text):
            decls.append((m.group(2), m.group(1).upper(),
                          m.group(3).upper() if m.group(3) else None))
        # MAP 别名：kind='MAP'，"类型"栏放目标寄存器，补全/悬停/重命名同样生效
        for m in self.MAP_RE.finditer(text):
            decls.append((m.group(1), 'MAP', f"V[{m.group(2)}]"))
        self._declared_vars = decls
        self._declared_subs = [m.group(1)
                               for m in self.SUB_RE.finditer(text)]

    def _declared_sub_displays(self) -> list:
        """已定义子程序的补全显示文本（保持定义时的大小写）"""
        return [f"{name}  SUB  已定义子程序" for name in self._declared_subs]

    def _declared_var_displays(self) -> list:
        """已声明变量的补全显示文本（保持声明时的大小写）"""
        out = []
        for name, kind, typ in self._declared_vars:
            if kind == 'MAP':
                out.append(f"{name}  MAP -> {typ}  寄存器别名")
            else:
                t = f" : {typ}" if typ else ""
                out.append(f"{name}  {kind}{t}  已声明变量")
        return out

    def _trigger_auto_complete(self, force=False):
        if self._in_comment():
            self.completer.popup().hide()
            return
        prefix = self._cursor_prefix()

        # 场景A: PR[n]. / P[n]. 后的分量补全
        m = re.match(r'(PR|P)\[\d+\]\.([A-Z0-9]*)$', prefix, re.IGNORECASE)
        if m:
            self._popup_completer(self.COMPLETION_COMPONENTS, m.group(2).upper())
            return

        # 场景A2: VAR/CONST 声明的 ':' 之后 → 类型关键字补全（变量名支持中文）
        m = re.match(r'^\s*(VAR|CONST)\s+[^\W\d]\w*\s*:\s*([A-Za-z]*)$',
                     self._line_upto_cursor(), re.IGNORECASE)
        if m:
            self._popup_completer(self.COMPLETION_TYPES, m.group(2).upper())
            return

        # 场景A3: CALL 之后 → 已定义子程序名补全（名字允许中文）
        m = re.match(r'^\s*CALL\s+(\w*)$', self._line_upto_cursor(), re.IGNORECASE)
        if m:
            self._popup_completer(self._declared_sub_displays(), m.group(1))
            return

        # 场景B: 赋值/比较右侧 → 推荐取值函数 + 已声明变量（CodeSys 的上下文感知）
        line_upto = self._line_upto_cursor()
        m_eq = re.search(r'(:=|==|=)\s*([A-Za-z0-9_]*)$', line_upto)
        if m_eq and not m_eq.group(2) and (force or line_upto.rstrip().endswith(('=', ':', '=='))):
            self._popup_completer(self._declared_var_displays() + self.VALUE_DISPLAY,
                                  m_eq.group(2))
            return

        # 场景C: 普通关键字补全（已声明变量排在关键字之前）
        word = self._text_under_cursor().upper()
        if not force and len(word) < 1:
            self.completer.popup().hide()
            return
        self._popup_completer(self._declared_var_displays() + self.COMPLETION_DISPLAY,
                              word)

    # ════════════════ 参数签名提示（Signature Help / Calltip） ════════════════
    def _init_calltip(self):
        self._calltip = QLabel(self.viewport())
        self._calltip.setStyleSheet(
            "QLabel { background-color: #F5F5F5; color: #2B2B2B;"
            " border: 1px solid #C0C0C0; border-radius: 4px; padding: 4px 8px; }")
        self._calltip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._calltip.hide()

    def _hide_calltip(self):
        if self._calltip.isVisible():
            self._calltip.hide()

    def _update_calltip(self):
        """光标位于 指令(...) 内时，显示签名并高亮当前参数"""
        if self._in_comment():
            self._hide_calltip()
            return
        doc = self.document().toPlainText()
        pos = self.textCursor().position()
        # 向左扫描未闭合的 '('（指令不跨行，遇换行即停）
        i = pos - 1
        depth = 0
        while i >= 0:
            c = doc[i]
            if c == '\n':
                self._hide_calltip()
                return
            if c == ')':
                depth += 1
            elif c == '(':
                if depth == 0:
                    break
                depth -= 1
            i -= 1
        if i < 0:
            self._hide_calltip()
            return
        open_idx = i
        # 提取 '(' 前的指令名
        j = open_idx - 1
        while j >= 0 and doc[j] in ' \t':
            j -= 1
        k = j
        while k >= 0 and (doc[k].isalnum() or doc[k] == '_'):
            k -= 1
        name = doc[k + 1:j + 1].upper()
        sig = self.SIGNATURES.get(name)
        if sig is None:
            # 动态签名：CALL 子程序名(...) → 显示该 SUB 的形参列表
            m = re.search(r'^\s*SUB\s+' + re.escape(name) + r'\s*\(([^)]*)\)',
                          doc, re.IGNORECASE | re.MULTILINE)
            if not m:
                self._hide_calltip()
                return
            params = [p.strip() for p in m.group(1).split(',') if p.strip()]
            sig = (params, "子程序形参（值传递，按调用深度分配 V[50]~V[59]）")
        # 统计光标前的顶层逗号数 → 当前参数序号
        arg_idx = 0
        d = 0
        for c in doc[open_idx + 1:pos]:
            if c == '(':
                d += 1
            elif c == ')':
                d -= 1
            elif c == ',' and d == 0:
                arg_idx += 1
        self._show_calltip(name, arg_idx, sig)

    def _show_calltip(self, name: str, arg_idx: int, sig=None):
        params, doc_text = sig if sig is not None else self.SIGNATURES[name]
        cur = min(arg_idx, len(params) - 1)
        parts = []
        for idx, p in enumerate(params):
            if idx == cur:
                parts.append(f'<b><span style="color:#1A6FD4">{p}</span></b>')
            else:
                parts.append(p)
        html = (f'<span style="color:#2B2B2B">{name}( ' +
                ", ".join(parts) +
                f' );</span><br><span style="color:#6E7781">{doc_text}</span>')
        self._calltip.setText(html)
        self._calltip.adjustSize()
        cr = self.cursorRect()
        # 默认显示在当前行上方（避免与补全弹窗重叠），上方放不下则放到下方
        y = cr.y() - self._calltip.height() - 6
        if y < 0:
            y = cr.y() + cr.height() + 4
        self._calltip.move(max(cr.x(), 0), y)
        self._calltip.show()

    # ════════════════ 悬停文档（Quick Info） ════════════════
    def event(self, e):
        if e.type() == QEvent.Type.ToolTip:
            tc = self.cursorForPosition(e.pos())
            # 用自实现标识符提取（兼容中文变量名；Qt WordUnderCursor 会拆散汉字）
            raw_word = self._identifier_at(tc.position())
            word = raw_word.upper()
            # 已声明变量优先：悬停显示声明类别/类型
            doc_text = None
            for name, kind, typ in self._declared_vars:
                if name.upper() == word:
                    if kind == 'MAP':
                        doc_text = f"MAP {name} -> {typ}（寄存器别名）"
                    else:
                        t = f" : {typ}" if typ else ""
                        doc_text = f"{kind} {name}{t}（已声明变量，编译器自动分配 V 寄存器）"
                    break
            if doc_text is None:
                for name in self._declared_subs:
                    if name.upper() == word:
                        doc_text = f"SUB {name}（已定义子程序，用 CALL {name}; 调用）"
                        break
            if doc_text is None:
                doc_text = self.HOVER_DOCS.get(word)
            if doc_text:
                sym = self._var_symbol_map.get(word)
                if sym is not None and self._var_values is not None \
                        and not sym["is_const"]:
                    val = self._var_values.get(sym["index"])
                    if val is not None:
                        doc_text += f"\n当前值: {val:g}"
                QToolTip.showText(e.globalPos(), doc_text, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    def focusOutEvent(self, e):
        self._hide_calltip()
        super().focusOutEvent(e)

    # ════════════════ 行号 / 高亮（原有功能） ════════════════
    def set_error_line(self, line_no: int):
        self._error_line = line_no
        self.highlight_current_line()
        if line_no > 0:
            block = self.document().findBlockByNumber(line_no - 1)
            if block.isValid():
                self.setTextCursor(QTextCursor(block))

    def set_exec_line(self, line_no: int, scroll: bool = True):
        self._exec_line = line_no
        self.highlight_current_line()
        if scroll and line_no > 0:
            block = self.document().findBlockByNumber(line_no - 1)
            if block.isValid():
                self.setTextCursor(QTextCursor(block))

    # ════════════════ 在线监视：变量当前值内联显示 ════════════════
    def set_var_symbols(self, symbols):
        """主窗口注入编译后的符号表（含编译器分配的 V 寄存器索引）"""
        self._var_symbol_map = {}
        for s in symbols:
            self._var_symbol_map[s["name"].upper()] = s
        self._update_monitor_padding()
        self.viewport().update()

    def set_var_values(self, values):
        """注入 V[n] 当前值（dict: 索引->值）；传 None 清除内联显示"""
        
        self._var_values = values
        self._update_monitor_padding()
        self.viewport().update()

    def set_io_values(self, di=None, do=None):
        """注入 DI/DO 当前值；不带参数调用则清除"""
        if di is None and do is None:
            self._io_values = None
        else:
            self._io_values = {"di": di, "do": do}
        self._update_monitor_padding()
        self.viewport().update()

    # ════════════════ 在线监视：CodeSys 风格数值框（占位空格把右侧代码右移） ════════════════
    def _monitor_active(self) -> bool:
        return (bool(self._var_values) and bool(self._var_symbol_map)) \
            or bool(self._io_values)

    def _tag_font(self) -> QFont:
        """数值框字体跟随文档字体（滚轮缩放时随之缩放），比正文字号略小"""
        tag_font = QFont(self.document().defaultFont())
        if tag_font.pointSizeF() > 0:
            tag_font.setPointSizeF(max(8.0, tag_font.pointSizeF() - 1.5))
        return tag_font

    def _line_tags(self, text: str):
        """收集一行内所有数值框 (标识符结束位置, 显示文本, 边框色)，按出现顺序"""
        tags = []
        if self._var_values and self._var_symbol_map:
            for m in re.finditer(self.IDENT_PATTERN, text):
                sym = self._var_symbol_map.get(m.group(0).upper())
                if sym is None or sym["is_const"]:
                    continue
                val = self._var_values.get(sym["index"])
                if val is None:
                    continue
                if sym.get("type_name") == "BOOL":
                    val_text = "TRUE" if val != 0 else "FALSE"
                else:
                    val_text = f"{val:g}"
                tags.append((m.end(), val_text, "#B08030"))
        if self._io_values:
            for m in re.finditer(r"\b(DI|DO)\[([^\]]+)\]", text, re.IGNORECASE):
                kind = m.group(1).upper()
                inner = m.group(2).strip()
                if inner.isdigit():
                    idx = int(inner)
                else:
                    sym = self._var_symbol_map.get(inner.upper())
                    if sym is None or not sym["is_const"]:
                        continue
                    idx = int(sym["const_val"])
                vals = self._io_values.get(kind.lower())
                if not vals or idx not in vals:
                    continue
                val_text = "TRUE" if vals[idx] else "FALSE"
                border = "#5E8C3A" if kind == "DI" else "#3E7E8E"
                tags.append((m.end(), val_text, border))
        tags.sort(key=lambda t: t[0])
        return tags

    # ── 占位空格（CodeSys 方式）：把数值框宽度以空格形式插到变量名后面， ──
    # ── 把该行右侧代码临时右移，退出在线时整体还原。                    ──
    # ── 实现上采用「干净源码备份 + 整文原子替换」：                    ──
    # ──   * 绝不做单点增量编辑，坐标不可能漂移（上一版逐点插入曾把文本搅乱）； ──
    # ──   * toPlainText() 对外永远返回备份原文，保存/编译/下载不会被污染。   ──
    def _build_padded(self, clean: str):
        """由干净源码生成 (加占位后的全文, 占位表[(占位起点, 空格数)])，坐标均为干净文本坐标"""
        fm_text = QFontMetrics(self.document().defaultFont())
        space_w = max(1, fm_text.horizontalAdvance(" "))
        fm_tag = QFontMetrics(self._tag_font())
        pad_x, gap = 5, 4
        out_lines = []
        spans = []
        abs_off = 0
        for line in clean.split("\n"):
            tags = self._line_tags(line)
            if tags:
                pieces, last = [], 0
                for end_pos, val_text, _b in tags:
                    w = fm_tag.horizontalAdvance(val_text) + pad_x * 2 + gap
                    n = max(1, -(-w // space_w))        # 向上取整，至少 1 格
                    pieces.append(line[last:end_pos])
                    pieces.append(" " * n)
                    spans.append((abs_off + end_pos, n))
                    last = end_pos
                pieces.append(line[last:])
                out_lines.append("".join(pieces))
            else:
                out_lines.append(line)
            abs_off += len(line) + 1
        return "\n".join(out_lines), spans

    @staticmethod
    def _map_pos_with_spans(pos: int, spans, reverse: bool = False) -> int:
        """光标坐标映射：正向 干净→加占位；反向 加占位→干净。spans 按起点升序"""
        if not reverse:
            return pos + sum(n for p, n in spans if p < pos)
        for p, n in spans:
            if p < pos:
                pos -= n
            else:
                break
        return pos

    def _replace_document_text(self, text: str, new_spans):
        """整文原子替换（占位更新/还原共用），保留光标与滚动位置"""
        old_spans = self._padded_spans or []
        clean_pos = self._map_pos_with_spans(self.textCursor().position(),
                                             old_spans, reverse=True)
        h = self.horizontalScrollBar().value()
        v = self.verticalScrollBar().value()
        self._in_padding_update = True
        try:
            cur = self.textCursor()
            cur.beginEditBlock()
            cur.select(QTextCursor.SelectionType.Document)
            cur.insertText(text)
            cur.endEditBlock()
        finally:
            self._in_padding_update = False
        self._padded_spans = new_spans
        # 光标 / 滚动条复位（光标按新旧占位表换算回同一源码位置）
        new_pos = self._map_pos_with_spans(clean_pos, new_spans or [])
        cur = self.textCursor()
        cur.setPosition(min(new_pos, self.document().characterCount() - 1))
        self.setTextCursor(cur)
        self.horizontalScrollBar().setValue(h)
        self.verticalScrollBar().setValue(v)
        # 占位/撤占位不进撤销栈：防止退出在线后 Ctrl+Z 把空格弄回来
        self.document().clearUndoRedoStacks()

    def _apply_monitor_padding(self):
        if self._source_backup is None:
            # 首次进入在线：此刻文档尚无占位，备份干净源码
            self._source_backup = super().toPlainText()
        padded, spans = self._build_padded(self._source_backup)
        if spans == self._padding_sig:
            return                      # 占位布局未变（值显示宽度没变），不折腾文档
        self._padding_sig = spans
        self._replace_document_text(padded, spans)

    def _restore_source(self):
        if self._source_backup is None:
            return
        backup = self._source_backup
        self._padding_sig = None
        self._replace_document_text(backup, None)   # 整文还原，坐标自然归零
        self._source_backup = None

    def _update_monitor_padding(self):
        """在线监视布局入口：进入/数值刷新/字号缩放时更新占位，退出时还原"""
        if self._in_padding_update:
            return
        if self._monitor_active():
            self._apply_monitor_padding()
        else:
            self._restore_source()

    def toPlainText(self) -> str:
        """对外返回干净源码：在线监视期间文档内是带占位的副本，
        保存/编译/下载一律取备份原文，不会被占位空格污染"""
        if self._source_backup is not None:
            return self._source_backup
        return super().toPlainText()

    def setPlainText(self, text: str):
        # 外部整文替换（打开文件/新建）时丢弃备份与占位状态
        self._source_backup = None
        self._padded_spans = None
        self._padding_sig = None
        super().setPlainText(text)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._monitor_active():
            painter = QPainter(self.viewport())
            self._paint_inline_values(painter)

    def _paint_inline_values(self, painter: QPainter):
        """CodeSys 风格在线监视：变量名 / DI[n] / DO[n] 右侧小色块显示当前值，
        色块所占宽度已由占位空格腾出，不会遮挡后面的代码"""
        tag_font = self._tag_font()
        fm = QFontMetrics(tag_font)
        painter.setFont(tag_font)
        block = self.firstVisibleBlock()
        while block.isValid():
            br = self.blockBoundingGeometry(block).translated(self.contentOffset())
            if br.top() > self.viewport().height():
                break
            if block.isVisible() and br.bottom() >= 0:
                for end_pos, val_text, border in self._line_tags(block.text()):
                    cursor = QTextCursor(block)
                    cursor.setPosition(block.position() + end_pos)
                    rect = self.cursorRect(cursor)
                    pad_x, pad_y = 5, 1
                    w = fm.horizontalAdvance(val_text) + pad_x * 2
                    h = fm.height() + pad_y * 2
                    x = rect.right() + 2
                    y = rect.top() + (rect.height() - h) // 2
                    painter.setPen(QColor(border))
                    painter.setBrush(QColor(239, 199, 155, 190))
                    painter.drawRoundedRect(x, y, w, h, 3, 3)
                    painter.setPen(QColor("#4A3728"))
                    painter.drawText(x, y, w, h,
                                     int(Qt.AlignmentFlag.AlignCenter), val_text)
            block = block.next()

    def line_number_area_width(self):
        digits = max(2, len(str(self.blockCount())))   # 至少 2 位，避免过窄
        return 10 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def wheelEvent(self, event):
        """Ctrl + 鼠标滚轮缩放字号（CodeSys 风格），并同步行号栏宽度与数值框占位"""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                f = QFont(self.document().defaultFont())
                size = f.pointSizeF() if f.pointSizeF() > 0 else 11.0
                f.setPointSizeF(max(6.0, min(48.0, size + (1.0 if delta > 0 else -1.0))))
                self.document().setDefaultFont(f)
                self.update_line_number_area_width(0)
                self.highlight_current_line()
                self._update_monitor_padding()   # 空格宽度变化 → 占位重算
            event.accept()
            return
        super().wheelEvent(event)

    def reset_zoom(self):
        self.setFont(QFont("Consolas", 11))
        self.document().setDefaultFont(QFont("Consolas", 11))
        self.update_line_number_area_width(0)
        self._update_monitor_padding()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#EFEFEF"))
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                if block_number + 1 == self._error_line:
                    painter.setPen(QColor("#E03131"))
                elif block_number + 1 == getattr(self, '_exec_line', -1):
                    painter.setPen(QColor("#0CA678"))
                else:
                    painter.setPen(QColor("#8A8A8A"))
                painter.drawText(0, int(top), self.line_number_area.width() - 5,
                                 self.fontMetrics().height(),
                                 Qt.AlignmentFlag.AlignRight, number)
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_number += 1

    def highlight_current_line(self):
        extra_selections = []
        extra_selections.extend(self._occurrence_selections())
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor("#F0F0F0"))
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extra_selections.append(selection)
        if self._exec_line > 0:
            block = self.document().findBlockByNumber(self._exec_line - 1)
            if block.isValid():
                sel = QTextEdit.ExtraSelection()
                sel.format.setBackground(QColor("#D6F0D6"))
                sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                sel.cursor = QTextCursor(block)
                sel.cursor.clearSelection()
                extra_selections.append(sel)
        if self._error_line > 0:
            block = self.document().findBlockByNumber(self._error_line - 1)
            if block.isValid():
                sel = QTextEdit.ExtraSelection()
                sel.format.setBackground(QColor("#F6DADA"))
                sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                sel.cursor = QTextCursor(block)
                sel.cursor.clearSelection()
                extra_selections.append(sel)
        self.setExtraSelections(extra_selections)

    def _occurrence_selections(self) -> list:
        """光标落在标识符（变量名等）上时，全文同名单词灰色底高亮（大小写不敏感）"""
        sels = []
        if self.isReadOnly():
            return sels
        word = self._text_under_cursor()
        if not word or len(word) < 2 or not re.fullmatch(self.IDENT_PATTERN, word):
            return sels
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#D9E7F5"))   # 浅蓝底（VS Code 浅色引用高亮风格）
        pattern = re.compile(
            r'(?<!\w)' + re.escape(word) + r'(?!\w)',
            re.IGNORECASE)
        for m in pattern.finditer(self.document().toPlainText()):
            sel = QTextEdit.ExtraSelection()
            sel.format = fmt
            c = QTextCursor(self.document())
            c.setPosition(m.start())
            c.setPosition(m.end(), QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = c
            sels.append(sel)
        return sels

    def _auto_upper_keyword(self):
        """单词结束（刚输入分隔符）时，若该单词是关键字则自动转大写；
        变量名不在关键字集合中，保持用户输入的大小写。注释内不处理。"""
        if self._in_comment():
            return
        pos = self.textCursor().position()
        doc = self.document().toPlainText()
        # 光标前一个是分隔符，再往前提取刚结束的单词
        i = pos - 2
        if i < 0:
            return
        end = i + 1
        while i >= 0 and (doc[i].isalnum() or doc[i] == '_'):
            i -= 1
        word = doc[i + 1:end]
        if not word or not word[0].isalpha():
            return
        upper = word.upper()
        if upper != word and upper in self.AUTO_UPPER_WORDS:
            c = QTextCursor(self.document())
            c.setPosition(i + 1)
            c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            c.insertText(upper)          # 长度不变，光标位置不受影响
            tc = self.textCursor()
            tc.setPosition(pos)
            self.setTextCursor(tc)

    # ════════════════ 跳转定义（Ctrl + 鼠标左键，VS Code 行为） ════════════════
    def mousePressEvent(self, e):
        if (e.button() == Qt.MouseButton.LeftButton
                and e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            word = self._identifier_at(self.cursorForPosition(e.pos()).position())
            if word and self.goto_definition(word):
                return   # 已跳转，不再走普通点击定位
        super().mousePressEvent(e)

    def goto_definition(self, word: str) -> bool:
        """Ctrl+点击名字：跳转到 SUB 子程序定义，或 VAR/CONST/MAP 声明处"""
        text = self.document().toPlainText()
        for pat in (
            re.compile(r'^\s*SUB\s+(' + re.escape(word) + r')(?!\w)',
                       re.IGNORECASE | re.MULTILINE),
            re.compile(r'^\s*(?:VAR|CONST|MAP)\s+(' + re.escape(word) + r')(?!\w)',
                       re.IGNORECASE | re.MULTILINE),
        ):
            m = pat.search(text)
            if m:
                tc = self.textCursor()
                tc.setPosition(m.start(1))   # 光标落在定义处的名字上
                self.setTextCursor(tc)
                self.centerCursor()
                return True
        return False

    # ════════════════ 变量重构（重命名，右键菜单 / F2） ════════════════
    def _rename_target(self):
        """光标下的单词若是已声明的 VAR/CONST 变量，返回 (声明名, 类别)，否则 None"""
        word = self._identifier_at()
        if not word or not re.fullmatch(self.IDENT_PATTERN, word):
            return None
        for name, kind, typ in self._declared_vars:
            if name.upper() == word.upper():
                return name, kind
        for name in self._declared_subs:
            if name.upper() == word.upper():
                return name, "SUB"
        return None

    def contextMenuEvent(self, e):
        # 右键时先把文本光标移到鼠标点击处（VS Code 行为），
        # 否则光标停留在原位置会导致取不到点击处的变量名
        self.setTextCursor(self.cursorForPosition(e.pos()))
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        act_rename = menu.addAction("重命名变量...\tF2")
        act_rename.setEnabled(True)   # 始终可点：点错位置时给出提示而不是灰色无响应
        chosen = menu.exec(e.globalPos())
        if chosen == act_rename:
            self.rename_variable()

    def rename_variable(self):
        """重命名当前变量：全文（声明处 + 所有引用，大小写不敏感）同步替换"""
        target = self._rename_target()
        if target is None:
            QMessageBox.information(
                self, "重命名变量",
                "光标处不是已声明的变量或子程序。\n\n"
                "请先把光标（或右键点击）放在 VAR / CONST 声明过的变量名、"
                "或 SUB 定义过的子程序名上，再执行重命名。")
            return
        old, kind = target
        label = {"SUB": "子程序", "MAP": "MAP 别名"}.get(kind, f"{kind} 变量")
        new, ok = QInputDialog.getText(
            self, "重命名变量", f"将{label} '{old}' 重命名为：",
            QLineEdit.EchoMode.Normal, old)
        if not ok:
            return
        new = new.strip()
        if not new:
            return
        if new == old:
            QMessageBox.information(self, "重命名变量", "新名字与旧名字相同，未做修改。")
            return
        # ---- 合法性校验（与编译器词法规则一致，支持中文名） ----
        if not re.fullmatch(self.IDENT_PATTERN, new):
            QMessageBox.warning(self, "重命名变量",
                                f"'{new}' 不是合法标识符（字母/下划线/中文开头，"
                                f"仅含字母、数字、下划线、中文）。")
            return
        up = new.upper()
        if up in self.AUTO_UPPER_WORDS or re.fullmatch(r'V\d+', up):
            QMessageBox.warning(self, "重命名变量",
                                f"'{new}' 与关键字/速度值冲突，不能用作变量名。")
            return
        for name, kind2, _ in self._declared_vars:
            if name.upper() == up and name.upper() != old.upper():
                QMessageBox.warning(self, "重命名变量",
                                    f"'{new}' 与已声明的变量 '{name}' 冲突。")
                return
        for name in self._declared_subs:
            if name.upper() == up and name.upper() != old.upper():
                QMessageBox.warning(self, "重命名变量",
                                    f"'{new}' 与已定义的子程序 '{name}' 冲突。")
                return
        # ---- 全文整词替换（从后往前，避免位置偏移；一次撤销块整体撤销） ----
        # \w 含中文，保证中文变量名的整词边界正确
        pattern = re.compile(
            r'(?<!\w)' + re.escape(old) + r'(?!\w)',
            re.IGNORECASE)
        matches = list(pattern.finditer(self.document().toPlainText()))
        cursor = self.textCursor()
        cursor.beginEditBlock()
        for m in reversed(matches):
            c = QTextCursor(self.document())
            c.setPosition(m.start())
            c.setPosition(m.end(), QTextCursor.MoveMode.KeepAnchor)
            c.insertText(new)   # 统一替换为新名字的大小写
        cursor.endEditBlock()

    def keyPressEvent(self, event: QKeyEvent):
        if (event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and event.key() == Qt.Key.Key_0):
            self.reset_zoom()
            return
        if event.key() == Qt.Key.Key_Escape and not self.completer.popup().isVisible():
            self._hide_calltip()
        if event.key() == Qt.Key.Key_F2:
            self.rename_variable()
            return
        if event.key() == Qt.Key.Key_Tab:
            cursor = self.textCursor()
            if cursor.hasSelection():
                self._indent_selection(4)
            else:
                cursor.insertText("    ")
            return
        if event.key() == Qt.Key.Key_Backtab or (
            event.key() == Qt.Key.Key_Tab
            and event.modifiers() == Qt.KeyboardModifier.ShiftModifier
        ):
            cursor = self.textCursor()
            if cursor.hasSelection():
                self._indent_selection(-4)
            else:
                self._unindent_current_line()
            return
        if event.key() == Qt.Key.Key_Slash and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self._toggle_comment()
            return
        if event.key() == Qt.Key.Key_Space and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self._show_completer()
            return
        if self.completer.popup().isVisible():
            if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return,
                               Qt.Key.Key_Escape, Qt.Key.Key_Tab,
                               Qt.Key.Key_Backtab):
                event.ignore()
                return

        # 关键字检测自动转大写：单词以分隔符结束（空格/分号/括号/回车等）时，
        # 若刚输入的单词是关键字（如 movj、if、then）则原地转为大写；
        # 变量名不在关键字集合中，保持用户输入的大小写（见 _auto_upper_keyword）。

        # ── 自动缩进: 当前行以 THEN/DO/ELSE 结尾时，回车自动缩进4空格 ──
        if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
            cursor = self.textCursor()
            block = cursor.block()
            line_text = block.text().strip().upper()
            if (line_text.endswith("THEN") or
                line_text.endswith("DO") or
                line_text == "ELSE" or
                (line_text.startswith("ELSIF ") and line_text.endswith("THEN"))):
                super().keyPressEvent(event)
                self._auto_upper_keyword()   # 行尾的 then/do/else 转大写
                raw_line = block.text()
                indent = len(raw_line) - len(raw_line.lstrip())
                self.textCursor().insertText(" " * (indent + 4))
                return

        super().keyPressEvent(event)

        # 输入分隔符（非字母数字/下划线）→ 检测刚结束的单词是否为关键字
        t = event.text()
        if t and len(t) == 1 and not (t.isalnum() or t in '._'):
            self._auto_upper_keyword()

        # 输入字母数字 / '.' / '=' 时触发补全（'=' 触发取值函数推荐）；
        # '(' ')' ',' 不触发补全，参数提示由 cursorPositionChanged 自动刷新
        if t.isalnum() or t in '.=':
            self._trigger_auto_complete()
        elif t not in '(),':
            self.completer.popup().hide()

    def _toggle_comment(self):
        cursor = self.textCursor()
        doc = self.document()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        block_start = doc.findBlock(start)
        block_end = doc.findBlock(end)

        cursor.beginEditBlock()
        all_commented = True
        block = block_start
        while block.isValid() and block.blockNumber() <= block_end.blockNumber():
            text = block.text()
            stripped = text.lstrip()
            if stripped and not stripped.startswith("//"):
                all_commented = False
                break
            block = block.next()

        block = block_start
        while block.isValid() and block.blockNumber() <= block_end.blockNumber():
            c = QTextCursor(block)
            c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            text = block.text()
            if not text.strip():
                block = block.next()
                continue
            if all_commented:
                pos = text.find("//")
                if pos >= 0:
                    c.movePosition(QTextCursor.MoveOperation.Right,
                                   QTextCursor.MoveMode.KeepAnchor, pos)
                    c.movePosition(QTextCursor.MoveOperation.Right,
                                   QTextCursor.MoveMode.KeepAnchor, 2)
                    c.removeSelectedText()
            else:
                c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                c.insertText("//")
            block = block.next()
        cursor.endEditBlock()

    def _indent_selection(self, spaces: int):
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        doc = self.document()
        block_start = doc.findBlock(start)
        block_end = doc.findBlock(end)
        cursor.beginEditBlock()
        block = block_start
        while block.isValid() and block.blockNumber() <= block_end.blockNumber():
            c = QTextCursor(block)
            c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            if spaces > 0:
                c.insertText(" " * spaces)
            elif spaces < 0:
                text = block.text()
                remove = min(-spaces, len(text) - len(text.lstrip()))
                if remove > 0:
                    c.movePosition(QTextCursor.MoveOperation.Right,
                                   QTextCursor.MoveMode.KeepAnchor, remove)
                    c.removeSelectedText()
            block = block.next()
        cursor.endEditBlock()

    def _unindent_current_line(self):
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        block = cursor.block()
        text = block.text()
        remove = min(4, len(text) - len(text.lstrip()))
        if remove > 0:
            cursor.movePosition(QTextCursor.MoveOperation.Right,
                                QTextCursor.MoveMode.KeepAnchor, remove)
            cursor.removeSelectedText()

    def get_lines(self, max_lines: int = 200) -> List[str]:
        """
        将代码区内容整理为字符串列表，按行划分。
        - 自动去除尾部空行
        - 每行去除尾部空白（保留缩进）
        - 最多返回 max_lines 行
        """
        text = self.toPlainText()
        lines = text.splitlines()
        # 去除尾部纯空行，但保留中间空行（它们可能是逻辑分隔）
        while lines and not lines[-1].strip():
            lines.pop()
        # 行尾去空白，保留缩进
        lines = [line.rstrip() for line in lines]
        if len(lines) > max_lines:
            lines = lines[:max_lines]
        return lines


class PointEditorDialog(QDialog):
    def __init__(self, parent=None, idx=0, data=None):
        super().__init__(parent)
        self.setWindowTitle(f"编辑点位 P[{idx}]")
        self.resize(300, 220)
        layout = QFormLayout(self)
        self.edits = {}
        for key in ["x", "y", "z", "j1", "j2", "j3"]:
            edit = QLineEdit(str(data.get(key, 0.0) if data else 0.0))
            self.edits[key] = edit
            layout.addRow(f"{key.upper()}:", edit)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_data(self):
        return {k: float(v.text() or 0) for k, v in self.edits.items()}


class PREditorDialog(QDialog):
    def __init__(self, parent=None, idx=0, data=None):
        super().__init__(parent)
        self.setWindowTitle(f"编辑位置寄存器 PR[{idx}]")
        self.resize(300, 220)
        layout = QFormLayout(self)
        self.edits = {}
        for key in ["x", "y", "z", "j1", "j2", "j3"]:
            edit = QLineEdit(str(data.get(key, 0.0) if data else 0.0))
            self.edits[key] = edit
            layout.addRow(f"{key.upper()}:", edit)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_data(self):
        return {k: float(v.text() or 0) for k, v in self.edits.items()}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AM521 PopPick 示教器 v2.6")
        self.resize(1500, 1000)
        self.modbus = ModbusClient()
        self.points = {i: {"x": 0.0, "y": 0.0, "z": 0.0, "j1": 0.0, "j2": 0.0, "j3": 0.0}
                       for i in range(32)}
        self._current_file = None

        self.program = None
        self._online_mode = False   # 在线模式：仅在点击「在线 🔄」后指示运行行，再点退出
        self._var_poll_timer = None   # 在线变量值轮询定时器
        self._warned_read_vars = False
        # 实时坐标读取相关
        self.bridge = SignalBridge()
        self.tcp_worker = None
        self._last_plc_pos = (0.0, 0.0, 0.0)

        self._build_ui()
        self._build_menubar()
        self._build_toolbar()
        self._build_statusbar()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_poll)
        self._timer.start(500)
        self.btn_clear_trail.clicked.connect(self._on_clear_trail)
        self.btn_clear_spheres.clicked.connect(self._on_clear_spheres)

        # 3D 视图看门狗：WebEngine 渲染进程崩溃/页面丢失时自动重建场景
        self._3d_miss = 0
        self._3d_cooldown_until = 0.0
        self._3d_watchdog = QTimer(self)
        self._3d_watchdog.timeout.connect(self._check_3d_alive)
        self._3d_watchdog.start(2000)

    def _make_action(self, text, slot, shortcut=None):
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(shortcut)
        act.triggered.connect(slot)
        return act

    def _build_ui(self):
        cw = QWidget()
        self.setCentralWidget(cw)
        hbox = QHBoxLayout(cw)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        hbox.addWidget(splitter)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(4, 4, 4, 4)
        self.editor = CodeEditor()
        self.editor.setPlainText(
           
            "MOVJ(P[0],V50,FINE,50,50);\n"
            "MOVL(P[1],V30,C100,80,80);\n"
            "PR[0] = CURPOS();\n"
            "PR[1] = P[0];\n"
            "PR[2] = PR[0] + PR[1];\n"
            "PR[2].Z = 100;\n"
            "PR[3] = PR[2] * 0.5;\n"
            "P[2] = PR[2];\n"
            "V[2] = IS_MOVING();\n"
            "DELAY(500);\n"
            "SET_DO(0);\n"
            "IF V[1] == 1 AND V[2] == 2 THEN\n"
            "    MOVL(P[2],V30,C100,80,80);\n"
            "END_IF;\n"
            "WHILE V[0] < 10 DO\n"
            "    V[0] = V[0] + 1;\n"
            "    DELAY(100);\n"
            "END_WHILE;\n"
            "STOP;\n"
        )
        # lv.addWidget(QLabel("程序编辑器 (支持 MOVJ/MOVL/MOVC/DELAY/SET_DO/WAIT_DI/IF/WHILE/PR/STOP)"))

        # 快捷模板按钮区
        template_box = QWidget()
        template_h = QHBoxLayout(template_box)
        template_h.setContentsMargins(0, 0, 0, 4)
        template_h.setSpacing(4)
        self._template_map = {
            
            "MOVJ":"MOVJ(P[0],V50,FINE,50,50);\n",
            "MOVL":"MOVL(P[0],V50,FINE,50,50);\n",
            "MOVC":"MOVC(P[0],P[1],V50,FINE,50,50);\n",
            "STOPON": "STOPON DI[0];\n",
            "IF": "IF V[0] == 1 THEN\n    SET_DO(0);\nELSE\n    RESET_DO(0);\nEND_IF;\n",
            "WHILE": "V[0] = 0;\nWHILE V[0] < 10 DO\n    V[0] = V[0] + 1;\n    DELAY(100);\nEND_WHILE;\n",
            "FOR": "FOR V[0] = 0 TO 5 DO\n    SET_DO(0);\n    DELAY(200);\n    RESET_DO(0);\n    DELAY(200);\nEND_FOR;\n",
            "PR": "PR[0] = CURPOS();\nPR[1] = P[0];\nPR[2] = PR[0] + PR[1];\nPR[2].Z = 100;\nPR[3] = PR[2] * 0.5;\n",
            "IS_MOVING": "V[0] = IS_MOVING();\nIF V[0] == 1 THEN\n    DELAY(100);\nEND_IF;\n",
            "WAIT": "WAIT_MOTION_DONE;\nIF V[0] == 1 THEN\n    SET_DO(1);\nEND_IF;\n",
            "DELAY": "DELAY(500);\n",
            "SET_DO": "SET_DO(0);\n",
            "GET_DI": "GET_DI(0);\n",
            "RESET_DO": "RESET_DO(0);\n",
            "STOP": "STOP;\n",
            "SERVO ON": "SERVO ON;\n",
            "SERVO OFF": "SERVO OFF;\n",
        }
        for name, tmpl in self._template_map.items():
            btn = QPushButton(name)
            btn.setStyleSheet("QPushButton { background: #FFFFFF; color: #2B2B2B; border: 1px solid #C0C0C0; border-radius: 3px; padding: 2px 10px; font-size: 11px; } QPushButton:hover { background: #3875D6; color: white; border: 1px solid #3875D6; }")
            btn.setFixedHeight(22)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, t=tmpl: self.editor.insertPlainText(t))
            template_h.addWidget(btn)
        template_h.addStretch()
        lv.addWidget(template_box)

        lv.addWidget(self.editor)

        splitter.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 4, 4, 4)
        rv.setSpacing(4)

        grp_3d = QGroupBox("3D 机械臂可视化")
        grp_3d.setStyleSheet("QGroupBox { color: #0B7285; border: 1px solid #9CC4D8; border-radius: 6px; margin-top: 8px; padding-top: 6px; font-weight: bold; } QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }")
        v3d = QVBoxLayout(grp_3d)
        v3d.setContentsMargins(2, 2, 2, 2)
        self.webview_3d = QWebEngineView()
        self.webview_3d.setMinimumHeight(280)
        self.webview_3d.setStyleSheet("background: #050510; border-radius: 4px;")
        self.webview_3d.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        v3d.addWidget(self.webview_3d)
        h3d = QHBoxLayout()
        self.btn_clear_trail = QPushButton("清除轨迹")
        self.btn_clear_trail.setStyleSheet("background: #6c5ce7; color: white; border: none; border-radius: 4px; padding: 4px 12px; font-size: 11px;")
        self.btn_clear_spheres = QPushButton("清除标记")
        self.btn_clear_spheres.setStyleSheet("background: #636e72; color: white; border: none; border-radius: 4px; padding: 4px 12px; font-size: 11px;")
        self.lbl_3d_pos = QLabel("末端: —")
        self.lbl_3d_pos.setStyleSheet("color: #2B2B2B; font-family: monospace; font-size: 11px;")
        self.lbl_tcp_pos = QLabel("PLC TCP: —")
        self.lbl_tcp_pos.setStyleSheet("color: #0B7285; font-family: monospace; font-size: 11px;")
        h3d.addWidget(self.btn_clear_trail)
        h3d.addWidget(self.btn_clear_spheres)
        h3d.addStretch()
        h3d.addWidget(self.lbl_3d_pos)
        h3d.addWidget(self.lbl_tcp_pos)
        v3d.addLayout(h3d)
        rv.addWidget(grp_3d, 2)

        grp_point = QGroupBox("点位表 (POS_REF) — 双击编辑，支持 CSV 导入导出")
        pv = QVBoxLayout(grp_point)
        self.tree_points = QTreeWidget()
        self.tree_points.setHeaderLabels(["点位", "X", "Y", "Z", "J1", "J2", "J3"])
        self.tree_points.setColumnWidth(0, 50)
        self.tree_points.doubleClicked.connect(self._on_edit_point)
        self.tree_points.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_points.customContextMenuRequested.connect(self._on_point_context_menu)
        self._refresh_point_table()
        pv.addWidget(self.tree_points)
        btn_h = QHBoxLayout()
        btn_read_points = QPushButton("从 PLC 读取")
        btn_write_points = QPushButton("写入 PLC")
        btn_import_csv = QPushButton("导入 CSV")
        btn_export_csv = QPushButton("导出 CSV")
        self.btn_teach_point = QPushButton("🎯 点位示教")
        self.btn_teach_point.setStyleSheet("background: linear-gradient(135deg, #0CA678, #00cec9); color: #001515; border: none; border-radius: 4px; padding: 4px 12px; font-size: 11px; font-weight: bold;")
        btn_read_points.clicked.connect(self._on_read_points)
        btn_write_points.clicked.connect(self._on_write_points)
        btn_import_csv.clicked.connect(self._on_import_csv)
        btn_export_csv.clicked.connect(self._on_export_csv)
        self.btn_teach_point.clicked.connect(self._on_teach_point)
        btn_h.addWidget(btn_read_points)
        btn_h.addWidget(btn_write_points)
        btn_h.addWidget(self.btn_teach_point)
        btn_h.addWidget(btn_import_csv)
        btn_h.addWidget(btn_export_csv)
        pv.addLayout(btn_h)
        rv.addWidget(grp_point)

        # ══════════════════════════════════════════════════════════
        # 手动示教区（Jog）— 替换原 PR 位置寄存器表
        # ══════════════════════════════════════════════════════════
        grp_teach = QGroupBox("手动示教 (Jog)")
        grp_teach.setStyleSheet(
            "QGroupBox { color: #0B7285; border: 1px solid #9CC4D8; border-radius: 6px; "
            "margin-top: 8px; padding-top: 6px; font-weight: bold; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
        )
        teach_v = QVBoxLayout(grp_teach)
        teach_v.setContentsMargins(6, 6, 6, 6)
        teach_v.setSpacing(6)

        # 1. 系统状态指示灯
        status_h = QHBoxLayout()
        self.lbl_sys_ready = QLabel("● 就绪")
        self.lbl_sys_ready.setStyleSheet("color: #0CA678; font-size: 12px;")
        self.lbl_sys_run = QLabel("● 运行")
        self.lbl_sys_run.setStyleSheet("color: #9E9E9E; font-size: 12px;")
        self.lbl_sys_err = QLabel("● 报警")
        self.lbl_sys_err.setStyleSheet("color: #9E9E9E; font-size: 12px;")
        status_h.addWidget(QLabel("系统状态:"))
        status_h.addWidget(self.lbl_sys_ready)
        status_h.addWidget(self.lbl_sys_run)
        status_h.addWidget(self.lbl_sys_err)
        status_h.addStretch()
        teach_v.addLayout(status_h)

        # 2. 坐标系与速度
        cfg_h = QHBoxLayout()
        cfg_h.addWidget(QLabel("坐标系:"))
        self.cbox_coord = QComboBox()
        self.cbox_coord.addItems(["关节坐标系", "直角坐标系"])
        self.cbox_coord.setStyleSheet("QComboBox { background: #FFFFFF; color: #2B2B2B; border: 1px solid #C0C0C0; border-radius: 3px; padding: 2px 6px; }")
        self.cbox_coord.currentIndexChanged.connect(self._on_coord_changed)
        cfg_h.addWidget(self.cbox_coord)

        cfg_h.addWidget(QLabel("速度:"))
        self.cbox_jog_speed = QComboBox()
        self.cbox_jog_speed.addItems(["1%", "5%", "10%", "20%", "50%", "100%"])
        self.cbox_jog_speed.setCurrentIndex(2)
        self.cbox_jog_speed.setStyleSheet("QComboBox { background: #FFFFFF; color: #2B2B2B; border: 1px solid #C0C0C0; border-radius: 3px; padding: 2px 6px; }")
        cfg_h.addWidget(self.cbox_jog_speed)
        cfg_h.addStretch()
        teach_v.addLayout(cfg_h)

        # 3. Jog 按钮网格
        jog_grid = QGridLayout()
        jog_grid.setSpacing(6)
        self.jog_buttons = {}

        axes_joint = ["J1", "J2", "J3"]
        for i in range(3):
            # 负按钮
            btn_neg = QPushButton(f"{axes_joint[i]}-")
            btn_neg.setFixedSize(70, 36)
            btn_neg.setStyleSheet(
                "QPushButton { background: #FFFFFF; color: #2B2B2B; border: 1px solid #C0C0C0; "
                "border-radius: 4px; font-weight: bold; } "
                "QPushButton:pressed { background: #3875D6; color: white; }"
            )
            btn_neg.setAutoRepeat(True)
            btn_neg.setAutoRepeatDelay(400)
            btn_neg.setAutoRepeatInterval(80)
            btn_neg.pressed.connect(lambda axis=i, dir=-1: self._on_jog_pressed(axis, dir))
            btn_neg.released.connect(lambda axis=i, dir=-1: self._on_jog_released(axis, dir))
            jog_grid.addWidget(btn_neg, i, 0)
            self.jog_buttons[f"{i}_neg"] = btn_neg

            # 标签
            lbl = QLabel(axes_joint[i])
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-weight: bold; color: #0B7285; font-size: 13px;")
            jog_grid.addWidget(lbl, i, 1)
            self.jog_buttons[f"{i}_label"] = lbl

            # 正按钮
            btn_pos = QPushButton(f"{axes_joint[i]}+")
            btn_pos.setFixedSize(70, 36)
            btn_pos.setStyleSheet(
                "QPushButton { background: #FFFFFF; color: #2B2B2B; border: 1px solid #C0C0C0; "
                "border-radius: 4px; font-weight: bold; } "
                "QPushButton:pressed { background: #3875D6; color: white; }"
            )
            btn_pos.setAutoRepeat(True)
            btn_pos.setAutoRepeatDelay(400)
            btn_pos.setAutoRepeatInterval(80)
            btn_pos.pressed.connect(lambda axis=i, dir=1: self._on_jog_pressed(axis, dir))
            btn_pos.released.connect(lambda axis=i, dir=1: self._on_jog_released(axis, dir))
            jog_grid.addWidget(btn_pos, i, 2)
            self.jog_buttons[f"{i}_pos"] = btn_pos

        jog_grid.setColumnStretch(0, 1)
        jog_grid.setColumnStretch(1, 1)
        jog_grid.setColumnStretch(2, 1)
        teach_v.addLayout(jog_grid)

        # 4. 当前位置显示（预留接口）
        pos_h = QHBoxLayout()
        pos_h.addWidget(QLabel("当前位置:"))
        self.lbl_teach_pos = QLabel("J1: 0.00  J2: 0.00  J3: 0.00")
        self.lbl_teach_pos.setStyleSheet("color: #0B7285; font-family: Consolas, monospace; font-size: 12px;")
        pos_h.addWidget(self.lbl_teach_pos)
        pos_h.addStretch()
        teach_v.addLayout(pos_h)

        # 5. 功能按钮
        func_h = QHBoxLayout()
        btn_home = QPushButton("🏠 回零")
        btn_home.setStyleSheet("QPushButton { background: #1971C2; color: white; border: none; border-radius: 4px; padding: 4px 12px; }")
        btn_home.clicked.connect(self._on_teach_home)

        btn_stop_jog = QPushButton("⏹ 停止")
        btn_stop_jog.setStyleSheet("QPushButton { background: #E03131; color: white; border: none; border-radius: 4px; padding: 4px 12px; }")
        btn_stop_jog.clicked.connect(self._on_teach_stop)

        btn_record = QPushButton("📝 记录点")
        btn_record.setStyleSheet("QPushButton { background: #0CA678; color: white; border: none; border-radius: 4px; padding: 4px 12px; }")
        btn_record.clicked.connect(self._on_teach_record)

        func_h.addWidget(btn_home)
        func_h.addWidget(btn_stop_jog)
        func_h.addWidget(btn_record)
        teach_v.addLayout(func_h)

        rv.addWidget(grp_teach)
        # ══════════════════════════════════════════════════════════

        grp_log = QGroupBox("操作日志")
        lg = QVBoxLayout(grp_log)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        lg.addWidget(self.log)
        rv.addWidget(grp_log)

        splitter.addWidget(right)
        splitter.setSizes([900, 600])
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.webview_3d.setHtml(HTML_3D, QUrl.fromLocalFile(os.path.join(base_dir, "") + os.sep))

    def _build_menubar(self):
        mb = self.menuBar()
        fm = mb.addMenu("文件(&F)")
        fm.addAction(self._make_action("新建", self._on_new, "Ctrl+N"))
        fm.addAction(self._make_action("打开...", self._on_open, "Ctrl+O"))
        fm.addAction(self._make_action("保存", self._on_save, "Ctrl+S"))
        fm.addAction(self._make_action("另存为...", self._on_save_as))
        fm.addSeparator()
        fm.addAction(self._make_action("退出", self.close, "Ctrl+Q"))

        em = mb.addMenu("编辑(&E)")
        em.addAction(self._make_action("撤销", self.editor.undo, "Ctrl+Z"))
        em.addAction(self._make_action("重做", self.editor.redo, "Ctrl+Y"))
        em.addSeparator()
        em.addAction(self._make_action("编译检查", self._on_compile, "F5"))
        em.addAction(self._make_action("插入模板...", self._on_insert_template))

        cm = mb.addMenu("PLC(&P)")
        cm.addAction(self._make_action("下载程序到 PLC", self._on_download, "F6"))
        cm.addAction(self._make_action("从 PLC 上载程序", self._on_upload, "F7"))
        cm.addSeparator()
        cm.addAction(self._make_action("连接/断开 PLC", self._on_toolbar_connect))
        cm.addSeparator()
        cm.addAction(self._make_action("启动任务 (47100=1)", self._on_cmd_start))
        cm.addAction(self._make_action("停止任务 (47100=2)", self._on_cmd_stop))
        cm.addAction(self._make_action("复位报警 (47100=3)", self._on_cmd_reset))


        hm = mb.addMenu("帮助(&H)")
        hm.addAction(self._make_action("指令手册", self._on_help))

    def _build_toolbar(self):
        tb = self.addToolBar("工具")
        tb.addAction(self._make_action("新建", self._on_new))
        tb.addAction(self._make_action("打开", self._on_open))
        tb.addAction(self._make_action("保存", self._on_save))
        tb.addSeparator()
        tb.addAction(self._make_action("编译", self._on_compile))
        tb.addAction(self._make_action("格式化", self._on_format))
        tb.addSeparator()
        tb.addAction(self._make_action("下载 ▼", self._on_download))
        tb.addAction(self._make_action("上载 ▲", self._on_upload))
        tb.addSeparator()
        self._act_connect = self._make_action("连接 PLC", self._on_toolbar_connect)
        self._act_connect.setCheckable(True)
        tb.addAction(self._act_connect)
        tb.addSeparator()
        tb.addAction(self._make_action("启动 ▶", self._on_cmd_start))
        tb.addAction(self._make_action("停止 ⏹", self._on_cmd_stop))
        tb.addAction(self._make_action("暂停 ⏸", self._on_cmd_halt))

        # 在线模式按钮：点击进入在线监视（指示运行行），再次点击退出在线模式
        self._act_online = self._make_action("在线 🔄", self._on_online_toggled)
        self._act_online.setCheckable(True)
        tb.addAction(self._act_online)

    def _build_statusbar(self):
        self.status = self.statusBar()
        self.status.showMessage("就绪 | 未连接 PLC | 模拟器: 空闲")

    def log_msg(self, msg):
        from datetime import datetime
        t = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{t}] {msg}")
        couser = self.log.textCursor()
        couser.movePosition(QTextCursor.MoveOperation.End)
        self.log.setTextCursor(couser)

    def _refresh_point_table(self):
        self.tree_points.clear()
        for i in range(32):
            d = self.points[i]
            item = QTreeWidgetItem([
                f"P[{i}]",
                f"{d['x']:.3f}", f"{d['y']:.3f}", f"{d['z']:.3f}",
                f"{d['j1']:.3f}", f"{d['j2']:.3f}", f"{d['j3']:.3f}"
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            self.tree_points.addTopLevelItem(item)

    def _on_point_context_menu(self, position):
        item = self.tree_points.itemAt(position)
        if not item:
            return
        idx = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        act_edit = menu.addAction(f"编辑 P[{idx}]")
        act_mark = menu.addAction(f"在 3D 视图中标记 P[{idx}]")
        act_teach = menu.addAction(f"🎯 示教 P[{idx}] (获取当前PLC坐标)")
        act = menu.exec(self.tree_points.viewport().mapToGlobal(position))
        if act == act_edit:
            self._on_edit_point_by_index(idx)
        elif act == act_mark:
            self._add_3d_sphere(idx)
            self.log_msg(f"[3D] 已标记 P[{idx}]: {self.points[idx]}")
        elif act == act_teach:
            self._teach_point_by_index(idx)

    def _on_edit_point_by_index(self, idx: int):
        dlg = PointEditorDialog(self, idx, self.points[idx])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.points[idx] = dlg.get_data()
            self._refresh_point_table()
            self.log_msg(f"P[{idx}] 已更新: {self.points[idx]}")

    def _on_edit_point(self, index):
        item = self.tree_points.currentItem()
        if not item:
            return
        idx = item.data(0, Qt.ItemDataRole.UserRole)
        dlg = PointEditorDialog(self, idx, self.points[idx])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.points[idx] = dlg.get_data()
            self._refresh_point_table()
            self.log_msg(f"P[{idx}] 已更新: {self.points[idx]}")

    def _on_read_points(self):
        if not self.modbus.is_connected():
            QMessageBox.warning(self, "警告", "请先连接 PLC")
            return
        ok = 0
        for i in range(32):
            data = self.modbus.read_point(i)
            if data:
                self.points[i] = data
                ok += 1
        self._refresh_point_table()
        self.log_msg(f"已从 PLC 读取点位: {ok}/32 成功")

    def _on_write_points(self):
        if not self.modbus.is_connected():
            QMessageBox.warning(self, "警告", "请先连接 PLC")
            return
        ok = 0
        for i in range(32):
            if self.modbus.write_point(i, self.points[i]):
                ok += 1
        self.log_msg(f"点位写入完成: {ok}/32 成功")

    def _on_import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入点位 CSV", "", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    idx = int(row.get("index", -1))
                    if 0 <= idx < 32:
                        self.points[idx] = {
                            "x": float(row.get("x", 0)), "y": float(row.get("y", 0)),
                            "z": float(row.get("z", 0)), "j1": float(row.get("j1", 0)),
                            "j2": float(row.get("j2", 0)), "j3": float(row.get("j3", 0))
                        }
            self._refresh_point_table()
            self.log_msg(f"已导入点位: {path}")
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    def _on_export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出点位 CSV", "", "CSV (*.csv)")
        if not path:
            return
        if not path.endswith(".csv"):
            path += ".csv"
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["index", "x", "y", "z", "j1", "j2", "j3"])
                writer.writeheader()
                for i in range(32):
                    d = self.points[i]
                    writer.writerow({"index": i, **d})
            self.log_msg(f"已导出点位: {path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _on_teach_point(self):
        item = self.tree_points.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先在点位表中选中一个点位")
            return
        idx = item.data(0, Qt.ItemDataRole.UserRole)
        self._teach_point_by_index(idx)

    def _teach_point_by_index(self, idx: int):
        if not self.modbus.is_connected():
            QMessageBox.warning(self, "警告", "请先连接 PLC")
            return
        if self.tcp_worker is None:
            QMessageBox.warning(self, "警告", "TCP坐标读取线程未运行")
            return

        x, y, z = self.tcp_worker.get_last_pos()
        self.points[idx]["x"] = x
        self.points[idx]["y"] = y
        self.points[idx]["z"] = z
        self._refresh_point_table()
        self.log_msg(f"[示教] P[{idx}] <- TCP坐标 X={x:.3f} Y={y:.3f} Z={z:.3f}")

        if self.modbus.write_point(idx, self.points[idx]):
            self.log_msg(f"[示教] P[{idx}] 已同步写入 PLC")
        else:
            self.log_msg(f"[示教] P[{idx}] 写入 PLC 失败")

        self._add_3d_sphere(idx)

    def _on_new(self):
        self.editor.setPlainText("// 新程序\n")
        self._current_file = None
        self.setWindowTitle("AM521 PopPick 示教器 v2.6 - 未命名")
        self.editor.set_error_line(-1)

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开程序", "", "Robot 程序 (*.robot *.txt)")
        if path:
            with open(path, "r", encoding="utf-8") as f:
                self.editor.setPlainText(f.read())
            self._current_file = path
            self.setWindowTitle(f"AM521 PopPick 示教器 v2.6 - {path}")
            self.editor.set_error_line(-1)
            # ★ 新增：加载调试映射表
            map_path = path.replace(".robot", ".map").replace(".txt", ".map")
            if os.path.exists(map_path):
                try:
                    import json
                    from complier import SourceMap, VarSymbol
                    with open(map_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._source_map = SourceMap(
                        addr_to_line={int(k): v for k, v in data["addr_to_line"].items()},
                        sub_entries=data["sub_entries"],
                        symbols=[VarSymbol(**s) for s in data["symbols"]]
                    )
                    self.log_msg(f"已加载调试映射表: {map_path}")
                except Exception as e:
                    self.log_msg(f"加载调试映射表失败: {e}")
                    self._source_map = None
            else:
                self._source_map = None

            self.log_msg(f"打开文件: {path}")

    def _on_save(self):
        if self._current_file:
            with open(self._current_file, "w", encoding="utf-8") as f:
                f.write(self.editor.toPlainText())
            self.log_msg(f"已保存: {self._current_file}")
        else:
            self._on_save_as()

    def _on_save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存程序", "", "Robot 程序 (*.robot)")
        if path:
            if not path.endswith(".robot"):
                path += ".robot"
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.editor.toPlainText())
            self._current_file = path
            self.setWindowTitle(f"AM521 PopPick 示教器 v2.6 - {path}")
            self.log_msg(f"另存为: {path}")

    def _on_compile(self):
        text = self.editor.toPlainText()
        self.editor.set_error_line(-1)
        self.editor.set_exec_line(-1)
        try:
            # prog = RobotParser.parse(text)
            prog, symbols, src_map = RobotParser.parse_full(text)
            self.log_msg(f"编译成功: 共 {len(prog)} 条指令")
            self.program = prog
            self._source_map = src_map   # ★ 缓存调试映射表

            self.modbus.trans_program_texts(self.editor.get_lines())

            print('#'*100)
            print(self.editor.get_lines())
            for a in prog:
                print(a)
            return prog
        except ParseError as e:
            self.editor.set_error_line(e.line_no)
            QMessageBox.critical(self, "编译错误", str(e))
            self.log_msg(f"编译失败: {e}")
            return None
        except Exception as e:
            QMessageBox.critical(self, "编译错误", str(e))
            self.log_msg(f"编译失败: {e}")
            return None

    def _on_format(self):
        """格式化代码: 自动缩进、关键字大写、操作符规范化"""
        text = self.editor.toPlainText()
        formatted = RobotSourceFormatter.format(text)
        cursor = self.editor.textCursor()
        old_pos = cursor.position()
        self.editor.setPlainText(formatted)
        cursor.setPosition(min(old_pos, len(formatted)))
        self.editor.setTextCursor(cursor)
        self.log_msg("代码已格式化: 自动缩进、关键字大写、操作符规范化")

    def _on_insert_template(self):
        templates = {
            "简单搬运": "SET_ACCE(50,50);\nMOVJ(P[0],V50,FINE);\nMOVL(P[1],V30,C100);\nSET_DO(0);\nDELAY(500);\nRESET_DO(0);\nMOVL(P[0],V30,C100);\nSTOP;\n",
            "IF 条件分支": "IF V[0] == 1 THEN\n    SET_DO(0);\nELSE\n    RESET_DO(0);\nEND_IF;\n",
            "WHILE 循环": "V[0] = 0;\nWHILE V[0] < 10 DO\n    V[0] = V[0] + 1;\n    DELAY(100);\nEND_WHILE;\n",
            "等待输入": "WAIT_DI(0,5000);\nIF V[0] == 1 THEN\n    SET_DO(1);\nEND_IF;\n",
            "等待运动完成": "MOVJ(P[0],V50,FINE);\nWAIT_MOTION_DONE;\nSET_DO(0);\n",
            "AND 复合条件": "IF V[1] == 1 AND V[2] == 2 THEN\n    MOVL(P[3],V30,FINE);\nEND_IF;\n",
            "OR 复合条件": "IF V[1] == 1 OR V[2] == 2 THEN\n    SET_DO(3);\nEND_IF;\n",
            "ELSIF 多分支": "IF V[0] == 1 THEN\n    SET_DO(0);\nELSIF V[0] == 2 THEN\n    SET_DO(1);\nELSE\n    RESET_DO(0);\nEND_IF;\n",
            "GET_DI 读取输入": "V[0] = GET_DI(0);\nIF V[0] == 1 THEN\n    SET_DO(0);\nEND_IF;\n",
            "NOT 条件": "IF NOT V[0] == 1 THEN\n    SET_DO(0);\nEND_IF;\n",
            "FOR 循环": "FOR V[0] = 0 TO 5 DO\n    SET_DO(0);\n    DELAY(200);\n    RESET_DO(0);\n    DELAY(200);\nEND_FOR;\n",
            "FOR 递减": "FOR V[0] = 10 TO 0 STEP -2 DO\n    V[1] = V[0] * 2;\n    DELAY(100);\nEND_FOR;\n",
            "BREAK 中断循环": "V[0] = 0;\nWHILE V[0] < 10 DO\n    V[0] = V[0] + 1;\n    IF V[0] == 5 THEN\n        BREAK;\n    END_IF;\n    DELAY(100);\nEND_WHILE;\n",
            "CONTINUE 跳过迭代": "FOR V[0] = 0 TO 5 DO\n    IF V[0] == 2 THEN\n        CONTINUE;\n    END_IF;\n    SET_DO(0);\n    DELAY(200);\n    RESET_DO(0);\nEND_FOR;\n",
            "PR 获取当前位置": "PR[0] = CURPOS();\nPR[1] = P[0];\nPR[2] = PR[0] + PR[1];\nPR[2].Z = 100;\n",
            "PR 标量乘法": "PR[0] = P[0];\nPR[1] = PR[0] * 0.5;\n// PR[1] 各分量为 PR[0] 的一半\n",
            "IS_MOVING 状态检测": "V[0] = IS_MOVING();\nIF V[0] == 1 THEN\n    DELAY(50);\nEND_IF;\n",
            "PR 偏移计算": "PR[0] = P[0];\nPR[1] = P[1];\nPR[2] = PR[1] - PR[0];\nP[2] = PR[2];\n// PR[2] 现在是从P0指向P1的向量，并写回P[2]\n",
            "MOVJ_DO 运动+DO": "SET_ACCE(50,50);\nMOVJ_DO(P[0],V50,FINE,100.0,DO[0],1);\nDELAY(200);\nRESET_DO(0);\n",
            "MOVL_DO 运动+DO": "SET_ACCE(80,80);\nMOVL_DO(P[1],V30,C100,50.0,DO[1],1);\nDELAY(200);\nRESET_DO(1);\n",
        }
        items = list(templates.keys())
        item, ok = QInputDialog.getItem(self, "插入模板", "选择模板:", items, 0, False)
        if ok and item in templates:
            cursor = self.editor.textCursor()
            cursor.insertText(templates[item])
            self.log_msg(f"已插入模板: {item}")

    def _on_download(self):
        prog = self._on_compile()
        if prog is None:
            return
        if not self.modbus.is_connected():
            QMessageBox.warning(self, "警告", "请先连接 PLC")
            return
        if self.modbus.write_program(prog):
            self.log_msg(f"程序下载成功: {len(prog)} 条指令 -> 保持寄存器 {self.modbus.REG_PROGRAM_BASE}")
            QMessageBox.information(self, "完成", f"已下载 {len(prog)} 条指令到 PLC")
            # ★ 新增：保存源码调试映射表
            if self._current_file:
                src_map = self._source_map
                import json
                map_path = self._current_file.replace(".robot", ".map")
                try:
                    with open(map_path, "w", encoding="utf-8") as f:
                        json.dump({
                            "addr_to_line": {str(k): v for k, v in src_map.addr_to_line.items()},
                            "sub_entries": src_map.sub_entries,
                            "symbols": [
                                {"name": s.name, "index": s.index, "is_const": s.is_const,
                                 "const_val": s.const_val, "type_name": s.type_name,
                                 "is_map": s.is_map, "src_line": s.src_line}
                                for s in src_map.symbols
                            ]
                        }, f, ensure_ascii=False, indent=2)
                    self.log_msg(f"调试映射表已保存: {map_path}")
                except Exception as e:
                    self.log_msg(f"保存调试映射表失败: {e}")
            # self._on_write_points()

        else:
            QMessageBox.critical(self, "失败", "程序下载失败，请检查通信")

    def _on_upload(self):
        if not self.modbus.is_connected():
            QMessageBox.warning(self, "警告", "请先连接 PLC")
            return
        count, ok = QInputDialog.getInt(self, "上载程序", "读取指令条数:", 20, 1, MAX_PROGRAM_LEN)
        if not ok:
            return
        prog = self.modbus.read_program(count)
        if prog:
            text = RobotFormatter.format(prog)
            self.editor.setPlainText(text)
            self.log_msg(f"程序上载成功: {len(prog)} 条指令")
        else:
            QMessageBox.critical(self, "失败", "程序上载失败")

    def _on_cmd_start(self):
        if not self.modbus.is_connected():
            return
        if self.modbus.write_system_out(0, [1]):
            self.log_msg("发送启动命令 (47100=1)")

    def _on_cmd_stop(self):
        if not self.modbus.is_connected():
            return
        if self.modbus.write_system_out(0, [2]):
            self.log_msg("发送停止命令 (47100=2)")
    def _on_cmd_halt(self):
            if not self.modbus.is_connected():
                return
            if self.modbus.write_system_out(1, [1]):
                self.log_msg("发送停止命令 (47101=1)")

    def _on_cmd_reset(self):
        if not self.modbus.is_connected():
            return
        if self.modbus.write_system_out(0, [3]):
            self.log_msg("发送复位命令 (47100=3)")

    def _update_ui(self,sys_status,ipc):
      
        if sys_status & 0x0001:
            state = "running"
        elif sys_status & 0x0002:
            state = "done"
        elif sys_status & 0x0004:
            state = "done"
        else:
            state = "idle"

        state_map = {"idle": "空闲", "running": "运行中", "paused": "暂停",
                             "wait_motion": "等待运动", "wait_delay": "等待延时",
                             "wait_di": "等待输入", "done": "完成", "error": f"错误: {"???"}"}
        
        self.status.showMessage(f"PLC: {state_map.get(state, state)} | PC={ipc} | ")
        if self.program is None:
            return
        if state in ("running",) and 0 <= ipc < len(self.program):
            # 优先使用 SourceMap 做精确源码级映射
            src_line = -1
            if hasattr(self, '_source_map') and self._source_map:
                src_line = self._source_map.lookup_line(ipc) or -1
            # 回退到指令内嵌行号
            if src_line <= 0:
                src_line = self.program[ipc].src_line
            if src_line > 0:
                self.editor.set_exec_line(src_line, scroll=False)
            else:
                self.editor.set_exec_line(-1)

        elif state in ("idle", "done", "error"):
            self.editor.set_exec_line(-1)

        # 同步刷新示教面板状态灯
        self._update_teach_panel(sys_status)

    def _on_poll(self):
        pass

    def _on_toolbar_connect(self):
        if self._act_connect.isChecked():
            host, port, unit = "192.168.1.88", 502, 1
            if self.modbus.connect(host, port, unit):
                self.status.showMessage(f"已连接 {host}:{port} 站号{unit}")
                self.log_msg(f"Modbus 连接成功: {host}:{port}")
                self._act_connect.setText("断开 PLC")
                cfg = {"interval": 200, "use_float32": True}
                self.tcp_worker = TcpPositionWorker(self.bridge, self.modbus, cfg)
                self.bridge.position_updated.connect(self._on_position)
                # self.bridge.robot_sys_status_ipc_updated.connect(self._update_ui)
                self.bridge.log_message.connect(self.log_msg)
                self.tcp_worker.start()
            else:
                self._act_connect.setChecked(False)
                QMessageBox.critical(self, "连接失败", f"无法连接到 {host}:{port}")
                self.log_msg("Modbus 连接失败")
        else:
            if self._online_mode:
                self._exit_online_mode()
            self._act_online.setChecked(False)
            self._act_online.setText("在线 🔄")
            if self.tcp_worker:
                self.tcp_worker.stop()
                self.tcp_worker = None
            self.modbus.disconnect()
            self.status.showMessage("未连接 PLC")
            self.log_msg("Modbus 已断开")
            self._act_connect.setText("连接 PLC")

    def _on_position(self, x: float, y: float, z: float):
        self._last_plc_pos = (x, y, z)
        self.lbl_tcp_pos.setText(f"TCP: X={x:.1f} Y={y:.1f} Z={z:.1f}")
        js = f"updatePosition({x:.2f}, {y:.2f}, {z:.2f})"
        self.webview_3d.page().runJavaScript(js)

    # ══════════════════════════════════════════════════════════
    # 示教区 (Jog) 接口 —— 预留 Modbus/PLC 对接点
    # ══════════════════════════════════════════════════════════
    def _on_coord_changed(self, index: int):
        """坐标系切换：更新 Jog 按钮标签"""
        is_joint = (index == 0)
        names = ["J1", "J2", "J3"] if is_joint else ["X", "Y", "Z"]
        for i, n in enumerate(names):
            self.jog_buttons[f"{i}_neg"].setText(f"{n}-")
            self.jog_buttons[f"{i}_label"].setText(n)
            self.jog_buttons[f"{i}_pos"].setText(f"{n}+")
        self.log_msg(f"[示教] 切换到 {'关节' if is_joint else '直角'} 坐标系")

    def _on_jog_pressed(self, axis: int, direction: int):
        """Jog 按钮按下（支持长按连发）"""
        coord = self.cbox_coord.currentText()
        speed = self.cbox_jog_speed.currentText()
        self.log_msg(f"[Jog] 按下 {coord} 轴{axis} 方向{direction:+d} 速度{speed}")
        # TODO: 调用 PLC 点动接口，例如
        # self.modbus.jog_start(axis=axis, direction=direction, speed=speed, coord_type=coord)

    def _on_jog_released(self, axis: int, direction: int):
        """Jog 按钮释放"""
        self.log_msg(f"[Jog] 释放 轴{axis}")
        # TODO: 调用 PLC 停止点动接口
        # self.modbus.jog_stop(axis=axis)

    def _on_teach_home(self):
        """回零按钮"""
        self.log_msg("[示教] 发送回零命令")
        # TODO: self.modbus.go_home()

    def _on_teach_stop(self):
        """急停/停止按钮"""
        self.log_msg("[示教] 发送急停命令")
        # TODO: self.modbus.emergency_stop() 或 self._on_cmd_stop()

    def _on_teach_record(self):
        """记录当前点按钮"""
        self.log_msg("[示教] 记录当前位置（预留接口）")
        # TODO: 读取当前坐标并填入点位表选中项，或弹出新建点位对话框

    def _update_teach_panel(self, sys_status: int):
        """根据 PLC 系统状态更新示教面板状态灯"""
        is_run = bool(sys_status & 0x0001)
        is_err = bool(sys_status & 0x0004)
        is_ready = not is_run and not is_err

        self.lbl_sys_ready.setStyleSheet(
            f"color: {'#0CA678' if is_ready else '#9E9E9E'}; font-size: 12px;")
        self.lbl_sys_run.setStyleSheet(
            f"color: {'#0B7285' if is_run else '#9E9E9E'}; font-size: 12px;")
        self.lbl_sys_err.setStyleSheet(
            f"color: {'#E03131' if is_err else '#9E9E9E'}; font-size: 12px;")

    def _update_teach_position(self, j1: float, j2: float, j3: float):
        """预留接口：外部线程收到坐标后更新示教区位置显示"""
        if self.cbox_coord.currentIndex() == 0:
            self.lbl_teach_pos.setText(
                f"J1: {j1:+.2f}  J2: {j2:+.2f}  J3: {j3:+.2f}")
        else:
            # 直角坐标系显示（需正解转换）
            self.lbl_teach_pos.setText(
                f"X: {j1:+.2f}  Y: {j2:+.2f}  Z: {j3:+.2f}")
    # ══════════════════════════════════════════════════════════

    def _on_online_toggled(self, checked: bool):
        """在线模式开关：点击 -> 进入在线监视并指示运行行；再次点击 -> 退出"""
        if checked:
            self._enter_online_mode()
        else:
            self._exit_online_mode()

    def _enter_online_mode(self):
        """进入在线模式：先做一致性对比，再连接状态信号以指示运行行"""
        if not self.modbus.is_connected():
            QMessageBox.warning(self, "在线模式", "请先连接 PLC")
            self._act_online.setChecked(False)
            return

        # 1) 编译本地程序（同时取回 SourceMap，供运行行精确映射）
        text = self.editor.toPlainText()
        try:
            local_prog, _symbols, src_map = RobotParser.parse_full(text)
            self.program = local_prog   # ★ 关键：_update_ui 依赖 self.program 非 None
            self._source_map = src_map
            # 注入符号表，供编辑器内联显示变量当前值
            self.editor.set_var_symbols([
                {"name": s.name, "index": s.index, "is_const": s.is_const,
                 "const_val": s.const_val, "type_name": s.type_name}
                for s in src_map.symbols])
        except ParseError as e:
            QMessageBox.critical(
                self, "在线模式",
                f"当前程序编译失败，无法进入在线模式。\n\n错误: {e}")
            self._act_online.setChecked(False)
            return
        except Exception as e:
            QMessageBox.critical(self, "在线模式", f"编译异常: {e}")
            self._act_online.setChecked(False)
            return

        if not local_prog:
            QMessageBox.information(self, "在线模式", "当前编辑器为空程序")
            self._act_online.setChecked(False)
            return

        # 2) 与 PLC 在线对比
        self.log_msg(f"[在线] 正在读取 PLC 程序 ({len(local_prog)} 条)...")
        plc_prog = self.modbus.read_program(len(local_prog))
        if plc_prog is None:
            QMessageBox.critical(self, "在线模式", "从 PLC 读取程序失败")
            self._act_online.setChecked(False)
            return
        self._compare_and_report(local_prog, plc_prog)

        # 3) 连接状态信号，开始指示运行行（重复进入时避免重复连接）
        if not self._online_mode:
            self._online_mode = True
            self.bridge.robot_sys_status_ipc_updated.connect(self._update_ui)
        # 启动变量当前值轮询（300ms）
        self._warned_read_vars = False
        if self._var_poll_timer is None:
            self._var_poll_timer = QTimer(self)
            self._var_poll_timer.timeout.connect(self._poll_online_vars)
        self._var_poll_timer.start(300)
        self.editor.setReadOnly(True)   # 在线监视期间锁定代码，退出在线后恢复
        self._act_online.setText("退出在线 🔄")
        self.log_msg("[在线] 已进入在线模式：实时指示运行行；再次点击「在线」退出")

    def _exit_online_mode(self):
        """退出在线模式：断开状态信号、清除运行行高亮"""
        if not self._online_mode:
            return
        self._online_mode = False
        try:
            self.bridge.robot_sys_status_ipc_updated.disconnect(self._update_ui)
        except TypeError:
            pass
        self.editor.set_exec_line(-1)
        if self._var_poll_timer is not None:
            self._var_poll_timer.stop()
        self.editor.set_var_values(None)      # 清除数值框
        self.editor.set_io_values()           # 清除 DI/DO 色块
        self.editor.set_var_symbols([])
        self.editor.setReadOnly(False)        # 恢复可编辑
        self._act_online.setText("在线 🔄")
        # 去掉标题栏的在线状态标记
        base_title = self.windowTitle().split(" | ")[0]
        self.setWindowTitle(base_title)
        self.log_msg("[在线] 已退出在线模式")

    def _poll_online_vars(self):
        """在线模式下周期读取 V 寄存器当前值，刷新编辑器内联数值框。
        依赖 com.py 中 ModbusClient.read_vars(n) -> list[float]（V[0..n-1]）。"""
        if not self._online_mode or not self.modbus.is_connected():
            return
        try:
            values = self.modbus.read_vars(MAX_VAR_INDEX + 1)
           
            
        except AttributeError:
            if not self._warned_read_vars:
                self._warned_read_vars = True
                self.log_msg("[在线] ModbusClient 缺少 read_vars(n) 方法，"
                             "请在 com.py 中补充（读取 V 寄存器区，返回 list）后重新进入在线模式")
            return
        except Exception:
            return
        if values is None:
            return
        if isinstance(values, dict):
            self.editor.set_var_values(values)
        else:
            self.editor.set_var_values({i: v for i, v in enumerate(values)})
       
        # DI/DO 当前值（com.py 需提供 read_dis(n) / read_dos(n) -> list[int]，缺失时静默跳过）
        di = do = None
        for meth, key in (("read_dis", "di"), ("read_dos", "do")):
            if not hasattr(self.modbus, meth):
                if not self._warned_read_vars:
                    self._warned_read_vars = True
                    self.log_msg(f"[在线] ModbusClient 缺少 {meth}(n) 方法，"
                                 f"请在 com.py 中补充（读取 {'DI' if key=='di' else 'DO'} 区）"
                                 f"后重新进入在线模式")
                continue
            try:
                vals = getattr(self.modbus, meth)(MAX_IO_INDEX + 1)
            except Exception:
                continue
            if vals is not None:
                if isinstance(vals, dict):
                    pass
                else:
                    vals = {i: v for i, v in enumerate(vals)}
                if key == "di":
                    di = vals
                else:
                    do = vals
        self.editor.set_io_values(di, do)

    def _compare_and_report(self, local_prog, plc_prog):
        """逐条对比指令序列，并弹出详细报告"""
        diffs = []
        max_show = 8   # 最多显示 8 条差异

        # 长度对比
        if len(local_prog) != len(plc_prog):
            diffs.append(
                f"▸ 长度不一致: 本地 {len(local_prog)} 条, PLC {len(plc_prog)} 条"
            )

        # 逐条对比（取两者最小长度）
        n = min(len(local_prog), len(plc_prog))
        for i in range(n):
            a = local_prog[i]
            b = plc_prog[i]
            # 对比核心字段：op + 所有寄存器参数（忽略 src_line，因为上载后行号会丢失）
            a_regs = a.to_regs()[:8]   # 前 8 个为指令寄存器，第 9 个是 src_line
            b_regs = b.to_regs()[:8]
            if a_regs != b_regs:
                # 反汇编单行文本用于展示
                a_fmt = RobotFormatter._fmt(a, i, len(local_prog))
                b_fmt = RobotFormatter._fmt(b, i, len(plc_prog))
                diffs.append(
                    f"▸ 指令 {i:04d} 不一致\n"
                    f"   本地: {a_fmt}\n"
                    f"   PLC : {b_fmt}"
                )
                if len(diffs) >= max_show:
                    diffs.append("▸ ... （更多差异已省略）")
                    break

        # PLC 比本地长的情况（本地已读完，PLC 还有剩余）
        if len(plc_prog) > len(local_prog):
            remain = len(plc_prog) - len(local_prog)
            diffs.append(f"▸ PLC 比本地多 {remain} 条指令（地址 {len(local_prog)} 起）")

        # 生成报告
        if not diffs:
            QMessageBox.information(
                self, "在线对比 ✅",
                f"程序完全一致！\n\n"
                f"本地与 PLC 均为 {len(local_prog)} 条指令，"
                f"所有操作码与参数完全匹配。"
            )
            self.log_msg("[在线对比] 程序一致")
            self._set_online_status(True)
        else:
            detail = "\n\n".join(diffs)
            msg = (
                f"程序不一致！共发现 {len(diffs)} 处差异。\n\n"
                f"{detail}\n\n"
                f"建议操作：\n"
                f"• 若本地为最新版本，请点击「下载 ▼」同步到 PLC\n"
                f"• 若 PLC 为最新版本，请点击「上载 ▲」覆盖本地"
            )
            QMessageBox.warning(self, "在线对比 ❌", msg)
            self.log_msg(f"[在线对比] 发现 {len(diffs)} 处差异")
            self._set_online_status(False)

    def _set_online_status(self, consistent: bool):
        """仅在标题栏显示在线一致性状态（视觉反馈，不再连接运行行指示；
        运行行指示由「在线 🔄」按钮的在线模式控制）"""
        title = self.windowTitle()
        # 去掉旧标记
        if " | " in title:
            title = title.split(" | ")[0]
        if consistent:
            self.setWindowTitle(title + " | 🟢 在线一致")
        else:
            self.setWindowTitle(title + " | 🔴 在线不一致")


    def _on_help(self):
        QMessageBox.information(self, "指令手册 (ST风格 + PR)",
            "<b>运动指令</b><br>"
            "MOVJ(P[pr],Vxx,Cxx/FINE);<br>"
            "MOVL(P[pr],Vxx,Cxx/FINE);<br>"
            "MOVC(P[end],P[mid],Vxx,Cxx/FINE);<br><br>"
            "<b>运动+DO输出指令</b><br>"
            "MOVJ_DO(P[pr],Vxx,Cxx/FINE,do_delay|V[n],DO[idx],do_val);<br>"
            "MOVL_DO(P[pr],Vxx,Cxx/FINE,do_delay|V[n],DO[idx],do_val);<br>"
            "MOVC_DO(P[end],P[mid],Vxx,Cxx/FINE,do_delay|V[n],DO[idx],do_val);<br>"
            "<i>do_delay: 常量(ms)或V[n]变量; DO[idx]: DO索引; do_val: 输出值(0/1)</i><br><br>"
            "<b>加速度设置</b><br>"
            "SET_ACCE(acc, dec);  <i>设置全局加速度和减速度</i><br><br>"
            "<b>全局倍率</b><br>"
            "SET_OVERALL(50);  <i>设置全局速度倍率 0~100%（常量模式）</i><br>"
            "SET_OVERALL(V[2]);  <i>通过变量动态设置倍率（变量模式）</i><br>"
            "V[n] = GET_OVERALL();  <i>读取当前全局倍率到变量</i><br><br>"
            "<b>位置寄存器 PR</b><br>"
            "PR[n] = CURPOS();  <i>获取当前TCP位置到PR[n]</i><br>"
            "PR[n] = P[m];      <i>将点位P[m]复制到PR[n]</i><br>"
            "PR[n] = PR[a] + PR[b];  <i>向量相加（偏移计算）</i><br>"
            "PR[n] = PR[a] - PR[b];  <i>向量相减</i><br>"
            "PR[n].X = 100;     <i>直接修改PR[n]的X分量</i><br>"
            "P[n] = PR[m];      <i>将PR[m]写回点位表P[n]</i><br>"
            "<i>支持分量: X, Y, Z, J1, J2, J3</i><br><br>"
            "<b>IO/流程控制</b><br>"
            "IF V[n] == value THEN<br>"
            "IF V[n] == value AND V[m] == value2 THEN<br>"
            "IF V[n] == value OR V[m] == value2 THEN<br>"
            "IF NOT V[n] == value THEN<br>"
            "IF 1 THEN  <i>纯常量真条件</i><br>"
            "IF NOT 0 THEN  <i>纯常量假取反</i><br>"
            "ELSIF V[n] == value THEN<br>"
            "ELSE;<br>END_IF;<br><br>"
            "WHILE V[n] == value DO<br>"
            "WHILE V[n] == value AND V[m] == value2 DO<br>"
            "WHILE 1 DO  <i>无限循环</i><br>"
            "WHILE NOT 0 DO  <i>等价 WHILE 1</i><br>"
            "END_WHILE;<br><br>"
            "WAIT_MOTION_DONE;  <i>阻塞等待当前运动指令执行完成</i><br>"
            "DELAY(ms); SET_DO(idx); RESET_DO(idx); WAIT_DI(idx,timeout);<br>"
            "STOPON DI[n];  <i>运动中断条件：当DI[n]为高时中断当前运动</i><br>"
            "V[n] = GET_DI(idx);  <i>读取数字输入到变量</i><br>"
            "V[n] = GET_DO(idx);  <i>读取数字输出到变量</i><br>"
            "V[n] = DISTANCE_TO(P[m]);  <i>计算当前TCP到P[m]的欧氏距离，存入V[n]</i><br>"
            "ISIGNAL_DI(DI[idx],val);  <i>设置DI中断信号，val=1启用/0禁用</i><br>"
            "JUMP addr; STOP;<br>"
            "BREAK; CONTINUE;<br><br>"
            "<b>变量运算</b><br>"
            "V[n] = value;<br>"
            "V[n] = V[a] + V[b];  (支持 + - * /)<br>"
            "V[n] = V[a] + 1;     (支持变量与常数混合)<br><br>"
            "<b>3D 可视化</b><br>"
            "连接 PLC 后自动读取实时 TCP 坐标驱动 3D 末端。<br>"
            "右键点位表可'在 3D 视图中标记'或'点位示教'。<br><br>"
            "<b>FOR 循环</b><br>"
            "FOR V[n] = start TO end [STEP step] DO<br>"
            "    ...<br>"
            "END_FOR;<br><br>"
            "<b>点位示教</b><br>"
            "选中点位后点击'🎯 点位示教'，可将当前 PLC 实时坐标写入该点位。<br><br>"
            "<b>限制</b><br>"
            f"变量: V[0..{MAX_VAR_INDEX}] | 点位: P[0..{MAX_POINT_INDEX}] | PR: PR[0..{MAX_PR_INDEX}]<br>"
            f"程序: 最多 {MAX_PROGRAM_LEN} 条指令"
        )

    def _on_clear_trail(self):
        self.webview_3d.page().runJavaScript("clearTrail()")
        self.log_msg("[3D] 轨迹已清除")

    def _on_clear_spheres(self):
        self.webview_3d.page().runJavaScript("clearSpheres()")
        self.log_msg("[3D] 标记已清除")

    def _check_3d_alive(self):
        """3D 看门狗：页面脚本丢失（渲染进程崩溃）时自动重建场景"""
        if time.time() < self._3d_cooldown_until:
            return
        page = self.webview_3d.page()
        if page is None:
            return
        page.runJavaScript("!!(window.updatePosition && window.addSphere)",
                           self._on_3d_alive_result)

    def _on_3d_alive_result(self, ok):
        if ok:
            self._3d_miss = 0
            return
        self._3d_miss += 1
        if self._3d_miss < 2:          # 连续 2 次探测失败才重建，避免页面加载期误触发
            return
        self._3d_miss = 0
        self._3d_cooldown_until = time.time() + 5
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.webview_3d.setHtml(HTML_3D, QUrl.fromLocalFile(base_dir + os.sep))
        # 重建后恢复点位标记与当前 TCP 位置
        for i in range(32):
            d = self.points[i]
            if any(abs(d[k]) > 1e-9 for k in ("x", "y", "z")):
                self._add_3d_sphere(i)
        x, y, z = self._last_plc_pos
        self.webview_3d.page().runJavaScript(f"updatePosition({x:.2f}, {y:.2f}, {z:.2f})")
        self.log_msg("[3D] 视图丢失（渲染进程崩溃），已自动重建场景")

    def _add_3d_sphere(self, p_idx: int):
        if p_idx not in self.points:
            return
        pt = self.points[p_idx]
        x, y, z = pt.get("x", 0.0), pt.get("y", 0.0), pt.get("z", 0.0)
        px = (x / abs(X_MAX_3D)) * VISUAL_SCALE_X
        py = (y / abs(Y_MAX_3D)) * VISUAL_SCALE_Y
        pz = (z / abs(Z_MAX_3D)) * VISUAL_SCALE_Z
        Y_HEIGHT = 800 + 155
        Y_BEAM_CENTER_Z = (1500 - 100) / 2
        zSlideOffset = 90
        zColumnH = 1000
        wx = px + 30 + zSlideOffset
        wy = Y_HEIGHT + (-pz) + (-zColumnH / 2) + (-92)
        wz = Y_BEAM_CENTER_Z + py
        js = f"addSphere({wx:.2f}, {wy:.2f}, {wz:.2f})"
        self.webview_3d.page().runJavaScript(js, lambda result: None)

   

    def closeEvent(self, event):
        if self.tcp_worker:
            self.tcp_worker.stop()
            self.tcp_worker = None
        self.modbus.disconnect()
        event.accept()

def main() -> int:
    app = QApplication(sys.argv)

    app.setStyle("Fusion")
    palette = app.palette()
    palette.setColor(palette.ColorRole.Window, QColor("#F0F0F0"))
    palette.setColor(palette.ColorRole.WindowText, QColor("#2B2B2B"))
    palette.setColor(palette.ColorRole.Base, QColor("#FFFFFF"))
    palette.setColor(palette.ColorRole.AlternateBase, QColor("#F5F5F5"))
    palette.setColor(palette.ColorRole.ToolTipBase, QColor("#F5F5F5"))
    palette.setColor(palette.ColorRole.ToolTipText, QColor("#2B2B2B"))
    palette.setColor(palette.ColorRole.Text, QColor("#2B2B2B"))
    palette.setColor(palette.ColorRole.Button, QColor("#F5F5F5"))
    palette.setColor(palette.ColorRole.ButtonText, QColor("#2B2B2B"))
    palette.setColor(palette.ColorRole.BrightText, QColor("#FF0000"))
    palette.setColor(palette.ColorRole.Highlight, QColor("#3875D6"))
    palette.setColor(palette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    # app.setApplicationName("Safety Car Config - Design")
    # app.setApplicationDisplayName("组态 · 设计模式")

    window = MainWindow()
    window.show()
    return app.exec()



# if __name__ == "__main__":
#     app = QApplication(sys.argv)
#     app.setStyle("Fusion")
#     palette = app.palette()
#     palette.setColor(palette.ColorRole.Window, QColor("#F0F0F0"))
#     palette.setColor(palette.ColorRole.WindowText, QColor("#2B2B2B"))
#     palette.setColor(palette.ColorRole.Base, QColor("#FFFFFF"))
#     palette.setColor(palette.ColorRole.AlternateBase, QColor("#F5F5F5"))
#     palette.setColor(palette.ColorRole.ToolTipBase, QColor("#F5F5F5"))
#     palette.setColor(palette.ColorRole.ToolTipText, QColor("#2B2B2B"))
#     palette.setColor(palette.ColorRole.Text, QColor("#2B2B2B"))
#     palette.setColor(palette.ColorRole.Button, QColor("#F5F5F5"))
#     palette.setColor(palette.ColorRole.ButtonText, QColor("#2B2B2B"))
#     palette.setColor(palette.ColorRole.BrightText, QColor("#FF0000"))
#     palette.setColor(palette.ColorRole.Highlight, QColor("#3875D6"))
#     palette.setColor(palette.ColorRole.HighlightedText, QColor("#FFFFFF"))
#     app.setPalette(palette)

#     win = MainWindow()
#     win.show()
#     sys.exit(app.exec())