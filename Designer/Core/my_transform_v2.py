
import math
import enum
from PySide6.QtCore import QPointF
from PySide6.QtGui import QTransform 


class Transform:
    class TransformationType(enum.Enum):

        TxNone                   : QTransform.TransformationType = ... # 0x0
        TxTranslate              : QTransform.TransformationType = ... # 0x1
        TxScale                  : QTransform.TransformationType = ... # 0x2
        TxRotate                 : QTransform.TransformationType = ... # 0x4
        TxShear                  : QTransform.TransformationType = ... # 0x8
        TxProject                : QTransform.TransformationType = ... # 0x10
    def __init__(self, matrix=None):
        if matrix is None:
            self.m = [
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0]
            ]
        else:
            if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
                raise ValueError("Matrix must be 3x3")
            self.m = matrix

    def get_matrix(self):
        return self.m
    
    def get_rotation_angle(self):
        """从2D旋转矩阵获取角度(弧度)"""
        return math.degrees(math.atan2(self.m[0][1], self.m[0][0]))
    
    def translate(self, *args):
        """在现有变换基础上叠加平移变换"""
        # 解析参数
        if len(args) == 1 and isinstance(args[0], QPointF):
            dx, dy = args[0].x(), args[0].y()
        elif len(args) == 2:
            dx, dy = args
        else:
            raise ValueError("参数必须是(x, y)或QPointF")
        
        if dx==0 and dy==0:
            return self
        # self.m[0][2] = dx * self.m[0][0] + dy *self.m[1][0]
        # self.m[1][2] = dx * self.m[0][1] + dy *self.m[1][1]
        # self.m[2][2] = dx * self.m[2][0] + dy *self.m[2][1]
        # 构造平移矩阵
        T = Transform([
            [1.0, 0.0, 0.0 ],
            [0.0, 1.0, 0.0 ],
            [dx,  dy,  1.0 ]
        ])
        
        # 右乘叠加变换：当前变换 = 当前变换 × 平移变换

        result =   self*T
        self.m = result.m
        return self
    

    def rotate(self, angle):
        """在现有变换基础上叠加旋转变换"""

        rad = math.radians(angle)
        c, s = math.cos(rad), math.sin(rad)
        
        # 构造旋转矩阵
        R = Transform([
            [ c,  s,   0.0],
            [-s,  c,   0.0],
            [0.0, 0.0, 1.0]
        ])
        
        
        result =  self * R 
        self.m = result.m
        # self.m = R.m
        return self
    
    def rotate_around(self, angle, pivot: QPointF):
        """绕指定点旋转"""
        # 1. 平移到原点
        self.translate(pivot.x(), pivot.y())
        # 2. 旋转
        self.rotate(angle)
        # 3. 平移回原位置
        self.translate(-pivot.x(), -pivot.y())
        return self

    def determinant(self):
        """计算行列式（正确实现）"""
        m = self.m
        return (m[0][0] * (m[1][1]*m[2][2] - m[1][2]*m[2][1]) -
                m[0][1] * (m[1][0]*m[2][2] - m[1][2]*m[2][0]) +
                m[0][2] * (m[1][0]*m[2][1] - m[1][1]*m[2][0]))
    
    def inverted(self):
        """计算逆矩阵（简化接口）"""
        det = self.determinant()
        
        if abs(det) < 1e-10:
            # 不可逆时返回单位矩阵
            return Transform()
            
        inv_det = 1.0 / det
        m = self.m
        
        # 计算伴随矩阵的转置
        inv_m = [
            [
                (m[1][1]*m[2][2] - m[1][2]*m[2][1]) * inv_det,
                (m[0][2]*m[2][1] - m[0][1]*m[2][2]) * inv_det,
                (m[0][1]*m[1][2] - m[0][2]*m[1][1]) * inv_det
            ],
            [
                (m[1][2]*m[2][0] - m[1][0]*m[2][2]) * inv_det,
                (m[0][0]*m[2][2] - m[0][2]*m[2][0]) * inv_det,
                (m[0][2]*m[1][0] - m[0][0]*m[1][2]) * inv_det
            ],
            [
                (m[1][0]*m[2][1] - m[1][1]*m[2][0]) * inv_det,
                (m[0][1]*m[2][0] - m[0][0]*m[2][1]) * inv_det,
                (m[0][0]*m[1][1] - m[0][1]*m[1][0]) * inv_det
            ]
        ]
        
        return Transform(inv_m)
    def __mul__(self, other):
        """矩阵乘法（---行主序）"""
        result = [[0.0]*3 for _ in range(3)]
        for i in range(3):
            for j in range(3):
                for k in range(3):
                    result[j][i] += self.m[k][i] * other.m[j][k]
        return Transform(result)
    
    # def __mul__(self, other):
    #     """矩阵乘法（行主序）"""
    #     result = [[0.0]*3 for _ in range(3)]
    #     for i in range(3):
    #         result[i][0] = self.m[i][0]*other.m[0][0] + self.m[i][1]*other.m[1][0] + self.m[i][2]*other.m[2][0]
    #         result[i][1] = self.m[i][0]*other.m[0][1] + self.m[i][1]*other.m[1][1] + self.m[i][2]*other.m[2][1]
    #         result[i][2] = self.m[i][0]*other.m[0][2] + self.m[i][1]*other.m[1][2] + self.m[i][2]*other.m[2][2]
    #     return Transform(result)
    
    def __eq__(self, other):
        if not isinstance(other, Transform):
            return False
        if self is other:
            return True
        a = self.m
        b = other.m
        if a == b:
            return True
        # 浮点抖动容差比较（热路径：每帧每个图元都会调用一次）
        for i in range(3):
            row_a = a[i]
            row_b = b[i]
            for j in range(3):
                if abs(row_a[j] - row_b[j]) > 1e-10:
                    return False
        return True
    
    def __ne__(self, other):
        return not self.__eq__(other)
    
    def __str__(self):
        return (
            f"Transform(\n"
            f"  [{self.m[0][0]:.4f}, {self.m[0][1]:.4f}, {self.m[0][2]:.4f}]\n"
            f"  [{self.m[1][0]:.4f}, {self.m[1][1]:.4f}, {self.m[1][2]:.4f}]\n"
            f"  [{self.m[2][0]:.4f}, {self.m[2][1]:.4f}, {self.m[2][2]:.4f}]\n"
            ")"
        )
    
    def map(self, point: QPointF):
        """应用变换到点（行主序）"""
        x, y = point.x(), point.y()
        wx = self.m[0][0]*x + self.m[1][0]*y + self.m[2][0]
        wy = self.m[0][1]*x + self.m[1][1]*y + self.m[2][1]
        w  = self.m[0][2]*x + self.m[1][2]*y + self.m[2][2]
        
        # 改进的归一化处理
        if abs(w) > 1e-10:
            wx /= w
            wy /= w
            return QPointF(wx, wy)
        else:
            # 当 w ≈ 0 时，返回无效点
            return QPointF(float('nan'), float('nan'))
    
    def map_inverse(self, point):
        """应用逆变换到点"""
        inv = self.inverted()
        return inv.map(point)



if __name__ == "__main__":
    t= Transform()
    t.translate(300,0)
    t.rotate(90)
    t.translate(-300,0)
    
    p1=t.map(QPointF(10,20))
    
    # t.rotate(30)
    t2=QTransform()
    t2.translate(300,0)
    t2.rotate(90)
    
    t2.translate(-300,0)
    p2=t2.map(10,20)
    # t2.rotate(30)
    print(p1,p2)
