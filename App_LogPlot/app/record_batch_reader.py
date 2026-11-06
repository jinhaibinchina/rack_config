import pyarrow as pa
from contextlib import contextmanager
from typing import Iterator, Dict, Any,Optional
import pandas as pd
import time
from functools import wraps

def time_it(func):
    """计算函数执行时间的装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.perf_counter()  # 高精度计时
        result = func(*args, **kwargs)    # 执行原函数
        end_time = time.perf_counter()
        elapsed_time = end_time - start_time
        
        # 格式化输出时间（根据时长自动选择合适的单位）
        if elapsed_time < 1e-6:
            time_str = f"{elapsed_time * 1e9:.3f} ns"
        elif elapsed_time < 1e-3:
            time_str = f"{elapsed_time * 1e6:.3f} μs"
        elif elapsed_time < 1:
            time_str = f"{elapsed_time * 1e3:.3f} ms"
        else:
            time_str = f"{elapsed_time:.3f} s"
        
        print(f"[{func.__name__}] 执行时间: {time_str}")
        return result
    return wrapper



@contextmanager
# @time_it
def open_feather_reader(file_path: str) -> Iterator[pa.ipc.RecordBatchFileReader]:
    """
    安全打开 Feather 文件的上下文管理器
    
    Args:
        file_path: 文件路径
        
    Yields:
        RecordBatchFileReader 对象
    """
    reader = None
    try:
        mmap = pa.memory_map(file_path)
        reader = pa.ipc.open_file(mmap)
        yield reader
    finally:
        if reader is not None:
            mmap.close()  
            


@time_it
def get_row_data_safe(file_path: str, row_index: int ,batch_offsets:list,batch_num_rows:list,total_rows:int ) -> pd.DataFrame:
    """
    安全的单行数据获取函数
    
    Args:
        file_path: 文件路径
        row_index: 行索引
        batch_offsets:批次列表
        total_rows:总行数
    Returns:
        行数据字典
    """

    with open_feather_reader(file_path) as reader:
        # print(row_index,total_rows)
        # 检查行索引有效性
        if row_index < 0 or row_index >= total_rows:
            return None
        
        # 查找对应的批次
        batch_index = -1
        for i, offset in enumerate(batch_offsets):
            # batch = reader.get_batch(i)
            if offset <= row_index < offset + batch_num_rows[i]:
                batch_index = i
                break
        
        if batch_index == -1:
            return None
        
        # 获取数据
        batch = reader.get_batch(batch_index)
        local_index = row_index - batch_offsets[batch_index]
        df = batch.to_pandas()
        # print(batch_index,local_index)
        if local_index < len(df):
            return df.iloc[[local_index]]
        
        return None


