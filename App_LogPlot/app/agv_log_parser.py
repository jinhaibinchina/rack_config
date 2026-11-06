#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AGV日志解析模块
"""

import os
import re
import json
from typing import List, Dict, Optional
from datetime import datetime, timedelta


class AGVLogParser:
    """AGV日志解析器"""
    
    def __init__(self):
        self.software_id = None
        self.main_version = None
        self.mcu_version = None
        self.car_type = "CTU"
        self.commands = {}
        self.agv_log_files = []
        
    def clear(self):
        """清空所有已有的数据"""
        self.software_id = None
        self.main_version = None
        self.mcu_version = None
        self.car_type = "CTU"
        self.commands.clear()
        self.agv_log_files.clear()

    def parse_log_folder(self, folder_path: str):
        """
        解析日志文件夹中的AGV日志
        
        Args:
            folder_path: 日志文件夹路径
        """
        # 清空之前的数据
        self.clear()
        # 查找符合格式的AGV日志文件
        agv_log_files = self._find_agv_log_files(folder_path)
        
        if not agv_log_files:
            print(f"未在 {folder_path} 中找到AGV日志文件")
            return
        self.agv_log_files = agv_log_files
        # 解析小车信息, 只解析第一个文件
        self._parse_car_info(agv_log_files[0])
        
    def _find_agv_log_files(self, folder_path: str):
        """
        查找文件夹中的AGV日志文件
        
        Args:
            folder_path: 文件夹路径
            
        Returns:
            List[str]: AGV日志文件路径列表
        """
        agv_log_files = []
        pattern = r'^\d+_AGV_.*_CASTOR\.txt$'
        
        try:
            for root_dir, dirs, files in os.walk(folder_path):
                for filename in files:
                    if re.match(pattern, filename):
                        file_path = os.path.join(root_dir, filename)
                        if os.path.isfile(file_path):
                            agv_log_files.append(file_path)
        except Exception as e:
            print(f"查找AGV日志文件时出错: {e}")
            
        return agv_log_files
        
    def _parse_car_info(self, file_path: str) -> bool:
        """
        解析单个AGV日志文件
        
        Args:
            file_path: 日志文件路径
            
        Returns:
            bool: 解析是否成功
        """
        try:
            # 读取文件内容（GBK编码）
            with open(file_path, 'r', encoding='gbk', errors='ignore') as f:
                content = f.read()

            # 提取软标
            pattern = r'software_id\s*=\s*([^\s,]+)'
            match = re.search(pattern, content)
            if match:
                self.software_id = match.group(1).strip()
            
            # 提取版本信息
            pattern = r'SOFTWARE_VERSION\s*:\s*([^\s,]+)'
            match = re.search(pattern, content)
            if match:
                self.main_version = match.group(1).strip()
            
            # 提取RCU 版本信息
            pattern = r'MCU_VERSION\s*:\s*([^\s,]+)'
            match = re.search(pattern, content)
            if match:
                self.mcu_version = match.group(1).strip()

            # 提取车型
            if 'CTU' in self.main_version:
                self.car_type = 'CTU'
            elif 'STU' in self.main_version:
                self.car_type = 'STU'
            else:
                self.car_type = 'CTU'
            
            return True
            
        except Exception as e:
            print(f"解析日志文件 {file_path} 时出错: {e}")
            return False
             
    def parse_cmd_by_regex(self, cmd_title:str, regex_pattern: str):
        """
        提取命令信息
        """
        self.commands[cmd_title] = []
        for file_path in self.agv_log_files:
            with open(file_path, 'r', encoding='gbk', errors='ignore') as f:
                content = f.read()
            # 正则表达式 regex_pattern 匹配 content
            matches = re.findall(regex_pattern, content, re.MULTILINE)
            if matches:
                for match in matches:
                    # 写一个正则表达式匹配时间和打印序号[2025-11-27 15:42:26][07269]
                    timestamp_pattern = r'\[(.*?)\]\[(\d+)\]'
                    timestamp_match = re.search(timestamp_pattern, match)
                    if timestamp_match:
                        timestamp_str = timestamp_match.group(1)
                        line_num = int(timestamp_match.group(2))
                        # 将时间字符串转换为datetime对象
                        try:

                            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                            # 将行号作为微秒
                            microseconds = line_num % 1000000
                            enhanced_timestamp = timestamp.replace(microsecond=microseconds)
                            command_info = {
                                'time': enhanced_timestamp,  # 增强的时间对象，用于排序
                                'context': match
                            }
                            self.commands[cmd_title].append(command_info)
                        except ValueError as e:
                            print(f"时间解析错误: {e}")
        # 按时间对命令进行排序
        self.commands[cmd_title].sort(key=lambda x: x['time'])
        
    def get_software_id(self) -> str:
        """
        获取软标
        
        Returns:
            str: 软标
        """
        return self.software_id
        
    def get_main_version(self) -> str:
        """
        获取版本信息
        """
        return self.main_version

    def get_mcu_version(self) -> str:
        return self.mcu_version

    def get_car_type(self) -> str:
        """
        获取车型
        
        Returns:
            str: 车型
        """
        return self.car_type
        
    def get_context_by_regex(self, regex_pattern: str) -> List[Dict]:
        """
        根据正则表达式匹配命令
        """
        matches_all = []
        for file_path in self.agv_log_files:
            with open(file_path, 'r', encoding='gbk', errors='ignore') as f:
                content = f.read()
            # 正则表达式 regex_pattern 匹配 content
            matches = re.findall(regex_pattern, content, re.MULTILINE)
            matches_all.extend(matches)
        return matches_all
        
    def get_command_by_time(self, cmd_title, target_time: datetime) -> Optional[str]:
        """
        根据时间获取最近的命令
        
        Args:
            target_time: 目标时间
            
        Returns:
            Optional[str]: 命令字符串，未找到返回None
        """
        if cmd_title not in self.commands:
            return None
        commands = self.commands[cmd_title] 
        # 找到时间小于等于目标时间的最近命令
        # 往后加1秒, AGV 日志 命令时间最小单位是s
        target_dt_plus_1s = target_time + timedelta(seconds=1)
        closest_cmd = None
        for cmd in commands:
            if cmd['time'] <= target_dt_plus_1s:
                if closest_cmd is None or cmd['time'] > closest_cmd['time']:
                    closest_cmd = cmd
                    
        return closest_cmd['context'] if closest_cmd else None

    def get_log_files(self):
        return self.agv_log_files



# 测试代码
if __name__ == "__main__":
    # 创建测试实例
    parser = AGVLogParser()
    
    # 测试解析
    test_folder = "test_output"
    parser.parse_log_folder(test_folder)
    print("软标:", parser.get_software_id())
    print("车型:", parser.get_car_type())
    print("版本信息:", parser.get_main_version())
    
    # 测试命令匹配
    pattern = r"^.*rcu_linear_set_cmd.*idx:0.*$"
    parser.parse_cmd_by_regex("linear0" ,pattern)
    matched = parser.get_command_by_time("linear0", datetime(2025, 11, 27, 16, 22, 32))
    print("匹配的命令:", matched)
    pattern = r"^.*rcu_linear_set_cmd.*idx:1.*$"
    matched = parser.get_context_by_regex(pattern)
    print("匹配的命令:", matched)

