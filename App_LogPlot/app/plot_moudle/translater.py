from .rcd_tr_interface import IDataTranslater


class rcd_translater(IDataTranslater):
    def __init__(self, name: str = "翻译器"):
        self.name = name
        self.version = "1.0"
    

    
    def translate_title(self,data_title:str) -> str|None:
        """翻译表头"""
        return None
    
  
    def translate_data(self,data_title:str,data:int) -> str|None:
        """根据表头和数据翻译数据"""
        return None