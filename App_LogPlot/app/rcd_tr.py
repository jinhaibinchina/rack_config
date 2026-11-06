import json
from jsonpath import jsonpath
import os


class RcdTr:
    def __init__(self):
        self.act_name_map = None
        self.state_map_json = None
        self.analysis_info_json = None
        # 表头中文转换
        self.tr_dict = {}  # {rcd_title:{"state_map_path": xx, "state_map_mask": xx, "tip": xx, "org_tip": xx}}

    def clear(self):
        self.tr_dict.clear()
        self.state_map_json = None
        self.analysis_info_json = None
        self.act_name_map = None

    def parse_tr_json(self, car_type:str):
        self.clear()
        # 配置文件跟着工程走，不能依赖启动时的当前工作目录（入口脚本现在放在
        # 仓库根目录，cwd 不再是 App_LogPlot）。
        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg_folder = os.path.join(app_root, "cfg", "ctu")
        if "STU" in car_type:
            cfg_folder = os.path.join(app_root, "cfg", "stu")
        analysis_info_path = os.path.join(cfg_folder, "analysis_info.json")
        state_map_path = os.path.join(cfg_folder, "state_map.json")
        with open(analysis_info_path, encoding="utf-8") as f:
            self.analysis_info_json = json.load(f)
        with open(state_map_path, encoding="utf-8") as f:
            self.state_map_json = json.load(f)
        self.init_tr_dict()


    def init_tr_dict(self):
        for mod_key, mod_value in self.analysis_info_json["rcd"].items():
            for item in mod_value:
                level1_list = item["level1"] if "level1" in item else ["0"]
                level2_list = item["level2"] if "level2" in item else ["0"]
                for index1, level1 in enumerate(level1_list):
                    for index2, level2 in enumerate(level2_list):
                        rcd_title = item["rcd_title"].format([level1_list[index1], level2_list[index2]])
                        if "tip" in item.keys():
                            self.tr_dict[rcd_title] = {}
                            tip = item["tip"].format([level1_list[index1], level2_list[index2]])
                            self.tr_dict[rcd_title].update({"tip": f"{mod_key}-{tip}"})
                        else:
                            continue
                        if "org_tip" in item.keys():
                            self.tr_dict[rcd_title].update({"org_tip": item["org_tip"].format([level1_list[index1], level2_list[index2]])})
                        if "state_map_path" in item.keys():
                            self.tr_dict[rcd_title].update({"state_map_path": item["state_map_path"]})
                        if "bit_map_path" in item.keys():
                            self.tr_dict[rcd_title].update({"bit_map_path": item["bit_map_path"]})

                        if "state_map_mask" in item.keys():
                            self.tr_dict[rcd_title].update({"state_map_mask": item["state_map_mask"]})
                        #STU特殊增加解析相关映射
                        if "special_state_type" in item.keys():
                            self.tr_dict[rcd_title].update({"special_state_type": item["special_state_type"]})
                        if "stu_gantry_com_map_path" in item.keys():
                            self.tr_dict[rcd_title].update({"stu_gantry_com_map_path": item["stu_gantry_com_map_path"]})
                        if "stu_gantry_stc_map_path" in item.keys():
                            self.tr_dict[rcd_title].update({"stu_gantry_stc_map_path": item["stu_gantry_stc_map_path"]})

    def set_act_name_map(self, act_name_map):
        """
        act_name_map = {"linear1":"伸缩"}
        """
        for value in self.tr_dict.values():
            if "org_tip" in value.keys():
                if "new_tip" in value.keys():
                    del value["new_tip"]
                if act_name_map is None:
                    continue
                for act_tip, act_name in act_name_map.items():
                    if act_tip in value["org_tip"]:
                        value.update({"new_tip": value["org_tip"].replace(act_tip, act_name)})
                        break

    def get_title_tip(self, title):
        if title in self.tr_dict.keys():
            if "new_tip" in self.tr_dict[title].keys():
                return self.tr_dict[title]["new_tip"]
            return self.tr_dict[title]["tip"]
        return None
    
    def process_jsonpath(self, mod, map_val, path, suffix):
        """
        处理 jsonpath 查询并拼接字符串。

        Args:
            mod (int): 模块标识。
            map_val (int): 映射值。
            path (str): jsonpath 查询路径。
            suffix (str): 拼接的字符串。

        Returns:
            list or None: 处理后的结果列表或 None。
        """
        res = jsonpath(self.state_map_json, path + "[?(@.key==" + str(map_val) + ")].str")
        if res:
            res = [suffix + r for r in res]
        return res
    

    def get_lable_value_tr(self, label, value):
        """获取标签对应的值的翻译"""
        state_enum = self.get_state_enum(label, value)
        if state_enum:
            return state_enum
        # 无状态枚举则获取bit val
        return self.get_bit_value(label, value)
        

    def get_state_enum(self, label, value):
        """获取状态枚举的翻译"""
        value = int(value)
        if label in self.tr_dict.keys():
            item = self.tr_dict[label]
            
            if "special_state_type" not in item.keys():
                if "state_map_path" not in item.keys():
                    return None
                if "state_map_mask" in item.keys():
                    value = value & int(item["state_map_mask"], base=0)
                res = jsonpath(self.state_map_json, item["state_map_path"] + "[?(@.key==" + str(value) + ")]." + "str")
            else:
                if item["special_state_type"] == "stu_gantry":
                    mod = (int(value) >> 24) & 0xFF
                    map_val = int(value) & 0xFFFF


                    if mod in [0x60, 0x61, 0x62]:
                        path = item["stu_gantry_com_map_path"]
                        suffix_map = {
                            0x60: "管理模块",
                            0x61: "轨道",
                            0x62: "举升"
                        }
                        res = self.process_jsonpath(mod, map_val, path, suffix_map[mod])
                    elif mod == 0x63:
                        path = item["stu_gantry_stc_map_path"]
                        res = self.process_jsonpath(mod, map_val, path, "STC算法")
                    else:
                        return None
            if res:
                return res[0]
            else:
                return None

    def get_bit_value(self, title, value):
        value = int(value)
        if title in self.tr_dict.keys():
            item = self.tr_dict[title]
            if "bit_map_path" not in item.keys():
                return None
            bit_value_list = []
            bit_list = [i for i, bit in enumerate(bin(value)[:1:-1]) if bit == '1']  # 找到二进制数中为1的位数
            for bit_sn in bit_list:
                res = jsonpath(self.state_map_json, f"{item['bit_map_path']}[?(@.key=={str(bit_sn)})].str")
                if res:
                    bit_value_list.append(res[0])

            if 0 != len(bit_value_list):
                return ','.join(bit_value_list)
            else:
                return None


if __name__ == '__main__':
    print('Python')
