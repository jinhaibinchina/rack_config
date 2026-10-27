#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PyInstaller 打包工具 (基于 Spec 文件)
可视化配置项目、资源、高级选项，生成 spec 文件后执行打包。
"""
import shutil
import sys
import os
import subprocess
import json
import tempfile
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

    def __init__(self, spec_file: Path, project_path: Path):
        super().__init__()
        self.spec_file = spec_file
        self.project_path = project_path

    def run(self) -> None:
        try:


        #     self.log_signal.emit("🚀 开始基于 Spec 文件打包...")
        #     cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", str(self.spec_file)]
        #     self.log_signal.emit(f"📦 执行命令: {' '.join(cmd)}")

        #     process = subprocess.Popen(
        #         cmd,
        #         stdout=subprocess.PIPE,
        #         stderr=subprocess.STDOUT,
        #         text=True,
        #         encoding='utf-8',
        #         errors='replace',
        #         cwd=str(self.project_path)
        #     )

        #     for line in process.stdout:
        #         if line.strip():
        #             self.log_signal.emit(line.rstrip())
        #         if "building EXE" in line.lower():
        #             self.progress_signal.emit(60)
        #         elif "building PKG" in line.lower():
        #             self.progress_signal.emit(40)

        #     process.wait()
        #     self.progress_signal.emit(100)

        #     if process.returncode == 0:
        #         self.finished_signal.emit(True, "✅ 打包成功！")
        #     else:
        #         self.finished_signal.emit(False, f"❌ 打包失败，返回码: {process.returncode}")

        # except Exception as e:
        #     self.finished_signal.emit(False, f"⚠️ 打包过程异常: {str(e)}")
       
            self.log_signal.emit("🚀 开始基于 Spec 文件打包...")
            
            # 确定 pyinstaller 命令
            pyinstaller_cmd = shutil.which('pyinstaller')
            if pyinstaller_cmd:
                cmd = [pyinstaller_cmd, "--noconfirm", str(self.spec_file)]
            else:
                # 如果没有 pyinstaller 命令，尝试使用 python -m PyInstaller
                # 但在打包后的 EXE 中，sys.executable 是 exe 自身，会递归启动
                if getattr(sys, 'frozen', False):
                    self.finished_signal.emit(False, 
                        "❌ 未找到 pyinstaller 命令，且当前为打包后的 EXE 环境，无法使用 python -m 方式。\n"
                        "请确保已安装 PyInstaller 并加入 PATH，或使用 Python 环境运行本工具。")
                    return
                else:
                    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", str(self.spec_file)]
            
            self.log_signal.emit(f"📦 执行命令: {' '.join(cmd)}")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=str(self.project_path)
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

            if process.returncode == 0:
                self.finished_signal.emit(True, "✅ 打包成功！")
                
            else:
                self.finished_signal.emit(False, f"❌ 打包失败，返回码: {process.returncode}")

        except Exception as e:
            self.finished_signal.emit(False, f"⚠️ 打包过程异常: {str(e)}")

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
        self.hidden_imports: List[str] = []
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

        self.resource_list = QListWidget()
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

    def _remove_hidden_import(self):
        current = self.hidden_imports_list.currentRow()
        if current >= 0:
            item = self.hidden_imports_list.takeItem(current)
            module = item.text()
            if module in self.hidden_imports:
                self.hidden_imports.remove(module)
            self._log(f"➖ 移除隐藏导入: {module}")

    def _add_resource_file(self):
        if not self.project_path:
            QMessageBox.warning(self, "提示", "请先选择项目目录")
            return
        files, _ = QFileDialog.getOpenFileNames(self, "选择资源文件", str(self.project_path))
        for f in files:
            if f not in self.include_resources:
                self.include_resources.append(f)
                
                self.resource_list.addItem(f)
                self._log(f"➕ 添加资源文件: {f}")

    def _add_resource_folder(self):
        if not self.project_path:
            QMessageBox.warning(self, "提示", "请先选择项目目录")
            return
        folder = QFileDialog.getExistingDirectory(self, "选择资源文件夹", str(self.project_path))
        if folder and folder not in self.include_resources:
            self.include_resources.append(folder)
            item = QListWidgetItem(f"📁 {folder}")
            item.setData(Qt.ItemDataRole.UserRole, folder)
            self.resource_list.addItem(item)
            self._log(f"➕ 添加资源文件夹: {folder}")

    def _remove_resource(self):
        current = self.resource_list.currentRow()
        if current >= 0:
            item = self.resource_list.takeItem(current)
            path = item.data(Qt.ItemDataRole.UserRole) or item.text()
            if path.startswith("📁 "):
                path = path[2:]
            if path in self.include_resources:
                self.include_resources.remove(path)
            self._log(f"➖ 移除资源: {path}")

    def _clear_resources(self):
        self.resource_list.clear()
        self.include_resources.clear()
        self._log("🗑️ 已清空所有附加资源")

    # -------------------- Spec 生成核心 --------------------
    def _generate_spec_content(self) -> str:
        """根据当前界面配置生成 spec 文件内容"""
        if not self.project_path:
            raise ValueError("请先选择项目目录")

        # 入口脚本
        entry_script = self.entry_edit.text().strip()
        if not entry_script:
            # 自动检测
            candidates = list(self.project_path.glob("*.py"))
            if not candidates:
                raise ValueError("未找到任何 Python 入口文件")
            entry_script = str(next((f for f in candidates if f.name == "main.py"), candidates[0]))
        entry_abs = Path(entry_script)
        if not entry_abs.is_absolute():
            entry_abs = self.project_path / entry_script
        entry_rel = entry_abs.relative_to(self.project_path)

        # 输出名称
        name = self.output_name_edit.text().strip() or "MyApp"

        # 构建 datas 列表 (格式: (源路径, 目标路径))
        datas = []
        for res in self.include_resources:
            src = Path(res)
            if not src.exists():
                continue
            # 计算相对路径
            try:
                rel = src.relative_to(self.project_path)
            except ValueError:
                rel = src
            if src.is_dir():
                dest = str(rel)  # 保持目录结构
            else:
                dest = str(rel.parent) if rel.parent != Path('.') else '.'
            datas.append((str(src), dest))

        # 隐藏导入
        hiddenimports = self.hidden_imports

        
        # 图标处理
        icon = None
        icon_str = self.icon_edit.text().strip()
        if icon_str:
            icon_path = Path(icon_str)
            if not icon_path.is_absolute():
                icon_path = self.project_path / icon_path
            if icon_path.exists():
                icon = icon_path.as_posix()  # 使用正斜杠，避免转义
            else:
                self._log(f"⚠️ 图标文件不存在: {icon_path}")

        # 运行时钩子
        runtime_hook = None
        hook_str = self.runtime_hook_edit.text().strip()
        if hook_str:
            hook_path = Path(hook_str)
            if not hook_path.is_absolute():
                hook_path = self.project_path / hook_path
            if hook_path.exists():
                runtime_hook = hook_path.as_posix()
            else:
                self._log(f"⚠️ 运行时钩子文件不存在: {hook_path}")

        # 输出目录
        distpath = self.output_dir_edit.text().strip()
        if not distpath:
            distpath = str(self.project_path / "dist")

        # 控制台 / 窗口模式
        console = self.console_cb.isChecked()

        # 单文件 / 单目录
        onefile = self.onefile_cb.isChecked()

        # UPX
        upx = self.upx_cb.isChecked()

        # 额外参数（字符串解析为列表，简单处理）
        extra_args_str = self.extra_args_edit.text().strip()
        extra_args = extra_args_str.split() if extra_args_str else []

        # 生成 spec 文本（使用 triple quotes 避免转义）
        spec_lines = [
            "# -*- mode: python ; coding: utf-8 -*-",
            "",
            "a = Analysis(",
            f"    ['{entry_rel.as_posix()}'],",
            f"    pathex=['{self.project_path.as_posix()}'],",
            f"    binaries=[],",
            f"    datas={repr(datas)},",
            f"    hiddenimports={repr(hiddenimports)},",
            f"    hookspath=[],"
        ]
        if runtime_hook:
            spec_lines.append(f"    runtime_hooks=['{runtime_hook}'],")
        else:
            spec_lines.append("    runtime_hooks=[],")
        spec_lines.append("    excludes=[],")
        spec_lines.append("    noarchive=False,")
        spec_lines.append(")")

        pyz_lines = [
            "",
            "pyz = PYZ(a.pure, a.zipped_data, cipher=None)",
            ""
        ]
        if onefile:
            exe_lines = [
                "exe = EXE(",
                "    pyz,",
                "    a.scripts,",
                "    a.binaries,",
                "    a.zipfiles,",
                "    a.datas,",
            ]
        else:
            exe_lines = [
                "exe = EXE(",
                "    pyz,",
                "    a.scripts,",
                "    [],",
                "    exclude_binaries=True,",
             
            ]
        if icon:
            exe_lines.append(f"    icon='{icon}',")

        exe_lines.append(f"    name='{name}',")
        exe_lines.append(f"    debug=False,")
        exe_lines.append(f"    bootloader_ignore_signals=False,")
        exe_lines.append(f"    strip=False,")
        exe_lines.append(f"    upx={repr(upx)},")
        exe_lines.append(f"    console={repr(console)},")
        exe_lines.append(f"    disable_windowed_traceback=False,")
        exe_lines.append(f"    argv_emulation=False,")
        exe_lines.append(f"    target_arch=None,")
        exe_lines.append(f"    codesign_identity=None,")
        exe_lines.append(f"    entitlements_file=None,")
        exe_lines.append(")")

        coll_lines = [
            "",
            f"coll = COLLECT(exe,",
            f"    a.binaries,",
            f"    a.zipfiles,",
            f"    a.datas,",
            f"    strip=False,",
            f"    upx={repr(upx)},",
            f"    upx_exclude=[],",
            f"    name='{name}',",
            ")"
        ]

        # 如果是单文件，使用 EXE 直接生成，不需要 COLLECT
        if onefile:
            # 移除 COLLECT 部分，EXE 中已包含所有内容
            spec_content = "\n".join(spec_lines + pyz_lines + exe_lines)
        else:
            spec_content = "\n".join(spec_lines + pyz_lines + exe_lines + coll_lines)

        # 添加额外参数注释 (不直接影响 spec 内容，但在打包命令中体现)
        if extra_args:
            spec_content += f"\n\n# 注意: 附加参数 {extra_args} 需要在命令行中手动添加，或直接修改 spec 文件。\n"
        return spec_content

    def _preview_spec(self):
        """预览生成的 spec 文件内容"""
        try:
            content = self._generate_spec_content()
            dialog = SpecEditorDialog(content, self)
            if dialog.exec():
                # 如果用户编辑后点击确定，可以选择是否应用
                edited = dialog.get_spec_content()
                if edited != content:
                    reply = QMessageBox.question(
                        self, "应用修改", "是否将编辑后的内容保存到当前配置中？\n注意：不会自动保存到 spec 文件，需要手动保存。",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        # 这里可以解析修改后的 spec 并更新界面控件，但比较复杂，简单提示即可
                        QMessageBox.information(self, "提示", "请手动点击「保存 Spec 文件到项目」来保存当前编辑内容。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成 Spec 文件失败: {e}")

    def _save_spec_file(self):
        """保存 spec 文件到项目目录"""
        if not self.project_path:
            QMessageBox.warning(self, "警告", "请先选择项目目录")
            return
        try:
            content = self._generate_spec_content()
            spec_path = self.project_path / f"{self.output_name_edit.text().strip() or 'MyApp'}.spec"
            with open(spec_path, "w", encoding="utf-8") as f:
                f.write(content)
            self._log(f"💾 Spec 文件已保存: {spec_path}")
            QMessageBox.information(self, "成功", f"Spec 文件已保存到:\n{spec_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存 Spec 文件失败: {e}")

    # -------------------- 打包流程 --------------------
    def _start_packaging(self):
        """开始打包：生成临时 spec 文件 → 执行 pyinstaller spec"""
        if not self.project_path:
            QMessageBox.warning(self, "警告", "请先选择项目目录")
            return

        # 检查 PyInstaller
        try:
            import PyInstaller  # noqa
        except ImportError:
            QMessageBox.critical(self, "缺少依赖", "未安装 PyInstaller，请执行: pip install pyinstaller")
            return

        # 生成 spec 内容
        try:
            spec_content = self._generate_spec_content()
        except Exception as e:
            QMessageBox.critical(self, "生成 Spec 失败", str(e))
            return

        # 创建临时 spec 文件（放在项目目录下，便于引用相对路径）
        spec_filename = f"temp_{self.output_name_edit.text().strip() or 'MyApp'}.spec"
        spec_path = self.project_path / spec_filename
        try:
            with open(spec_path, "w", encoding="utf-8") as f:
                f.write(spec_content)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法创建临时 spec 文件: {e}")
            return

        self._log(f"📄 已创建临时 spec 文件: {spec_path}")

        # 禁用打包按钮
        self.package_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        # 启动线程
        self.current_thread = PackagerThread(spec_path, self.project_path)
        self.current_thread.log_signal.connect(self._log)
        self.current_thread.progress_signal.connect(self._update_progress)
        self.current_thread.finished_signal.connect(lambda success, msg: self._on_finished(success, msg, spec_path))
        self.current_thread.start()

    def _on_finished(self, success: bool, msg: str, spec_path: Path):
        self.progress_bar.setVisible(False)
        self.package_btn.setEnabled(True)
        self._log(msg)
        # 删除临时 spec 文件（可选，保留便于调试）
        try:
            if spec_path.exists():
                spec_path.unlink()
                self._log(f"🗑️ 已删除临时 spec 文件: {spec_path}")
        except Exception:
            pass
        if success:
            QMessageBox.information(self, "完成", msg)
            self._log("成功")
        else:
            QMessageBox.critical(self, "失败", msg)
            self._log("失败")
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
            "entry_script": self.entry_edit.text(),
            "output_name": self.output_name_edit.text(),
            "output_dir": self.output_dir_edit.text(),
            "onefile": self.onefile_cb.isChecked(),
            "console": self.console_cb.isChecked(),
            "icon": self.icon_edit.text(),
            "hidden_imports": self.hidden_imports,
            "upx": self.upx_cb.isChecked(),
            "runtime_hook": self.runtime_hook_edit.text(),
            "extra_args": self.extra_args_edit.text(),
            "resources": self.include_resources,
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
            self.entry_edit.setText(config.get("entry_script", ""))
            self.output_name_edit.setText(config.get("output_name", "MyApp"))
            self.output_dir_edit.setText(config.get("output_dir", ""))
            self.onefile_cb.setChecked(config.get("onefile", True))
            self.console_cb.setChecked(config.get("console", False))
            self.icon_edit.setText(config.get("icon", ""))
            self.hidden_imports = config.get("hidden_imports", [])
            for mod in self.hidden_imports:
                self.hidden_imports_list.addItem(mod)
            self.upx_cb.setChecked(config.get("upx", False))
            self.runtime_hook_edit.setText(config.get("runtime_hook", ""))
            self.extra_args_edit.setText(config.get("extra_args", ""))
            # 资源列表
            self.include_resources = config.get("resources", [])
            for res in self.include_resources:
                if Path(res).is_dir():
                    self.resource_list.addItem(f"📁 {res}")
                else:
                    self.resource_list.addItem(res)
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