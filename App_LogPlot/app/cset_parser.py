import os
import json
from typing import List, Dict, Optional, Any, Union
from pathlib import Path
from jsonpath import jsonpath


class CSetParser:
    """能力集解析器"""
    
    def __init__(self, cset_path: str = None):
        """
        初始化能力集解析器
        
        Args:
            cset_path: cset路径，如果为None则从cfg/config.json读取，默认值"./cset"
        """
        # 如果未提供cset_path，尝试从配置文件读取
        if cset_path is None:
            cset_path = self._load_cset_path_from_config()
        
        self.cset_path = cset_path
        self.rcu_json_data = None
        self.rcd_json_data = None
        self.actuator_info = {}
        self.act_name_map = {}  # {"linear1":"伸缩"}
        self.io_map_info = []
        
    def _load_cset_path_from_config(self) -> str:
        """
        从cfg/config.json加载cset_path配置
        
        Returns:
            str: cset_path配置值，如果读取失败则返回默认值"./cset"
        """
        config_path = os.path.join("cfg", "config.json")
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    cset_path = config.get("cset_path")
                    if cset_path:
                        print(f"从配置文件加载cset_path: {cset_path}")
                        return cset_path
        except Exception as e:
            print(f"读取配置文件失败: {e}，使用默认值")
        
        # 返回默认值
        return "./cset"

    def clear_data(self):
        """清空所有已加载的数据"""
        self.rcu_json_data = None
        self.rcd_json_data = None
        self.actuator_info.clear()
        self.act_name_map.clear()
        self.io_map_info.clear()

    def parse_log_folder(self, log_folder_path: str, software_id: str):
        # 清空之前的数据
        self.clear_data()
        self.load_rcd_json(log_folder_path)
        self.load_rcu_json(log_folder_path, software_id)

    def load_rcu_json(self, log_folder_path: str, software_id: str) -> bool:
        """
        加载RCU JSON文件
        
        Args:
            log_folder_path: 日志文件夹路径
            software_id: 软标ID
            
        Returns:
            bool: 加载是否成功
        """
        if not software_id:
            return False

        # 首先尝试在日志解析文件夹下查找RCU json文件
        log_rcu_path = os.path.join(log_folder_path, f"rcu_hw_cfg_{software_id}.json")
        
        if os.path.exists(log_rcu_path):
            json_path = log_rcu_path
        else:
            # 如果没有，则在默认cset路径下查找
            json_path = os.path.join(self.cset_path, f"rcu_hw_cfg_{software_id}.json")
            
        if not os.path.exists(json_path):
            print(f"未找到RCU JSON文件: {json_path}")
            return False
            
        try:
            # 读取GBK编码的JSON文件
            with open(json_path, 'r', encoding='gbk') as f:
                self.rcu_json_data = json.load(f)
                
            # 解析actuator信息
            self._parse_actuator_info()
            
            return True
        except Exception as e:
            print(f"加载RCU JSON文件失败: {e}")
            return False
            

    def load_rcd_json(self, log_folder_path: str) -> bool:
        """
        加载RCD JSON文件（解压生成的JSON文件）
        
        Args:
            log_folder_path: 日志文件夹路径
            
        Returns:
            bool: 加载是否成功
        """
        # 在文件夹及其子文件夹中查找所有以rcd_开头的JSON文件
        try:
            # 遍历文件夹及其所有子文件夹
            for root, dirs, files in os.walk(log_folder_path):
                for filename in files:
                    if filename.startswith("rcd_") and filename.endswith(".json"):
                        json_path = os.path.join(root, filename)
                        with open(json_path, 'r', encoding='utf-8') as f:
                            self.rcd_json_data = json.load(f)
                        # 解析RCD JSON中的机构信息
                        self._parse_rcd_actuator_info()
                        print(f"从 {json_path} 加载RCD JSON成功")
                        return True
            print("未找到RCD JSON文件")
            return False
        except Exception as e:
            print(f"加载RCD JSON文件失败: {e}")
            return False


    def _parse_rcd_actuator_info(self):
        """解析RCD JSON中的actuator信息"""
        if not self.rcd_json_data or "rcu_info" not in self.rcd_json_data:
            return
            
        rcd_info = self.rcd_json_data["rcu_info"]
        # 将RCD JSON中的rcu_info信息保存到act_name_map中
        for key, value in rcd_info.items():
            if "act_name" in value:
                # 保存机构名信息到act_name_map
                self.act_name_map[key] = value["act_name"]
            
    def _parse_actuator_info(self):
        """解析actuator信息"""
        if not self.rcu_json_data or "actuator" not in self.rcu_json_data:
            return
            
        actuator_data = self.rcu_json_data["actuator"]
        if "inst" not in actuator_data:
            return
            
        # 遍历所有actuator实例
        for actuator in actuator_data["inst"]:
            if "b_exist" in actuator and actuator["b_exist"] == 1:
                # 提取基本信息
                actuator_type = actuator.get("type", "")
                sub_type = actuator.get("sub_type", "")
                idx = actuator.get("idx", -1)
                name = actuator.get("private", {}).get("name", "")
                
                # 保存到actuator_info字典中，使用与act_name_map相同的key格式
                key = f"{actuator_type.lower()}{idx}"
                # 将io_map转换为以name为键的字典
                io_map_dict = {}
                io_map_list = actuator.get("private", {}).get("io_map", [])
                for io_info in io_map_list:
                    io_name = io_info.get("name", "")
                    if io_name:
                        io_map_dict[io_name] = io_info
                
                self.actuator_info[key] = {
                    "type": actuator_type,
                    "sub_type": sub_type,
                    "idx": idx,
                    "name": name,
                    "io_map": io_map_dict
                }
                

                # 同时将机构名保存到act_name_map中 (使用类型和索引拼接，类型转为小写)
                act_key = f"{actuator_type.lower()}{idx}"
                # 先解析底盘的机构名，后解析能力集的，底盘json优先级更高
                if act_key not in self.act_name_map.keys():
                    self.act_name_map[act_key] = name
                
                # 保存IO映射信息，包含关联的actuator信息
                for io_info in io_map_list:
                    io_name = io_info.get("name", "")
                    if io_name:
                        # 创建包含关联actuator信息的IO信息
                        io_with_act = {
                            "io_info": io_info,
                            "act_info": {
                                "type": actuator_type,
                                "sub_type": sub_type,
                                "idx": idx,
                                "name": name
                            }
                        }
                        self.io_map_info.append(io_with_act)
                        
    def get_actuator_by_type_idx(self, actuator_type: str, idx: int) -> Optional[Dict]:
        """
        根据type和idx获取机构信息
        
        Args:
            actuator_type: 机构类型
            idx: 索引
            
        Returns:
            Optional[Dict]: 机构信息，未找到返回None
        """
        # 使用与存储时相同的key格式
        key = f"{actuator_type.lower()}{idx}"
        return self.actuator_info.get(key)
        

    def get_all_actuator_info(self) -> Dict:
        """
        获取所有机构信息
        
        Returns:
            Dict: 所有机构信息
        """
        return self.actuator_info
        
    def get_actuator_mapping(self) -> Dict[str, str]:
        """
        获取机构名映射表
        
        Returns:
            Dict[str, str]: 机构名映射表 {"linear1":"伸缩"}
        """
        # 返回RCD JSON中的机构名映射
        return self.act_name_map
        
    def get_rcu_json_data(self) -> Optional[Dict]:
        """
        返回整个JSON字典，用于插件解析
        
        Returns:
            Optional[Dict]: JSON数据
        """
        return self.rcu_json_data
        
    def get_io_info_by_name(self, io_name: str) -> Optional[Dict]:
        """
        根据IO名称获取IO信息
        
        Args:
            io_name: IO名称
            
        Returns:
            Optional[Dict]: IO信息，未找到返回None
        """
        # 遍历IO映射信息列表，查找匹配的IO名称
        for io_entry in self.io_map_info:
            if io_entry["io_info"].get("name") == io_name:
                return io_entry
        return None
        

    def get_io_info_list(self) -> List[Dict]:
        """
        获取所有IO信息列表
        
        Returns:
            List[Dict]: IO信息列表
        """
        return self.io_map_info
        
    def get_actuator_types(self) -> List[str]:
        """
        获取所有机构类型
        
        Returns:
            List[str]: 机构类型列表
        """
        types = set()
        for info in self.actuator_info.values():
            types.add(info["type"])
        return list(types)
        
    def get_actuator_indices(self, actuator_type: str) -> List[int]:
        """
        获取指定类型的所有索引
        
        Args:
            actuator_type: 机构类型
            
        Returns:
            List[int]: 索引列表
        """
        indices = []
        for key, info in self.actuator_info.items():
            # 使用类型匹配时，需要转换为小写进行比较
            if info["type"].lower() == actuator_type.lower():
                indices.append(info["idx"])
        return indices
        

    def get_io_pin_info(self, io_name: str) -> Optional[Dict]:
        """
        获取IO的节点信息（node_id, grp, pin_idx）
        
        Args:
            io_name: IO名称
            
        Returns:
            Optional[Dict]: IO节点信息，未找到返回None
        """
        io_info = self.get_io_info_by_name(io_name)
        if io_info:
            io_data = io_info["io_info"]
            return {
                "node_id": io_data.get("node_id"),
                "grp": io_data.get("grp"),
                "pin_idx": io_data.get("pin_idx")
            }
        return None
        
    def get_io_config_by_type_idx_name(self, actuator_type: str, idx: int, io_name: str) -> Optional[Dict]:
        """
        根据type、idx和name获取对应的IO配置信息
        
        Args:
            actuator_type: 机构类型
            idx: 索引
            io_name: IO名称
            
        Returns:
            Optional[Dict]: IO配置信息，未找到返回None
        """
        # 先通过type和idx找到对应的机构 (使用新的key格式)
        key = f"{actuator_type.lower()}{idx}"
        actuator_info = self.actuator_info.get(key)
        if actuator_info:
            # 在该机构中查找指定名称的IO
            io_map = actuator_info["io_map"]
            if io_name in io_map:
                io_data = io_map[io_name]
                return {
                    "node_id": io_data.get("node_id"),
                    "grp": io_data.get("grp"),
                    "pin_idx": io_data.get("pin_idx")
                }
        return None

    def get_io_config_from_dict(self, io_dict: Dict) -> Optional[Dict]:
        """
        从IO字典获取IO配置信息
        
        Args:
            io_dict: IO字典，包含node_id, grp, pin_idx等信息
            
        Returns:
            Optional[Dict]: IO配置信息，未找到返回None
        """
        if not io_dict:
            return None
            
        # 从传入的IO字典中提取信息
        return {
            "node_id": io_dict.get("node_id"),
            "grp": io_dict.get("grp"),
            "pin_idx": io_dict.get("pin_idx")
        }
        
    def query_by_jsonpath(self, jsonpath_expr: str) -> Union[List[Any], Any, None]:
        """
        使用JSONPath表达式查询RCU JSON数据
        
        Args:
            jsonpath_expr: JSONPath表达式字符串，例如 "$.actuator.inst[*].type"
            
        Returns:
            Union[List[Any], Any, None]: 匹配的结果列表，如果只有一个结果则返回该结果，未找到返回None
            
        Raises:
            ValueError: 如果RCU JSON数据未加载
            
        Examples:
            >>> parser = CSetParser()
            >>> parser.load_rcu_json("./test", "UMGBF52")
            >>> # 查询所有actuator的类型
            >>> types = parser.query_by_jsonpath("$.actuator.inst[*].type")
            >>> # 查询特定索引的actuator
            >>> actuator = parser.query_by_jsonpath("$.actuator.inst[?(@.idx==0)]")
        """
        if not self.rcu_json_data:
            raise ValueError("RCU JSON数据未加载，请先调用load_rcu_json方法")
            
        try:
            # 使用jsonpath库执行查询
            results = jsonpath(self.rcu_json_data, jsonpath_expr)
            
            # 如果没有匹配结果，返回None
            if not results:
                return None
                
            # 如果只有一个结果，直接返回该结果
            if len(results) == 1:
                return results[0]
                
            # 返回结果列表
            return results
            
        except Exception as e:
            print(f"JSONPath查询失败: {e}")
            return None


