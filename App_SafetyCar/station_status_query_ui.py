# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'station_status_query.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QGroupBox,
    QHBoxLayout, QLabel, QSizePolicy, QSpacerItem,
    QVBoxLayout, QWidget)

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        if not Dialog.objectName():
            Dialog.setObjectName(u"Dialog")
        Dialog.resize(588, 396)
        Dialog.setCursor(QCursor(Qt.CrossCursor))
        self.label_6 = QLabel(Dialog)
        self.label_6.setObjectName(u"label_6")
        self.label_6.setGeometry(QRect(270, 370, 262, 15))
        self.layoutWidget = QWidget(Dialog)
        self.layoutWidget.setObjectName(u"layoutWidget")
        self.layoutWidget.setGeometry(QRect(60, 40, 471, 321))
        self.horizontalLayout_22 = QHBoxLayout(self.layoutWidget)
        self.horizontalLayout_22.setObjectName(u"horizontalLayout_22")
        self.horizontalLayout_22.setContentsMargins(0, 0, 0, 0)
        self.groupBox = QGroupBox(self.layoutWidget)
        self.groupBox.setObjectName(u"groupBox")
        self.verticalLayout = QVBoxLayout(self.groupBox)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.horizontalLayout_4 = QHBoxLayout()
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.label_3 = QLabel(self.groupBox)
        self.label_3.setObjectName(u"label_3")

        self.horizontalLayout_4.addWidget(self.label_3)

        self.label_PLC_status = QLabel(self.groupBox)
        self.label_PLC_status.setObjectName(u"label_PLC_status")

        self.horizontalLayout_4.addWidget(self.label_PLC_status)


        self.verticalLayout.addLayout(self.horizontalLayout_4)

        self.verticalSpacer = QSpacerItem(20, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.verticalLayout.addItem(self.verticalSpacer)

        self.horizontalLayout_3 = QHBoxLayout()
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.label_4 = QLabel(self.groupBox)
        self.label_4.setObjectName(u"label_4")

        self.horizontalLayout_3.addWidget(self.label_4)

        self.label_PLC_fault_status = QLabel(self.groupBox)
        self.label_PLC_fault_status.setObjectName(u"label_PLC_fault_status")

        self.horizontalLayout_3.addWidget(self.label_PLC_fault_status)


        self.verticalLayout.addLayout(self.horizontalLayout_3)

        self.verticalSpacer_2 = QSpacerItem(20, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.verticalLayout.addItem(self.verticalSpacer_2)

        self.horizontalLayout_2 = QHBoxLayout()
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.label_5 = QLabel(self.groupBox)
        self.label_5.setObjectName(u"label_5")

        self.horizontalLayout_2.addWidget(self.label_5)

        self.label_controller_mode = QLabel(self.groupBox)
        self.label_controller_mode.setObjectName(u"label_controller_mode")

        self.horizontalLayout_2.addWidget(self.label_controller_mode)


        self.verticalLayout.addLayout(self.horizontalLayout_2)

        self.verticalSpacer_22 = QSpacerItem(20, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.verticalLayout.addItem(self.verticalSpacer_22)

        self.horizontalLayout_23 = QHBoxLayout()
        self.horizontalLayout_23.setObjectName(u"horizontalLayout_23")
        self.label_7 = QLabel(self.groupBox)
        self.label_7.setObjectName(u"label_7")

        self.horizontalLayout_23.addWidget(self.label_7)

        self.label_controller_status = QLabel(self.groupBox)
        self.label_controller_status.setObjectName(u"label_controller_status")

        self.horizontalLayout_23.addWidget(self.label_controller_status)


        self.verticalLayout.addLayout(self.horizontalLayout_23)

        self.verticalSpacer_4 = QSpacerItem(20, 135, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout.addItem(self.verticalSpacer_4)


        self.horizontalLayout_22.addWidget(self.groupBox)

        self.groupBox_3 = QGroupBox(self.layoutWidget)
        self.groupBox_3.setObjectName(u"groupBox_3")
        self.verticalLayout_2 = QVBoxLayout(self.groupBox_3)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.label = QLabel(self.groupBox_3)
        self.label.setObjectName(u"label")

        self.horizontalLayout.addWidget(self.label)

        self.comboBox_station_select = QComboBox(self.groupBox_3)
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.addItem("")
        self.comboBox_station_select.setObjectName(u"comboBox_station_select")

        self.horizontalLayout.addWidget(self.comboBox_station_select)


        self.verticalLayout_2.addLayout(self.horizontalLayout)

        self.verticalSpacer_3 = QSpacerItem(20, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.verticalLayout_2.addItem(self.verticalSpacer_3)

        self.horizontalLayout_5 = QHBoxLayout()
        self.horizontalLayout_5.setObjectName(u"horizontalLayout_5")
        self.label_2 = QLabel(self.groupBox_3)
        self.label_2.setObjectName(u"label_2")

        self.horizontalLayout_5.addWidget(self.label_2)

        self.label_status = QLabel(self.groupBox_3)
        self.label_status.setObjectName(u"label_status")

        self.horizontalLayout_5.addWidget(self.label_status)


        self.verticalLayout_2.addLayout(self.horizontalLayout_5)

        self.verticalSpacer_5 = QSpacerItem(20, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.verticalLayout_2.addItem(self.verticalSpacer_5)

        self.horizontalLayout_6 = QHBoxLayout()
        self.horizontalLayout_6.setObjectName(u"horizontalLayout_6")
        self.label_9 = QLabel(self.groupBox_3)
        self.label_9.setObjectName(u"label_9")

        self.horizontalLayout_6.addWidget(self.label_9)

        self.label_errcode = QLabel(self.groupBox_3)
        self.label_errcode.setObjectName(u"label_errcode")

        self.horizontalLayout_6.addWidget(self.label_errcode)


        self.verticalLayout_2.addLayout(self.horizontalLayout_6)

        self.verticalSpacer_6 = QSpacerItem(20, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.verticalLayout_2.addItem(self.verticalSpacer_6)

        self.horizontalLayout_7 = QHBoxLayout()
        self.horizontalLayout_7.setObjectName(u"horizontalLayout_7")
        self.label_10 = QLabel(self.groupBox_3)
        self.label_10.setObjectName(u"label_10")

        self.horizontalLayout_7.addWidget(self.label_10)

        self.label_errinfo = QLabel(self.groupBox_3)
        self.label_errinfo.setObjectName(u"label_errinfo")

        self.horizontalLayout_7.addWidget(self.label_errinfo)


        self.verticalLayout_2.addLayout(self.horizontalLayout_7)

        self.verticalSpacer_7 = QSpacerItem(20, 126, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_2.addItem(self.verticalSpacer_7)


        self.horizontalLayout_22.addWidget(self.groupBox_3)


        self.retranslateUi(Dialog)

        QMetaObject.connectSlotsByName(Dialog)
    # setupUi

    def retranslateUi(self, Dialog):
        Dialog.setWindowTitle(QCoreApplication.translate("Dialog", u"\u72b6\u6001\u67e5\u8be2", None))
        self.label_6.setText(QCoreApplication.translate("Dialog", u"tips:\u6545\u969c\u4fe1\u606f\u8be6\u89c1\u300a1756-rm003_-zh-p\u6307\u4ee4\u96c6\u300b", None))
        self.groupBox.setTitle(QCoreApplication.translate("Dialog", u"PLC", None))
        self.label_3.setText(QCoreApplication.translate("Dialog", u"\u8bbe\u5907\u72b6\u6001\uff1a", None))
        self.label_PLC_status.setText(QCoreApplication.translate("Dialog", u"TextLabel", None))
        self.label_4.setText(QCoreApplication.translate("Dialog", u"\u6545\u969c\u72b6\u6001\uff1a", None))
        self.label_PLC_fault_status.setText(QCoreApplication.translate("Dialog", u"TextLabel", None))
        self.label_5.setText(QCoreApplication.translate("Dialog", u"\u63a7\u5236\u5668\u6a21\u5f0f\uff1a", None))
        self.label_controller_mode.setText(QCoreApplication.translate("Dialog", u"TextLabel", None))
        self.label_7.setText(QCoreApplication.translate("Dialog", u"\u63a7\u5236\u5668\u72b6\u6001\uff1a", None))
        self.label_controller_status.setText(QCoreApplication.translate("Dialog", u"TextLabel", None))
        self.groupBox_3.setTitle(QCoreApplication.translate("Dialog", u"\u4ece\u7ad9\u72b6\u6001\u67e5\u8be2", None))
        self.label.setText(QCoreApplication.translate("Dialog", u"\u7ad9\u70b9\u9009\u62e9\uff1a", None))
        self.comboBox_station_select.setItemText(0, QCoreApplication.translate("Dialog", u"\u672a\u9009\u62e9", None))
        self.comboBox_station_select.setItemText(1, QCoreApplication.translate("Dialog", u"1#\u7ef4\u4fee\u533a/\u5b89\u5168\u95e8", None))
        self.comboBox_station_select.setItemText(2, QCoreApplication.translate("Dialog", u"2#\u7ef4\u4fee\u533a/\u5b89\u5168\u95e8", None))
        self.comboBox_station_select.setItemText(3, QCoreApplication.translate("Dialog", u"3#\u7ef4\u4fee\u533a/\u5b89\u5168\u95e8", None))
        self.comboBox_station_select.setItemText(4, QCoreApplication.translate("Dialog", u"4#\u7ef4\u4fee\u533a/\u5b89\u5168\u95e8", None))
        self.comboBox_station_select.setItemText(5, QCoreApplication.translate("Dialog", u"1#\u4e0a\u67b6X4", None))
        self.comboBox_station_select.setItemText(6, QCoreApplication.translate("Dialog", u"2#\u4e0a\u67b6X4", None))
        self.comboBox_station_select.setItemText(7, QCoreApplication.translate("Dialog", u"3#\u4e0a\u67b6X4", None))
        self.comboBox_station_select.setItemText(8, QCoreApplication.translate("Dialog", u"4#\u4e0a\u67b6X4", None))
        self.comboBox_station_select.setItemText(9, QCoreApplication.translate("Dialog", u"5#\u4e0a\u67b6X4", None))
        self.comboBox_station_select.setItemText(10, QCoreApplication.translate("Dialog", u"6#\u4e0a\u67b6X4", None))
        self.comboBox_station_select.setItemText(11, QCoreApplication.translate("Dialog", u"7#\u4e0a\u67b6X4", None))
        self.comboBox_station_select.setItemText(12, QCoreApplication.translate("Dialog", u"8#\u4e0a\u67b6X4", None))
        self.comboBox_station_select.setItemText(13, QCoreApplication.translate("Dialog", u"9#\u4e0a\u67b6X4", None))
        self.comboBox_station_select.setItemText(14, QCoreApplication.translate("Dialog", u"1#\u62e3\u9009X4", None))
        self.comboBox_station_select.setItemText(15, QCoreApplication.translate("Dialog", u"2#\u62e3\u9009X4", None))
        self.comboBox_station_select.setItemText(16, QCoreApplication.translate("Dialog", u"3#\u62e3\u9009X4", None))
        self.comboBox_station_select.setItemText(17, QCoreApplication.translate("Dialog", u"4#\u62e3\u9009X4", None))
        self.comboBox_station_select.setItemText(18, QCoreApplication.translate("Dialog", u"5#\u62e3\u9009X4", None))
        self.comboBox_station_select.setItemText(19, QCoreApplication.translate("Dialog", u"6#\u62e3\u9009X4", None))
        self.comboBox_station_select.setItemText(20, QCoreApplication.translate("Dialog", u"7#\u62e3\u9009X4", None))
        self.comboBox_station_select.setItemText(21, QCoreApplication.translate("Dialog", u"8#\u62e3\u9009X4", None))
        self.comboBox_station_select.setItemText(22, QCoreApplication.translate("Dialog", u"9#\u62e3\u9009X4", None))
        self.comboBox_station_select.setItemText(23, QCoreApplication.translate("Dialog", u"1#\u5b89\u5168\u95e8X1", None))
        self.comboBox_station_select.setItemText(24, QCoreApplication.translate("Dialog", u"2#\u5b89\u5168\u95e8X1", None))
        self.comboBox_station_select.setItemText(25, QCoreApplication.translate("Dialog", u"3#\u5b89\u5168\u95e8X1", None))
        self.comboBox_station_select.setItemText(26, QCoreApplication.translate("Dialog", u"4#\u5b89\u5168\u95e8X1", None))
        self.comboBox_station_select.setItemText(27, QCoreApplication.translate("Dialog", u"5#\u5b89\u5168\u95e8X1", None))
        self.comboBox_station_select.setItemText(28, QCoreApplication.translate("Dialog", u"6#\u5b89\u5168\u95e8X1", None))
        self.comboBox_station_select.setItemText(29, QCoreApplication.translate("Dialog", u"7#\u5b89\u5168\u95e8X1", None))
        self.comboBox_station_select.setItemText(30, QCoreApplication.translate("Dialog", u"8#\u5b89\u5168\u95e8X1", None))
        self.comboBox_station_select.setItemText(31, QCoreApplication.translate("Dialog", u"9#\u5b89\u5168\u95e8X1", None))
        self.comboBox_station_select.setItemText(32, QCoreApplication.translate("Dialog", u"1#\u8f93\u9001\u7ebfX2", None))
        self.comboBox_station_select.setItemText(33, QCoreApplication.translate("Dialog", u"2#\u8f93\u9001\u7ebfX2", None))
        self.comboBox_station_select.setItemText(34, QCoreApplication.translate("Dialog", u"3#\u8f93\u9001\u7ebfX2", None))
        self.comboBox_station_select.setItemText(35, QCoreApplication.translate("Dialog", u"4#\u8f93\u9001\u7ebfX2", None))
        self.comboBox_station_select.setItemText(36, QCoreApplication.translate("Dialog", u"1#Q1P\u62e3\u9009/Q3P\u62e3\u9009", None))
        self.comboBox_station_select.setItemText(37, QCoreApplication.translate("Dialog", u"2#Q1P\u62e3\u9009/Q3P\u62e3\u9009", None))
        self.comboBox_station_select.setItemText(38, QCoreApplication.translate("Dialog", u"3#Q1P\u62e3\u9009/Q3P\u62e3\u9009", None))
        self.comboBox_station_select.setItemText(39, QCoreApplication.translate("Dialog", u"4#Q1P\u62e3\u9009/Q3P\u62e3\u9009", None))
        self.comboBox_station_select.setItemText(40, QCoreApplication.translate("Dialog", u"5#Q1P\u62e3\u9009/Q3P\u62e3\u9009", None))
        self.comboBox_station_select.setItemText(41, QCoreApplication.translate("Dialog", u"6#Q1P\u62e3\u9009/Q3P\u62e3\u9009", None))
        self.comboBox_station_select.setItemText(42, QCoreApplication.translate("Dialog", u"7#Q1P\u62e3\u9009/Q3P\u62e3\u9009", None))
        self.comboBox_station_select.setItemText(43, QCoreApplication.translate("Dialog", u"8#Q1P\u62e3\u9009/Q3P\u62e3\u9009", None))
        self.comboBox_station_select.setItemText(44, QCoreApplication.translate("Dialog", u"9#Q1P\u62e3\u9009/Q3P\u62e3\u9009", None))
        self.comboBox_station_select.setItemText(45, QCoreApplication.translate("Dialog", u"1#Q3P\u6258\u76d8X2", None))
        self.comboBox_station_select.setItemText(46, QCoreApplication.translate("Dialog", u"2#Q3P\u6258\u76d8X2", None))
        self.comboBox_station_select.setItemText(47, QCoreApplication.translate("Dialog", u"3#Q3P\u6258\u76d8X2", None))
        self.comboBox_station_select.setItemText(48, QCoreApplication.translate("Dialog", u"4#Q3P\u6258\u76d8X2", None))
        self.comboBox_station_select.setItemText(49, QCoreApplication.translate("Dialog", u"\u4e3b\u67dc\u8fdc\u7a0bIO", None))
        self.comboBox_station_select.setItemText(50, QCoreApplication.translate("Dialog", u"\u4ecePLC", None))

        self.label_2.setText(QCoreApplication.translate("Dialog", u"\u72b6\u6001\uff1a", None))
        self.label_status.setText(QCoreApplication.translate("Dialog", u"TextLabel", None))
        self.label_9.setText(QCoreApplication.translate("Dialog", u"\u6545\u969c\u7801\uff1a", None))
        self.label_errcode.setText(QCoreApplication.translate("Dialog", u"TextLabel", None))
        self.label_10.setText(QCoreApplication.translate("Dialog", u"\u6545\u969c\u4fe1\u606f\uff1a", None))
        self.label_errinfo.setText(QCoreApplication.translate("Dialog", u"TextLabel", None))
    # retranslateUi

