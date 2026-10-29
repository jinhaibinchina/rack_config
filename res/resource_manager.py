import os,sys
import json

from pathlib import Path
from typing import Optional, Union

class _ResourceManager:
    
    def __init__(self, package_name: Optional[str] = None):
        self.package_name = package_name or self._detect_package_name()
        self._cache = {}  # 简单的资源路径缓存
        self._base_path = self._get_base_path()
    
    def _get_base_path(self) -> Path:
        """获取资源文件的基础路径"""
        # 如果是打包后的可执行文件
        if getattr(sys, 'frozen', False):
            # PyInstaller 创建的临时文件夹
            base_path = Path(sys._MEIPASS)
        else:
            # 脚本文件所在路径
            base_path = Path(__file__).parent
        
        return base_path
    
    def _detect_package_name(self) -> str:
        """自动检测包名"""
        # 获取调用者的包名
        import inspect
        frame = inspect.currentframe()
        try:
            # 向上追溯调用栈，找到第一个非资源管理器的模块
            for i in range(5):  # 限制追溯深度
                frame = frame.f_back
                if frame is None:
                    break
                module_name = frame.f_globals.get('__name__', '')
                if module_name and not module_name.endswith('resource_manager'):
                    # 提取包名（第一个部分）
                    return module_name.split('.')[0]
        finally:
            del frame
        
        return '__main__'  # 默认回退

    def get_path(self, relative_path: str) -> str:
        """获取资源文件的完整路径"""
        # 使用缓存提高性能
        if relative_path in self._cache:
            return self._cache[relative_path]
        
        # 构建相对于基础目录的完整路径
        path = str(self._base_path / relative_path)
        self._cache[relative_path] = path
        return path
    
    def get_icon_path(self, icon_name: str) -> str:
        """获取图标路径"""
        return self.get_path(f"App/ico/{icon_name}")
    
    def get_branch_icon_path(self, branch_icon_name: str) -> str:
        """获取图标路径"""
        return self.get_path(f"App/ico/branch/{branch_icon_name}")
    
    def get_config_path(self, config_name: str) -> str:
        """获取配置文件路径"""
        return self.get_path(f"App/cfg/{config_name}")
    
    def get_data_path(self, data_name: str) -> str:
        """获取数据文件路径"""
        return self.get_path(f"App/data/{data_name}")
    
    def get_ui_path(self, ui_name: str) -> str:
        """获取数据文件路径"""
        print(ui_name)
        return self.get_path(f"App/ui/{ui_name}")
    
    def get_template(self, template_name: str) -> str:
        """获取模板文件路径"""
        return self.get_path(f"App/templates/{template_name}")
    
    def read_text(self, relative_path: str, encoding: str = 'utf-8') -> str:
        """读取文本文件内容"""
        file_path = self.get_path(relative_path)
        print(file_path)
        with open(file_path, 'r', encoding=encoding) as f:
            return f.read()
    
    def read_json(self, relative_path: str) -> Union[dict, list]:
        """读取JSON文件"""
        content = self.read_text(relative_path)
        return json.loads(content)
    

    def read_binary(self, relative_path: str) -> bytes:
        """读取二进制文件"""
        file_path = self.get_path(relative_path)
        with open(file_path, 'rb') as f:
            return f.read()
    
    def exists(self, relative_path: str) -> bool:
        """检查资源文件是否存在"""
        file_path = self.get_path(relative_path)
        return os.path.exists(file_path)
    
    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()

# 创建全局单例实例
resource_manager = _ResourceManager()



