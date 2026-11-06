from abc import ABC, abstractmethod
from typing import Optional
class IDataTranslater(ABC):
    """数据提供者接口"""
    
    @abstractmethod
    def translate_title(self,data_title:str) ->Optional[str]:
        """翻译表头"""
        pass
    
    @abstractmethod
    def translate_data(self,data_title:str,data:int)->Optional[str]:
        """根据表头和数据翻译数据"""
        pass
