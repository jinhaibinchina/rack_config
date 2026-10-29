# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'parames_set.ui'
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
from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QDialog,
    QDialogButtonBox, QSizePolicy, QWidget)

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        if not Dialog.objectName():
            Dialog.setObjectName(u"Dialog")
        Dialog.resize(384, 183+30)
        self.buttonBox = QDialogButtonBox(Dialog)
        self.buttonBox.setObjectName(u"buttonBox")
        self.buttonBox.setGeometry(QRect(20, 180, 341, 32))
        self.buttonBox.setOrientation(Qt.Horizontal)
        self.buttonBox.setStandardButtons(QDialogButtonBox.Cancel|QDialogButtonBox.Ok)
        self.checkBox_ask_bf_open_door = QCheckBox(Dialog)
        self.checkBox_ask_bf_open_door.setObjectName(u"checkBox_ask_bf_open_door")
        self.checkBox_ask_bf_open_door.setGeometry(QRect(60, 90, 221, 19))
        self.checkBox_enable_fire_signal = QCheckBox(Dialog)
        self.checkBox_enable_fire_signal.setObjectName(u"checkBox_enable_fire_signal")
        self.checkBox_enable_fire_signal.setGeometry(QRect(60, 60, 321, 19))
        self.checkBox_enable_estop_ext = QCheckBox(Dialog)
        self.checkBox_enable_estop_ext.setObjectName(u"checkBox_enable_estop_ext")
        self.checkBox_enable_estop_ext.setGeometry(QRect(60, 30, 221, 19))
        self.checkBox_disable_buzzer = QCheckBox(Dialog)
        self.checkBox_disable_buzzer.setObjectName(u"checkBox_disable_buzzer")
        self.checkBox_disable_buzzer.setGeometry(QRect(60, 120, 221, 19))
        self.checkBox_disable_worktable_canbit = QCheckBox(Dialog)
        self.checkBox_disable_worktable_canbit.setObjectName(u"checkBox_disable_worktable_canbit")
        self.checkBox_disable_worktable_canbit.setGeometry(QRect(60, 150, 221, 19))

        self.retranslateUi(Dialog)
        self.buttonBox.accepted.connect(Dialog.accept)
        self.buttonBox.rejected.connect(Dialog.reject)

        QMetaObject.connectSlotsByName(Dialog)
    # setupUi

    def retranslateUi(self, Dialog):
        Dialog.setWindowTitle(QCoreApplication.translate("Dialog", u"\u53c2\u6570\u8bbe\u7f6e", None))

        self.checkBox_ask_bf_open_door.setText('开门时需向平台申请，40011')
        self.checkBox_enable_fire_signal.setText('启用消防信号(接主柜DI0.4)，40001上报消防信号给WCS')
        self.checkBox_enable_estop_ext.setText('启用外部急停(接主柜DI0.5)')
        self.checkBox_disable_buzzer.setText('禁用蜂鸣器')
        self.checkBox_disable_worktable_canbit.setText('禁用主电柜IO模块')
    # retranslateUi

