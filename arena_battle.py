import math, time, random
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GLUT import *
from OpenGL.GLUT import GLUT_BITMAP_HELVETICA_18, GLUT_BITMAP_HELVETICA_12, GLUT_BITMAP_TIMES_ROMAN_24

# =========================
# Window / Camera / World
# =========================
WIN_W, WIN_H = 1000, 800
ARENA_R = 600.0
WALL_H  = 160.0

ISO_ELEV   = math.degrees(math.atan(1.0 / math.sqrt(2.0)))
cam_yaw    = 45.0
iso_zoom   = 430.0
ISO_ZOOM_MIN, ISO_ZOOM_MAX = 220.0, 820.0
CAM_ROT_SPEED  = 90.0
CAM_ZOOM_SPEED = 380.0
cam_target = [0.0, 0.0]
first_person = False

# =========================
# Player / Combat (unchanged)
# =========================
PLAYER_SIZE = 25.0
PLAYER_MAX_HP = 20
PLAYER_MOVE_SPEED = 190.0
PLAYER_ROT_SPEED = 170.0
PLAYER_TURN_SPEED = 900.0

DASH_DIST = 120.0
DASH_CD   = 0.85

ATTACK_RANGE = 92.0
ATTACK_COOLDOWN = 0.42
ATTACK_ANGLE = 78.0
ATTACK_KB = 320.0
SWING_TIME = 0.25
SWING_ARC  = 112.0     # shoulder-pivot arc

KICK_COOLDOWN = 0.50
KICK_RANGE = 74.0
KICK_ANGLE = 72.0
KICK_KB = 420.0
KICK_DMG = 1
KICK_TIME = 0.20

EN_BULLET_SPEED   = 250.0
BOSS_BULLET_SPEED = 190.0
BULLET_TTL = 5.0
BULLET_R   = 5.0
BULLET_Z   = 32.0

MAX_WAVES = 6
BOSS_WAVE = MAX_WAVES
WAVE_BREAK = 2.0

# Obstacle scatter options
OB_MIN_SEP = 95.0
OB_TYPES = ('pillar','crate','rock','tree')

# =========================
# State
# =========================
player = {
    'pos':[0.0,0.0],
    'z':0.0,
    'angle':270.0,
    'hp':PLAYER_MAX_HP,
    'size':PLAYER_SIZE,
    'last_atk':-10.0,
    'last_dash':-10.0,
    'last_kick':-10.0,
    'gait_phase':0.0,
    'mv':[0.0,0.0]
}

sword = {'swing':False, 't0':0.0}
kick  = {'on':False, 't0':0.0, 'leg':'right'}

keys=set()
special=set()

enemies=[]
eid=0
bullets=[]
obstacles=[]

wave=0
wave_running=False
wave_target=0
wave_defeated=0
next_wave_at=0.0
score=0
game_over=False
game_msg=""

rng = random.Random()
QUAD = None

# =========================
# Utils
# =========================
def clamp(v,a,b): return a if v<a else b if v>b else v
def inside_arena(x,y,margin=0.0): return math.hypot(x,y) <= ARENA_R - margin
def damp(factor_per_frame, dt):
    return factor_per_frame ** (dt*60.0)

def push_inside(pos, margin):
    if not inside_arena(pos[0], pos[1], margin):
        ang = math.atan2(pos[1], pos[0])
        pos[0] = math.cos(ang)*(ARENA_R - margin)
        pos[1] = math.sin(ang)*(ARENA_R - margin)
        return True
    return False

def player_radius(): return player['size']*0.6
def enemy_radius(e): return e['size']*(0.45 if e['type']=='boss' else 0.6)

def cam_right():
    if first_person:
        a = math.radians(player['angle'])
        return (-math.cos(a), -math.sin(a))
    y = math.radians(cam_yaw)
    return (-math.sin(y), math.cos(y))

# =========================
# Enemies
# =========================
enemy_templates = {
    'standard': {'size': 28, 'speed': 105.0, 'hp': 2, 'color': (0.85,0.18,0.18), 'score': 1, 'type':'melee'},
    'fast':     {'size': 22, 'speed': 175.0, 'hp': 1, 'color': (1.0, 0.55,0.10), 'score': 1, 'type':'melee'},
    'heavy':    {'size': 38, 'speed':  70.0, 'hp': 6, 'color': (0.55,0.20,0.80), 'score': 3, 'type':'melee'},
    'ranged':   {'size': 26, 'speed':  85.0, 'hp': 2, 'color': (0.10,0.70,0.15), 'score': 2, 'type':'ranged', 'shoot':2.0},
    'boss':     {'size': 80, 'speed':  60.0, 'hp': 40,'color': (0.15,0.25,0.90), 'score':20, 'type':'boss'}
}

def rand_spawn(min_d=220.0, margin=52.0):
    for _ in range(400):
        a = rng.uniform(0, 2*math.pi)
        r = rng.uniform(ARENA_R*0.55, ARENA_R-margin)
        x,y = math.cos(a)*r, math.sin(a)*r
        if math.hypot(x-player['pos'][0], y-player['pos'][1]) < min_d: continue
        if any(math.hypot(x-ob['pos'][0], y-ob['pos'][1]) < ob['r']+margin for ob in obstacles): continue
        return [x,y]
    a = rng.uniform(0,2*math.pi); r = ARENA_R-margin-10
    return [math.cos(a)*r, math.sin(a)*r]

def make_enemy(kind):
    global eid
    t = enemy_templates[kind]
    size = t['size']
    x,y = rand_spawn(margin=size*0.6+20)
    hp = t['hp']
    e = {'id':eid,'type':kind,'pos':[x,y],'vx':0.0,'vy':0.0,'size':size,'speed':t['speed'],
         'hp':hp,'max_hp':hp,'color':t['color'],'score':t['score'],
         'last_shot': time.time()-rng.uniform(0,1.0),
         'last_hit':-10.0,'stun':0.0,'special': time.time()+rng.uniform(1.2,3.2),
         'phase':rng.uniform(0,6.28), 'flash':0.0}
    if kind=='ranged': e['shoot']=t['shoot']
    eid+=1; enemies.append(e); return e

# =========================
# Obstacles (RANDOM PER WAVE/RESET, Z-up)
# =========================
def _ob_params(k):
    if k=='pillar': return {'r':rng.uniform(22,32), 'h':rng.uniform(90,130)}
    if k=='crate' : return {'r':rng.uniform(24,36), 'h':rng.uniform(32,50)}
    if k=='rock'  : return {'r':rng.uniform(24,40), 'h':rng.uniform(26,42)}
    if k=='tree'  : return {'r':rng.uniform(24,32), 'h':rng.uniform(110,150)}
    return {'r':28,'h':50}

def _place_one(kind):
    for _ in range(260):
        a = rng.uniform(0, 2*math.pi)
        rr = rng.uniform(ARENA_R*0.15, ARENA_R-80)
        x,y = math.cos(a)*rr, math.sin(a)*rr
        if math.hypot(x-player['pos'][0], y-player['pos'][1]) < 130: continue
        p=_ob_params(kind); r=p['r']
        if not inside_arena(x,y, r+16): continue
        if any(math.hypot(x-ob['pos'][0], y-ob['pos'][1]) < ob['r']+r+OB_MIN_SEP for ob in obstacles): continue
        obstacles.append({'type':kind,'pos':(x,y),'r':r,'h':p['h']})
        return True
    return False

def build_random_obstacles_for_wave(w):
    obstacles.clear()
    base = 11 + min(22, w*4)
    budget = {'pillar': max(2, base//3), 'crate': max(2, base//3),
              'rock': max(2, base//4), 'tree': max(2, base//3)}
    kinds = []
    for k,n in budget.items(): kinds += [k]*n
    rng.shuffle(kinds)
    for k in kinds: _place_one(k)

def disc(r, z, segs=24):
    glNormal3f(0,0,1)
    glBegin(GL_TRIANGLE_FAN); glVertex3f(0,0,z)
    for i in range(segs+1):
        a=2*math.pi*i/segs; glVertex3f(math.cos(a)*r, math.sin(a)*r, z)
    glEnd()

def draw_one_obstacle(ob, alpha=1.0):
    t=ob['type']; x,y=ob['pos']; r=ob['r']; h=ob['h']
    def col(c): glColor4f(c[0],c[1],c[2],alpha)
    glPushMatrix(); glTranslatef(x,y,0)
    if t=='pillar':
        col((0.62,0.59,0.55)); gluCylinder(QUAD, r, r, h, 18, 1)
        col((0.50,0.47,0.43)); disc(r, h, 18)
    elif t=='crate':
        col((0.55,0.34,0.15))
        glPushMatrix(); glTranslatef(0,0,h/2.0); glScalef(r*1.6, r*1.6, h); glutSolidCube(1.0); glPopMatrix()
        col((0.35,0.20,0.08))
        glPushMatrix(); glTranslatef(0,0,h/2.0); glScalef(r*1.65, r*0.25, h*1.02); glutSolidCube(1.0); glPopMatrix()
    elif t=='rock':
        col((0.45,0.43,0.41))
        glPushMatrix(); glTranslatef(0,0,h*0.42); glScalef(r*0.95, r*0.85, h*0.6); glutSolidIcosahedron(); glPopMatrix()
    elif t=='tree':
        col((0.45,0.28,0.12)); gluCylinder(QUAD, r*0.32, r*0.24, h*0.6, 12, 1)
        col((0.13,0.55,0.20)); glPushMatrix(); glTranslatef(0,0,h*0.38); glutSolidCone(r*1.35, h*0.45, 14, 2); glPopMatrix()
        col((0.16,0.64,0.24)); glPushMatrix(); glTranslatef(0,0,h*0.62); glutSolidCone(r*1.0, h*0.40, 14, 2); glPopMatrix()
    glPopMatrix()

def obstacle_hides_player(ob):
    if first_person: return False
    y = math.radians(cam_yaw)
    tx, ty = math.cos(y), math.sin(y)
    dx = ob['pos'][0]-player['pos'][0]; dy = ob['pos'][1]-player['pos'][1]
    toward = dx*tx + dy*ty
    side   = abs(-dx*ty + dy*tx)
    return 0 < toward < ob['h']*1.6 + 40 and side < ob['r'] + 34

def draw_obstacles():
    see_through = []
    for ob in obstacles:
        if obstacle_hides_player(ob): see_through.append(ob)
        else: draw_one_obstacle(ob)
    return see_through

def draw_see_through(obs):
    if not obs: return
    glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA); glDepthMask(GL_FALSE)
    for ob in obs: draw_one_obstacle(ob, 0.28)
    glDepthMask(GL_TRUE); glDisable(GL_BLEND)

# =========================
# Floor & Wall (CIRCULAR DISK)
# =========================
def draw_floor():
    outer = ARENA_R
    bands = 22; segs = 120
    glNormal3f(0,0,1)
    for i in range(bands):
        r0 = (outer/bands)*i; r1 = (outer/bands)*(i+1)
        glColor3f(*((0.96,0.93,0.85) if i%2==0 else (0.88,0.78,0.55)))
        glBegin(GL_TRIANGLE_STRIP)
        for k in range(segs+1):
            a = (k/segs)*2*math.pi
            glVertex3f(math.cos(a)*r0, math.sin(a)*r0, 0.0)
            glVertex3f(math.cos(a)*r1, math.sin(a)*r1, 0.0)
        glEnd()

def _wall_seg_faces_camera(amid):
    if first_person: return False
    y = math.radians(cam_yaw)
    return math.cos(amid)*math.cos(y) + math.sin(amid)*math.sin(y) > 0.05

def draw_wall(near_pass):
    steps=120; r=ARENA_R
    if near_pass:
        glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA); glDepthMask(GL_FALSE)
    for i in range(steps):
        a1=(i/steps)*2*math.pi; a2=((i+1)/steps)*2*math.pi; am=(a1+a2)/2
        if _wall_seg_faces_camera(am) != near_pass: continue
        x1,y1=math.cos(a1)*r, math.sin(a1)*r; x2,y2=math.cos(a2)*r, math.sin(a2)*r
        if near_pass: glColor4f(0.45,0.40,0.35,0.16)
        else: glColor3f(0.52,0.46,0.40)
        glBegin(GL_QUADS)
        glNormal3f(-math.cos(am), -math.sin(am), 0)
        glVertex3f(x1,y1,0); glVertex3f(x2,y2,0); glVertex3f(x2,y2,WALL_H); glVertex3f(x1,y1,WALL_H)
        glEnd()
        if not near_pass:
            glColor3f(0.40,0.35,0.30)
            glBegin(GL_QUADS); glNormal3f(0,0,1)
            glVertex3f(x1,y1,WALL_H); glVertex3f(x2,y2,WALL_H)
            glVertex3f(x2*1.03,y2*1.03,WALL_H); glVertex3f(x1*1.03,y1*1.03,WALL_H)
            glEnd()
    if near_pass:
        glDisable(GL_LIGHTING); glColor4f(0.35,0.30,0.25,0.9); glLineWidth(2.0)
        glBegin(GL_LINE_STRIP)
        c = math.radians(cam_yaw)
        for i in range(61):
            a = c - math.pi/2 + math.pi*i/60
            glVertex3f(math.cos(a)*r, math.sin(a)*r, WALL_H)
        glEnd(); glLineWidth(1.0); glEnable(GL_LIGHTING)
        glDepthMask(GL_TRUE); glDisable(GL_BLEND)

def draw_shadow(x, y, r):
    glDisable(GL_LIGHTING); glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    glDepthMask(GL_FALSE)
    glColor4f(0,0,0,0.28)
    glPushMatrix(); glTranslatef(x,y,0); disc(r, 0.6, 20); glPopMatrix()
    glDepthMask(GL_TRUE); glDisable(GL_BLEND); glEnable(GL_LIGHTING)

# =========================
# HUD helpers
# =========================
def _begin_2d():
    glDisable(GL_LIGHTING); glDisable(GL_DEPTH_TEST)
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity(); gluOrtho2D(0,WIN_W,0,WIN_H)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()

def _end_2d():
    glPopMatrix(); glMatrixMode(GL_PROJECTION); glPopMatrix(); glMatrixMode(GL_MODELVIEW)
    glEnable(GL_DEPTH_TEST); glEnable(GL_LIGHTING)

def text_width(s, font): return sum(glutBitmapWidth(font, ord(c)) for c in s)

def draw_text(x,y,s, font=GLUT_BITMAP_HELVETICA_18, color=(1,1,1), center=False):
    _begin_2d()
    if center: x -= text_width(s, font)/2.0
    for (ox, oy, c) in ((1.5, -1.5, (0,0,0)), (0, 0, color)):
        glColor3f(*c)
        glRasterPos2f(x+ox, y+oy)
        for ch in s: glutBitmapCharacter(font, ord(ch))
    _end_2d()

def draw_rect_2d(x,y,w,h,c):
    glColor4f(*c); glBegin(GL_QUADS)
    glVertex2f(x,y); glVertex2f(x+w,y); glVertex2f(x+w,y+h); glVertex2f(x,y+h); glEnd()

def draw_health_bar(x,y,w,h,val,mx):
    _begin_2d()
    ratio=clamp(val/float(mx),0,1)
    draw_rect_2d(x-2,y-2,w+4,h+4,(0,0,0,1))
    draw_rect_2d(x,y,w,h,(0.18,0.18,0.18,1))
    col = (0.1,0.9,0.2,1) if ratio>0.5 else (0.95,0.75,0.1,1) if ratio>0.25 else (0.95,0.15,0.1,1)
    draw_rect_2d(x,y,w*ratio,h,col)
    _end_2d()

def draw_cooldown(x, y, label, frac):
    _begin_2d()
    draw_rect_2d(x, y, 70, 6, (0.2,0.2,0.2,1))
    draw_rect_2d(x, y, 70*clamp(frac,0,1), 6, (0.4,0.8,1.0,1) if frac>=1 else (0.4,0.5,0.6,1))
    for (ox, c) in ((1, (0,0,0)), (0, (0.9,0.9,0.95))):
        glColor3f(*c); glRasterPos2f(x+ox, y+10-ox)
        for ch in label: glutBitmapCharacter(GLUT_BITMAP_HELVETICA_12, ord(ch))
    _end_2d()

def draw_world_bar(x, y, z, w, h, ratio):
    rx, ry = cam_right()
    glDisable(GL_LIGHTING)
    def quad(a, b, c, z0, z1):
        glColor3f(*c); glBegin(GL_QUADS)
        glVertex3f(x+rx*a, y+ry*a, z0); glVertex3f(x+rx*b, y+ry*b, z0)
        glVertex3f(x+rx*b, y+ry*b, z1); glVertex3f(x+rx*a, y+ry*a, z1); glEnd()
    glEnable(GL_POLYGON_OFFSET_FILL)
    glPolygonOffset(1,1); quad(-w/2-1, w/2+1, (0.05,0.05,0.05), z-1, z+h+1)
    glPolygonOffset(0,0)
    col = (0.1,0.95,0.2) if ratio>0.5 else (0.95,0.75,0.1) if ratio>0.25 else (0.95,0.15,0.1)
    glPolygonOffset(-1,-1); quad(-w/2, -w/2+w*ratio, col, z, z+h)
    glDisable(GL_POLYGON_OFFSET_FILL)
    glEnable(GL_LIGHTING)

LEG_LEN, HIP_Z = 22.0, 22.0
TORSO_W, TORSO_D, TORSO_H = 20.0, 12.0, 22.0
SHOULDER_Z, ARM_LEN, SHOULDER_X = 42.0, 19.0, 13.5
HEAD_Z, HEAD_R = 52.0, 7.5

def limb(length, r0, r1):
    glPushMatrix(); glRotatef(180, 1, 0, 0)
    gluCylinder(QUAD, r0, r1, length, 10, 1)
    glTranslatef(0, 0, length); gluSphere(QUAD, r1*1.05, 8, 6)
    glPopMatrix()

def draw_sword_blade():
    glColor3f(0.35,0.25,0.12); glPushMatrix(); glTranslatef(0,0,-1); glScalef(9,3,2.5); glutSolidCube(1.0); glPopMatrix()
    glColor3f(0.85,0.87,0.92); glPushMatrix(); glTranslatef(0,0,-16); glScalef(2.6,1.2,28); glutSolidCube(1.0); glPopMatrix()

def draw_axe(big=False):
    k = 1.6 if big else 1.0
    glColor3f(0.40,0.25,0.10); glPushMatrix(); glTranslatef(0,0,-11*k); glScalef(2*k,2*k,26*k); glutSolidCube(1.0); glPopMatrix()
    glColor3f(0.72,0.72,0.78); glPushMatrix(); glTranslatef(0,4*k,-20*k); glScalef(1.5*k,9*k,9*k); glutSolidCube(1.0); glPopMatrix()

def draw_bow():
    glDisable(GL_LIGHTING); glLineWidth(3.0)
    glColor3f(0.45,0.25,0.10); glBegin(GL_LINE_STRIP)
    for i in range(-80, 81, 10):
        a = math.radians(i); glVertex3f(0, math.cos(a)*6, -math.sin(a)*18)
    glEnd()
    glLineWidth(1.0); glColor3f(0.95,0.95,0.95); glBegin(GL_LINES)
    glVertex3f(0, math.cos(math.radians(80))*6, -math.sin(math.radians(80))*18)
    glVertex3f(0, math.cos(math.radians(80))*6,  math.sin(math.radians(80))*18); glEnd()
    glEnable(GL_LIGHTING)

def draw_humanoid(body, skin, legs_col, gait=0.0, r_arm=(10,0), l_arm=(10,0),
                  r_leg=None, l_leg=None, weapon=None, armor=False, flash=False):
    if flash: body = skin = legs_col = (1.0, 1.0, 1.0)
    for side, override in ((1, r_leg), (-1, l_leg)):
        ang = override if override is not None else gait*side
        glPushMatrix(); glTranslatef(side*5.5, 0, HIP_Z)
        glRotatef(ang, 1, 0, 0)
        glColor3f(*legs_col); limb(LEG_LEN, 4.6, 4.0)
        glPopMatrix()
    glColor3f(*body)
    glPushMatrix(); glTranslatef(0, 0, HIP_Z + TORSO_H/2); glScalef(TORSO_W, TORSO_D, TORSO_H); glutSolidCube(1.0); glPopMatrix()
    if armor:
        glColor3f(0.62,0.62,0.70)
        for sx in (-1, 1):
            glPushMatrix(); glTranslatef(sx*13, 0, SHOULDER_Z+2); glScalef(10, 12, 7); glutSolidCube(1.0); glPopMatrix()
    glColor3f(*skin); glPushMatrix(); glTranslatef(0, 0, HEAD_Z); gluSphere(QUAD, HEAD_R, 14, 10)
    glColor3f(0.08,0.08,0.1)
    for ex in (-2.8, 2.8):
        glPushMatrix(); glTranslatef(ex, HEAD_R*0.88, 1.5); gluSphere(QUAD, 1.3, 6, 4); glPopMatrix()
    glPopMatrix()
    for side, (pitch, yaw) in ((1, r_arm), (-1, l_arm)):
        glPushMatrix(); glTranslatef(side*SHOULDER_X, 0, SHOULDER_Z)
        glRotatef(yaw, 0, 0, 1); glRotatef(pitch, 1, 0, 0)
        glColor3f(*skin); limb(ARM_LEN, 3.4, 3.0)
        if side == 1 and weapon:
            glPushMatrix(); glTranslatef(0, 0, -ARM_LEN)
            if weapon == 'sword': draw_sword_blade()
            elif weapon == 'axe': draw_axe()
            elif weapon == 'bigaxe': draw_axe(big=True)
            elif weapon == 'bow': draw_bow()
            glPopMatrix()
        glPopMatrix()

# =========================
# Player model & FPV
# =========================
def sword_pose():
    if not sword['swing']: return None
    t = clamp((time.time()-sword['t0'])/SWING_TIME, 0.0, 1.0)
    e = 1-(1-t)**2
    return (85.0, -SWING_ARC/2 + e*SWING_ARC)

def draw_player():
    x, y = player['pos']
    s = player['size']; scale = s / 25.0
    gait = math.sin(player['gait_phase'])*28.0 if math.hypot(*player['mv'])>1 else 0.0
    r_arm = sword_pose() or (20 - gait*0.5, 0)
    l_arm = (gait*0.6 + 8, 0)
    r_leg = l_leg = None
    if kick['on']:
        t = clamp((time.time()-kick['t0'])/KICK_TIME, 0, 1)
        k = math.sin(t*math.pi)*85.0
        if kick['leg']=='right': r_leg = k
        else: l_leg = k
    draw_shadow(x, y, s*0.75)
    glPushMatrix()
    glTranslatef(x, y, 0)
    glRotatef(player['angle']+180.0, 0, 0, 1)
    glScalef(scale, scale, scale)
    draw_humanoid((0.15,0.35,0.95), (0.98,0.85,0.72), (0.18,0.18,0.25),
                  gait=gait, r_arm=r_arm, l_arm=l_arm, r_leg=r_leg, l_leg=l_leg, weapon='sword')
    glPopMatrix()

def segment(p0, p1, r0, r1):
    vx, vy, vz = p1[0]-p0[0], p1[1]-p0[1], p1[2]-p0[2]
    ln = math.sqrt(vx*vx+vy*vy+vz*vz) or 1e-6
    glPushMatrix(); glTranslatef(*p0)
    ax, ay = -vy, vx
    if abs(ax)+abs(ay) > 1e-6: glRotatef(math.degrees(math.acos(clamp(vz/ln,-1,1))), ax, ay, 0)
    elif vz < 0: glRotatef(180, 1, 0, 0)
    gluCylinder(QUAD, r0, r1, ln, 12, 1)
    glPopMatrix()

def draw_fpv_hands():
    now = time.time()
    glClear(GL_DEPTH_BUFFER_BIT)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
    bob = math.sin(player['gait_phase'])*0.6 if math.hypot(*player['mv']) > 1 else 0.0
    if sword['swing']:
        t = clamp((now-sword['t0'])/SWING_TIME, 0.0, 1.0); e = 1-(1-t)**2
        hand = (10 - 18*e, -8 + 2*math.sin(e*math.pi), -30)
        yaw, pitch = -65 + 130*e, 18
    else:
        hand = (9, -9 + bob, -28)
        yaw, pitch = 8, 50
    skin = (0.98,0.85,0.72)
    glColor3f(*skin); segment((hand[0]+6, hand[1]-14, hand[2]+16), hand, 2.4, 2.0)
    glPushMatrix(); glTranslatef(*hand); gluSphere(QUAD, 2.3, 10, 8)
    glRotatef(yaw, 0, 1, 0); glRotatef(pitch, 1, 0, 0)
    glScalef(0.5, 0.5, 0.5); draw_sword_blade()
    glPopMatrix()
    if kick['on']:
        t = clamp((now-kick['t0'])/KICK_TIME, 0, 1); k = math.sin(t*math.pi)
        side = 5 if kick['leg']=='right' else -5
        foot = (side*0.6, -30 + 22*k, -26 - 10*k)
        glColor3f(0.18,0.18,0.25); segment((side, -48, 4), foot, 3.4, 3.0)
        glColor3f(0.28,0.22,0.18)
        glPushMatrix(); glTranslatef(*foot); glScalef(5, 3.5, 7); glutSolidCube(1.0); glPopMatrix()
    glPopMatrix()

def draw_crosshair():
    _begin_2d()
    cx, cy = WIN_W/2, WIN_H/2
    glLineWidth(2.0)
    for col, o in (((0,0,0), 1), ((1,1,1), 0)):
        glColor3f(*col); glBegin(GL_LINES)
        for (x0,y0,x1,y1) in ((-9,0,-3,0),(3,0,9,0),(0,-9,0,-3),(0,3,0,9)):
            glVertex2f(cx+x0+o, cy+y0-o); glVertex2f(cx+x1+o, cy+y1-o)
        glEnd()
    glLineWidth(1.0)
    _end_2d()

# -------------------- Enemy models --------------------
def enemy_yaw(e):
    dx = player['pos'][0]-e['pos'][0]; dy = player['pos'][1]-e['pos'][1]
    return math.degrees(math.atan2(dy, dx)) - 90.0

def draw_enemy(e):
    x, y = e['pos']; s = e['size']; now = time.time()
    moving = math.hypot(e['vx'], e['vy']) > 8
    gait = math.sin(e['phase'])*26.0 if moving else 0.0
    flash = now < e['flash']
    since_hit = now - e['last_hit']
    chop = 95.0*math.sin(clamp(since_hit/0.3,0,1)*math.pi) if since_hit < 0.3 else 0.0
    if e['type'] == 'boss':
        scale = s/32.0
        r_arm = (30 + chop, 0); l_arm = (gait*0.5 + 15, 0); weapon='bigaxe'
        body, skin, legs, armor = (0.20,0.22,0.55), (0.80,0.80,0.84), (0.35,0.10,0.10), True
    else:
        scale = s/25.0
        if e['type'] == 'ranged':
            r_arm = (85, 0); l_arm = (85, -25); weapon='bow'
        else:
            r_arm = (35 + chop, 0); l_arm = (gait*0.6 + 30, 0); weapon='axe'
        body = e['color']; skin = (1.0,0.62,0.42); legs = tuple(c*0.45 for c in e['color'])
        armor = e['type']=='heavy'
    draw_shadow(x, y, s*(0.55 if e['type']=='boss' else 0.75))
    glPushMatrix(); glTranslatef(x, y, 0); glRotatef(enemy_yaw(e), 0, 0, 1); glScalef(scale, scale, scale)
    draw_humanoid(body, skin, legs, gait=gait, r_arm=r_arm, l_arm=l_arm, weapon=weapon, armor=armor, flash=flash)
    glPopMatrix()
    top = (HEAD_Z + HEAD_R + 8)*scale
    if first_person and math.hypot(x-player['pos'][0], y-player['pos'][1]) < 70: return
    if e['type']=='boss': draw_world_bar(x, y, top, 90, 9, e['hp']/float(e['max_hp']))
    else: draw_world_bar(x, y, top, 30, 4, e['hp']/float(e['max_hp']))
# -------------------- end enemy models --------------------

def draw_bullet(b):
    x,y=b['pos']
    glDisable(GL_LIGHTING)
    glPushMatrix(); glTranslatef(x,y,BULLET_Z)
    glColor3f(1.0,0.85,0.15); gluSphere(QUAD,BULLET_R,10,8)
    glPopMatrix()
    glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA); glDepthMask(GL_FALSE)
    glColor4f(1.0,0.5,0.1,0.35); glPushMatrix(); glTranslatef(x,y,0); disc(BULLET_R*1.4, 0.8, 12); glPopMatrix()
    glDepthMask(GL_TRUE); glDisable(GL_BLEND)
    glEnable(GL_LIGHTING)

# =========================
# Physics/AI
# =========================
def push_out_of_obstacles(pos, rad):
    hit=False
    for ob in obstacles:
        ox,oy=ob['pos']; d=math.hypot(pos[0]-ox,pos[1]-oy); min_d=ob['r']+rad
        if d<min_d:
            if d<1e-3: nx,ny=1.0,0.0
            else: nx,ny=(pos[0]-ox)/d,(pos[1]-oy)/d
            pos[0]=ox+nx*min_d; pos[1]=oy+ny*min_d; hit=True
    return hit

def collide_player_obs():
    push_out_of_obstacles(player['pos'], player_radius())
    push_inside(player['pos'], player_radius()+2)

def collide_enemy_obs(e):
    if push_out_of_obstacles(e['pos'], enemy_radius(e)):
        e['vx']*=0.3; e['vy']*=0.3

def separate_enemies():
    for i in range(len(enemies)):
        a = enemies[i]
        for j in range(i+1, len(enemies)):
            b = enemies[j]
            dx = b['pos'][0]-a['pos'][0]; dy = b['pos'][1]-a['pos'][1]
            d = math.hypot(dx,dy); min_d = enemy_radius(a)+enemy_radius(b)
            if 1e-3 < d < min_d:
                push = (min_d-d)*0.5; nx,ny = dx/d, dy/d
                a['pos'][0]-=nx*push; a['pos'][1]-=ny*push
                b['pos'][0]+=nx*push; b['pos'][1]+=ny*push

def hurt_player(dmg):
    player['hp'] -= dmg
    if player['hp'] <= 0:
        player['hp'] = 0; trigger_game_over("You died")

def fire_bullet(x, y, ang, speed, now):
    if inside_arena(x, y, BULLET_R):
        bullets.append({'pos':[x,y],'vel':[math.cos(ang)*speed, math.sin(ang)*speed],'born':now,'dmg':1})

def update_enemies(dt):
    global score, wave_defeated
    now=time.time(); px,py=player['pos']
    steer = 1.0 - math.exp(-6.0*dt)
    for e in enemies:
        if e['hp']<=0: continue
        dx,dy=px-e['pos'][0], py-e['pos'][1]; dd=math.hypot(dx,dy) or 0.0001
        if now<e['stun']:
            k = damp(0.90, dt); e['vx']*=k; e['vy']*=k
        else:
            desx = desy = 0.0
            if e['type']=='boss':
                if now>e['special']:
                    e['special']=now+rng.uniform(2.4,5.0)
                    if rng.random()<0.5:
                        sp=520.0; e['vx']=(dx/dd)*sp; e['vy']=(dy/dd)*sp; e['stun']=now+0.45
                    else:
                        base = math.atan2(dy,dx)
                        for k in range(14):
                            ang=base+(k-6.5)*0.32
                            fire_bullet(e['pos'][0]+math.cos(ang)*(enemy_radius(e)+10),
                                        e['pos'][1]+math.sin(ang)*(enemy_radius(e)+10), ang, BOSS_BULLET_SPEED, now)
                desx,desy=(dx/dd)*e['speed'], (dy/dd)*e['speed']
            elif e['type']=='ranged':
                if dd<180:   desx,desy = (-dx/dd)*e['speed'], (-dy/dd)*e['speed']
                elif dd>320: desx,desy = (dx/dd)*e['speed'], (dy/dd)*e['speed']
                else:        desx,desy = (-dy/dd)*e['speed']*0.5, (dx/dd)*e['speed']*0.5
                if now - e['last_shot'] >= e['shoot']:
                    e['last_shot']=now; ang=math.atan2(dy,dx)
                    fire_bullet(e['pos'][0]+math.cos(ang)*(enemy_radius(e)+8),
                                e['pos'][1]+math.sin(ang)*(enemy_radius(e)+8), ang, EN_BULLET_SPEED, now)
            else:
                desx,desy=(dx/dd)*e['speed'], (dy/dd)*e['speed']
            e['vx']+=(desx-e['vx'])*steer; e['vy']+=(desy-e['vy'])*steer

        e['pos'][0]+=e['vx']*dt; e['pos'][1]+=e['vy']*dt
        e['phase'] += math.hypot(e['vx'],e['vy'])*dt*0.12
        collide_enemy_obs(e)
        if push_inside(e['pos'], enemy_radius(e)+2):
            e['vx']*=-0.3; e['vy']*=-0.3

        dx,dy=px-e['pos'][0], py-e['pos'][1]; dd=math.hypot(dx,dy) or 0.0001
        reach = enemy_radius(e)+player_radius()
        if dd < reach + 6:
            if now - e['last_hit'] > 0.85:
                e['last_hit']=now; dmg=2 if e['type'] in ('heavy','boss') else 1
                if e['type']=='boss':
                    player['pos'][0]+=dx/dd*44.0; player['pos'][1]+=dy/dd*44.0
                    collide_player_obs()
                hurt_player(dmg)
            if dd < reach:
                over = reach-dd
                e['pos'][0]-=dx/dd*over; e['pos'][1]-=dy/dd*over

    separate_enemies()
    for e in enemies:
        collide_enemy_obs(e); push_inside(e['pos'], enemy_radius(e)+2)
    for e in [e for e in enemies if e['hp']<=0]:
        score += e.get('score',1); wave_defeated += 1
        enemies.remove(e)

def update_bullets(dt):
    now=time.time(); keep=[]
    for b in bullets:
        b['pos'][0]+=b['vel'][0]*dt; b['pos'][1]+=b['vel'][1]*dt
        x,y = b['pos']
        if now-b['born']>BULLET_TTL: continue
        if not inside_arena(x, y, BULLET_R): continue
        if any(math.hypot(x-ob['pos'][0], y-ob['pos'][1]) < ob['r']+BULLET_R for ob in obstacles): continue
        if math.hypot(x-player['pos'][0], y-player['pos'][1]) <= player_radius()+BULLET_R:
            hurt_player(b.get('dmg',1)); continue
        keep.append(b)
    bullets[:] = keep

# =========================
# Waves / flow
# =========================
def start_wave():
    global wave, wave_running, wave_target, wave_defeated
    wave += 1
    enemies.clear(); bullets.clear()
    wave_defeated = 0
    player['hp'] = PLAYER_MAX_HP
    build_random_obstacles_for_wave(wave)
    collide_player_obs()
    sp_mult = 1.0 + 0.08 * (wave - 1)
    if wave % 2 == 0:
        wave_target = 1
        e = make_enemy('boss'); e['speed'] *= sp_mult
    else:
        wave_target = 2 + wave
        for _ in range(wave_target):
            r = rng.random()
            kind = 'standard' if r < 0.5 else 'fast' if r < 0.78 else 'ranged' if r < 0.94 else 'heavy'
            e = make_enemy(kind); e['speed'] *= sp_mult
    wave_running = True

def spawn_fill():
    if not wave_running or wave % 2 == 0: return
    alive = len(enemies)
    remaining = wave_target - wave_defeated - alive
    while remaining > 0 and alive < 12:
        r=rng.random(); kind='standard' if r<0.6 else 'fast' if r<0.85 else 'ranged'
        make_enemy(kind); alive+=1; remaining-=1

def end_wave():
    global wave_running, next_wave_at
    wave_running=False
    next_wave_at = time.time() + WAVE_BREAK

def trigger_game_over(msg):
    global game_over, game_msg
    game_over=True; game_msg=msg

# =========================
# Combat/Input
# =========================
def hit_enemies(rng_, angle_deg, kb, dmg, stun, kb_boss=True):
    yaw = math.radians(player['angle']-90.0); fx,fy = math.cos(yaw), math.sin(yaw)
    px,py=player['pos']; now=time.time()
    for e in enemies:
        if e['hp']<=0: continue
        dx,dy=e['pos'][0]-px, e['pos'][1]-py; d=math.hypot(dx,dy) or 1.0
        if d <= rng_ + enemy_radius(e):
            dot = clamp((dx*fx+dy*fy)/d, -1, 1)
            if d < enemy_radius(e) + player_radius() + 4 or math.degrees(math.acos(dot)) <= angle_deg/2.0:
                e['hp'] -= dmg; e['flash'] = now + 0.12
                if e['type']!='boss' or kb_boss:
                    m = 0.35 if e['type'] in ('heavy','boss') else 1.0
                    e['vx'] += dx/d*kb*m; e['vy'] += dy/d*kb*m
                e['stun'] = now + stun

def attack_sword():
    now=time.time()
    if now - player['last_atk'] < ATTACK_COOLDOWN: return
    player['last_atk']=now; sword['swing']=True; sword['t0']=now
    hit_enemies(ATTACK_RANGE, ATTACK_ANGLE, ATTACK_KB, 1, 0.2)

def attack_kick():
    now=time.time()
    if now - player['last_kick'] < KICK_COOLDOWN: return
    player['last_kick']=now
    kick['on']=True; kick['t0']=now
    kick['leg'] = 'right' if kick['leg']=='left' else 'left'
    hit_enemies(KICK_RANGE, KICK_ANGLE, KICK_KB, KICK_DMG, 0.25, kb_boss=False)

def dash():
    now=time.time()
    if now - player['last_dash'] < DASH_CD: return
    player['last_dash']=now
    d = None if first_person else input_dir()
    if d is None:
        a = math.radians(player['angle']-90.0); d = (math.cos(a), math.sin(a))
    else:
        player['angle'] = (math.degrees(math.atan2(d[1], d[0])) + 90.0) % 360.0
    steps = 12
    for _ in range(steps):
        player['pos'][0] += d[0]*DASH_DIST/steps
        player['pos'][1] += d[1]*DASH_DIST/steps
        if push_out_of_obstacles(player['pos'], player_radius()): break
        if push_inside(player['pos'], player_radius()+2): break

def key_down(k,x,y):
    global first_person
    if not k: return
    c=(k.decode(errors='ignore') if isinstance(k,bytes) else k).lower()
    keys.add(c)
    if c=='r': reset_game(); return
    if c=='\x1b':
        try: glutLeaveMainLoop()
        except Exception: raise SystemExit
        return
    if game_over: return
    if c=='f': attack_sword()
    elif c=='k': attack_kick()
    elif c==' ': dash()
    elif c=='`': first_person = not first_person

def key_up(k,x,y):
    if not k: return
    c=(k.decode(errors='ignore') if isinstance(k,bytes) else k).lower()
    keys.discard(c)

def sp_down(k,x,y): special.add(k)
def sp_up(k,x,y): special.discard(k)

def mouse(btn,state,x,y):
    global first_person, iso_zoom
    if state!=GLUT_DOWN: return
    if btn==GLUT_LEFT_BUTTON and not game_over: attack_sword()
    elif btn==GLUT_RIGHT_BUTTON: first_person = not first_person
    elif btn==3: iso_zoom = clamp(iso_zoom-30, ISO_ZOOM_MIN, ISO_ZOOM_MAX)
    elif btn==4: iso_zoom = clamp(iso_zoom+30, ISO_ZOOM_MIN, ISO_ZOOM_MAX)

# =========================
# Movement
# =========================
def input_dir():
    up = (1 if 'w' in keys else 0) - (1 if 's' in keys else 0)
    rt = (1 if 'd' in keys else 0) - (1 if 'a' in keys else 0)
    if not up and not rt: return None
    if first_person:
        a = math.radians(player['angle']-90.0)
        fx, fy = math.cos(a), math.sin(a)
        rx, ry = math.cos(a-math.pi/2), math.sin(a-math.pi/2)
    else:
        c = math.radians(cam_yaw)
        fx, fy = -math.cos(c), -math.sin(c)
        rx, ry = cam_right()
    dx = fx*up + rx*rt; dy = fy*up + ry*rt
    n = math.hypot(dx, dy)
    return (dx/n, dy/n)

def turn_towards(target, dt):
    diff = (target - player['angle'] + 180.0) % 360.0 - 180.0
    step = PLAYER_TURN_SPEED*dt
    player['angle'] = (player['angle'] + clamp(diff, -step, step)) % 360.0

def move_player(dt):
    mvx = mvy = 0.0
    if first_person:
        if 'a' in keys: player['angle'] = (player['angle'] + PLAYER_ROT_SPEED*dt) % 360.0
        if 'd' in keys: player['angle'] = (player['angle'] - PLAYER_ROT_SPEED*dt) % 360.0
        fwd = (1 if 'w' in keys else 0) - (1 if 's' in keys else 0)
        if fwd:
            a = math.radians(player['angle']-90.0)
            mvx, mvy = math.cos(a)*PLAYER_MOVE_SPEED*fwd, math.sin(a)*PLAYER_MOVE_SPEED*fwd
    else:
        d = input_dir()
        if d:
            turn_towards(math.degrees(math.atan2(d[1], d[0])) + 90.0, dt)
            mvx, mvy = d[0]*PLAYER_MOVE_SPEED, d[1]*PLAYER_MOVE_SPEED
    if mvx or mvy:
        player['pos'][0] += mvx*dt; player['pos'][1] += mvy*dt
        player['gait_phase'] += PLAYER_MOVE_SPEED*dt*0.09
    player['mv'] = [mvx, mvy]
    collide_player_obs()

def move_camera(dt):
    global cam_yaw, iso_zoom
    if GLUT_KEY_LEFT in special:  cam_yaw = (cam_yaw + CAM_ROT_SPEED*dt) % 360.0
    if GLUT_KEY_RIGHT in special: cam_yaw = (cam_yaw - CAM_ROT_SPEED*dt) % 360.0
    if GLUT_KEY_UP in special:    iso_zoom = clamp(iso_zoom - CAM_ZOOM_SPEED*dt, ISO_ZOOM_MIN, ISO_ZOOM_MAX)
    if GLUT_KEY_DOWN in special:  iso_zoom = clamp(iso_zoom + CAM_ZOOM_SPEED*dt, ISO_ZOOM_MIN, ISO_ZOOM_MAX)
    k = 1.0 - math.exp(-5.0*dt)
    cam_target[0] += (player['pos'][0]-cam_target[0])*k
    cam_target[1] += (player['pos'][1]-cam_target[1])*k

# =========================
# Loop / Display
# =========================
_last=time.time()
def idle():
    global _last
    now=time.time(); dt=clamp(now-_last, 0.0, 0.05); _last=now
    move_camera(dt)
    if not game_over:
        move_player(dt)
        if sword['swing'] and (now - sword['t0'])>=SWING_TIME: sword['swing']=False
        if kick['on'] and (now - kick['t0'])>=KICK_TIME: kick['on']=False
        update_enemies(dt)
        update_bullets(dt)
        if wave_running:
            spawn_fill()
            if len(enemies)==0 and wave_defeated>=wave_target: end_wave()
        elif now >= next_wave_at:
            if wave>=MAX_WAVES: trigger_game_over("Victory! You cleared all waves.")
            else: start_wave()
    glutPostRedisplay()

def setup_camera():
    glMatrixMode(GL_PROJECTION); glLoadIdentity()
    aspect = float(WIN_W)/float(WIN_H)
    if first_person:
        gluPerspective(70.0, aspect, 2.0, 6000.0)
        glMatrixMode(GL_MODELVIEW); glLoadIdentity()
        rad = math.radians(player['angle']-90.0)
        cx = player['pos'][0] - math.cos(rad)*10; cy = player['pos'][1] - math.sin(rad)*10
        cz = HEAD_Z*player['size']/25.0 + 4
        gluLookAt(cx,cy,cz, cx+math.cos(rad)*100, cy+math.sin(rad)*100, cz-8, 0,0,1)
    else:
        glOrtho(-iso_zoom*aspect, iso_zoom*aspect, -iso_zoom, iso_zoom, -4000.0, 8000.0)
        glMatrixMode(GL_MODELVIEW); glLoadIdentity()
        dist = 2500.0
        yaw, el = math.radians(cam_yaw), math.radians(ISO_ELEV)
        tx, ty = cam_target
        ex = tx + math.cos(yaw)*math.cos(el)*dist
        ey = ty + math.sin(yaw)*math.cos(el)*dist
        ez = math.sin(el)*dist
        gluLookAt(ex,ey,ez, tx,ty,0, 0,0,1)
    glLightfv(GL_LIGHT0, GL_POSITION, (0.35, 0.55, 1.0, 0.0))

def display():
    if first_person: glClearColor(0.42,0.58,0.78,1.0)
    else: glClearColor(0.10,0.11,0.15,1.0)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glViewport(0,0,WIN_W,WIN_H)
    setup_camera()

    draw_floor()
    draw_wall(near_pass=False)
    see_through = draw_obstacles()
    if not first_person: draw_player()
    for e in enemies: draw_enemy(e)
    for b in bullets: draw_bullet(b)
    draw_see_through(see_through)
    draw_wall(near_pass=True)

    if first_person:
        draw_fpv_hands()
        draw_crosshair()

    draw_health_bar(WIN_W-300, WIN_H-46, 270, 18, player['hp'], PLAYER_MAX_HP)
    draw_text(WIN_W-300, WIN_H-68, f"Health {player['hp']}/{PLAYER_MAX_HP}")
    now = time.time()
    draw_cooldown(WIN_W-300, WIN_H-100, "Sword", (now-player['last_atk'])/ATTACK_COOLDOWN)
    draw_cooldown(WIN_W-200, WIN_H-100, "Kick",  (now-player['last_kick'])/KICK_COOLDOWN)
    draw_cooldown(WIN_W-100, WIN_H-100, "Dash",  (now-player['last_dash'])/DASH_CD)
    draw_text(12, WIN_H-26, f"Wave: {wave}/{MAX_WAVES}   Score: {score}   Enemies: {len(enemies)}")
    move_help = "W/S forward/back, A/D turn" if first_person else "WASD move (W = up the screen)"
    draw_text(12, 30, move_help + " | F / Left click sword, K kick, Space dash", GLUT_BITMAP_HELVETICA_12, (0.85,0.85,0.9))
    draw_text(12, 12, "Arrows / wheel: rotate & zoom camera | ` or right click: first person | R restart | Esc quit", GLUT_BITMAP_HELVETICA_12, (0.85,0.85,0.9))

    if not wave_running and not game_over and wave>0:
        draw_text(WIN_W/2, WIN_H/2+60, f"Wave {wave} cleared!", GLUT_BITMAP_TIMES_ROMAN_24, (1,0.9,0.4), center=True)
    elif wave_running and wave%2==0 and now - (next_wave_at) < 2.0:
        draw_text(WIN_W/2, WIN_H/2+60, "BOSS WAVE", GLUT_BITMAP_TIMES_ROMAN_24, (1,0.4,0.3), center=True)

    if game_over:
        _begin_2d()
        glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        draw_rect_2d(WIN_W/2-220, WIN_H/2-60, 440, 120, (0,0,0,0.65)); glDisable(GL_BLEND)
        _end_2d()
        draw_text(WIN_W/2, WIN_H/2+25, game_msg, GLUT_BITMAP_TIMES_ROMAN_24, center=True)
        draw_text(WIN_W/2, WIN_H/2-5, f"Final Score: {score}", GLUT_BITMAP_TIMES_ROMAN_24, center=True)
        draw_text(WIN_W/2, WIN_H/2-35, "Press R to restart", GLUT_BITMAP_TIMES_ROMAN_24, center=True)

    glutSwapBuffers()

# =========================
# Init / Reset
# =========================
def reset_game():
    global eid, wave, wave_running, wave_target, wave_defeated, score, game_over, game_msg
    global cam_yaw, iso_zoom, next_wave_at
    player['pos']=[0.0,0.0]; player['angle']=270.0; player['hp']=PLAYER_MAX_HP
    player['last_atk']=player['last_dash']=player['last_kick']=-10.0
    player['gait_phase']=0.0; player['mv']=[0.0,0.0]
    sword['swing']=False; kick['on']=False; kick['leg']='right'
    enemies.clear(); bullets.clear(); eid=0
    wave=0; wave_running=False; wave_target=0; wave_defeated=0; score=0; game_over=False; game_msg=""
    next_wave_at=0.0
    cam_yaw=45.0; iso_zoom=430.0; cam_target[0]=cam_target[1]=0.0
    start_wave()

def reshape(w,h):
    global WIN_W, WIN_H
    WIN_W, WIN_H = max(1,w), max(1,h)
    glViewport(0,0,WIN_W,WIN_H)

def init_gl():
    global QUAD
    QUAD = gluNewQuadric(); gluQuadricNormals(QUAD, GLU_SMOOTH)
    glEnable(GL_DEPTH_TEST)
    glClearColor(0.10,0.11,0.15,1.0)
    glEnable(GL_LIGHTING); glEnable(GL_LIGHT0); glEnable(GL_NORMALIZE)
    glLightfv(GL_LIGHT0, GL_DIFFUSE, (0.75,0.75,0.72,1.0))
    glLightModelfv(GL_LIGHT_MODEL_AMBIENT, (0.48,0.48,0.52,1.0))
    glEnable(GL_COLOR_MATERIAL); glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
    glShadeModel(GL_SMOOTH)

def main():
    glutInit()
    glutInitDisplayMode(GLUT_DOUBLE | GLUT_RGBA | GLUT_DEPTH)
    glutInitWindowSize(WIN_W, WIN_H)
    glutInitWindowPosition(100, 60)
    glutCreateWindow(b"3D Gladiator Arena")
    init_gl()
    reset_game()
    glutDisplayFunc(display)
    glutIdleFunc(idle)
    glutIgnoreKeyRepeat(1)
    glutKeyboardFunc(key_down)
    glutKeyboardUpFunc(key_up)
    glutSpecialFunc(sp_down)
    glutSpecialUpFunc(sp_up)
    glutMouseFunc(mouse)
    glutReshapeFunc(reshape)
    glutMainLoop()

if __name__=="__main__":
    main()
