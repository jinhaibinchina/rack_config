"""Designer.CoreQGraphics —— 用原生 QGraphicsScene 重写的 Core 平行实现。

与 ``Designer.Core`` 读同一份 ``page_*.json``，序列化格式零改动；
不改动、也不 import ``Designer.Core`` 的任何运行时代码（仅图片路径解析
复用项目的 resource_manager，失败时回退到相对路径）。

典型用法::

    from Designer.CoreQGraphics import load_page, GraphicsView

    scene = load_page("Designer/Core/data.json/datas/design/pages/page_1.json")
    view = GraphicsView(scene)
    view.fit_content()
    view.show()

模块对应关系::

    Core/element.py            -> g_element.py   (BaseItem)
    Core/elements.py           -> g_elements.py  (12 类图元)
    Core/my_transform_v2.py    -> g_projection.py(坐标投影)
    Core/myGraphicsScene.py    -> g_scene.py     (场景 + 视图范围)
    Core/myQuadTreeScene.py    -> g_scene.py     (SceneIndex + 序列化)
    Core/mySnapSystem.py       -> g_snap.py
    Core/scene_fast.py         -> g_style.py
    （Core 无对应物）          -> g_view.py      (QGraphicsView 交互)

UI 外壳在子包 ``Designer.CoreQGraphics.ui``：属性面板 / 工具箱 / 图层树 /
设计器主窗口，命令行 ``python -m Designer.CoreQGraphics.ui page_1.json``。
顶层用 ``__getattr__`` 延迟导出，纯场景用户不会被 UI 依赖拖慢导入。

已知边界（见 docs/stage2_geometry_backend_design.md 附录 C）：
* widget 图元只画占位框，不创建 EmbeddedWidgetLayer 真实控件；
* 不含 PLC / 料仓状态绑定与运行态站点说明页。

父对象与旋转支点（口径与 Designer.Core 逐项对齐）：
* 有父对象（``parent_id``）的图元**不能自行平移、但可以自行旋转**：父对象平移 /
  旋转时，后代图元的中心、支点、角度一起走同一个刚体变换（顶点类图元把旋转
  烘焙进 ``vertices``）；子图元自己拖不动——拖它会转成拖根父对象，而
  ``set_page_angle`` / ``rotate_by`` / 面板「旋转」仍然生效（绕自己的支点转，
  后代跟着转，父对象与兄弟不动）。
* **坐标系**：设了父对象后，对外读数与写入口径都是**父坐标系**——原点是父图元
  的可视中心、朝向是父图元的绝对角度。``page_local_center()`` /
  ``page_local_angle()`` / ``page_local_origin()`` 取值，父对象怎么动这组数都不
  变；``set_page_local_angle`` / ``set_page_local_origin`` 按父系写入。属性面板
  的「布局」页因此显示 ``（父坐标系）``，中心 X/Y 只读（不能自行平移）。
  存储与 page JSON 仍是场景绝对坐标（``page_center`` / ``page_angle``），以便
  存量页面零改动、与旧引擎逐项对拍；两套口径靠 ``local_to_world`` /
  ``world_to_local`` 互换。
* 旋转支点 ``origin_pos`` 与可视中心 ``center_pos`` 解耦：``_place()`` 按
  ``q → pos + o + R(q - o)`` 摆位，所以 ``mapToScene(0) == center``、
  支点处不动，改角度即铰链式旋转。画布上右键菜单「旋转中心设到此处」把支点
  钉在点击位置，选中时画蓝色十字圆环 + 中心到支点的虚线；**中心点标识（红点 +
  ID 标签）画在支点处**（``pivot_scene_point()``），默认绕中心转时与几何中心重合。
* **顶点类的旋转是「记账」不是「重建」**：``line / triangle / polygon / path`` 的
  几何是烘焙进 ``vertices`` / ``head_pos`` 的绝对坐标，所以改角度只是先把 Qt
  旋转挂上去（``_apply_pose``），存盘时才 ``bake_rotation()`` 折进顶点。烘焙
  必须原样带上中心与支点（``set_page_vertices(center=…, pivot=…)``）——
  三角形不是中心对称图形，绕中心转一次后**包围盒中心本来就换了个点**，若按
  新包围盒重新定位，支点会跟着跳一大截。真实朝向记在 ``_baked_angle``（落盘即
  ``rotate`` 字段，旧 Core 读法是「先反旋再正旋」，等价恒等，不会二次旋转），
  所以面板「旋转」读回的是绝对值，连续设 30→60 就是 60，不是叠加成 90。

背景网格与鼠标吸附（对照 ``Core/myGraphicsScene.draw_grid`` 与
``Core/mySnapSystem``）：
* 网格画在场景坐标里，基准 ``50`` 视图单位（= 页面 200 单位），以
  ``projection.point(0, 0)`` 为锚点；步长随视图缩放按 2 的幂细分 / 合并，
  保证屏幕格宽落在 18~90 px，**画出来的格子就是能吸的格子**（``grid_step``
  由 ``SnapSystem.adapt_grid_to_scale`` 统一维护）。菜单「显示网格」
  （Ctrl+Shift+N）默认开启。
* 吸附点三类：端点 / 中点（``scene.snap_points()`` 收集）与**网格交汇点**。
  网格不预先枚举——最近格点由 ``nearest_grid()`` 直接算（同 Core 的
  ``get_nearest_grid_point``），图元点优先、网格仅在更近时顶替（同
  ``snap_to_point`` 的顺序）。端点/中点存空间哈希，鼠标移动只扫附近格子。
* 光标附近（阈值 1.6 倍内）的候选点始终画成橙色细十字，当前会命中的那个
  加粗并套圆环；阈值按屏幕像素（``pixel_threshold = 12px``）换算成场景单位，
  缩放后手感一致。``T`` 键只是**开关吸附**，不影响标记显示。
* 吸附位移以**鼠标位置**为基准：``_apply_snap_follow()`` 算出
  ``目标点 - 光标点`` 的偏移，原样叠加到选中的无父图元上——鼠标吸了多少，
  图元就移动多少，多选整体平移保持相对位置。按 T 立即吸一次；拖动松手时再补
  一次（拖动过程中不补：Qt 对可拖图元用「按下点 + 鼠标位移」的绝对定位，会
  覆盖掉中途的叠加）。``_snap_offset`` 记录已叠加量，重复按 T 或原地不动都
  不会重复推图元。
"""

from .g_element import BaseItem
from .g_elements import ITEM_TYPES
from .g_projection import SceneProjection
from .g_scene import GraphicsScene, SceneIndex
from .g_snap import SnapSystem
from .g_style import Style
from .g_view import GraphicsView


def load_page(path: str, projection: SceneProjection | None = None) -> GraphicsScene:
    """读取一份 page JSON，返回已装载的 QGraphicsScene。"""
    scene = GraphicsScene(projection)
    scene.load_page(path)
    return scene


__all__ = [
    "BaseItem", "ITEM_TYPES", "SceneProjection", "GraphicsScene", "SceneIndex",
    "SnapSystem", "Style", "GraphicsView", "load_page",
    "DesignerWindow", "PropertyPanel", "ElementToolboxDock", "LayerTreeDock",
    "PageHistory", "open_designer",
]

_UI_EXPORTS = {
    "DesignerWindow", "PropertyPanel", "ElementToolboxDock", "LayerTreeDock",
    "PageHistory", "open_designer",
}


def __getattr__(name: str):
    """UI 类按需导入：纯场景用法不必拉起 Qt Widgets 面板模块。"""
    if name in _UI_EXPORTS:
        from . import ui
        return getattr(ui, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
