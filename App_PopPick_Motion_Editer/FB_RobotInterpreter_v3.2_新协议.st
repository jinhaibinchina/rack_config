// ============================================================================
//  FB_RobotInterpreter  ——  适配 v3.2 AST 编译器（新协议 + 子程序）  2026-09
// ----------------------------------------------------------------------------
//  协议变更：
//   1) IF(30) 改为"条件跳转"：条件为 FALSE → iPC := p5*256 + p6（16 位绝对地址），
//      为 TRUE → 顺序执行。不再压栈/扫描匹配 ELSE、ENDIF。
//   2) JUMP(50) 跳转地址由 p1 改为 p5*256 + p6（16 位绝对地址）。
//   3) ELSE/ENDIF/WHILE/ENDWHILE/FOR/ENDFOR/BREAK/CONTINUE 已在编译期展开为
//      IF + JUMP，PLC 上不再出现；若收到则报 'Obsolete OpCode, Recompile'。
//   4) 跳转目标允许 = iPC_Max（即程序末尾，视为程序结束）。
//   5) v3.2 新增子程序指令：
//        CALL(72)：压入返回地址(iPC+1)后跳转 p5*256+p6（目标必须 < iPC_Max）；
//        RET(73) ：弹出返回地址并跳回。
//      调用栈深度 16，溢出报 'Call Stack Overflow'，空栈 RET 报 'RET Without CALL'。
//      编译器已禁止递归/循环调用，此处仅做运行期兜底。
//
//  ★ 配套修改（必须在 CODESYS 工程里手动完成）：
//   a) 枚举 E_OP_CODE 增加两个成员：  _CALL := 72;  _RET := 73;
//   b) 本 FB 的 VAR 区增加两个变量：
//        CallStack : ARRAY[0..15] OF INT;   // 子程序返回地址栈
//        iCSP      : INT;                   // 调用栈指针（= 当前嵌套深度）
//
//  其余指令（运动/DO/DELAY/IO/运算/PR/SERVO 等）处理保持不变。
//  ParseCmdSeq 方法无需修改（已按 reg3 解析 p5/p6 高/低字节，与新编译器一致）。
//  可删除（可选）的本地变量：Stack、iSP、ForStack、ForVar、ForEnd、ForCmp、
//  iForSP、k、l、m、n、o、p；不删也可正常编译（仅有未使用警告）。
// ============================================================================
// ============================================================================
//  启动 / 停止 / 暂停 / 下载 控制
// ============================================================================
rExecute(CLK := xExecute);
fExecute(CLK := xExecute);
//rLoad(CLK := xLoad);

// // ---- 程序下载（单条写入） ----
// IF rLoad.Q THEN
//     IF iLoadAddr >= 0 AND iLoadAddr < 500 THEN
//         j := iLoadAddr * 8;
//         FOR i := 0 TO CMD_SEQ_LENGTH DO
//             ProgramMem[j + i] := aiLoadData[i];
//         END_FOR;
//         IF iLoadAddr >= iPC_Max THEN
//             iPC_Max := iLoadAddr + 1;
//         END_IF;
//     END_IF;
// END_IF;

// // ---- 停止 ----
// IF fExecute.Q  THEN
//     eState     := ST_IDLE;
//     iPrevState := 0;
//     xBusy      := FALSE;
//     xDone      := FALSE;
//     xError     := FALSE;
//    
//     tmrDelay(IN:=FALSE);
//     tmrWait(IN:=FALSE);
//     iForSP := 0;
// 	
// 	iPC    := 0;
// 	STOP_ROBOT();
// 	RESET_QUEUE();
// END_IF;
delay(IN := IDLE_QUEUE_EMPTY() AND eState = ST_WAIT_MOTION , PT := T#1S, Q => , ET => );
IF delay.Q THEN
	eState := 0;
END_IF
// ---- 启动（仅在 Idle 状态响应） ----
IF rExecute.Q AND eState = 0 THEN
    IF iPC_Max > 0 THEN
        eState := ST_RUN;        // Running
        xBusy  := TRUE;
        xDone  := FALSE;
        xError := FALSE;
		xAskPowerOn:=FALSE;
		xAskPowerOff:=FALSE;
        iPC    := 0;
		xMotionDone:=FALSE;
		sErrorMsg := '';
		iCSP   := 0;             // v3.2：清空子程序调用栈

		FOR i:=0 TO 63 DO
			V[i]:= 0.0;
		END_FOR
		RESUME_ROBOT();
    ELSE
        xError    := TRUE;
        sErrorMsg := 'No Program';
    END_IF;
END_IF;

// ---- Halt 处理 ----
IF xHalt AND (eState = ST_RUN OR eState = ST_WAIT_MOTION OR eState = ST_WAIT_DELAY OR eState = ST_WAIT_DI)  THEN
    iPrevState := eState;
    eState     := ST_HALT;        // Halted
	STOP_ROBOT();
END_IF;

IF NOT xHalt AND eState = ST_HALT THEN
    eState := iPrevState;   // 恢复之前状态
	RESUME_ROBOT();
END_IF;

// Halted 时冻结一切
IF eState = ST_HALT THEN
	IF xReset THEN
		eState     := ST_IDLE;
		iPrevState := 0;
		xBusy      := FALSE;
		xDone      := FALSE;
		xError     := FALSE;
	   
		tmrDelay(IN:=FALSE);
		tmrWait(IN:=FALSE);
		
		iPC    := 0;
		iCSP   := 0;             // v3.2：清空子程序调用栈
		STOP_ROBOT();
		RESET_QUEUE();
		iPCtoDisplay :=0;
		CurrCmdSeq := ParseCmdSeq( E_CMD_LOCATION.CURR);
		iCurrentSrcLine:= CurrCmdSeq.iSrcLine;
	END_IF
	
	
	
	
    RETURN;
ELSIF eState = ST_ERR THEN
	IF xClearErr THEN
		eState:= ST_IDLE;
	END_IF
END_IF;

// ============================================================================
//  主状态机
// ============================================================================

IF eState<>ST_WAIT_MOTION THEN
	IF xMotionDone THEN
		xMotionDone:=FALSE;
	END_IF;
END_IF
CASE eState OF

	// --------------------------------------------------------------------------
	//  State 0 : Idle
	// --------------------------------------------------------------------------
	ST_IDLE:
		; // 空转，等待 xExecute
	
	// --------------------------------------------------------------------------
	//  State 1 : Running（取指 + 执行非阻塞指令）
	// --------------------------------------------------------------------------
	ST_RUN:
		// ---- 程序结束 ----
		IF iPC >= iPC_Max THEN
			eState := ST_IDLE;
			xBusy  := FALSE;
			xDone  := TRUE;
			RETURN;
		END_IF;
	
		// ---- 取指（解析 CMD_SEQ_LENGTH 个 INT，打包格式） ----
		
		CurrCmdSeq := ParseCmdSeq( E_CMD_LOCATION.CURR);
	
		// ---- 译码执行 ----
		CASE CurrCmdSeq.iOp OF
	
			// -------- 0 : NOP --------
			E_OP_CODE.NOP:
				iPC := iPC + 1;
			
			
			// -------- 1:MOVJ / 2:MOVL / 3:MOVC --------
			// p1: 目标位置寄存器 PR 索引 (0..31)
			// p2: 速度档位 (EnumVelocityRate: 0=V10 .. 9=V100)
			// p3: 过渡模式 (EnumTransientMode: 0=C0 .. 10=FINE)
			// p4: MOVC 过渡点 PR 索引 (0..31)
		
			E_OP_CODE.MOVJ:
				
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 31 THEN			
					MOVJ(iPC,aTeachPos[CurrCmdSeq.iP1], CurrCmdSeq.iP2,CurrCmdSeq.iP3,acc,dac);	
	
					eState      := ST_WAIT_MOTION;          // 转入 WaitMotion
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad PR index';
					eState    := ST_ERR;
				END_IF;
				
			E_OP_CODE.MOVL:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 31 THEN
					MOVL(iPC,aTeachPos[CurrCmdSeq.iP1],CurrCmdSeq.iP2,CurrCmdSeq.iP3,acc,dac);	
					
					
					eState      := ST_WAIT_MOTION;          // 转入 WaitMotion
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad PR index';
					eState    := ST_ERR;
				END_IF;
				
			E_OP_CODE.MOVC:
				// MOVC: p1=终点, p4=过渡点, p2=速度, p3=过渡模式
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 31 AND CurrCmdSeq.iP4 >= 0 AND CurrCmdSeq.iP4 <= 31 THEN
					MOVC(iPC, aTeachPos[CurrCmdSeq.iP1],aTeachPos[CurrCmdSeq.iP4],CurrCmdSeq.iP2,CurrCmdSeq.iP3,acc,dac);	
					
					eState      := ST_WAIT_MOTION;          // 转入 WaitMotion
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad PR index';
					eState    := ST_ERR;
				END_IF;
				
			E_OP_CODE.MOVJ_DO:
				// MOVJ_DO: p1=终点, p2=速度, p3=过渡模式,p5= DO索引，p6=  1 or 0,f1= 剩余距离mm
				//f2 == 0：do_delay 为常量，直接使用 f1（单位 ms）。
				//f2 > 0：do_delay 为变量模式，变量索引 = int(f2) - 1，PLC 从该变量寄存器读取延时值。
				//
				//
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 31 THEN			
					MOVJ(iPC,aTeachPos[CurrCmdSeq.iP1], CurrCmdSeq.iP2,CurrCmdSeq.iP3,acc,dac);	
					set_DO_when_motion.iPC:= iPC;
					set_DO_when_motion.iDO_index := CurrCmdSeq.iP5;
					set_DO_when_motion.iValue := TO_BOOL(CurrCmdSeq.iP6);
					IF CurrCmdSeq.lrF2 >0.0 THEN
						set_DO_when_motion.lrDistance := V[CurrCmdSeq.diF2/1000 -1];
					ELSE
						set_DO_when_motion.lrDistance := CurrCmdSeq.lrF1;
					END_IF
					
					eState      := ST_WAIT_MOTION;          // 转入 WaitMotion
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad PR index';
					eState    := ST_ERR;
				END_IF;
			E_OP_CODE.MOVL_DO:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 31 THEN			
					MOVL(iPC,aTeachPos[CurrCmdSeq.iP1], CurrCmdSeq.iP2,CurrCmdSeq.iP3,acc,dac);	
					set_DO_when_motion.iPC:= iPC;
					set_DO_when_motion.iDO_index := CurrCmdSeq.iP5;
					set_DO_when_motion.iValue := TO_BOOL(CurrCmdSeq.iP6);
					IF CurrCmdSeq.lrF2 >0.0 THEN
						set_DO_when_motion.lrDistance := V[CurrCmdSeq.diF2/1000 -1];
					ELSE
						set_DO_when_motion.lrDistance := CurrCmdSeq.lrF1;
					END_IF
					
					eState      := ST_WAIT_MOTION;          // 转入 WaitMotion
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad PR index';
					eState    := ST_ERR;
				END_IF;
			
			E_OP_CODE.MOVC_DO:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 31 AND CurrCmdSeq.iP4 >= 0 AND CurrCmdSeq.iP4 <= 31 THEN
					MOVC(iPC, aTeachPos[CurrCmdSeq.iP1],aTeachPos[CurrCmdSeq.iP4],CurrCmdSeq.iP2,CurrCmdSeq.iP3,acc,dac);
					set_DO_when_motion.iPC:= iPC;
					set_DO_when_motion.iDO_index := CurrCmdSeq.iP5;
					set_DO_when_motion.iValue := TO_BOOL(CurrCmdSeq.iP6);
					IF CurrCmdSeq.lrF2 >0.0 THEN
						set_DO_when_motion.lrDistance := V[CurrCmdSeq.diF2/1000 -1];
					ELSE
						set_DO_when_motion.lrDistance := CurrCmdSeq.lrF1;
					END_IF
					
					eState      := ST_WAIT_MOTION;          // 转入 WaitMotion
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad PR index';
					eState    := ST_ERR;
				END_IF;
			// -------- 10 : DELAY --------
			// f1: 延时毫秒（32 位 DINT，最大约 24 天）
			
			E_OP_CODE.DELAY:
				tmrDelay(IN:=FALSE);           // 先复位
				eState := ST_WAIT_DELAY;                   // 转入 WaitDelay
		
			// -------- 20 : SET_DO --------
			// p1: 输出索引（见 SetOutputByIndex）
			E_OP_CODE.SET_DO:
				SetOutputByIndex(CurrCmdSeq.iP1, TRUE);
				iPC := iPC + 1;
		
			// -------- 21 : RESET_DO --------
			E_OP_CODE.RESET_DO:
				SetOutputByIndex(CurrCmdSeq.iP1, FALSE);
				iPC := iPC + 1;
		
			// -------- 22 : WAIT_DI --------
			// p1: 输入索引；f1: 超时毫秒（0=无限等待）
			E_OP_CODE.WAIT_DI:
				tmrWait(IN:=FALSE);
				eState := ST_WAIT_DI;                   // 转入 WaitDI
		
			// -------- 23 : GET_DI --------
			// p1: 目标变量索引 V[p1]；p2: 输入索引
			E_OP_CODE.GET_DI:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 63 THEN
					IF GetInputByIndex(CurrCmdSeq.iP2) THEN
						V[CurrCmdSeq.iP1] := 1.0;
					ELSE
						V[CurrCmdSeq.iP1] := 0.0;
					END_IF;
					iPC := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var Index';
					eState    := ST_ERR;
				END_IF;
			// -------- 23 : GET_DO --------
			// p1: 目标变量索引 V[p1]；p2: 输入索引
			E_OP_CODE.GET_DO:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 63 THEN
					IF GetOutputByIndex(CurrCmdSeq.iP2) THEN
						V[CurrCmdSeq.iP1] := 1.0;
					ELSE
						V[CurrCmdSeq.iP1] := 0.0;
					END_IF;
					iPC := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var Index';
					eState    := ST_ERR;
				END_IF;
			// -------- 30 : IF（条件跳转，v3.0 新协议） --------
			// 语义：条件为 FALSE → iPC := p5*256 + p6（16 位绝对地址）；为 TRUE → 顺序执行
			// p1: 变量索引 V[p1]
			// p2: 比较类型：0:>  1:<  2:==  3:>=  4:<=  5:<>
			// p3: 0=常量比较(f1), 1=变量比较(V[f1])
			// p5/p6: 跳转目标地址 高/低字节（目标 = iPC_Max 即跳到程序末尾，合法）
			E_OP_CODE._IF:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 63 THEN
					bCond := FALSE;
					// p3=1: 与变量 V[f1] 比较；p3=0: 与常量 f1 比较
					IF CurrCmdSeq.iP3 = 1 AND CurrCmdSeq.diF1/1000 >= 0 AND CurrCmdSeq.diF1/1000 <= 63 THEN
						tmp_lrCurrF1 := V[DINT_TO_INT(CurrCmdSeq.diF1/1000)];
						tmp_result := TRUE;
					ELSIF CurrCmdSeq.iP3 = 0 THEN
						tmp_lrCurrF1 := CurrCmdSeq.lrF1;
						tmp_result := TRUE;
					ELSE
						tmp_result := FALSE;   // 非法 p3
					END_IF;

					IF NOT tmp_result THEN
						xError    := TRUE;
						sErrorMsg := 'Bad IF Operand';
						eState    := ST_ERR;
					ELSE
						CASE CurrCmdSeq.iP2 OF
							0: bCond := V[CurrCmdSeq.iP1] > tmp_lrCurrF1;
							1: bCond := V[CurrCmdSeq.iP1] < tmp_lrCurrF1;
							2: bCond := ABS(V[CurrCmdSeq.iP1] - tmp_lrCurrF1) < 1.0E-6;
							3: bCond := V[CurrCmdSeq.iP1] >= tmp_lrCurrF1;
							4: bCond := V[CurrCmdSeq.iP1] <= tmp_lrCurrF1;
							5: bCond := ABS(V[CurrCmdSeq.iP1] - tmp_lrCurrF1) >= 1.0E-6;
						ELSE
							bCond := FALSE;
						END_CASE;

						IF bCond THEN
							// 条件成立：顺序执行下一条
							iPC := iPC + 1;
						ELSE
							// 条件不成立：跳转到 p5*256+p6 指定的绝对地址
							j := CurrCmdSeq.iP5 * 256 + CurrCmdSeq.iP6;
							IF j >= 0 AND j <= iPC_Max THEN
								iPC := j;
							ELSE
								xError    := TRUE;
								sErrorMsg := 'Jump Out of Range';
								eState    := ST_ERR;
							END_IF;
						END_IF;
					END_IF;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var Index';
					eState    := ST_ERR;
				END_IF;

			// -------- 旧协议指令（ELSE/ENDIF/WHILE/ENDWHILE/FOR/ENDFOR/BREAK/CONTINUE） --------
			// v3.0 编译器已在编译期把以上结构化指令全部展开为 IF + JUMP，
			// PLC 上不会再出现；若收到，说明下载的是旧格式程序，请用新编译器重新编译下载。
			E_OP_CODE._ELSE, E_OP_CODE._ENDIF, E_OP_CODE._WHILE, E_OP_CODE._ENDWHILE,
			E_OP_CODE._FOR, E_OP_CODE._ENDFOR, E_OP_CODE._BREAK, E_OP_CODE._CONTINUE:
				xError    := TRUE;
				sErrorMsg := 'Obsolete OpCode, Recompile';
				eState    := ST_ERR;

			// -------- 40 : ASSIGN --------
			// V[p1] = f1
			E_OP_CODE._ASSIGN:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 63 THEN
					V[CurrCmdSeq.iP1] := CurrCmdSeq.lrF1;
					iPC        := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var Index';
					eState    := ST_ERR;
				END_IF;
		
			// -------- 41 : ADD --------
			// V[p1] = V[p2] + V[p3]
			E_OP_CODE._ADD:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 63 AND
				   CurrCmdSeq.iP2 >= 0 AND CurrCmdSeq.iP2 <= 63 AND
				   CurrCmdSeq.iP3 >= 0 AND CurrCmdSeq.iP3 <= 63 THEN
					V[CurrCmdSeq.iP1] := V[CurrCmdSeq.iP2] + V[CurrCmdSeq.iP3];
					iPC        := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var Index';
					eState    := ST_ERR;
				END_IF;
		
			// -------- 42 : SUB --------
			E_OP_CODE._SUB:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 63 AND
				   CurrCmdSeq.iP2 >= 0 AND CurrCmdSeq.iP2 <= 63 AND
				   CurrCmdSeq.iP3 >= 0 AND CurrCmdSeq.iP3 <= 63 THEN
					V[CurrCmdSeq.iP1] := V[CurrCmdSeq.iP2] - V[CurrCmdSeq.iP3];
					iPC        := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var Index';
					eState    := ST_ERR;
				END_IF;
		
			// -------- 43 : MUL --------
			E_OP_CODE._MUL:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 63 AND
				   CurrCmdSeq.iP2 >= 0 AND CurrCmdSeq.iP2 <= 63 AND
				   CurrCmdSeq.iP3 >= 0 AND CurrCmdSeq.iP3 <= 63 THEN
					V[CurrCmdSeq.iP1] := V[CurrCmdSeq.iP2] * V[CurrCmdSeq.iP3];
					iPC        := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var Index';
					eState    := ST_ERR;
				END_IF;
		
			// -------- 44 : DIV --------
			E_OP_CODE._DIV:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 63 AND
				   CurrCmdSeq.iP2 >= 0 AND CurrCmdSeq.iP2 <= 63 AND
				   CurrCmdSeq.iP3 >= 0 AND CurrCmdSeq.iP3 <= 63 THEN
					IF ABS(V[CurrCmdSeq.iP3]) > 1.0E-9 THEN
						V[CurrCmdSeq.iP1] := V[CurrCmdSeq.iP2] / V[CurrCmdSeq.iP3];
						iPC        := iPC + 1;
					ELSE
						xError    := TRUE;
						sErrorMsg := 'DivByZero';
						eState    := ST_ERR;
					END_IF;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var Index';
					eState    := ST_ERR;
				END_IF;
			
			// -------- 50 : JUMP（无条件跳转，v3.0 新协议） --------
			// p5/p6: 16 位绝对地址 高/低字节（目标 = iPC_Max 即跳到程序末尾，合法）
			E_OP_CODE._JUMP:
				j := CurrCmdSeq.iP5 * 256 + CurrCmdSeq.iP6;
				IF j >= 0 AND j <= iPC_Max THEN
					iPC := j;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Jump Out of Range';
					eState    := ST_ERR;
				END_IF;

		
			// -------- 72 : CALL（调用子程序，v3.2 新增） --------
			// p5/p6: 子程序入口 16 位绝对地址 高/低字节；返回地址(iPC+1)压栈
			E_OP_CODE._CALL:
				j := CurrCmdSeq.iP5 * 256 + CurrCmdSeq.iP6;
				IF j >= 0 AND j < iPC_Max THEN
					IF iCSP < 16 THEN
						CallStack[iCSP] := iPC + 1;
						iCSP := iCSP + 1;
						iPC  := j;
					ELSE
						xError    := TRUE;
						sErrorMsg := 'Call Stack Overflow';
						eState    := ST_ERR;
					END_IF;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Call Out of Range';
					eState    := ST_ERR;
				END_IF;

			// -------- 73 : RET（子程序返回，v3.2 新增） --------
			E_OP_CODE._RET:
				IF iCSP > 0 THEN
					iCSP := iCSP - 1;
					iPC  := CallStack[iCSP];
				ELSE
					xError    := TRUE;
					sErrorMsg := 'RET Without CALL';
					eState    := ST_ERR;
				END_IF;

			// -------- 99 : STOP --------
			E_OP_CODE._STOP:
				eState := 0;
				xBusy  := FALSE;
				xDone  := TRUE;

			// （原 60:FOR / 61:ENDFOR / BREAK / CONTINUE 处理已删除，由上方"旧协议指令"分支统一报错）

			E_OP_CODE.PR_CURPOS:
					
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 15 THEN
					tmpPose := GETCURRENTPOS();
	
					PR[CurrCmdSeq.iP1] := tmpPose ;
					
					iPC        := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var Index';
					eState    := ST_ERR;
				END_IF;
			E_OP_CODE.PR_ADD_VEC://PR[2] = PR[0] + PR[1];
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 15 AND
				   CurrCmdSeq.iP2 >= 0 AND CurrCmdSeq.iP2 <= 15 AND
				   CurrCmdSeq.iP3 >= 0 AND CurrCmdSeq.iP3 <= 15 THEN
					PR[CurrCmdSeq.iP1] :=  _POSREF_ADD(a := PR[CurrCmdSeq.iP2], b := PR[CurrCmdSeq.iP3]);
					
					iPC        := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var Index';
					eState    := ST_ERR;
				END_IF;
			E_OP_CODE.PR_SUB_VEC:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 15 AND
				   CurrCmdSeq.iP2 >= 0 AND CurrCmdSeq.iP2 <= 15 AND
				   CurrCmdSeq.iP3 >= 0 AND CurrCmdSeq.iP3 <= 15 THEN
					PR[CurrCmdSeq.iP1] :=  _POSREF_SUB(a := PR[CurrCmdSeq.iP2], b := PR[CurrCmdSeq.iP3]);
					
					iPC        := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var Index';
					eState    := ST_ERR;
				END_IF;
			E_OP_CODE.PR_MUL_SCALAR:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 15 AND
				   CurrCmdSeq.iP2 >= 0 AND CurrCmdSeq.iP2 <= 15 
				    THEN
					PR[CurrCmdSeq.iP1] :=  _POSREF_MUL_FACTOR(a := PR[CurrCmdSeq.iP2], b := CurrCmdSeq.lrF1);
					
					iPC        := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var Index';
					eState    := ST_ERR;
				END_IF;
			E_OP_CODE.PR_SET_COMP://PR[2].Z = 100;   comp_map = {"X": 0, "Y": 1, "Z": 2, "J1": 3, "J2": 4, "J3": 5} Instruction(op=<OpCode.PR_SET_COMP: 114>, p1=2, p2=2, p3=0, p4=0, f1=100.0, f2=0.0, src_line=4)
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 15 AND
				   CurrCmdSeq.iP2 >= 0 AND CurrCmdSeq.iP2 <= 5  THEN
				
					CASE CurrCmdSeq.iP2 OF
						0 :PR[CurrCmdSeq.iP1].x:=CurrCmdSeq.lrF1;
						1 :PR[CurrCmdSeq.iP1].y:=CurrCmdSeq.lrF1;
						2 :PR[CurrCmdSeq.iP1].z:=CurrCmdSeq.lrF1;
						3 :PR[CurrCmdSeq.iP1].j1:=CurrCmdSeq.lrF1;
						4 :PR[CurrCmdSeq.iP1].j2:=CurrCmdSeq.lrF1;
						5 :PR[CurrCmdSeq.iP1].j3:=CurrCmdSeq.lrF1;
					END_CASE
					
					iPC        := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var Index';
					eState    := ST_ERR;
				END_IF;
				
			E_OP_CODE.PR_ASSIGN_P://PR[1] = P[2];
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 15 AND
					CurrCmdSeq.iP2 >= 0 AND CurrCmdSeq.iP2 <= 31
					THEN
					
						PR[CurrCmdSeq.iP1]:=GVL_ROBOT.gaTeachPos[CurrCmdSeq.iP2];
						iPC        := iPC + 1;
					ELSE
						xError    := TRUE;
						sErrorMsg := 'Bad Var Index';
						eState    := ST_ERR;
					END_IF;
				
			E_OP_CODE.P_ASSIGN_PR://P[1] = PR[2];
			
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 31 AND
					CurrCmdSeq.iP2 >= 0 AND CurrCmdSeq.iP2 <= 15 THEN				
					GVL_ROBOT.gaTeachPos[CurrCmdSeq.iP1]:=PR[CurrCmdSeq.iP2];
					iPC        := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var Index';
					eState    := ST_ERR;
				END_IF;
					
			E_OP_CODE.SERVO_ON:
				eState    := ST_WAIT_POWER_ON;
				
			E_OP_CODE.SERVO_OFF:
				eState    := ST_WAIT_POWER_OFF;	
				
			// -------- 122:SET_ACCE --------
			E_OP_CODE.SET_ACCE:
				IF CurrCmdSeq.lrF1 >= 0 AND CurrCmdSeq.lrF1 <= 100 AND 
					CurrCmdSeq.lrF2 >= 0 AND CurrCmdSeq.lrF2 <= 100  THEN
					acc := CurrCmdSeq.lrF1/100.0;
					dac := CurrCmdSeq.lrF2/100.0;
					iPC := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad PR ';
					eState    := ST_ERR;
				END_IF;
			
			E_OP_CODE.STOPON_DI:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 15 THEN
					stop_on_DI_index := CurrCmdSeq.iP1;
					iPC := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var Index';
					eState    := ST_ERR;
				END_IF;
				
			E_OP_CODE.ISIGNAL_DI:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 15 THEN
					stop_on_DI_index := CurrCmdSeq.iP1;
					isignal_Di_value := TO_BOOL(CurrCmdSeq.ip2);
					iPC := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var Index';
					eState    := ST_ERR;
				END_IF;
			E_OP_CODE.DISTANCE_TO:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 63 AND
					CurrCmdSeq.iP2 >= 0 AND CurrCmdSeq.iP2 <= 31
					THEN				
					V[CurrCmdSeq.iP1]:=_POSREF_DISTANCE_A_TO_B(GETCURRENTPOS(),GVL_ROBOT.gaTeachPos[CurrCmdSeq.iP2]);
					iPC        := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var (DISTANCE_TO)';
					eState    := ST_ERR;
				END_IF;
			E_OP_CODE.IS_MOVING:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 63 THEN				
					IF IS_ROBOT_MOVING() THEN
						V[CurrCmdSeq.iP1] := 1.0;
					ELSE
						V[CurrCmdSeq.iP1] := 0.0;
					END_IF;
					iPC        := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var (IS_MOVING)';
					eState    := ST_ERR;
				END_IF;
			E_OP_CODE.SET_OVERALL:
				IF CurrCmdSeq.lrF1 > 0 AND CurrCmdSeq.lrF1 <= 100 THEN
					SETOVERALL(TO_UINT( CurrCmdSeq.lrF1));
					iPC := iPC + 1;
				ELSIF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 63 THEN
					SETOVERALL(TO_UINT(V[CurrCmdSeq.iP1]));
					iPC := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad PR (SET_OVERALL)';
					eState    := ST_ERR;
				END_IF;
				
			E_OP_CODE.GET_OVERALL:
				IF CurrCmdSeq.iP1 >= 0 AND CurrCmdSeq.iP1 <= 63 THEN				
					V[CurrCmdSeq.iP1] :=TO_LREAL(GET_OVERALL());
					iPC        := iPC + 1;
				ELSE
					xError    := TRUE;
					sErrorMsg := 'Bad Var (GET_OVERALL)';
					eState    := ST_ERR;
				END_IF;
				
		ELSE
			xError    := TRUE;
			sErrorMsg := 'Unknown OpCode';
			eState    := ST_ERR;
		END_CASE;
		
		IF GVL_ROBOT.g_xMotionIpc = set_DO_when_motion.iPC THEN
			IF GET_DISTANCE_LEFT()> 0.0 AND GET_DISTANCE_LEFT()<set_DO_when_motion.lrDistance THEN
				SetOutputByIndex(set_DO_when_motion.iDO_index,set_DO_when_motion.iValue);
				set_DO_when_motion.iDO_index:= -1;
			END_IF
			
		END_IF
		
// --------------------------------------------------------------------------
//  State 4 : WaitMotion（等待外部运动完成）                                |
// --------------------------------------------------------------------------
ST_WAIT_MOTION:
	
	
	CurrCmdSeq := ParseCmdSeq( E_CMD_LOCATION.CURR);
	prev_op    := ProgramMem[(iPC-1) * CMD_SEQ_LENGTH + 0] ;
	next_op:= ProgramMem[(iPC+1) * CMD_SEQ_LENGTH + 0] ;
	
	IF xMotionDone THEN
		xMotionDone:=FALSE;
		IF prev_op = E_OP_CODE.ISIGNAL_DI AND NOT isignal_Di_value=GetInputByIndex(stop_on_DI_index ) AND (next_op >=1 AND next_op <=6 ) THEN
			iPC    := iPC + 2;//没有触发DI，则跳过下一条运动指令
		ELSE
			iPC    := iPC + 1;
		END_IF
		
		eState := ST_RUN;            // 回到 Running
	
	ELSE
		IF NOT ENOUGH_CMD_IN_QUEUE() AND (prev_op <> E_OP_CODE.ISIGNAL_DI OR  prev_op = E_OP_CODE.ISIGNAL_DI AND isignal_Di_value=GetInputByIndex(stop_on_DI_index)) THEN
	
			IF CurrCmdSeq.iOp = E_OP_CODE.MOVJ THEN
		
				IF CurrCmdSeq.iP3 < 9 AND (iPC+1) <= iPC_Max THEN
					
					IF next_op = E_OP_CODE.MOVJ THEN
	
						NextCmdSeq := ParseCmdSeq( E_CMD_LOCATION.NEXT);
						
						IF NextCmdSeq.iP1 >= 0 AND NextCmdSeq.iP1 <= 31 THEN
							MOVJ(iPC+1,aTeachPos[NextCmdSeq.iP1], NextCmdSeq.iP2,NextCmdSeq.iP3,acc,dac);
							iPC    := iPC + 1;
						END_IF;
					ELSIF next_op =E_OP_CODE.MOVJ_DO THEN
						NextCmdSeq := ParseCmdSeq( E_CMD_LOCATION.NEXT);
						
						IF NextCmdSeq.iP1 >= 0 AND NextCmdSeq.iP1 <= 31 THEN
							MOVJ(iPC+1,aTeachPos[NextCmdSeq.iP1], NextCmdSeq.iP2,NextCmdSeq.iP3,acc,dac);
							set_DO_when_motion.iPC:= iPC+1;
							set_DO_when_motion.iDO_index := NextCmdSeq.iP5;
							set_DO_when_motion.iValue := TO_BOOL(NextCmdSeq.iP6);
							set_DO_when_motion.lrDistance := NextCmdSeq.lrF1;
							iPC    := iPC + 1;
						END_IF;
					
					END_IF
					
				ELSIF CurrCmdSeq.iP3 = 9 AND (iPC+1) <= iPC_Max THEN
					
					IF next_op>=1 AND next_op<=6 THEN
	
						NextCmdSeq := ParseCmdSeq( E_CMD_LOCATION.NEXT);
						IF NextCmdSeq.iP1 >= 0 AND NextCmdSeq.iP1 <= 31 THEN
							IF    next_op =E_OP_CODE.MOVJ  THEN
								MOVJ(iPC+1,aTeachPos[NextCmdSeq.iP1], NextCmdSeq.iP2,NextCmdSeq.iP3,acc,dac);
							ELSIF next_op =E_OP_CODE.MOVL  THEN
								MOVL(iPC+1,aTeachPos[NextCmdSeq.iP1], NextCmdSeq.iP2,NextCmdSeq.iP3,acc,dac);
							ELSIF next_op =E_OP_CODE.MOVC  THEN						
								MOVC(iPC+1,aTeachPos[NextCmdSeq.iP1],aTeachPos[NextCmdSeq.iP4], NextCmdSeq.iP2,NextCmdSeq.iP3,acc,dac);
							ELSIF next_op =E_OP_CODE.MOVJ_DO THEN
								NextCmdSeq := ParseCmdSeq( E_CMD_LOCATION.NEXT);							
								IF NextCmdSeq.iP1 >= 0 AND NextCmdSeq.iP1 <= 31 THEN
									MOVJ(iPC+1,aTeachPos[NextCmdSeq.iP1], NextCmdSeq.iP2,NextCmdSeq.iP3,acc,dac);
									set_DO_when_motion.iPC:= iPC+1;
									set_DO_when_motion.iDO_index := NextCmdSeq.iP5;
									set_DO_when_motion.iValue := TO_BOOL(NextCmdSeq.iP6);
									//set_DO_when_motion.lrDistance := NextCmdSeq.lrF1;	
									
									IF NextCmdSeq.lrF2 >0.0 THEN
										set_DO_when_motion.lrDistance := V[NextCmdSeq.diF2/1000 -1];
									ELSE
										set_DO_when_motion.lrDistance := NextCmdSeq.lrF1;
									END_IF
								END_IF;	
							ELSIF next_op =E_OP_CODE.MOVL_DO THEN
								NextCmdSeq := ParseCmdSeq( E_CMD_LOCATION.NEXT);							
								IF NextCmdSeq.iP1 >= 0 AND NextCmdSeq.iP1 <= 31 THEN
									MOVL(iPC+1,aTeachPos[NextCmdSeq.iP1], NextCmdSeq.iP2,NextCmdSeq.iP3,acc,dac);
									set_DO_when_motion.iPC:= iPC+1;
									set_DO_when_motion.iDO_index := NextCmdSeq.iP5;
									set_DO_when_motion.iValue := TO_BOOL(NextCmdSeq.iP6);
									//set_DO_when_motion.lrDistance := NextCmdSeq.lrF1;	
									
									IF NextCmdSeq.lrF2 >0.0 THEN
										set_DO_when_motion.lrDistance := V[NextCmdSeq.diF2/1000 -1];
									ELSE
										set_DO_when_motion.lrDistance := NextCmdSeq.lrF1;
									END_IF
								END_IF;	
							
							ELSIF next_op =E_OP_CODE.MOVC_DO THEN
								NextCmdSeq := ParseCmdSeq( E_CMD_LOCATION.NEXT);							
								IF NextCmdSeq.iP1 >= 0 AND NextCmdSeq.iP1 <= 31 THEN
									MOVC(iPC+1,aTeachPos[NextCmdSeq.iP1],aTeachPos[NextCmdSeq.iP4], NextCmdSeq.iP2,NextCmdSeq.iP3,acc,dac);
									set_DO_when_motion.iPC:= iPC+1;
									set_DO_when_motion.iDO_index := NextCmdSeq.iP5;
									set_DO_when_motion.iValue := TO_BOOL(NextCmdSeq.iP6);
									//set_DO_when_motion.lrDistance := NextCmdSeq.lrF1;
									IF NextCmdSeq.lrF2 >0.0 THEN
										set_DO_when_motion.lrDistance := V[NextCmdSeq.diF2/1000 -1];
									ELSE
										set_DO_when_motion.lrDistance := NextCmdSeq.lrF1;
									END_IF
								END_IF;	
							END_IF
							
							iPC    := iPC + 1;
						END_IF;
						
					END_IF
				
					
				END_IF
			ELSIF CurrCmdSeq.iOp = E_OP_CODE.MOVL THEN
				IF CurrCmdSeq.iP3 < 9 AND (iPC+1) <= iPC_Max THEN
					
					IF next_op =E_OP_CODE.MOVJ THEN
						
						NextCmdSeq := ParseCmdSeq( E_CMD_LOCATION.NEXT);
						
						IF NextCmdSeq.iP1 >= 0 AND NextCmdSeq.iP1 <= 31 THEN
							MOVJ(iPC+1,aTeachPos[NextCmdSeq.iP1], NextCmdSeq.iP2,NextCmdSeq.iP3,acc,dac);
							iPC    := iPC + 1;
						END_IF;
					ELSIF next_op =E_OP_CODE.MOVJ_DO THEN
						NextCmdSeq := ParseCmdSeq( E_CMD_LOCATION.NEXT);							
						IF NextCmdSeq.iP1 >= 0 AND NextCmdSeq.iP1 <= 31 THEN
							MOVJ(iPC+1,aTeachPos[NextCmdSeq.iP1], NextCmdSeq.iP2,NextCmdSeq.iP3,acc,dac);
							set_DO_when_motion.iPC:= iPC+1;
							set_DO_when_motion.iDO_index := NextCmdSeq.iP5;
							set_DO_when_motion.iValue := TO_BOOL(NextCmdSeq.iP6);
							set_DO_when_motion.lrDistance := NextCmdSeq.lrF1;	
							iPC    := iPC + 1;
						END_IF;	
					
					END_IF
	
				END_IF;
				
			ELSIF CurrCmdSeq.iOp = E_OP_CODE.MOVC THEN	
				IF CurrCmdSeq.iP3 < 9 AND (iPC+1) <= iPC_Max THEN
					
					IF next_op =E_OP_CODE.MOVJ THEN
						
						NextCmdSeq := ParseCmdSeq( E_CMD_LOCATION.NEXT);
						
						IF NextCmdSeq.iP1 >= 0 AND NextCmdSeq.iP1 <= 31 THEN
							MOVJ(iPC+1,aTeachPos[NextCmdSeq.iP1], NextCmdSeq.iP2,NextCmdSeq.iP3,acc,dac);
							iPC    := iPC + 1;
						END_IF;
					ELSIF next_op =E_OP_CODE.MOVJ_DO THEN
						NextCmdSeq := ParseCmdSeq( E_CMD_LOCATION.NEXT);							
						IF NextCmdSeq.iP1 >= 0 AND NextCmdSeq.iP1 <= 31 THEN
							MOVJ(iPC+1,aTeachPos[NextCmdSeq.iP1], NextCmdSeq.iP2,NextCmdSeq.iP3,acc,dac);
							set_DO_when_motion.iPC:= iPC+1;
							set_DO_when_motion.iDO_index := NextCmdSeq.iP5;
							set_DO_when_motion.iValue := TO_BOOL(NextCmdSeq.iP6);
							set_DO_when_motion.lrDistance := NextCmdSeq.lrF1;	
							iPC    := iPC + 1;
						END_IF;	
					END_IF
				
				END_IF;
				
			END_IF	
		END_IF
		
		(* 如果*)
		DI_V:=GetInputByIndex(stop_on_DI_index );
		IF prev_op = E_OP_CODE.ISIGNAL_DI AND isignal_Di_value=GetInputByIndex(stop_on_DI_index ) THEN
			iPC    := iPC + 1;
			eState := ST_RUN;            // 回到 Running
		END_IF;
	END_IF;
	
	
	IF GVL_ROBOT.g_xMotionIpc = set_DO_when_motion.iPC THEN
		IF GET_DISTANCE_LEFT()> 0.0 AND GET_DISTANCE_LEFT()<set_DO_when_motion.lrDistance THEN
			SetOutputByIndex(set_DO_when_motion.iDO_index,set_DO_when_motion.iValue);
			set_DO_when_motion.iDO_index:= -1;
		END_IF
		
	END_IF
	
// --------------------------------------------------------------------------
//  State 5 : WaitDelay（延时等待）
// --------------------------------------------------------------------------
ST_WAIT_DELAY:
	
    tmrDelay(IN:=TRUE, PT:=LREAL_TO_TIME(CurrCmdSeq.lrF1));
	
    IF tmrDelay.Q THEN
        tmrDelay(IN:=FALSE);
        iPC    := iPC + 1;
        eState := ST_RUN;
    END_IF;

// --------------------------------------------------------------------------
//  State 6 : WaitDI（等待输入为真，可选超时）
// --------------------------------------------------------------------------
ST_WAIT_DI:
	
    IF GetInputByIndex(CurrCmdSeq.iP1) THEN
        tmrWait(IN:=FALSE);
        iPC    := iPC + 1;
        eState := ST_RUN;
    ELSIF CurrCmdSeq.diF1 > 0 AND FALSE THEN
        // f1 > 0 表示启用超时（毫秒）
        tmrWait(IN:=TRUE, PT:=LREAL_TO_TIME(CurrCmdSeq.lrF1));
        IF tmrWait.Q THEN
            tmrWait(IN:=FALSE);
            xError    := TRUE;
            sErrorMsg := 'WaitDI Timeout';
            eState    := ST_ERR;
        END_IF;
    END_IF;
ST_WAIT_POWER_ON:
	xAskPowerOn:=TRUE;
	IF IS_ROBOT_MOTORS_ENABLED() THEN
		xAskPowerOn:=FALSE;
		iPC    := iPC + 1;
		eState := ST_RUN;
	END_IF
ST_WAIT_POWER_OFF:
	xAskPowerOff:=TRUE;
	IF NOT IS_ROBOT_MOTORS_ENABLED() THEN
		xAskPowerOff:=FALSE;
		iPC    := iPC + 1;
		eState := ST_RUN;
	END_IF
// --------------------------------------------------------------------------|
//  State 3 : Error（出错停机，需 xReset 复位）                              |
// --------------------------------------------------------------------------|
ST_ERR:
    xBusy := FALSE;
    // 保持错误状态，等待外部复位

END_CASE;

// 输出当前 PC 供监视

IF eState = ST_WAIT_MOTION  THEN
	iPCtoDisplay := GVL_ROBOT.g_xMotionIpc;
ELSIF eState <> ST_ERR AND eState <> ST_HALT AND eState <> ST_IDLE THEN
	iPCtoDisplay := iPC;
END_IF

iCurrentSrcLine:= CurrCmdSeq.iSrcLine;
