"""widget_element 复制/粘贴几何保真回归。

问题：改过尺寸和旋转中心的控件图元，粘贴出来的副本会被"控件自适应"打回
``sizeHint`` 尺寸，旋转中心也被重置为 (0,0)。

根因在 ``_auto_fit_size()``：只读态下无条件用控件 sizeHint 覆盖
``setSize`` + 四角 + ``_center_pos``，而粘贴流程
``set_widget_visible(True)`` → ``_ensure_layer`` → ``_rebuild_widget``
必然触发它。

用法：.venv/Scripts/python.exe tools/verify_widget_clone_geometry.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import QObject, QPointF, Signal
from PySide6.QtWidgets import QApplication, QLineEdit

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


class StubScene(QObject):
    """只提供 widget_element 需要用到的场景接口。"""

    shine_flag_change = Signal()
    item_DirtyChange = Signal(object)
    item_GeometryChange = Signal(object)

    scene_units_per_grid_x = 10.0
    scene_units_per_grid_y = 10.0
    grid_size = 10.0
    scale_factor = 1.0

    def pos_viewToWindow(self, p):
        return p

    def sceneToView(self, p):
        return p

    def viewToScene(self, p):
        return p

    def __getattr__(self, name):
        # 其余场景接口（update / invalidate / 各种通知）一律 no-op
        return lambda *args, **kwargs: None


class StubView:
    def viewport(self):
        return None


class StubLayer:
    """替代 EmbeddedWidgetLayer：只需要 widget / 状态 / 无副作用的同步。"""

    def __init__(self, widget):
        self.widget = widget
        self.view = StubView()

    def set_widget(self, widget):
        self.widget = widget

    def __getattr__(self, name):
        # 其余承载层接口（set_interactive / raise_view / ...）一律 no-op
        return lambda *args, **kwargs: None

    def is_active(self):
        return True

    def dispose(self):
        pass

    def apply(self, *args):
        pass

    def set_visible(self, visible):
        pass

    def is_visible(self):
        return True


def make_widget_element(scene, layer_widget=None):
    from Designer.Core.elements import widget_element

    item = widget_element()
    item.set_scene_ref(scene)
    item.m_pos = QPointF(0.0, 0.0)
    for attr in ("_head_pos", "_end_pos", "_topLeft", "_topRight",
                 "_bottomLeft", "_bottomRight", "_center_pos"):
        if getattr(item, attr, None) is None:
            setattr(item, attr, QPointF(0.0, 0.0))
    if layer_widget is not None:
        item._layer = StubLayer(layer_widget)
    return item


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    scene = StubScene()

    # ---- 1. 用户改动尺寸 + 旋转中心 ----
    src = make_widget_element(scene, QLineEdit())
    src._widget_readonly = True
    src.setSize(320.0, 210.0)
    src.set_center_pos(QPointF(12.0, -8.0))
    check("源图元尺寸已设置", (src.getSize().width(), src.getSize().height()) == (320.0, 210.0),
          f"{src.getSize().width()}x{src.getSize().height()}")
    check("源图元旋转中心已设置", src.get_center_pos() == QPointF(12.0, -8.0),
          str(src.get_center_pos()))

    # ---- 2. 克隆本身要带上这些字段 ----
    cloned = src.clone()
    check("克隆体尺寸一致",
          (cloned.getSize().width(), cloned.getSize().height()) == (320.0, 210.0),
          f"{cloned.getSize().width()}x{cloned.getSize().height()}")
    check("克隆体旋转中心一致", cloned.get_center_pos() == QPointF(12.0, -8.0),
          str(cloned.get_center_pos()))

    # ---- 3. 粘贴后的挂载流程：控件自适应必须尊重用户设定 ----
    cloned.set_scene_ref(scene)
    cloned._layer = StubLayer(QLineEdit())
    cloned._widget_readonly = True
    cloned._auto_fit_size()
    check("挂载后尺寸没有被 sizeHint 打回",
          (cloned.getSize().width(), cloned.getSize().height()) == (320.0, 210.0),
          f"{cloned.getSize().width()}x{cloned.getSize().height()}")
    check("挂载后旋转中心没有被重置", cloned.get_center_pos() == QPointF(12.0, -8.0),
          str(cloned.get_center_pos()))

    # ---- 4. 新建图元仍然要能自动贴合控件自然尺寸 ----
    fresh = make_widget_element(scene)
    fresh._layer = StubLayer(QLineEdit())
    fresh._widget_readonly = True
    fresh._auto_fit_size()
    hint_fitted = (fresh.getSize().width() > 0.0 and fresh.getSize().height() > 0.0)
    check("新建图元仍会自动贴合 sizeHint", hint_fitted,
          f"{fresh.getSize().width()}x{fresh.getSize().height()}")

    # ---- 5. 切换控件类型也不该冲掉用户已经定好的尺寸 ----
    src.set_widget_type("pushbutton")
    src._auto_fit_size()
    check("切换控件类型后保留用户尺寸",
          (src.getSize().width(), src.getSize().height()) == (320.0, 210.0),
          f"{src.getSize().width()}x{src.getSize().height()}")

    # ---- 6. 显式强制时才重新贴合 ----
    src._auto_fit_size(force=True)
    check("force=True 可以重新贴合",
          (src.getSize().width(), src.getSize().height()) != (320.0, 210.0),
          f"{src.getSize().width()}x{src.getSize().height()}")

    # ---- 7. 真实场景：走完整的 copy_selected / paste ----
    from Designer.Core.myQuadTreeScene import QuadTreeScene, SceneManager
    from Designer.Core.elements import widget_element

    real = QuadTreeScene()
    manager = SceneManager(real)
    real.scene_manager = manager

    original = widget_element()
    original.set_scene_ref(real)
    original.set_scene_manager_ref(manager)
    original.setSize(320.0, 210.0)
    original.set_center_pos(QPointF(12.0, -8.0))
    original.setPos(QPointF(500.0, 500.0))
    manager.addItem(original, False)
    original.set_selected(True)

    real.copy_selected()
    real.paste()
    pasted = [item for item in manager.m_sorted_items if item is not original]
    check("真实粘贴产出一个副本", len(pasted) == 1, f"count={len(pasted)}")
    if pasted:
        copy_item = pasted[0]
        check("真实粘贴保留尺寸",
              (copy_item.getSize().width(), copy_item.getSize().height()) == (320.0, 210.0),
              f"{copy_item.getSize().width()}x{copy_item.getSize().height()}")
        check("真实粘贴保留旋转中心",
              copy_item.get_center_pos() == QPointF(12.0, -8.0),
              str(copy_item.get_center_pos()))
        # 承载层确实被创建了，说明 _rebuild_widget → _auto_fit_size 真的跑过，
        # 尺寸没被打回是判断条件生效、而不是没走到。
        check("粘贴后承载层已创建", copy_item.has_widget_layer())

    return _report()


def _report() -> int:
    failed = 0
    for name, ok, detail in results:
        if not ok:
            failed += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
