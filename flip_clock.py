from PySide6.QtWidgets import QWidget, QApplication, QLabel,QVBoxLayout,QHBoxLayout,QMainWindow,QPushButton
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QRect, QPoint, QEasingCurve,Signal
from PySide6.QtGui import QPainter, QColor, QFont, QLinearGradient, QPen,QFontMetrics
from PySide6.QtCore import Property

import time
import sys
from math import sin,cos,pi

class FlipDigit_top(QWidget):
    animation_done =Signal()
    def __init__(self, parent=None, width=280, height=180, bg=QColor(30,30,30), text_color=QColor(255,255,255), **kwargs):
        super().__init__(parent)
        self.width = width
        self.height = height
        self.bg = bg
        self.text_color = text_color
        self.current_value = 0
        self.next_value = 1
        self.is_animating = False
        self.is_animating_bottom = False
        self._animation_progress = 0
        self.max_value =9
        self.text = str(self.current_value)
       
        self.setFixedSize(width, height)
        self.scale =1.0
        
        for key, value in kwargs.items():
            if key!= "max_value":
                return
            if value>=0 and value<=9:
                self.max_value = value
    def set_max_value(self,value):
        if value>=0 and value<=9:
                self.max_value = value
    # 添加属性声明
    def get_animation_progress(self):
        return self._animation_progress

    def set_animation_progress(self, value):
        self._animation_progress = value
        self.update()  # 值变化时触发重绘

    animation_progress = Property(int, get_animation_progress, set_animation_progress)

    def showEvent(self, event):
        super().showEvent(event)
        
        # self.width = self.rect().width()
        # self.height = self.rect().height()
        # self.font = QFont("Arial", int(self.width*1.0))
        # self.font.setBold(True)
    def set_value(self, value):
        if value != self.current_value and not self.is_animating:
            self.next_value = value
            self.start_animation()

    def handle_bottom_done(self):
        self.is_animating_bottom = False

    def flip(self):
        """触发翻页动画"""
        if self.is_animating or self.is_animating_bottom:
            return
        # self.next_value = (self.current_value + 1) % 10 
        self.next_value = (self.current_value + 1) % (self.max_value+1)
        # 开始动画
        self.start_animation()

    def start_animation(self):
        self.is_animating = True
        self._animation_progress = 0
        self.animation = QPropertyAnimation(self, b"animation_progress")
        self.animation.setDuration(250)
        self.animation.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.animation.setStartValue(0)
        self.animation.setEndValue(100)
        self.animation.valueChanged.connect(self.update)
        self.animation.finished.connect(self.animation_finished)
        self.animation.start()
        
    def animation_finished(self):
        self.current_value = self.next_value
        self.is_animating = False
        self._animation_progress = 0
        self.scale =1.0
        self.update()
        self.animation_done.emit()
        self.is_animating_bottom = True
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 绘制背景
        painter.fillRect(self.rect(), self.bg)
        
        # 设置大号字体
        font = QFont("Arial", 250)  # 使用固定大字号
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self.text_color)
        
        # # 计算文字metrics
        metrics = QFontMetrics(font)
       
        text_width = metrics.horizontalAdvance("0")
        
        text_height =self.height-20 if self.height>40 else self.height
        a = 20 if self.height>40 else 0
       
        text = str(self.next_value)
        # painter.drawText(QRect(0,b,self.width, text_height), text,Qt.AlignmentFlag.AlignCenter)
        self.draw_number_fill_height(painter,QRect(0,a,self.width, text_height*2),text)

        # 绘制背景
        painter.fillRect(QRect(0,self.height -int((text_height+a)*self.scale),self.width, self.height), self.bg)
        # painter.drawText(x, y, text)
        # 应用视图变换
        painter.translate(QPoint(0,self.height))

        painter.scale(1.0, self.scale)

        
        text = str(self.current_value)
        # painter.drawText(QRect(0,a,self.width, text_height*inv_scale), text,Qt.AlignmentFlag.AlignCenter)
        self.draw_number_fill_height(painter,QRect(0,-text_height,self.width, text_height*2),text)

        if self.is_animating:
            progress = self._animation_progress 
            # 绘制翻页效果
            x= (progress)/100.0
            self.scale=cos(pi/2.0*x)
          
            # self.scale= (100-progress)/100.0
    
    def draw_number_fill_height(self,painter, rect:QRect, number_str):
        font = painter.font()
        metrics = painter.fontMetrics()
        
        # 计算最佳字体大小
        target_height = rect.height()
        if not hasattr(self,"font_size"):
            setattr(self,"font_size",10)
        # self.font_size = 10
        
        # 数字特有的高度计算（忽略descent）
        while True:
            font.setPointSize(self.font_size)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            
            # 只考虑ascent部分
            if metrics.ascent()-metrics.descent() >= target_height:
                break
                
            self.font_size += 1
            if self.font_size > 500:
                break
        
        # 微调确保不超出
        while metrics.ascent()-metrics.descent() > target_height and self.font_size > 1:
            self.font_size -= 1
            font.setPointSize(self.font_size)
            painter.setFont(font)
            metrics = painter.fontMetrics()
        
       
        # 数字定位：基线在容器底部
        text_width = metrics.horizontalAdvance(number_str)
        x = (rect.width() - text_width) // 2+rect.left()
        y = rect.height() +rect.top()# 基线在容器底部
        
        painter.drawText(QPoint(int(x), int(y)), number_str)
            
class FlipDigit_bottom(QWidget):
    animation_done =Signal()
    def __init__(self, parent=None, width=280, height=180, bg=QColor(30,30,30), text_color=QColor(255,255,255), **kwargs):
        super().__init__(parent)
        self.width = width
        self.height = height
        self.bg = bg
        self.text_color = text_color
        self.current_value = 0
        self.next_value = 1
        self.is_animating = False
        self._animation_progress = 0
        self.text = str(self.current_value)
        self.max_value =9
        self.setFixedSize(width, height)
        self.scale =0.0
        for key, value in kwargs.items():
            if key!= "max_value":
                return
            if value>=0 and value<=9:
                self.max_value = value
                print(f'设置了最大值{self.max_value}')
    def set_max_value(self,value):
        if value>=0 and value<=9:
                self.max_value = value
                


    # 添加属性声明
    def get_animation_progress(self):
        return self._animation_progress

    def set_animation_progress(self, value):
        self._animation_progress = value
        self.update()  # 值变化时触发重绘

    animation_progress = Property(int, get_animation_progress, set_animation_progress)

    def showEvent(self, event):
        super().showEvent(event)
        
       
    def set_value(self, value):
        if value != self.current_value and not self.is_animating:
            self.next_value = value
            self.start_animation()
    
    def flip(self):
        """触发翻页动画"""
        if self.is_animating:
            return
        # self.next_value = (self.current_value + 1) % 10 
        self.next_value = (self.current_value + 1) % (self.max_value+1)
        # 开始动画
        self.start_animation()

    def start_animation(self):
        self.is_animating = True
        self._animation_progress = 0
        self.animation = QPropertyAnimation(self, b"animation_progress")
        self.animation.setDuration(250)
        self.animation.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.animation.setStartValue(0)
        self.animation.setEndValue(100)
        self.animation.valueChanged.connect(self.update)
        self.animation.finished.connect(self.animation_finished)
        self.animation.start()
        
    def animation_finished(self):
        self.current_value = self.next_value
        self.is_animating = False
        self._animation_progress = 0
        self.scale =0.0
        self.update()
        self.animation_done.emit()
        
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 绘制背景
        painter.fillRect(self.rect(), self.bg)
        
        # 设置大号字体
        font = QFont("Arial", 250)  # 使用固定大字号
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self.text_color)
        
       
        text_height =self.height-20 if self.height>40 else self.height
        a = 20 if self.height>40 else 0
        
        text = str(self.current_value)
        # painter.drawText(QRect(0,-text_height//2,self.width, text_height), text,Qt.AlignmentFlag.AlignCenter)
        self.draw_number_fill_height(painter,QRect(0,-text_height,self.width, text_height*2),text)
        # painter.drawRect(QRect(0,0,self.width, text_height))
        # 绘制背景
        painter.fillRect(QRect(0,0,self.width, int((self.height)*self.scale)), self.bg)

        # painter.drawText(x, y, text)
        # 应用视图变换
        painter.translate(QPoint(0,0))

        painter.scale(1.0, self.scale)
        
        text = str(self.next_value)
        # painter.drawText(QRect(0,-text_height//2,self.width, text_height*self.scale), text,Qt.AlignmentFlag.AlignCenter)
        self.draw_number_fill_height(painter,QRect(0,-text_height,self.width, text_height*2),text)

        if self.is_animating:
            progress = self._animation_progress 
            # if progress==0:
            #     return
            # 绘制翻页效果
            x= (progress)/100.0
            self.scale=sin(pi/2.0*x)
            # self.scale= (progress)/100.0
    
    def draw_number_fill_height(self,painter, rect:QRect, number_str):
        font = painter.font()
        metrics = painter.fontMetrics()
        
        # 计算最佳字体大小
        target_height = rect.height()
        if not hasattr(self,"font_size"):
            setattr(self,"font_size",10)
        # self.font_size = 10
        
        # 数字特有的高度计算（忽略descent）
        while True:
            font.setPointSize(self.font_size)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            
            # 只考虑ascent部分
            if metrics.ascent()-metrics.descent() >= target_height:
                break
                
            self.font_size += 1
            if self.font_size > 500:
                break
        
        # 微调确保不超出
        while metrics.ascent()-metrics.descent() > target_height and self.font_size > 1:
            self.font_size -= 1
            font.setPointSize(self.font_size)
            painter.setFont(font)
            metrics = painter.fontMetrics()
        
       
        # 数字定位：基线在容器底部
        text_width = metrics.horizontalAdvance(number_str)
        x = (rect.width() - text_width) // 2+rect.left()
        y = rect.height() +rect.top()# 基线在容器底部
        
        painter.drawText(QPoint(int(x), int(y)), number_str)
                
            
class FlipDigit(QWidget):
    def __init__(self, parent=None,size_factor=1.0, bg="black", **kwargs):
        super().__init__(parent)
        if 0.05<=size_factor<=1.0:
            self.factor = size_factor
        else:
            self.factor =0.5
        self.base_width =280
        self.base_height = 190*2
        width =int(self.base_width*self.factor)
        height=int((self.base_height//2)*self.factor)
        self.setFixedSize(width, height*2+2)  if size_factor>0.1 else self.setFixedSize(width, height*2+1)
        layout =QVBoxLayout()
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(2) if size_factor>0.1 else layout.setSpacing(1)
        self.bottom_digit =FlipDigit_bottom(width=width,height=height,bg=bg, **kwargs)
        self.top_digit = FlipDigit_top(width=width,height=height,bg=bg, **kwargs)
        layout.addWidget(self.top_digit)
        layout.addWidget(self.bottom_digit)
        self.setLayout(layout)
        self.top_digit.animation_done.connect(self.bottom_digit.flip)
        self.bottom_digit.animation_done.connect(self.top_digit.handle_bottom_done)

    def flip(self):
        self.top_digit.flip()
       

    def set_max_value(self,value):
        if value>=0 and value<=9:
                self.bottom_digit.set_max_value(value) 
                self.top_digit.set_max_value(value) 

class FlipDigit_Time_display(QWidget):
    
    # def __init__(self, parent=None, bg="black",size_factor=1.0):
    def __init__(self, parent=None, bg=QColor(218,218,218),size_factor=1.0):
        super().__init__(parent)
       
        if bg == "#F0F0F0":
            _bg ="#F0F0F0"
            _text_color = "black"
        else:
            _bg ="black"
            _text_color ="white"
        
        _bg =QColor(218,218,218)
        # 创建时间分隔符（冒号）
       
        # 初始化数字组件
        self.digits = {
            'h1': FlipDigit(self,max_value=2,bg=_bg,size_factor=size_factor),  # 小时十位  
            'h2': FlipDigit(self,max_value=9,bg=_bg,size_factor=size_factor),  # 小时个位 dync  max_value
            'm1': FlipDigit(self,max_value=5,bg=_bg,size_factor=size_factor),  # 分钟十位
            'm2': FlipDigit(self,max_value=9,bg=_bg,size_factor=size_factor),  # 分钟个位
            's1': FlipDigit(self,max_value=5,bg=_bg,size_factor=size_factor),  # 秒十位
            's2': FlipDigit(self,max_value=9,bg=_bg,size_factor=size_factor)   # 秒个位
        }
        layout = QHBoxLayout()

        layout.setSpacing(2) 
        for name in self.digits.keys():
            layout.addWidget( self.digits[name])
        
        self.setLayout(layout)
        
        # 初始化时间
        self.last_time = ("00", "00", "00")
        # self.timer.start(200)
        if size_factor>0.8:
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.update_time)  
            self.timer.start(200)  
    def get_time_parts(self):
        """获取当前时间并分解为各个数字位"""
        now = time.strftime("%H:%M:%S")
        hours, minutes, seconds = now.split(":")

        # current_time = QTime.currentTime()
        # current_time.
        return [
            hours[0], hours[1], 
            minutes[0], minutes[1], 
            seconds[0], seconds[1]]
    
    
    def update_time(self):
        """更新时间显示"""
        new_time = self.get_time_parts()
      
        current_digits = ['h1', 'h2', 'm1', 'm2', 's1', 's2']
        
        for name, new_val in zip(current_digits, new_time):
            if self.digits['h1'].top_digit.current_value==2:
                self.digits['h2'].set_max_value(3)
            else:
                self.digits['h2'].set_max_value(9)
            current_val = self.digits[name].top_digit.current_value
            if int(new_val) != current_val:
                self.digits[name].flip()
        
    def get_time_parts_by_plc(self,now):
        """把 PLC 时间字符串 "HH:MM:SS" 分解成 6 个数字位。

        兼容以下情况（返回 None 表示无法解析，调用方应保持原显示）：
          * 空值 / None
          * 段数不足（如 "12:30"）或过多
          * 时分秒不是两位数字（如 "1:2:3"、"':'"、乱码）
          * 数值越界（时 > 23、分/秒 > 59）
        """
        parts = self.parse_plc_time(now)
        if parts is None:
            return None
        hours, minutes, seconds = parts
        return [
            hours[0], hours[1],
            minutes[0], minutes[1],
            seconds[0], seconds[1]]

    @staticmethod
    def parse_plc_time(now):
        """解析 "HH:MM:SS"，成功返回 ("HH","MM","SS")，失败返回 None。"""
        if now is None:
            return None
        if isinstance(now, (bytes, bytearray)):
            now = now.decode("ascii", errors="ignore")
        text = str(now).strip()
        # 去掉 PLC 字符串里可能残留的空字节与非法字符
        text = text.replace("\x00", "").strip()
        if not text:
            return None
        fields = text.split(":")
        if len(fields) != 3:
            return None
        if not all(len(f) == 2 and f.isdigit() for f in fields):
            return None
        hours, minutes, seconds = fields
        if int(hours) > 23 or int(minutes) > 59 or int(seconds) > 59:
            return None
        return hours, minutes, seconds

    def update_time_by_plc(self,time_h_m_s):
        """更新时间显示；PLC 时间非法时保持当前显示不变。"""
        new_time = self.get_time_parts_by_plc(time_h_m_s)
        if new_time is None:
            return False

        current_digits = ['h1', 'h2', 'm1', 'm2', 's1', 's2']

        for name, new_val in zip(current_digits, new_time):
            if self.digits['h1'].top_digit.current_value==2:
                self.digits['h2'].set_max_value(3)
            else:
                self.digits['h2'].set_max_value(9)
            current_val = self.digits[name].top_digit.current_value
            if int(new_val) != current_val:
                self.digits[name].flip()
        return True


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("test")
        self.resize(800, 800)
    
        self.test_window = FlipDigit_Time_display(size_factor=0.9)
        
        self.setCentralWidget(self.test_window)
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_A:
            print("A键被按下")
        elif event.key() == Qt.Key_Space:
            self.test_window.update_time()
        elif event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)  # 调用父类处理其他按键

if __name__ == "__main__":
    app = QApplication([])
    window = MainWindow()
    window.show()
    
    window.move(100, 100)  # 确保窗口显示在可见位置
    window.showMaximized()
    app.exec()
