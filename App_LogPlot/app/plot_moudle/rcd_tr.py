from .rcd_tr_interface import IDataTranslater


class RcdTr_for_polt_moudle(IDataTranslater):
    def __init__(self,translater):
        self._translater = translater
    
        
    def translate_title(self,data_title:str) -> str|None:
        """翻译表头"""
        # print(data_title)
        return self._translater.get_title_tip(data_title)
    
    def translate_data(self,data_title:str,data:int) -> str|None:
        """根据表头和数据翻译数据"""
        return self._translater.get_lable_value_tr(data_title,data)

