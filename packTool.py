#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PyInstaller 打包工具 (基于 Spec 文件)
可视化配置项目、资源、高级选项，生成 spec 文件后执行打包。
"""
import shutil
import sys
import os
import ast
import subprocess
import json
import tempfile
import shlex
import locale
import re
from importlib.util import find_spec
from pathlib import Path
from typing import List, Optional, Dict, Any

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QListWidget, QFileDialog, QLabel, QLineEdit,
    QProgressBar, QGroupBox, QCheckBox, QMessageBox, QListWidgetItem,
    QScrollArea, QDialog, QDialogButtonBox, QPlainTextEdit, QComboBox,
    QFormLayout, QSpinBox
)
from PySide6.QtCore import Qt, QThread, Signal, QDateTime
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QInputDialog

class PackagerThread(QThread):
    """基于 Spec 文件的打包线程"""
    log_signal = Signal(str)
    progress_signal = Signal(int)
    finished_signal = Signal(bool, str)

    def __init__(self, spec_file: Path, project_path: Path, *,
                 python_exe: str = "", distpath: str = "",
                 extra_args: Optional[List[str]] = None,
                 hidden_imports: Optional[List[str]] = None):
        super().__init__()
        self.spec_file = spec_file
        self.project_path = project_path
        self.python_exe = python_exe
        self.distpath = distpath
        self.extra_args = list(extra_args or [])
        self.hidden_imports = list(hidden_imports or [])

    def run(self) -> None:
        try:
            self.log_signal.emit("🚀 开始基于 Spec 文件打包...")

            # 解释器必须显式钉死。PyInstaller 收集模块用的是「它自己所在解释器」
            # 的 site-packages，跟 spec 里的 pathex 无关；以前用
            # shutil.which('pyinstaller') 优先，PATH 里如果指向别的 venv，
            # 就会静默产出一个缺依赖的包（asyncua 那次事故就是这么来的）。
            if self.python_exe:
                cmd = [self.python_exe, "-m", "PyInstaller"]
                self.log_signal.emit(f"🐍 打包解释器: {self.python_exe}")
            else:
                pyinstaller_cmd = shutil.which("pyinstaller")
                if not pyinstaller_cmd:
                    if getattr(sys, "frozen", False):
                        self.finished_signal.emit(
                            False,
                            "❌ 未指定 Python 解释器，PATH 中也没有 pyinstaller。\n"
                            "请在「Python 解释器」里填一个装齐依赖的 python.exe。",
                        )
                        return
                    pyinstaller_cmd_path = sys.executable
                    cmd = [pyinstaller_cmd_path, "-m", "PyInstaller"]
                    self.log_signal.emit(f"🐍 打包解释器: {pyinstaller_cmd_path}")
                else:
                    cmd = [pyinstaller_cmd]
                    self.log_signal.emit(
                        f"⚠️ 使用 PATH 中的 pyinstaller: {pyinstaller_cmd}\n"
                        "   无法确认它属于哪个环境，请确认该环境装齐了所有依赖。"
                    )

            cmd.append("--noconfirm")
            if self.distpath:
                cmd += ["--distpath", self.distpath]
            cmd += self.extra_args
            cmd.append(str(self.spec_file))
            self.log_signal.emit(f"📦 执行命令: {' '.join(cmd)}")

            # Windows 控制台输出是本地编码（GBK），写死 utf-8 会把中文路径
            # 全替换成问号，warn 排查时很难读。
            encoding = locale.getpreferredencoding(False) or "utf-8"
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding=encoding,
                errors="replace",
                cwd=str(self.project_path),
            )

            for line in process.stdout:
                if line.strip():
                    self.log_signal.emit(line.rstrip())
                if "building EXE" in line.lower():
                    self.progress_signal.emit(60)
                elif "building PKG" in line.lower():
                    self.progress_signal.emit(40)

            process.wait()
            self.progress_signal.emit(100)

            if process.returncode != 0:
                # 失败时不要把 warn 结论混进来，先让用户看返回码对应的错误
                self.finished_signal.emit(False, f"❌ 打包失败，返回码: {process.returncode}")
                return

            # 返回码 0 != 打包正确：hiddenimport 找不到时 PyInstaller 只写
            # warn 文件、不报错。必须扫一遍，否则又是「打开 exe 才发现缺库」。
            declared_missing, other_missing = self._scan_warn_files()
            if declared_missing:
                self.log_signal.emit("=" * 60)
                self.log_signal.emit("❌ 严重：以下顶层包在打包解释器里确实找不到！")
                for name in declared_missing:
                    self.log_signal.emit(f"    - {name}")
                self.log_signal.emit(
                    "   说明：多半是打包用的 Python 解释器不对。换到装齐依赖的 "
                    ".venv/Scripts/python.exe 重新打包。"
                )
                self.log_signal.emit("=" * 60)
                self.finished_signal.emit(
                    False,
                    "❌ 打包进程返回 0，但顶层依赖包没找到："
                    + ", ".join(declared_missing),
                )
                return
            # 包内子模块/属性级缺失是 PyInstaller 静态分析的常见噪声，
            # 单独报数，不混进「真正缺失模块」里。
            noise = {m for m in other_missing
                     if any(m.startswith(n + ".") for n in self.hidden_imports)}
            real_missing = other_missing - noise
            if noise:
                self.log_signal.emit(
                    f"ℹ️ warn 里 {len(noise)} 条「包内子模块/属性」缺失"
                    "（如 numpy._core.zeros，多为 re-export 的函数/类误判），已忽略。"
                )
            if real_missing:
                self.log_signal.emit(
                    f"⚠️ warn 文件里有 {len(real_missing)} 个缺失模块"
                    "（多为可选依赖，确认不是业务必需的即可）："
                    + ", ".join(sorted(real_missing)[:12])
                )

            self.finished_signal.emit(True, "✅ 打包成功，隐藏导入全部可用！")

        except Exception as e:
            self.finished_signal.emit(False, f"⚠️ 打包过程异常: {str(e)}")

    def _scan_warn_files(self):
        """读 PyInstaller 的 warn-*.txt，找出 missing module。

        返回 ``(声明过的顶层包确实找不到的, 其它缺失模块)``。

        只有「顶层包本身」在打包解释器里也 find_spec 不到，才是致命的。
        warn 里绝大多数 ``missing module named pkg.sub`` 不是缺包：
        PyInstaller 静态分析会把包内 re-export 的函数/类（numpy 2.x 的
        ``numpy._core.zeros``、``pandas.core.internals.Block``）和可选组件
        （``pyarrow._cuda`` / ``pyarrow.gandiva``）当成子模块写进 warn，
        而顶层包其实已完整进 PYZ。旧逻辑用 ``startswith(name + '.')``
        判致命，结果 numpy/pandas/pyarrow 装齐、spec 自检通过、返回码 0，
        仍被误报成「打包解释器不对」。
        """
        warn_dir = self.project_path / "build" / self.spec_file.stem
        if not warn_dir.is_dir():
            return [], set()
        pattern = re.compile(r"missing module named [\"']?([^\"'\s,]+)")
        missing = set()
        for warn_file in warn_dir.glob("warn-*.txt"):
            try:
                text = warn_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                match = pattern.search(line)
                if match:
                    missing.add(match.group(1))
        # 精确匹配：包内子模块/属性缺失不算「整个包找不到」
        candidates = set(self.hidden_imports) & missing
        declared = self._unresolvable_roots(candidates) if candidates else []
        return sorted(declared), missing - set(self.hidden_imports)

    def _unresolvable_roots(self, candidates) -> list:
        """在真正跑 PyInstaller 的解释器里复核顶层包是否真的装不上。

        spec 的前置自检可能被手工编辑绕过，所以这里再确认一次；
        复核不了（解释器失效 / 子进程异常）就宁可按 warn 原样报错。
        """
        code = (
            "import importlib.util, json; "
            "print(json.dumps({m: importlib.util.find_spec(m) is not None "
            "for m in " + repr(sorted(candidates)) + "}))"
        )
        try:
            out = subprocess.check_output(
                [self.python_exe or sys.executable, "-c", code], text=True,
                encoding="utf-8", errors="replace", timeout=30,
            )
            result = json.loads(out.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001 - 复核失败不静默放过
            return sorted(candidates)
        return sorted(m for m, ok in result.items() if not ok)

class SpecEditorDialog(QDialog):
    """Spec 文件预览/编辑对话框"""
    def __init__(self, spec_content: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑 Spec 文件内容")
        self.resize(800, 600)

        layout = QVBoxLayout(self)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlainText(spec_content)
        self.text_edit.setFont(QFont("Consolas", 10))
        layout.addWidget(self.text_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_spec_content(self) -> str:
        return self.text_edit.toPlainText()


class PythonPackager(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyInstaller Spec 打包工具")
        self.setGeometry(100, 100, 1200, 850)

        self.project_path: Optional[Path] = None
        self.include_resources: List[str] = []
        #: 每个资源在包内的目标目录（key 是源路径）。留空 = 按相对项目路径摆放。
        self.resource_dests: Dict[str, str] = {}
        self.hidden_imports: List[str] = []
        #: 预览对话框里手工编辑过的 spec；非空时保存 / 打包都优先用它。
        self._edited_spec: Optional[str] = None
        self.current_thread: Optional[PackagerThread] = None
        self.config_file = Path.home() / ".python_packager_spec_config.json"

        self._init_ui()
        self._load_config()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # ========== 项目基本设置 ==========
        basic_group = QGroupBox("📁 项目基本设置")
        basic_layout = QFormLayout(basic_group)

        # 项目路径
        self.project_edit = QLineEdit()
        self.project_edit.setPlaceholderText("选择 Python 项目根目录")
        browse_btn = QPushButton("浏览")
        browse_btn.clicked.connect(self._browse_project)
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.project_edit)
        path_layout.addWidget(browse_btn)
        basic_layout.addRow("项目目录:", path_layout)

        # 打包用的 Python 解释器：PyInstaller 只认「自己所在解释器」的
        # site-packages，PATH 里的 pyinstaller 指到别的项目时，产物会静默缺依赖。
        self.python_edit = QLineEdit(sys.executable)
        self.python_edit.setPlaceholderText("必须指向装齐依赖的 venv/Scripts/python.exe")
        browse_python_btn = QPushButton("浏览")
        browse_python_btn.clicked.connect(self._browse_python)
        python_layout = QHBoxLayout()
        python_layout.addWidget(self.python_edit)
        python_layout.addWidget(browse_python_btn)
        basic_layout.addRow("Python 解释器:", python_layout)

        # 入口脚本
        self.entry_edit = QLineEdit()
        self.entry_edit.setPlaceholderText("自动检测 main.py 或第一个 .py")
        browse_entry = QPushButton("选择文件")
        browse_entry.clicked.connect(self._browse_entry)
        entry_layout = QHBoxLayout()
        entry_layout.addWidget(self.entry_edit)
        entry_layout.addWidget(browse_entry)
        basic_layout.addRow("入口脚本:", entry_layout)

        # 输出名称
        self.output_name_edit = QLineEdit("MyApp")
        basic_layout.addRow("输出名称 (不含扩展名):", self.output_name_edit)

        # 输出目录
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("默认: 项目目录/dist")
        browse_out = QPushButton("浏览")
        browse_out.clicked.connect(self._browse_output_dir)
        out_layout = QHBoxLayout()
        out_layout.addWidget(self.output_dir_edit)
        out_layout.addWidget(browse_out)
        basic_layout.addRow("输出目录:", out_layout)

        # 基本选项
        self.onefile_cb = QCheckBox("单文件打包 (--onefile)")
        self.onefile_cb.setChecked(True)
        self.console_cb = QCheckBox("显示控制台窗口")
        self.console_cb.setChecked(False)
        opts_layout = QHBoxLayout()
        opts_layout.addWidget(self.onefile_cb)
        opts_layout.addWidget(self.console_cb)
        basic_layout.addRow("打包选项:", opts_layout)

        main_layout.addWidget(basic_group)

        # ========== 高级选项 (折叠区域) ==========
        advanced_group = QGroupBox("⚙️ 高级选项 (Spec 配置)")
        advanced_group.setCheckable(True)
        advanced_group.setChecked(False)
        adv_layout = QFormLayout(advanced_group)

        # 图标文件
        self.icon_edit = QLineEdit()
        self.icon_edit.setPlaceholderText("例如: assets/app.ico (Windows) 或 .icns (macOS)")
        icon_btn = QPushButton("选择图标")
        icon_btn.clicked.connect(self._browse_icon)
        icon_layout = QHBoxLayout()
        icon_layout.addWidget(self.icon_edit)
        icon_layout.addWidget(icon_btn)
        adv_layout.addRow("应用程序图标:", icon_layout)

        # 隐藏导入
        self.hidden_imports_list = QListWidget()
        self.hidden_imports_list.setMaximumHeight(100)
        add_hidden_btn = QPushButton("添加模块")
        add_hidden_btn.clicked.connect(self._add_hidden_import)
        remove_hidden_btn = QPushButton("移除选中")
        remove_hidden_btn.clicked.connect(self._remove_hidden_import)
        hidden_btn_layout = QHBoxLayout()
        hidden_btn_layout.addWidget(add_hidden_btn)
        hidden_btn_layout.addWidget(remove_hidden_btn)
        adv_layout.addRow("隐藏导入 (PyInstaller 无法自动检测的模块):", self.hidden_imports_list)
        adv_layout.addRow("", hidden_btn_layout)

        # 只写顶层包名时，PyInstaller 不会自动收子包（asyncua 的 __init__
        # 只导出几个名字，实现全在 asyncua.client.* / asyncua.ua.*）。
        self.collect_submodules_cb = QCheckBox(
            "隐藏导入同时收集全部子模块 (--collect-submodules，推荐勾选)"
        )
        self.collect_submodules_cb.setChecked(True)
        adv_layout.addRow("", self.collect_submodules_cb)

        # UPX 压缩
        self.upx_cb = QCheckBox("启用 UPX 压缩 (需安装 upx 并配置 PATH)")
        self.upx_cb.setChecked(False)
        adv_layout.addRow("压缩选项:", self.upx_cb)

        # 运行时钩子
        self.runtime_hook_edit = QLineEdit()
        self.runtime_hook_edit.setPlaceholderText("可选: 指定 .py 钩子脚本")
        hook_btn = QPushButton("浏览")
        hook_btn.clicked.connect(self._browse_runtime_hook)
        hook_layout = QHBoxLayout()
        hook_layout.addWidget(self.runtime_hook_edit)
        hook_layout.addWidget(hook_btn)
        adv_layout.addRow("运行时钩子:", hook_layout)

        # 附加命令行参数 (自由格式)
        self.extra_args_edit = QLineEdit()
        self.extra_args_edit.setPlaceholderText("例如: --noupx --optimize 2")
        adv_layout.addRow("附加 PyInstaller 参数:", self.extra_args_edit)

        main_layout.addWidget(advanced_group)

        # ========== 资源文件区域 ==========
        resource_group = QGroupBox("📦 附加资源 (--add-data)")
        res_layout = QVBoxLayout(resource_group)

        res_layout.addWidget(QLabel(
            "双击列表项可修改「包内目标目录」。默认保持源码层级"
            "（如 App_PopPick/hmi/data）；只有代码按 cwd 相对读取时才填 ."
        ))
        self.resource_list = QListWidget()
        self.resource_list.itemDoubleClicked.connect(self._edit_resource_dest)
        res_layout.addWidget(self.resource_list)

        res_btn_layout = QHBoxLayout()
        add_file_btn = QPushButton("添加文件")
        add_file_btn.clicked.connect(self._add_resource_file)
        add_folder_btn = QPushButton("添加文件夹")
        add_folder_btn.clicked.connect(self._add_resource_folder)
        remove_res_btn = QPushButton("移除选中")
        remove_res_btn.clicked.connect(self._remove_resource)
        clear_res_btn = QPushButton("清空全部")
        clear_res_btn.clicked.connect(self._clear_resources)
        res_btn_layout.addWidget(add_file_btn)
        res_btn_layout.addWidget(add_folder_btn)
        res_btn_layout.addWidget(remove_res_btn)
        res_btn_layout.addWidget(clear_res_btn)
        res_btn_layout.addStretch()
        res_layout.addLayout(res_btn_layout)

        main_layout.addWidget(resource_group)

        # ========== Spec 操作按钮 ==========
        spec_btn_layout = QHBoxLayout()
        self.gen_spec_btn = QPushButton("📄 生成/预览 Spec 文件")
        self.gen_spec_btn.clicked.connect(self._preview_spec)
        self.save_spec_btn = QPushButton("💾 保存 Spec 文件到项目")
        self.save_spec_btn.clicked.connect(self._save_spec_file)
        spec_btn_layout.addWidget(self.gen_spec_btn)
        spec_btn_layout.addWidget(self.save_spec_btn)
        scan_btn = QPushButton("🔍 扫描依赖 / 资源")
        scan_btn.clicked.connect(self._scan_project)
        spec_btn_layout.addWidget(scan_btn)
        spec_btn_layout.addStretch()
        main_layout.addLayout(spec_btn_layout)

        # ========== 日志与进度 ==========
        log_group = QGroupBox("📝 打包日志")
        log_layout = QVBoxLayout(log_group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_text)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        log_layout.addWidget(self.progress_bar)

        main_layout.addWidget(log_group)

        # ========== 底部按钮 ==========
        button_layout = QHBoxLayout()
        self.package_btn = QPushButton("🚀 开始打包 (使用 Spec 文件)")
        self.package_btn.clicked.connect(self._start_packaging)
        self.package_btn.setStyleSheet("font-weight: bold; padding: 5px;")
        clear_log_btn = QPushButton("清空日志")
        clear_log_btn.clicked.connect(self._clear_log)
        save_config_btn = QPushButton("保存配置")
        save_config_btn.clicked.connect(self._save_config)
        button_layout.addWidget(self.package_btn)
        button_layout.addWidget(clear_log_btn)
        button_layout.addWidget(save_config_btn)
        button_layout.addStretch()
        main_layout.addLayout(button_layout)

        self.statusBar().showMessage("就绪")

    # -------------------- 辅助函数 --------------------
    def _browse_project(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择 Python 项目目录")
        if dir_path:
            self.project_path = Path(dir_path)
            self.project_edit.setText(str(self.project_path))
            self._log(f"已选择项目目录: {self.project_path}")
            # 自动检测入口
            main_candidate = self.project_path / "main.py"
            if main_candidate.exists():
                self.entry_edit.setText(str(main_candidate))

    def _browse_python(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择打包用的 python.exe", str(self.project_path or Path.home()),
            "可执行文件 (*.exe);;所有文件 (*)",
        )
        if file_path:
            self.python_edit.setText(file_path)
            self._log(f"🐍 打包解释器已设为: {file_path}")

    def _browse_entry(self):
        if not self.project_path:
            QMessageBox.warning(self, "提示", "请先选择项目目录")
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择入口 Python 文件", str(self.project_path), "Python 文件 (*.py)"
        )
        if file_path:
            self.entry_edit.setText(file_path)

    def _browse_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if dir_path:
            self.output_dir_edit.setText(dir_path)

    def _browse_icon(self):
        if not self.project_path:
            QMessageBox.warning(self, "提示", "请先选择项目目录")
            return
        filters = "图标文件 (*.ico *.icns *.png);;所有文件 (*)"
        file_path, _ = QFileDialog.getOpenFileName(self, "选择图标文件", str(self.project_path), filters)
        if file_path:
            # 尝试转换为相对路径
            try:
                rel = Path(file_path).relative_to(self.project_path)
                self.icon_edit.setText(str(rel))
            except ValueError:
                self.icon_edit.setText(file_path)

    def _browse_runtime_hook(self):
        if not self.project_path:
            QMessageBox.warning(self, "提示", "请先选择项目目录")
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "选择钩子脚本", str(self.project_path), "Python 文件 (*.py)")
        if file_path:
            try:
                rel = Path(file_path).relative_to(self.project_path)
                self.runtime_hook_edit.setText(str(rel))
            except ValueError:
                self.runtime_hook_edit.setText(file_path)

    def _add_hidden_import(self):
        module, ok = QInputDialog.getText(self, "添加隐藏导入", "模块名 (例如: pyodbc, cryptography):")
        if ok and module.strip():
            if module not in self.hidden_imports:
                self.hidden_imports.append(module)
                self.hidden_imports_list.addItem(module)
                self._log(f"➕ 添加隐藏导入: {module}")
                self._edited_spec = None

    def _add_hidden_imports(self, modules) -> None:
        """批量补隐藏导入（扫描报告里「加入隐藏导入」按钮用）。"""
        added = 0
        for module in modules:
            if module and module not in self.hidden_imports:
                self.hidden_imports.append(module)
                self.hidden_imports_list.addItem(module)
                added += 1
        if added:
            self._edited_spec = None
            self._log(f"➕ 已从扫描结果补齐 {added} 个隐藏导入: {', '.join(modules)}")

    def _remove_hidden_import(self):
        current = self.hidden_imports_list.currentRow()
        if current >= 0:
            item = self.hidden_imports_list.takeItem(current)
            module = item.text()
            if module in self.hidden_imports:
                self.hidden_imports.remove(module)
            self._log(f"➖ 移除隐藏导入: {module}")
            self._edited_spec = None

    # -------------------- 资源：源 -> 包内目标 --------------------
    def _default_dest(self, src: Path) -> str:
        try:
            rel = src.relative_to(self.project_path)
        except (ValueError, TypeError):
            rel = Path(src.name)
        if src.is_dir():
            return rel.as_posix()
        parent = rel.parent.as_posix()
        return parent if parent not in ("", ".") else "."

    def _resource_label(self, src: str) -> str:
        dest = self.resource_dests.get(src, "")
        if not dest:
            dest = self._default_dest(Path(src))
        kind = "📁 " if Path(src).is_dir() else "📄 "
        return f"{kind}{src}  →  {dest}"

    def _reload_resource_list(self) -> None:
        self.resource_list.clear()
        for src in self.include_resources:
            item = QListWidgetItem(self._resource_label(src))
            item.setData(Qt.ItemDataRole.UserRole, src)
            self.resource_list.addItem(item)

    def _register_resource(self, src: str) -> None:
        if src in self.include_resources:
            return
        default_dest = self._default_dest(Path(src))
        dest, ok = QInputDialog.getText(
            self, "包内目标目录",
            "该资源放进包里的哪个目录？\n"
            "· 默认（推荐）：保持源码层级，如 App_LogPlot/app/plot_moudle/ui\n"
            "· 代码按 sys._MEIPASS/<名字> 找时才填短名：ui / cfg / ico\n"
            "· 代码按 cwd 相对读取时填 .（并考虑放到 exe 同层）",
            text=default_dest,
        )
        if not ok:
            return
        dest = dest.strip() or default_dest
        self.include_resources.append(src)
        self.resource_dests[src] = dest
        self._reload_resource_list()
        self._log(f"➕ 添加资源: {src} → {dest}")
        self._edited_spec = None

    def _add_resource_file(self):
        if not self.project_path:
            QMessageBox.warning(self, "提示", "请先选择项目目录")
            return
        files, _ = QFileDialog.getOpenFileNames(self, "选择资源文件", str(self.project_path))
        for f in files:
            self._register_resource(f)

    def _add_resource_folder(self):
        if not self.project_path:
            QMessageBox.warning(self, "提示", "请先选择项目目录")
            return
        folder = QFileDialog.getExistingDirectory(self, "选择资源文件夹", str(self.project_path))
        if folder:
            self._register_resource(folder)

    def _edit_resource_dest(self, item: QListWidgetItem):
        src = item.data(Qt.ItemDataRole.UserRole)
        if not src:
            QMessageBox.warning(self, "提示", "这条资源来自旧配置，请移除后重新添加")
            return
        current = self.resource_dests.get(src, self._default_dest(Path(src)))
        dest, ok = QInputDialog.getText(
            self, "修改包内目标目录", f"资源: {src}", text=current
        )
        if ok and dest.strip():
            self.resource_dests[src] = dest.strip()
            self._reload_resource_list()
            self._log(f"✏️ 资源目标改为: {src} → {dest.strip()}")
            self._edited_spec = None

    def _remove_resource(self):
        current = self.resource_list.currentRow()
        if current >= 0:
            item = self.resource_list.takeItem(current)
            path = item.data(Qt.ItemDataRole.UserRole) or item.text()
            if path.startswith("📁 ") or path.startswith("📄 "):
                path = path[2:]
            if path in self.include_resources:
                self.include_resources.remove(path)
            self.resource_dests.pop(path, None)
            self._log(f"➖ 移除资源: {path}")
            self._edited_spec = None

    def _clear_resources(self):
        self.resource_list.clear()
        self.include_resources.clear()
        self.resource_dests.clear()
        self._log("🗑️ 已清空所有附加资源")
        self._edited_spec = None

    # -------------------- 项目扫描 --------------------
    #: 扫描时跳过的目录（产物 / 虚拟环境 / 缓存）
    SCAN_SKIP = {".venv", "venv", "env", "build", "dist", "__pycache__",
                 ".git", ".workbuddy", "site-packages", "node_modules"}
    SCAN_DATA_EXT = {".json", ".xml", ".yaml", ".yml", ".csv", ".ini", ".cfg",
                     ".ui", ".qss", ".svg", ".png", ".jpg", ".ico", ".dll",
                     ".txt", ".ttf", ".otf", ".db", ".sqlite"}

    def _scan_python_files(self):
        for path in self.project_path.rglob("*.py"):
            if any(part in self.SCAN_SKIP for part in path.parts):
                continue
            yield path

    def _scan_imports(self):
        """AST 收集顶层导入名 + 动态导入字面量（不执行任何代码）。"""
        imports, dynamic = set(), set()
        for path in self._scan_python_files():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    imports.add(node.module.split(".")[0])
                elif isinstance(node, ast.Call):
                    func = node.func
                    is_dynamic = (
                        (isinstance(func, ast.Attribute) and func.attr in
                         ("import_module", "find_spec"))
                        or (isinstance(func, ast.Name) and func.id == "__import__")
                    )
                    if is_dynamic and node.args and isinstance(node.args[0], ast.Constant):
                        if isinstance(node.args[0].value, str):
                            dynamic.add(node.args[0].value.split(".")[0])
        return imports, dynamic

    def _suggest_dest(self, directory: Path) -> str:
        """资源目标默认就是「保持源码层级」。

        项目里的资源读取方（``resource_manager`` / ``tag_catalog`` /
        ``designer_resource_manager``）现在统一用
        ``Path(__file__).parent`` 定位；frozen 下 ``__file__`` 落在
        ``<_MEIPASS>/<包路径>/``，所以包内目录照抄源码相对路径即可，
        不需要 ``if frozen`` 分支，也不会把 ``ui`` / ``cfg`` / ``ico``
        这类通用短名堆到 ``_internal`` 根下互相撞名。

        只保留一个显式例外并打标记：代码若按 cwd 相对读取（如
        ``open("cfg/config.json")``），那属于第三种语义，得放到 exe 同层，
        datas 目标填 ``.``；这由人在 UI 里双击改，不自动猜。
        """
        return self._default_dest(directory)

    def _scan_resource_dirs(self):
        """找出含非 .py 资源文件的目录，按文件数排序。"""
        counts = {}
        for path in self.project_path.rglob("*"):
            if not path.is_file() or any(part in self.SCAN_SKIP for part in path.parts):
                continue
            if path.suffix.lower() in self.SCAN_DATA_EXT:
                counts[path.parent] = counts.get(path.parent, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))

    def _probe_import_origins(self, python_exe: str) -> dict:
        """在**打包用的解释器**里查 AST 扫到的第三方模块来自哪里。

        返回 ``{模块名: origin 或 None}``。GUI 自己的解释器不算数：真正
        执行 PyInstaller 的是 ``python_exe``，它的 site-packages 才是
        模块收集的来源。
        """
        imports, _ = self._scan_imports()
        local_names = {p.name for p in self.project_path.iterdir()
                       if p.is_dir() and (p / "__init__.py").exists()}
        local_names |= {p.stem for p in self.project_path.glob("*.py")}
        candidates = sorted(
            m for m in imports
            if m not in sys.stdlib_module_names
            and m not in local_names
            and not m.startswith("_")
        )
        if not candidates or not Path(python_exe).is_file():
            return {}
        code = (
            "import importlib.util, json\n"
            "out = {}\n"
            "for m in " + repr(candidates) + ":\n"
            "    try:\n"
            "        s = importlib.util.find_spec(m)\n"
            "    except Exception:\n"
            "        s = None\n"
            "    out[m] = (s.origin or '') if s else None\n"
            "print(json.dumps(out))\n"
        )
        try:
            raw = subprocess.check_output(
                [python_exe, "-c", code], text=True,
                encoding="utf-8", errors="replace", timeout=60,
            )
            return json.loads(raw.strip().splitlines()[-1])
        except Exception as exc:  # noqa: BLE001 - 探针失败不该阻断生成
            self._log(f"⚠️ 依赖扫描子进程失败: {exc}")
            return {}

    @staticmethod
    def _is_site_packages(origin) -> bool:
        return bool(origin) and "site-packages" in str(origin).replace("\\", "/")

    def _installed_third_party(self, python_exe: str) -> list:
        """打包解释器里确实来自 site-packages 的第三方模块名。"""
        origins = self._probe_import_origins(python_exe)
        return sorted(m for m, origin in origins.items()
                      if self._is_site_packages(origin))

    def _optional_import_roots(self, python_exe: str,
                               installed=None) -> list:
        """被 ``try/except ImportError`` 包起来的第三方导入。

        这类导入 PyInstaller 静态分析最容易判成「可选」而漏收，而且实现
        往往藏在子模块里（``asyncua`` 就是典型）。即使 UI 的「隐藏导入」
        被清空，也要自动把它们加进 ``SUBMODULE_ROOTS``。
        """
        optional = set()
        for path in self._scan_python_files():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, OSError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Try):
                    continue
                if not any(isinstance(h.type, ast.Name)
                           and h.type.id == "ImportError" for h in node.handlers):
                    continue
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Import):
                        optional.update(a.name.split(".")[0] for a in sub.names)
                    elif isinstance(sub, ast.ImportFrom) and sub.module \
                            and sub.level == 0:
                        optional.add(sub.module.split(".")[0])
        if installed is None:
            installed = self._installed_third_party(python_exe)
        return sorted(optional & set(installed))

    def _scan_project(self):
        """生成一份只读扫描报告：第三方依赖 / 动态导入 / 资源目录。"""
        if not self.project_path:
            QMessageBox.warning(self, "提示", "请先选择项目目录")
            return

        _, dynamic = self._scan_imports()
        python_exe = self.python_edit.text().strip() or sys.executable
        origins = self._probe_import_origins(python_exe)
        third_party = sorted(m for m, origin in origins.items()
                             if self._is_site_packages(origin))
        missing = sorted(m for m, origin in origins.items() if origin is None)
        optional_roots = self._optional_import_roots(python_exe)

        resources = self._scan_resource_dirs()
        already = {str(Path(r).resolve()) for r in self.include_resources}
        suggested = [(d, n) for d, n in resources
                     if str(d.resolve()) not in already]

        lines = [
            "=" * 68,
            "项目扫描报告（只读；不修改任何配置）",
            "=" * 68,
            f"项目：{self.project_path}",
            f"打包解释器：{python_exe}",
            f"扫描到的 Python 文件：{sum(1 for _ in self._scan_python_files())} 个",
            "",
            "【1】第三方模块（来自 site-packages，PyInstaller 一般能自动收，",
            "     但插件式 / try-except 里的导入仍建议加进「隐藏导入」）",
        ]
        lines += [f"    + {m}" for m in third_party] or ["    （无）"]
        lines += ["", "【2】打包解释器里找不到的模块 —— 必须处理，否则运行期报错"]
        lines += [f"    ! {m}" for m in missing] or ["    （无）"]
        lines += ["", "【3】代码里的动态导入（字符串形式，静态分析看不到）"]
        lines += [f"    ? {m}" for m in sorted(dynamic)] or ["    （无）"]
        lines += ["", "【4】被 try/except ImportError 包住的第三方包",
                  "     静态分析最容易判成「可选」而漏收，会自动收子模块："]
        lines += [f"    * {m}" for m in optional_roots] or ["    （无）"]
        lines += ["", "【5】资源目录（含 json/ui/qss/ico/dll 等非 .py 文件）",
                  "     未加入资源列表的目录，打包后运行期会找不到文件："]
        for d, n in suggested[:40]:
            try:
                rel = d.relative_to(self.project_path).as_posix()
            except ValueError:
                rel = str(d)
            dest = self._suggest_dest(d)
            lines.append(f"    · {rel}  ({n} 个文件)  → 建议目标 {dest}")
        if not suggested:
            lines.append("    （无，或都已加入）")
        lines += [
            "",
            "【提醒】本项目资源一律按「保持源码层级」放置：",
            "  · resource_manager / tag_catalog 都用 Path(__file__).parent 定位",
            "    → dest 照抄源码相对目录，开发和打包两种模式同构",
            "  · 例外：代码按 cwd 相对读取（cfg/config.json）要放 exe 同层，",
            "    或按 sys._MEIPASS/<名字> 读取时才需要短名；这类请双击列表项改",
            "  添加资源时可以在弹窗里改，或双击列表项修改。",
            "",
            f"当前已配置隐藏导入：{self.hidden_imports}",
            "=" * 68,
        ]
        text = "\n".join(lines)

        dialog = QDialog(self)
        dialog.setWindowTitle("项目扫描报告")
        dialog.resize(900, 620)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(text)
        view.setFont(QFont("Consolas", 9))
        layout.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        if optional_roots:
            import_btn = buttons.addButton("把关键包加入隐藏导入",
                                           QDialogButtonBox.ButtonRole.ActionRole)
            import_btn.clicked.connect(
                lambda: self._add_hidden_imports(optional_roots)
            )
        apply_btn = buttons.addButton("把建议的资源目录加入列表",
                                      QDialogButtonBox.ButtonRole.ActionRole)
        apply_btn.clicked.connect(
            lambda: self._apply_scan_resources([d for d, _ in suggested[:40]])
        )
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _apply_scan_resources(self, dirs):
        """把扫描建议的目录加入资源列表。

        一刀切全加会出两个事故：项目根本身（目录下直接有 json/txt）会被算成
        ``(ROOT, '.')``，把 ``.venv`` / ``dist`` / ``build`` 整个塞进包；同一棵
        目录树上的父子目录会重复进 datas，COLLECT 时同名目标文件互相覆盖。
        所以这里先排除不该打包的目录，再做「保留顶层父、丢掉后代」去重。
        """
        exclude_parts = {"tools", "build", "dist", "__pycache__", ".venv", "venv",
                         ".git", ".workbuddy", "node_modules", "data.json"}
        project = self.project_path.resolve()
        roots = []
        for d in sorted({Path(x).resolve() for x in dirs},
                        key=lambda p: (len(p.parts), str(p))):
            if d == project:          # 绝不能把整个项目根加进 datas
                continue
            try:
                rel = d.relative_to(project)
            except ValueError:
                continue
            if any(part in exclude_parts for part in rel.parts):
                continue
            if any(r == d or r in d.parents for r in roots):
                continue              # 已有祖先，子目录内容已被覆盖
            roots.append(d)

        added = 0
        for d in roots:
            src = str(d)
            if src in self.include_resources:
                continue
            self.include_resources.append(src)
            self.resource_dests[src] = self._suggest_dest(d)
            added += 1
        self._reload_resource_list()
        self._log(f"🔍 已加入 {added} 个资源目录（已排除项目根 / 工具目录 / 设计工程，"
                  "并去掉父子重复；保持源码层级）")
        self._edited_spec = None

    # -------------------- Spec 生成核心 --------------------
    def _generate_spec_content(self) -> str:
        """根据当前界面配置生成 spec 文件内容。"""
        if not self.project_path:
            raise ValueError("请先选择项目目录")

        # 入口脚本
        entry_script = self.entry_edit.text().strip()
        if not entry_script:
            candidates = list(self.project_path.glob("*.py"))
            if not candidates:
                raise ValueError("未找到任何 Python 入口文件")
            entry_script = str(next((f for f in candidates if f.name == "main.py"), candidates[0]))
        entry_abs = Path(entry_script)
        if not entry_abs.is_absolute():
            entry_abs = self.project_path / entry_script
        entry_rel = entry_abs.relative_to(self.project_path)
        name = self.output_name_edit.text().strip() or "MyApp"

        # 资源：(包内相对源路径, 目标目录)。源路径相对 ROOT 写，spec 换机器也能用。
        data_entries = []
        for res in self.include_resources:
            src = Path(res)
            if not src.exists():
                self._log(f"⚠️ 资源不存在，已跳过: {src}")
                continue
            try:
                rel_src = src.relative_to(self.project_path).as_posix()
            except ValueError:
                # 项目目录之外的资源只能写绝对路径（打包时会带本机路径）
                rel_src = None
            dest = self.resource_dests.get(res, "") or self._default_dest(src)
            source_expr = (
                f"str(ROOT / {rel_src!r})" if rel_src is not None else repr(str(src))
            )
            data_entries.append((source_expr, dest))
        datas_expr = "[" + ", ".join(
            f"({src_expr}, {dest!r})" for src_expr, dest in data_entries
        ) + "]"

        hiddenimports = list(self.hidden_imports)
        submodule_roots = hiddenimports if self.collect_submodules_cb.isChecked() else []
        python_exe = self.python_edit.text().strip() or sys.executable
        # 自检与子模块收集不能只靠 UI 手填：配置被清空过一次（hidden_imports
        # 变成 []），结果生成的 spec 既不检查依赖、也不收 asyncua 子模块。
        # 现在从源码 AST 自动算出两条兜底清单。
        scanned_imports = self._installed_third_party(python_exe)
        auto_roots = self._optional_import_roots(python_exe, scanned_imports)

        # 图标 / 运行时钩子（都按 ROOT 相对写）
        icon_expr = "None"
        icon_str = self.icon_edit.text().strip()
        if icon_str:
            icon_path = Path(icon_str)
            if not icon_path.is_absolute():
                icon_path = self.project_path / icon_path
            if icon_path.exists():
                try:
                    icon_expr = f"str(ROOT / {icon_path.relative_to(self.project_path).as_posix()!r})"
                except ValueError:
                    icon_expr = repr(icon_path.as_posix())
            else:
                self._log(f"⚠️ 图标文件不存在: {icon_path}")

        hook_expr = "[]"
        hook_str = self.runtime_hook_edit.text().strip()
        if hook_str:
            hook_path = Path(hook_str)
            if not hook_path.is_absolute():
                hook_path = self.project_path / hook_path
            if hook_path.exists():
                try:
                    hook_rel = hook_path.relative_to(self.project_path).as_posix()
                    hook_expr = f"[str(ROOT / {hook_rel!r})]"
                except ValueError:
                    hook_expr = f"[{hook_path.as_posix()!r}]"
            else:
                self._log(f"⚠️ 运行时钩子文件不存在: {hook_path}")

        console = self.console_cb.isChecked()
        onefile = self.onefile_cb.isChecked()
        upx = self.upx_cb.isChecked()

        # 所有字符串一律 repr，避免项目名/路径里的引号把 spec 写坏。
        lines = [
            "# -*- mode: python ; coding: utf-8 -*-",
            f"# 由 packTool.py 生成 ｜ 打包解释器：{python_exe}",
            "# 注意：重新生成会覆盖本文件里的人工修改。",
            "",
            "import sys",
            "from importlib.util import find_spec",
            "from pathlib import Path",
            "from PyInstaller.utils.hooks import collect_submodules",
            "",
            "ROOT = Path(SPECPATH).resolve()",
            "",
            "# ---- 前置自检：缺依赖直接中止，不产出运行期才报错的包 ----",
            "# DECLARED 是 UI 手填，SCANNED 是从源码 AST 自动扫出的第三方包；",
            "# 两者取并集，避免「隐藏导入被清空 → 自检形同虚设」。",
            f"DECLARED_IMPORTS = {hiddenimports!r}",
            f"SCANNED_IMPORTS = {scanned_imports!r}",
            "REQUIRED_IMPORTS = sorted(set(DECLARED_IMPORTS) | set(SCANNED_IMPORTS))",
            "_missing = [m for m in REQUIRED_IMPORTS if find_spec(m) is None]",
            "if _missing:",
            "    print('打包中止：当前解释器缺少依赖', _missing, file=sys.stderr)",
            "    print('解释器:', sys.executable, file=sys.stderr)",
            "    print('site-packages:', [p for p in sys.path if 'site-packages' in p], file=sys.stderr)",
            "    raise SystemExit(1)",
            "",
            "# 顶层包名不等于整个包：asyncua 之类 __init__ 只导出几个名字，",
            "# 实现全在子模块里，必须显式收集。AUTO 来自被 try/except ImportError",
            "# 包住的第三方导入，即使 UI 手填为空也会自动兜底。",
            f"MANUAL_SUBMODULE_ROOTS = {submodule_roots!r}",
            f"AUTO_SUBMODULE_ROOTS = {auto_roots!r}",
            "SUBMODULE_ROOTS = sorted(set(MANUAL_SUBMODULE_ROOTS) | set(AUTO_SUBMODULE_ROOTS))",
            "hiddenimports = list(DECLARED_IMPORTS)",
            "for _root in SUBMODULE_ROOTS:",
            "    hiddenimports.extend(collect_submodules(_root))",
            "hiddenimports = sorted(set(hiddenimports))",
            "",
        ]
        if not hiddenimports:
            lines.insert(3, "# ⚠️ UI 的「隐藏导入」为空；已用 AST 扫描结果自动兜底自检与子模块收集。")
        lines += [
            "a = Analysis(",
            f"    [str(ROOT / {entry_rel.as_posix()!r})],",
            "    pathex=[str(ROOT)],",
            "    binaries=[],",
            f"    datas={datas_expr},",
            "    hiddenimports=hiddenimports,",
            "    hookspath=[],",
            f"    runtime_hooks={hook_expr},",
            "    excludes=[],",
            "    noarchive=False,",
            ")",
            "",
            "pyz = PYZ(a.pure, a.zipped_data, cipher=None)",
            "",
            "exe = EXE(",
            "    pyz,",
            "    a.scripts,",
        ]
        if onefile:
            lines += [
                "    a.binaries,",
                "    a.zipfiles,",
                "    a.datas,",
            ]
        else:
            lines += [
                "    [],",
                "    exclude_binaries=True,",
            ]
        if icon_expr != "None":
            lines.append(f"    icon={icon_expr},")
        lines += [
            f"    name={name!r},",
            "    debug=False,",
            "    bootloader_ignore_signals=False,",
            "    strip=False,",
            f"    upx={upx!r},",
            f"    console={console!r},",
            "    disable_windowed_traceback=False,",
            "    argv_emulation=False,",
            "    target_arch=None,",
            "    codesign_identity=None,",
            "    entitlements_file=None,",
            ")",
        ]
        if not onefile:
            lines += [
                "",
                "coll = COLLECT(",
                "    exe,",
                "    a.binaries,",
                "    a.zipfiles,",
                "    a.datas,",
                "    strip=False,",
                f"    upx={upx!r},",
                "    upx_exclude=[],",
                f"    name={name!r},",
                ")",
            ]
        return "\n".join(lines) + "\n"

    def _spec_text(self) -> str:
        """预览里手工编辑过的 spec 优先，否则按当前界面重新生成。"""
        return self._edited_spec if self._edited_spec else self._generate_spec_content()

    def _preflight(self, python_exe: str) -> tuple:
        """在**真正执行打包的那个解释器**里检查隐藏导入是否装齐。

        GUI 自己跑在哪个解释器里不重要；以前只 ``import PyInstaller`` 做检查，
        而打包命令用的是另一个 python，检查等于没做。
        """
        modules = sorted(set(self.hidden_imports)
                         | set(self._installed_third_party(python_exe)))
        if not modules:
            return True, "无需检查依赖"
        self._log(f"🔍 依赖自检范围：{', '.join(modules)}")
        code = (
            "import importlib.util, json; "
            "print(json.dumps({m: importlib.util.find_spec(m) is not None "
            "for m in " + repr(modules) + "}))"
        )
        try:
            out = subprocess.check_output(
                [python_exe, "-c", code], text=True,
                encoding="utf-8", errors="replace", timeout=30,
            )
            result = json.loads(out.strip().splitlines()[-1])
        except Exception as exc:
            return False, f"无法在指定解释器里自检依赖：{exc}"
        missing = [m for m, ok in result.items() if not ok]
        if missing:
            return False, (
                "指定解释器缺少依赖：" + ", ".join(missing)
                + f"\n解释器: {python_exe}\n"
                "请换到装齐依赖的 .venv/Scripts/python.exe，或先 pip install。"
            )
        return True, f"依赖自检通过：{', '.join(modules)}"

    def _preview_spec(self):
        """预览生成的 spec 文件内容；编辑后的内容会被保存 / 打包真正使用。"""
        try:
            content = self._spec_text()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成 Spec 文件失败: {e}")
            return
        dialog = SpecEditorDialog(content, self)
        if dialog.exec():
            edited = dialog.get_spec_content()
            if edited != content:
                self._edited_spec = edited
                self._log("✏️ 已采用手工编辑的 spec 内容（保存 / 打包都会用它）")
            else:
                self._edited_spec = None
                self._log("ℹ️ 预览未修改，仍按界面配置生成")

    def _save_spec_file(self):
        """保存 spec 文件到项目目录"""
        if not self.project_path:
            QMessageBox.warning(self, "警告", "请先选择项目目录")
            return
        try:
            content = self._spec_text()
            spec_path = self.project_path / f"{self.output_name_edit.text().strip() or 'MyApp'}.spec"
            with open(spec_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            self._log(f"💾 Spec 文件已保存: {spec_path}")
            QMessageBox.information(self, "成功", f"Spec 文件已保存到:\n{spec_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存 Spec 文件失败: {e}")

    # -------------------- 打包流程 --------------------
    def _start_packaging(self):
        """开始打包：生成临时 spec 文件 → 用指定解释器执行 PyInstaller。"""
        if not self.project_path:
            QMessageBox.warning(self, "警告", "请先选择项目目录")
            return

        python_exe = self.python_edit.text().strip() or sys.executable
        if not Path(python_exe).is_file():
            QMessageBox.critical(
                self, "解释器无效", f"找不到 Python 解释器：\n{python_exe}"
            )
            return

        # 在真正打包的解释器里检查依赖（GUI 自己的 site-packages 不算数）
        ok, message = self._preflight(python_exe)
        if not ok:
            QMessageBox.critical(self, "依赖自检未通过", message)
            self._log("❌ " + message)
            return
        self._log("✅ " + message)

        # 生成 spec 内容
        try:
            spec_content = self._spec_text()
        except Exception as e:
            QMessageBox.critical(self, "生成 Spec 失败", str(e))
            return

        # 创建临时 spec 文件（放在项目目录下，便于引用相对路径）
        spec_filename = f"temp_{self.output_name_edit.text().strip() or 'MyApp'}.spec"
        spec_path = self.project_path / spec_filename
        try:
            with open(spec_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(spec_content)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法创建临时 spec 文件: {e}")
            return

        self._log(f"📄 已创建临时 spec 文件: {spec_path}")
        self._log(
            "ℹ️ 提示：COLLECT 会清空同名旧产物目录，需要保留旧包时请先把 dist/<名称> 改名。"
        )

        # 附加参数真正生效（以前只写成 spec 末尾的一行注释）
        extra_raw = self.extra_args_edit.text().strip()
        try:
            extra_args = [
                tok.strip('"').strip("'")
                for tok in shlex.split(extra_raw, posix=False)
            ] if extra_raw else []
        except ValueError as exc:
            QMessageBox.warning(self, "附加参数有误", str(exc))
            return

        # 禁用打包按钮
        self.package_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        # 启动线程
        self.current_thread = PackagerThread(
            spec_path,
            self.project_path,
            python_exe=python_exe,
            distpath=self.output_dir_edit.text().strip(),
            extra_args=extra_args,
            # warn 文件里出现这些模块的「missing module」时判致命，
            # 不只看 UI 手填 —— 隐藏导入被清空过一次，不能让它静默漏掉。
            hidden_imports=sorted(set(self.hidden_imports)
                                  | set(self._installed_third_party(python_exe))),
        )
        self.current_thread.log_signal.connect(self._log)
        self.current_thread.progress_signal.connect(self._update_progress)
        self.current_thread.finished_signal.connect(
            lambda success, msg: self._on_finished(success, msg, spec_path)
        )
        self.current_thread.start()

    def _on_finished(self, success: bool, msg: str, spec_path: Path):
        self.progress_bar.setVisible(False)
        self.package_btn.setEnabled(True)
        self._log(msg)
        # 成功才删临时 spec；失败时留着，warn / spec 内容都还能复盘。
        if success:
            try:
                if spec_path.exists():
                    spec_path.unlink()
                    self._log(f"🗑️ 已删除临时 spec 文件: {spec_path}")
            except Exception:
                pass
        else:
            self._log(f"🔍 临时 spec 保留以便排查: {spec_path}")
            QMessageBox.critical(self, "失败", msg)
            self._log("失败")
            self.current_thread = None
            return
        QMessageBox.information(self, "完成", msg)
        self._log("成功")
        self.current_thread = None

    def _update_progress(self, value: int):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(value)

    def _log(self, msg: str):
        timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")
        self.log_text.append(f"[{timestamp}] {msg}")
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
        if "错误" in msg or "失败" in msg:
            self.statusBar().showMessage("❌ 出错", 5000)
        elif "成功" in msg:
            self.statusBar().showMessage("✅ 成功", 5000)
        else:
            self.statusBar().showMessage("打包中...")

    def _clear_log(self):
        self.log_text.clear()

    # -------------------- 配置持久化 --------------------
    def _save_config(self):
        config = {
            "project_path": str(self.project_path) if self.project_path else "",
            "python": self.python_edit.text(),
            "entry_script": self.entry_edit.text(),
            "output_name": self.output_name_edit.text(),
            "output_dir": self.output_dir_edit.text(),
            "onefile": self.onefile_cb.isChecked(),
            "console": self.console_cb.isChecked(),
            "icon": self.icon_edit.text(),
            "hidden_imports": self.hidden_imports,
            "collect_submodules": self.collect_submodules_cb.isChecked(),
            "upx": self.upx_cb.isChecked(),
            "runtime_hook": self.runtime_hook_edit.text(),
            "extra_args": self.extra_args_edit.text(),
            "resources": self.include_resources,
            "resource_dests": self.resource_dests,
        }
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            self._log(f"💾 配置已保存至 {self.config_file}")
        except Exception as e:
            self._log(f"⚠️ 保存配置失败: {e}")

    def _load_config(self):
        if not self.config_file.exists():
            return
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
            if config.get("project_path") and Path(config["project_path"]).exists():
                self.project_path = Path(config["project_path"])
                self.project_edit.setText(config["project_path"])
            self.python_edit.setText(config.get("python") or sys.executable)
            self.entry_edit.setText(config.get("entry_script", ""))
            self.output_name_edit.setText(config.get("output_name", "MyApp"))
            self.output_dir_edit.setText(config.get("output_dir", ""))
            self.onefile_cb.setChecked(config.get("onefile", True))
            self.console_cb.setChecked(config.get("console", False))
            self.icon_edit.setText(config.get("icon", ""))
            self.hidden_imports = config.get("hidden_imports", [])
            for mod in self.hidden_imports:
                self.hidden_imports_list.addItem(mod)
            self.collect_submodules_cb.setChecked(
                config.get("collect_submodules", True)
            )
            self.upx_cb.setChecked(config.get("upx", False))
            self.runtime_hook_edit.setText(config.get("runtime_hook", ""))
            self.extra_args_edit.setText(config.get("extra_args", ""))
            # 资源列表：旧配置只有源路径，缺目标时按相对项目路径补默认值
            self.include_resources = config.get("resources", [])
            self.resource_dests = dict(config.get("resource_dests", {}))
            for res in self.include_resources:
                if res not in self.resource_dests:
                    self.resource_dests[res] = self._default_dest(Path(res))
            self._reload_resource_list()
            self._log("⚙️ 已加载上次配置")
        except Exception as e:
            self._log(f"⚠️ 加载配置失败: {e}")

    def closeEvent(self, event):
        self._save_config()
        if self.current_thread and self.current_thread.isRunning():
            reply = QMessageBox.question(
                self, "确认退出",
                "打包任务尚未完成，确定退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.current_thread.terminate()
                self.current_thread.wait(1000)
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = PythonPackager()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()