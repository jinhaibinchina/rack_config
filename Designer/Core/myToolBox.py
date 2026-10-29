import sys
from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QLabel, QFrame, 
    QHBoxLayout, QLineEdit, QCheckBox, QRadioButton, QComboBox, 
    QSlider, QProgressBar, QMenu, QSizePolicy
)
from PySide6.QtCore import Qt, QByteArray, QPoint, QEvent, QMimeData
from PySide6.QtGui import QDrag, QPainter, QPixmap, QPainterPath


class ToolButton(QPushButton):
    def __init__(self, tool_name, parent=None):
        super().__init__(tool_name, parent)
        self.m_toolName = tool_name
        self.setMinimumSize(80, 40)
        self.setAcceptDrops(False)  # 按钮本身不接受拖拽
        # 设置样式，让按钮看起来更美观
        self.setStyleSheet("""
            QPushButton {
                background-color: #e0e0e0;
                border: 1px solid #a0a0a0;
                border-radius: 4px;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #d0d0d0;
            }
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # 创建拖拽对象
            drag = QDrag(self)
            mime_data = QMimeData()
            
            # 设置拖拽数据 - 包含控件类型
            mime_data.setData("application/x-toolbox-item", self.m_toolName.encode('utf-8'))
            drag.setMimeData(mime_data)
            
            # 创建拖拽预览图像 - 使用grab()替代render()
            pixmap = self.grab()  # 直接捕获控件的当前显示
            
            # 添加半透明效果
            transparent_pixmap = QPixmap(pixmap.size())
            transparent_pixmap.fill(Qt.transparent)
            painter = QPainter(transparent_pixmap)
            painter.setOpacity(0.7)  # 设置为半透明
            painter.drawPixmap(0, 0, pixmap)
            painter.end()
            
            drag.setPixmap(transparent_pixmap)
            drag.setHotSpot(event.position().toPoint())
            
            # 开始拖拽
            drag.exec(Qt.CopyAction)
        
        super().mousePressEvent(event)


class ToolboxWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 标题
        title_label = QLabel("控件工具箱", self)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("""
            font-weight: bold; 
            font-size: 16px; 
            color: #333333;
            padding: 5px;
        """)
        main_layout.addWidget(title_label)
        
        # 分隔线
        separator = QFrame(self)
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setStyleSheet("color: #c0c0c0;")
        main_layout.addWidget(separator)
        
        # 添加工具按钮组
        self.add_tool_group("基本控件", [
            ("按钮", "QPushButton"),
            ("文本框", "QLineEdit"),
            ("标签", "QLabel")
        ], main_layout)
        
        self.add_tool_group("选择控件", [
            ("复选框", "QCheckBox"),
            ("单选按钮", "QRadioButton"),
            ("下拉框", "QComboBox")
        ], main_layout)
        
        self.add_tool_group("进度控件", [
            ("滑块", "QSlider"),
            ("进度条", "QProgressBar")
        ], main_layout)
        
        # 添加弹簧
        main_layout.addStretch()
        
        self.setMinimumWidth(160)
        self.setStyleSheet("""
            background-color: #f5f5f5; 
            border: 1px solid #cccccc;
            border-radius: 5px;
        """)

    def add_tool_button(self, display_name, tool_name, layout):
        button = ToolButton(display_name, self)
        button.setProperty("toolType", tool_name)  # 存储控件类型
        layout.addWidget(button)
    
    def add_tool_group(self, group_name, tools, main_layout):
        # 分组标签
        group_label = QLabel(group_name, self)
        group_label.setStyleSheet("""
            font-weight: bold; 
            color: #555555;
            margin-top: 10px;
            margin-bottom: 5px;
        """)
        main_layout.addWidget(group_label)
        
        # 组内按钮
        for tool in tools:
            self.add_tool_button(tool[0], tool[1], main_layout)


class DesignArea(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)  # 启用拖拽接收
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.on_context_menu)
        self.selected_widget = None
        
        # 设置样式
        self.setStyleSheet("""
            background-color: white; 
            border: 1px dashed #cccccc;
            border-radius: 4px;
        """)
        
        # 添加默认提示
        hint_label = QLabel("从工具箱拖拽控件到此处", self)
        hint_label.setAlignment(Qt.AlignCenter)
        hint_label.setStyleSheet("color: #999999; font-size: 14px;")
        hint_label.setGeometry(0, 0, self.width(), self.height())
        hint_label.show()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-toolbox-item"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasFormat("application/x-toolbox-item"):
            # 获取控件类型
            item_data = event.mimeData().data("application/x-toolbox-item")
            tool_type = bytes(item_data).decode('utf-8')
            
            # 在释放位置创建控件
            self.create_control(tool_type, event.position().toPoint())
            
            event.acceptProposedAction()
        else:
            event.ignore()

    def on_context_menu(self, pos):
        menu = QMenu(self)
        delete_action = menu.addAction("删除控件")
        delete_action.triggered.connect(lambda: self.delete_control(pos))
        
        # 添加其他操作
        if self.selected_widget:
            menu.addSeparator()
            bring_forward = menu.addAction("上移一层")
            bring_forward.triggered.connect(lambda: self.selected_widget.raise_())
            
            send_backward = menu.addAction("下移一层")
            send_backward.triggered.connect(lambda: self.selected_widget.lower())
        
        menu.exec(self.mapToGlobal(pos))

    def delete_control(self, pos):
        # 查找点击位置下的控件
        child = self.childAt(pos)
        if child and child != self:
            child.deleteLater()
            self.clear_selection()

    def create_control(self, tool_type, pos):
        # 清除选择
        self.clear_selection()
        
        control = None
        control_size = (120, 40)  # 默认大小
        
        if tool_type == "QPushButton":
            control = QPushButton("按钮", self)
            control.setFixedSize(*control_size)
        elif tool_type == "QLineEdit":
            control = QLineEdit(self)
            control.setPlaceholderText("输入文本...")
            control.setFixedSize(150, 30)
        elif tool_type == "QLabel":
            control = QLabel("标签文本", self)
            control.setAlignment(Qt.AlignCenter)
            control.setFixedSize(120, 30)
            control.setStyleSheet("border: 1px dashed #cccccc;")
        elif tool_type == "QCheckBox":
            control = QCheckBox("复选框", self)
            control.setFixedSize(100, 30)
        elif tool_type == "QRadioButton":
            control = QRadioButton("单选按钮", self)
            control.setFixedSize(100, 30)
        elif tool_type == "QComboBox":
            control = QComboBox(self)
            control.addItems(["选项1", "选项2", "选项3"])
            control.setFixedSize(120, 30)
        elif tool_type == "QSlider":
            control = QSlider(Qt.Horizontal, self)
            control.setFixedSize(150, 30)
        elif tool_type == "QProgressBar":
            control = QProgressBar(self)
            control.setValue(50)
            control.setFixedSize(150, 25)
        
        if control:
            # 移除默认提示（如果有）
            for child in self.children():
                if isinstance(child, QLabel) and "从工具箱" in child.text():
                    child.deleteLater()
            
            # 设置位置（确保在区域内）
            x = max(10, min(pos.x(), self.width() - control.width() - 10))
            y = max(10, min(pos.y(), self.height() - control.height() - 10))
            control.move(x, y)
            
            control.show()
            control.installEventFilter(self)  # 安装事件过滤器以便后续交互
            
            # 设置选中状态
            self.select_widget(control)
            
            # 添加调整大小句柄
            self.add_resize_handles(control)

    def select_widget(self, widget):
        """选择指定控件并高亮显示"""
        # 清除之前的选择
        self.clear_selection()
        
        # 设置新选择
        self.selected_widget = widget
        widget.setStyleSheet("border: 2px solid #1e90ff;")
        
        # 显示调整大小句柄
        self.show_resize_handles(widget)
    
    def clear_selection(self):
        """清除当前选择"""
        if self.selected_widget:
            # 恢复原始样式
            self.selected_widget.setStyleSheet("")
            # 隐藏调整大小句柄
            self.hide_resize_handles()
            self.selected_widget = None

    def add_resize_handles(self, widget):
        """为控件添加调整大小句柄"""
        # 创建8个句柄（4个角 + 4个边）
        self.resize_handles = []
        
        # 句柄样式
        handle_style = "background-color: #1e90ff; border: 1px solid white;"
        
        for i in range(8):
            handle = QWidget(self)
            handle.setFixedSize(8, 8)
            handle.setStyleSheet(handle_style)
            handle.setVisible(False)
            self.resize_handles.append(handle)
        
        # 更新句柄位置
        self.update_resize_handle_positions(widget)
    
    def update_resize_handle_positions(self, widget):
        """更新调整大小句柄的位置"""
        if not hasattr(self, 'resize_handles') or not widget:
            return
            
        rect = widget.geometry()
        
        # 角句柄
        self.resize_handles[0].move(rect.left() - 4, rect.top() - 4)       # 左上
        self.resize_handles[1].move(rect.right() - 4, rect.top() - 4)      # 右上
        self.resize_handles[2].move(rect.right() - 4, rect.bottom() - 4)   # 右下
        self.resize_handles[3].move(rect.left() - 4, rect.bottom() - 4)    # 左下
        
        # 边句柄
        self.resize_handles[4].move(rect.left() + rect.width()//2 - 4, rect.top() - 4)       # 上
        self.resize_handles[5].move(rect.right() - 4, rect.top() + rect.height()//2 - 4)     # 右
        self.resize_handles[6].move(rect.left() + rect.width()//2 - 4, rect.bottom() - 4)    # 下
        self.resize_handles[7].move(rect.left() - 4, rect.top() + rect.height()//2 - 4)      # 左
    
    def show_resize_handles(self, widget):
        """显示调整大小句柄"""
        if hasattr(self, 'resize_handles'):
            self.update_resize_handle_positions(widget)
            for handle in self.resize_handles:
                handle.setVisible(True)
                handle.raise_()  # 确保句柄在控件上方
    
    def hide_resize_handles(self):
        """隐藏调整大小句柄"""
        if hasattr(self, 'resize_handles'):
            for handle in self.resize_handles:
                handle.setVisible(False)

    # 事件过滤器用于实现控件交互
    def eventFilter(self, obj, event):
        # 处理控件选择
        if event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                self.select_widget(obj)
        
        # 处理控件移动
        elif event.type() == QEvent.MouseMove:
            if event.buttons() & Qt.LeftButton and self.selected_widget == obj:
                # 计算移动的偏移量
                new_pos = obj.pos() + (event.position() - event.lastPosition()).toPoint()
                
                # 确保控件在设计区域内
                x = max(0, min(new_pos.x(), self.width() - obj.width()))
                y = max(0, min(new_pos.y(), self.height() - obj.height()))
                
                obj.move(x, y)
                
                # 更新调整大小句柄位置
                self.update_resize_handle_positions(obj)
                
                return True
        
        return super().eventFilter(obj, event)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UI设计工具")
        self.setGeometry(100, 100, 1000, 700)
        self.setup_ui()
    
    def setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # 添加工具箱
        toolbox = ToolboxWidget(self)
        main_layout.addWidget(toolbox)
        
        # 添加设计区域
        self.design_area = DesignArea(self)
        main_layout.addWidget(self.design_area, 1)  # 占据剩余空间
        
        # 设置窗口样式
        self.setStyleSheet("""
            QWidget {
                font-family: 'Segoe UI', Arial, sans-serif;
            }
        """)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
