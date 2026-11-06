import numpy as np
import re
from typing import Dict, Tuple, List, Optional
from .common import PlotDataMapRef,rcd_data_bridge


def replace_variable_dot(expression):
        """
        只替换变量名中的小数点，不替换数字中的小数点
        """
        # 匹配变量名中的小数点：字母或下划线开头，包含小数点，后面跟着字母、数字或下划线
        pattern = r'\b[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*\b'
        
        def replace_dot(match):
            # 将匹配到的变量名中的小数点替换为下划线
            return match.group().replace('.', '_')
        
        # 使用 re.sub 进行替换
        result = re.sub(pattern, replace_dot, expression)
        return result

class DataTransformer:
    """数据转换器类，支持脚本运算生成新数据"""
    
    def __init__(self, src_datamap: PlotDataMapRef):
        self.datamap = src_datamap
        self.__new_data_key = []
        self.script_functions = {
            'sin': np.sin,
            'cos': np.cos,
            'tan': np.tan,
            'exp': np.exp,
            'log': np.log,
            'log10': np.log10,
            'sqrt': np.sqrt,
            'abs': np.abs,
            'max': np.maximum,
            'min': np.minimum,
            'mean': np.mean,
            'sum': np.sum,
            'diff': np.diff,
            'cumsum': np.cumsum,
            'cumprod': np.cumprod,
            'arcsin': np.arcsin,
            'arccos': np.arccos,
            'arctan': np.arctan,
            'sinh': np.sinh,
            'cosh': np.cosh,
            'tanh': np.tanh,
            'floor': np.floor,
            'ceil': np.ceil,
            'round': np.round,
            'clip': np.clip,
            'power': np.power,
            'mod': np.mod,
        }
    def parse_script(self, script: str) -> Tuple[str, str]:
        """解析脚本，提取新数据名称和表达式"""
        # 格式: "新数据名称 = 表达式"
        match = re.match(r'^\s*([\w/\.]+)\s*=\s*(.+)$', script.strip())
        if not match:
            raise ValueError("脚本格式错误，应为: '新数据名称 = 表达式'")
        
        new_data_name = match.group(1)
        expression = match.group(2)
        print(f'new_data_name={new_data_name},expression={expression}\n')
        return new_data_name, expression
    
    def evaluate_expression(self, expression: str, x_data: np.ndarray) -> np.ndarray:
        """计算表达式，返回y数据"""
        # 安全检查：禁止使用危险的内置函数
        dangerous_patterns = [
            r'__.*__',  # 双下划线方法
            r'import\s+',  # import语句
            r'exec\s*\(',  # exec函数
            r'eval\s*\(',  # eval函数
            r'compile\s*\(',  # compile函数
            r'open\s*\(',  # open函数
            r'file\s*\(',  # file函数
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, expression, re.IGNORECASE):
                raise ValueError(f"表达式包含危险模式: {pattern}")
        
        # 准备局部变量字典
        local_vars = {'np': np, 'x_data': x_data}
        # 添加数据引用
        for key in self.datamap.data.keys():
            _, y_data = self.datamap.get_data(key)
            # 创建有效的Python变量名 - 替换特殊字符为下划线
            var_name = key.replace('.', '_').replace('[', '_').replace(']', '_')
            local_vars[var_name] = y_data
            
            # 同时保留原始键名作为变量（如果原始键名是有效的Python标识符）
            if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', key):
                local_vars[key] = y_data
        # # 替换数据引用
        
        expression = expression.replace('[', '_').replace(']', '_')
        expression = replace_variable_dot(expression)

        print(expression)

        # 特殊处理max和min函数 - 确保只替换函数调用
        expression = re.sub(r'\bmax\s*\(', 'np.maximum(', expression)
        expression = re.sub(r'\bmin\s*\(', 'np.minimum(', expression)
        
        # 特殊处理mean函数 - 检查参数数量并正确处理
        # 使用正则表达式匹配mean函数调用并检查参数
        mean_pattern = r'\bmean\s*\(([^)]+)\)'
        mean_matches = re.finditer(mean_pattern, expression)
        
        # 需要从后往前处理，避免替换影响后续匹配
        matches_list = list(mean_matches)
        for match in reversed(matches_list):
            # 检查参数数量
            params_str = match.group(1)
            params = [param.strip() for param in params_str.split(',')]
            
            if len(params) == 1:
                # 单个参数，使用np.mean
                old_mean_call = match.group(0)  # 整个匹配的字符串
                new_mean_call = f"np.mean({params_str})"
                
                # 替换整个匹配的部分
                start, end = match.span()
                expression = expression[:start] + new_mean_call + expression[end:]
            elif len(params) > 1:
                # 如果mean函数有多个参数，转换为元素级平均
                mean_expr = f"({' + '.join(params)}) / {len(params)}"
                old_mean_call = match.group(0)  # 整个匹配的字符串
                new_mean_call = f"({mean_expr})"
                
                # 替换整个匹配的部分
                start, end = match.span()
                expression = expression[:start] + new_mean_call + expression[end:]
        
        # 处理其他函数
        for func_name, func in self.script_functions.items():
            if func_name not in ['max', 'min', 'mean']:  # 已经处理过max、min和mean
                # 使用单词边界确保只匹配函数名，而不是变量名的一部分
                pattern = r'\b' + re.escape(func_name) + r'\s*\('
                replacement = f'np.{func_name}('
                expression = re.sub(pattern, replacement, expression)
		# 添加x_data引用 - 使用正则表达式确保只替换独立的x变量
        expression = re.sub(r'\bx\b', 'x_data', expression)
        print(local_vars)
        try:
            # 安全地计算表达式
            result = eval(expression, {'np': np}, local_vars)
            
            # 确保结果是数组类型
            result_array = np.array(result, dtype=float)
            
            # 检查结果是否是标量或0维数组
            if result_array.ndim == 0 or np.isscalar(result_array):
                # 如果是标量，扩展到相同长度
                result_array = np.full_like(x_data, result_array)
            elif len(result_array) != len(x_data):
                # 如果是差分操作，调整x_data长度
                if len(result_array) == len(x_data) - 1:
                    # 对于差分操作，截断x_data以匹配结果长度
                    x_data = x_data[:-1]
                    result_array = result_array
                else:
                    raise ValueError(f"结果长度({len(result_array)})与x_data长度({len(x_data)})不匹配")
            
            return result_array
        except Exception as e:
            raise ValueError(f"表达式计算错误: {e}")
        
    def transform_data(self, script: str) -> str:
        """执行数据转换脚本，返回新数据名称"""
        new_data_name, expression = self.parse_script(script)
        
        # 获取x数据（使用第一个数据的x轴）
        first_key = next(iter(self.datamap.data.keys()))
        x_data, _ = self.datamap.get_data(first_key)
        
        # 计算新数据
        y_data = self.evaluate_expression(expression, x_data)
        
        # 添加到数据映射
        self.datamap.add_data(new_data_name, x_data, y_data)
        self.__new_data_key.append(new_data_name)
        
        return new_data_name
    
    def get_available_functions(self) -> List[str]:
        """获取可用的函数列表"""
        return list(self.script_functions.keys())
    
    def get_available_data_keys(self) -> List[str]:
        """获取可用的数据键列表"""
        c = [x for x in self.datamap.data.keys() if x not in self.__new_data_key]
        return c
	
    def validate_script(self, script: str) -> Tuple[bool, str]:
        """验证脚本语法"""
        try:
            new_data_name, expression = self.parse_script(script)
            
            # 检查数据名称是否已存在
            if new_data_name in self.datamap.data:
                return False, f"数据名称 '{new_data_name}' 已存在"
            
            # 检查数据名称格式
            if not re.match(r'^[\w/]+$', new_data_name):
                return False, "数据名称只能包含字母、数字、下划线和斜杠"
            
            # 测试表达式计算
            if not self.datamap.data:
                return False, "没有可用的数据源"
                
            first_key = next(iter(self.datamap.data.keys()))
            x_data, _ = self.datamap.get_data(first_key)
            self.evaluate_expression(expression, x_data)
            
            return True, "脚本验证通过"
        except Exception as e:
            return False, str(e)
    
    def clear_generated_data(self):
        """清除所有生成的数据"""
        for key in self.__new_data_key:
            if key in self.datamap.data:
                del self.datamap.data[key]
        self.__new_data_key.clear()
    
    def get_generated_data_keys(self) -> List[str]:
        """获取所有生成的数据键"""
        return self.__new_data_key.copy()
    
    
    def get_expression_syntax_help(self) -> str:
        """获取表达式语法帮助文档"""
        help_text = """
            aaa,
            ddd
            """
        
        return help_text.strip()


class ScriptDialog:
    """脚本输入对话框"""
    
    def __init__(self, transformer: DataTransformer):
        self.transformer = transformer
        self.script_history = []
    
    def get_script_examples(self) -> List[str]:
        """获取脚本示例"""
        examples = [
            "new_data = sin(x) + cos(x)",
            "filtered_data = data_father1_data1 * 0.5 + 2",
            "derivative = diff(data_father1_data1)",
            "integral = cumsum(data_father1_data1)",
            "combined = data_father1_data1 + data_father2_data1",
            "scaled_data = data_father1_data1 * 2 - 1",
        ]
        return examples