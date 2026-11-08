"""料仓全局参数面板 V2：场景后端换成 ``Designer/CoreQGraphics``。

与旧 ``rack_global_paras_widget.RackGlobalParasWindow`` 的对应关系：

============================================  ==========================================
旧（Designer/Core）                            新（Designer/CoreQGraphics）
============================================  ==========================================
``QuadTreeScene`` + ``SceneManager``            ``GraphicsScene`` + ``GraphicsView``
``set_scene_mode(SceneMode.Run)``               ``set_scene_mode(True)``
``load_element_info_run_mode(json)``            ``load_page(绝对路径)``
``EmbeddedWidgetLayer`` 挂真实控件              ``QGraphicsProxyWidget`` 挂真实控件
``findItemByName`` → ``_leaf_widget()``         ``find_item_by_name`` → ``widget_proxies``
``set_canvas_navigation_enabled(False)``        :class:`_ReadOnlyView`（禁缩放/平移/右键）
============================================  ==========================================

三条约定：

1. **顺序** ``load_page()`` → ``set_scene_mode(True)``。运行态才创建 proxy，
   顺序反了会拿到空场景、一个控件都挂不上。
2. **取景与旧窗口同口径**：``fit``（默认）＝ ``min(视口宽/页面宽,
   视口高/页面高)`` 等比适配，**允许放大**——旧 ``QuadTreeScene`` 在 Run 态就是
   这么算的，392×900 面板下 878/805.7 ≈ 1.0897，页面顶到上下边缘。改成
   「不放大」会让整幅画面小 9%，与旧窗口对不上。需要像素最清晰的 1:1 时可传
   ``fit_mode="native"``。
3. **只读**：滚轮 / 中键 / 空格 / 右键菜单 / 设计器快捷键一律拦掉，面板上
   能点的只有场景里那几个控件本身。

控件句柄由 :class:`RackGlobalParasModelV2` 管理，交互（勾选、改数字）直接写
PLC DB41；``apply_db41()`` 只做回显，不回写。
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

# 允许以脚本方式单独跑本文件（``python App_RackConfig/run/..._v2.py``）
if __package__ in (None, ""):
    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)

from Designer.CoreQGraphics import GraphicsScene, GraphicsView
from res.designer_resource_manager import resource_manager as res_mng

from .rack_global_paras_model_v2 import (
    CHECKBOX_BINDINGS,
    SPINBOX_BINDINGS,
    RackGlobalParasModelV2,
)

# 与旧窗口同一个页面文件（设计器工程 → res 快照，源码 / 打包都能命中）
SCENE_NAME = "rack_requirements_scene3.json"


class _ReadOnlyView(GraphicsView):
    """运行态视图：去掉一切设计态输入（缩放、平移、右键菜单、快捷键）。

    ``GraphicsView`` 的自绘层已经按 ``is_run_mode`` 屏蔽了红点 / 拖角手柄 /
    捕捉十字，所以这里只处理**输入**：滚轮缩放、中键与空格平移、右键菜单、
    以及 Delete / G / T / +/- 这类会改场景的快捷键。

    导航开关不在本类里另存状态，直接用基类的 ``set_pan_enabled`` /
    ``set_zoom_enabled``；构造时统一关掉，需要放大看细节再显式打开。
    """

    def __init__(self, scene=None, parent=None) -> None:
        super().__init__(scene, parent)
        self.setDragMode(GraphicsView.NoDrag)          # 不要框选橡皮筋
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.StrongFocus)
        # QGraphicsView 默认带 1px 凹陷边框，会让 viewport 比控件小 2px。
        # 旧 QuadTreeScene 是自绘 widget，没有这层边框；留着它取景就永远差
        # 一两个百分点（370×878 的可用区变成 368×876）。
        self.setFrameShape(QFrame.NoFrame)
        # 运行态不画设计网格 / 捕捉标记：GridView.drawBackground 只看这两个
        # 开关（不看 is_run_mode），不关掉面板背后会是一片网格。
        self.show_grid = False
        self.snap.grid_enabled = False
        self.snap.show_markers = False
        # 运行态默认不许拖拽 / 缩放；要放开只调这一个开关。
        self.set_canvas_navigation_enabled(False)
        # 视口尺寸变化时回调窗口重新取景。窗口自身的 resizeEvent 在
        # 「先 resize 再 show」的调用顺序下不会触发（布局是在 show 时才把
        # 视图撑开的），只挂窗口那一头会拿到 show 之前的旧视口尺寸，
        # 于是 fitInView 按极小的 viewport 算出一个离谱的缩放。
        self.on_viewport_resized = None

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if callable(self.on_viewport_resized):
            self.on_viewport_resized()

    def mousePressEvent(self, event: QMouseEvent) -> None:   # noqa: N802
        # 右键在设计器里是上下文菜单，运行态一律吞掉；中键只在导航开启时
        # 交给基类（基类据此进平移状态，并在 release 时收尾）。
        # 左键仍交给基类，控件（proxy）才收得到点击。
        if event.button() == Qt.RightButton:
            event.accept()
            return
        if event.button() == Qt.MiddleButton and not self.is_pan_enabled():
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.RightButton:
            event.accept()
            return
        if event.button() == Qt.MiddleButton and not self.is_pan_enabled():
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        # 焦点在控件上时事件被控件自己吃掉，走不到这里；能到这里的都是
        # 落在画布上的按键，运行态不应改场景。空格例外：它是第二种平移手势。
        if event.key() == Qt.Key_Space and self.is_pan_enabled():
            super().keyPressEvent(event)
            return
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        # 空格一定放行给基类，否则关掉导航前按下的空格会让 _space_held 卡住
        if event.key() == Qt.Key_Space:
            super().keyReleaseEvent(event)
            return
        event.accept()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        event.accept()                              # 不弹设计器右键菜单


class RackGlobalParasWindowV2(QWidget):
    """料仓全局参数面板（CoreQGraphics 版）。

    构造签名与旧窗口一致——``RackGlobalParasWindowV2(plc_mgr, parent)``，
    外部把它塞进布局即可，其余接口只看 :meth:`apply_db41`。
    """

    def __init__(self, plc_mgr, parent=None, *, scene_path: Optional[str] = None,
                 fit_mode: str = "fit") -> None:
        super().__init__(parent)
        if fit_mode not in ("fit", "native"):
            raise ValueError(f"fit_mode 只能是 'fit' / 'native'：{fit_mode!r}")
        self.fit_mode = fit_mode

        # 先建场景再建视图：GraphicsView 构造时会同步网格基准（要 projection）
        self.scene = GraphicsScene()
        self.view = _ReadOnlyView(self.scene, self)
        self.view.on_viewport_resized = self._apply_framing

        self.scene_path = scene_path or res_mng.get_json_path(SCENE_NAME)
        self._load_error = ""
        self._load()

        # 边距跟旧窗口一样用布局默认值（Windows 风格 11px）：旧 QuadTreeScene
        # 就是在 370×878 的可用区里做等比适配的，V2 改成 0 边距会让视口变大，
        # 缩放随之从 1.0897 变成 1.1145，画面整体差几个百分点。
        layout = QVBoxLayout(self)
        layout.addWidget(self.view)
        self.setLayout(layout)

        self.model = RackGlobalParasModelV2(plc_mgr, self.scene, self)
        missing = self.missing_widgets()
        if missing:
            print(f"[RackGlobalParasV2] 控件未挂载：{'、'.join(missing)}")

    # ------------------------------------------------------------------
    # 场景
    # ------------------------------------------------------------------
    def _load(self) -> None:
        """载页面 → 切运行态 → 取景。顺序不能反（见模块 docstring）。"""
        self._clear()
        if not os.path.isfile(self.scene_path):
            self._load_error = f"场景文件不存在：{self.scene_path}"
            print(self._load_error)
            return
        count = self.scene.load_page(self.scene_path)
        if count <= 0:
            self._load_error = f"场景里没有图元：{self.scene_path}"
            print(self._load_error)
        # 运行态：建 proxy 挂真实控件，同时关掉选中 / 拖动
        self.scene.set_scene_mode(True)
        self._apply_framing()

    def _clear(self) -> None:
        """清场景前先退运行态：否则 proxy 里的 QWidget 会被直接 deleteLater。"""
        self.scene.set_scene_mode(False)
        self.scene.clear_page()

    def reload(self) -> bool:
        """重载同一页面（设计器改完不想重启时用）。返回是否绑定到全部控件。"""
        self.model.unbind()
        self._load()
        return self.model.bind()

    def _apply_framing(self) -> None:
        """把页面摆进视口。

        ``fit``（默认）＝等比适配可视区，**允许放大**。这是旧 QuadTreeScene
        的行为：它在 Run 态用 ``scale = min(w/pw, h/ph)`` 填满，392×900 的
        面板里 878/805.7 ≈ 1.0897，页面正好顶到上下边缘。V2 若改成不放大，
        画面会整体小 9%，与旧窗口对不上，故保持一致。

        ``native`` ＝ 1:1 居中，只在页面比视口大时缩小。像素最清晰，但外观
        与旧版不同，供调用方显式选择。
        """
        rect = self.scene.view_scene_rect()
        if rect.isEmpty():
            return
        avail = self.view.viewport().rect()
        if avail.width() < 8 or avail.height() < 8:
            # 还没 show / 布局没跑完：此时视口是默认极小尺寸，算出来的缩放
            # 会离谱（0.05 那种），等视图真正 resize 后回调会再来一次。
            return
        target = self.scene.projection.rect(rect)
        self.view.resetTransform()      # 每次从单位变换重算，避免缩放累积
        if self.fit_mode == "fit" or (
                target.width() > avail.width()
                or target.height() > avail.height()):
            # 手算缩放而不是 fitInView：fitInView 内部会按整数取整，且在
            # 「刚好装下」时给出比 min() 略小的比例，导致同一面板比旧窗口
            # 整体小半个百分点、控件位置差 1~3px。自己算 = 和旧
            # QuadTreeScene 的 ``min(w/pw, h/ph)`` 完全同口径。
            scale = min(avail.width() / target.width(),
                        avail.height() / target.height())
            if scale <= 0 or scale != scale:            # 0 / NaN 保护
                scale = 1.0
            self.view.scale(scale, scale)
        self.view.centerOn(target.center())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_framing()

    # ------------------------------------------------------------------
    # 业务接口（与旧窗口同名）
    # ------------------------------------------------------------------
    def apply_db41(self, db41: bytes) -> None:
        """解析 DB41 数据，更新控件显示。"""
        self.model.apply_db41(db41)

    @property
    def load_error(self) -> str:
        return self._load_error

    def missing_widgets(self) -> list[str]:
        """没拿到真实控件的图元名（正常应为空）。"""
        names = [name for _a, name, _o in CHECKBOX_BINDINGS]
        names += [name for _a, name, _o in SPINBOX_BINDINGS]
        return [n for n in names if self.model.leaf_widget(n) is None]


def _demo() -> int:  # pragma: no cover - 手工预览用
    """单独跑本文件时弹一个假 PLC 的预览窗口。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])
    win = RackGlobalParasWindowV2(None)
    win.setWindowTitle("料仓全局参数（V2 / CoreQGraphics）")
    win.resize(392, 900)
    win.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_demo())
