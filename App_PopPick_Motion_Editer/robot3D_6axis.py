from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtGui import (
    QColor, QBrush, QFont, QFontMetrics, QPainter, QTextFormat, QTextCharFormat,
    QSyntaxHighlighter, QKeyEvent, QAction, QTextCursor
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QSizePolicy,
    QTreeWidget, QTreeWidgetItem, QLabel, QLineEdit, QGroupBox,
    QPushButton, QMessageBox, QDialog, QFormLayout, QDialogButtonBox,
    QSplitter, QPlainTextEdit, QTextEdit, QInputDialog, QFileDialog,
    QComboBox, QMenu, QProgressDialog,
    QCompleter, QToolTip
)
from Robot3D_6axis_Com import SignalBridge,TcpPositionWorker,ModbusClient
import sys

# ==================== 6轴关节机器人 3D 可视化 ====================
# 结构（按图纸 image(2).png + 用户描述）：
#   J1 电机1：轴线竖直(Y)、朝下、与立柱同轴；J1 转时方壳不动，电机随转
#   J2 电机2：轴线水平(Z)，轴端固定在电机1 圆柱侧面（支架 z 36->85.5），本体旋转
#   大臂管1：轴线与电机2 轴线相交（穿入电机2 本体），距电机1 轴线 116.50
#   J3 电机3：轴线水平(Z) 在 z=37.3；大臂管经 L 型圆柱拐角（Ø44 等径 90° 弯管：X 向顺延
#             -> 四分之一圆环弯 -> Z 向插入电机3 端面）跨 79.2；电机3 本体旋转带出小臂管
#   小臂管2：穿入电机3 本体（轴线与电机3 轴线相交，z=37.3），与大臂管轴线距 79.2，不同轴
#   腕部（电机挂电机链式结构）：
#     J4 输出轴朝 +Z（反向180°到另一侧），L3=79.20：J5 侧面固定在 J4 输出轴上（z=+79.2）
#     J5 输出朝下(-Y)，L4=79.20：J6 侧面固定在 J5 输出轴上（y=-79.2），J6 Ø60x62 轴X，J5 轴穿 J6 中心
#     电机4->5、5->6 均为输出轴直接圆柱插入下一电机侧面（无连接块）
#   电机直径：J1/J2 = Ø80，J4/J5/J6 = Ø60，J3 = Ø79.2（关节）
#
# 尺寸链（零位：臂沿 +X，mm；z+ = 电机2 侧）：
#   J1 轴 (0,120.5,0)；J2 轴 (0,132.5,116.5)；管1 (y132.5, z116.5) x:0->203.5
#   J3 轴 (203.5,132.5,37.3)；管2 (y132.5, z37.3) x:0->173；J4 轴 (173,0,0)（j3 系）
#   电机本体长度统一 L=62；J5 轴与管2 轴线距 = 79.2；两管轴线距 = 79.2；J5 轴穿过电机6 中心
#   J4 输出(+Z) 79.20 -> J5 轴 (0,0,+79.2)（j4 系）；J5 输出(-Y) 79.20 -> J6 轴 (0,-79.2,+79.2)

VISUAL_SCALE = 3.0

BASE_PLATE   = 261.91 * VISUAL_SCALE   # 底板 X 向宽
BASE_PLATE_D = 244.53 * VISUAL_SCALE   # 底板 Z 向深
FOOT_SP      = 219.53 * VISUAL_SCALE   # 支脚/螺栓孔距
BASE_PLATE_T = 15    * VISUAL_SCALE

LEG_LEN = 170 * VISUAL_SCALE
LEG_R   = 25  * VISUAL_SCALE
LEG_Y   = 30  * VISUAL_SCALE
PAD_H   = 8   * VISUAL_SCALE

FLANGE_PLATE = 170 * VISUAL_SCALE
FLANGE_T     = 12  * VISUAL_SCALE
FLANGE_HOLE  = 65  * VISUAL_SCALE

PEDESTAL_W   = 120 * VISUAL_SCALE
PEDESTAL_TOP = 100 * VISUAL_SCALE
J1_HOUSING_D = 100 * VISUAL_SCALE

J1_AXIS_H = 120.50 * VISUAL_SCALE
J2_AXIS_H = 132.50 * VISUAL_SCALE

L1 = 203.50 * VISUAL_SCALE   # 大臂（J2 轴 -> J3 轴）
L2 = 173    * VISUAL_SCALE   # 小臂（J3 轴 -> J4 轴）
L3 = 79.20  * VISUAL_SCALE   # 腕一节（J4 -> J5）
L4 = 79.20  * VISUAL_SCALE   # 腕二节（J5 -> J6 法兰面）

R_JOINT = 39.60 * VISUAL_SCALE   # Ø79.20 关节/电机2/3/4
R_TUBE  = 22    * VISUAL_SCALE
TUBE2_R = R_TUBE * 0.95

MOTOR1_R, MOTOR1_L = 40 * VISUAL_SCALE, 62 * VISUAL_SCALE    # J1 Ø80x62
MOTOR2_R, MOTOR2_L = 40 * VISUAL_SCALE, 62 * VISUAL_SCALE    # J2 Ø80
MOTOR3_R, MOTOR3_L = 39.6 * VISUAL_SCALE, 62 * VISUAL_SCALE  # J3 Ø79.2
MOTOR4_R, MOTOR4_L = 30 * VISUAL_SCALE, 62 * VISUAL_SCALE    # J4 Ø60
J5_R, J5_H = 30 * VISUAL_SCALE, 62 * VISUAL_SCALE            # J5 Ø60x62（轴Y，输出朝下）
J6_R, J6_L = 30 * VISUAL_SCALE, 62 * VISUAL_SCALE            # J6 Ø60x62（轴X，与电机3/4/5 等长）
SHAFT4_R = 14 * VISUAL_SCALE   # J4 输出轴半径
SHAFT5_R = 12 * VISUAL_SCALE   # J5 输出轴半径

# 轴向位置（未缩放毫米，世界系；z+ = 电机2 侧）
Z_TUBE1 = 116.50     # 大臂管轴：与电机1 轴线距 116.50（图纸），与电机2 轴线相交
Z2_AXIS = 116.50     # 电机2 轴线 z
Z3_AXIS = 116.50 - 79.20   # 37.3 电机3 轴线 z：两管轴线距 79.2（=116.5-79.2），L 型件跨 79.2
Z_TUBE2 = 0.0        # 小臂管轴 z（穿入电机3，轴线相交）

J_LIMITS = {"j1": (-165, 165), "j2": (-150, 150), "j3": (-150, 150),
            "j4": (-180, 180), "j5": (-120, 120), "j6": (-180, 180)}

TRAIL_MAX_POINTS = 900
TRAIL_COLOR = "0xff00ff"

T3D = {"scene_bg": "0x050510", "scene_fog": "0x050510", "floor": "0x1a1a2e",
       "grid": "0x00ffc8", "grid_sub": "0x1a3a3a"}

HTML_3D = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{ margin: 0; overflow: hidden; background: #050510; }}
  #info {{
    position: absolute; top: 6px; left: 6px;
    color: #00ffc8; font-family: monospace; font-size: 11px;
    background: rgba(0,0,0,0.5); padding: 6px 10px; border-radius: 4px;
    border: 1px solid rgba(0,255,200,0.15); pointer-events: none;
  }}
</style>
</head>
<body>
<div id="info">左键旋转 | 滚轮缩放 | 右键平移</div>
<script src="three.min.js"></script>
<script>
const scene = new THREE.Scene();
scene.background = new THREE.Color({T3D['scene_bg']});
scene.fog = new THREE.Fog({T3D['scene_fog']}, 4000, 24000);

const camera = new THREE.PerspectiveCamera(45, window.innerWidth/window.innerHeight, 10, 20000);
camera.position.set(2500, 2200, 2500);

const renderer = new THREE.WebGLRenderer({{ antialias: true }});
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
document.body.appendChild(renderer.domElement);

scene.add(new THREE.AmbientLight(0x909090, 1.5));
scene.add(new THREE.HemisphereLight(0x8899aa, 0x1a2030, 0.9));
const dl = new THREE.DirectionalLight(0xffffff, 2.4);
dl.position.set(1500, 5000, 1500); dl.castShadow = true;
dl.shadow.mapSize.set(2048, 2048);
scene.add(dl);
const pl = new THREE.PointLight(0x00ffc8, 0.5, 6000);
pl.position.set(0, 4000, 0);
scene.add(pl);

// ==================== 材质 ====================
const matFloor = new THREE.MeshStandardMaterial({{ color: {T3D['floor']}, roughness: 0.9 }});
const matBody   = new THREE.MeshStandardMaterial({{ color: 0x646c78, roughness: 0.4, metalness: 0.7 }});
const matDark   = new THREE.MeshStandardMaterial({{ color: 0x2a2e35, roughness: 0.5,  metalness: 0.6 }});
const matSilver = new THREE.MeshStandardMaterial({{ color: 0xb8bfc7, roughness: 0.2,  metalness: 0.95 }});
const matRed    = new THREE.MeshStandardMaterial({{ color: 0xd21f3c, roughness: 0.35, metalness: 0.4,
                                                     emissive: 0x7a1020, emissiveIntensity: 0.9 }});
function makeCarbonTexture(repeatX) {{
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d');
  g.fillStyle = '#1d2127'; g.fillRect(0, 0, 128, 128);
  const s = 16;
  for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {{
    const odd = (x + y) % 2 === 1;
    const grad = odd ? g.createLinearGradient(x*s, y*s, x*s+s, y*s+s)
                     : g.createLinearGradient(x*s+s, y*s, x*s, y*s+s);
    grad.addColorStop(0,   '#454c56');
    grad.addColorStop(0.5, '#14161a');
    grad.addColorStop(1,   '#333a42');
    g.fillStyle = grad; g.fillRect(x*s, y*s, s, s);
  }}
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(repeatX || 4, 1);
  return t;
}}
const matCarbon = new THREE.MeshStandardMaterial({{ map: makeCarbonTexture(6),
                                                    color: 0xcccccc, roughness: 0.35, metalness: 0.55 }});
const matMotor   = new THREE.MeshStandardMaterial({{ color: 0x4a515b, roughness: 0.35, metalness: 0.8 }});
const matIndicator = new THREE.MeshStandardMaterial({{
  color: 0xff00ff, emissive: 0xff00ff, emissiveIntensity: 1.0, transparent: true, opacity: 0.9
}});

const floor = new THREE.Mesh(new THREE.PlaneGeometry(16000, 16000), matFloor);
floor.rotation.x = -Math.PI/2; floor.receiveShadow = true; scene.add(floor);
const grid = new THREE.GridHelper(16000, 80, {T3D['grid']}, {T3D['grid_sub']});
grid.position.y = 0.5; scene.add(grid);

// ==================== 尺寸常量（视觉单位）====================
const VISUAL_SCALE = {VISUAL_SCALE};
const BASE_PLATE = {BASE_PLATE}, BASE_PLATE_D = {BASE_PLATE_D}, BASE_PLATE_T = {BASE_PLATE_T};
const FOOT_SP = {FOOT_SP};
const LEG_LEN = {LEG_LEN}, LEG_R = {LEG_R}, LEG_Y = {LEG_Y}, PAD_H = {PAD_H};
const FLANGE_PLATE = {FLANGE_PLATE}, FLANGE_T = {FLANGE_T}, FLANGE_HOLE = {FLANGE_HOLE};
const PEDESTAL_W = {PEDESTAL_W}, PEDESTAL_TOP = {PEDESTAL_TOP}, J1_HOUSING_D = {J1_HOUSING_D};
const J1_AXIS_H = {J1_AXIS_H}, J2_AXIS_H = {J2_AXIS_H};
const L1 = {L1}, L2 = {L2}, L3 = {L3}, L4 = {L4};
const R_JOINT = {R_JOINT}, R_TUBE = {R_TUBE}, TUBE2_R = {TUBE2_R};
const MOTOR1_R = {MOTOR1_R}, MOTOR1_L = {MOTOR1_L};
const MOTOR2_R = {MOTOR2_R}, MOTOR2_L = {MOTOR2_L};
const MOTOR3_R = {MOTOR3_R}, MOTOR3_L = {MOTOR3_L};
const MOTOR4_R = {MOTOR4_R}, MOTOR4_L = {MOTOR4_L};
const J5_R = {J5_R}, J5_H = {J5_H}, J6_R = {J6_R}, J6_L = {J6_L};
const SHAFT4_R = {SHAFT4_R}, SHAFT5_R = {SHAFT5_R};
const Z2_AXIS = {Z2_AXIS} * VISUAL_SCALE, Z3_AXIS = {Z3_AXIS} * VISUAL_SCALE;

const PLATE_TOP = LEG_Y + LEG_R - 10;

// ==================== 底座（全部固定）====================
const baseGroup = new THREE.Group(); scene.add(baseGroup);
[[1,1],[1,-1],[-1,1],[-1,-1]].forEach(([sx,sz])=>{{
  const dir = new THREE.Vector3(sx, 0, sz).normalize();
  const leg = new THREE.Mesh(new THREE.CylinderGeometry(LEG_R, LEG_R, LEG_LEN, 24), matBody);
  leg.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0), dir);
  const start = new THREE.Vector3(sx*FOOT_SP*0.40, 0, sz*FOOT_SP*0.40);
  leg.position.copy(start.clone().add(dir.clone().multiplyScalar(LEG_LEN/2)));
  leg.position.y = LEG_Y;
  leg.castShadow = true; baseGroup.add(leg);
  const capPos = start.clone().add(dir.clone().multiplyScalar(LEG_LEN));
  const cap = new THREE.Mesh(new THREE.CylinderGeometry(LEG_R*0.8, LEG_R*0.8, 12, 24), matSilver);
  cap.quaternion.copy(leg.quaternion);
  cap.position.set(capPos.x, LEG_Y, capPos.z);
  baseGroup.add(cap);
  const pad = new THREE.Mesh(new THREE.CylinderGeometry(LEG_R*1.6, LEG_R*1.8, PAD_H, 24), matDark);
  pad.position.set(capPos.x, PAD_H/2, capPos.z);
  pad.castShadow = true; baseGroup.add(pad);
}});
const basePlate = new THREE.Mesh(new THREE.BoxGeometry(BASE_PLATE, BASE_PLATE_T, BASE_PLATE_D), matDark);
basePlate.position.y = PLATE_TOP - BASE_PLATE_T/2;
basePlate.castShadow = true; basePlate.receiveShadow = true; baseGroup.add(basePlate);
[[-1,-1],[1,-1],[-1,1],[1,1]].forEach(([sx,sz])=>{{
  const bolt = new THREE.Mesh(new THREE.CylinderGeometry(9, 9, BASE_PLATE_T+8, 12), matSilver);
  bolt.position.set(sx*(FOOT_SP/2), PLATE_TOP - BASE_PLATE_T/2, sz*(FOOT_SP/2));
  baseGroup.add(bolt);
}});
const flangePlate = new THREE.Mesh(new THREE.BoxGeometry(FLANGE_PLATE, FLANGE_T, FLANGE_PLATE), matBody);
flangePlate.position.y = PLATE_TOP + FLANGE_T/2;
flangePlate.castShadow = true; baseGroup.add(flangePlate);
[[-1,-1],[1,-1],[-1,1],[1,1]].forEach(([sx,sz])=>{{
  const hole = new THREE.Mesh(new THREE.CylinderGeometry(7, 7, FLANGE_T+4, 12), matDark);
  hole.position.set(sx*FLANGE_HOLE, PLATE_TOP + FLANGE_T/2, sz*FLANGE_HOLE);
  baseGroup.add(hole);
}});
const pedestal = new THREE.Mesh(new THREE.BoxGeometry(PEDESTAL_W, PEDESTAL_TOP - PLATE_TOP - FLANGE_T, PEDESTAL_W), matBody);
pedestal.position.y = PLATE_TOP + FLANGE_T + (PEDESTAL_TOP - PLATE_TOP - FLANGE_T)/2;
pedestal.castShadow = true; pedestal.receiveShadow = true; baseGroup.add(pedestal);
const seat = new THREE.Mesh(new THREE.CylinderGeometry(MOTOR1_R*1.15, MOTOR1_R*1.25, 8, 36), matDark);
seat.position.y = PEDESTAL_TOP + 4;
seat.castShadow = true; baseGroup.add(seat);

// ---- 构件工具 ----
function createMotorZ(r, l) {{   // 电机本体，轴线 Z
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.CylinderGeometry(r, r, l, 48), matMotor);
  body.rotation.x = Math.PI/2; body.castShadow = true; g.add(body);
  [-1, 1].forEach(s => {{
    const cap = new THREE.Mesh(new THREE.CylinderGeometry(r*0.98, r*0.98, l*0.1, 36), matSilver);
    cap.rotation.x = Math.PI/2; cap.position.z = s*(l/2 - l*0.05); g.add(cap);
  }});
  const ring = new THREE.Mesh(new THREE.CylinderGeometry(r*1.05, r*1.05, l*0.12, 36), matRed);
  ring.rotation.x = Math.PI/2; ring.position.z = l*0.18; g.add(ring);
  return g;
}}
function createMotorY(r, h) {{   // 电机本体，轴线 Y（立式）
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, 36), matMotor);
  body.castShadow = true; g.add(body);
  [-1, 1].forEach(s => {{
    const cap = new THREE.Mesh(new THREE.CylinderGeometry(r*0.97, r*0.97, h*0.12, 36), matSilver);
    cap.position.y = s*(h/2 - h*0.06); g.add(cap);
  }});
  const ring = new THREE.Mesh(new THREE.TorusGeometry(r + 2, 4, 8, 40), matRed);
  ring.rotation.x = Math.PI/2; ring.position.y = -h*0.18; g.add(ring);
  return g;
}}
function createCollarX(r, x, y, z) {{  // 管穿入电机处的银卡环（轴线 X）
  const c = new THREE.Mesh(new THREE.CylinderGeometry(r + 5, r + 5, 8, 28), matSilver);
  c.rotation.z = Math.PI/2; c.position.set(x, y || 0, z || 0);
  c.castShadow = true;
  return c;
}}
function createTubeX(x0, x1, r, y, z) {{  // 碳纤维管（轴线 X）
  const len = x1 - x0;
  const tube = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, 40), matCarbon);
  tube.rotation.z = Math.PI/2;
  tube.position.set((x0+x1)/2, y || 0, z || 0);
  tube.castShadow = true;
  return tube;
}}

// ==================== J1（轴线 Y @(0,120.5,0)，与立柱同轴；电机1 朝下，随 J1 转）====================
const j1Group = new THREE.Group();
j1Group.position.set(0, J1_AXIS_H, 0);
baseGroup.add(j1Group);
const j1Ring = new THREE.Mesh(new THREE.CylinderGeometry(MOTOR1_R*1.15, MOTOR1_R*1.15, 9, 36), matRed);
j1Ring.position.y = PEDESTAL_TOP + 8 - J1_AXIS_H;
j1Group.add(j1Ring);
const motor1 = new THREE.Mesh(new THREE.CylinderGeometry(MOTOR1_R, MOTOR1_R, MOTOR1_L, 28), matDark);
motor1.castShadow = true; j1Group.add(motor1);
const m1cap = new THREE.Mesh(new THREE.CylinderGeometry(MOTOR1_R*0.85, MOTOR1_R*0.85, 5, 28), matSilver);
m1cap.position.y = -MOTOR1_L/2 - 2;
j1Group.add(m1cap);
const m1ring = new THREE.Mesh(new THREE.CylinderGeometry(MOTOR1_R*1.08, MOTOR1_R*1.08, 8, 28), matRed);
m1ring.position.y = -MOTOR1_L/2 + 8;
j1Group.add(m1ring);
// 电机1 -> 电机2 固定支架（电机2 轴端固定在电机1 圆柱侧面：z 36 -> 85.5）
const brLen = (85.5 - 40) * VISUAL_SCALE;
const bracket = new THREE.Mesh(new THREE.CylinderGeometry(16*VISUAL_SCALE, 16*VISUAL_SCALE, brLen, 20), matSilver);
bracket.rotation.x = Math.PI/2;
bracket.position.set(0, J2_AXIS_H - J1_AXIS_H, (40 + 85.5)/2 * VISUAL_SCALE);
bracket.castShadow = true; j1Group.add(bracket);

// ==================== J2（轴线 Z @(0,132.5,116.5)；电机2 本体旋转，带大臂管）====================
const j2Group = new THREE.Group();
j2Group.position.set(0, J2_AXIS_H - J1_AXIS_H, Z2_AXIS);
j1Group.add(j2Group);
j2Group.add(createMotorZ(MOTOR2_R, MOTOR2_L));
// 大臂管 L1=203.50：从 J2 轴线（x=0）到 J3 轴线（x=L1），轴线与电机2 轴线相交
j2Group.add(createTubeX(0, L1 - 30*VISUAL_SCALE, R_TUBE, 0, 0));   // 端部接入 L 型圆柱拐角
j2Group.add(createCollarX(R_TUBE, MOTOR2_R - 6, 0, 0));
(function() {{
  const pts = [
    new THREE.Vector3(L1*0.06, -10, R_TUBE + 8),
    new THREE.Vector3(L1*0.4, -R_TUBE*1.6, R_TUBE + 14),
    new THREE.Vector3(L1*0.72, -R_TUBE*1.6, R_TUBE + 14),
    new THREE.Vector3((L1 - 30*VISUAL_SCALE)*0.94, -10, R_TUBE + 8)
  ];
  const cable = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 32, 5, 8, false), matDark);
  j2Group.add(cable);
}})();
// ---- L 型圆柱拐角（J3 固定侧）：与大臂管等径 Ø44 的 90° 弯管 ----
// 中心线路径：+X 向顺延大臂管 -> 90° 弯（R18） -> -Z 向插入电机3 端面（z=-48.2*S）
const j3zLocal = Z3_AXIS - Z2_AXIS;   // = -79.2*S
(function() {{
  const s = VISUAL_SCALE, R = 22*s, BEND = 34*s;   // 弯半径必须 > 管半径，否则圆环自交
  // 90° 弯：四分之一圆环，下端与管1 端部等径相切（管1 即 X 向直管段，无需另接）
  const bend = new THREE.Mesh(new THREE.TorusGeometry(BEND, R, 20, 48, Math.PI/2), matBody);
  bend.rotation.x = -Math.PI/2;
  bend.position.set(L1 - 30*s, 0, BEND);
  bend.castShadow = true; j2Group.add(bend);
  // Z 向直管段：从弯的上切点下行，插入电机3 +Z 端面（z=-48.2*s）
  const legZ = new THREE.Mesh(new THREE.CylinderGeometry(R, R, 84*s, 40), matBody);
  legZ.rotation.x = Math.PI/2;
  legZ.position.set(L1 + 4*s, 0, -8*s);
  legZ.castShadow = true; j2Group.add(legZ);
}})();

// ==================== J3（轴线 Z @(L1,132.5,0)；电机3 本体旋转，带小臂管）====================
const j3Group = new THREE.Group();
j3Group.position.set(L1, 0, j3zLocal);
j2Group.add(j3Group);
j3Group.add(createMotorZ(MOTOR3_R, MOTOR3_L));
// 小臂管 L2=173：从 J3 轴线（x=0，穿入电机3）到 J4 轴线（x=L2），轴线与电机3 轴线相交
// 与大臂管（z 错 116.5）不同轴
j3Group.add(createTubeX(0, L2, TUBE2_R, 0, 0));
j3Group.add(createCollarX(TUBE2_R, MOTOR3_R - 6, 0, 0));

// ==================== J4（轴线 Z；Ø60；输出轴朝 +Z，反向180°到另一侧）====================
const j4Group = new THREE.Group();
j4Group.position.set(L2, 0, 0);
j3Group.add(j4Group);
j4Group.add(createMotorZ(MOTOR4_R, MOTOR4_L));
// J4 输出轴（+Z 端，反向180°到另一侧，伸入电机5 侧面）
const shaft4 = new THREE.Mesh(new THREE.CylinderGeometry(SHAFT4_R, SHAFT4_R, 29*VISUAL_SCALE, 20), matSilver);
shaft4.rotation.x = Math.PI/2;
shaft4.position.set(0, 0, 40.5*VISUAL_SCALE);
shaft4.castShadow = true; j4Group.add(shaft4);
// ---- J5 定子（侧面固定在 J4 输出轴上）：J5 轴位于 j4 系 (0,0,+79.2) ----
const motor5 = createMotorY(J5_R, J5_H);
motor5.position.set(0, 0, L3);
j4Group.add(motor5);
// 卡箍/连接块：电机4 输出轴 -> 电机5 侧面
const band5 = new THREE.Mesh(new THREE.CylinderGeometry(J5_R + 3, J5_R + 3, 18*VISUAL_SCALE, 36), matDark);
band5.position.set(0, 0, L3); band5.castShadow = true; j4Group.add(band5);
// （电机4 -> 电机5：输出轴直接圆柱插入电机5 侧面，无连接块）

// ==================== J5（轴线 Y @(0,0,+79.2) j4 系；输出朝下(-Y)，转子带电机6）====================
const j5Group = new THREE.Group();
j5Group.position.set(0, 0, L3);
j4Group.add(j5Group);
// J5 输出轴（-Y 端，伸入电机6 侧面）
const shaft5 = new THREE.Mesh(new THREE.CylinderGeometry(SHAFT5_R, SHAFT5_R, 28*VISUAL_SCALE, 20), matSilver);
shaft5.position.set(0, -45*VISUAL_SCALE, 0);
shaft5.castShadow = true; j5Group.add(shaft5);
// ---- J6 定子（侧面固定在 J5 输出轴上）：J6 轴位于 j5 系 (0,-79.2,0) ----
// 电机6 本体居中于 J5 轴线（J5 轴穿过电机6 中心），x ∈ [-31, +31]
const j6Body = new THREE.Mesh(new THREE.CylinderGeometry(J6_R, J6_R, J6_L, 36), matBody);
j6Body.rotation.z = Math.PI/2; j6Body.position.set(0, -L4, 0);
j6Body.castShadow = true; j5Group.add(j6Body);
const band6 = new THREE.Mesh(new THREE.CylinderGeometry(J6_R + 3, J6_R + 3, 18*VISUAL_SCALE, 36), matDark);
band6.rotation.z = Math.PI/2; band6.position.set(0, -L4, 0);
band6.castShadow = true; j5Group.add(band6);
// （电机5 -> 电机6：输出轴直接圆柱插入电机6 侧面，无连接块）

// ==================== J6（轴线 X @(0,-79.2,0) j5 系；Ø60 法兰面，随 J6 绕 X 转）====================
const j6Group = new THREE.Group();
j6Group.position.set(0, -L4, 0);
j5Group.add(j6Group);
const j6Ring = new THREE.Mesh(new THREE.CylinderGeometry(J6_R + 2, J6_R + 2, 5, 36), matRed);
j6Ring.rotation.z = Math.PI/2; j6Ring.position.x = J6_L/2 - 4; j6Group.add(j6Ring);
const j6Face = new THREE.Mesh(new THREE.CylinderGeometry(J6_R*0.95, J6_R*0.95, 5, 36), matSilver);
j6Face.rotation.z = Math.PI/2; j6Face.position.x = J6_L/2 + 1; j6Group.add(j6Face);
[[-1,-1],[1,-1],[-1,1],[1,1]].forEach(([sy,sz])=>{{
  const hole = new THREE.Mesh(new THREE.CylinderGeometry(3.5, 3.5, 7, 10), matDark);
  hole.rotation.z = Math.PI/2;
  hole.position.set(J6_L/2 + 1, sy*J6_R*0.55, sz*J6_R*0.55);
  j6Group.add(hole);
}});
// TCP
const indicator = new THREE.Mesh(new THREE.SphereGeometry(16, 16, 16), matIndicator);
indicator.position.set(J6_L/2 + 26, 0, 0);
j6Group.add(indicator);
const endLight = new THREE.PointLight(0xff00ff, 1.5, 500);
endLight.position.set(J6_L/2 + 26, 0, 0);
j6Group.add(endLight);
const endAxes = new THREE.AxesHelper(80);
endAxes.position.set(J6_L/2 + 26, 0, 0);
j6Group.add(endAxes);

// ==================== 轨迹（预分配缓冲）====================
const trailPoints = [];
const trailMat = new THREE.LineBasicMaterial({{ color: {TRAIL_COLOR}, transparent: true, opacity: 0.85 }});
const trailPos = new Float32Array({TRAIL_MAX_POINTS} * 3);
const trailGeo = new THREE.BufferGeometry();
trailGeo.setAttribute("position", new THREE.BufferAttribute(trailPos, 3));
trailGeo.setDrawRange(0, 0);
const trailLine = new THREE.Line(trailGeo, trailMat);
trailLine.frustumCulled = false;
scene.add(trailLine);
function updateTrail(wx, wy, wz) {{
  trailPoints.push(new THREE.Vector3(wx, wy, wz));
  if (trailPoints.length > {TRAIL_MAX_POINTS}) trailPoints.shift();
  if (trailPoints.length < 2) {{ trailGeo.setDrawRange(0, 0); return; }}
  for (let i = 0; i < trailPoints.length; i++) {{
    trailPos[i*3]   = trailPoints[i].x;
    trailPos[i*3+1] = trailPoints[i].y;
    trailPos[i*3+2] = trailPoints[i].z;
  }}
  trailGeo.attributes.position.needsUpdate = true;
  trailGeo.setDrawRange(0, trailPoints.length);
}}
function clearTrail() {{ trailPoints.length = 0; trailGeo.setDrawRange(0, 0); }}
window.clearTrail = clearTrail;

// ==================== 相机控制 ====================
let isDrag=false, prevX=0, prevY=0;
let camTheta=Math.PI/4, camPhi=Math.PI/2.6, camR=5600;
let target=new THREE.Vector3(700, 800, 0);
function updateCam() {{
  camera.position.x = target.x + camR*Math.sin(camPhi)*Math.sin(camTheta);
  camera.position.y = target.y + camR*Math.cos(camPhi);
  camera.position.z = target.z + camR*Math.sin(camPhi)*Math.cos(camTheta);
  camera.lookAt(target);
}}
updateCam();
const cvs = renderer.domElement;
cvs.addEventListener('mousedown', e=>{{isDrag=true;prevX=e.clientX;prevY=e.clientY;}});
window.addEventListener('mouseup',()=>isDrag=false);
cvs.addEventListener('mousemove',e=>{{
  if(!isDrag)return;
  camTheta-=(e.clientX-prevX)*0.005;
  camPhi=Math.max(0.15,Math.min(Math.PI-0.15,camPhi+(e.clientY-prevY)*0.005));
  prevX=e.clientX;prevY=e.clientY;updateCam();
}});
cvs.addEventListener('wheel',e=>{{camR=Math.max(1200,Math.min(22000,camR+e.deltaY*0.8));updateCam();}});

// ==================== 关节角控制（度） ====================
// 轴向：J1:Y | J2:Z | J3:Z | J4:Z | J5:Y(竖直) | J6:X
const J_LIMITS = {{
  j1: [{J_LIMITS['j1'][0]}, {J_LIMITS['j1'][1]}],
  j2: [{J_LIMITS['j2'][0]}, {J_LIMITS['j2'][1]}],
  j3: [{J_LIMITS['j3'][0]}, {J_LIMITS['j3'][1]}],
  j4: [{J_LIMITS['j4'][0]}, {J_LIMITS['j4'][1]}],
  j5: [{J_LIMITS['j5'][0]}, {J_LIMITS['j5'][1]}],
  j6: [{J_LIMITS['j6'][0]}, {J_LIMITS['j6'][1]}],
}};
function clampJoint(v, lim) {{ return Math.max(lim[0], Math.min(lim[1], v)); }}
let curAngles={{j1:0,j2:0,j3:0,j4:0,j5:0,j6:0}};
let tgtAngles={{j1:0,j2:0,j3:0,j4:0,j5:0,j6:0}};

// 由外部调用：updatePosition(a1..a6)，单位为度
window.updatePosition = function(a1,a2,a3,a4,a5,a6) {{
  tgtAngles.j1 = clampJoint(a1 || 0, J_LIMITS.j1);
  tgtAngles.j2 = clampJoint(a2 || 0, J_LIMITS.j2);
  tgtAngles.j3 = clampJoint(a3 || 0, J_LIMITS.j3);
  tgtAngles.j4 = clampJoint(a4 || 0, J_LIMITS.j4);
  tgtAngles.j5 = clampJoint(a5 || 0, J_LIMITS.j5);
  tgtAngles.j6 = clampJoint(a6 || 0, J_LIMITS.j6);
}};

const tcpWorld = new THREE.Vector3();
function animate() {{
  requestAnimationFrame(animate);
  const f = 0.12;
  curAngles.j1 += (tgtAngles.j1 - curAngles.j1) * f;
  curAngles.j2 += (tgtAngles.j2 - curAngles.j2) * f;
  curAngles.j3 += (tgtAngles.j3 - curAngles.j3) * f;
  curAngles.j4 += (tgtAngles.j4 - curAngles.j4) * f;
  curAngles.j5 += (tgtAngles.j5 - curAngles.j5) * f;
  curAngles.j6 += (tgtAngles.j6 - curAngles.j6) * f;

  const d2r = Math.PI / 180;
  j1Group.rotation.y = curAngles.j1 * d2r;
  j2Group.rotation.z = curAngles.j2 * d2r;
  j3Group.rotation.z = curAngles.j3 * d2r;
  j4Group.rotation.z = curAngles.j4 * d2r;
  j5Group.rotation.y = curAngles.j5 * d2r;
  j6Group.rotation.x = curAngles.j6 * d2r;

  indicator.updateWorldMatrix(true, false);
  tcpWorld.setFromMatrixPosition(indicator.matrixWorld);
  // 恒定亮度：呼吸式脉动会让周边表面明暗闪烁（"曝光感"）
  indicator.material.emissiveIntensity = 0.9;
  endLight.intensity = 1.2;
  updateTrail(tcpWorld.x, tcpWorld.y, tcpWorld.z);
  renderer.render(scene, camera);
}}
animate();
window.addEventListener('resize', () => {{
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
}});
</script>
</body>
</html>
"""



import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QSlider, QLabel
from PySide6.QtCore import Qt, QTimer, QUrl

class Demo(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("6轴机器人 3D 可视化")
        central = QWidget(); self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        self._online_mode = False   # 在线模式：仅在点击「在线 🔄」后指示运行行，再点退出
        self.modbus = ModbusClient()
        self.bridge = SignalBridge()
        self.tcp_worker = None
        self._last_plc_pos = (0.0, 0.0, 0.0)
        self.view = QWebEngineView()
        # three.min.js 需与本文件同目录（沿用原项目的 three.min.js）
        self.view.setHtml(HTML_3D, baseUrl=QUrl.fromLocalFile(__file__))
        layout.addWidget(self.view, stretch=1)

        self.labels = []
        self.sliders = []
        # limits = [J_LIMITS[f"j{i}"] for i in range(1, 7)]
        # for i, (lo, hi) in enumerate(limits):
        #     row = QWidget(); h = QVBoxLayout(row); h.setContentsMargins(0, 0, 0, 0)
        #     lbl = QLabel(f"J{i+1}: 0°"); h.addWidget(lbl); self.labels.append(lbl)
        #     s = QSlider(Qt.Orientation.Horizontal)
        #     s.setRange(lo, hi); s.setValue(0)
        #     s.valueChanged.connect(self.on_slider)
        #     h.addWidget(s); self.sliders.append(s)
        #     layout.addWidget(row)

        self._act_connect = self._make_action("连接 PLC", self._on_toolbar_connect)
        self._act_connect.setCheckable(True)    
        self._build_statusbar()
        self._build_toolbar()
        self._build_menubar()
        # self.timer = QTimer(self)
        # self.timer.timeout.connect(self.demo_motion)
        # self.t = 0
        # self.timer.start(30)

    def on_slider(self, _):
        vals = [s.value() for s in self.sliders]
        for lbl, v in zip(self.labels, vals):
            lbl.setText(f"{lbl.text().split(':')[0]}: {v}°")
        self.view.page().runJavaScript(
            f"updatePosition({vals[0]},{vals[1]},{vals[2]},{vals[3]},{vals[4]},{vals[5]})")

    def demo_motion(self):
        self.t += 0.02
        import math
        a1 = 60 * math.sin(self.t)
        a2 = 40 * math.sin(self.t * 1.3) + 90
        a3 = 50 * math.sin(self.t * 0.7 + 1)
        a4 = 70 * math.sin(self.t * 1.7)
        a5 = 30 * math.sin(self.t * 1.1 + 2)
        a6 = 90 * math.sin(self.t * 2.3)
        self.view.page().runJavaScript(
            f"updatePosition({a1:.1f},{a2:.1f},{a3:.1f},{a4:.1f},{a5:.1f},{a6:.1f})")

    def _build_statusbar(self):
        self.status = self.statusBar()
        self.status.showMessage("就绪 | 未连接 PLC | 模拟器: 空闲")
    def _build_menubar(self):
        mb = self.menuBar()
        
      
        cm = mb.addMenu("PLC(&P)")
        
        cm.addAction(self._make_action("连接/断开 PLC", self._on_toolbar_connect))
        cm.addSeparator()

    def _build_toolbar(self):
        tb = self.addToolBar("工具")
        self._act_connect = self._make_action("连接 PLC", self._on_toolbar_connect)
        self._act_connect.setCheckable(True)
        tb.addAction(self._act_connect)
        # 在线模式按钮：点击进入在线监视（指示运行行），再次点击退出在线模式
        self._act_online = self._make_action("在线 🔄", self._on_online_toggled)
        self._act_online.setCheckable(True)
        tb.addAction(self._act_online)


    def _make_action(self, text, slot, shortcut=None):
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(shortcut)
        act.triggered.connect(slot)
        return act
    
    def _on_toolbar_connect(self):
        if self._act_connect.isChecked():
            host, port, unit = "192.168.1.88", 502, 1
            if self.modbus.connect(host, port, unit):
                self.status.showMessage(f"已连接 {host}:{port} 站号{unit}")
                # self.log_msg(f"Modbus 连接成功: {host}:{port}")
                self._act_connect.setText("断开 PLC")
                cfg = {"interval": 200, "use_float32": True}
                self.tcp_worker = TcpPositionWorker(self.bridge, self.modbus, cfg)
                self.bridge.position_updated.connect(self._on_position)
                # self.bridge.robot_sys_status_ipc_updated.connect(self._update_ui)
                # self.bridge.log_message.connect(self.log_msg)
                self.tcp_worker.start()
            else:
                self._act_connect.setChecked(False)
                QMessageBox.critical(self, "连接失败", f"无法连接到 {host}:{port}")
                # self.log_msg("Modbus 连接失败")
        else:
            if self._online_mode:
                self._exit_online_mode()
            self._act_online.setChecked(False)
            self._act_online.setText("在线 🔄")
            if self.tcp_worker:
                self.tcp_worker.stop()
                self.tcp_worker = None
            self.modbus.disconnect()
            self.status.showMessage("未连接 PLC")
            # self.log_msg("Modbus 已断开")
            self._act_connect.setText("连接 PLC")
    
    def _on_position(self, x: float, y: float, z: float,a: float,b: float,c: float):
        self._last_plc_pos = (x, y, z,a,b,c)
        # self.lbl_tcp_pos.setText(f"TCP: X={x:.1f} Y={y:.1f} Z={z:.1f}")
        # js = f"updatePosition({x:.2f}, {y:.2f}, {z:.2f})"
        # self.webview_3d.page().runJavaScript(js)

        self.view.page().runJavaScript(
                        f"updatePosition({x:.1f},{y:.1f},{z:.1f},{a:.1f},{b:.1f},{c:.1f})")
        # print(self._last_plc_pos)

    def _on_online_toggled(self, checked: bool):
        """在线模式开关：点击 -> 进入在线监视并指示运行行；再次点击 -> 退出"""
        pass
    # app = QApplication(sys.argv)
    # w = Demo(); w.resize(1200, 900); w.show()
    # sys.exit(app.exec())




def main() -> int:
  app = QApplication(sys.argv)

  app.setStyle("Fusion")
  palette = app.palette()
  palette.setColor(palette.ColorRole.Window, QColor("#F0F0F0"))
  palette.setColor(palette.ColorRole.WindowText, QColor("#2B2B2B"))
  palette.setColor(palette.ColorRole.Base, QColor("#FFFFFF"))
  palette.setColor(palette.ColorRole.AlternateBase, QColor("#F5F5F5"))
  palette.setColor(palette.ColorRole.ToolTipBase, QColor("#F5F5F5"))
  palette.setColor(palette.ColorRole.ToolTipText, QColor("#2B2B2B"))
  palette.setColor(palette.ColorRole.Text, QColor("#2B2B2B"))
  palette.setColor(palette.ColorRole.Button, QColor("#F5F5F5"))
  palette.setColor(palette.ColorRole.ButtonText, QColor("#2B2B2B"))
  palette.setColor(palette.ColorRole.BrightText, QColor("#FF0000"))
  palette.setColor(palette.ColorRole.Highlight, QColor("#3875D6"))
  palette.setColor(palette.ColorRole.HighlightedText, QColor("#FFFFFF"))
  # app.setApplicationName("Safety Car Config - Design")
  # app.setApplicationDisplayName("组态 · 设计模式")

  window = Demo()
  window.show()
  return app.exec()
