

# from PySide6.QtCore import Signal,QObject

import enum

class SceneMode(enum.Enum):
    Design               = 0x0
    Run                  = 0x1



class GlobalConfigSingleton():
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
          
        return cls._instance
    
    def _initialize(self):
        # 配置项
        self.scene_mode = SceneMode.Design
       
    
    def setSceneMode(self,mode):
        self.scene_mode = mode
    
# 创建全局单例实例
global_cfg = GlobalConfigSingleton()



