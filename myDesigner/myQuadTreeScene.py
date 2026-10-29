
from threading import Lock
from PySide6.QtCore import QRectF, QPointF

from .my_common import SceneMode
from .myGraphicsScene import myGraphicsScene, DEFAULT_BACKGROUND_COLOR, debug_log

from PySide6.QtWidgets import QMainWindow, QApplication

from PySide6.QtWidgets import QMenu,QDialog,QSizePolicy
from PySide6.QtWidgets import ( QToolTip)
from PySide6.QtCore import Qt, QPointF, QRectF,Signal,QSize,QObject,QRect,QPoint,QTimer,QSizeF
from PySide6.QtGui import QPainter, QPen, QColor,QFont , QPixmap,QRegion, QUndoCommand,QUndoStack

import json,sys,os,traceback
from .elements import (
    base_element,
    circle_element,
    group_element,
    image_element,
    line_element,
    rect_element,
    text_element,
    triangle_element,
)
# from my_elements_v2 import rect_element,line_element,circle_element ,base_element,group_element,text_element,image_element,triangle_element
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtCore import QRegularExpression


from .mySnapSystem import SnapSystem
import copy



class QuadtreeNode:
    def __init__(self, boundary: QRectF, capacity=4):
        self.boundary = boundary  # 节点边界（矩形区域）
        
        self.capacity = capacity  # 节点最大容量
        self.items = []           # 存储的图形项
        self.divided = False      # 是否已分裂
        # 四个子节点
        self.nw = None  # 西北
        self.ne = None  # 东北
        self.sw = None  # 西南
        self.se = None  # 东南


        self.scene_ref=None

    def set_scene_ref(self,scene):
        self.scene_ref=scene

    def subdivide(self):
        """ 分裂当前节点为4个子节点 """
        x, y = self.boundary.x(), self.boundary.y()
        w, h = self.boundary.width() / 2, self.boundary.height() / 2

        # 创建四个子区域
        nw_rect = QRectF(x, y, w, h)
        ne_rect = QRectF(x + w, y, w, h)
        sw_rect = QRectF(x, y + h, w, h)
        se_rect = QRectF(x + w, y + h, w, h)

        self.nw = QuadtreeNode(nw_rect, self.capacity)
        self.ne = QuadtreeNode(ne_rect, self.capacity)
        self.sw = QuadtreeNode(sw_rect, self.capacity)
        self.se = QuadtreeNode(se_rect, self.capacity)
        self.divided = True

    # def insert(self, item: base_element) -> bool:
    #     """ 插入图形项 """
    #     # 检查是否在边界内
    #     if not self.boundary.intersects(item.sceneBoundingRect()):
    #         return False

    #     # 如果未超容量或未分裂，直接存储
    #     if len(self.items) < self.capacity and not self.divided:
    #         self.items.append(item)
           
    #         return True
    #     elif len(self.items) < self.capacity and  self.divided:
    #         self.items.append(item)

    #     # 如果未分裂，先分裂
    #     if not self.divided:
    #         self.subdivide()

    #     # 尝试插入到子节点
    #     return (self.nw.insert(item) or self.ne.insert(item) or
    #             self.sw.insert(item) or self.se.insert(item))

    def insert(self, item: base_element) -> bool:
        # 检查是否与节点边界相交
        if not self.boundary.intersects(item.sceneBoundingRect()):
            
                
            return False

        # 未分裂时直接存储相交项
        if not self.divided:
            self.items.append(item)
            # 超容量时分裂，但不迁移父节点数据
            if len(self.items) > self.capacity:
                self.subdivide()
            return True

        # 已分裂时，尝试插入到子节点
        inserted = False
        if self.nw.insert(item): inserted = True
        if self.ne.insert(item): inserted = True
        if self.sw.insert(item): inserted = True
        if self.se.insert(item): inserted = True

        # 若子节点无法完全容纳，保留在父节点
        if not inserted:
            self.items.append(item)
        return True

    
    def query(self, area: QRectF, found_items: set):  # 使用集合而非列表
        if not self.boundary.intersects(area):
            return

        for item in self.items:
            if area.intersects(item.sceneBoundingRect()):
                found_items.add(item)  # 集合自动去重

        if self.divided:
            self.nw.query(area, found_items)
            self.ne.query(area, found_items)
            self.sw.query(area, found_items)
            self.se.query(area, found_items)
    # def remove(self, item: base_element) -> bool:
    #     """ 从节点中删除图形项 """
    #     removed = False
        
    #     # 从当前节点删除
    #     if item in self.items:
    #         self.items.remove(item)
            
    #         removed = True
            
    #     # 从子节点递归删除
    #     if self.divided:
    #         if self.nw.remove(item): removed = True
    #         if self.ne.remove(item): removed = True
    #         if self.sw.remove(item): removed = True
    #         if self.se.remove(item): removed = True
        
    #     return removed
    def remove_all(self):
        removed = False
        
        # 从当前节点删除
        for item in self.items:
            self.items.remove(item)
            removed = True
            
        # 从子节点递归删除
        if self.divided:
            if self.nw.remove_all(): removed = True
            if self.ne.remove_all(): removed = True
            if self.sw.remove_all(): removed = True
            if self.se.remove_all(): removed = True
            
            # 检查所有子节点是否为空
            if (len(self.nw.items) == 0 and not self.nw.divided and
                len(self.ne.items) == 0 and not self.ne.divided and
                len(self.sw.items) == 0 and not self.sw.divided and
                len(self.se.items) == 0 and not self.se.divided):
                # 重置子节点和分裂状态
                self.nw = self.ne = self.sw = self.se = None
                self.divided = False
        
        return removed

    def remove(self, item: base_element) -> bool:
        removed = False
        
        # 从当前节点删除
        if item in self.items:
            self.items.remove(item)
            removed = True
            
        # 从子节点递归删除
        if self.divided:
            if self.nw.remove(item): removed = True
            if self.ne.remove(item): removed = True
            if self.sw.remove(item): removed = True
            if self.se.remove(item): removed = True
            
            # 检查所有子节点是否为空
            if (len(self.nw.items) == 0 and not self.nw.divided and
                len(self.ne.items) == 0 and not self.ne.divided and
                len(self.sw.items) == 0 and not self.sw.divided and
                len(self.se.items) == 0 and not self.se.divided):
                # 重置子节点和分裂状态
                self.nw = self.ne = self.sw = self.se = None
                self.divided = False
        
        return removed
    def visualize(self, painter: QPainter, max_depth=None, current_depth=0):
        """
        递归绘制四叉树结构
        :param painter: QPainter绘图对象
        :param max_depth: 最大绘制深度
        :param current_depth: 当前节点深度
        """
        # 深度限制检查
        if max_depth is not None and current_depth > max_depth:
            return
        # print("可视化")
        if self.scene_ref is None:
            return
        sceneToView = self.scene_ref.sceneToView
        pen = QPen(Qt.blue)
        pen.setWidth(1)
        font = QFont("Arial", 50, QFont.Bold)
        painter.setFont(font)
        painter.setPen(pen)

        # r=   QRect(  sceneToView(self.boundary.topLeft()) ,sceneToView(self.boundary.bottomRight()))
        # painter.drawRect(r)
        
        # 标记节点深度和元素数量
        info = f"D:{current_depth} N:{len(self.items)}"
        if self.scene_ref:
            p = sceneToView(self.boundary.center() )
           
            painter.drawText(p+ QPointF(5, 15), info)

        # 绘制子节点连接线（若有子节点）
        if self.divided:
            center = sceneToView(self.boundary.center())
            for child in [self.nw, self.ne, self.sw, self.se]:
                child_center = sceneToView(child.boundary.center())
                painter.drawLine(center, child_center)
                
                # 递归绘制子节点
                child.visualize(painter, max_depth, current_depth+1)

class SceneSerializer:
    @staticmethod
    def _resource_dirs():
        """按优先级返回查找场景文件的候选目录。

        打包后 exe 的资源可能落在不同位置，取决于 ``--add-data`` 的目标路径：
        直接放在解包根目录、放在 ``myDesigner/`` 子目录，或者被现场替换到
        exe 同目录。单看 ``sys._MEIPASS`` 一处会漏，所以这里全部列出来逐个试。
        """
        module_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = []

        if getattr(sys, 'frozen', False):
            # 1) exe 同目录：允许现场直接替换 data2.json，不必重新打包
            candidates.append(os.path.dirname(os.path.abspath(sys.executable)))
            meipass = getattr(sys, '_MEIPASS', None)
            if meipass:
                # 2) --add-data 目标为根目录
                candidates.append(meipass)
                # 3) --add-data 目标为 myDesigner（打包工具按源相对路径放置）
                candidates.append(os.path.join(meipass, 'myDesigner'))
        else:
            # 源码运行：data2.json 就在 myDesigner 包里
            candidates.append(module_dir)
            candidates.append(os.path.dirname(module_dir))

        # 4) 兜底：当前工作目录
        try:
            candidates.append(os.getcwd())
        except OSError:
            pass

        # 去重且保持顺序
        seen, ordered = set(), []
        for path in candidates:
            if not path:
                continue
            key = os.path.normcase(os.path.abspath(path))
            if key in seen:
                continue
            seen.add(key)
            ordered.append(path)
        return ordered

    @staticmethod
    def get_json_path(relative_path=""):
        """获取json文件路径

        Args:
            relative_path: 相对于资源根目录的子路径，如"config/data.json"。
                为空时默认 "data.json"。

        查找顺序见 :meth:`_resource_dirs`：取第一个真实存在的文件。
        都不存在时返回第一候选（调用方按"空场景"处理，保存时也不会写到
        临时解包目录里白白丢失）。
        """
        name = relative_path or "data.json"
        if os.path.isabs(name):
            return name

        dirs = SceneSerializer._resource_dirs()
        for base_dir in dirs:
            candidate = os.path.join(base_dir, name)
            if os.path.isfile(candidate):
                return candidate
        return os.path.join(dirs[0], name)
    


    # def get_json_path():
    #     if getattr(sys, 'frozen', False):
    #         # 打包后的可执行文件路径（如 PyInstaller）
    #         app_dir = os.path.dirname(sys.executable)
    #     else:
    #         # 脚本文件所在路径
    #         app_dir = os.path.dirname(os.path.abspath(__file__))

    #     return os.path.join(app_dir, "data.json")


    @staticmethod
    def item_to_dict(item):
        """Serialize one element including its design-time event bindings."""

        data = item.to_dict()
        events = item.event_bindings_to_dict()
        if events:
            data["events"] = events
        return data

    @staticmethod
    def serialize_scene(scene: myGraphicsScene, filename: str):
        """将场景序列化为JSON文件"""
        # ``sceneRect`` stores the scene-coordinate rectangle that is currently
        # visible.  Run mode can then reopen the page at the same view range.
        # Empty/uninitialised scenes keep the all-zero placeholder.
        view_rect = scene.get_view_scene_rect()
        # Keep the in-memory record in sync with the file: "调整视图" must
        # restore the range that ends up in ``sceneRect`` below, even after the
        # user saved a new view range in this session.
        if view_rect.width() > 0 and view_rect.height() > 0:
            scene.set_saved_view_scene_rect(view_rect)
        background_color = scene.get_bg_color()
        if not isinstance(background_color, QColor) or not background_color.isValid():
            background_color = QColor(DEFAULT_BACKGROUND_COLOR)
        scene_data = {
            "sceneRect": {
                "x": view_rect.x(),
                "y": view_rect.y(),
                "width": view_rect.width(),
                "height": view_rect.height()
            },
            # Page background colour, written as ``#aarrggbb``.
            "backgroundColor": background_color.name(QColor.HexArgb),
            "items": []
        }
        for item in scene.findChildren(base_element):

            # item_data = {}

            # 处理不同类型的图元
            if isinstance(item, base_element) :
                scene_data["items"].append(SceneSerializer.item_to_dict(item)) 
            # elif isinstance(item, group_element):
            #     scene_data["items"].append(item.to_dict()) 
            # 可以继续添加其他图元类型的处理...

        
        # with open(filename, 'w') as f:
        #     json.dump(scene_data, f, indent=4)


   
        json_path=SceneSerializer.get_json_path(filename)
        # 写入 JSON 文件
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(scene_data, f, ensure_ascii=False, indent=4)  # 格式化输出

        print(f"JSON 文件已保存至: {json_path}")

    @staticmethod
    def deserialize_scene(scene: myGraphicsScene, filename: str):
        """从JSON文件反序列化场景"""
        def restore_relationship(id_item_map):
            # print(id_item_map)
            for  id,item in  id_item_map.items():
                if item.m_parent_id>0 and item.m_parent is None:
                    item.setParentItem(id_item_map[item.m_parent_id])
                    # if isinstance(id_item_map[item.m_parent_id],group_element):
                    #     item.set_group_id(item.m_parent_id)


        json_path=SceneSerializer.get_json_path(filename)
        if not os.path.isfile(json_path):
            # A brand-new design page has no file yet; treat it as empty
            # instead of aborting the application startup.
            print(f"场景文件不存在，按空场景处理: {json_path}")
            return
        with open(json_path, "r", encoding="utf-8") as f:
            scene_data = json.load(f)  # 解析为 Python 字典或列表
        
        # for item in scene.findChildren(base_element):
        #     item.deleteLater()
        #     scene.quadtree.remove(item)
        #     scene.scene_manager.m_items.clear()
        #     scene.update()



        # The serialized sceneRect is the design/run view range, not the
        # quadtree's world bounds, so it must not be passed to setSceneRect().
        view_rect = None
        rect_data = scene_data.get("sceneRect") or {}
        try:
            candidate = QRectF(
                float(rect_data.get("x", 0.0)),
                float(rect_data.get("y", 0.0)),
                float(rect_data.get("width", 0.0)),
                float(rect_data.get("height", 0.0)),
            )
        except (TypeError, ValueError):
            candidate = None
        if (
            candidate is not None
            and candidate.width() > 0
            and candidate.height() > 0
        ):
            view_rect = candidate

        # Page background colour; older files simply keep the scene default.
        color_data = scene_data.get("backgroundColor")
        if isinstance(color_data, str) and color_data.strip():
            background_color = QColor(color_data.strip())
            if background_color.isValid():
                scene.set_bg_color(background_color)

        max_id =0
        # 反序列化图元
        for item_data in scene_data["items"]:
            item = None

            if  item_data["type"] == "line":
                item = line_element.from_dict(item_data)
            elif item_data["type"] == "rect":
                item = rect_element.from_dict(item_data)
                # print(f"rect{item._topLeft}")
                # print(f"rect{item.get_scene_topLeft()}")
            elif item_data["type"] == "triangle":
                item = triangle_element.from_dict(item_data)
            elif item_data["type"] == "circle":
                item = circle_element.from_dict(item_data)
            elif item_data["type"] == "text":
                item = text_element.from_dict(item_data)

            elif item_data["type"] == "image":
                item = image_element.from_dict(item_data)
               
            elif item_data["type"] == "group":
                item = group_element.from_dict(item_data)
       

            if item:
                item.set_scene_ref(scene)
                item.set_scene_manager_ref(scene.scene_manager)
                id =item.id()
                item.completed(True)
                item.apply_event_bindings(
                    item_data.get("events") or item_data.get("event_bindings")
                )
                if id>max_id:
                    max_id = id

        scene.scene_manager.m_idGenerator.updateAfterLoad(max_id)
        restore_relationship(scene.scene_manager.m_items)

        if view_rect is not None:
            # Applied immediately for an already-visible scene, otherwise
            # deferred until showEvent() gives the widget its final size.
            scene.set_view_scene_rect(view_rect)


        debug_log(scene.scene_manager.m_name_items)
        # for  id,item in      scene.scene_manager.m_items:
        #     if item.m_parent_id>0:
    


class QuadTreeScene(myGraphicsScene):
    action_begin_draw_line   =Signal()
    action_begin_draw_rect   =Signal()
    action_begin_draw_triangle =Signal()
    action_begin_draw_circle =Signal()
    action_begin_new_rect    =Signal(dict)
    action_begin_new_text    =Signal()
    action_begin_new_image   =Signal()
    action_set_parent        =Signal()
    action_set_group         =Signal(list)# 图元编辑成组
    scene_updated            =Signal()
    quadtree_updated         =Signal()

    
    item_GeometryChange      =Signal(base_element)
    item_DirtyChange         =Signal(base_element)

    hover_sta_change = Signal(base_element)

    run_mode_station_change = Signal(SceneMode)#切换子站点显示

    # (variable_name, value, source_element, event_name)
    variable_written = Signal(str, object, object, str)

    double_clicked_without_group = Signal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        
        self.setMinimumSize(300,300)
        # self.setWindowFlags(Qt.FramelessWindowHint)
        # self.setAttribute(Qt.WA_TranslucentBackground)
        self.setSizePolicy(
            QSizePolicy.Expanding,  # 水平策略：可扩展
            QSizePolicy.Expanding   # 垂直策略：可扩展
            )
        self.setFocusPolicy(Qt.StrongFocus)  # 允许接收事件

        self.quadtree = None
        self.boundingRect_old = {}
        self.dirtyBoundingRect_old = {}
        # self.dirtyRegion = QRegion()#脏区域集
        
        
        self.setSceneRect(QRectF(QPointF(-100000.0,-100000.0),QPointF(100000.0,100000.0)))
        # Design-mode pages are also created without a MainWindow that owns a
        # status bar, so do not rely on that attribute being present.
        self.statusBar = getattr(parent, "status_bar", None)
        # Optional per-scene file used by the built-in context-menu save/load
        # actions.  None keeps the legacy datas/data.json behaviour.
        self.scene_file_path = None

        # Runtime variables written by group event bindings.  A run-mode host
        # may additionally install ``variable_writer`` to forward them to PLC.
        self.runtime_variables = {}
        self.variable_writer = None
        # Run-mode hosts install a callable here; element event bindings then
        # resolve ``{"handler": "name", "args": {...}}`` through it.
        self.event_handler_resolver = None
        self._event_pressed_group = None

        self.copied_items = []  # 存储复制的图元
        self.all_copied_items = []  # 存储复制的图元
        self.paste_offset = QPointF(100, 100)  # 粘贴偏移量
        self.paste_count = 0     # 粘贴计数器

        self.snapSys = SnapSystem(self,self.scene_units_per_grid_x/self.grid_size*self.scale_factor*10,self.map_scene_to_screen)
        self.snapSys.move_item_to_snap_pos.connect(self.move_item_to_snap_pos)
        self.mouse_not_move_signal.connect(lambda:self.snapSys.move_cursor_to_snaped_pos_V2(self.snapSys.current_snap_pos,not self.menu_opened and self.cursor_inside_flag and self.is_show_grid() and self.snap_auto_enabled()))

        self.set_snap_sys_ref(self.snapSys)


        self.item_GeometryChange.connect(self.prepareItemGeometryChange)
        self.item_DirtyChange.connect(self.prepareItemDirtyChange)
        self.scene_updated.connect(self.handle_scene_update)
        self.quadtree_updated.connect(self.handle_quadtree_update)
        self.hover_sta_change.connect(self.handle_hover_sta_change)

        self.menu_opened =False
        self.update_callback         = None
        self.__load_done = False

        # 提高渲染频率，减少拖影

        self.render_timer.timeout.connect(self.on_render_frame)
        # # 确保拖动时也能及时更新
        # self.setRenderHint(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.frame_count =0
        # 使用高精度定时器
        self.frame_count_timer = QTimer()
        self.frame_count_timer.setTimerType(Qt.PreciseTimer)  # 高精度模式
        self.frame_count_timer.timeout.connect(self.handle_frame_count)
        self.frame_count_timer.start(1000)

        self.set_scene_mode(SceneMode.Run)

    def snap_auto_enabled(self) -> bool:
        """鼠标停止移动时是否自动吸附到捕捉点。

        运行模式保持自动吸附；设计模式（DesignScene）覆盖为 False，
        只按快捷键 T 手动吸附。
        """
        return True

    def loadDone(self):
        return self.__load_done
    
    def mode(self)->SceneMode:
        return self._mode
    def set_scene_mode(self,mode:SceneMode):
        if mode == SceneMode.Run:
            self.show_grid(False)
            self.show_coordinate(False)
        else:
            self.show_grid(True)
            self.show_coordinate(True)
        self._mode =mode
        if mode != SceneMode.Run:
            if self._event_pressed_group is not None:
                self._event_pressed_group.cancel_mouse_press()
            self._event_pressed_group = None
        self.run_mode_station_change.emit(mode)

    # ------------------------------------------------------------------
    # Group event bindings (run mode)
    # ------------------------------------------------------------------
    def write_variable(self, name, value, source=None, event=""):
        """Write one runtime variable triggered by an element event.

        The value is stored in ``runtime_variables`` and announced through
        ``variable_written``.  A host can additionally assign
        ``scene.variable_writer = callable(name, value)`` to forward it to a
        PLC/Modbus layer.
        """
        name = str(name or "").strip()
        if not name:
            return False

        self.runtime_variables[name] = value
        self.variable_written.emit(name, value, source, event)

        writer = self.variable_writer
        if callable(writer):
            try:
                writer(name, value)
            except Exception as exc:
                # A broken PLC writer must not break the scene interaction.
                print(f"写入变量失败({name}={value!r}): {exc}")
        return True

    def read_variable(self, name, default=None):
        return self.runtime_variables.get(name, default)

    def clear_runtime_variables(self):
        self.runtime_variables.clear()

    def set_event_handler_resolver(self, resolver):
        """Install the run-mode ``handler_name -> bool`` dispatcher."""

        self.event_handler_resolver = resolver if callable(resolver) else None

    def invoke_event_handler(self, name, source, event, args=None, event_value=None):
        """Resolve one design-time event handler; returns ``True`` if handled."""

        resolver = self.event_handler_resolver
        if not callable(resolver):
            print(f"[运行态事件] 未安装事件处理函数解析器: {name}")
            return False
        try:
            return bool(resolver(name, source, event, args or {}, event_value))
        except Exception as exc:  # noqa: BLE001 - never break mouse interaction
            traceback.print_exc()
            print(f"[运行态事件] 处理函数 {name} 执行失败: {type(exc).__name__}: {exc}")
            return False

    def initialize_event_handlers(self):
        """Run every serialized ``attach`` binding once after page load.

        ``attach`` is not a mouse event: it lets a handler establish the
        initial visual state (for example hide the alarm image of a safety
        door) without duplicating that logic in a click handler.
        """

        manager = getattr(self, "scene_manager", None)
        if manager is None:
            return 0
        invoked = 0
        for item in list(manager.m_items.values()):
            if item is None:
                continue
            try:
                binding = item.get_event_binding("attach")
            except (AttributeError, RuntimeError):
                continue
            if not binding:
                continue
            handler = str(binding.get("handler", "")).strip()
            if not handler:
                continue
            if self.invoke_event_handler(
                handler, item, "attach", binding.get("args") or {}, None
            ):
                invoked += 1
        return invoked

    def _event_scene_pos(self, event):
        """Convert a widget-space mouse event to this scene's custom coords."""
        scale = self.scale_factor if self.scale_factor else 1.0
        view_pos = QPointF(
            event.position().x() / scale + self.view_x0,
            event.position().y() / scale + self.view_y0,
        )
        return self.viewToScene(view_pos)

    def _find_event_group_at(self, scene_pos):
        """Topmost interactive group under ``scene_pos``."""
        manager = getattr(self, "scene_manager", None)
        if manager is None or scene_pos is None:
            return None

        for item in reversed(getattr(manager, "m_sorted_items", [])):
            if not isinstance(item, group_element):
                continue
            if not item.get_visibility():
                continue
            if not (
                item.has_event_bindings()
                or item.is_toggle_enabled()
                or item.is_interactive()
            ):
                continue
            rect = item.sceneBoundingRect()
            if isinstance(rect, QRectF) and rect.contains(scene_pos):
                return item
        return None

    def toggle_sence_mode(self):
        if self._mode==SceneMode.Design:
            for item in self.findChildren(base_element):
                item.set_selectable(False)
            self.set_scene_mode(SceneMode.Run)
        else:
            for item in self.findChildren(base_element):
                item.set_selectable(True)
                item.set_visibility(True)
            self.set_scene_mode(SceneMode.Design)

    def handle_frame_count(self):
        # print(f"当前帧率{self.frame_count}fps")
        self.frame_count= 0

    def prepareItemGeometryChange(self,item:base_element):
        self.boundingRect_old[item] = item.sceneBoundingRect()
    
    def prepareItemDirtyChange(self,item:base_element):
        w_factor,h_factor =  self.screenToScene_factor()
        rect = item.sceneBoundingRect()
        dirty_rect = QRectF(rect.left()-10*w_factor,rect.top()-10*h_factor,rect.width()+20*w_factor,rect.height()+20*h_factor)
        self.dirtyBoundingRect_old[item] = dirty_rect
    
    def handle_hover_sta_change(self,item:base_element):
        state = item.get_hover()
        if isinstance(item,group_element):
            for i in item.m_children:
                if i.is_in_group() and i.get_group_id()==item.id():
                    i.set_group_in_hover(state)
        else:
            item.m_parent.set_group_in_hover(state)
            for i in item.m_parent.m_children:
                if i.is_in_group() and i.get_group_id()==item.m_parent.id():
                    i.set_group_in_hover(state)
        # for id,Item in self.scene_manager.self.m_items.items:
        #     if 
            
   
    def processOverlappingAreas(self,oldRect:QRectF,newRect:QRectF):
        """重叠区域处理"""
        changedRegion = QRegion()
        # 合并新旧区域确保完全覆盖变化区域
        if not oldRect.isEmpty():
            changedRegion += QRegion(oldRect.toRect())
        if not newRect.isEmpty():
            changedRegion += QRegion(newRect.toRect())
        return changedRegion     


    def handle_quadtree_update(self):
        if len(self.boundingRect_old):
     
            for item,rect in self.boundingRect_old.items():
                # self.dirtyRegion_manager.markDirty(self.processOverlappingAreas( self.rect_viewToWindow( self.rect_sceneToView(rect)) ,item.windowBoundingRect()))
                self.scene_manager.m_scene.quadtree.remove(item)
                self.scene_manager.m_scene.quadtree.insert(item)
            self.boundingRect_old.clear()

    def handle_scene_update(self):
        
        if len(self.dirtyBoundingRect_old):

            for item,rect in self.dirtyBoundingRect_old.items():
                self.dirtyRegion_manager.markDirty(self.processOverlappingAreas( self.rect_viewToWindow( self.rect_sceneToView(rect)) ,item.windowBoundingRect()))
            self.dirtyBoundingRect_old.clear()  
            
    def on_render_frame(self):
        self._ready_for_update = False

        if self.update_callback and callable(self.update_callback):
            if self._mode==SceneMode.Run:
                self.update_callback()
            
        if self.needs_redraw:
            self.needs_redraw = False
        self.frame_count+=1
        # for child in  self.findChildren(base_element):
        #     child.check_hover(self.sence_pos_mouse)
          
        self.quadtree_updated.emit()
        # 只在鼠标静止时更新and self.isActiveWindow()
        if not self.CTRL_pressed_flag and (self.mouse_moving_flag  or self.mouse_wheeling_flag) :
            return
        
        # 触发场景更新信号
        self.scene_updated.emit()
        
        # 所有屏幕内脏区域
        dirty_region = self.dirtyRegion_manager.region().intersected(self.rect())

        self.dirtyRegion_manager.set(dirty_region)
        # print(dirty_region)
        # 只更新有变化的区域
        if not dirty_region.isEmpty():
            self.update(dirty_region)
        # 没有脏区域说明本帧没有任何变化，无需重绘：
        # 位置/颜色/可见性变化都会经 prepareDirtyChange() 进入脏区域，
        # 不再对全部图元做 check_moving() 轮询（那曾占满整个 GUI 线程）。
        # 单帧内的几何漂移仍由 paint() 里的 __check_position_change() 兜底。
        # 重置脏区域记录
        self.dirtyRegion_manager.reset()

        

    def setSceneRect(self, rect: QRectF):
        """ 初始化四叉树根节点 """
        super().setSceneRect(rect)
        self.quadtree = QuadtreeNode(rect)
        self.quadtree.set_scene_ref(super())

    def addItem(self, item: base_element)->bool:
        """ 添加项到场景和四叉树 """
        super().addItem(item)
        if self.quadtree:
            if not self.quadtree.boundary.intersects(item.sceneBoundingRect()):
                print(f"超出边界了，因此没有添加进树{item.sceneBoundingRect()}")
            return self.quadtree.insert(item)
        return True
    
    def removeItem(self, item: base_element):
        super().removeItem(item)
        if self.quadtree:
             self.quadtree.remove(item)

    def deleteItem(self, item: base_element):
        if self.quadtree:
             self.quadtree.remove(item)
        super().deleteItem(item)
        self.selectionChanged.emit()

    def items_in_area(self, area: QRectF) -> list:
        """ 使用四叉树快速查询区域内的项 """
        found_items = set()
        if self.quadtree:
            self.quadtree.query(area, found_items)
        return found_items

    def on_mouse_move(self,pos):
        
        """pos:鼠标场景坐标"""

        # 创建查询区域（以鼠标为中心，100x100矩形）
        view_center_pos = self.sceneToView(pos)
        a= 50/self.scale_factor
        view_area = QRectF(view_center_pos.x()-a,view_center_pos.y()-a,a*2,a*2)
        scene_area = QRectF(self.viewToScene(view_area.topLeft()),self.viewToScene(view_area.bottomRight()))
    
        if not hasattr(self,"area"):
            setattr(self,"area",view_area)
        self.area =view_area
        items = self.items_in_area(scene_area)

        end_points = []
        center_points = []

        for child in self.findChildren(base_element):
            if  child in items:
                child.check_hover(self.sence_pos_mouse)
            else:
                if child.is_in_group() or isinstance(child,group_element):
                    self.hover_sta_change.emit(child)
                child.set_hover(False)


        for item in items:
            # for child in  self.findChildren(base_element):
            # item.check_hover(self.sence_pos_mouse)
            if not( item.get_selected() and  self.CTRL_pressed_flag ): 
                if isinstance(item,line_element):
                    head_pos = item.get_scene_head_pos()
                    end_pos =  item.get_scene_end_pos()
                    center_pos = item.get_scene_center_pos()
                    end_points.append(head_pos)
                    end_points.append(end_pos)
                    center_points.append(center_pos)
                if isinstance(item,rect_element) or isinstance(item,text_element) or isinstance(item,image_element):
                    head_pos = item.get_scene_head_pos()
                    end_pos =  item.get_scene_end_pos()
                    center_pos = item.get_scene_center_pos()
                    topRight   = item.get_scene_topRight()
                    bottomLeft = item.get_scene_bottomLeft()
                
                    end_points.append(head_pos)
                    end_points.append(end_pos)
                    end_points.append(topRight)
                    end_points.append(bottomLeft)
                    center_points.append(center_pos)
                if isinstance(item,circle_element):
                    center_pos = item.get_scene_center_pos()
                    center_points.append(center_pos)

        

        
        # self.statusBar.showMessage(f"区域内有 {len(items)} 个图形项")
      

        self.snapSys.update_grid(scene_area)
        self.snapSys.update_endpoints(end_points)
        self.snapSys.update_midpoints(center_points)
        self.snapSys.snap_to_point(pos)

      




    def wheelEvent(self, event):
        super().wheelEvent( event)
        self.snapSys.set_snap_threshold(self.scene_units_per_grid_x/self.grid_size/self.scale_factor*10)
        

    def mouseMoveEvent(self, event):

        # ``super().mouseMoveEvent`` refreshes ``sence_pos_mouse`` from this
        # event, so evaluate snapping afterwards.  Doing it before used the
        # previous mouse sample, which made a fast move to a grid intersection
        # stop one event short of the actual position.
        super().mouseMoveEvent(event)
        self.on_mouse_move(self.sence_pos_mouse)
       
    
    def mousePressEvent(self, event):
        super().mousePressEvent( event)

        if event.button() == Qt.LeftButton and self._mode == SceneMode.Run:
            previous = self._event_pressed_group
            if previous is not None:
                previous.handle_mouse_release(False)
            self._event_pressed_group = self._find_event_group_at(
                self._event_scene_pos(event)
            )
            if self._event_pressed_group is not None:
                self._event_pressed_group.handle_mouse_press()
        
        if event.button() == Qt.RightButton:
            if self.is_setting_father or self.is_setting_base_pos:
                event.ignore()  # 明确忽略事件，阻止传递到contextMenuEvent
                self.setContextMenuPolicy(Qt.NoContextMenu)  # 完全禁用默认右键菜单
                
                # self.is_setting_group_pos = False
                self.is_setting_father = False
                self.is_setting_base_pos =False
                print("不打开右键菜单")
              
                return  # 直接返回，确保不会继续处理
            else:
                print("------------")
                self.setContextMenuPolicy(Qt.DefaultContextMenu)
        elif event.button() == Qt.MiddleButton:
            area = QRectF(QPointF(-50000.0,-50000.0),QPointF(50000.0,50000.0))
            items = self.items_in_area(area)
            print(items)

      
    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent( event)
        





        if event.button() == Qt.LeftButton and self._mode == SceneMode.Run:
            group = self._event_pressed_group
            self._event_pressed_group = None
            if group is not None:
                group.handle_mouse_release(
                    group.contains_scene_pos(self._event_scene_pos(event))
                )

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        if event.button() == Qt.LeftButton and self._mode == SceneMode.Run:
            group = self._find_event_group_at(self._event_scene_pos(event))
            if group is None:
                self.double_clicked_without_group.emit()

    def on_menu_closed(self):
        self.menu_opened = False

    def extend_context_menu(self, menu):
        """Hook for subclasses that want to append their own actions."""

    def contextMenuEvent(self, event):
        """鼠标右键按下时（默认行为）：
            当用户按下并释放鼠标右键后，若未在 mousePressEvent 或 mouseReleaseEvent 中拦截事件，系统会自动触发 contextMenuEvent。
            显式请求上下文菜单时：
            通过代码调用 QWidget::customContextMenuRequested() 信号或 QMenu::exec() 手动触发。"""

        if self._mode == SceneMode.Run:
            return

        def set_group_zValue(item:base_element,val):
            if item.is_has_child():
                item.set_zValue(val)
                for child in item.childItems():
                    set_group_zValue(child,val)
            else:
                item.set_zValue(val)
        
        def add_zValue_group(item:base_element,val):
            if item.is_has_child():
                item.set_zValue(val+ item.zValue())
                for child in item.childItems():
                    add_zValue_group(child,val)
            else:
                item.set_zValue(val+ item.zValue())

        def handle_go_top():
            def get_min_zValue_in_group(item:base_element):
                min_val =9999
                            # 当前节点的 zValue 参与比较
                min_val = min(min_val, item.zValue())

                # 如果有子节点，递归查找最小值
                if item.is_has_child():
                    for child in item.childItems():
                        child_min = get_min_zValue_in_group(child)
                        min_val = min(min_val, child_min)
                return min_val

            print("上移到顶")
            max_val= -9999
            for child in self.findChildren(base_element):
                if child.zValue()>max_val:
                    max_val = child.zValue()
            min_in_selected = 9999
           

            for child in self.findChildren(base_element):
                if child.get_selected():
                    min_in_selected =get_min_zValue_in_group(child)

            for child in self.findChildren(base_element):
                if child.get_selected():
                    if isinstance(child,group_element):
                        add_zValue_group(child, max_val-min_in_selected+1)
                    else:
                        child.set_zValue( max_val + 1 )

        def handle_go_bottom():
            def get_max_zValue_in_group(item:base_element):
                max_val =9999
                            # 当前节点的 zValue 参与比较
                max_val = min(max_val, item.zValue())

                # 如果有子节点，递归查找最小值
                if item.is_has_child():
                    for child in item.childItems():
                        child_min = get_max_zValue_in_group(child)
                        max_val = min(max_val, child_min)
                return max_val

            print("移到最底")
            min_val= 9999
            for child in self.findChildren(base_element):
                if child.zValue()<min_val:
                    min_val = child.zValue()

            max_in_selected = 9999

            for child in self.findChildren(base_element):
                if child.get_selected():
                    max_in_selected =get_max_zValue_in_group(child)

            for child in self.findChildren(base_element):
                if child.get_selected():
                    if isinstance(child,group_element):
                        add_zValue_group(child, -(max_in_selected-min_val+1))
                    else:
                        child.set_zValue(min_val - 1 )
        #     return
        self.menu_opened = True
        menu                   = QMenu(self)
        arrange_menu               = QMenu(self)
        action_go_top          = arrange_menu.addAction("移到最前")
        action_go_up           = arrange_menu.addAction("上移一层")
        action_go_down         = arrange_menu.addAction("下移一层")
        action_go_bottom       = arrange_menu.addAction("移到最后")

        # 方法1：监听关闭信号
        menu.aboutToHide.connect(self.on_menu_closed)
        action_line           = menu.addAction("绘制直线")
        action_rect           = menu.addAction("绘制矩形")
        action_triangle       = menu.addAction("绘制三角形")
        action_circle         = menu.addAction("绘制圆")
        action_new_image       = menu.addAction("新建图片")
        action_new_text       = menu.addAction("新建标签")
        action_fill_unfill    = menu.addAction("填充/不填充")
        action_copy    = menu.addAction("复制")
        action_paste   = menu.addAction("粘贴")


        action_delete         = menu.addAction("删除")
        action_delete_all     = menu.addAction("删除所有")
        action_save           = menu.addAction("保存元素")
        action_load           = menu.addAction("载入元素")
        action_set_group      = menu.addAction("设置成组")
        action_free_group     = menu.addAction("拆解组")
        action_select_all     = menu.addAction("全选/全不选")

        action_set_father     = menu.addAction("设置父图元")
        action_remove_father  = menu.addAction("解除父子关系")
        action_set_base_pos   = menu.addAction("设置图元的旋转中心")
 
        action_arrange        = menu.addAction("排列")
        action_arrange.setMenu(arrange_menu)
       
        action_save_widget    = menu.addAction("保存控件")
        action_agv_test       = menu.addAction("agv test")
        self.extend_context_menu(menu)
        selected_action       = menu.exec(event.globalPos())
        
        if selected_action == action_line:
            print("绘制直线")
            self.action_begin_draw_line.emit()
        elif selected_action == action_rect:
            print("绘制矩形")
            self.action_begin_draw_rect.emit()
        elif selected_action == action_triangle:
            print("绘制三角形")
            self.action_begin_draw_triangle.emit()
        elif   selected_action == action_circle:
            print("绘制圆")
            self.action_begin_draw_circle.emit()
        elif   selected_action == action_new_image:
            print("新建图片")
            self.action_begin_new_image.emit()
        elif   selected_action == action_new_text:
            print("新建文本")
            self.action_begin_new_text.emit()
        
        elif   selected_action == action_fill_unfill:
            for child in self.findChildren(QObject):
                if isinstance(child, rect_element) or isinstance(child, circle_element):
                    if child.get_selected():
                        child.set_fill(not child.get_fill())
        
        elif   selected_action == action_copy:         
            if not hasattr(self,"has_selected_flag"):
                setattr(self,"has_selected_flag",False)
            for child in self.findChildren(QObject):
                if isinstance(child, base_element):
                    if child.get_selected():
                        self.has_selected_flag =True
                        break
            if not self.has_selected_flag:
               
                print("未选择需要复制的项")
                return
            del self.has_selected_flag
            
            
            
            self.copy_selected()
            
        elif selected_action == action_paste: 
            self.paste()

        elif selected_action == action_delete:
            print("delete")
            for child in self.findChildren(QObject):
                if isinstance(child, base_element) :
                    if child.get_selected():
                        child.Delete()
                       
                
        elif selected_action == action_delete_all:
            print("delete all")
            self.delete_all_elements()
        elif selected_action == action_save:
            print("save")
            self.save_element_info(self.scene_file_path or "datas/data.json")
        elif selected_action == action_load:
            print("load")
            self.load_element_info(self.scene_file_path or "datas/data.json")
        elif selected_action == action_set_group:
            """编辑成组"""
            if not hasattr(self,"has_selected_flag"):
                setattr(self,"has_selected_flag",False)
            for child in self.findChildren(QObject):
                if isinstance(child, base_element) :
                    if child.get_selected() and not child.is_has_parent():
                        self.has_selected_flag =True
                        break
            if not self.has_selected_flag:
                print("未选择需要组合的元素")
                return
            del self.has_selected_flag
            # self.rect_params={}
            # top_window=group_params_setup(rect_params=self.rect_params)
            # top_window.exec()
            # if bool(self.rect_params) ==False:
            #     return

            items_lst = []
            for child in self.findChildren(QObject):
                # if isinstance(child, rect_element) or isinstance(child, circle_element) or isinstance(child, line_element):
                #     if child.get_selected() and not child.is_in_group():
                #         items_lst.append(child)
                if isinstance(child, base_element) :
                    if child.get_selected() and not child.is_in_group() and not child.is_has_parent():
                        items_lst.append(child)
            self.action_set_group.emit(items_lst)
      
       
        elif selected_action == action_set_base_pos:
            if not hasattr(self,"has_selected_flag"):
                setattr(self,"has_selected_flag",False)
            for child in self.findChildren(QObject):
                if isinstance(child, base_element) :
                    if child.get_selected():
                        self.has_selected_flag =True
                        break
            if not self.has_selected_flag:
               
                print("未选择需要设置旋转中心的元素")
                return
            del self.has_selected_flag
            self.is_setting_base_pos = True
            self.setContextMenuPolicy(Qt.NoContextMenu)  # 完全禁用默认右键菜单
        
        elif selected_action == action_set_father:
            """设置父图元"""
            if not hasattr(self,"has_selected_flag"):
                setattr(self,"has_selected_flag",False)
            for child in self.findChildren(QObject):
                if isinstance(child, base_element) :
                    if child.get_selected():
                        self.has_selected_flag =True
                        break
            if not self.has_selected_flag:
               
                print("未选择需要父图元的元素")
                return
            del self.has_selected_flag
            self.is_setting_father = True
            self.selected_items = []
            for child in self.findChildren(QObject):
                if isinstance(child, base_element):
                    if child.get_selected() and not child.is_in_group():
                        self.selected_items.append(child)
                        
        elif selected_action == action_remove_father:
            """解除父图元"""
            if not hasattr(self,"has_selected_flag"):
                setattr(self,"has_selected_flag",False)
            for child in self.findChildren(QObject):
                if isinstance(child, base_element) :
                    if child.get_selected():
                        self.has_selected_flag =True
                        break
            if not self.has_selected_flag:
                print("未选择需要解除父图元的元素")
                return
            del self.has_selected_flag

            for child in self.findChildren(QObject):
                if isinstance(child, base_element) :
                    if child.get_selected():
                        child.removeParentItem()

        elif selected_action == action_select_all:
            if not hasattr(self,"select_all_flag"):
                setattr(self,"select_all_flag",False)  
            else:
                self.select_all_flag = not self.select_all_flag
            for child in self.findChildren(base_element):
                child.set_selected(self.select_all_flag)
       
        elif selected_action == action_free_group:
            """拆解组"""
            for child in self.findChildren(QObject):
                if isinstance(child, group_element)  and child.get_selected():
                    if child.is_has_parent()==False:
                        child.free_group()

        elif selected_action == action_go_top:
            handle_go_top()
            
            # def get_min_zValue_in_group(item:base_element):
            #     min_val =9999
            #                 # 当前节点的 zValue 参与比较
            #     min_val = min(min_val, item.zValue())

            #     # 如果有子节点，递归查找最小值
            #     if item.is_has_child():
            #         for child in item.childItems():
            #             child_min = get_min_zValue_in_group(child)
            #             min_val = min(min_val, child_min)
            #     return min_val

            # print("上移到顶")
            # max_val= -9999
            # for child in self.findChildren(base_element):
            #     if child.zValue()>max_val:
            #         max_val = child.zValue()
            # min_in_selected = 9999
           

            # for child in self.findChildren(base_element):
            #     if child.get_selected():
            #         min_in_selected =get_min_zValue_in_group(child)

            # for child in self.findChildren(base_element):
            #     if child.get_selected():
            #         if isinstance(child,group_element):
            #             add_zValue_group(child, max_val-min_in_selected+1)
            #         else:
            #             child.set_zValue( max_val + 1 )

        elif selected_action == action_go_up:
            print("上移")
            
            for child in self.findChildren(base_element):
                if child.get_selected():
                    if isinstance(child,group_element):
                        set_group_zValue(child,child.zValue() + 1)
                    else:
                        child.set_zValue(child.zValue() + 1)
        
        elif selected_action == action_go_down:
            print("下沉")
            for child in self.findChildren(base_element):
                if child.get_selected():
                    if isinstance(child,group_element):
                        set_group_zValue(child,child.zValue() - 1)
                    else:
                        child.set_zValue(child.zValue() - 1)
        
        elif selected_action == action_go_bottom:
            handle_go_bottom()
            # def get_max_zValue_in_group(item:base_element):
            #     max_val =9999
            #                 # 当前节点的 zValue 参与比较
            #     max_val = min(max_val, item.zValue())

            #     # 如果有子节点，递归查找最小值
            #     if item.is_has_child():
            #         for child in item.childItems():
            #             child_min = get_max_zValue_in_group(child)
            #             max_val = min(max_val, child_min)
            #     return max_val

            # print("移到最底")
            # min_val= 9999
            # for child in self.findChildren(base_element):
            #     if child.zValue()<min_val:
            #         min_val = child.zValue()

            # max_in_selected = 9999

            # for child in self.findChildren(base_element):
            #     if child.get_selected():
            #         max_in_selected =get_max_zValue_in_group(child)

            # for child in self.findChildren(base_element):
            #     if child.get_selected():
            #         if isinstance(child,group_element):
            #             add_zValue_group(child, -(max_in_selected-min_val+1))
            #         else:
            #             child.set_zValue(min_val - 1 )
           
           

        elif selected_action == action_save_widget:
            if not hasattr(self,"has_selected_flag"):
                setattr(self,"has_selected_flag",False)
            for child in self.findChildren(QObject):
                if isinstance(child, base_element) :
                    if child.get_selected():
                        self.has_selected_flag =True
                        break
            if not self.has_selected_flag:
                print("未选择需要设置旋转中心的元素")
                return
            del self.has_selected_flag

            for child in self.findChildren(base_element):
                if child.get_selected():
                    if isinstance(child,text_element):
                        self.current_widget_to_save = child

        elif selected_action == action_agv_test:
         
            top_window=agv_test(self,self.scene_manager)
            top_window.exec()


    def save_current_widget(self,item:text_element):
        rect = self.rect_viewToWindow(self.rect_sceneToView(item.sceneBoundingRect()))
        
        pixmap = QPixmap(rect.size().toSize())



    # def delete_all_elements(self):
    #     for child in self.findChildren(QObject):
    #         if isinstance(child, base_element) :

    #             child.deleteLater()
    #             self.quadtree.remove(child)
    #             self.scene_manager.m_items.clear()
    #             self.update()
    def copy_selected(self):
        """复制选中图元（自动处理父子关系）"""
        self.selected_items = []
        for child in self.findChildren(base_element):
            if child.get_selected() :
                self.selected_items.append(child)

        selected = self.selected_items
        if not selected: 
            return
        
        # 过滤出顶层图元（无父图元或父图元未被选中）
        top_level_items = []
        for item in selected:
            parent = item.parentItem()
            while parent:
                if parent in selected:
                    break  # 如果父级也被选中，跳过子级
                parent = parent.parentItem()
            else:
                top_level_items.append(item)
        
        # 克隆图元并存储
        self.copied_items = [item.clone() for item in top_level_items]


        print(f"顶层复制项：{self.copied_items}")
        # self.paste_count = 0  # 重置粘贴计数器

    def paste(self):
        """粘贴复制的图元"""
        def add_child_item(item:base_element):
            """该图元下的所有子项加入""" 
            if item.is_has_child():
                for child in item.childItems():
                    self.all_copied_items.append(child)
                    add_child_item(child)
            else:
                return
        if not self.copied_items:
            return
        
       
        offset = self.paste_offset 
        self.all_copied_items = []

        # 添加克隆图元到场景
        for item in self.copied_items:
            item.setPos(item.pos() + offset)
            self.all_copied_items.append(item)
            add_child_item(item)

        for  item in self.all_copied_items:   
            item.set_scene_ref(self)
            new_id = self.scene_manager.m_idGenerator.generateID()
            item.setID(new_id)

        # ------------------------------------------------------------------
        # 命名：顶层图元在这里确定名字，组内成员只替换组名前缀。
        # 例如组“组1”的成员“组1_abc”复制后得到组“组1_2”、成员“组1_2_abc”，
        # 成员名不会再追加 _2 之类的后缀。
        # 这一步还没有绑定 manager，_rename_item 只改名字，不会动名字表。
        # ------------------------------------------------------------------
        reserved_names = set()

        def name_in_use(name: str) -> bool:
            return name in reserved_names or name in self.scene_manager.m_name_items

        def free_name(candidate: str) -> str:
            name = candidate
            index = 2
            while name_in_use(name):
                name = f"{candidate}_{index}"
                index += 1
            reserved_names.add(name)
            return name

        def default_name_args(item: base_element):
            """返回该图元默认名称的前缀与计数器。"""

            if isinstance(item, group_element):
                return "组_", group_element
            if isinstance(item, triangle_element):
                return "三角形_", triangle_element
            if isinstance(item, rect_element):
                return "矩形_", rect_element
            if isinstance(item, line_element):
                return "直线_", line_element
            if isinstance(item, circle_element):
                return "圆_", circle_element
            if isinstance(item, text_element):
                return "文本_", text_element
            return "图片_", image_element

        def next_default_name(prefix: str, counter_holder) -> str:
            """沿用“类型_序号”命名，跳过已被占用的名字。"""

            while True:
                name = f"{prefix}{counter_holder.count}"
                if not name_in_use(name):
                    reserved_names.add(name)
                    return name
                counter_holder.count += 1

        def rename_members(item: base_element, old_prefix: str, new_prefix: str):
            """把子树里的组名前缀换成新组名前缀。

            旧工程里的成员名可能还没有组名前缀，或者改写后的名字已被占用，
            这类成员退回默认命名，避免覆盖已有的名字。
            """

            name = str(item.get_name() or "")
            if old_prefix and name.startswith(old_prefix):
                base = name[len(old_prefix):]
            else:
                base = name
            candidate = f"{new_prefix}{base}" if (new_prefix and base) else ""
            if candidate and not name_in_use(candidate):
                reserved_names.add(candidate)
                item._rename_item(candidate)
            else:
                item._rename_item(next_default_name(*default_name_args(item)))
            for child in list(item.m_children):
                rename_members(child, old_prefix, new_prefix)

        for item in self.copied_items:
            old_name = str(item.get_name() or "")
            if isinstance(item, group_element):
                if old_name:
                    new_name = free_name(old_name)
                else:
                    new_name = next_default_name("组_", group_element)
                item._rename_item(new_name)
                if old_name:
                    for child in list(item.m_children):
                        rename_members(child, f"{old_name}_", f"{new_name}_")
            else:
                item._rename_item(next_default_name(*default_name_args(item)))

        # 名字定下来后再绑定 manager 并入库，名字表里保存的就是最终名字。
        for item in self.all_copied_items:
            item.set_scene_manager_ref(self.scene_manager)
            item.completed(True)

        for item in self.scene_manager.m_items.values():
            if item in self.all_copied_items:
                item.set_selected(True)
                # self.selected_items.append(item)
            else:
                item.set_selected(False)
       
        self.copy_selected()
     

    def delete_all_elements(self):

        # def free_all_groups(item:base_element):
        #     if isinstance(group_element):
                
        #         self.free_group

        #         free_all_groups()

        def remove_parent_item(item:base_element):
            """移除该图元下的所有父项"""
            if item.m_parent:
                
                parent_item = item.m_parent
                item.removeParentItem(True)
                remove_parent_item(parent_item)
            else:
                return


        for child in self.findChildren(base_element):
            child.set_selected(True)
        #移除父项
        for child in self.findChildren(base_element):
            
            remove_parent_item(child)
        
        # for child in self.findChildren(base_element):
        #     if isinstance(child,group_element):
        #         child.free_group()
        #     child.removeChildsItem() if child.is_has_child() else None

        for child in self.findChildren(base_element):
            child.Delete()
        self.quadtree.remove_all()
        self.update()
    def save_element_info(self, filename="datas/data.json"):
        """Serialize the scene.

        The default keeps the legacy run-mode behaviour, while design-mode
        pages pass their own absolute page file path.
        """
        SceneSerializer.serialize_scene(self, filename)


    def load_element_info(self, filename="data.json"):
        self.delete_all_elements()
        SceneSerializer.deserialize_scene(self, filename)
        self.update()
        self.__load_done = True
    def load_element_info2(self, filename="data2.json"):
        self.delete_all_elements()
        SceneSerializer.deserialize_scene(self, filename)
        self.update()
        self.__load_done = True
    
    def right_alignment_for_selected(self):
        """右对齐"""
        min_y = 500000.0
        self.selected_items = []
        for child in self.findChildren(base_element):
            if child.get_selected() and not child.is_has_parent() :
                self.selected_items.append(child)
                if child.get_scene_topLeft().y() < min_y:
                    min_y = child.get_scene_topLeft().y()
        selected = self.selected_items
        if not selected: 
            return
        for item in selected:
            pos = QPointF(item.get_scene_topLeft().x(),min_y)
            item.change_position(pos)

    def left_alignment_for_selected(self):
        """左对齐"""
        max_y = -500000.0
        self.selected_items = []
        for child in self.findChildren(base_element):
            if child.get_selected() and not child.is_has_parent() :
                self.selected_items.append(child)
                if child.get_scene_bottomRight().y() > max_y:
                    max_y = child.get_scene_bottomRight().y()
        selected = self.selected_items
        if not selected: 
            return
        for item in selected:
            pos = QPointF(item.get_scene_topLeft().x(),max_y-item.getSize().height())
            item.change_position(pos)

    def bottom_alignment_for_selected(self):
        """下对齐"""
        min_x = 500000.0
        self.selected_items = []
        for child in self.findChildren(base_element):
            if child.get_selected() and not child.is_has_parent() :
                self.selected_items.append(child)
                if child.get_scene_topLeft().x() < min_x:
                    min_x = child.get_scene_topLeft().x()
        selected = self.selected_items
        if not selected: 
            return
        for item in selected:
            pos = QPointF(min_x,item.get_scene_topLeft().y())
            item.change_position(pos)

    def top_alignment_for_selected(self):
        """上对齐"""
        max_x = -500000.0
        self.selected_items = []
        for child in self.findChildren(base_element):
            if child.get_selected() and not child.is_has_parent() :
                self.selected_items.append(child)
                if child.get_scene_bottomRight().x() > max_x:
                    max_x = child.get_scene_bottomRight().x()
        selected = self.selected_items
        if not selected: 
            return
        for item in selected:
            pos = QPointF(max_x-item.getSize().width(),item.get_scene_topLeft().y())
            item.change_position(pos)
        
        
    def set_same_horizontal_distance(self):
        
        min_y =  500000.0
        max_y = -500000.0
        self.selected_items = []
        for child in self.findChildren(base_element):
            if child.get_selected() and not child.is_has_parent() :
                self.selected_items.append(child)
                if child.get_scene_topLeft().y() < min_y:
                    min_y = child.get_scene_topLeft().y()
                if child.get_scene_topLeft().y() > max_y:
                    max_y = child.get_scene_topLeft().y()
        selected = self.selected_items
        if not selected or len(selected)==1: 
            return
        distance = (max_y-min_y)/(len(selected)-1)
   
        sorted_items = sorted(selected, key = lambda item: item.get_scene_topLeft().y())
        y_init =  sorted_items[0].get_scene_topLeft().y()
        print(sorted_items)
        for i, item in enumerate(sorted_items):
            pos = QPointF(item.get_scene_topLeft().x(), y_init + distance*i)
            item.change_position(pos)

    def set_same_vertical_distance(self):
        
        min_x =  500000.0
        max_x = -500000.0
        self.selected_items = []
        for child in self.findChildren(base_element):
            if child.get_selected() and not child.is_has_parent() :
                self.selected_items.append(child)
                if child.get_scene_topLeft().x() < min_x:
                    min_x = child.get_scene_topLeft().x()
                if child.get_scene_topLeft().x() > max_x:
                    max_x = child.get_scene_topLeft().x()
        selected = self.selected_items
        if not selected or len(selected)==1: 
            return
        distance = (max_x-min_x)/(len(selected)-1)
        sorted_items = sorted(selected, key = lambda item: item.get_scene_topLeft().x())
        x_init =  sorted_items[0].get_scene_topLeft().x()
        for i, item in enumerate(sorted_items):
            pos = QPointF(x_init + distance*i,item.get_scene_topLeft().y())
            item.change_position(pos)


    # def get_json_path(self):
    #     if getattr(sys, 'frozen', False):
    #         # 打包后的可执行文件路径（如 PyInstaller）
    #         app_dir = os.path.dirname(sys.executable)
    #     else:
    #         # 脚本文件所在路径
    #         app_dir = os.path.dirname(os.path.abspath(__file__))
    #     return os.path.join(app_dir, "data.json")





class IDGenerator:
    def __init__(self):
        self._lock = Lock()  # 线程安全锁
        self.m_nextID = 1    # 起始ID值

    def generateID(self):
        with self._lock:
            current_id = self.m_nextID
            self.m_nextID += 1
            return current_id

    def reset(self, start=1):
        with self._lock:
            self.m_nextID = start

    def updateAfterLoad(self, maxLoadedID):
        with self._lock:
            self.m_nextID = maxLoadedID + 1


class SceneManager(QObject):
    delete_item_signal = Signal(base_element)
    completed_item_signal =Signal(base_element,bool)

    def __init__(self, scene:QuadTreeScene, undo_stack=None, parent=None):
        super().__init__(parent)
        self.m_items = {}           # ID->图元  映射字典
        self.m_name_items = {}      # name->id  映射字典
        self.m_sorted_items = []  #根据Z值排序
        self.m_idGenerator = IDGenerator()
        self.m_scene = scene        # QuadTreeScene实例
        self.m_undoStack = undo_stack  # QUndoStack实例
        self.delete_item_signal.connect(self.deleteItem,Qt.UniqueConnection)
        self.completed_item_signal.connect(self.addItem,Qt.UniqueConnection)
        
    # # 创建图元
    # def createItem(self, item_class, *args, **kwargs):
    #     item = item_class(*args, **kwargs)  # 动态创建图元
    #     item.set_scene_ref(self.m_scene)
    #     item.set_scene_manager_ref(self)
    #     # print(item.get_actived())
    #     # 分配ID
    #     new_id = self.m_idGenerator.generateID()
    #     item.setID(new_id)
        

    # 创建图元
    def createItem(self, item_class, *args, **kwargs):
        item = item_class(*args, **kwargs)  # 动态创建图元
        item.set_scene_ref(self.m_scene)
        item.set_scene_manager_ref(self)
        # print(item.get_actived())
        # 分配ID
        new_id = self.m_idGenerator.generateID()
        item.setID(new_id)
        
        if  isinstance(item,group_element)  :
            name = "组_"
            while item.set_name(name + str(group_element.count))==False:
                # name += str(group_element.count)+"_"
                group_element.count+=1
            
            item.initialize()
        elif isinstance(item,triangle_element)  :
            name = "三角形_"
            while item.set_name(name + str(triangle_element.count))==False:
                triangle_element.count+=1
        elif isinstance(item,rect_element)  :
            name = "矩形_"
            while item.set_name(name + str(rect_element.count))==False:
                # name += str(rect_element.count)+"_"
                rect_element.count+=1

        elif isinstance(item,line_element):
            name = "直线_"
            while item.set_name(name + str(line_element.count))==False:
                # name += str(line_element.count)+"_"
                line_element.count+=1
           
        elif isinstance(item,circle_element):
            name = "圆_"
            while item.set_name(name + str(circle_element.count))==False:
                # name += str(circle_element.count)+"_"
                circle_element.count+=1
           
        elif isinstance(item,text_element):
            name = "文本_"
            while item.set_name(name + str(text_element.count))==False:
                # name += str(text_element.count)+"_"
                text_element.count+=1
        
        elif isinstance(item,image_element):
            name = "图片_"
            while item.set_name(name + str(image_element.count))==False:
                # name += str(text_element.count)+"_"
                image_element.count+=1
        



        self.m_scene.current_element_id = new_id
        self.m_scene.current_element    = item
     
        # item.completed_signal.connect(self.addItem)
        # item.bounding_change_signal.connect(self.re_addItem_to_tree)
        # item.delete_signal.connect(self.deleteItem)
        
        

        # if isinstance(item,group_element):
        #     item.initialize()

        


        # self.m_scene.addItem(item)
        
        # 记录创建命令（需实现CreateCommand）
        # self.m_undoStack.push(CreateCommand(item, self))
        return item
    
    def sort_items_by_zValue(self):
        """根据Z值从小到大排序"""
        items = [value for value in self.m_items.values()]
        self.m_sorted_items = sorted(items, key=lambda item: item.zValue())
    
    # def sort_items_by_zValue_reverse(self):

    #     items = [value for value in self.m_items.values()]
    #     self.m_sorted_items = sorted(items, key=lambda item: item.zValue(),reverse=True)

    def addItem(self,*arg):
       
        item = arg[0]
        construct_from_dict = arg[1]
        # 注册到管理容器
        self.m_items[item.id()] = item
        debug_log(self.m_items.keys())
       
        self.m_scene.addItem(item)

        item.set_zValue(item.id())     if not construct_from_dict else None
        item.construct_name_items()    if  construct_from_dict else None
        self.sort_items_by_zValue()
        
        
        debug_log(f"加入id:{item.id()}type:{item.type}到了场景")

    def re_addItem_to_tree(self,id):
        
        if id in self.m_items.keys():
            item = self.findItem(id)
            self.m_scene.quadtree.remove(item)
            self.m_scene.quadtree.insert(item)
            # print(f'更新图元{id}在树的位置')
    # 删除图元
    def deleteItem(self, item:base_element):
        print(f"准备删除id{item.id()}")
        self.m_items[item.id()] =None
        del self.m_items[item.id()]
        self.m_scene.deleteItem(item)
        self.m_scene.current_element = None
        dic = copy.copy(self.m_name_items)
        for item_name,item_id in  dic.items():
            if item_id==item.id():
                del self.m_name_items[item_name]
        self.sort_items_by_zValue()
        debug_log(self.m_items.keys(), self.m_name_items)
    
        

    # 查找图元
    def findItem(self, id):
        return self.m_items.get(id, None)


    def findItemByName(self, name):
        item_id = self.m_name_items.get(name, None)
        if item_id is not None:
            return self.findItem(item_id)
        return None



class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("test")
        self.resize(1200, 800)
        self.test_window = QuadTreeScene()
        
        self.setCentralWidget(self.test_window)


if __name__ == "__main__":
    app = QApplication([])
    window = MainWindow()
    window.show()
    window.move(100, 100)  # 确保窗口显示在可见位置
    app.exec()
