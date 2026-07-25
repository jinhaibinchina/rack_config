

# from PyQt6.QtCore import pyqtSignal,QObject





class GlobalConfigSingleton():
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
          
        return cls._instance
    
    def _initialize(self):
        # 配置项
        self.is_logged_in = False
        self.status_bar = None
        self._user_name = ''
        self._password = ''
    
    def login_enable_disable(self,en):
       
        self.is_logged_in = en
        return
        if en:
            self.status_bar.showMessage(f'用户:{self._user_name} 已登入')
        else:
            self.status_bar.showMessage(f'用户:{self._user_name} 已注销登入')

    
# 创建全局单例实例
global_cfg = GlobalConfigSingleton()

# print(global_cfg.is_logged_in)

