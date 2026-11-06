from PySide6.QtWebEngineWidgets import QWebEngineView

# ==================== 3D 可视化配置 ====================
# 实际设备行程范围
X_MIN_3D, X_MAX_3D = -1071, 34
Y_MIN_3D, Y_MAX_3D = -13, 716
Z_MIN_3D, Z_MAX_3D = -4043, 15

# 视觉缩放系数（统一比例 0.5，保持真实比例）
X_RANGE = max(abs(X_MIN_3D), abs(X_MAX_3D))   # 1071
Y_RANGE = max(abs(Y_MIN_3D), abs(Y_MAX_3D))   # 716
Z_RANGE = max(abs(Z_MIN_3D), abs(Z_MAX_3D))   # 4043

VISUAL_SCALE_X = int(X_RANGE * 0.5)   # 535
VISUAL_SCALE_Y = int(Y_RANGE * 0.5)   # 358
VISUAL_SCALE_Z = int(Z_RANGE * 0.5)   # 2021

TRAIL_MAX_POINTS = 900
TRAIL_COLOR = "0xff00ff"

# 暗色主题配色（与示教器暗色主题统一）
T3D = {
    "scene_bg": "0x050510", "scene_fog": "0x050510", "floor": "0x1a1a2e",
    "grid": "0x00ffc8", "grid_sub": "0x1a3a3a",
}

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
scene.fog = new THREE.Fog({T3D['scene_fog']}, 2000, 12000);

const camera = new THREE.PerspectiveCamera(45, window.innerWidth/window.innerHeight, 1, 15000);
camera.position.set(3000, 3500, 3000);

const renderer = new THREE.WebGLRenderer({{ antialias: true }});
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
document.body.appendChild(renderer.domElement);

scene.add(new THREE.AmbientLight(0x404040, 1.5));
const dl = new THREE.DirectionalLight(0xffffff, 2);
dl.position.set(800, 4000, 800); dl.castShadow = true;
dl.shadow.mapSize.set(2048, 2048);
scene.add(dl);
const pl = new THREE.PointLight(0x00ffc8, 0.6, 3000);
pl.position.set(0, 2500, 0);
scene.add(pl);

const matFrame = new THREE.MeshStandardMaterial({{ color: 0x5a6a7a, roughness: 0.3, metalness: 0.7 }});
const matRail = new THREE.MeshStandardMaterial({{ color: 0x8899aa, roughness: 0.2, metalness: 0.85 }});
const matSlideX = new THREE.MeshStandardMaterial({{ color: 0xe17055, roughness: 0.3, metalness: 0.6 }});
const matSlideY = new THREE.MeshStandardMaterial({{ color: 0x00b894, roughness: 0.3, metalness: 0.6 }});
const matSlideZ = new THREE.MeshStandardMaterial({{ color: 0x0984e3, roughness: 0.3, metalness: 0.6 }});
const matFloor = new THREE.MeshStandardMaterial({{ color: {T3D['floor']}, roughness: 0.9 }});
const matSucker = new THREE.MeshStandardMaterial({{ color: 0xfdcb6e, emissive: 0xffaa00, emissiveIntensity: 0.5 }});
const matIndicator = new THREE.MeshStandardMaterial({{
  color: 0xff00ff, emissive: 0xff00ff, emissiveIntensity: 1.0,
  transparent: true, opacity: 0.9
}});

const floor = new THREE.Mesh(new THREE.PlaneGeometry(8000, 8000), matFloor);
floor.rotation.x = -Math.PI/2; floor.receiveShadow = true; scene.add(floor);
const grid = new THREE.GridHelper(8000, 80, {T3D['grid']}, {T3D['grid_sub']});
grid.position.y = 0.5; scene.add(grid);

const LEG_H = 1800, LEG_W = 100, LEG_D = 150, LEG_X = 600;
function createLeg(xPos) {{
  const g = new THREE.Group();
  const leg = new THREE.Mesh(new THREE.BoxGeometry(LEG_W, LEG_H, LEG_D), matFrame);
  leg.position.set(0, LEG_H/2, 0); leg.castShadow = true; g.add(leg);
  const foot = new THREE.Mesh(new THREE.BoxGeometry(LEG_W+80, 40, LEG_D+80), matFrame);
  foot.position.set(0, 20, 0); g.add(foot);
  const top = new THREE.Mesh(new THREE.BoxGeometry(LEG_W+80, 40, LEG_D+80), matFrame);
  top.position.set(0, LEG_H-20, 0); g.add(top);
  g.position.x = xPos; return g;
}}
scene.add(createLeg(-LEG_X)); scene.add(createLeg(LEG_X));

const xBaseLen = 1600;
const xBase = new THREE.Mesh(new THREE.BoxGeometry(xBaseLen, 60, 150), matRail);
xBase.position.set(0, LEG_H, 0); xBase.castShadow = true; scene.add(xBase);

const sliderX = new THREE.Group(); scene.add(sliderX);
const xSlide = new THREE.Mesh(new THREE.BoxGeometry(180, 120, 170), matSlideX);
xSlide.position.set(0, LEG_H+90, 0); xSlide.castShadow = true; sliderX.add(xSlide);

const Y_BEAM_OFFSET_X = 40;
const Y_HEIGHT = LEG_H + 180;
const Y_BEAM_NEG_LEN = 80;
const Y_BEAM_POS_LEN = 800;
const Y_BEAM_TOTAL_LEN = Y_BEAM_NEG_LEN + Y_BEAM_POS_LEN;
const Y_BEAM_CENTER_Z = (Y_BEAM_POS_LEN - Y_BEAM_NEG_LEN) / 2;

const yBeamGroup = new THREE.Group();
yBeamGroup.position.set(Y_BEAM_OFFSET_X, Y_HEIGHT, 0);
sliderX.add(yBeamGroup);
const yBeam = new THREE.Mesh(new THREE.BoxGeometry(120, 70, Y_BEAM_TOTAL_LEN), matSlideY);
yBeam.position.set(0, 0, Y_BEAM_CENTER_Z); yBeam.castShadow = true; yBeamGroup.add(yBeam);

const sliderY = new THREE.Group();
sliderY.position.set(Y_BEAM_OFFSET_X, Y_HEIGHT, Y_BEAM_CENTER_Z);
sliderX.add(sliderY);
const ySlide = new THREE.Mesh(new THREE.BoxGeometry(140, 80, 120), matSlideY);
ySlide.castShadow = true; sliderY.add(ySlide);

const zSlideOffset = 100;
const zSlide = new THREE.Mesh(new THREE.BoxGeometry(100, 90, 100), matSlideZ);
zSlide.position.set(zSlideOffset, 0, 0); zSlide.castShadow = true; sliderY.add(zSlide);

const zColumnH = 2100;
const zColumnGroup = new THREE.Group();
zColumnGroup.position.set(zSlideOffset, 0, 0);
sliderY.add(zColumnGroup);
const zColumn = new THREE.Mesh(new THREE.BoxGeometry(80, zColumnH, 80), matFrame);
zColumn.castShadow = true; zColumnGroup.add(zColumn);

// ==================== 吸盘组件（朝向 Y+ / 世界 Z+）====================
const suckerGroup = new THREE.Group();
suckerGroup.position.set(0, -zColumnH/2, 0);
zColumnGroup.add(suckerGroup);

// 吸盘杆 - 水平向 +Z
const suckerRod = new THREE.Mesh(new THREE.CylinderGeometry(14, 14, 70), matSlideZ);
suckerRod.rotation.x = Math.PI/2;
suckerRod.position.set(0, 0, 35);
suckerRod.castShadow = true;
suckerGroup.add(suckerRod);

// 吸盘盘
const suckerDisc = new THREE.Mesh(new THREE.CylinderGeometry(55, 40, 24, 16), matSucker);
suckerDisc.rotation.x = Math.PI/2;
suckerDisc.position.set(0, 0, 82);  // 70 + 12
suckerGroup.add(suckerDisc);

// 吸盘垫
const suckerPad = new THREE.Mesh(new THREE.CylinderGeometry(40, 40, 10, 16), matSucker);
suckerPad.rotation.x = Math.PI/2;
suckerPad.position.set(0, 0, 99);  // 82 + 12 + 5
suckerGroup.add(suckerPad);

// 末端标记
const SUCKER_END_Z = 108;  // 99 + 5 + 4 (垫厚半5 + 间距4)
const indicator = new THREE.Mesh(new THREE.SphereGeometry(18, 16, 16), matIndicator);
indicator.position.set(0, 0, SUCKER_END_Z);
suckerGroup.add(indicator);
const endLight = new THREE.PointLight(0xff00ff, 1.5, 400);
endLight.position.set(0, 0, SUCKER_END_Z);
suckerGroup.add(endLight);
const endAxes = new THREE.AxesHelper(70);
endAxes.position.set(0, 0, SUCKER_END_Z);
suckerGroup.add(endAxes);

const trailPoints = [];
const trailMat = new THREE.LineBasicMaterial({{ color: {TRAIL_COLOR}, transparent: true, opacity: 0.85 }});
// 轨迹线只创建一次，之后每帧原地更新顶点数组（needsUpdate）。
// 旧实现每帧 new BufferGeometry + dispose，持续制造 GPU 缓冲 churn，
// 长时间运行易导致 WebEngine 渲染进程崩溃、3D 视图整体消失。
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

const spheres = [];
const sphereMat = new THREE.MeshStandardMaterial({{ color: 0xff3366, emissive: 0xff1144, emissiveIntensity: 0.4 }});
const sphereGlowMat = new THREE.MeshBasicMaterial({{ color: 0xff3366, transparent: true, opacity: 0.25 }});
function addSphere(wx, wy, wz) {{
  const g = new THREE.Group(); g.position.set(wx, wy, wz);
  g.add(new THREE.Mesh(new THREE.SphereGeometry(4, 32, 32), sphereMat));
  const glow = new THREE.Mesh(new THREE.SphereGeometry(32, 32, 32), sphereGlowMat);
  g.add(glow);
  const ring = new THREE.Mesh(new THREE.RingGeometry(40, 44, 32),
    new THREE.MeshBasicMaterial({{ color: 0xff3366, side: THREE.DoubleSide, transparent: true, opacity: 0.6 }}));
  ring.rotation.x = -Math.PI/2; ring.position.y = -wy + 0.6; g.add(ring);
  scene.add(g); spheres.push({{ group: g, glow, ring }});
  return spheres.length;
}}
window.addSphere = addSphere;
function clearSpheres() {{ spheres.forEach(s=>scene.remove(s.group)); spheres.length=0; }}
window.clearSpheres = clearSpheres;
function animateSpheres() {{
  const t = Date.now()*0.002;
  spheres.forEach((s,i)=>{{ s.glow.scale.setScalar(1+Math.sin(t+i*1.5)*0.15); s.ring.material.opacity=0.4+Math.sin(t*2+i)*0.2; }});
}}

let isDrag=false, prevX=0, prevY=0;
let camTheta=Math.PI/4, camPhi=Math.PI/3, camR=6000;
let target=new THREE.Vector3(-260, 1650, 180);
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
cvs.addEventListener('wheel',e=>{{camR=Math.max(1500,Math.min(12000,camR+e.deltaY*0.8));updateCam();}});

const RANGE={{x:{X_RANGE},y:{Y_RANGE},z:{Z_RANGE}}};
const SCALE={{x:{VISUAL_SCALE_X},y:{VISUAL_SCALE_Y},z:{VISUAL_SCALE_Z}}};
let curPos={{x:0,y:0,z:0}}, tgtPos={{x:0,y:0,z:0}};
window.updatePosition = function(x,y,z){{ tgtPos.x=x; tgtPos.y=y; tgtPos.z=z; }};

function animate(){{
  requestAnimationFrame(animate);
  const f=0.12;
  curPos.x+=(tgtPos.x-curPos.x)*f;
  curPos.y+=(tgtPos.y-curPos.y)*f;
  curPos.z+=(tgtPos.z-curPos.z)*f;
  const px=(curPos.x/RANGE.x)*SCALE.x;
  const py=(curPos.y/RANGE.y)*SCALE.y;
  const pz=(curPos.z/RANGE.z)*SCALE.z;
  sliderX.position.x=px;
  sliderY.position.z=Y_BEAM_CENTER_Z+py;
  zColumnGroup.position.y=-pz;
  
  // 末端位置计算（吸盘水平向 +Z）
  const endWx=px+Y_BEAM_OFFSET_X+zSlideOffset;
  const endWy=Y_HEIGHT+(-pz)+(-zColumnH/2);
  const endWz=Y_BEAM_CENTER_Z+py+SUCKER_END_Z;
  
  indicator.material.emissiveIntensity=0.6+Math.sin(Date.now()*0.008)*0.4;
  endLight.intensity=1.0+Math.sin(Date.now()*0.008)*0.5;
  updateTrail(endWx,endWy,endWz);
  animateSpheres();
  renderer.render(scene,camera);
}}
animate();
window.addEventListener('resize',()=>{{
  camera.aspect=window.innerWidth/window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth,window.innerHeight);
}});
</script>
</body>
</html>
"""