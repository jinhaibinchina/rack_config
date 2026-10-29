# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'property_set.ui'
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
    QDialogButtonBox, QHBoxLayout, QLabel, QRadioButton,
    QSizePolicy, QSpinBox, QWidget)

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        if not Dialog.objectName():
            Dialog.setObjectName(u"Dialog")
        Dialog.resize(338, 193)
        self.buttonBox = QDialogButtonBox(Dialog)
        self.buttonBox.setObjectName(u"buttonBox")
        self.buttonBox.setGeometry(QRect(-40, 140, 341, 32))
        self.buttonBox.setOrientation(Qt.Horizontal)
        self.buttonBox.setStandardButtons(QDialogButtonBox.Cancel|QDialogButtonBox.Ok)
        self.checkBox_fill = QCheckBox(Dialog)
        self.checkBox_fill.setObjectName(u"checkBox_fill")
        self.checkBox_fill.setGeometry(QRect(260, 80, 80, 19))
        self.layoutWidget = QWidget(Dialog)
        self.layoutWidget.setObjectName(u"layoutWidget")
        self.layoutWidget.setGeometry(QRect(190, 40, 116, 23))
        self.horizontalLayout_3 = QHBoxLayout(self.layoutWidget)
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.horizontalLayout_3.setContentsMargins(0, 0, 0, 0)
        self.label_2 = QLabel(self.layoutWidget)
        self.label_2.setObjectName(u"label_2")

        self.horizontalLayout_3.addWidget(self.label_2)

        self.spinBox_fontSize = QSpinBox(self.layoutWidget)
        self.spinBox_fontSize.setObjectName(u"spinBox_fontSize")
        self.spinBox_fontSize.setMinimum(1)

        self.horizontalLayout_3.addWidget(self.spinBox_fontSize)

        self.widget = QWidget(Dialog)
        self.widget.setObjectName(u"widget")
        self.widget.setGeometry(QRect(40, 80, 201, 21))
        self.horizontalLayout = QHBoxLayout(self.widget)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.horizontalLayout.setContentsMargins(0, 0, 0, 0)
        self.radioButton_red = QRadioButton(self.widget)
        self.radioButton_red.setObjectName(u"radioButton_red")

        self.horizontalLayout.addWidget(self.radioButton_red)

        self.radioButton_green = QRadioButton(self.widget)
        self.radioButton_green.setObjectName(u"radioButton_green")

        self.horizontalLayout.addWidget(self.radioButton_green)

        self.radioButton_blue = QRadioButton(self.widget)
        self.radioButton_blue.setObjectName(u"radioButton_blue")

        self.horizontalLayout.addWidget(self.radioButton_blue)

        self.radioButton_yellow = QRadioButton(self.widget)
        self.radioButton_yellow.setObjectName(u"radioButton_yellow")

        self.horizontalLayout.addWidget(self.radioButton_yellow)

        self.radioButton_black = QRadioButton(self.widget)
        self.radioButton_black.setObjectName(u"radioButton_black")
        self.radioButton_black.setChecked(True)

        self.horizontalLayout.addWidget(self.radioButton_black)

        self.widget1 = QWidget(Dialog)
        self.widget1.setObjectName(u"widget1")
        self.widget1.setGeometry(QRect(40, 40, 134, 23))
        self.horizontalLayout_2 = QHBoxLayout(self.widget1)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.horizontalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(self.widget1)
        self.label.setObjectName(u"label")

        self.horizontalLayout_2.addWidget(self.label)

        self.spinBox_lineWidth = QSpinBox(self.widget1)
        self.spinBox_lineWidth.setObjectName(u"spinBox_lineWidth")
        self.spinBox_lineWidth.setMinimum(1)
        self.spinBox_lineWidth.setMaximum(10)

        self.horizontalLayout_2.addWidget(self.spinBox_lineWidth)


        self.retranslateUi(Dialog)
        self.buttonBox.accepted.connect(Dialog.accept)
        self.buttonBox.rejected.connect(Dialog.reject)

        QMetaObject.connectSlotsByName(Dialog)
    # setupUi

    def retranslateUi(self, Dialog):
        Dialog.setWindowTitle(QCoreApplication.translate("Dialog", u"\u5c5e\u6027\u8bbe\u7f6e", None))
        self.checkBox_fill.setText(QCoreApplication.translate("Dialog", u"\u586b\u5145", None))
        self.label_2.setText(QCoreApplication.translate("Dialog", u"\u5b57\u4f53\u5927\u5c0f\uff1a", None))
        self.radioButton_red.setText(QCoreApplication.translate("Dialog", u"\u7ea2", None))
        self.radioButton_green.setText(QCoreApplication.translate("Dialog", u"\u7eff", None))
        self.radioButton_blue.setText(QCoreApplication.translate("Dialog", u"\u84dd", None))
        self.radioButton_yellow.setText(QCoreApplication.translate("Dialog", u"\u9ec4", None))
        self.radioButton_black.setText(QCoreApplication.translate("Dialog", u"\u9ed1", None))
        self.label.setText(QCoreApplication.translate("Dialog", u"\u7ebf\u5bbd\uff1a", None))
    # retranslateUi

