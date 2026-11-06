# -*- coding: utf-8 -*-
"""
complier.py (v3.0 AST 版) 测试套件
- 覆盖：词法/语法/代码生成/校验/反汇编
- 内置指令级虚拟机 VM，对新协议 (IF=条件不成立跳转 + JUMP) 做语义级验证
"""
from complier import (
    OpCode, Instruction, ParseError, RobotParser, RobotFormatter,
    TEMP_VAR_INDEX, MAX_PROGRAM_LEN,
)

# ============================================================================
# 指令级虚拟机（按新协议语义执行，验证编译结果正确性）
# ============================================================================
def vm_run(program, preset=None, max_steps=100000):
    vars_ = [0.0] * 64
    if preset:
        for k, v in preset.items():
            vars_[k] = v
    pc = 0
    steps = 0
    trace = []
    call_stack = []

    def cmp(op, a, b):
        return {0: a > b, 1: a < b, 2: a == b,
                3: a >= b, 4: a <= b, 5: a != b}[op]

    while 0 <= pc < len(program) and steps < max_steps:
        inst = program[pc]
        steps += 1
        op = inst.op
        if op == OpCode.STOP:
            trace.append(('STOP',))
            break
        elif op == OpCode.NOP:
            pc += 1
        elif op == OpCode.ASSIGN:
            vars_[inst.p1] = inst.f1
            pc += 1
        elif op == OpCode.ADD:
            vars_[inst.p1] = vars_[inst.p2] + vars_[inst.p3]
            pc += 1
        elif op == OpCode.SUB:
            vars_[inst.p1] = vars_[inst.p2] - vars_[inst.p3]
            pc += 1
        elif op == OpCode.MUL:
            vars_[inst.p1] = vars_[inst.p2] * vars_[inst.p3]
            pc += 1
        elif op == OpCode.DIV:
            vars_[inst.p1] = vars_[inst.p2] / vars_[inst.p3]
            pc += 1
        elif op == OpCode.IF:
            a = vars_[inst.p1]
            b = vars_[int(inst.f1)] if inst.p3 == 1 else inst.f1
            pc = pc + 1 if cmp(inst.p2, a, b) else inst.jump_addr()
        elif op == OpCode.JUMP:
            pc = inst.jump_addr()
        elif op == OpCode.CALL:
            call_stack.append(pc + 1)
            pc = inst.jump_addr()
        elif op == OpCode.RET:
            pc = call_stack.pop()
        elif op in (OpCode.SET_DO, OpCode.RESET_DO):
            trace.append(('DO', inst.p1, 1 if op == OpCode.SET_DO else 0))
            pc += 1
        elif op in (OpCode.MOVJ, OpCode.MOVL, OpCode.MOVC,
                    OpCode.MOVJ_DO, OpCode.MOVL_DO, OpCode.MOVC_DO):
            trace.append(('MOVE', inst.p1))
            pc += 1
        else:
            # DELAY/WAIT_DI/GET_DI/PR... 测试中视为空操作
            pc += 1
    return vars_, steps, trace


def check(name, cond):
    assert cond, f"FAILED: {name}"
    print(f"  ✓ {name}")


def expect_error(name, text, line_no=None, contains=None):
    try:
        RobotParser.parse(text)
    except ParseError as e:
        if line_no is not None:
            assert e.line_no == line_no, f"{name}: 期望行号 {line_no}，得到 {e.line_no} ({e})"
        if contains is not None:
            assert contains in str(e), f"{name}: 错误信息不含 '{contains}': {e}"
        print(f"  ✓ {name}  →  第{e.line_no}行: {e}")
        return
    raise AssertionError(f"FAILED: {name} 应抛出 ParseError 但没有")


# ============================================================================
# 1. 基础指令编译
# ============================================================================
def test_basic():
    print("== 基础指令 ==")
    prog = RobotParser.parse("""
        // 注释行
        MOVJ(P[0], V50, FINE);   # 行尾注释
        MOVL(P[1], V30, C100);
        MOVC(P[2], P[3], V80, C50);
        DELAY(500);
        SET_DO(0); RESET_DO(1);
        WAIT_DI(2); WAIT_DI(3, 1000);
        SET_ACCE(50, 50);
        SERVO ON;
        SERVO OFF;
        STOPON DI[4];
        SET_OVERALL(80);
        SET_OVERALL(V[5]);
        STOP;
    """)
    ops = [i.op for i in prog]
    assert ops == [OpCode.MOVJ, OpCode.MOVL, OpCode.MOVC, OpCode.DELAY,
                   OpCode.SET_DO, OpCode.RESET_DO, OpCode.WAIT_DI, OpCode.WAIT_DI,
                   OpCode.SET_ACCE, OpCode.SERVO_ON, OpCode.SERVO_OFF,
                   OpCode.STOPON_DI, OpCode.SET_OVERALL, OpCode.SET_OVERALL,
                   OpCode.STOP], ops
    check("基础指令序列", True)
    check("MOVJ 速度/过渡编码", prog[0].p2 == 4 and prog[0].p3 == 10)
    check("MOVC 过渡点 p4", prog[2].p4 == 3)
    check("WAIT_DI 超时", prog[7].f1 == 1000.0)
    check("SET_OVERALL 变量模式", prog[13].p3 == 1 and prog[13].p1 == 5)
    check("src_line 记录", prog[0].src_line == 3 and prog[14].src_line == 15)

    # 5 参数形式（acc/dec → f1/f2）
    prog2 = RobotParser.parse("MOVJ(P[0],V50,FINE,50,80); MOVC(P[1],P[2],V10,C0,10,20);")
    check("MOVJ 5参数 acc/dec", prog2[0].f1 == 50 and prog2[0].f2 == 80)
    check("MOVC 6参数 acc/dec", prog2[1].f1 == 10 and prog2[1].f2 == 20)


# ============================================================================
# 2. 赋值与表达式
# ============================================================================
def test_expr():
    print("== 赋值与表达式 ==")
    prog = RobotParser.parse("""
        V[0] = 1 + 2 * 3;
        V[1] = V[0];
        V[2] = V[0] + V[1];
        V[3] = V[0] + 10;
        V[4] = 100 - V[0];
        V[5] = (V[0] + 1) * (V[1] - 2);
        V[6] = -V[0];
        V[7] = V[0] * -2.5;
        V[8] := 3.14;
    """)
    vars_, _, _ = vm_run(prog)
    check("常量折叠 1+2*3=7", vars_[0] == 7)
    check("V=V 拷贝", vars_[1] == 7)
    check("V+V", vars_[2] == 14)
    check("V+常量", vars_[3] == 17)
    check("常量-V", vars_[4] == 93)
    check("括号表达式 (7+1)*(7-2)=40", vars_[5] == 40)
    check("一元负号", vars_[6] == -7)
    check("V*负常量", vars_[7] == -17.5)
    check(":= 赋值", abs(vars_[8] - 3.14) < 1e-9)

    # 常量折叠确实减少了指令数
    prog_fold = RobotParser.parse("V[0] = 1 + 2 * 3;")
    check("常量折叠为单条 ASSIGN", len(prog_fold) == 1 and prog_fold[0].op == OpCode.ASSIGN
          and prog_fold[0].f1 == 7)

    # 内嵌函数表达式
    prog_fn = RobotParser.parse("V[0] = GET_DI(3); V[1] = GET_DO(2); "
                                "V[2] = DISTANCE_TO(P[5]); V[3] = IS_MOVING(); "
                                "V[4] = GET_OVERALL();")
    check("GET_DI 表达式", prog_fn[0].op == OpCode.GET_DI and prog_fn[0].p1 == 0)
    check("DISTANCE_TO", prog_fn[2].op == OpCode.DISTANCE_TO and prog_fn[2].p2 == 5)
    check("IS_MOVING", prog_fn[3].op == OpCode.IS_MOVING)
    check("GET_OVERALL", prog_fn[4].op == OpCode.GET_OVERALL)


# ============================================================================
# 3. PR 指令
# ============================================================================
def test_pr():
    print("== PR 指令 ==")
    prog = RobotParser.parse("""
        PR[0] = CURPOS();
        PR[1] = P[0];
        PR[2] = PR[0] + PR[1];
        PR[3] = PR[1] - PR[0];
        PR[2].Z = 100;
        PR[2].J1 = 1 + 2;
        PR[4] = PR[2] * 0.5;
        P[2] = PR[2];
    """)
    ops = [i.op for i in prog]
    assert ops == [OpCode.PR_CURPOS, OpCode.PR_ASSIGN_P, OpCode.PR_ADD_VEC,
                   OpCode.PR_SUB_VEC, OpCode.PR_SET_COMP, OpCode.PR_SET_COMP,
                   OpCode.PR_MUL_SCALAR, OpCode.P_ASSIGN_PR], ops
    check("PR 指令序列", True)
    check("PR_SET_COMP 分量Z=2", prog[4].p2 == 2 and prog[4].f1 == 100)
    check("PR 分量常量折叠 J1=3", prog[5].p2 == 3 and prog[5].f1 == 3)
    check("PR_MUL_SCALAR", prog[6].p1 == 4 and prog[6].p2 == 2 and prog[6].f1 == 0.5)
    check("P=PR 反向写入", prog[7].p1 == 2 and prog[7].p2 == 2)


# ============================================================================
# 4. IF / ELSE / ELSIF（VM 语义验证）
# ============================================================================
def test_if():
    print("== IF / ELSE / ELSIF ==")
    src = """
        IF V[10] == 1 THEN
            V[0] = 100;
        ELSE
            V[0] = 200;
        END_IF;
        STOP;
    """
    prog = RobotParser.parse(src)
    v, _, _ = vm_run(prog, preset={10: 1})
    check("IF 真分支", v[0] == 100)
    v, _, _ = vm_run(prog, preset={10: 0})
    check("IF 假分支(ELSE)", v[0] == 200)

    src2 = """
        IF V[10] == 1 THEN
            V[0] = 1;
        ELSIF V[10] == 2 THEN
            V[0] = 2;
        ELSIF V[10] == 3 THEN
            V[0] = 3;
        ELSE
            V[0] = 99;
        END_IF;
        STOP;
    """
    prog2 = RobotParser.parse(src2)
    for x, expect in [(1, 1), (2, 2), (3, 3), (7, 99)]:
        v, _, _ = vm_run(prog2, preset={10: x})
        check(f"ELSIF V[10]={x} → {expect}", v[0] == expect)

    # 无 ELSE 且位于程序末尾：跳转到 len(program) 应允许
    src3 = "IF V[10] == 1 THEN\n V[0] = 5;\nEND_IF;\n"
    prog3 = RobotParser.parse(src3)
    v, _, _ = vm_run(prog3, preset={10: 0})
    check("IF 无ELSE 假分支跳到末尾", v[0] == 0)


# ============================================================================
# 5. 复合条件 AND / OR / NOT / 括号（真值表穷举验证）
# ============================================================================
def test_conditions():
    print("== 复合条件 ==")
    tpl = """
        IF %s THEN
            V[0] = 1;
        ELSE
            V[0] = 0;
        END_IF;
        STOP;
    """
    cases = [
        ("V[10] == 1 AND V[11] == 2",
         lambda a, b, c: a == 1 and b == 2),
        ("V[10] == 1 OR V[11] == 2",
         lambda a, b, c: a == 1 or b == 2),
        ("NOT V[10] == 1",
         lambda a, b, c: not (a == 1)),
        ("(V[10] == 1 OR V[11] == 2) AND NOT V[12] == 3",
         lambda a, b, c: (a == 1 or b == 2) and not (c == 3)),
        ("V[10] > 5 AND (V[11] < 2 OR V[12] != 0)",
         lambda a, b, c: a > 5 and (b < 2 or c != 0)),
        ("V[10] == V[11]",
         lambda a, b, c: a == b),
        ("5 < V[10]",          # 常量在左 → 自动交换比较方向
         lambda a, b, c: 5 < a),
        ("V[10]",              # 真值判断 ⇔ V[10] != 0
         lambda a, b, c: a != 0),
    ]
    for cond_src, fn in cases:
        prog = RobotParser.parse(tpl % cond_src)
        for a in (0, 1, 6):
            for b in (0, 2):
                for c in (0, 3):
                    v, _, _ = vm_run(prog, preset={10: a, 11: b, 12: c})
                    expect = 1 if fn(a, b, c) else 0
                    assert v[0] == expect, (
                        f"条件 '{cond_src}' 在 ({a},{b},{c}) 期望 {expect} 得到 {v[0]}")
        check(f"条件真值表: {cond_src}", True)

    # 纯常量条件
    prog = RobotParser.parse(
        "IF 1 THEN\n V[0]=1;\nEND_IF;\n"
        "IF 0 THEN\n V[1]=1;\nEND_IF;\nSTOP;")
    v, _, _ = vm_run(prog)
    check("IF 1 / IF 0 常量条件", v[0] == 1 and v[1] == 0)


# ============================================================================
# 6. WHILE / FOR / BREAK / CONTINUE（VM 语义验证）
# ============================================================================
def test_loops():
    print("== 循环 ==")
    prog = RobotParser.parse("""
        V[0] = 0;
        WHILE V[0] < 10 DO
            V[0] = V[0] + 1;
        END_WHILE;
        STOP;
    """)
    v, _, _ = vm_run(prog)
    check("WHILE 计数到 10", v[0] == 10)

    # WHILE 1 无限循环 + BREAK
    prog = RobotParser.parse("""
        V[0] = 0;
        WHILE 1 DO
            V[0] = V[0] + 1;
            IF V[0] == 5 THEN
                BREAK;
            END_IF;
        END_WHILE;
        STOP;
    """)
    v, _, _ = vm_run(prog)
    check("WHILE 1 + BREAK", v[0] == 5)

    # FOR 正向
    prog = RobotParser.parse("""
        V[1] = 0;
        FOR V[0] = 0 TO 5 DO
            V[1] = V[1] + 1;
        END_FOR;
        STOP;
    """)
    v, _, _ = vm_run(prog)
    check("FOR 0..5 共 6 次", v[1] == 6 and v[0] == 6)

    # FOR 带 STEP 递减
    prog = RobotParser.parse("""
        V[1] = 0;
        FOR V[0] = 10 TO 0 STEP -2 DO
            V[1] = V[1] + 1;
        END_FOR;
        STOP;
    """)
    v, _, _ = vm_run(prog)
    check("FOR 10→0 STEP -2 共 6 次", v[1] == 6 and v[0] == -2)

    # FOR + CONTINUE（跳过 V[0]==2）
    prog = RobotParser.parse("""
        V[1] = 0;
        FOR V[0] = 0 TO 4 DO
            IF V[0] == 2 THEN
                CONTINUE;
            END_IF;
            V[1] = V[1] + 1;
        END_FOR;
        STOP;
    """)
    v, _, _ = vm_run(prog)
    check("FOR + CONTINUE 跳过一次", v[1] == 4)

    # FOR 的 TO 使用变量
    prog = RobotParser.parse("""
        V[5] = 3;
        V[1] = 0;
        FOR V[0] = 1 TO V[5] DO
            V[1] = V[1] + V[0];
        END_FOR;
        STOP;
    """)
    v, _, _ = vm_run(prog)
    check("FOR TO V[n] 求和 1+2+3=6", v[1] == 6)

    # 嵌套循环 + 内层 BREAK（只跳出内层）
    prog = RobotParser.parse("""
        V[2] = 0;
        FOR V[0] = 0 TO 2 DO
            FOR V[1] = 0 TO 9 DO
                IF V[1] == 3 THEN
                    BREAK;
                END_IF;
                V[2] = V[2] + 1;
            END_FOR;
        END_FOR;
        STOP;
    """)
    v, _, _ = vm_run(prog)
    check("嵌套循环 内层BREAK 3×3=9", v[2] == 9)

    # 空循环体（条件一开始就不成立）
    prog = RobotParser.parse("""
        FOR V[0] = 5 TO 1 DO
            V[1] = 1;
        END_FOR;
        STOP;
    """)
    v, _, _ = vm_run(prog)
    check("FOR 起始>结束 不执行", v[1] == 0)


# ============================================================================
# 7. 运动 + DO 指令
# ============================================================================
def test_mov_do():
    print("== MOVx_DO ==")
    prog = RobotParser.parse("""
        MOVJ_DO(P[0],V50,FINE,100.0,DO[0],1);
        MOVL_DO(P[1],V30,C100,V[7],DO[1],0);
        MOVC_DO(P[2],P[3],V10,C25,50,DO[2],1);
        STOP;
    """)
    check("MOVJ_DO 常量延时", prog[0].f1 == 100.0 and prog[0].f2 == 0
          and prog[0].p5 == 0 and prog[0].p6 == 1)
    check("MOVL_DO 变量延时 (f2=idx+1)", prog[1].f2 == 8 and prog[1].p5 == 1)
    check("MOVC_DO 过渡点", prog[2].p4 == 3 and prog[2].f1 == 50)


# ============================================================================
# 8. 错误处理与行号
# ============================================================================
def test_errors():
    print("== 错误处理 ==")
    expect_error("缺少 END_IF", "MOVJ(P[0],V50,FINE);\nIF V[0] == 1 THEN\nSET_DO(0);",
                 line_no=2, contains="缺少 END_IF")
    expect_error("缺少 END_WHILE", "WHILE V[0] < 1 DO\nSET_DO(0);",
                 line_no=1, contains="缺少 END_WHILE")
    expect_error("缺少 END_FOR", "FOR V[0] = 0 TO 5 DO\nSET_DO(0);",
                 line_no=1, contains="缺少 END_FOR")
    expect_error("变量越界", "V[64] = 1;", line_no=1, contains="越界")
    expect_error("点位越界", "MOVJ(P[32],V50,FINE);", contains="越界")
    expect_error("PR 越界", "PR[16] = CURPOS();", contains="越界")
    expect_error("BREAK 在循环外", "BREAK;", line_no=1, contains="循环内")
    expect_error("CONTINUE 在循环外", "WHILE 1 DO\nEND_WHILE;\nCONTINUE;",
                 line_no=3, contains="循环内")
    expect_error("FOR 步长为 0", "FOR V[0] = 0 TO 5 STEP 0 DO\nEND_FOR;",
                 contains="STEP 不能为 0")
    expect_error("FOR 临时寄存器", "FOR V[62] = 0 TO 5 DO\nEND_FOR;",
                 contains="临时寄存器")
    expect_error("临时寄存器读写混用", "V[62] = V[62] + 1;", contains="临时寄存器")
    expect_error("常量除零", "V[0] = 1 / 0;", contains="除以 0")
    expect_error("未知标识符", "FOO(1);", contains="未声明的变量")
    expect_error("非法字符", "V[0] = 1 @ 2;", contains="非法字符")
    expect_error("JUMP 越界", "JUMP 999;", contains="越界")
    expect_error("END_IF 无匹配", "END_IF;", contains="没有匹配的 IF")
    expect_error("速度值非法", "MOVJ(P[0],V55,FINE);", contains="V10~V100")
    expect_error("语句后垃圾", "SET_DO(0) SET_DO(1);", contains="';' 或换行")
    expect_error("比较误用于赋值", "V[0] == 1;", contains="赋值")
    expect_error("SET_OVERALL 范围", "SET_OVERALL(101);", contains="0~100")
    expect_error("ISIGNAL_DI 参数", "ISIGNAL_DI(DI[0], 2);", contains="0 或 1")
    expect_error("速度值不能作语句", "V50;", contains="不能作为语句开头")


# ============================================================================
# 9. 寄存器编码往返
# ============================================================================
def test_regs_roundtrip():
    print("== 寄存器编码往返 ==")
    prog = RobotParser.parse("""
        MOVJ(P[1],V50,FINE);
        V[0] = -123.456;
        V[1] = V[0] * 2;
        IF V[1] < 0 THEN
            STOP;
        END_IF;
    """)
    for inst in prog:
        regs = inst.to_regs()
        back = Instruction.from_regs(regs, src_line=inst.src_line)
        assert back.op == inst.op and back.p1 == inst.p1 and back.p2 == inst.p2
        assert back.p3 == inst.p3 and back.p4 == inst.p4
        assert back.p5 == inst.p5 and back.p6 == inst.p6
        assert abs(back.f1 - inst.f1) < 1e-3 and abs(back.f2 - inst.f2) < 1e-3
    check("to_regs/from_regs 往返一致（含负数 f1、跳转地址）", True)


# ============================================================================
# 10. 反汇编格式化
# ============================================================================
def test_formatter():
    print("== 反汇编 ==")
    prog = RobotParser.parse("""
        V[0] = 0;
        WHILE V[0] < 3 DO
            V[0] = V[0] + 1;
        END_WHILE;
        STOP;
    """)
    text = RobotFormatter.format(prog)
    assert "L_" in text and "WHILE" not in text.replace("旧协议", "")
    assert "JUMP" in text and "不成立则跳转" in text
    print(text)
    check("反汇编输出包含标签与跳转注释", True)


# ============================================================================
# 11. 示教器 GUI 默认程序（兼容性冒烟测试）
# ============================================================================
def test_gui_default_program():
    print("== GUI 默认程序 ==")
    src = (
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
    prog = RobotParser.parse(src)
    v, _, _ = vm_run(prog)
    check("GUI 默认程序编译+运行", v[0] == 10)
    assert len(prog) <= MAX_PROGRAM_LEN


# ============================================================================
# 12. 边界：16 位跳转地址高字节 / 超长程序 / GUI 模板全覆盖
# ============================================================================
def test_edge_cases():
    print("== 边界场景 ==")
    # 构造 >260 条指令的程序，使跳转地址跨越 p5 高字节 (>=256)
    lines = ["IF V[10] == 1 THEN"]
    lines += ["DELAY(1);"] * 260          # then 分支 260 条
    lines += ["ELSE", "V[0] = 42;", "END_IF;", "STOP;"]
    prog = RobotParser.parse("\n".join(lines))
    if_inst = prog[0]
    check("IF 跳转地址 >255 (p5 高字节非零)", if_inst.jump_addr() > 255 and if_inst.p5 > 0)
    v, _, _ = vm_run(prog, preset={10: 0})
    check("跨页跳转执行正确", v[0] == 42)
    v, steps, _ = vm_run(prog, preset={10: 1})
    check("跨页跳转-真分支走完 then", steps > 260)

    # 超长程序
    big = "\n".join(["DELAY(1);"] * 501)
    expect_error("程序超长", big, contains="程序过长")

    # SERVO_ON 下划线形式 / WHILE NOT 0 / 行尾分号可选
    prog = RobotParser.parse("SERVO_ON;\nV[0]=0\nWHILE NOT 0 DO\nV[0]=V[0]+1\n"
                             "IF V[0]==3 THEN\nBREAK\nEND_IF\nEND_WHILE\nSERVO_OFF\nSTOP")
    v, _, _ = vm_run(prog)
    check("SERVO_ON / 无分号 / WHILE NOT 0 / BREAK 无分号", v[0] == 3)

    # ELSIF 空分支
    prog = RobotParser.parse("IF V[10]==1 THEN\nELSIF V[10]==2 THEN\nV[0]=2;\nEND_IF;\nSTOP;")
    v, _, _ = vm_run(prog, preset={10: 1})
    check("ELSIF 空分支-真", v[0] == 0)
    v, _, _ = vm_run(prog, preset={10: 2})
    check("ELSIF 空分支-命中第二支", v[0] == 2)

    # GUI 快捷模板全覆盖
    templates = {
        "MOVJ": "MOVJ(P[0],V50,FINE,50,50);\n",
        "MOVL": "MOVL(P[0],V50,FINE,50,50);\n",
        "MOVC": "MOVC(P[0],P[1],V50,FINE,50,50);\n",
        "STOPON": "STOPON DI[0];\n",
        "IF": "IF V[0] == 1 THEN\n    SET_DO(0);\nELSE\n    RESET_DO(0);\nEND_IF;\n",
        "WHILE": "V[0] = 0;\nWHILE V[0] < 10 DO\n    V[0] = V[0] + 1;\n    DELAY(100);\nEND_WHILE;\n",
        "FOR": "FOR V[0] = 0 TO 5 DO\n    SET_DO(0);\n    DELAY(200);\n    RESET_DO(0);\n    DELAY(200);\nEND_FOR;\n",
        "PR": "PR[0] = CURPOS();\nPR[1] = P[0];\nPR[2] = PR[0] + PR[1];\nPR[2].Z = 100;\nPR[3] = PR[2] * 0.5;\n",
        "IS_MOVING": "V[0] = IS_MOVING();\nIF V[0] == 1 THEN\n    DELAY(100);\nEND_IF;\n",
        "WAIT": "WAIT_DI(0,5000);\nIF V[0] == 1 THEN\n    SET_DO(1);\nEND_IF;\n",
        "DELAY": "DELAY(500);\n",
        "SET_DO": "SET_DO(0);\n",
        "GET_DI": "GET_DI(0);\n",
        "RESET_DO": "RESET_DO(0);\n",
        "STOP": "STOP;\n",
        "SERVO ON": "SERVO ON;\n",
        "SERVO OFF": "SERVO OFF;\n",
        "简单搬运": "SET_ACCE(50,50);\nMOVJ(P[0],V50,FINE);\nMOVL(P[1],V30,C100);\nSET_DO(0);\nDELAY(500);\nRESET_DO(0);\nMOVL(P[0],V30,C100);\nSTOP;\n",
        "AND 复合条件": "IF V[1] == 1 AND V[2] == 2 THEN\n    MOVL(P[3],V30,FINE);\nEND_IF;\n",
        "OR 复合条件": "IF V[1] == 1 OR V[2] == 2 THEN\n    SET_DO(3);\nEND_IF;\n",
        "ELSIF 多分支": "IF V[0] == 1 THEN\n    SET_DO(0);\nELSIF V[0] == 2 THEN\n    SET_DO(1);\nELSE\n    RESET_DO(0);\nEND_IF;\n",
        "GET_DI 读取输入": "V[0] = GET_DI(0);\nIF V[0] == 1 THEN\n    SET_DO(0);\nEND_IF;\n",
        "NOT 条件": "IF NOT V[0] == 1 THEN\n    SET_DO(0);\nEND_IF;\n",
        "FOR 递减": "FOR V[0] = 10 TO 0 STEP -2 DO\n    V[1] = V[0] * 2;\n    DELAY(100);\nEND_FOR;\n",
        "BREAK 中断循环": "V[0] = 0;\nWHILE V[0] < 10 DO\n    V[0] = V[0] + 1;\n    IF V[0] == 5 THEN\n        BREAK;\n    END_IF;\n    DELAY(100);\nEND_WHILE;\n",
        "CONTINUE 跳过迭代": "FOR V[0] = 0 TO 5 DO\n    IF V[0] == 2 THEN\n        CONTINUE;\n    END_IF;\n    SET_DO(0);\n    DELAY(200);\n    RESET_DO(0);\nEND_FOR;\n",
        "PR 获取当前位置": "PR[0] = CURPOS();\nPR[1] = P[0];\nPR[2] = PR[0] + PR[1];\nPR[2].Z = 100;\n",
        "PR 标量乘法": "PR[0] = P[0];\nPR[1] = PR[0] * 0.5;\n",
        "IS_MOVING 状态检测": "V[0] = IS_MOVING();\nIF V[0] == 1 THEN\n    DELAY(50);\nEND_IF;\n",
        "PR 偏移计算": "PR[0] = P[0];\nPR[1] = P[1];\nPR[2] = PR[1] - PR[0];\nP[2] = PR[2];\n",
        "MOVJ_DO 运动+DO": "SET_ACCE(50,50);\nMOVJ_DO(P[0],V50,FINE,100.0,DO[0],1);\nDELAY(200);\nRESET_DO(0);\n",
        "MOVL_DO 运动+DO": "SET_ACCE(80,80);\nMOVL_DO(P[1],V30,C100,50.0,DO[1],1);\nDELAY(200);\nRESET_DO(1);\n",
    }
    for name, src in templates.items():
        prog = RobotParser.parse(src)   # 不抛异常即通过
        assert len(prog) > 0
    check(f"GUI 全部 {len(templates)} 个模板编译通过", True)


# ============================================================================
# 13. 变量声明（v3.1：VAR / CONST / 符号表）
# ============================================================================
def test_var_decl():
    from complier import VarSymbol
    print("== 变量声明（VAR/CONST） ==")

    # --- 基本声明与符号表 ---
    prog, syms = RobotParser.parse_full("""
        VAR count : INT = 0;
        CONST MAX_RETRY = 3;
        VAR ratio : REAL = 0.5;
        VAR done : BOOL = FALSE;
        count = count + MAX_RETRY;
        done = TRUE;
    """)
    smap = {s.name: s for s in syms}
    check("符号表大小写归一", set(smap) == {"COUNT", "MAX_RETRY", "RATIO", "DONE"})
    check("变量从 V[0] 向上分配",
          smap["COUNT"].index == 0 and smap["RATIO"].index == 1 and smap["DONE"].index == 2)
    check("CONST 不占寄存器", smap["MAX_RETRY"].is_const and smap["MAX_RETRY"].index == -1)
    v, _, _ = vm_run(prog)
    check("VAR 初值 + CONST 折叠", v[0] == 3.0 and v[1] == 0.5 and v[2] == 1.0)
    check("初值为 0 不产生指令",
          not any(i.op == OpCode.ASSIGN and i.p1 == 0 and i.f1 == 0.0 for i in prog))

    # --- 大小写不敏感 ---
    prog = RobotParser.parse("VAR cnt = 1;\nCNT = Cnt + 1;")
    v, _, _ = vm_run(prog)
    check("名字大小写不敏感", v[0] == 2.0)

    # --- 名字用于表达式/条件/循环 ---
    prog = RobotParser.parse("""
        VAR i : INT = 0;
        VAR total = 0;
        CONST N = 5;
        FOR i = 1 TO N DO
            total = total + i;
        END_FOR
        WHILE total > 10 DO
            total = total - 3;
        END_WHILE
        IF total == 5 AND NOT total == 0 THEN
            total = total * 2;
        END_IF
    """)
    v, _, _ = vm_run(prog)
    check("名字贯穿 FOR/WHILE/IF", v[0] == 6 and v[1] == 9.0)

    # --- VAR 初值引用先声明的名字 ---
    prog = RobotParser.parse("""
        VAR a = 2;
        VAR b = a * 10 + 1;
    """)
    v, _, _ = vm_run(prog)
    check("初值引用先声明变量", v[1] == 21.0)

    # --- CONST 引用 CONST ---
    prog = RobotParser.parse("""
        CONST BASE = 4;
        CONST DOUBLE_BASE = BASE * 2;
        V[0] = DOUBLE_BASE;
    """)
    v, _, _ = vm_run(prog)
    check("CONST 引用 CONST", v[0] == 8.0)

    # --- 名字用于 SET_OVERALL / MOVJ_DO 变量延时 ---
    prog = RobotParser.parse("""
        VAR ovr = 80;
        VAR dly = 100;
        SET_OVERALL(ovr);
        MOVJ_DO(P[0], V50, FINE, dly, DO[1], 1);
    """)
    so = [i for i in prog if i.op == OpCode.SET_OVERALL][0]
    check("SET_OVERALL(变量名)", so.p3 == 1 and so.p1 == 0)
    md = [i for i in prog if i.op == OpCode.MOVJ_DO][0]
    check("MOVJ_DO 延时变量名", int(md.f2) - 1 == 1)

    # --- 符号表随反汇编输出 ---
    prog, syms = RobotParser.parse_full("VAR count : INT = 0;\ncount = count + 1;")
    listing = RobotFormatter.format(prog, syms)
    check("反汇编带符号表", "COUNT" in listing and "V[0]" in listing)

    # --- 错误处理 ---
    expect_error("未声明变量", "foo = 1;", contains="未声明的变量")
    expect_error("常量赋值", "CONST K = 1;\nK = 2;", line_no=2, contains="常量")
    expect_error("重复声明", "VAR a = 1;\nVAR a = 2;", line_no=2, contains="重复声明")
    expect_error("声明不在开头", "V[0] = 1;\nVAR a = 2;", line_no=2, contains="程序开头")
    expect_error("CONST 无初值", "CONST K;", contains="必须初始化")
    expect_error("CONST 引用变量", "VAR a = 1;\nCONST K = a + 1;", contains="常量表达式")
    expect_error("BOOL 初值非法", "VAR b : BOOL = 5;", contains="BOOL")
    expect_error("INT 初值非法", "VAR i : INT = 1.5;", contains="整数")
    expect_error("未知类型", "VAR i : STR = 1;", contains="INT / REAL / BOOL")
    expect_error("变量过多",
                 "\n".join(f"VAR x{i} = 0;" for i in range(61)),
                 contains="最多")

    # --- 与 V[n] 混用：声明变量和直接寄存器可并存 ---
    prog = RobotParser.parse("""
        VAR a = 7;
        V[10] = a;
        a = V[10] + V[11];
    """)
    v, _, _ = vm_run(prog)
    check("名字与 V[n] 混用", v[10] == 7.0 and v[0] == 7.0)

    # --- V 后非速度数字可作变量名（V5 不再是词法错误） ---
    prog = RobotParser.parse("VAR v5 = 3;\nV[0] = v5;")
    v, _, _ = vm_run(prog)
    check("V5 可作变量名", v[0] == 3.0)

    # --- CONST 名字可用于所有整数位置（符号化地址） ---
    prog = RobotParser.parse("""
        VAR req : BOOL = FALSE;
        CONST DI_PICK_REQ = 1;
        CONST DO_CLAMP = 3;
        req = GET_DI(DI_PICK_REQ);
        SET_DO(DO_CLAMP);
        WAIT_DI(DI_PICK_REQ);
        ISIGNAL_DI(DI_PICK_REQ, 1);
        V[0] = GET_DO(DO_CLAMP);
    """)
    g = [i for i in prog if i.op == OpCode.GET_DI][0]
    check("GET_DI(CONST名)", g.p1 == 0 and g.p2 == 1)
    sd = [i for i in prog if i.op == OpCode.SET_DO][0]
    check("SET_DO(CONST名)", sd.p1 == 3)
    gd = [i for i in prog if i.op == OpCode.GET_DO][0]
    check("GET_DO(CONST名)", gd.p1 == 0 and gd.p2 == 3)

    # --- VAR 变量名不能用作索引（无运行期间接寻址） ---
    expect_error("VAR 不能作索引", "VAR idx = 1;\nSET_DO(idx);", contains="间接寻址")
    expect_error("非整 CONST 不能作索引", "CONST K = 1.5;\nSET_DO(K);", contains="整数")


def test_map():
    print("\n== MAP 寄存器别名 (v3.3) ==")

    # --- 基本：MOVJ_DO 的 do_delay 用别名，等价于 V[40] ---
    src = ("MAP 延时参数 TO V[40];\n"
           "MOVJ_DO(P[1],V80,C0,延时参数,DO[2],1);\n")
    prog, syms = RobotParser.parse_full(src)
    md = prog[0]
    check("MAP 不生成指令", len(prog) == 1 and md.op == OpCode.MOVJ_DO)
    check("do_delay 变量模式指向 V[40]", md.f2 > 0 and int(md.f2) - 1 == 40)
    s = [x for x in syms if x.name == "延时参数"][0]
    check("符号表 is_map 标记", s.is_map and s.index == 40 and not s.is_const)

    # --- 别名读写 / 条件 / 表达式 ---
    src = ("MAP 延时参数 TO V[41];\n"
           "延时参数 = 500;\n"
           "IF 延时参数 > 100 THEN\n V[0] = 延时参数 / 2;\n ENDIF\n")
    prog, _ = RobotParser.parse_full(src)
    v, _, _ = vm_run(prog)
    check("别名写入 V[41]", v[41] == 500)
    check("别名参与条件与表达式", v[0] == 250)

    # --- VAR 自动分配跳过专用区 V[40]~V[49] ---
    src = "\n".join(f"VAR a{i};" for i in range(41))
    _, syms = RobotParser.parse_full(src)
    idxs = [s.index for s in syms]
    check("VAR 分配跳过 V[40]~V[49]",
          all(not (40 <= i <= 49) for i in idxs) and 50 in idxs and len(idxs) == 41)

    # --- 专用区外仍可直接用 V[n]，只是不能起别名 ---
    v, _, _ = vm_run(RobotParser.parse_full("V[45] = 3;")[0])
    check("直接写 V[45] 不受影响", v[45] == 3)

    # --- 反汇编符号表打印 MAP ---
    text = RobotFormatter.format(*RobotParser.parse_full("MAP m TO V[42];\nV[0]=1;"))
    check("反汇编符号表含 MAP 行", "MAP   M -> V[42]" in text)

    # --- 错误场景 ---
    expect_error("MAP 越出专用区", "MAP a TO V[0];", contains="专用区")
    expect_error("MAP V[50] 也不在专用区", "MAP a TO V[50];", contains="专用区")
    expect_error("重复映射同一寄存器", "MAP a TO V[40];\nMAP b TO V[40];",
                 contains="只能有一个别名")
    expect_error("MAP 名字与 VAR 冲突", "VAR a;\nMAP a TO V[40];", contains="重复声明")
    expect_error("MAP 名不能作索引", "MAP a TO V[40];\nSET_DO(a);", contains="间接寻址")
    expect_error("MAP 必须在程序开头", "MOVJ(P[1],V50,FINE);\nMAP a TO V[40];",
                 contains="只能放在程序开头")
    expect_error("MAP 缺少 TO", "MAP a V[40];", contains="TO")
    expect_error("MAP 目标必须是 V[n]", "MAP a TO P[40];", contains="V[n]")


def test_subroutine():
    print("\n== 子程序 CALL/RET (v3.2) ==")

    # --- 基本调用：主程序两次调用，执行流不跌入子程序区 ---
    src = ("VAR cnt : INT = 0;\n"
           "CALL 取箱;\n"
           "CALL 取箱;\n"
           "SUB 取箱:\n"
           "    cnt = cnt + 1;\n"
           "END_SUB\n")
    prog, syms = RobotParser.parse_full(src)
    calls = [i for i in prog if i.op == OpCode.CALL]
    check("生成两条 CALL", len(calls) == 2)
    check("两条 CALL 指向同一入口", calls[0].jump_addr() == calls[1].jump_addr())
    entry = calls[0].jump_addr()
    check("入口在 STOP/JUMP 之后", entry >= 3)
    check("CALL 之前有防跌入 JUMP",
          any(i.op == OpCode.JUMP and i.jump_addr() == len(prog) for i in prog[:entry]))
    check("子程序末尾自动补 RET", prog[-1].op == OpCode.RET)
    v, steps, _ = vm_run(prog)
    check("两次调用 cnt == 2", v[0] == 2)

    # --- 子程序内调用子程序（两级） ---
    src = ("CALL A;\n"
           "SUB A:\n CALL B;\n V[1] = V[1] + 1;\nEND_SUB\n"
           "SUB B:\n V[1] = V[1] + 10;\nEND_SUB\n")
    prog, _ = RobotParser.parse_full(src)
    v, _, _ = vm_run(prog)
    check("两级调用 V[1] == 11", v[1] == 11)

    # --- 显式 RET：提前返回 ---
    src = ("CALL S;\n V[0] = 99;\n"
           "SUB S:\n V[0] = 1;\n RET;\n V[0] = 2;\nEND_SUB\n")
    prog, _ = RobotParser.parse_full(src)
    v, _, _ = vm_run(prog)
    check("RET 提前返回（V[0]==99，而非 2→99 中的异常）", v[0] == 99)
    rets = [i for i in prog if i.op == OpCode.RET]
    check("显式 RET + 兜底 RET", len(rets) == 2)

    # --- 子程序内可用控制流与变量 ---
    src = ("VAR total = 0;\nVAR i;\n"
           "CALL Sum5;\n"
           "SUB Sum5:\n"
           "  FOR i = 1 TO 5 DO\n total = total + i;\n ENDFOR\n"
           "  IF total == 15 THEN\n total = total + 100;\n ENDIF\n"
           "END_SUB\n")
    prog, _ = RobotParser.parse_full(src)
    v, _, _ = vm_run(prog)
    check("子程序内 FOR+IF: total == 115", v[0] == 115)

    # --- 参数约定区 V[50]~V[59] ---
    src = ("V[50] = 7;\nCALL Double;\n"
           "SUB Double:\n V[0] = V[50] * 2;\nEND_SUB\n")
    prog, _ = RobotParser.parse_full(src)
    v, _, _ = vm_run(prog)
    check("参数经 V[50] 传递: V[0] == 14", v[0] == 14)

    # --- 中文子程序名 & CALL name() 空括号兼容 ---
    src = "CALL 复位流程();\nSUB 复位流程:\n V[2] = 5;\nEND_SUB\n"
    prog, _ = RobotParser.parse_full(src)
    v, _, _ = vm_run(prog)
    check("中文名 + 空括号调用", v[2] == 5)

    # --- CALL 目标校验（指令级兜底） ---
    bad = [Instruction(OpCode.CALL)]
    bad[0].set_jump_addr(5)
    try:
        RobotParser._validate(bad)
        check("CALL 目标越界应报错", False)
    except ParseError:
        check("CALL 目标越界应报错", True)

    # --- 错误场景 ---
    expect_error("调用未定义子程序", "CALL FOO;", contains="未定义的子程序")
    expect_error("自递归", "SUB A:\n CALL A;\nEND_SUB", contains="循环调用")
    expect_error("两子程序互调", "SUB A:\n CALL B;\nEND_SUB\nSUB B:\n CALL A;\nEND_SUB",
                 contains="循环调用")
    expect_error("主程序中 RET", "RET;", contains="只能在子程序")
    expect_error("重复定义", "SUB A:\nEND_SUB\nSUB A:\nEND_SUB", contains="重复定义")
    expect_error("子程序名与变量重名", "VAR A = 1;\nSUB A:\nEND_SUB", contains="重名")
    expect_error("嵌套定义", "SUB A:\n SUB B:\n END_SUB\nEND_SUB", contains="不能嵌套")
    expect_error("缺少 END_SUB", "SUB A:\n V[0]=1;", contains="缺少 END_SUB")
    expect_error("子程序区后不能有语句", "SUB A:\nEND_SUB\nMOVJ P[1],V50,FINE;",
                 contains="不允许再出现语句")
    expect_error("END_SUB 无匹配", "END_SUB", contains="没有匹配")

    # --- 反汇编输出 ---
    text = RobotFormatter.format(*RobotParser.parse_full(
        "CALL S;\nSUB S:\n V[0]=1;\nEND_SUB\n"))
    check("反汇编含 CALL L_", "CALL L_" in text)
    check("反汇编含 RET;", "RET;" in text)


def test_sub_params():
    print("\n== 带参子程序 (v3.4) ==")

    # --- 基本：实参求值写入第一层带 V[50]/V[51]，形参可参与表达式 ---
    src = ("VAR cnt = 0;\n"
           "CALL 取箱(3, cnt + 1);\n"
           "SUB 取箱(库位, 数量):\n"
           "    cnt = 库位 * 数量;\n"
           "END_SUB\n")
    prog, _ = RobotParser.parse_full(src)
    a0, a1 = prog[0], prog[1]
    check("实参1 → V[50]", a0.op == OpCode.ASSIGN and a0.p1 == 50 and a0.f1 == 3)
    check("CALL 在实参赋值之后", prog[3].op == OpCode.CALL)
    v, _, _ = vm_run(prog)
    check("形参参与表达式: cnt == 3", v[0] == 3)

    # --- 值传递：改形参不影响调用方 ---
    src = ("VAR q = 7;\n"
           "CALL S(q);\n"
           "SUB S(n):\n n = 99;\nEND_SUB\n")
    v, _, _ = vm_run(RobotParser.parse_full(src)[0])
    check("值传递: q 仍为 7", v[0] == 7)

    # --- 两层嵌套分带：A 的参数在 V[50]，B 的在 V[55]，互不覆盖 ---
    src = ("CALL A(1);\n"
           "SUB A(n1):\n"
           "    CALL B(n1 + 10);\n"
           "    V[0] = n1;\n"
           "END_SUB\n"
           "SUB B(n2):\n"
           "    V[1] = n2 * 2;\n"
           "END_SUB\n")
    prog, _ = RobotParser.parse_full(src)
    v, _, _ = vm_run(prog)
    check("内层调用不冲外层参数: V[0]==1", v[0] == 1)
    check("第二层带 V[55]: V[1]==22", v[1] == 22)

    # --- 主程序直调带参子程序（深度 1） ---
    v, _, _ = vm_run(RobotParser.parse_full(
        "CALL B(5);\nSUB B(kk):\n V[1] = kk;\nEND_SUB")[0])
    check("主程序直调: V[1]==5", v[1] == 5)

    # --- 实参可以是常量/变量/表达式/函数混合 ---
    src = ("VAR a = 2;\n"
           "CALL S(a * 3, GET_DI(1));\n"
           "SUB S(p1, p2):\n V[2] = p1 + p2;\nEND_SUB\n")
    prog, _ = RobotParser.parse_full(src)
    check("表达式实参编译通过", prog[3].op == OpCode.GET_DI and prog[4].op == OpCode.CALL)

    # --- 形参可作 MOVJ_DO 的 do_delay（变量模式） ---
    src = ("CALL M(40);\n"
           "SUB M(dly):\n MOVJ_DO(P[1],V80,C0,dly,DO[2],1);\nEND_SUB\n")
    prog, _ = RobotParser.parse_full(src)
    md = [i for i in prog if i.op == OpCode.MOVJ_DO][0]
    check("形参作 do_delay → 指向参数带", md.f2 > 0 and int(md.f2) - 1 == 50)

    # --- 形参在 IF/WHILE/FOR 中使用 ---
    src = ("CALL W(3);\n"
           "SUB W(n):\n"
           "  WHILE n > 0 DO\n V[5] = V[5] + n;\n n = n - 1;\n END_WHILE\n"
           "END_SUB\n")
    v, _, _ = vm_run(RobotParser.parse_full(src)[0])
    check("形参作循环条件: 3+2+1==6", v[5] == 6)

    # --- 不带参子程序不受层数限制 ---
    RobotParser.parse_full(
        "CALL A;\nSUB A:\n CALL B;\nEND_SUB\nSUB B:\n CALL C;\nEND_SUB\n"
        "SUB C:\n V[9]=7;\nEND_SUB")
    check("不带参三层嵌套合法", True)

    # --- 中文形参名 ---
    v, _, _ = vm_run(RobotParser.parse_full(
        "CALL S(8);\nSUB S(数量):\n V[3] = 数量 * 2;\nEND_SUB")[0])
    check("中文形参: V[3]==16", v[3] == 16)

    # --- 错误场景 ---
    expect_error("实参个数不符", "CALL A(1,2);\nSUB A(n):\nEND_SUB",
                 contains="需要 1 个参数")
    expect_error("少给实参", "CALL A;\nSUB A(n):\nEND_SUB", contains="需要 1 个参数")
    expect_error("超过5个形参", "SUB A(a,b,c,d,e,f):\nEND_SUB", contains="最多 5 个")
    expect_error("形参与全局变量重名", "VAR n;\nSUB A(n):\nEND_SUB", contains="重名")
    expect_error("形参重复", "SUB A(n, n):\nEND_SUB", contains="重复")
    expect_error("带参三层嵌套",
                 "CALL A(1);\nSUB A(a1):\n CALL B(a1);\nEND_SUB\n"
                 "SUB B(b1):\n CALL C(b1);\nEND_SUB\nSUB C(c1):\nEND_SUB",
                 contains="只分 2 层")
    expect_error("形参在体外不可见", "CALL A(1);\nV[0] = n;\nSUB A(n):\nEND_SUB",
                 contains="未声明的变量")
    expect_error("形参不能作索引", "CALL A(1);\nSUB A(n):\n SET_DO(n);\nEND_SUB",
                 contains="间接寻址")


if __name__ == "__main__":
    test_basic()
    test_expr()
    test_pr()
    test_if()
    test_conditions()
    test_loops()
    test_mov_do()
    test_errors()
    test_regs_roundtrip()
    test_formatter()
    test_gui_default_program()
    test_edge_cases()
    test_var_decl()
    test_subroutine()
    test_sub_params()
    test_map()
    print("\n全部测试通过 ✔")
