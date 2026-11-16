from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                              QLabel, QTableWidget, QTableWidgetItem, QSplitter, QFrame,
                              QTabWidget, QTabBar, QMenuBar, QStatusBar, QDialog, QLineEdit,
                              QComboBox, QDialogButtonBox, QMenu,QSizePolicy,QCheckBox,QSpinBox,QSpacerItem, QStyle, QStyleOption, QProxyStyle)
from PySide6.QtCore import Qt, QTimer, QEvent, QSize,QRect,QPoint
from PySide6.QtGui import QFont, QPainter, QTransform, QAction, QRegularExpressionValidator, QPalette,QPen,QDoubleValidator,QIntValidator,QValidator

class battery(QWidget):
    def __init__(self):
        super().__init__()
      
        self.setMaximumHeight(25)
        self.setMinimumWidth(80)
        self._var=50
       
    def paintEvent(self, event):
        rect = self.rect()
        self.width=rect.width()
        self.height=rect.height()
        height_centre = self.height//2

        rect_battery = QRect(QPoint(1,1),QPoint(self.width-10,self.height-2))

        rect_battery_head =QRect(QPoint(self.width-9,height_centre-5),QPoint(self.width-5,height_centre+5))

        rect_battery_body = QRect(QPoint(2,2),QPoint((self.width-10)*self._var//100,self.height-3))

        painter = QPainter(self)

        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(Qt.GlobalColor.black, 1))
        
        painter.drawRoundedRect(rect_battery,3,3)
        
        painter.save()
        painter.setBrush(Qt.GlobalColor.black)
        
        painter.drawRect(rect_battery_head)
        painter.save()
        painter.setBrush(Qt.GlobalColor.green)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect_battery_body,3,3)
       
        painter.restore()

        
        painter.restore()
        painter.drawText(QPoint(self.width//2-10,height_centre+5),str(self._var)+"%")
        painter.end()

    @property
    def value(self):
        return self._var.get()
    
    @value.setter
    def value(self,val):
        if val>100:
            a=100
        elif val<0:
            a=0
        else:
            a=val
        self._var.set( a)
        self.update()

  


class VerticalLabel(QLabel):
    """竖向文本标签"""
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().windowText().color())
        
        # 设置固定字体大小
        font = QFont("Arial", 12, QFont.Bold)
        painter.setFont(font)
        
        # 计算文本所需空间
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(self.text())
        text_height = metrics.height()
        
        # 调整控件最小尺寸，确保不为负值
        min_width = max(text_height + 10, 1)
        min_height = max(text_width + 10, 1)
        self.setMinimumSize(min_width, min_height)
        
        # 坐标系变换
        transform = QTransform()
        transform.translate(self.width()/2, self.height()/2)  # 居中变换
        transform.rotate(-90)
        painter.setTransform(transform)
        
        # 计算文本绘制位置
        x = -text_width / 2
        y = text_height / 2 - metrics.descent()
        
        # 绘制文本
        painter.drawText(x, y, self.text())

class sys_checkbutton(QCheckBox):
    def __init__(self, parent=None,text="",color=Qt.black):
        super().__init__(parent,text=text)
        palette = self.palette()
        palette.setColor(QPalette.WindowText, color)  # 修改文字颜色
        self.setPalette(palette)
    @property 
    def value(self):
        return self.isChecked()
    
    @value.setter
    def value(self, state):
        self.setChecked(bool(state))

class my_text_value(QWidget):
    def __init__(self, parent=None, text=""):
        super().__init__(parent)
        self._text = text
        self._value ="###"

        self._setup_UI()
        self._set_style()
    def _setup_UI(self):
        layout =QHBoxLayout()
        layout.addWidget(QLabel(text=self._text))
        self.value_label = QLabel()
        self.value_label.setMinimumWidth(50)
        layout.addWidget(self.value_label,Qt.AlignmentFlag.AlignRight)
        self.setLayout(layout)
        self.value_label.setText(self._value)
    def _set_style(self):
        self.value_label.setStyleSheet("""QLabel {
                        border: 1px solid #4B4B50;
                        border-radius: 5px;        
                        padding: 3px;             
        }""")

    @property 
    def value(self):
        return self._value
    @value.setter
    def value(self, val):
        if type(val) is str:
            self._value = val
            self.value_label.setText(self._value)

class my_text_value_editable(QWidget):
    def __init__(self, parent=None, text="",NonInteractive=False):
        super().__init__(parent)
        self._text = text
        self._val = "###"
        self._setup_UI()
        if NonInteractive:
            self.value_editable.setReadOnly(True)  # 可选中/复制文本，但不可编辑
            # self.value_editable.setStyleSheet("background: white;")  # 保持白色背景（可选）
       

    def _setup_UI(self):
        layout =QHBoxLayout()
        layout.addWidget(QLabel(text=self._text))
        self.value_editable = QLineEdit()
        self.value_editable.setText(self._val)
        self.value_editable.setFixedWidth(60)
        layout.addWidget(self.value_editable,alignment=Qt.AlignmentFlag.AlignRight)
        self.setLayout(layout)

    def setValidator(self, arg__1: QValidator):
        self.value_editable.setValidator(arg__1)
    @property 
    def value(self):
        self._val=self.value_editable.text()
        return self._val
    @value.setter
    def value(self, val):
        if type(val) is str:
            self._val = val
            self.value_editable.setText(self._val)


class my_text_comboBox(QWidget):
    def __init__(self,*items, parent=None, text="",NonInteractive=False):
        super().__init__(parent)
        self._text = text
        self.combo = QComboBox()
        self.combo.setFixedWidth(100)
        for item in items:
            self.combo.addItem(item)
        self._setup_UI()
        if NonInteractive:
            # self.combo.setEditable(False)  # 禁止编辑（如果是可编辑的）
            self.combo.setEnabled(False)    # 保持可交互但不可修改
            

    def _setup_UI(self):
        layout =QHBoxLayout()
        layout.addWidget(QLabel(text=self._text))
        
        self.combo.setCurrentIndex(0)
     
        layout.addWidget(self.combo, alignment=Qt.AlignmentFlag.AlignRight)
        self.setLayout(layout)

   
    @property 
    def value(self):
      
        return self.combo.currentIndex()
    @value.setter
    def value(self, val):
        self.combo.setCurrentIndex(val)


class my_checkbutton(QWidget):
    def __init__(self, parent=None, text=""):
        super().__init__(parent)
        self._text = text
        self._checked = False
        self._enabled = False
        self.setMinimumSize(140, 30)
    
    def set_Enabled(self,val=True):
        self._enabled =val

    @property 
    def value(self):
        return self._checked
    
    @value.setter
    def value(self, state):
        self._checked = bool(state)
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.rect()
        
        # 绘制文字（左对齐）
        font = painter.font()
        font.setPointSize(10)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(self._text)
        text_height = metrics.height()

        text_rect = QRect(
            5,  # 左边距5像素
            rect.center().y() - text_height//2,
            text_width,
            text_height
        )
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, self._text)
        
        # 绘制正方形（右对齐）
        square_size = min(rect.height() - 4, 20)
        square_size_1 = int(square_size/1.5)
      
        x= rect.right() - square_size - 2
        y= rect.center().y() - square_size//2

        centre_x = x +square_size//2
        centre_y = y +square_size//2

        x1=centre_x - square_size_1//2
        y1=centre_y - square_size_1//2

        square_rect = QRect(
            x,
            y,
            square_size,
            square_size
        )

        square_rect_selected = QRect(
            x1,
            y1,
            square_size_1,
            square_size_1
        )

        # 绘制正方形边框
        painter.setPen(Qt.black)
        painter.drawRect(square_rect)
        
        # 如果选中则填充正方形
        if self._checked:
            painter.fillRect(square_rect_selected, Qt.black)
            
    def mousePressEvent(self, event):
        if self._enabled:
            self._checked = not self._checked
            self.update()
        super().mousePressEvent(event)

class label_checkbutton_out(QWidget):
    def __init__(self, parent=None,text="备用",size=120):
        super().__init__(parent)
        self._size = size
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.label = QLabel(text=text)
        self.chk_btn = QCheckBox()
        self.chk_btn.setEnabled(False)
        
        self.chk_btn.setFixedSize(150,150)
        layout.addWidget(self.label)
        layout.addWidget(self.chk_btn)
       
        
        # 应用初始size
        self.setMinimumSize(size, size)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    @property 
    def value(self):
        return self.chk_btn.isChecked()
    
    @value.setter
    def value(self, state):
        self.chk_btn.setChecked(bool(state))
        
    @property
    def size(self):
        return self._size
        
    @size.setter
    def size(self, value):
        self._size = value
        self.setMinimumSize(value, value)
        self.updateGeometry()


class my_button(QPushButton):
    def __init__(self, parent=None,text="备用",size=120):
        super().__init__(parent,text=text)

    

import sys
if __name__ == "__main__":
    app = QApplication(sys.argv)
    # cb = my_checkbutton(text="测试复选框")
    # cb.set_Enabled()
    # cb.value=True
    cb = battery()
    window = QWidget()
    window.setFixedSize(200,200)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0,0,0,0)
    layout.addWidget(cb)
    window.show()
    sys.exit(app.exec())
