from abc import ABC, abstractmethod
from abc import ABCMeta
from typing import Any, List, Dict
from PySide6.QtCore import QObject


class IDataProvider(ABC):
    """数据提供者接口"""
    def __init__(self):
        super().__init__()
    @abstractmethod
    def get_data(self,head_name) -> List[str]|None:
        """根据表头名称获取数据"""
        pass

    @abstractmethod
    def get_datas(self,head_names) -> List[Any]|None:
        """根据表头名称获取数据"""
        pass
    
    @abstractmethod
    def get_data_head(self) -> List[str]|None:
        """获取表头数据列表"""
        pass

    @abstractmethod
    def get_row_data(self,idx) -> Dict[str,List[Any]]|None:
        """根据表行号获取数据"""
        pass

class IChartRenderer(ABC):
    """图表绘制器接口"""
    
    def __init__(self):
        super().__init__()
    
    @abstractmethod
    def on_data_ready(self, data_provider: IDataProvider):
        """数据准备完成时的回调方法"""
        pass





# 创建协调元类
class MultiMeta(type(QObject), ABCMeta):
    pass

