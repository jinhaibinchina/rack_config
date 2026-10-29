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
        """获取资源文件的基础路径。

        源码运行：base 就是本文件所在目录（即 ``res/``），后续拼接
        ``App_SafetyCar/ui/xxx.ui`` 正好命中 ``res/App_SafetyCar/ui/xxx.ui``。

        打包运行：spec 里 ``datas=[('res', 'res')]`` 会把资源放到
        ``<_MEIPASS>/res/``，而不是 ``<_MEIPASS>/`` 根目录。早期这里直接
        取 ``sys._MEIPASS``，于是拼出 ``<_MEIPASS>/App_SafetyCar/ui/main.ui``，
        文件不存在 -> LoadMainWindow 里 ``sys.exit(1)``，表现为 exe "打不开"。

        这里按优先级找出真正的资源根目录：以 ``App_SafetyCar`` 子目录是否存在作为
        判定依据，同时兼容"资源被放到 exe 同目录"的现场替换场景。
        """
        if not getattr(sys, 'frozen', False):
            return Path(__file__).parent

        meipass = getattr(sys, '_MEIPASS', None)
        exe_dir = Path(sys.executable).resolve().parent

        candidates = []
        if meipass:
            candidates.append(Path(meipass) / 'res')
            candidates.append(Path(meipass))
        candidates.append(exe_dir / 'res')
        candidates.append(exe_dir)

        for candidate in candidates:
            if (candidate / 'myDesigner').is_dir():
                return candidate

        # 都不存在时回退到打包约定位置，让后续报错路径可读
        return (Path(meipass) / 'res') if meipass else (exe_dir / 'res')
    
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
        return self.get_path(f"App_SafetyCar/ico/{icon_name}")
    
    def get_branch_icon_path(self, branch_icon_name: str) -> str:
        """获取图标路径"""
        return self.get_path(f"App_SafetyCar/ico/branch/{branch_icon_name}")
    
    def get_config_path(self, config_name: str) -> str:
        """获取配置文件路径"""
        return self.get_path(f"App_SafetyCar/cfg/{config_name}")
    
    def get_data_path(self, data_name: str) -> str:
        """获取数据文件路径"""
        return self.get_path(f"App_SafetyCar/data/{data_name}")
    
    def get_ui_path(self, ui_name: str) -> str:
        """获取数据文件路径"""
        print(ui_name)
        return self.get_path(f"App_SafetyCar/ui/{ui_name}")
    
    def get_template(self, template_name: str) -> str:
        """获取模板文件路径"""
        return self.get_path(f"App_SafetyCar/templates/{template_name}")
    
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



