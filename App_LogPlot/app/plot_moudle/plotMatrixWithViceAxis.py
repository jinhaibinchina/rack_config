"""主副轴合并图容器。

``TabbedPlotWidget`` 右键菜单的「第一行/第二行双图合并」「第一列/第二列
双图合并」会创建本类，把原来两幅图里的曲线塞进同一个窗口：第一组画在
左主轴，第二组画在右副轴（``Axes.twinx()``）。

与 ``PlotMatrix`` 的差别只有两点：

* ``addPlotWidget`` 创建带副轴的 ``MplPlotWidget(ax_vice_en=True)``；
* 响应 ``global_config.axis_visibility_change``，让对话框的「主」「副」
  按钮能真正控制两组曲线的显隐。

其余网格、x 轴同步、清空、拖拽等能力全部沿用 ``PlotMatrix``。
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from .common import rcd_data_bridge
from .global_config import global_config
from .mat_plot import MplPlotWidget
from .polt_matrix import PlotMatrix
from .translater import rcd_translater

if TYPE_CHECKING:
    from .tabbed_plot_widget import TabbedPlotWidget


class PlotMatrixWithVice(PlotMatrix):
    """单窗口 + 右侧副轴的绘图矩阵（右上角「回到初始比例」走 on_Zoom_max）。"""

    def __init__(
        self,
        name: str,
        data_bridge: rcd_data_bridge,
        translater: rcd_translater,
        parent: Optional[TabbedPlotWidget] = None,
    ):
        super().__init__(name, data_bridge, translater, parent)
        # 接收者销毁时 PySide 会自动断开，不会把已删除的窗口留在单例的
        # 连接列表里。
        global_config.axis_visibility_change.connect(self.apply_axis_visibility)

    def addPlotWidget(self, row: int, col: int) -> MplPlotWidget:
        """创建带副轴的绘图窗口（父类创建的是普通单轴窗口）。"""
        plot_name = f"{self._name}_plot_{row}_{col}"
        plot = MplPlotWidget(plot_name, (row, col), self, ax_vice_en=True)
        plot.setMinimumSize(300, 200)
        plot.xlim_changed.connect(self.on_sync_x_update)
        return plot

    def on_Zoom_max(self):
        """回到初始缩放比例，主轴和副轴都要复位。"""
        for row in range(self.rowsCount()):
            for col in range(self.colsCount()):
                plot = self.plotAt(row, col)
                if plot:
                    plot.restore_initial_lim()

    def apply_axis_visibility(self):
        """按全局主/副轴开关刷新本容器内所有绘图窗口。"""
        major = global_config.major_axis_en
        vice = global_config.vice_axis_en
        for row in range(self.rowsCount()):
            for col in range(self.colsCount()):
                plot = self.plotAt(row, col)
                if plot:
                    plot.set_axis_visible(major, vice)
