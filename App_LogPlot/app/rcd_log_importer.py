"""
RCD日志导入模块
支持导入CSV格式的RCD日志文件，预处理为Parquet格式后按需加载数据
"""

import os
import pandas as pd
from typing import List, Optional, Union
from pathlib import Path
from datetime import datetime, timedelta
import time
import threading
import numpy as np
from PySide6.QtCore import QObject, Signal
import gc

from .record_batch_reader import get_row_data_safe
import pyarrow as pa
import pyarrow.feather as feather


class RcdLogImporter(QObject):
    """RCD日志导入器"""

    # 定义信号
    logs_imported = Signal(bool)  # (导入是否成功)

    def __init__(self):
        super().__init__()
        self.log_folder_path: Optional[str] = None
        self.csv_files: List[str] = []
        self.headers: List[str] = []
        self.time: List = []
        self._parquet_file: Optional[str] = None
        # 文件监控相关
        self._is_monitoring: bool = False
        #读取行数据用
        self._feather_file: Optional[str]  = None
        self._enable_feather: bool = False
        
    def clear_data(self):
        """清空所有已加载的数据"""
        self.headers.clear()
        self.time.clear()
        self.csv_files.clear()
        self._parquet_file = None
        self._feather_file = None
        self.log_folder_path = None

    def _is_valid_csv_file(self, file_path: str) -> bool:
        """
        判断文件是否为有效的CSV文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否为有效的CSV文件
        """
        # 检查文件是否存在
        if not os.path.exists(file_path):
            print(f"文件不存在，跳过: {file_path}")
            return False
        
        # 检查是否为文件
        if not os.path.isfile(file_path):
            print(f"不是文件，跳过: {file_path}")
            return False
        
        # 检查文件扩展名是否为.csv
        if not file_path.lower().endswith('.csv'):
            print(f"不是CSV文件，跳过: {file_path}")
            return False
        
        return True
    
    def _filter_valid_csv_files(self, file_paths: List[str]) -> List[str]:
        """
        过滤出有效的CSV文件
        
        Args:
            file_paths: 文件路径列表
            
        Returns:
            List[str]: 有效的CSV文件路径列表
        """
        valid_files = []
        for file_path in file_paths:
            if self._is_valid_csv_file(file_path):
                valid_files.append(file_path)
        return valid_files


    def import_logs(self, folder_path: str, file_list: Optional[List[str]] = None, clear_data=True) -> bool:
        """
        导入指定文件夹中的RCD日志（预处理为Parquet格式，然后按需加载数据）
        
        Args:
            folder_path: 日志文件夹路径
            file_list: 可选的文件列表，如果提供则直接使用该列表，不扫描文件夹
            
        Returns:
            bool: 导入是否成功
        """
        # 清空之前的数据
        if clear_data:
            self.clear_data()

        try:
            # 获取CSV文件列表
            csv_files = []
            folder_path_obj = None
            
            if file_list:
                # 使用提供的文件列表
                print(f"使用提供的文件列表，共 {len(file_list)} 个文件")
                csv_files = self._filter_valid_csv_files(file_list)
                print(f"过滤后有效文件: {len(csv_files)} 个")                
                # 检查是否找到CSV文件
                if not csv_files:
                    print("未找到CSV文件")
                    # 直接返回导入结果
                    self.logs_imported.emit(False)
                    return False
                # 从第一个有效文件提取文件夹路径
                folder_path_obj = Path(os.path.dirname(os.path.abspath(csv_files[0])))
            else:
                # 使用文件夹路径扫描CSV文件
                folder_path_obj = Path(folder_path)
                
                # 检查路径是否存在
                if not folder_path_obj.exists():
                    print(f"日志文件夹路径不存在: {folder_path_obj}")
                    return False

                # 获取所有CSV文件（包括子文件夹）
                csv_files = [str(f) for f in folder_path_obj.rglob("*.csv")]


            # 检查是否找到CSV文件
            if not csv_files:
                print("未找到CSV文件")
                # 直接返回导入结果
                self.logs_imported.emit(False)
                return False
            
            # 保存日志文件夹路径
            self.log_folder_path = str(folder_path_obj)

            # 文件夹下存在 log_data.parquet 则不再进行csv转换，使用旧的Parquet文件
            parquet_path = folder_path_obj / "log_data.parquet"
            if not parquet_path.exists():
                self._csv_to_parquet(csv_files)
            else:
                self._parquet_file = parquet_path
                print("使用旧parquet，不执行转换")                

            print(f"找到 {len(csv_files)} 个CSV文件")
            # 统计加载表头的时间
            header_start_time = time.time()
            # 使用pandas加载第一个文件获取表头
            first_df = pd.read_csv(csv_files[0], encoding='gbk', nrows=1)
            # 获取表头
            self.headers = list(first_df.columns)
            header_end_time = time.time()
            header_time = header_end_time - header_start_time
            print(f"加载表头耗时: {header_time:.4f} 秒")

            # 加载所有CSV文件的时间戳和时间列
            self._load_time_data()

            # 发送导入完成信号
            # self._parquet_to_feather(folder_path)
            self._notify_when_import_files()

            self.logs_imported.emit(True)
            print("日志导入完成")
            return True

        except Exception as e:
            print(f"导入日志时发生错误: {str(e)}")
            # 发送导入失败信号
            self.logs_imported.emit(False)
            return False


    def _load_time_data(self):
        """加载时间数据"""
        try:
            # 使用get_column_data加载time_ts和date_time列
            time_columns = ['time_ts', 'date_time']
            time_data_result = self.get_column_data(time_columns)

            # 检查是否成功获取到数据
            if time_data_result.empty:
                print("无法获取时间数据: 未能成功读取time_ts或date_time列")
                return

            # 检查必要列是否存在
            if 'time_ts' not in time_data_result.columns or 'date_time' not in time_data_result.columns:
                print("无法获取时间数据: 缺少必要的time_ts或date_time列")
                return

            time_ts_data = time_data_result['time_ts']
            date_time_data = time_data_result['date_time']

            if len(time_ts_data) != len(date_time_data):
                print("时间数据长度不匹配")
                return

            start_time = time.time()
            
            # 1. 预处理：确保数据类型正确
            time_data_result = time_data_result.copy()
            time_data_result['time_ts'] = pd.to_numeric(time_data_result['time_ts'], errors='coerce')
            
            # 2. 向量化datetime转换
            datetime_objs = pd.to_datetime(
                time_data_result['date_time'].values,
                format='%Y_%m_%d_%H_%M_%S'
            )

            # 3. 找到第一个秒发生变化的位置作为基准时间
            # 先获取第一个时间点
            first_datetime = datetime_objs[0]
            
            # 找到第一个秒发生变化的位置（即第一个与起始时间秒数不同的位置）
            start_idx = 0
            for i in range(1, min(1000, len(datetime_objs))):  # 限制搜索范围，避免过长搜索
                if datetime_objs[i].second != first_datetime.second:
                    start_idx = i
                    break
            
            # 获取基准时间点
            base_ts = time_data_result['time_ts'].iloc[start_idx]
            base_datetime = datetime_objs[start_idx]
            
            print(f"使用第{start_idx}行作为基准时间点: {base_datetime}, time_ts: {base_ts}")


            # 4. 向量化时间差计算（相对于基准时间点）
            time_diff_ms = time_data_result['time_ts'].values - base_ts

            # 5. 使用numpy进行高效时间计算
            # 将毫秒转换为纳秒（pandas datetime内部使用纳秒）
            time_diff_ns = (time_diff_ms * 1_000_000).astype('timedelta64[ns]')

            # 6. 向量化时间戳计算
            new_datetimes = base_datetime + time_diff_ns

            # 7. 高效格式化
            # 直接使用pandas的向量化strftime
            time_formatted = pd.Series(new_datetimes).dt.strftime('%Y-%m-%d %H:%M:%S.%f')

            # 保留3位毫秒（截取最后3位微秒）
            time_formatted = time_formatted.str[:-3]
            self.time = time_formatted.tolist()
            
            end_time = time.time()
            print(f"时间转换耗时: {end_time - start_time:.2f} 秒")
            
        except Exception as e:
            print(f"加载时间数据时发生错误: {str(e)}")

    def get_time_list(self, type='str'):
        """
        获取时间列表
        
        Args:
            type: 返回类型，'str'表示字符串格式，'datetime'表示datetime对象格式
            
        Returns:
            List[str] 或 List[datetime]: 时间列表
        """
        if type == 'str':
            return self.time.copy()

        else:
            if self.time is not None and len(self.time) > 0:
                return pd.to_datetime(self.time, format='%Y-%m-%d %H:%M:%S.%f')
        return []


    def get_headers(self) -> List[str]:
        """
        获取CSV表头列表
        
        Returns:
            List[str]: 表头列表
        """
        return self.headers.copy()
 
    def get_column_data(self, column_names: Union[str, List[str]]) -> pd.DataFrame:
        """
        获取指定列的数据（从Parquet文件中按需加载）
        
        Args:
            column_names: 列名或列名列表
            
        Returns:
            pd.DataFrame: 包含列数据的DataFrame
        """
        if not self._parquet_file or not os.path.exists(self._parquet_file):
            print("Parquet文件不存在")
            return None

        if isinstance(column_names, str):
            column_names = [column_names]

        # 剔除不在表头的列
        column_names = [col for col in column_names if col in self.headers]  # 确保列名在表头中存在

        try:
            # 统计读取数据的耗时
            start_time = time.time()
            # 直接从Parquet文件中读取指定列
            result_df = pd.read_parquet(self._parquet_file, columns=column_names)
            end_time = time.time()
            elapsed_time = end_time - start_time
            print(f"读取列数据完成，耗时: {elapsed_time:.4f} 秒")
            return result_df

        except Exception as e:
            print(f"从Parquet文件读取列数据时发生错误: {str(e)}")
            return None

    def import_logs_async(self, folder_path: str, file_list: Optional[List[str]] = None):
        """
        异步导入指定文件夹中的RCD日志
        
        Args:
            folder_path: 日志文件夹路径
            file_list: 可选的文件列表，如果提供则直接使用该列表，不扫描文件夹
        """

        def run_import():
            # 在新线程中执行导入操作
            self.import_logs(folder_path, file_list)

        # 创建并启动新线程
        thread = threading.Thread(target=run_import)
        thread.daemon = True  # 设置为守护线程，确保主线程退出时线程也会退出
        thread.start()

    def start_monitoring(self, folder_path: str):
        """
        开始监控指定文件夹中的CSV文件变化（单线程扫描方式）
        
        Args:
            folder_path: 要监控的文件夹路径
        """
        if self._is_monitoring:
            print("监控已在运行中")
            return

        try:
            self.clear_data()
            self.log_folder_path = folder_path  
            self._is_monitoring = True
            thread = threading.Thread(target=self._monitoring_worker, daemon=True)
            thread.start()
            print(f"开始单线程监控文件夹: {folder_path}")
            
        except Exception as e:
            print(f"启动监控失败: {e}")

    def _csv_to_parquet(self, file_paths: list):
        """
        新添加的CSV文件转parquet，分批读取以避免内存不足，最终合并为一个Parquet文件。
        """
        start_time = time.time()
        file_paths = sorted(file_paths)

        if not self._parquet_file:
            folder_path = Path(self.log_folder_path)
            parquet_file = folder_path / "log_data.parquet"
            self._parquet_file = str(parquet_file)
            print(f"创建Parquet文件路径: {self._parquet_file}")

        max_total_size_mb = 400  # 单次处理最大总文件大小（单位：MB）
        max_total_size_bytes = max_total_size_mb * 1024 * 1024

        current_batch = []
        current_size = 0

        def process_batch(batch_files):
            """处理一个批次的文件，返回 DataFrame"""
            all_dfs = []
            for csv_file in batch_files:
                try:
                    df = pd.read_csv(csv_file, encoding='gbk', low_memory=False)
                    all_dfs.append(df)
                except Exception as e:
                    print(f"读取文件 {csv_file} 失败: {e}")
            if not all_dfs:
                return pd.DataFrame()
            return pd.concat(all_dfs, ignore_index=True)

        # 读取已有 Parquet 文件（如存在）
        if os.path.exists(self._parquet_file):
            existing_df = pd.read_parquet(self._parquet_file)
        else:
            existing_df = pd.DataFrame()

        # 分批读取 CSV 文件
        for csv_file in file_paths:
            file_size = os.path.getsize(csv_file)

            if current_size + file_size > max_total_size_bytes and current_batch:
                # 处理当前批次
                batch_df = process_batch(current_batch)
                if not batch_df.empty:
                    existing_df = pd.concat([existing_df, batch_df], ignore_index=True)
                current_batch = []
                current_size = 0

            current_batch.append(csv_file)
            current_size += file_size

        # 处理最后一个批次
        if current_batch:
            batch_df = process_batch(current_batch)
            if not batch_df.empty:
                existing_df = pd.concat([existing_df, batch_df], ignore_index=True)

        # 一次性写入最终的 Parquet 文件
        existing_df.to_parquet(self._parquet_file, index=False)
        elapsed_time = time.time() - start_time
        print(f"转换文件个数: {len(file_paths)}, 耗时{elapsed_time:.2f}")
    def _monitoring_worker(self):
        """
        监控工作线程函数
        """
        print("监控线程启动")
        process_start_time = time.time()
        folder_path_obj = Path(self.log_folder_path)
        if not folder_path_obj.exists():
            return
        try:
            while self._is_monitoring:
                # 每隔一段时间检查一次文件变化
                time.sleep(0.5)  # 每0.5秒检查一次
                # 获取当前的CSV文件列表
                current_files = list(str(f) for f in folder_path_obj.rglob("*.csv"))
                # 找出新增的文件
                new_files = list(set(current_files) - set(self.csv_files))
                
                if new_files:                    
                    # 批量处理新文件
                    self._csv_to_parquet(new_files)
                    # 更新初始文件列表
                    self.csv_files = current_files
            # 程序退出前再执行一次扫描
            current_files = list(str(f) for f in folder_path_obj.rglob("*.csv"))
            # 找出新增的文件
            new_files = list(set(current_files) - set(self.csv_files))
            if new_files:                    
                # 批量处理新文件
                self._csv_to_parquet(new_files)
                # 更新初始文件列表
                self.csv_files = current_files

            elapsed_time = time.time() - process_start_time
            print(f"监控线程即将退出。总共处理了 {len(self.csv_files)} 个CSV文件，耗时: {elapsed_time:.2f} 秒")       
            # 扫描结束自动加载
            self.import_logs(self.log_folder_path, clear_data=False)
        except Exception as e:
            print(f"监控线程出错: {e}")

    def stop_monitoring(self):
        """停止文件监控"""
        if not self._is_monitoring:
            return
        # 停止监控线程 - 不阻塞调用者
        self._is_monitoring = False

    def get_column_changes(self, column_name: str) -> List[dict]:
        """
        快速获取一列数据值发生变化的时间和变化时的值
        使用NumPy的diff + where组合优化效率
        
        Args:
            column_name: 要分析的列名
            
        Returns:
            List[dict]: 包含变化时间点和对应值的字典列表
            每个字典格式: {'time': 时间, 'value': 变化后的值}
        """
        try:
            start_time = time.time()
            # 获取该列的所有数据
            column_data = self.get_column_data(column_name)
            if column_data is None or column_data.empty:
                print(f"无法获取列 {column_name} 的数据")
                return []
            
            # 获取时间列表
            time_list = self.get_time_list()
            if not time_list:
                print("无法获取时间列表")
                return []
            
            # 获取该列的值并转换为numpy数组
            values = column_data[column_name].values            
            
            # 使用numpy的diff找出变化点
            # diff会返回相邻元素的差值，第一个元素为0
            diff_values = np.diff(values)
            # 找出非零的差值位置（即发生变化的位置）
            change_indices = np.where(diff_values != 0)[0] + 1  # +1因为diff会少一个元素
            
            # 添加第一个元素（总是变化点）
            all_change_indices = np.concatenate([[0], change_indices])
            all_change_indices = np.sort(all_change_indices)

           # 构建变化点列表
            changes = []
            for i in all_change_indices:
                if i < len(time_list):
                    changes.append({
                        'time': time_list[i],
                        'value': values[i]
                    })
            
            end_time = time.time()
            elapsed_time = end_time - start_time
            print(f"获取列 {column_name} 变化数据完成，耗时: {elapsed_time:.4f} 秒")
            return changes
        except Exception as e:
            print(f"获取列变化数据时发生错误: {str(e)}")
            return []
    
    
    
        
    def get_row_data(self, row_idx: int) -> pd.DataFrame:
        
        if self.imported_flag:
            self._parquet_to_feather(self.log_folder_path)
            self.imported_flag = False

        if not self._feather_file or not os.path.exists(self._feather_file):
            print("feather文件不存在")
            return None
        try:
            
            return get_row_data_safe(self._feather_file,row_idx,self._batch_offsets,self._batch_num_rows,self._total_rows)
        
        except Exception as e:
            print(f"从feather文件读取行数据时发生错误: {str(e)}")
            return None


    def slot_clear_read_feather(self):        
        gc.collect()  # 强制垃圾回收
        print("强制对象回收")


    def slot_on_off_row_data_read(self,en:bool):
        pass

    def _notify_when_import_files(self):
        if not hasattr(self,"imported_flag"):
            setattr(self,"imported_flag",True)
        else:
            self.imported_flag = True
        
    def _parquet_to_feather(self,select_folder_path):
        """parquet文件转feather """
        start_time = time.time()
        
        if not self._feather_file:
            folder_path =  Path(select_folder_path)
            feather_file = folder_path / "log_data.feather"
            self._feather_file = str(feather_file)
            
            if os.path.exists(self._feather_file):
                print("使用旧feather，不执行转换")
                self.verify()
                return
            print(f"创建feather文件路径: {self._feather_file}")
            result_df = pd.read_parquet(self._parquet_file)
            # 转换为 Arrow Table 并分批次
            table = pa.Table.from_pandas(result_df)
            rows_per_batch =5000
            batches = table.to_batches(max_chunksize=rows_per_batch)
            
            print(f"新批次数量: {len(batches)}")
            print(f"每批次约 {rows_per_batch} 行")
            
            # 重新组合并写入
            new_table = pa.Table.from_batches(batches)
            feather.write_feather(new_table, self._feather_file)
            
            self.verify()
            
            if not os.path.exists(self._feather_file):
                print("feather文件创建失败")
                return 
            self.verify()
            
        else:
            print("使用旧feather，不执行转换")
            self.verify()
            return
        
        elapsed_time = time.time() - start_time
        print(f"从parquet文件生成feather文件, 耗时{elapsed_time:.2f}秒")
    

    def verify(self):
        # 验证
        mmap = pa.memory_map(self._feather_file)
        reader = pa.ipc.RecordBatchFileReader(mmap)

        
        print(f"新文件批次数量: {reader.num_record_batches}")

        total_rows = 0
        batch_offsets = []
        num_rows = []
       
        for i in range(reader.num_record_batches):
            batch = reader.get_batch(i)
            
            batch_offsets.append(total_rows)
            num_rows.append(batch.num_rows)
            total_rows += batch.num_rows

       

        print(f"total_rows={total_rows}  batch_offsets={batch_offsets}   num_rows={num_rows}")
        if not hasattr(self, "_total_rows"):
            setattr(self,"_total_rows",total_rows)
        if not hasattr(self, "_batch_offsets"):
            setattr(self,"_batch_offsets",batch_offsets)
        if not hasattr(self, "_batch_num_rows"):
            setattr(self,"_batch_num_rows",num_rows)

        mmap.close()
    

