# PyInstaller runtime hook for snap7
#
# 打包后 snap7.dll 可能被放在不同位置，取决于打包方式：
#   --collect-binaries snap7   ->  <_MEIPASS>/snap7/lib/snap7.dll
#   手工 --add-binary          ->  <_MEIPASS>/snap7.dll 或根目录
# 这里只把**存在的目录**加进 DLL 搜索路径。注意 os.add_dll_directory 要的是
# 目录而不是 dll 文件本身，早期版本传了文件路径会直接抛 FileNotFoundError，
# 把整个 exe 顶在启动阶段。
import os
import sys


def _add_dll_dir(path):
    if not path or not os.path.isdir(path):
        return
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(path)
        except OSError:
            pass


if getattr(sys, "frozen", False):
    base_path = getattr(
        sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable))
    )
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    candidates = [
        base_path,
        os.path.join(base_path, "snap7"),
        os.path.join(base_path, "snap7", "lib"),
        exe_dir,
        os.path.join(exe_dir, "snap7"),
    ]

    for directory in candidates:
        _add_dll_dir(directory)

    # PATH 兜底（部分老版本 ctypes 不认 add_dll_directory）
    existing = [d for d in candidates if os.path.isdir(d)]
    if existing:
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = os.pathsep.join(existing + ([old_path] if old_path else []))
