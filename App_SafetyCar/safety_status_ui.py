# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'safety_status.ui'
##
## Created by: Qt User Interface Compiler version 6.6.3
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QSizePolicy, QSpacerItem, QVBoxLayout, QWidget)

class Ui_Form(object):
    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName(u"Form")
        Form.resize(243, 840)
        self.verticalLayout_3 = QVBoxLayout(Form)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.verticalLayout_2 = QVBoxLayout()
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.horizontalLayout_4 = QHBoxLayout()
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.label = QLabel(Form)
        self.label.setObjectName(u"label")
        font = QFont()
        font.setPointSize(16)
        self.label.setFont(font)

        self.horizontalLayout_4.addWidget(self.label)

        self.label_safety_triggered = QLabel(Form)
        self.label_safety_triggered.setObjectName(u"label_safety_triggered")
        self.label_safety_triggered.setFont(font)

        self.horizontalLayout_4.addWidget(self.label_safety_triggered)


        self.verticalLayout_2.addLayout(self.horizontalLayout_4)

        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_2.addItem(self.verticalSpacer)

        self.verticalLayout = QVBoxLayout()
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.label_3 = QLabel(Form)
        self.label_3.setObjectName(u"label_3")

        self.horizontalLayout.addWidget(self.label_3)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer)

        self.label_total_carbinet_counts = QLabel(Form)
        self.label_total_carbinet_counts.setObjectName(u"label_total_carbinet_counts")
        self.label_total_carbinet_counts.setFont(font)

        self.horizontalLayout.addWidget(self.label_total_carbinet_counts)


        self.verticalLayout.addLayout(self.horizontalLayout)

        self.horizontalLayout_2 = QHBoxLayout()
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.label_5 = QLabel(Form)
        self.label_5.setObjectName(u"label_5")

        self.horizontalLayout_2.addWidget(self.label_5)

        self.horizontalSpacer_2 = QSpacerItem(40, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_2.addItem(self.horizontalSpacer_2)

        self.label_total_carbinet_online = QLabel(Form)
        self.label_total_carbinet_online.setObjectName(u"label_total_carbinet_online")
        self.label_total_carbinet_online.setFont(font)

        self.horizontalLayout_2.addWidget(self.label_total_carbinet_online)


        self.verticalLayout.addLayout(self.horizontalLayout_2)

        self.horizontalLayout_3 = QHBoxLayout()
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.label_7 = QLabel(Form)
        self.label_7.setObjectName(u"label_7")

        self.horizontalLayout_3.addWidget(self.label_7)

        self.horizontalSpacer_3 = QSpacerItem(40, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_3.addItem(self.horizontalSpacer_3)

        self.label_total_carbinet_err = QLabel(Form)
        self.label_total_carbinet_err.setObjectName(u"label_total_carbinet_err")
        self.label_total_carbinet_err.setFont(font)

        self.horizontalLayout_3.addWidget(self.label_total_carbinet_err)


        self.verticalLayout.addLayout(self.horizontalLayout_3)


        self.verticalLayout_2.addLayout(self.verticalLayout)

        self.verticalLayout_6 = QVBoxLayout()
        self.verticalLayout_6.setObjectName(u"verticalLayout_6")
        self.horizontalLayout_9 = QHBoxLayout()
        self.horizontalLayout_9.setObjectName(u"horizontalLayout_9")
        self.label_9 = QLabel(Form)
        self.label_9.setObjectName(u"label_9")

        self.horizontalLayout_9.addWidget(self.label_9)

        self.horizontalSpacer_4 = QSpacerItem(40, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_9.addItem(self.horizontalSpacer_4)

        self.label_configured_agv_counts = QLabel(Form)
        self.label_configured_agv_counts.setObjectName(u"label_configured_agv_counts")
        self.label_configured_agv_counts.setFont(font)

        self.horizontalLayout_9.addWidget(self.label_configured_agv_counts)


        self.verticalLayout_6.addLayout(self.horizontalLayout_9)

        self.horizontalLayout_10 = QHBoxLayout()
        self.horizontalLayout_10.setObjectName(u"horizontalLayout_10")
        self.label_11 = QLabel(Form)
        self.label_11.setObjectName(u"label_11")

        self.horizontalLayout_10.addWidget(self.label_11)

        self.horizontalSpacer_5 = QSpacerItem(40, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_10.addItem(self.horizontalSpacer_5)

        self.label_disconnected_agv_counts = QLabel(Form)
        self.label_disconnected_agv_counts.setObjectName(u"label_disconnected_agv_counts")
        self.label_disconnected_agv_counts.setFont(font)

        self.horizontalLayout_10.addWidget(self.label_disconnected_agv_counts)


        self.verticalLayout_6.addLayout(self.horizontalLayout_10)

        self.horizontalLayout_11 = QHBoxLayout()
        self.horizontalLayout_11.setObjectName(u"horizontalLayout_11")
        self.label_13 = QLabel(Form)
        self.label_13.setObjectName(u"label_13")

        self.horizontalLayout_11.addWidget(self.label_13)

        self.horizontalSpacer_6 = QSpacerItem(40, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_11.addItem(self.horizontalSpacer_6)

        self.label_err_agv_counts = QLabel(Form)
        self.label_err_agv_counts.setObjectName(u"label_err_agv_counts")
        self.label_err_agv_counts.setFont(font)

        self.horizontalLayout_11.addWidget(self.label_err_agv_counts)


        self.verticalLayout_6.addLayout(self.horizontalLayout_11)


        self.verticalLayout_2.addLayout(self.verticalLayout_6)

        self.verticalSpacer_2 = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_2.addItem(self.verticalSpacer_2)

        self.frame = QFrame(Form)
        self.frame.setObjectName(u"frame")
        self.frame.setFrameShape(QFrame.Box)
        self.frame.setFrameShadow(QFrame.Raised)
        self.verticalLayout_4 = QVBoxLayout(self.frame)
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.checkBox_is_fireSignal_enable = QCheckBox(self.frame)
        self.checkBox_is_fireSignal_enable.setObjectName(u"checkBox_is_fireSignal_enable")
        self.checkBox_is_fireSignal_enable.setEnabled(False)
        self.checkBox_is_fireSignal_enable.setTabletTracking(False)
        self.checkBox_is_fireSignal_enable.setLayoutDirection(Qt.RightToLeft)

        self.verticalLayout_4.addWidget(self.checkBox_is_fireSignal_enable)

        self.checkBox_is_enable_estop_ext = QCheckBox(self.frame)
        self.checkBox_is_enable_estop_ext.setObjectName(u"checkBox_is_enable_estop_ext")
        self.checkBox_is_enable_estop_ext.setEnabled(False)
        self.checkBox_is_enable_estop_ext.setLayoutDirection(Qt.RightToLeft)

        self.verticalLayout_4.addWidget(self.checkBox_is_enable_estop_ext)

        self.checkBox_is_double_plc = QCheckBox(self.frame)
        self.checkBox_is_double_plc.setObjectName(u"checkBox_is_double_plc")
        self.checkBox_is_double_plc.setEnabled(False)
        self.checkBox_is_double_plc.setTabletTracking(False)
        self.checkBox_is_double_plc.setLayoutDirection(Qt.RightToLeft)

        self.verticalLayout_4.addWidget(self.checkBox_is_double_plc)

        self.checkBox_need_ask_open_door = QCheckBox(self.frame)
        self.checkBox_need_ask_open_door.setObjectName(u"checkBox_need_ask_open_door")
        self.checkBox_need_ask_open_door.setEnabled(False)
        self.checkBox_need_ask_open_door.setLayoutDirection(Qt.RightToLeft)

        self.verticalLayout_4.addWidget(self.checkBox_need_ask_open_door)

        self.checkBox_is_disable_buzzer = QCheckBox(self.frame)
        self.checkBox_is_disable_buzzer.setObjectName(u"checkBox_is_disable_buzzer")
        self.checkBox_is_disable_buzzer.setEnabled(False)
        self.checkBox_is_disable_buzzer.setLayoutDirection(Qt.RightToLeft)

        self.verticalLayout_4.addWidget(self.checkBox_is_disable_buzzer)


        self.verticalLayout_2.addWidget(self.frame)

        self.label_2 = QLabel(Form)
        self.label_2.setObjectName(u"label_2")

        self.verticalLayout_2.addWidget(self.label_2)

        self.plainTextEdit = QPlainTextEdit(Form)
        self.plainTextEdit.setObjectName(u"plainTextEdit")
        self.plainTextEdit.setMinimumSize(QSize(0, 200))

        self.verticalLayout_2.addWidget(self.plainTextEdit)


        self.verticalLayout_3.addLayout(self.verticalLayout_2)

        self.Btn_clear = QPushButton(Form)
        self.Btn_clear.setObjectName(u"Btn_clear")
        font1 = QFont()
        font1.setPointSize(10)
        self.Btn_clear.setFont(font1)

        self.verticalLayout_3.addWidget(self.Btn_clear)

        self.groupBox = QGroupBox(Form)
        self.groupBox.setObjectName(u"groupBox")
        self.verticalLayout_5 = QVBoxLayout(self.groupBox)
        self.verticalLayout_5.setObjectName(u"verticalLayout_5")
        self.horizontalLayout_5 = QHBoxLayout()
        self.horizontalLayout_5.setObjectName(u"horizontalLayout_5")
        self.label_4 = QLabel(self.groupBox)
        self.label_4.setObjectName(u"label_4")

        self.horizontalLayout_5.addWidget(self.label_4)

        self.label_A1_ip = QLabel(self.groupBox)
        self.label_A1_ip.setObjectName(u"label_A1_ip")

        self.horizontalLayout_5.addWidget(self.label_A1_ip)


        self.verticalLayout_5.addLayout(self.horizontalLayout_5)

        self.horizontalLayout_6 = QHBoxLayout()
        self.horizontalLayout_6.setObjectName(u"horizontalLayout_6")
        self.label_8 = QLabel(self.groupBox)
        self.label_8.setObjectName(u"label_8")

        self.horizontalLayout_6.addWidget(self.label_8)

        self.label_A1_MAC = QLabel(self.groupBox)
        self.label_A1_MAC.setObjectName(u"label_A1_MAC")

        self.horizontalLayout_6.addWidget(self.label_A1_MAC)


        self.verticalLayout_5.addLayout(self.horizontalLayout_6)

        self.horizontalLayout_7 = QHBoxLayout()
        self.horizontalLayout_7.setObjectName(u"horizontalLayout_7")
        self.label_10 = QLabel(self.groupBox)
        self.label_10.setObjectName(u"label_10")

        self.horizontalLayout_7.addWidget(self.label_10)

        self.label_A2_ip = QLabel(self.groupBox)
        self.label_A2_ip.setObjectName(u"label_A2_ip")

        self.horizontalLayout_7.addWidget(self.label_A2_ip)


        self.verticalLayout_5.addLayout(self.horizontalLayout_7)

        self.horizontalLayout_8 = QHBoxLayout()
        self.horizontalLayout_8.setObjectName(u"horizontalLayout_8")
        self.label_12 = QLabel(self.groupBox)
        self.label_12.setObjectName(u"label_12")

        self.horizontalLayout_8.addWidget(self.label_12)

        self.label_A2_MAC = QLabel(self.groupBox)
        self.label_A2_MAC.setObjectName(u"label_A2_MAC")

        self.horizontalLayout_8.addWidget(self.label_A2_MAC)


        self.verticalLayout_5.addLayout(self.horizontalLayout_8)


        self.verticalLayout_3.addWidget(self.groupBox)

        self.verticalSpacer_3 = QSpacerItem(20, 218, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Maximum)

        self.verticalLayout_3.addItem(self.verticalSpacer_3)


        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)
    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", u"Form", None))
        self.label.setText(QCoreApplication.translate("Form", u"\u5b89\u5168\u4fe1\u53f7\uff1a", None))
        self.label_safety_triggered.setText(QCoreApplication.translate("Form", u"\u6b63\u5e38", None))
        self.label_3.setText(QCoreApplication.translate("Form", u"\u914d\u7f6e\u7684\u7535\u67dc\u6570\u91cf\uff1a", None))
        self.label_total_carbinet_counts.setText(QCoreApplication.translate("Form", u"10", None))
        self.label_5.setText(QCoreApplication.translate("Form", u"\u5728\u7ebf\u7684\u7535\u67dc\u6570\u91cf\uff1a", None))
        self.label_total_carbinet_online.setText(QCoreApplication.translate("Form", u"10", None))
        self.label_7.setText(QCoreApplication.translate("Form", u"\u544a\u8b66\u7684\u7535\u67dc\u6570\u91cf\uff1a", None))
        self.label_total_carbinet_err.setText(QCoreApplication.translate("Form", u"10", None))
        self.label_9.setText(QCoreApplication.translate("Form", u"\u914d\u7f6e\u7684AGV\u6570\u91cf\uff1a", None))
        self.label_configured_agv_counts.setText(QCoreApplication.translate("Form", u"10", None))
        self.label_11.setText(QCoreApplication.translate("Form", u"\u7f51\u7edc\u65ad\u5f00\u7684AGV\u6570\u91cf\uff1a", None))
        self.label_disconnected_agv_counts.setText(QCoreApplication.translate("Form", u"10", None))
        self.label_13.setText(QCoreApplication.translate("Form", u"\u72b6\u6001\u5f02\u5e38\u7684AGV\u6570\u91cf\uff1a", None))
        self.label_err_agv_counts.setText(QCoreApplication.translate("Form", u"10", None))
        self.checkBox_is_fireSignal_enable.setText(QCoreApplication.translate("Form", u"\u662f\u5426\u542f\u7528\u4e86\u6d88\u9632\u4fe1\u53f7", None))
        self.checkBox_is_enable_estop_ext.setText(QCoreApplication.translate("Form", u"\u662f\u5426\u542f\u7528\u4e86\u5916\u90e8\u6025\u505c\u4fe1\u53f7", None))
        self.checkBox_is_double_plc.setText(QCoreApplication.translate("Form", u"\u662f\u5426\u542f\u7528\u4e86\u53ccPLC", None))
        self.checkBox_need_ask_open_door.setText(QCoreApplication.translate("Form", u"\u5f00\u95e8\u524d\u662f\u5426\u9700\u8981\u5411\u5e73\u53f0\u53d1\u8d77\u8bf7\u6c42", None))
        self.checkBox_is_disable_buzzer.setText(QCoreApplication.translate("Form", u"\u662f\u5426\u7981\u6b62\u4e86\u8702\u9e23\u5668", None))
        self.label_2.setText(QCoreApplication.translate("Form", u"\u544a\u8b66\u6d88\u606f", None))
        self.Btn_clear.setText(QCoreApplication.translate("Form", u"\u6e05\u7a7a", None))
        self.groupBox.setTitle(QCoreApplication.translate("Form", u"PLC\u7684ip\u5730\u5740\u548cmac\u5730\u5740", None))
        self.label_4.setText(QCoreApplication.translate("Form", u"A1 ip:", None))
        self.label_A1_ip.setText(QCoreApplication.translate("Form", u"TextLabel", None))
        self.label_8.setText(QCoreApplication.translate("Form", u"A1 MAC:", None))
        self.label_A1_MAC.setText(QCoreApplication.translate("Form", u"TextLabel", None))
        self.label_10.setText(QCoreApplication.translate("Form", u"A2 ip:", None))
        self.label_A2_ip.setText(QCoreApplication.translate("Form", u"TextLabel", None))
        self.label_12.setText(QCoreApplication.translate("Form", u"A2 MAC:", None))
        self.label_A2_MAC.setText(QCoreApplication.translate("Form", u"TextLabel", None))
    # retranslateUi

