import numpy as np
import pandas as pd
from typing import Tuple, Union, Iterator,List

def average_downsample_simple(
    x_data: Union[np.ndarray, pd.Series, list],
    y_data: Union[np.ndarray, pd.Series, list],
    target_points: int
) -> Tuple[np.ndarray, np.ndarray]:
    """
    基础版平均采样。
    适用于原始数据能一次性放入内存的情况。

    参数:
        x_data: 时间戳或索引数组，必须单调递增。
        y_data: 对应的数值数组。
        target_points: 目标采样点数。

    返回:
        降采样后的 (x_sampled, y_sampled) 的元组。
    """
    n = len(x_data)
    if n <= target_points:
        # 如果原始数据点不多于目标点数，直接返回原数据
        return np.asarray(x_data), np.asarray(y_data)

    # 计算采样步长 (stride)
    stride = max(1, n // target_points)

    # 使用等间距索引进行切片采样
    # 确保第一个和最后一个点被包含
    indices = np.arange(0, n, stride, dtype=np.int64)
    # 如果最后一个点未被包含，则强制添加
    if indices[-1] != n - 1:
        indices = np.append(indices, n - 1)

    x_sampled = np.asarray(x_data)[indices]
    y_sampled = np.asarray(y_data)[indices]

    return x_sampled, y_sampled