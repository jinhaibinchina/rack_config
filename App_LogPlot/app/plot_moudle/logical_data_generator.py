import numpy as np
import re
from typing import Dict, Tuple, List, Optional
from .common import PlotDataMapRef


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

class LogicalDataGenerator:
    """逻辑数据生成器类，支持逻辑运算生成新数据"""
    
    def __init__(self, src_datamap: PlotDataMapRef):
        self.datamap = src_datamap
        self.new_data_key = []
        self.logical_operators = {
            'and': np.logical_and,
            'or': np.logical_or,
            'not': np.logical_not,
            'xor': np.logical_xor,
        }
        
        self.comparison_operators = {
            '>': np.greater,
            '>=': np.greater_equal,
            '<': np.less,
            '<=': np.less_equal,
            '==': np.equal,
            '!=': np.not_equal,
        }

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
            'where': np.where,
            'all': np.all,
            'any': np.any,
        }

        self.last_scrip_context = None
        self.last_tips_context  = None
    def parse_script(self, script: str) -> Tuple[str, str]:
        """解析脚本，提取新数据名称和逻辑表达式"""
        # 格式: "新数据名称 = 逻辑表达式"
        match = re.match(r'^\s*([\w/]+)\s*=\s*(.+)$', script.strip())
        if not match:
            raise ValueError("脚本格式错误，应为: '新数据名称 = 逻辑表达式'")
        
        new_data_name = match.group(1)
        expression = match.group(2)
        return new_data_name, expression
    
    def preprocess_logical_expression(self, expression: str) -> str:
        """预处理逻辑表达式，替换逻辑运算符为函数调用"""
        # 首先替换数据引用，使用更精确的替换方法
        for key in self.datamap.data.keys():
            # 使用正则表达式确保只替换完整的数据键名
            pattern = r'\b' + re.escape(key) + r'\b'
            var_name = f"{key.replace('.', '_')}"

            # # 同时保留原始键名作为变量（如果原始键名是有效的Python标识符）
            # if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', key):
            #     local_vars[key] = y_data

            expression = re.sub(pattern, var_name, expression)
        
        # 替换逻辑运算符 - 使用更安全的方法
        # 先替换逻辑运算符，然后处理比较运算符
        expression = re.sub(r'\band\b', '&', expression)
        expression = re.sub(r'\bor\b', '|', expression)
        expression = re.sub(r'\bnot\b', '~', expression)
        expression = re.sub(r'\bxor\b', '^', expression)
        
        return expression
    
    def comparison_converter(self,code_string):
        """通用版本，支持各种变量命名约定"""
        
        operator_map = {
            '>': 'np.greater',
            '>=': 'np.greater_equal', 
            '<': 'np.less',
            '<=': 'np.less_equal',
            '==': 'np.equal',
            '!=': 'np.not_equal'
        }
        
        # 通用的变量名模式：支持字母、数字、下划线（包括双下划线）
        pattern = r'([a-zA-Z_][a-zA-Z0-9_]*(?:__[a-zA-Z0-9_]+)*)\s*([><]=?|==|!=)\s*([a-zA-Z_][a-zA-Z0-9_]*(?:__[a-zA-Z0-9_]+)*|-?\d+\.?\d*(?:[eE][-+]?\d+)?)'
        
        def replacer(match):
            left = match.group(1)
            op = match.group(2)
            right = match.group(3)
            
            if op in operator_map:
                return f'{operator_map[op]}({left}, {right})'
            return match.group(0)
        
        return re.sub(pattern, replacer, code_string)
    def evaluate_logical_expression(self, expression: str, x_data: np.ndarray) -> np.ndarray:
        """计算逻辑表达式，返回布尔值或数值结果"""
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
            
        expression = expression.replace('[', '_').replace(']', '_')
        # 预处理逻辑表达式
        processed_expression = self.preprocess_logical_expression(expression)
        print(f"替换逻辑运算符后的表达式{processed_expression}")
        # 准备局部变量字典
        local_vars = {'np': np, 'x_data': x_data}
        
        # 添加数据引用 - 使用正确的变量名格式
        for key in self.datamap.data.keys():
            _, y_data = self.datamap.get_data(key)
            # 创建变量名 - 与预处理中的格式保持一致
            var_name = f"{key.replace('.', '_').replace('[', '_').replace(']', '_')}"
            local_vars[var_name] = y_data

            # 同时保留原始键名作为变量（如果原始键名是有效的Python标识符）
            if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', key):
                local_vars[key] = y_data

        processed_expression = replace_variable_dot(processed_expression)
            
        print(f"替换变量名中的小数点{processed_expression}\n") 
        processed_expression =self.comparison_converter(processed_expression)
        print(f"替换比较运算符{processed_expression}\n")
        # 确保数据引用在表达式中使用正确的变量名
        # 预处理已经处理了数据引用替换，这里不需要重复处理
        
        # 特殊处理max和min函数 - 确保只替换函数调用
        processed_expression = re.sub(r'\bmax\s*\(', 'np.maximum(', processed_expression)
        processed_expression = re.sub(r'\bmin\s*\(', 'np.minimum(', processed_expression)
        
        # 特殊处理mean函数
        mean_pattern = r'\bmean\s*\(([^)]+)\)'
        mean_matches = re.finditer(mean_pattern, processed_expression)
        
        matches_list = list(mean_matches)
        for match in reversed(matches_list):
            params_str = match.group(1)
            params = [param.strip() for param in params_str.split(',')]
            
            if len(params) == 1:
                old_mean_call = match.group(0)
                new_mean_call = f"np.mean({params_str})"
                start, end = match.span()
                processed_expression = processed_expression[:start] + new_mean_call + processed_expression[end:]
            elif len(params) > 1:
                mean_expr = f"({' + '.join(params)}) / {len(params)}"
                old_mean_call = match.group(0)
                new_mean_call = f"({mean_expr})"
                start, end = match.span()
                processed_expression = processed_expression[:start] + new_mean_call + processed_expression[end:]
		# 处理其他函数 - 确保np命名空间正确
        for func_name, func in self.script_functions.items():
            if func_name not in ['max', 'min', 'mean']:
                # 使用更精确的正则表达式来匹配函数调用，避免重复替换
                pattern = r'(?<!np\.)\b' + re.escape(func_name) + r'\s*\('
                replacement = f'np.{func_name}('
                processed_expression = re.sub(pattern, replacement, processed_expression)
        
        # 添加x_data引用
        processed_expression = re.sub(r'\bx\b', 'x_data', processed_expression)
        
        try:
            # 安全地计算表达式 - 修复np命名空间问题
            result = eval(processed_expression, {'np': np}, local_vars)
            
            # 确保结果是数组类型
            result_array = np.array(result, dtype=bool)
            
            # 检查结果是否是标量或0维数组
            if result_array.ndim == 0 or np.isscalar(result_array):
                # 如果是标量，扩展到相同长度
                result_array = np.full_like(x_data, result_array)
            elif len(result_array) != len(x_data):
                # 如果是差分操作，调整x_data长度
                if len(result_array) == len(x_data) - 1:
                    x_data = x_data[:-1]
                    result_array = result_array
                else:
                    raise ValueError(f"结果长度({len(result_array)})与x_data长度({len(x_data)})不匹配")
            
            return result_array
        except Exception as e:
            raise ValueError(f"逻辑表达式计算错误: {e}")
    def generate_logical_data(self, script: str) -> Tuple[str, list]:
        """执行逻辑数据生成脚本，返回新数据名称"""
        new_data_name, expression = self.parse_script(script)
        
        # 获取x数据（使用第一个数据的x轴）
        first_key = next(iter(self.datamap.data.keys()))
        x_data, _ = self.datamap.get_data(first_key)
        
        # 计算新数据
        y_data = self.evaluate_logical_expression(expression, x_data)
        
        # 添加到数据映射
        # self.datamap.add_data(new_data_name, x_data, y_data)
        # self.new_data_key.append(new_data_name)
        
        return new_data_name,y_data.tolist()
    
    def get_available_logical_operators(self) -> List[str]:
        """获取可用的逻辑运算符列表"""
        return list(self.logical_operators.keys())
    
    def get_available_comparison_operators(self) -> List[str]:
        """获取可用的比较运算符列表"""
        return list(self.comparison_operators.keys())
    
    def get_available_functions(self) -> List[str]:
        """获取可用的函数列表"""
        return list(self.script_functions.keys())
    
    def get_available_data_keys(self) -> List[str]:
        """获取可用的数据键列表"""
        c = [x for x in self.datamap.data.keys() if x not in self.new_data_key]
        return c
	
    def validate_script(self, script: str) -> Tuple[bool, str]:
        """验证脚本语法"""
        try:
            condition_name, expression = self.parse_script(script)
            print(f"提取到的数据名{condition_name},表达式{expression}")
            # 检查数据名称是否已存在
            # if new_data_name in self.datamap.data:
            #     return False, f"数据名称 '{new_data_name}' 已存在"
            
            # 检查数据名称格式
            if not re.match(r'^[\w/]+$', condition_name):
                return False, "数据名称只能包含字母、数字、下划线和斜杠 "
            
            # 测试表达式计算
            if not self.datamap.data:
                return False, "没有可用的数据源"
                
            first_key = next(iter(self.datamap.data.keys()))
            x_data, _ = self.datamap.get_data(first_key)
            self.evaluate_logical_expression(expression, x_data)
            
            return True, "脚本验证通过"
        except Exception as e:
            return False, str(e)
    
    def clear_generated_data(self):
        """清除所有生成的数据"""
        for key in self.new_data_key:
            if key in self.datamap.data:
                del self.datamap.data[key]
        self.new_data_key.clear()
    
    def get_generated_data_keys(self) -> List[str]:
        """获取所有生成的数据键"""
        return self.new_data_key.copy()
    
    def get_logical_expression_syntax_help(self) -> str:
        """获取逻辑表达式语法帮助文档"""
        help_text = """
        balabla
        baddd
        """
        return help_text.strip()


class LogicalScriptDialog:
    """逻辑脚本输入对话框"""
    
    def __init__(self, generator: LogicalDataGenerator):
        self.generator = generator
        self.script_history = []
    
    def get_logical_script_examples(self) -> List[str]:
        """获取逻辑脚本示例"""
        examples = [
            "threshold_data = data_father1_data1 > 0.5",
            "range_data = (data_father1_data1 >= 0.2) and (data_father1_data1 <= 0.8)",
            "combined_logic = (data_father1_data1 > 0) or (data_father2_data1 < 0)",
            "conditional_data = np.where(data_father1_data1 > 0, 1, -1)",
            "filtered_signal = data_father1_data1 * (data_father1_data1 > 0.3)",
            "xor_condition = data_father1_data1 > 0.5 xor data_father2_data1 < 0.2",
            "complex_logic = (data_father1_data1 > mean(data_father1_data1)) and (data_father2_data1 < 0)",
            "multi_condition = (data_father1_data1 > 0.1) and (data_father1_data1 < 0.9) and not (data_father2_data1 == 0)",
        ]
        return examples
    
    def format_data_reference(self, data_key: str) -> str:
        """格式化数据引用"""
        return f"data_{data_key.replace('/', '_')}"

	# 测试函数
def test_logical_generator():
    """测试逻辑数据生成器"""
    # 创建一个简单的测试数据映射
    class TestDataMap:
        def __init__(self):
            self.data = {
                'test/data1': (np.linspace(0, 10, 100), np.sin(np.linspace(0, 10, 100))),
                'test/data2': (np.linspace(0, 10, 100), np.cos(np.linspace(0, 10, 100)))
            }
        
        def get_data(self, key):
            return self.data[key]
        
        def add_data(self, key, x_data, y_data):
            self.data[key] = (x_data, y_data)
    
    # 创建测试实例
    test_map = TestDataMap()
    generator = LogicalDataGenerator(test_map)
    
    # 测试逻辑表达式 - 使用正确的数据引用格式
    test_scripts = [
        "threshold = data_test_data1 > 0.5",
        "range_check = (data_test_data1 >= -0.5) and (data_test_data1 <= 0.5)",
        "combined = (data_test_data1 > 0) or (data_test_data2 < 0)",
        "conditional = np.where(data_test_data1 > 0, data_test_data1, 0)",
    ]
    
    print("测试逻辑数据生成器:")
    print("=" * 50)
    
    for script in test_scripts:
        try:
            result_key = generator.generate_logical_data(script)
            x_data, y_data = test_map.get_data(result_key)
            print(f"脚本: {script}")
            print(f"生成数据: {result_key}")
            print(f"数据形状: {y_data.shape}")
            print(f"唯一值: {np.unique(y_data)}")
            print(f"y值: {y_data}")
            print("-" * 30)
        except Exception as e:
            print(f"错误: {script} -> {e}")
            print("-" * 30)


if __name__ == "__main__":
    test_logical_generator()

