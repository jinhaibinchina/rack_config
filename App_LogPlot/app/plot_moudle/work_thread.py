from PySide6.QtCore import QThread, Signal,Qt,QObject
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QTextEdit
import time
import sys
from .common import rcd_data_bridge
from .global_config import global_config,PlaySpeed
from typing import Callable

class playerWorkerThread(QThread):
    """工作线程类"""
    
    # 定义信号
    progress_updated = Signal(int)      # 进度更新信号
    result_ready = Signal(str)          # 结果就绪信号
    error_occurred = Signal(str)        # 错误信号
    finished_signal = Signal()          # 完成信号
    target_idx_change         = Signal(int)
    def __init__(self,parent, task_id,plot_ref,data_bridge:rcd_data_bridge,check_operation:Callable):
        super().__init__(parent)
        self.task_id = task_id
        
        self.plot = plot_ref
        self.target_idx_change.connect(plot_ref.move_slider_by_idx, Qt.QueuedConnection)
        self.current = self.plot.current_x_idx()
        self.target  = self.plot.target_x_idx()
        self._is_running = True
        self._idx_count = data_bridge.idx_count()
        self._total_time_ms = data_bridge.total_time_ms()
        self._step_time_ms =  self._total_time_ms/(self._idx_count-1)
        print(f"playing step_time={self._step_time_ms}ms")
        self._last_time = time.time()
        self._check_operation = check_operation
        self.__target_fps = 1.0
        self.__frame_time_ms = 1

    def reset_fps(self,val):
        if val<1.0 or val>5.0:
            return
        self.__target_fps = val
        target_fps = self.__target_fps  # 目标帧率
        self.__frame_time_ms =int( 1000.0 / target_fps)
        print(f"fps:{self.__target_fps}")

    def run(self):
        """线程执行的主函数"""
        # try:

        #     while self._is_running:
        #         self.process_data()
        #         self.msleep(50)
        # except Exception as e:
        #     self.error_occurred.emit(f"错误: {str(e)}")
        
        try:
            # 使用QTimer进行更精确的时间控制
            target_fps = self.__target_fps  # 目标帧率
            self.__frame_time_ms =int( 1000.0 / target_fps)
            
            while self._is_running:
                start_time = time.time()
                self.process_data()
                # 计算处理时间并调整睡眠时间
                process_time = (time.time() - start_time) * 1000
                sleep_time = max(1, self.__frame_time_ms - process_time)  # 确保至少睡眠1ms
                self.msleep(int(sleep_time))
                
        except Exception as e:
            self.error_occurred.emit(f"错误: {str(e)}")
            self.finished_signal.emit()

    def process_data(self):
        """处理数据的实际逻辑"""
        if self._check_operation():
            return
            self.finished_signal.emit()
       
        
        if global_config.play_speed ==PlaySpeed.STEP:
            current_time = time.time()
            elapsed_time = (current_time - self._last_time) * 1000  # 转换为毫秒
            self._last_time = current_time
            if self.current < self.target:
                self.current = min(self.current + 1, self.target)
                
            elif self.current > self.target:
                self.current = max(self.current - 1, self.target)
            else:
                if self._is_running:
                    self.result_ready.emit(f"任务 {self.task_id} 完成")
                    self.finished_signal.emit()
                    # self._is_running =False
            self.target_idx_change.emit(self.current)
        else:
            current_time = time.time()
            elapsed_time = (current_time - self._last_time) * 1000  # 转换为毫秒
            self._last_time = current_time
            
            # 计算应该移动的步数
            step_count = int(elapsed_time / self._step_time_ms)
            if step_count == 0:
                step_count = 1  # 确保至少移动1步
            
            # 更新当前位置
            if self.current < self.target:
                self.current = min(self.current + step_count, self.target)
            elif self.current > self.target:
                self.current = max(self.current - step_count, self.target)
            else:
                if self._is_running:
                    self.result_ready.emit(f"任务 {self.task_id} 完成")
                    self.finished_signal.emit()
            self.target_idx_change.emit(self.current)

    def stop(self):
        """停止线程"""
        self._is_running = False
        global_config.enable_play_mode(False)
        self.wait()  # 等待线程结束

class ThreadManager(QObject):
    """线程管理器"""
    
    def __init__(self,parent=None):
        super().__init__(parent)
        self.threads = {}  # 存储线程的字典
        self.thread_counter = 0

    def cleanup(self):
        """显式清理方法"""
        self.stop_all_threads()
    
    def start_thread(self, task_name,plot_ref,data_bridge,check_operation:Callable):
        """启动新线程"""
        thread_id = self.thread_counter
        self.thread_counter += 1
        
        thread = playerWorkerThread(self,thread_id,plot_ref,data_bridge,check_operation)
        self.threads[thread_id] = {
            'thread': thread,
            'name': task_name,
            'status': 'running'
        }
        
        # 连接信号
        thread.progress_updated.connect(lambda progress: self.on_progress_updated(thread_id, progress))
        thread.result_ready.connect(lambda result: self.on_result_ready(thread_id, result))
        thread.error_occurred.connect(lambda error: self.on_error_occurred(thread_id, error))
        thread.finished_signal.connect(lambda: self.on_thread_finished(thread_id))
        
        # 启动线程
        thread.start()
        global_config.enable_play_mode(True)
        return thread_id

    def get_thread_by_id(self,id):
        return self.threads[id]['thread']

    def stop_thread(self, thread_id):
        """停止指定线程"""
        if thread_id in self.threads:
            self.threads[thread_id]['thread'].stop()
            self.threads[thread_id]['status'] = 'stopped'

        del self.threads[thread_id]

    def stop_all_threads(self):
        """停止所有线程"""
        print(f"尝试停止所有子线程,当前数量={len(list(self.threads.keys()))}")
        for thread_id in list(self.threads.keys()):
            self.stop_thread(thread_id)
        
        
        

    def get_thread_status(self, thread_id):
        """获取线程状态"""
        if thread_id in self.threads:
            return self.threads[thread_id]['status']
        return 'not_found'
    
    def on_progress_updated(self, thread_id, progress):
        """处理进度更新"""
        print(f"线程 {thread_id} 进度: {progress}%")
    
    def on_result_ready(self, thread_id, result):
        """处理结果就绪"""
        print(f"线程 {thread_id} 结果: {result}")
    
    def on_error_occurred(self, thread_id, error):
        """处理错误"""
        print(f"线程 {thread_id} 错误: {error}")
        if thread_id in self.threads:
            self.threads[thread_id]['status'] = 'error'
    

    def on_thread_finished(self, thread_id):
        """线程完成"""
        print(f"线程 {thread_id} 完成")
        self.stop_thread(thread_id)
        if thread_id in self.threads:
            self.threads[thread_id]['status'] = 'finished'
            

class MainWindow(QMainWindow):
    """主窗口示例"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyQt多线程示例")
        self.setGeometry(100, 100, 600, 400)
        
        # 创建线程管理器
        self.thread_manager = ThreadManager()
        
        self.setup_ui()
    
    def setup_ui(self):
        """设置UI"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 文本显示区域
        self.text_edit = QTextEdit()
        layout.addWidget(self.text_edit)

        self.btn_start = QPushButton("启动任务")
        self.btn_start.clicked.connect(self.start_task)
        layout.addWidget(self.btn_start)
        
        self.btn_stop = QPushButton("停止所有任务")
        self.btn_stop.clicked.connect(self.stop_all_tasks)
        layout.addWidget(self.btn_stop)
        
        self.btn_status = QPushButton("查看状态")
        self.btn_status.clicked.connect(self.show_status)
        layout.addWidget(self.btn_status)
    
    def start_task(self):
        """启动任务"""
        task_id = self.thread_manager.start_thread("数据处理任务", "示例数据")
        self.append_text(f"启动任务 ID: {task_id}")
    
    def stop_all_tasks(self):
        """停止所有任务"""
        self.thread_manager.stop_all_threads()
        self.append_text("已停止所有任务")
    
    def show_status(self):
        """显示状态"""
        status_text = "当前线程状态:\n"
        for thread_id, info in self.thread_manager.threads.items():
            status_text += f"线程 {thread_id} ({info['name']}): {info['status']}\n"
        self.append_text(status_text)
    
    def append_text(self, text):
        """添加文本到显示区域"""
        self.text_edit.append(text)

# 使用示例
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

