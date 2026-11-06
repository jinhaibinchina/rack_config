from __future__ import annotations
import math
import numpy as np
from PySide6.QtCore import Signal, Slot,QObject
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .mat_plot import MplPlotWidget

class ToolSystem(QObject):
    
    measure_done = Signal()

    def __init__(self,parent:MplPlotWidget=None):
        
        super().__init__(parent)
       
        self.measure_marks = {
            'headpoints'  :[],    # 端点
            'endpoints'   :[],    # 中点           
            'marklines_x' :[],
            'marklines_y' :[],
            'marktexts_x' :[],
            'marktexts_y' :[]
        }
       
        self.mpl = parent

        self.head_pos       = None
        self.textbox_width  = None
        self.textbox_height = None

        self.current_head_pos = None  # 当前捕捉点 point

    def check_if_show_labels(self):
        if self.textbox_width is None or self.textbox_height is None:
            return
        # print(self.textbox_width,self.textbox_height)
        trans = self.mpl.ax.transData.transform
        show_x_labels = []
        show_y_labels = []
        for line in self.measure_marks['marklines_x']:
            if line:
                xdata = line.get_xdata()
                if abs( trans((xdata[0],0))[0] - trans((xdata[1],0))[0])>self.textbox_width:
                    show_x_labels.append(True)
                else:
                    show_x_labels.append(False)
            else:
                show_x_labels.append(None)
           
        for line in self.measure_marks['marklines_y']:
            if line:
                ydata = line.get_ydata()
                # print(ydata)
                if abs( trans((0,ydata[0]))[1] - trans((0,ydata[1]))[1])>self.textbox_height:
                    show_y_labels.append(True)
                else:
                    show_y_labels.append(False)
            else:
                show_y_labels.append(None)
        
        renderer = self.mpl.canvas.get_renderer()
        
        trans = self.mpl.ax.transData.inverted()
        for i, textbox in enumerate(self.measure_marks['marktexts_x']):
            if textbox:
                textbox.set_visible(show_x_labels[i])
                bbox = textbox.get_window_extent(renderer)
                line = self.measure_marks['marklines_x'][i]
                x_text = (line.get_xdata()[0]+line.get_xdata()[1])/2.0
                y_text = line.get_ydata()[0]
                
                point1 = trans.transform((0, 0))
                point2 = trans.transform((bbox.width, 0))
                box_width_data = point2[0] - point1[0]
                textbox.set_position((x_text-box_width_data/2,y_text))
   

        for i, textbox in enumerate(self.measure_marks['marktexts_y']):
            if textbox:
                textbox.set_visible(show_y_labels[i])
        
        
    def add_success(self):
        return len(self.measure_marks['headpoints']) == len(self.measure_marks['endpoints'])
       
    def add_endpoint(self,mouse_xData,mouse_yData):
        """Add an endpoint to the measurement system.
        
        Args:
            mouse_xData: X coordinate of mouse position
            mouse_yData: Y coordinate of mouse position
        """
        # Check if there are any headpoints to connect to
        if not self.measure_marks['headpoints']:
            return
            
        head_point = self.measure_marks['headpoints'][-1]
        display_head_pose = self.mpl.ax.transData.transform((head_point.get_xdata()[0], head_point.get_ydata()[0]))
        display_end_pose  = self.mpl.ax.transData.transform((mouse_xData, mouse_yData))
        # if display_head_pose[0] == display_end_pose[0] or display_head_pose[1] == display_end_pose[1]:
        #     return
        # print((head_point.get_xdata()[0], head_point.get_ydata()[0]),display_head_pose,display_end_pose)
        distance = math.sqrt( (display_head_pose[0]-display_end_pose[0])*(display_head_pose[0]-display_end_pose[0])
                             + (display_head_pose[1]-display_end_pose[1])*(display_head_pose[1]-display_end_pose[1]))
        if distance<20:
            self.remove_current_head_point()
            return
        endpoint = self.mpl.ax.plot(mouse_xData, mouse_yData, 'x', markersize=2, 
                                    markeredgecolor='#1f77b4', markerfacecolor='yellow')[0]
        self.measure_marks['endpoints'].append(endpoint)


        if head_point.get_xdata()[0] <= endpoint.get_xdata()[0] and head_point.get_ydata()[0] <= endpoint.get_ydata()[0]:
            #_|
            interact_point = (max(head_point.get_xdata()[0],endpoint.get_xdata()[0]),min(head_point.get_ydata()[0],endpoint.get_ydata()[0]))
            if head_point.get_xdata()[0] == endpoint.get_xdata()[0]:
                line_x_xdata = None
                line_x_ydata = None
            else:
                line_x_xdata = np.array([interact_point[0],head_point.get_xdata()[0]])
                line_x_ydata = np.array([interact_point[1],head_point.get_ydata()[0]])
            if head_point.get_ydata()[0] == endpoint.get_ydata()[0]:
                line_y_xdata = None
                line_y_ydata = None
            else:
                line_y_xdata = np.array([interact_point[0],endpoint.get_xdata()[0]])
                line_y_ydata = np.array([interact_point[1],endpoint.get_ydata()[0]])

        elif head_point.get_xdata()[0] >= endpoint.get_xdata()[0] and head_point.get_ydata()[0] >= endpoint.get_ydata()[0]:
            interact_point = (max(head_point.get_xdata()[0],endpoint.get_xdata()[0]),min(head_point.get_ydata()[0],endpoint.get_ydata()[0]))
            if head_point.get_xdata()[0] == endpoint.get_xdata()[0]:
                line_x_xdata = None
                line_x_ydata = None
            else:
                line_x_xdata = np.array([interact_point[0],endpoint.get_xdata()[0]])
                line_x_ydata = np.array([interact_point[1],endpoint.get_ydata()[0]])
            if head_point.get_ydata()[0] == endpoint.get_ydata()[0]:
                line_y_xdata = None
                line_y_ydata = None

            else:
                line_y_xdata = np.array([interact_point[0],head_point.get_xdata()[0]])
                line_y_ydata = np.array([interact_point[1],head_point.get_ydata()[0]])
        elif head_point.get_xdata()[0] <= endpoint.get_xdata()[0] and head_point.get_ydata()[0] >= endpoint.get_ydata()[0]:
            #|_
            interact_point = (min(head_point.get_xdata()[0],endpoint.get_xdata()[0]),min(head_point.get_ydata()[0],endpoint.get_ydata()[0]))
            if head_point.get_xdata()[0] == endpoint.get_xdata()[0]:
                line_x_xdata = None
                line_x_ydata = None
            else:
                line_x_xdata = np.array([interact_point[0],endpoint.get_xdata()[0]])
                line_x_ydata = np.array([interact_point[1],endpoint.get_ydata()[0]])
            if head_point.get_ydata()[0] == endpoint.get_ydata()[0]:
                line_y_xdata = None
                line_y_ydata = None
            else:
                line_y_xdata = np.array([interact_point[0],head_point.get_xdata()[0]])
                line_y_ydata = np.array([interact_point[1],head_point.get_ydata()[0]])
        elif head_point.get_xdata()[0] >= endpoint.get_xdata()[0] and head_point.get_ydata()[0] <= endpoint.get_ydata()[0]:
            #|_
            interact_point = (min(head_point.get_xdata()[0],endpoint.get_xdata()[0]),min(head_point.get_ydata()[0],endpoint.get_ydata()[0]))
            if head_point.get_xdata()[0] == endpoint.get_xdata()[0]:
                line_x_xdata = None
                line_x_ydata = None
            else:

                line_x_xdata = np.array([interact_point[0],head_point.get_xdata()[0]])
                line_x_ydata = np.array([interact_point[1],head_point.get_ydata()[0]])
            if head_point.get_ydata()[0] == endpoint.get_ydata()[0]:
                line_y_xdata = None
                line_y_ydata = None
            else:
                line_y_xdata = np.array([interact_point[0],endpoint.get_xdata()[0]])
                line_y_ydata = np.array([interact_point[1],endpoint.get_ydata()[0]])
        

        
        
        if not (line_x_xdata is None or line_x_ydata is None):
            line_x, = self.mpl.ax.plot(line_x_xdata, line_x_ydata,  color="black",linestyle='--', linewidth=0.5,zorder=1)
        else:
            line_x =None
        self.measure_marks['marklines_x'].append(line_x)
        if not (line_y_xdata is None or line_y_ydata is None):
            line_y, = self.mpl.ax.plot(line_y_xdata, line_y_ydata,  color="black",linestyle='--', linewidth=0.5,zorder=1)
        else:
            line_y =None
        self.measure_marks['marklines_y'].append(line_y)

        renderer = self.mpl.canvas.get_renderer()
        if not (line_x_xdata is None or line_x_ydata is None):
            x = abs(line_x_xdata[0]-line_x_xdata[1])/1000.0
            x_text = (line_x_xdata[0]+line_x_xdata[1])/2.0
            y_text = line_x_ydata[0]
            xcontext = f"{x:.1f}s"
            
            textbox= self.mpl.ax.text(x_text, y_text, xcontext, 
                                bbox=dict(boxstyle="round,pad=0.1", 
                                        facecolor="lightyellow", 
                                        alpha=0.8, 
                                        edgecolor="none"),
                                        fontsize=7,
                                        verticalalignment='center',
                                        weight='bold',zorder=3, clip_on=True)
            
            self.measure_marks['marktexts_x'].append(textbox)

            
            bbox = textbox.get_window_extent(renderer)
            if self.textbox_width is None or self.textbox_width<bbox.width:
                self.textbox_width = bbox.width
        else:
            self.measure_marks['marktexts_x'].append(None)

        if not (line_y_xdata is None or line_y_ydata is None):
            y = abs(line_y_ydata[0]-line_y_ydata[1])
            ycontext = f"{y:.1f}"

            y_text = (line_y_ydata[0]+line_y_ydata[1])/2.0
            x_text = line_y_xdata[0] 
            textbox= self.mpl.ax.text(x_text, y_text, ycontext, 
                                bbox=dict(boxstyle="round,pad=0.1", 
                                        facecolor="lightyellow", 
                                        alpha=0.8, 
                                        edgecolor="none"),
                                        fontsize=7,
                                        verticalalignment='center',
                                        weight='bold',zorder=3, clip_on=True)
            self.measure_marks['marktexts_y'].append(textbox)
            bbox = textbox.get_window_extent(renderer)
            if self.textbox_height is None:
                self.textbox_height = bbox.height
        else:
            self.measure_marks['marktexts_y'].append(None)


        self.measure_done.emit()


    def add_headpoint(self,mouse_xData,mouse_yData):
        display_mouse = self.mpl.ax.transData.transform((mouse_xData, mouse_yData))
        point = self.mpl.ax.plot(mouse_xData, mouse_yData, 'x', markersize=2, 
                                    markeredgecolor='#1f77b4', markerfacecolor='yellow')[0]
        
        self.measure_marks['headpoints'].append(point)
    
    def remove_current_head_point(self):
        if self.measure_marks['headpoints']:
            point =  self.measure_marks['headpoints'].pop()
            
            point.remove()
            self.mpl.update_partly()


    def clear(self):
        self.textbox_width = None
        self.textbox_height = None
        self.measure_marks = {
            'headpoints': [],    # 端点
            'endpoints' : [],    # 中点           
            'marklines_x':[],
            'marklines_y':[],
            'marktexts_x' :[],
            'marktexts_y' :[]
        }
    
    def clear_current_point(self):
        if self.current_snap_pos:
            self.current_snap_pos.remove()
            self.current_snap_pos =None
            self.mpl.update_partly()


    def update_snap_point(self,mouse_xData,mouse_yData):
        
        if self.current_snap_pos:
            self.current_snap_pos.remove()
            self.current_snap_pos =None
        intersection_points_y =[]
        x_data = self.mpl._rcd_data_bridge.xdata_rcd()[self.mpl.idx_min():self.mpl.idx_max()+1]
        idx = np.argmin(np.abs(x_data - mouse_xData))
        for i, line in enumerate(self.mpl.lines):
            if self.mpl.lines_visionable_flag[i] == False:
                continue

            line_name ,_ = self.mpl.lineKeys_lineColors[i]
            y_data = self.mpl._rcd_data_bridge.get_one_data_saved_in_bridge(line_name)[1][self.mpl.idx_min():self.mpl.idx_max()+1]
            y_min,y_max = self.mpl.get_ylim()
            if 0 <= idx < len(x_data):
               
                y_intersect = y_data[idx]
                if  y_min<y_intersect<y_max:
                    intersection_points_y.append(y_intersect)

        if not intersection_points_y:
            return
        index = np.argmin(np.abs(np.array(intersection_points_y) - mouse_yData))
        x,y=x_data[idx], intersection_points_y[index]

        point = self.mpl.ax.transData.transform((x, y))
        point_mouse = self.mpl.ax.transData.transform((mouse_xData, mouse_yData))

        if abs(point[1]-point_mouse[1])> 10:
            return

        self.current_snap_pos = self.mpl.ax.plot(x, y, 'ro', markersize=2, 
                                    markeredgecolor='#1f77b4', markerfacecolor='yellow')[0]


