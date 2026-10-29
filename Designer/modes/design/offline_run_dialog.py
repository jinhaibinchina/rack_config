"""Read-only offline preview of a design page in run mode."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QVBoxLayout,
)

from Designer.Core.my_common import SceneMode
from Designer.Core.myQuadTreeScene import QuadTreeScene, SceneManager

from .project_store import PageMeta, ProjectStore


class OfflineRunDialog(QDialog):
    """Show one design page exactly as the run-mode scene renders it.

    The dialog owns a dedicated scene instead of switching the design page
    itself, so opening the preview can never change the editor's mode,
    selection or grid state.  No PLC/data-broker connection is created:
    dynamic values simply keep their serialized defaults.
    """

    def __init__(self, page: PageMeta, store: ProjectStore, parent=None):
        super().__init__(parent)
        self.setObjectName("offlineRunDialog")
        self.setWindowTitle(f"离线运行 · {page.name}")
        self.resize(1200, 800)
        self.setModal(True)
        self.setStyleSheet(
            """
            QDialog#offlineRunDialog { background: #f3f4f6; }
            QFrame#offlineRunHeader {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
            }
            QLabel#offlineRunTitle {
                font-size: 16px;
                font-weight: 600;
                color: #111827;
            }
            QLabel#offlineRunModeLabel {
                color: #1d4ed8;
                font-weight: 600;
            }
            QLabel#offlineRunHint { color: #6b7280; }
            """
        )

        self.page = page
        self.store = store

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        self.scene = QuadTreeScene(parent=self)
        self.scene.setObjectName(f"offline_run_scene_{page.id}")
        self.scene.scene_file_path = store.page_path(page)
        self.manager = SceneManager(self.scene, parent=self)
        self.scene.set_scene_manager(self.manager)

        root_layout.addWidget(self._build_header(page))
        root_layout.addWidget(self.scene, 1)
        root_layout.addWidget(self._build_footer())

        self.scene.load_element_info(store.page_path(page))
        self._enter_run_mode()
        self._start_scene_timers()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_header(self, page: PageMeta) -> QFrame:
        header = QFrame(self)
        header.setObjectName("offlineRunHeader")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        title = QLabel(f"主场景：{page.name}", header)
        title.setObjectName("offlineRunTitle")
        self.mode_label = QLabel(
            f"运行模式：{SceneMode.Run.name}（离线运行）", header
        )
        self.mode_label.setObjectName("offlineRunModeLabel")
        hint = QLabel(
            "离线预览：不连接 PLC 与数据总线，事件绑定写入离线变量表。",
            header,
        )
        hint.setObjectName("offlineRunHint")
        hint.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(self.mode_label)
        layout.addWidget(hint)
        return header

    def _build_footer(self) -> QDialogButtonBox:
        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.setObjectName("offlineRunButtons")
        close_button = buttons.button(QDialogButtonBox.Close)
        if close_button is not None:
            close_button.setText("关闭")
        buttons.rejected.connect(self.reject)
        return buttons

    # ------------------------------------------------------------------
    # Run-mode scene setup
    # ------------------------------------------------------------------
    def _enter_run_mode(self) -> None:
        # ``toggle_sence_mode`` disables selection before switching and hides
        # grid/coordinates through ``set_scene_mode``, matching main.py.
        if self.scene.mode() != SceneMode.Design:
            self.scene.set_scene_mode(SceneMode.Design)
        self.scene.toggle_sence_mode()
        self.scene.setFocusPolicy(Qt.NoFocus)
        # Reflect the real scene mode instead of relying on the hard-coded
        # label built before the page file was loaded.
        self.mode_label.setText(
            f"运行模式：{self.scene.mode().name}（离线运行）"
        )

    def _start_scene_timers(self) -> None:
        for name, interval in (
            ("render_timer", 16),
            ("frame_count_timer", 1000),
            ("timer1", 500),
        ):
            timer = getattr(self.scene, name, None)
            if timer is not None and not timer.isActive():
                timer.start(interval)

    def _stop_scene_timers(self) -> None:
        for name in ("render_timer", "frame_count_timer", "timer1", "timer2"):
            timer = getattr(self.scene, name, None)
            if timer is not None:
                timer.stop()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def done(self, result: int) -> None:
        self._stop_scene_timers()
        super().done(result)
