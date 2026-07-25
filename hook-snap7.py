# PyInstaller runtime hook for snap7
import os
import sys

# 在打包后的环境中设置 snap7 库路径
if getattr(sys, 'frozen', False):
    # 获取打包后的临时目录
    base_path = sys._MEIPASS
    
    # 添加 snap7 目录到 DLL 搜索路径
    snap7_path = os.path.join(base_path, 'snap7.dll')
    
    # 在 Windows 上添加 DLL 搜索路径
    if hasattr(os, 'add_dll_directory'):
        # Python 3.8+
        os.add_dll_directory(snap7_path)
    
    # 设置环境变量（备用方法）
    if 'PATH' in os.environ:
        os.environ['PATH'] = snap7_path + os.pathsep + os.environ['PATH']
    else:
        os.environ['PATH'] = snap7_path
