import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle
from matplotlib.transforms import Affine2D

def draw_agv_trajectory_with_rotation(x, y, a, agv_length=0.5, agv_width=0.3):
    """
    使用matplotlib的旋转变换绘制AGV
    """
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # 绘制轨迹线
    ax.plot(x, y, 'b-', alpha=0.3, linewidth=1, label='轨迹')
    
    # 绘制关键点的AGV
    indices = np.linspace(0, len(x)-1, 20, dtype=int)  # 选择20个关键点
    
    for idx in indices:
        i = int(idx)
        # 创建旋转变换
        t = Affine2D().rotate_around(x[i], y[i], a[i])
        
        # 创建矩形
        rect = Rectangle((x[i] - agv_length/2, y[i] - agv_width/2), 
                        agv_length, agv_width,
                        facecolor='lightblue', edgecolor='blue',
                        alpha=0.7, linewidth=1.5)
        
        # 应用旋转
        rect.set_transform(t + ax.transData)
        ax.add_patch(rect)
        
        # 添加编号
        ax.text(x[i], y[i], str(i), fontsize=8, ha='center', va='center')
    
    # 绘制起始和结束的AGV
    for i in [0, -1]:
        t = Affine2D().rotate_around(x[i], y[i], a[i])
        rect = Rectangle((x[i] - agv_length/2, y[i] - agv_width/2), 
                        agv_length, agv_width,
                        facecolor='red' if i == -1 else 'green', 
                        edgecolor='darkred' if i == -1 else 'darkgreen',
                        alpha=0.8, linewidth=2)
        rect.set_transform(t + ax.transData)
        ax.add_patch(rect)
    
    ax.set_xlabel('X坐标', fontsize=12)
    ax.set_ylabel('Y坐标', fontsize=12)
    ax.set_title('AGV轨迹（带旋转矩形）', fontsize=14)
    ax.grid(True, alpha=0.3)
    ax.legend(['轨迹'])
    ax.axis('equal')

    
    plt.tight_layout()
    plt.show()


# 生成示例数据
def generate_sample_data(n_points=100):
    """生成示例AGV轨迹数据"""
    t = np.linspace(0, 4*np.pi, n_points)
    x = t * np.cos(t)  # 螺旋轨迹
    y = t * np.sin(t)
    
    # 计算方向角（轨迹的切线方向）
    dx = np.gradient(x, t)
    dy = np.gradient(y, t)
    a = np.arctan2(dy, dx)  # 方向角
    
    return x, y, a

# 主程序
if __name__ == "__main__":
    # 生成示例数据
    x, y, a = generate_sample_data(200)
    
    # # 方法1: 基础版本
    # print("绘制基础版本...")
    # draw_agv_trajectory_basic(x, y, a, step=15)
    
    # 方法2: 使用旋转矩形
    print("绘制旋转矩形版本...")
    draw_agv_trajectory_with_rotation(x, y, a)
    
    # 方法3: 动画（如果需要可以取消注释）
    # print("生成动画...")
    # animate_agv_trajectory(x, y, a, interval=50)
    
    # 方法4: 绘制所有时间戳的AGV（密集显示）
    def draw_all_agv_positions(x, y, a):
        """绘制所有时间戳的AGV位置（小点表示）"""
        fig, ax = plt.subplots(figsize=(12, 8))
        
        # 绘制轨迹线
        ax.plot(x, y, 'b-', alpha=0.3, linewidth=1)
        
        # 用箭头表示每个点的方向
        for i in range(0, len(x), 5):  # 每隔5个点画一个箭头
            dx = 0.3 * np.cos(a[i])
            dy = 0.3 * np.sin(a[i])
            ax.arrow(x[i], y[i], dx, dy, 
                    head_width=0.1, head_length=0.15, 
                    fc='blue', ec='blue', alpha=0.5)
        
        # 用颜色表示时间序列
        scatter = ax.scatter(x, y, c=range(len(x)), 
                            cmap='viridis', s=20, alpha=0.7)
        
        plt.colorbar(scatter, label='时间戳索引')
        ax.set_xlabel('X坐标', fontsize=12)
        ax.set_ylabel('Y坐标', fontsize=12)
        ax.set_title('AGV轨迹（颜色表示时间）', fontsize=14)
        ax.grid(True, alpha=0.3)
        ax.axis('equal')
        
        plt.tight_layout()
        plt.show()
    
    print("绘制时间序列版本...")
    draw_all_agv_positions(x, y, a)