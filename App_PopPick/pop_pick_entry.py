"""PopPick 运行态窗口：加载设计页，点左侧页签与右侧当前页互换。

场景来自设计器的页面文件（默认 ``page_9``）：左侧几张卡扇形堆叠，右侧一张
是「当前页」。运行态把场景切到 ``SceneMode.Run`` 只读显示，卡片上的真实控件
设为鼠标穿透，点击事件落到场景上，再由 :class:`PageDeck` 做命中测试与交换
动画。

运行方式::

    python pop_pick_main.py                 # 经统一入口（--app PopPick）
    python -m App_PopPick                   # 等价
    python App_PopPick/pop_pick_entry.py --page page_9
    python App_PopPick/pop_pick_entry.py --scene <绝对路径>.json

页面文件查找顺序：``--scene`` 指定 → 设计工程 ``pages/page_9.json``（源码运行，
设计器改完直接生效）→ ``res/myDesigner/scene/pop_pick_scene.json``（打包后的
运行态快照，需要同步更新时直接从 page_9 拷一份覆盖）。

为什么不用 ``load_element_info_run_mode``
-----------------------------------------
那个入口（``SceneSerializer.deserialize_scene(mode=Run)``）只认
``res/myDesigner/scene`` 下的场景名，而这里要读的是**设计工程里正在编辑的
页面文件**（设计器改完立刻能看效果，不用先导出一份运行态场景）。
``deserialize_scene`` 的 ``mode`` 只用来选路径解析器（Design 分支支持绝对
路径），场景模式随后由 :meth:`set_scene_mode` 显式切换，不影响语义。
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from typing import Optional, Sequence

# 项目根加进 sys.path：单独跑本文件时 Designer 包才 import 得到
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

from Designer.Core.myQuadTreeScene import QuadTreeScene, SceneManager, SceneSerializer
from Designer.Core.my_common import SceneMode
# 用绝对导入而不是 ``from .page_deck``：本文件也支持被直接当脚本跑
# （``python App_PopPick/pop_pick_entry.py``），那时没有包上下文。
from App_PopPick.page_deck import PageDeck, find_page_cards

APP_TITLE = "PopPick 拣选工作站"
DEFAULT_PAGE = "page_9"
DEFAULT_PLC_IP = "192.168.1.88"


def _page_file_candidates(page: str) -> list[str]:
    """页面文件的候选路径（源码运行 → 打包后的运行态场景副本）。"""
    candidates = [
        os.path.join(
            _PROJECT_ROOT, "Designer", "Core", "data.json", "datas", "design",
            "pages", f"{page}.json",
        )
    ]
    if getattr(sys, "frozen", False):
        # 打包后设计工程不一定跟着走，退到 res 下的运行态场景副本
        try:
            from res.designer_resource_manager import resource_manager as res_mng

            candidates.append(res_mng.get_json_path("pop_pick_scene.json"))
        except Exception:  # noqa: BLE001 - 资源包缺失时按"没找到"处理
            pass
    return candidates


def resolve_page_file(page: str) -> str:
    for path in _page_file_candidates(page):
        if path and os.path.isfile(path):
            return path
    tried = "\n".join(_page_file_candidates(page))
    raise FileNotFoundError(f"找不到页面文件「{page}」，已尝试：\n{tried}")


class PopPickWindow(QMainWindow):
    """运行态主窗口：一张场景 + 一个页面堆叠交互。"""

    def __init__(
        self,
        *,
        page: str = DEFAULT_PAGE,
        scene_path: Optional[str] = None,
        plc_ip: str = DEFAULT_PLC_IP,
        enable_plc: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.plc_ip = plc_ip
        self.enable_plc = enable_plc
        self.scene_path: Optional[str] = None
        self.deck: Optional[PageDeck] = None

        self._press_pos: Optional[QPointF] = None
        self._dragged = False

        self.setObjectName("popPickWindow")
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 820)
        self.statusBar().showMessage("正在加载场景…")

        self._build_scene()
        self._load_scene(scene_path or resolve_page_file(page))
        self._install_deck()
        self._build_actions()

        self.statusBar().showMessage(
            "点击左侧任意页面，与右侧当前页互换（拖动可平移画布）"
        )

    # ------------------------------------------------------------------
    # 场景
    # ------------------------------------------------------------------
    def _build_scene(self) -> None:
        self.scene = QuadTreeScene(parent=self)
        self.scene.setObjectName("popPickScene")
        self.scene_manager = SceneManager(self.scene, parent=self)
        self.scene.set_scene_manager(self.scene_manager)
        # 运行态没有 PLC 渲染回调，显式清空避免访问空对象
        self.scene.update_callback = None
        self.setCentralWidget(self.scene)
        self.scene.installEventFilter(self)

    def _load_scene(self, path: str) -> None:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"场景文件不存在: {path}")
        self.scene_path = path

        self.scene.delete_all_elements()
        # mode 只决定路径解析器（Design 分支支持绝对路径），见模块头说明
        SceneSerializer.deserialize_scene(self.scene, path, mode=SceneMode.Design)
        # 先加载再切模式：set_scene_mode 里那轮 embedded widget 同步只有在
        # 图元已入库时才有效，反过来做运行态一个控件都不会挂载。
        self.scene.set_scene_mode(SceneMode.Run)

    # ------------------------------------------------------------------
    # 页面堆叠
    # ------------------------------------------------------------------
    def _install_deck(self) -> None:
        cards = find_page_cards(self.scene_manager.m_sorted_items)
        if len(cards) < 2:
            raise RuntimeError(
                f"页面「{os.path.basename(str(self.scene_path))}」里只有 "
                f"{len(cards)} 张卡片图元，无法做页面互换"
            )
        for card in cards:
            # 只读 → 承载视图与控件都设 WA_TransparentForMouseEvents，
            # 点击才能穿透到场景（否则一下点就被 QTextEdit 自己吃掉）。
            card.set_widget_readonly(True)

        self.deck = PageDeck(self.scene, cards, parent=self)
        self.deck.swap_finished.connect(self._on_swap_finished)
        # 卡片布局依赖窗口尺寸（视图坐标），布局收敛后再对一次视图
        self.scene.refresh_embedded_widgets()

    def _on_swap_finished(self, entered: str, left: str) -> None:
        self.statusBar().showMessage(f"已切换到「{entered}」，「{left}」已放回左侧", 4000)

    # ------------------------------------------------------------------
    # 工具栏
    # ------------------------------------------------------------------
    def _build_actions(self) -> None:
        toolbar = self.addToolBar("页面")
        toolbar.setObjectName("pop_pick_toolbar")
        toolbar.setMovable(False)

        reset_action = QAction("重置布局", self)
        reset_action.setToolTip("把卡片放回页面文件里记录的初始位姿与 Z 值")
        reset_action.triggered.connect(self._reset_layout)
        toolbar.addAction(reset_action)

        fit_action = QAction("适应窗口", self)
        fit_action.setToolTip("缩放到能看全所有卡片")
        fit_action.triggered.connect(self._fit_view)
        toolbar.addAction(fit_action)

        self.plc_status_action = QAction(
            "PLC：未接入" if self.enable_plc else "PLC：离线", self
        )
        self.plc_status_action.setEnabled(False)
        self.plc_status_action.setToolTip(
            f"预留地址 {self.plc_ip}；当前版本只做页面交互，未接 PLC 数据链路"
        )
        toolbar.addAction(self.plc_status_action)

    def _reset_layout(self) -> None:
        if self.deck is None:
            return
        self.deck.reset()
        self.statusBar().showMessage("已恢复初始布局", 2500)

    def _fit_view(self) -> None:
        rect = QRectF()
        for item in self.scene_manager.m_sorted_items:
            if not item.get_visibility():
                continue
            bound = item.sceneBoundingRect()
            rect = bound if rect.isNull() else rect.united(bound)
        if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
            return
        # 留一圈边距，卡片边框和旋转后的尖角不贴边
        margin = max(rect.width(), rect.height()) * 0.04
        self.scene.set_view_scene_rect(rect.adjusted(-margin, -margin, margin, margin))
        # 改的是场景的 offset / scale，卡片实体（承载视图）必须跟着重排。
        # 滚轮缩放和拖拽平移都在 myQuadTreeScene 里各自补了这一步，走
        # ``set_view_scene_rect`` 这条程序化路径不会自动触发；漏了就会出现
        # "黑边框缩放了、白卡片没动"的错位画面。
        self.scene.refresh_embedded_widgets()

    # ------------------------------------------------------------------
    # 鼠标：把"点一下卡片"翻译成一次交换
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):  # noqa: N802 - Qt 命名
        if obj is not self.scene:
            return super().eventFilter(obj, event)

        kind = event.type()
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._press_pos = QPointF(event.position())
            self._dragged = False
        elif kind == QEvent.MouseMove and self._press_pos is not None:
            distance = (QPointF(event.position()) - self._press_pos).manhattanLength()
            if distance >= QApplication.startDragDistance():
                self._dragged = True
        elif kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            press, dragged = self._press_pos, self._dragged
            self._press_pos = None
            self._dragged = False
            # 拖动是"平移画布"（场景自己处理），只有原地按放才算点击
            if press is not None and not dragged:
                self._handle_click(QPointF(event.position()))
        return super().eventFilter(obj, event)

    def _handle_click(self, window_pos: QPointF) -> None:
        if self.deck is None or self.deck.is_busy():
            return
        card = self.deck.card_at(self._window_to_scene(window_pos))
        if card is None:
            return
        if card is self.deck.slot_card():
            self.statusBar().showMessage("这是当前页，点左侧任意页面进行互换", 2500)
            return
        self.deck.swap_with_slot(card)

    def _window_to_scene(self, window_pos: QPointF) -> QPointF:
        """窗口像素 → 场景坐标。

        绘制链是 ``painter.translate(offset); painter.scale(scale_factor)`` 后
        再按 ``sceneToView`` 映射，因此逆运算先去掉 offset 与缩放，再走
        ``viewToScene``（那里已经带 AGV 的轴交换）。
        """
        scale = self.scene.scale_factor or 1.0
        view_pos = (window_pos - self.scene.offset) / scale
        return self.scene.viewToScene(view_pos)

    # ------------------------------------------------------------------
    def closeEvent(self, event):  # noqa: N802 - Qt 命名
        if self.deck is not None:
            self.deck.stop()
        super().closeEvent(event)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="pop_pick_entry.py", description=APP_TITLE)
    parser.add_argument(
        "--page", default=DEFAULT_PAGE, help=f"设计工程里的页面 id（默认 {DEFAULT_PAGE}）"
    )
    parser.add_argument("--scene", default=None, help="直接指定页面 JSON 的绝对路径")
    parser.add_argument("--plc-ip", default=DEFAULT_PLC_IP, help="预留的 PLC 地址")
    parser.add_argument("--no-plc", action="store_true", help="离线模式（当前版本无差别）")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication([sys.argv[0]])

    try:
        window = PopPickWindow(
            page=args.page,
            scene_path=args.scene,
            plc_ip=args.plc_ip,
            enable_plc=not args.no_plc,
        )
    except Exception as exc:  # noqa: BLE001 - 启动失败要给出可读原因
        traceback.print_exc()
        QMessageBox.critical(None, "启动失败", f"{type(exc).__name__}: {exc}")
        return 2

    window.show()
    if owns_app:
        return app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
