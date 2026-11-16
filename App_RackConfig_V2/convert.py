import os
import sys

def convert_with_error_handling(input_file, output_file):
    """
    带错误处理的转换函数
    """
    try:
        # 检查输入文件是否存在
        if not os.path.exists(input_file):
            print(f"错误：文件 '{input_file}' 不存在")
            return False
        
        # 检查文件是否为空
        if os.path.getsize(input_file) == 0:
            print(f"警告：文件 '{input_file}' 为空")
            # 创建空的 UTF-8 文件
            with open(output_file, 'w', encoding='utf-8') as f:
                pass
            return True
        
        # 转换文件
        with open(input_file, 'r', encoding='utf-16le') as f_in:
            with open(output_file, 'w', encoding='utf-8') as f_out:
                for line in f_in:
                    f_out.write(line)
        
        print(f"转换成功：'{input_file}' -> '{output_file}'")
        return True
        
    except UnicodeDecodeError as e:
        print(f"解码错误：文件可能不是 UTF-16 LE 编码")
        print(f"错误详情：{e}")
        return False
    except Exception as e:
        print(f"转换失败：{e}")
        return False

# 使用示例
if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法：python convert.py <输入文件> <输出文件>")
        sys.exit(1)
    
    input_path = sys.argv[1]
    output_path = sys.argv[2]
    success = convert_with_error_handling(input_path, output_path)
    sys.exit(0 if success else 1)