VAR   PickFromStorageReq:BOOL = FALSE;
VAR   PutIntoStorageReq :BOOL = FALSE;
VAR   IsRobotMoving     :BOOL = FALSE;
VAR   Distance          :REAL = 0.0;
VAR   SpeedOverall      :REAL = 0.0;
MAP   GearOutPos TO V[49];
CONST PICK_FROM_STORAGE_REQ       :INT= 1;
CONST PUT_INTO_STORAGE_REQ        :INT= 2;
CONST ACK_INTERUPT                :INT= 9;
CONST IS_BOX_ON_WORKSTATION       :INT= 10;
CONST IS_GEARIN                   :INT= 11;
CONST IS_GEAROUT                  :INT= 12;
CONST IS_GRIPPER_CLASPED          :INT= 13;
CONST IS_BOX_INTO_ROBOT_CNY       :INT= 14;
CONST IS_BOX_NEER_WORKSTATION     :INT= 6;
CONST PICK_FROM_STORAGE_ACK       :INT= 1;
CONST PUT_INTO_STORAGE_ACK        :INT= 2;
CONST ASK_INTERUPT                :INT= 9;
CONST ASK_BOX_TO_WORKSTATION      :INT= 10;
CONST ASK_GEARIN                  :INT= 11;
CONST ASK_GEAROUT                 :INT= 12;
CONST CLASP_GRIPPER               :INT= 13;
CONST ASK_CNY_RUN_AFTER_GEAROUT   :INT= 14;
CONST ASK_CNY_RUN_AGAIN           :INT= 6;
CONST TASK_DONE                   :INT= 15;
CONST ASK_BOX_TO_ARM_CNY          :INT= 10;
CONST DI10_IS_BOX_ON_ROBOT_CNY    :INT= 10;
CONST IS_ALLOW_PUSH               :INT= 14;
CONST ASK_BOX_TO_STORAGE          :INT= 14;
CONST 拣选区放箱位   :INT= 11;
CONST 货架预取箱位   :INT= 12;
CONST 货架取箱位     :INT= 13;
CONST 货架取箱后退位 :INT= 14;
CONST 拣选区取箱位   :INT= 11;
CONST 货架放箱原位   :INT= 12;
CONST 货架放箱预推位 :INT= 13;
CONST 货架放箱位     :INT= 14;
SET_ACCE(100.0,100.0);
RESET_DO(9);
RESET_DO(10);
RESET_DO(11);
RESET_DO(12);
RESET_DO(13);
RESET_DO(14);
WHILE TRUE DO
    PickFromStorageReq = GET_DI(PICK_FROM_STORAGE_REQ);
    PutIntoStorageReq  = GET_DI(PUT_INTO_STORAGE_REQ);
    RESET_DO(PICK_FROM_STORAGE_ACK);
    RESET_DO(PUT_INTO_STORAGE_ACK);
    RESET_DO(TASK_DONE);
    IF PickFromStorageReq THEN//从货架取箱子 
        SET_DO(PICK_FROM_STORAGE_ACK);//     
        IsRobotMoving = IS_MOVING();
        IF IsRobotMoving THEN
            Distance = DISTANCE_TO(P[货架预取箱位]);
            ISIGNAL_DI(DI[7],false);//强制下一条运动指令不阻塞
            MOVJ(P[货架预取箱位],V100,C100);//P[12]精定位取箱位(吸盘预取位)
        ELSE
            Distance = DISTANCE_TO(P[货架预取箱位]);
            IF Distance<300.0 THEN
                ISIGNAL_DI(DI[7],false);//强制下一条运动指令不阻塞
                MOVJ(P[货架预取箱位],V100,C100);//P[12]精定位取箱位(吸盘预取位)
            ELSE
                ISIGNAL_DI(DI[ACK_INTERUPT],TRUE);
                MOVL_DO(P[货架预取箱位],V80,C0,300.0,DO[ASK_INTERUPT],TRUE);//P[12]精定位取箱位(吸盘预取位)
                MOVJ(P[货架预取箱位],V100,C100);
            END_IF;
        ENDIF;
        ISIGNAL_DI(DI[IS_GRIPPER_CLASPED],TRUE);//检测到吸住箱子后
        MOVJ_DO(P[货架取箱位],V100,C0,100.0,DO[CLASP_GRIPPER],TRUE);//定位到货架取箱位 距离到位50mm 打开吸盘
        SpeedOverall = GET_OVERALL();
        SET_OVERALL(80.0);
        CALL FUN_PositionToRetPickAndGearIn();// 吸盘轴定位到0点，过程中耦合输送带
        CALL FUN_PositionToRetPickAndGearOut();// 吸盘轴定位到0点，过程中解耦输送带
        CALL FUN_RunConveyUntilBoxIn();        //运行输送带直到箱子完全进入输送带
        SET_OVERALL(SpeedOverall);
        CALL FUN_GotoAndMoveBoxToWorkstationSide();
        CALL FUN_Tranfer_Box_to_Workstation();//输送箱子到工作台
        RESET_DO(PICK_FROM_STORAGE_ACK);
        SET_DO(TASK_DONE);//完成
    ELSIF PutIntoStorageReq THEN//放箱子到货架
        SET_DO(PUT_INTO_STORAGE_ACK);//
        IsRobotMoving = IS_MOVING();
        IF IsRobotMoving THEN            
            MOVJ(P[拣选区取箱位],V100,FINE);//
        ELSE
            MOVL(P[拣选区取箱位],V100,FINE);//
        ENDIF;
        
        CALL FUN_TranferBoxToConveyFromWorkstation();
        MOVL(P[货架放箱预推位],V100,FINE);//P[13]精定位放箱位(吸盘预推位)
        CALL FUN_PushBoxToStoreByConvey();
        CALL FUN_GearIn();//耦合输送带和吸盘臂
        SpeedOverall = GET_OVERALL();
        SET_OVERALL(80.0);
        CALL FUN_PushBoxToStoreBySucker();
        SET_OVERALL(SpeedOverall);
        CALL FUN_PositionToRetPut();
        RESET_DO(PUT_INTO_STORAGE_ACK);
        SET_DO(TASK_DONE);//完成
    END_IF;
END_WHILE;
STOP;
SUB FUN_GearIn():
    SET_DO(ASK_GEARIN);//请求耦合
    WAIT_DI(IS_GEARIN,0);//等待耦合成功
    RESET_DO(ASK_GEARIN);
END_SUB
SUB FUN_GearOut():
    SET_DO(ASK_GEAROUT);//解除耦合
    WAIT_DI(IS_GEAROUT,0);//解除耦合成功
    RESET_DO(ASK_GEAROUT);
END_SUB
SUB FUN_Tranfer_Box_to_Workstation():
    SET_DO(ASK_BOX_TO_WORKSTATION);
    WAIT_DI(IS_BOX_ON_WORKSTATION,0);//等待箱子到工作位
    RESET_DO(ASK_BOX_TO_WORKSTATION);
END_SUB
SUB FUN_PositionToRetPickAndGearIn():
    ISIGNAL_DI(DI[ACK_INTERUPT],TRUE);//
    MOVJ_DO(P[货架取箱后退位],V80,C0,600.0,DO[ASK_INTERUPT],TRUE);// P[14]精定位取箱回位 距离到位600mm申请耦合
    RESET_DO(ASK_INTERUPT);
    CALL FUN_GearIn();//耦合输送带和吸盘臂
END_SUB
SUB FUN_PositionToRetPickAndGearOut():
    ISIGNAL_DI(DI[ACK_INTERUPT],TRUE);//
    MOVJ_DO(P[货架取箱后退位],V80,C0,GearOutPos,DO[ASK_INTERUPT],TRUE);// P[14]精定位取箱回位 距离到位147mm申请解除耦合
    RESET_DO(ASK_INTERUPT);
    RESET_DO(CLASP_GRIPPER);
    CALL FUN_GearOut();
END_SUB
SUB FUN_RunConveyUntilBoxIn():
    ISIGNAL_DI(DI[IS_BOX_INTO_ROBOT_CNY],TRUE);//
    MOVJ_DO(P[货架取箱后退位],V80,FINE,1000.0,DO[ASK_CNY_RUN_AFTER_GEAROUT],TRUE);
    WAIT_DI(IS_BOX_INTO_ROBOT_CNY,0);//等待箱子进入输送带
    RESET_DO(ASK_CNY_RUN_AFTER_GEAROUT);
END_SUB
SUB FUN_GotoAndMoveBoxToWorkstationSide():
    ISIGNAL_DI(DI[IS_BOX_NEER_WORKSTATION],TRUE);//
    MOVL_DO(P[拣选区放箱位],V100,FINE,5000.0,DO[ASK_CNY_RUN_AGAIN],TRUE);
    WAIT_DI(IS_BOX_NEER_WORKSTATION,0);//
    RESET_DO(ASK_CNY_RUN_AGAIN);
    WAIT_MOTION_DONE;
END_SUB
SUB FUN_TranferBoxToConveyFromWorkstation():
    SET_DO(ASK_BOX_TO_ARM_CNY);//请求输送线送箱子
    WAIT_DI(DI10_IS_BOX_ON_ROBOT_CNY,0);//等待箱子到输送带
    RESET_DO(ASK_BOX_TO_ARM_CNY);
END_SUB
SUB FUN_PushBoxToStoreByConvey():
    SET_DO(ASK_BOX_TO_STORAGE);//请求皮带送箱出干涉点
    WAIT_DI(IS_ALLOW_PUSH,0);//
    RESET_DO(ASK_BOX_TO_STORAGE);
END_SUB
SUB FUN_PushBoxToStoreBySucker():
    MOVL_DO(P[货架放箱位],V100,C0,50.0,DO[ASK_GEAROUT],TRUE);//推箱，距离到位50mm申请
    WAIT_DI(IS_GEAROUT,0);//等待解除耦合成功
    RESET_DO(ASK_GEAROUT);
END_SUB
SUB FUN_PositionToRetPut():
    ISIGNAL_DI(DI[ACK_INTERUPT],TRUE);//
    MOVJ_DO(P[货架放箱原位],V100,C0,600.0,DO[ASK_INTERUPT],TRUE);//距离目标600.0mm
    RESET_DO(ASK_INTERUPT);
END_SUB