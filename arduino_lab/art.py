"""UNO 보드와 모듈 그림. 실물 색을 차분하게 낮춰 그립니다(그림자·광택·발광 없음).

여기 색은 '재료 색'(기판, 플라스틱, 금속, LED)입니다. UI 색은 theme.py 토큰만 씁니다.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainterPath, QPen, QBrush, QPolygonF

import theme
from . import board as B

# 재료 색
PCB_UNO = QColor('#1f5961')
PCB_UNO_EDGE = QColor('#163f45')
PCB_BLUE = QColor('#24426b')
PCB_BLUE_EDGE = QColor('#182d4a')
PCB_GREEN = QColor('#26523a')
PCB_GREEN_EDGE = QColor('#1a3828')
PCB_BLACK = QColor('#232427')
PCB_RED = QColor('#7a2d2a')
SILK = QColor('#dfe6e2')
SILK_DIM = QColor(223, 230, 226, 150)
PLASTIC = QColor('#18191b')
PLASTIC_EDGE = QColor('#0b0b0c')
METAL = QColor('#b9b4a8')
METAL_DARK = QColor('#85817a')
GOLD = QColor('#c2a35e')
CHIP = QColor('#1c1c1e')
WHITE_PLASTIC = QColor('#d9d6cf')

LED_ON = {'red': '#ff5a47', 'yellow': '#ffd447', 'green': '#5ee36a', 'blue': '#4a8dff', 'white': '#f4f1ea',
          'orange': '#ff9a3c'}
LED_OFF = {'red': '#6b2622', 'yellow': '#6e6125', 'green': '#2a5a30', 'blue': '#253f6e', 'white': '#77746e',
           'orange': '#6e4422'}

WIRE_COLORS = [('red', '빨강', '#c4473c'), ('black', '검정', '#3d3e42'), ('orange', '주황', '#d48a3c'),
               ('yellow', '노랑', '#cdb84e'), ('green', '초록', '#5c9e5a'), ('blue', '파랑', '#4f80bb'),
               ('purple', '보라', '#8d6db3'), ('white', '흰색', '#d2cdc3'), ('brown', '갈색', '#8b5b3e')]
WIRE_HEX = {k: h for k, _, h in WIRE_COLORS}
SIGNAL_CYCLE = ['orange', 'yellow', 'green', 'blue', 'purple', 'white', 'brown']


def font(px, bold=False, mono=False):
    f = QFont()
    f.setFamilies(theme.MONO_FAMILIES if mono else theme.FONT_FAMILIES)
    f.setPixelSize(max(1, int(round(px))))
    f.setBold(bold)
    return f


def text(p, s, x, y, px=8, color=SILK, align='c', bold=False, mono=False, rot=0):
    """(x, y)를 기준점으로 글자 하나 줄을 씁니다. align: l c r."""
    p.save()
    p.setFont(font(px, bold, mono))
    p.setPen(color)
    p.translate(x, y)
    if rot:
        p.rotate(rot)
    fm = p.fontMetrics()
    w = fm.horizontalAdvance(s)
    dx = {'l': 0, 'c': -w / 2, 'r': -w}[align]
    p.drawText(QPointF(dx, fm.ascent() / 2 - 1), s)
    p.restore()


def rect(p, r, fill, edge=None, radius=2.0, width=1.0):
    p.setPen(QPen(edge, width) if edge is not None else Qt.PenStyle.NoPen)
    p.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
    if radius:
        p.drawRoundedRect(r, radius, radius)
    else:
        p.drawRect(r)


def pcb(p, w, h, fill=PCB_BLUE, edge=PCB_BLUE_EDGE, holes=True):
    rect(p, QRectF(0.5, 0.5, w - 1, h - 1), fill, edge, 3)
    if holes and w >= 50 and h >= 40:
        p.setPen(QPen(METAL_DARK, 1))
        p.setBrush(QColor('#101114'))
        for hx, hy in ((6, 6), (w - 6, 6)):
            p.drawEllipse(QPointF(hx, hy), 2.6, 2.6)


LABEL_PX = 9.5


def fit_text(p, s, x, y, px, color, maxw, bold=True, mono=False):
    """maxw 안에 들어가도록 글자 크기를 줄여서 씁니다."""
    while px > 6.5:
        p.setFont(font(px, bold, mono))
        if p.fontMetrics().horizontalAdvance(s) <= maxw:
            break
        px -= 0.5
    text(p, s, x, y, px, color, bold=bold, mono=mono)


def readout(p, s, cx, y=-14):
    """모듈 위에 뜨는 현재 값(거리, 온도 등). 어두운 상자 + 밝은 글자."""
    p.save()
    p.setFont(font(10))
    w = p.fontMetrics().horizontalAdvance(s) + 10
    r = QRectF(cx - w / 2, y - 8, w, 16)
    rect(p, r, QColor(theme.BASE), QColor(theme.LINE2), 2)
    p.restore()
    text(p, s, cx, y, 10, QColor(theme.TEXT))


def silk_title(p, s, x, y, px=8.5, color=None):
    text(p, s, x, y, px, color or SILK_DIM, bold=True)


def header(p, mod, body_h, labels=True, label_y=None, px=LABEL_PX):
    """모듈 아래쪽 수 핀 헤더(플라스틱 띠 + 금속 핀 + 이름)."""
    pins = mod.PINS
    if not pins:
        return
    xs = [x for _, x, _ in pins]
    y_pin = pins[0][2]
    rect(p, QRectF(min(xs) - 7, body_h, max(xs) - min(xs) + 14, 7), PLASTIC, PLASTIC_EDGE, 1)
    p.setPen(QPen(METAL, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    for name, x, y in pins:
        p.drawLine(QPointF(x, body_h + 7), QPointF(x, y))
    if labels:
        ly = body_h - 8 if label_y is None else label_y
        pitch = min((b - a for a, b in zip(xs, xs[1:])), default=24) or 24
        labs = [mod.pin_label(n) if len(mod.pin_label(n)) <= 4 else n for n, _x, _y in pins]
        size = px
        while size > 6.5:          # 한 줄의 글자 크기를 모두 같게
            p.setFont(font(size, True))
            if max(p.fontMetrics().horizontalAdvance(t) for t in labs) <= pitch - 2:
                break
            size -= 0.5
        for lab, (name, x, y) in zip(labs, pins):
            text(p, lab, x, ly, size, SILK, bold=True)


def lead(p, x0, y0, x1, y1, color=METAL, width=1.8):
    p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(x0, y0), QPointF(x1, y1))


def smd_led(p, x, y, on, color='green', w=7, h=4):
    c = QColor(LED_ON[color] if on else LED_OFF[color])
    rect(p, QRectF(x - w / 2, y - h / 2, w, h), c, QColor('#0e0e0f'), 0.5, 0.6)
    if on:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 120))
        p.drawRect(QRectF(x - w / 4, y - h / 4, w / 2, h / 2))


def mix(c1, c2, t):
    a, b = QColor(c1), QColor(c2)
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


# ---------------------------------------------------------------- UNO 보드
def paint_board(p, st):
    """st: {'L': bool, 'TX': bool, 'RX': bool, 'ON': bool, 'pins': {pin: 'hi'|'lo'|None}}"""
    W, H = B.BOARD_W, B.BOARD_H
    # 기판
    path = QPainterPath()
    path.addRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 5, 5)
    p.setPen(QPen(PCB_UNO_EDGE, 1))
    p.setBrush(PCB_UNO)
    p.drawPath(path)
    # 고정 구멍
    p.setPen(QPen(QColor('#b3a77f'), 2))
    p.setBrush(QColor('#0f1012'))
    for hx, hy in ((112, 18), (520, 110), (520, 388), (120, 400)):
        p.drawEllipse(QPointF(hx, hy), 5, 5)
    # USB-B 단자
    rect(p, QRectF(-14, 46, 66, 92), QColor('#a9a69e'), QColor('#6f6c66'), 1.5)
    rect(p, QRectF(-14, 64, 18, 56), QColor('#c4c1b9'), QColor('#77746d'), 1)
    p.setPen(QPen(QColor('#8d8a83'), 1))
    for k in range(5):
        p.drawLine(QPointF(10 + k * 8, 50), QPointF(10 + k * 8, 134))
    # 전원 잭
    rect(p, QRectF(-8, 302, 74, 72), QColor('#141416'), QColor('#050505'), 2)
    rect(p, QRectF(-8, 318, 20, 40), QColor('#202023'), QColor('#050505'), 1)
    p.setPen(QPen(QColor('#3a3a3d'), 1))
    p.drawLine(QPointF(14, 306), QPointF(14, 370))
    # 리셋 버튼
    rect(p, QRectF(26, 8, 28, 28), QColor('#9b978f'), QColor('#5e5b55'), 1.5)
    p.setPen(QPen(QColor('#3b3936'), 1))
    p.setBrush(QColor('#6e2b27'))
    p.drawEllipse(QPointF(40, 22), 8, 8)
    text(p, 'RESET', 40, 44, 7, SILK_DIM)
    # 16U2 칩과 ICSP(USB 쪽)
    rect(p, QRectF(86, 92, 34, 34), CHIP, QColor('#050505'), 1)
    p.setPen(QPen(METAL_DARK, 1))
    for k in range(7):
        p.drawLine(QPointF(90 + k * 4.5, 89), QPointF(90 + k * 4.5, 92))
        p.drawLine(QPointF(90 + k * 4.5, 126), QPointF(90 + k * 4.5, 129))
    icsp(p, 74, 46)
    # 크리스털과 레귤레이터
    rect(p, QRectF(150, 196, 46, 16), QColor('#b9b5ac'), QColor('#7b7871'), 7)
    text(p, '16.000', 173, 204, 6.5, QColor('#55524c'), mono=True)
    rect(p, QRectF(84, 306, 30, 34), QColor('#1b1b1d'), QColor('#050505'), 1)
    rect(p, QRectF(80, 300, 38, 10), QColor('#9c988f'), QColor('#55524c'), 1)
    # 커패시터
    for cx, cy in ((134, 324), (162, 324)):
        p.setPen(QPen(QColor('#4d4d50'), 1))
        p.setBrush(QColor('#26272a'))
        p.drawEllipse(QPointF(cx, cy), 11, 11)
        p.setPen(QPen(QColor('#8e8b84'), 1))
        p.drawLine(QPointF(cx - 7, cy), QPointF(cx + 7, cy))
    # ATmega328P (DIP-28)
    chip = QRectF(214, 286, 262, 54)
    p.setPen(QPen(METAL, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    for k in range(14):
        x = chip.left() + 15 + k * 17.6
        p.drawLine(QPointF(x, chip.top() - 5), QPointF(x, chip.top()))
        p.drawLine(QPointF(x, chip.bottom()), QPointF(x, chip.bottom() + 5))
    rect(p, chip, CHIP, QColor('#050505'), 1.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor('#0b0b0c'))
    p.drawPie(QRectF(chip.left() - 7, chip.center().y() - 7, 14, 14), -90 * 16, 180 * 16)
    text(p, 'ATMEGA328P', chip.center().x(), chip.center().y(), 9, QColor('#6d6b66'), mono=True)
    icsp(p, 496, 200, vertical=True)
    text(p, 'ICSP', 507, 258, 7, SILK_DIM)
    # 글자
    text(p, 'UNO', 330, 170, 44, SILK, bold=True)
    text(p, 'R3', 420, 158, 11, SILK_DIM)
    text(p, 'DIGITAL (PWM~)', 310, 108, 9, SILK_DIM)
    text(p, 'POWER', 286, 318 - 54, 9, SILK_DIM)
    text(p, 'ANALOG IN', 446, 264, 9, SILK_DIM)
    # 상태 LED
    smd_led(p, 222, 132, st.get('L', False), 'orange')
    text(p, 'L', 236, 132, 8, SILK)
    smd_led(p, 222, 150, st.get('TX', False), 'orange')
    text(p, 'TX', 239, 150, 8, SILK)
    smd_led(p, 222, 166, st.get('RX', False), 'orange')
    text(p, 'RX', 239, 166, 8, SILK)
    smd_led(p, 478, 132, st.get('ON', True), 'green')
    text(p, 'ON', 496, 132, 8, SILK)
    # 헤더
    top = [pp for pp in B.UNO_PINS if pp[3] < H / 2]
    bottom = [pp for pp in B.UNO_PINS if pp[3] > H / 2]
    female_header(p, [pp for pp in top if pp[2] < 340])
    female_header(p, [pp for pp in top if pp[2] >= 340])
    female_header(p, [pp for pp in bottom if pp[2] < 380])
    female_header(p, [pp for pp in bottom if pp[2] >= 380])
    pin_states = st.get('pins', {})
    for pid, label, x, y, node in B.UNO_PINS:
        lab = label
        if pid.startswith('D') and pid[1:].isdigit():
            n = int(pid[1:])
            lab = ('~' if n in B.PWM_PINS else '') + str(n)
            if n <= 1:
                lab = f'{n} {"RX" if n == 0 else "TX"}'
        elif pid == '3V3':
            lab = '3.3V'
        if y < H / 2:
            text(p, lab, x, y + 18, 8, SILK, align='l', rot=90)
        else:
            text(p, lab, x, y - 18, 8, SILK, align='l', rot=-90)
        s = pin_states.get(pid)
        if s:
            mark = QColor(theme.TEXT) if s == 'hi' else QColor(theme.DIM)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(mark)
            off = -12 if y < H / 2 else 12
            p.drawRect(QRectF(x - 3, y + off - 1, 6, 2))


def female_header(p, pins):
    if not pins:
        return
    xs = [pp[2] for pp in pins]
    y = pins[0][3]
    rect(p, QRectF(min(xs) - 10, y - 10, max(xs) - min(xs) + 20, 20), PLASTIC, PLASTIC_EDGE, 1)
    for pp in pins:
        x = pp[2]
        rect(p, QRectF(x - 4, y - 4, 8, 8), QColor('#050506'), QColor('#3a3a3d'), 0.5, 1)


def icsp(p, x, y, vertical=False):
    for i in range(3):
        for j in range(2):
            px, py = (x + j * 10, y + i * 10) if vertical else (x + i * 10, y + j * 10)
            rect(p, QRectF(px - 4, py - 4, 8, 8), PLASTIC, PLASTIC_EDGE, 0)
            rect(p, QRectF(px - 1.6, py - 1.6, 3.2, 3.2), GOLD, None, 0)


# ---------------------------------------------------------------- 모듈
def paint_module(p, mod):
    fn = PAINTERS.get(mod.TYPE)
    if fn is not None:
        fn(p, mod)


def module_rect(mod):
    w, h = mod.SIZE
    xs = [x for _, x, _ in mod.PINS] + [0, w]
    ys = [y for _, _, y in mod.PINS] + [0, h]
    return QRectF(min(xs) - 6, min(ys) - 6, max(xs) - min(xs) + 12, max(ys) - min(ys) + 12)


def pin_dir(owner, pin, mod=None):
    """점퍼선이 핀에서 나가는 방향."""
    if owner == 'uno':
        y = B.UNO_PIN_POS[pin][1]
        return (0, -1) if y < B.BOARD_H / 2 else (0, 1)
    if mod is not None and mod.TYPE == 'resistor':
        return (-1, 0) if pin == '1' else (1, 0)
    return (0, 1)


def p_led(p, mod):
    color = mod.props.get('color', 'red')
    level = mod.state.get('level', 0.0)
    lead(p, 9, 38, 9, 70)
    lead(p, 21, 38, 21, 64)
    # 몸체: 렌즈 + 테두리
    base = QColor(LED_OFF[color])
    on = QColor(LED_ON[color])
    c = mix(base, on, min(1.0, 0.25 + level * 0.75)) if level > 0 else base
    c.setAlpha(235)
    body = QPainterPath()
    body.moveTo(3, 36)
    body.lineTo(3, 14)
    body.arcTo(QRectF(3, 2, 24, 24), 180, -180)
    body.lineTo(27, 36)
    body.closeSubpath()
    p.setPen(QPen(mix(base, QColor('#000000'), 0.4), 1))
    p.setBrush(c)
    p.drawPath(body)
    rect(p, QRectF(1, 34, 28, 5), mix(base, QColor('#000000'), 0.1), mix(base, QColor('#000000'), 0.5), 1)
    if level > 0:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, int(70 + 110 * level)))
        p.drawEllipse(QRectF(10, 9, 10, 10))
    # 내부 리드프레임(실물처럼 안쪽 금속)
    p.setPen(QPen(QColor(40, 40, 40, 110), 1.2))
    p.drawLine(QPointF(10, 34), QPointF(10, 22))
    p.drawLine(QPointF(20, 34), QPointF(20, 18))
    text(p, '+', 2, 76, 11, QColor(theme.TEXT), bold=True)
    text(p, '−', 28, 70, 11, QColor(theme.TEXT), bold=True)


def p_resistor(p, mod):
    lead(p, 0, 9, 80, 9)
    body = QRectF(18, 3, 44, 12)
    rect(p, body, QColor('#c9b48c'), QColor('#8a7a5a'), 5)
    ohms = int(mod.props.get('ohms', 220))
    bands = {220: ['#c4473c', '#c4473c', '#5a3a25'], 330: ['#d48a3c', '#d48a3c', '#5a3a25'],
             1000: ['#5a3a25', '#1e1e1e', '#c4473c'], 10000: ['#5a3a25', '#1e1e1e', '#d48a3c']}[ohms]
    for k, col in enumerate(bands + ['#b8963e']):
        x = 24 + k * 8 + (6 if k == 3 else 0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(col))
        p.drawRect(QRectF(x, 3.5, 3.5, 11))
    label = {220: '220Ω', 330: '330Ω', 1000: '1kΩ', 10000: '10kΩ'}[ohms]
    text(p, label, 40, -7, 10, QColor(theme.TEXT))


def p_rgb_led(p, mod):
    pcb(p, 64, 58, PCB_BLACK, QColor('#0c0c0d'))
    r, g, b = mod.state.get('rgb', [0, 0, 0])
    c = QColor(int(70 + 185 * r), int(70 + 185 * g), int(70 + 185 * b)) if (r or g or b) else QColor('#7a7872')
    c.setAlpha(230)
    p.setPen(QPen(QColor('#3c3b38'), 1))
    p.setBrush(c)
    p.drawEllipse(QPointF(32, 24), 13, 13)
    if r or g or b:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 130))
        p.drawEllipse(QPointF(29, 21), 4, 4)
    header(p, mod, 58)


def p_button(p, mod):
    pressed = mod.props.get('pressed')
    lead(p, 15, 46, 15, 66)
    lead(p, 35, 46, 35, 66)
    rect(p, QRectF(3, 3, 44, 44), QColor('#1d1e21'), QColor('#0b0b0c'), 2)
    p.setPen(QPen(METAL_DARK, 1))
    p.setBrush(METAL)
    for cx, cy in ((9, 9), (41, 9), (9, 41), (41, 41)):
        p.drawEllipse(QPointF(cx, cy), 2.4, 2.4)
    cap = {'black': '#2b2c30', 'red': '#9e3a32', 'blue': '#2f5a92', 'yellow': '#b39a3a'}[mod.props.get('cap', 'black')]
    capc = QColor(cap)
    if pressed:
        capc = mix(capc, QColor('#000000'), 0.35)
    p.setPen(QPen(mix(capc, QColor('#000000'), 0.5), 1))
    p.setBrush(capc)
    rr = 12 if not pressed else 10.5
    p.drawEllipse(QPointF(25, 25), rr, rr)
    if not pressed:
        p.setPen(QPen(mix(capc, QColor('#ffffff'), 0.18), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(25, 25), 8, 8)


def p_slide_switch(p, mod):
    pos = mod.props.get('pos', 0)
    for _, x, y in mod.PINS:
        lead(p, x, 36, x, y)
    rect(p, QRectF(2, 12, 56, 24), QColor('#a9a59c'), QColor('#66635d'), 1.5)
    rect(p, QRectF(10, 17, 40, 14), QColor('#2a2a2d'), QColor('#101012'), 1)
    kx = 12 if pos == 0 else 31
    rect(p, QRectF(kx, 2, 17, 26), QColor('#2c2d31'), QColor('#0d0d0e'), 1.5)
    p.setPen(QPen(QColor('#4a4b50'), 1))
    for k in range(3):
        p.drawLine(QPointF(kx + 4, 8 + k * 5), QPointF(kx + 13, 8 + k * 5))
    for name, x, y in mod.PINS:
        text(p, name if name != 'COM' else 'C', x + 7, 47, 9.5, QColor(theme.TEXT), bold=True)


def p_toggle(p, mod):
    on = mod.props.get('on')
    lead(p, 15, 46, 15, 66)
    lead(p, 35, 46, 35, 66)
    rect(p, QRectF(5, 18, 40, 28), QColor('#24252a'), QColor('#0c0c0d'), 2)
    p.setPen(QPen(METAL_DARK, 1))
    p.setBrush(METAL)
    p.drawEllipse(QPointF(25, 22), 8, 5)
    tip = QPointF(36, 2) if on else QPointF(14, 2)
    p.setPen(QPen(METAL, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(25, 22), tip)
    text(p, 'ON' if on else 'OFF', 25, 36, 8, SILK_DIM)


def p_pot(p, mod):
    v = mod.props.get('value', 512) / 1023.0
    for _, x, y in mod.PINS:
        lead(p, x, 56, x, y, METAL, 2.2)
    rect(p, QRectF(2, 8, 60, 50), PCB_BLUE, PCB_BLUE_EDGE, 3)
    p.setPen(QPen(QColor('#5f5c55'), 1))
    p.setBrush(QColor('#8d8981'))
    p.drawEllipse(QPointF(32, 32), 21, 21)
    p.setBrush(QColor('#3a3b3f'))
    p.setPen(QPen(QColor('#1a1a1c'), 1))
    p.drawEllipse(QPointF(32, 32), 15, 15)
    ang = math.radians(225 - 270 * v)
    p.setPen(QPen(SILK, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(32, 32), QPointF(32 + 12 * math.cos(ang), 32 - 12 * math.sin(ang)))
    readout(p, f'{mod.props.get("value", 512)}', 32, -12)
    for name, x, y in mod.PINS:
        text(p, name, x + 7, 68, 9.5, QColor(theme.TEXT), bold=True)


def p_joystick(p, mod):
    pcb(p, 100, 84, PCB_BLACK, QColor('#0c0c0d'))
    rect(p, QRectF(18, 6, 64, 64), QColor('#2c2d30'), QColor('#0c0c0d'), 4)
    dx = (mod.props.get('x', 512) - 512) / 512 * 14
    dy = (mod.props.get('y', 512) - 512) / 512 * 14
    p.setPen(QPen(QColor('#101011'), 1))
    p.setBrush(QColor('#1a1a1c'))
    p.drawEllipse(QPointF(50, 38), 25, 25)
    cap = QColor('#3b3c40') if not mod.props.get('pressed') else QColor('#2a2b2e')
    p.setBrush(cap)
    p.drawEllipse(QPointF(50 + dx, 38 + dy), 17, 17)
    p.setPen(QPen(QColor('#505156'), 1))
    for k in range(4):
        a = k * math.pi / 2 + math.pi / 4
        p.drawLine(QPointF(50 + dx + 8 * math.cos(a), 38 + dy + 8 * math.sin(a)),
                   QPointF(50 + dx + 13 * math.cos(a), 38 + dy + 13 * math.sin(a)))
    header(p, mod, 84)


def p_buzzer(p, mod, active=False):
    sounding = bool(mod.state.get('freq'))
    lead(p, 15, 46, 15, 66)
    lead(p, 35, 46, 35, 66)
    p.setPen(QPen(QColor('#09090a'), 1))
    p.setBrush(QColor('#1d1d1f'))
    p.drawEllipse(QPointF(25, 25), 22, 22)
    p.setBrush(QColor('#111112') if not active else QColor('#18181a'))
    p.drawEllipse(QPointF(25, 25), 5, 5)
    if active:
        p.setPen(QPen(QColor('#2f2f33'), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(25, 25), 15, 15)
    else:
        rect(p, QRectF(13, 46, 24, 4), PCB_GREEN, PCB_GREEN_EDGE, 0)
    text(p, '+', 6, 4, 11, QColor(theme.TEXT), bold=True)
    if sounding:
        p.setPen(QPen(QColor(theme.TEXT), 1.3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for r in (30, 35):
            p.drawArc(QRectF(25 - r, 25 - r, 2 * r, 2 * r), 20 * 16, 50 * 16)
        readout(p, f'{mod.state["freq"]} Hz', 25, -14)
    elif mod.state.get('dc'):
        readout(p, '소리 없음', 25, -14)


def p_servo(p, mod):
    # 몸체(파란 반투명 플라스틱)와 선 세 가닥
    for (name, x, y), col in zip(mod.PINS, ('#6b4a32', '#b7443a', '#d3893a')):
        p.setPen(QPen(QColor(col), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        p.drawLine(QPointF(x, 60), QPointF(x, y - 6))
    rect(p, QRectF(20, 70, 56, 8), PLASTIC, PLASTIC_EDGE, 1)
    rect(p, QRectF(0, 18, 96, 42), QColor('#2d4f86'), QColor('#1b3157'), 2)
    rect(p, QRectF(-8, 26, 112, 8), QColor('#2d4f86'), QColor('#1b3157'), 1)
    p.setPen(QPen(QColor('#1b3157'), 1))
    p.setBrush(QColor('#335a96'))
    p.drawEllipse(QPointF(28, 18), 16, 16)
    text(p, 'SG90', 68, 46, 9, QColor(210, 220, 235, 170), bold=True)
    ang = mod.state.get('angle', 90.0)
    # 혼: 0°=오른쪽, 180°=왼쪽
    a = math.radians(180 - ang)
    cx, cy = 28, 18
    tip = QPointF(cx + 26 * math.cos(a), cy - 26 * math.sin(a))
    p.setPen(QPen(WHITE_PLASTIC, 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(cx, cy), tip)
    p.setPen(QPen(QColor('#9a968e'), 1))
    p.setBrush(WHITE_PLASTIC)
    p.drawEllipse(QPointF(cx, cy), 6, 6)
    readout(p, f'{ang:.0f}°', 82, -12)
    for (name, x, y) in mod.PINS:
        text(p, {'GND': 'G', '5V': '+', 'SIG': 'S'}[name], x + 8, 66, 9.5, QColor(theme.TEXT), bold=True)


def p_dc_motor(p, mod):
    pcb(p, 120, 72, PCB_RED, QColor('#521d1b'))
    # 드라이버 칩과 단자대
    rect(p, QRectF(52, 22, 20, 14), CHIP, None, 1)
    rect(p, QRectF(84, 8, 28, 34), QColor('#2f6b45'), QColor('#1d4a2e'), 1)
    text(p, 'L9110S', 62, 46, 7.5, SILK_DIM)
    header(p, mod, 72)
    # 모터와 팬(보드 왼쪽 위로 붙은 모습)
    rect(p, QRectF(-34, -2, 40, 30), QColor('#a7a39a'), QColor('#6a675f'), 4)
    ang = math.radians(mod.state.get('angle', 0.0))
    cx, cy = -14, 13
    p.setPen(QPen(QColor('#3a3b3e'), 1))
    p.setBrush(QColor(200, 196, 188, 200))
    for k in range(3):
        a = ang + k * 2 * math.pi / 3
        blade = QPolygonF([QPointF(cx, cy),
                           QPointF(cx + 22 * math.cos(a - 0.25), cy + 22 * math.sin(a - 0.25)),
                           QPointF(cx + 22 * math.cos(a + 0.25), cy + 22 * math.sin(a + 0.25))])
        p.drawPolygon(blade)
    p.setBrush(QColor('#2a2b2e'))
    p.drawEllipse(QPointF(cx, cy), 4, 4)
    sp = mod.state.get('speed', 0.0)
    if abs(sp) < 0.01:
        s = '정지'
    else:
        s = f'{abs(sp) * 100:.0f}% ' + ('정방향' if sp > 0 else '역방향')
    readout(p, s, 70, -14)


def p_relay(p, mod):
    pcb(p, 130, 66, PCB_BLUE, PCB_BLUE_EDGE)
    on = mod.state.get('on')
    rect(p, QRectF(62, 8, 60, 36), QColor('#2a5ea8'), QColor('#183a6c'), 1)
    text(p, 'SRD-05VDC', 92, 20, 6.5, QColor(220, 230, 245, 170), mono=True)
    text(p, 'COM–NO' if on else 'COM–NC', 92, 33, 8, SILK)
    smd_led(p, 18, 20, on, 'red')
    text(p, 'IN', 18, 32, 8, SILK_DIM, bold=True)
    header(p, mod, 66)


def p_lcd(p, mod):
    lcd = mod.lcd
    powered = mod.state.get('powered')
    pcb(p, 300, 112, PCB_GREEN, PCB_GREEN_EDGE)
    for hx, hy in ((8, 104),):
        p.setPen(QPen(METAL_DARK, 1))
        p.setBrush(QColor('#101114'))
        p.drawEllipse(QPointF(hx, hy), 2.6, 2.6)
    p.drawEllipse(QPointF(292, 104), 2.6, 2.6)
    frame = QRectF(14, 14, 272, 82)
    rect(p, frame, QColor('#141516'), QColor('#050505'), 2)
    glass = QRectF(28, 26, 244, 58)
    if powered and lcd.backlight:
        bg = QColor('#93ac3c')
        ink = QColor('#1f2a0e')
        cell = QColor(128, 152, 50)
    elif powered:
        bg = QColor('#4b5a26')
        ink = QColor('#26300f')
        cell = QColor(70, 84, 34)
    else:
        bg = QColor('#3c4521')
        ink = None
        cell = QColor(56, 64, 30)
    rect(p, glass, bg, None, 1)
    cw, ch = 14.0, 22.0
    x0 = glass.left() + (glass.width() - 16 * cw) / 2 + 0.5
    y0 = glass.top() + 6
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(cell)
    for r in range(2):
        for c in range(16):
            p.drawRect(QRectF(x0 + c * cw, y0 + r * (ch + 3), cw - 2, ch))
    if powered:
        if not lcd.initialized:
            p.setBrush(QColor(30, 40, 12, 200))
            for c in range(16):
                p.drawRect(QRectF(x0 + c * cw, y0, cw - 2, ch))
        elif lcd.display_on:
            rows = lcd.visible()
            p.setFont(font(17, mono=True))
            p.setPen(ink)
            for r, line in enumerate(rows):
                for c, chx in enumerate(line):
                    if ord(chx) < 8:
                        draw_custom_char(p, lcd.custom.get(ord(chx)), x0 + c * cw, y0 + r * (ch + 3), cw - 2, ch, ink)
                        continue
                    if chx == ' ':
                        continue
                    if chx == '\xdf':
                        chx = '°'
                    p.drawText(QRectF(x0 + c * cw, y0 + r * (ch + 3), cw - 2, ch),
                               Qt.AlignmentFlag.AlignCenter, chx)
            if lcd.show_cursor and 0 <= lcd.col - lcd.shift < 16:
                p.fillRect(QRectF(x0 + (lcd.col - lcd.shift) * cw, y0 + lcd.row * (ch + 3) + ch - 2, cw - 2, 2), ink)
    # 뒷면 I2C 보드의 헤더(왼쪽 아래)
    rect(p, QRectF(4, 108, 90, 4), PCB_BLACK, None, 0)
    header(p, mod, 112, label_y=103)
    text(p, f'0x{int(mod.props.get("addr", 0x27)):02X}', 270, 104, 7.5, SILK_DIM, mono=True)


def draw_custom_char(p, data, x, y, w, h, ink):
    if not data:
        return
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ink)
    dw, dh = w / 5.0, h / 8.0
    for r, bits in enumerate(data):
        for c in range(5):
            if bits & (0x10 >> c):
                p.drawRect(QRectF(x + c * dw + 0.3, y + r * dh + 0.3, dw - 0.6, dh - 0.6))
    p.restore()


SEG_SHAPES = {
    'a': [(0.15, 0.0), (0.85, 0.0)], 'b': [(1.0, 0.05), (0.95, 0.47)], 'c': [(0.95, 0.53), (0.9, 0.95)],
    'd': [(0.05, 1.0), (0.75, 1.0)], 'e': [(0.05, 0.53), (0.0, 0.95)], 'f': [(0.1, 0.05), (0.05, 0.47)],
    'g': [(0.1, 0.5), (0.85, 0.5)],
}


def draw_digit(p, x, y, w, h, segs, on_color, off_color, thick=5.0, dp=0.0):
    """segs: 'abcdefg' 순서의 밝기 목록. 약간 기울인 실물 모양."""
    for k, name in enumerate('abcdefg'):
        (x1, y1), (x2, y2) = SEG_SHAPES[name]
        lv = segs[k]
        col = mix(off_color, on_color, min(1.0, 0.2 + lv * 0.8)) if lv > 0 else off_color
        sk = 0.12 * w
        p.setPen(QPen(col, thick, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(x + x1 * w + sk * (1 - y1), y + y1 * h), QPointF(x + x2 * w + sk * (1 - y2), y + y2 * h))
    col = mix(off_color, on_color, 0.2 + dp * 0.8) if dp > 0 else off_color
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(col)
    p.drawEllipse(QPointF(x + w + 5, y + h), thick / 2 + 0.6, thick / 2 + 0.6)


def p_seg7(p, mod):
    lit = mod.state.get('lit', [0] * 8)
    for _, x, y in mod.PINS:
        lead(p, x, 104, x, y, METAL, 1.6)
    rect(p, QRectF(0, 2, 116, 102), QColor('#1c1c1e'), QColor('#070708'), 2)
    draw_digit(p, 36, 12, 38, 72, lit[:7], QColor('#ff4a3a'), QColor('#3a1d1b'), 7, lit[7])
    for name, x, y in mod.PINS:
        text(p, name if name != 'COM' else 'C', x, 96, 9, QColor('#8d8a83'), bold=True)
    text(p, 'CC' if mod.props.get('common') == 'cathode' else 'CA', 104, 12, 7.5, QColor('#77746d'))


def p_tm1637(p, mod):
    pcb(p, 170, 70, PCB_BLUE, PCB_BLUE_EDGE)
    rect(p, QRectF(12, 8, 146, 52), QColor('#18181a'), QColor('#060606'), 1)
    st = mod.state
    on = mod.state.get('powered') and st.get('on', True)
    bright = 0.45 + 0.55 * st.get('brightness', 7) / 7
    oncol = mix(QColor('#3a1d1b'), QColor('#ff4a3a'), bright)
    for k in range(4):
        sv = st['segs'][k] if on else 0
        segs = [1.0 if sv & (1 << b) else 0.0 for b in range(7)]
        x = 22 + k * 34 + (6 if k >= 2 else 0)
        draw_digit(p, x, 14, 20, 38, segs, oncol, QColor('#311a19'), 4, 0)
    colon = on and (st['segs'][1] & 0x80)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(oncol if colon else QColor('#311a19'))
    p.drawEllipse(QPointF(87, 26), 2.4, 2.4)
    p.drawEllipse(QPointF(87, 42), 2.4, 2.4)
    header(p, mod, 70, label_y=64)


def p_matrix(p, mod):
    pcb(p, 130, 150, PCB_BLUE, PCB_BLUE_EDGE, holes=False)
    rect(p, QRectF(8, 6, 114, 114), QColor('#141416'), QColor('#050505'), 1)
    st = mod.state
    on = mod.state.get('powered') and not st.get('shutdown', True)
    lvl = 0.45 + 0.55 * st.get('intensity', 8) / 15
    oncol = mix(QColor('#40201e'), QColor('#ff4a3a'), lvl)
    offcol = QColor('#2c1c1b')
    p.setPen(Qt.PenStyle.NoPen)
    for r in range(8):
        bits = st['rows'][r] if on else 0
        for c in range(8):
            p.setBrush(oncol if bits & (0x80 >> c) else offcol)
            p.drawEllipse(QPointF(15 + c * 14 + 0.5, 13 + r * 14 + 0.5), 5, 5)
    rect(p, QRectF(42, 124, 46, 14), CHIP, None, 1)
    text(p, 'MAX7219', 65, 131, 6.5, QColor('#6d6b66'), mono=True)
    header(p, mod, 150, label_y=144)


def p_hcsr04(p, mod):
    pcb(p, 130, 64, PCB_BLUE, PCB_BLUE_EDGE)
    for cx in (30, 100):
        p.setPen(QPen(QColor('#77746d'), 1))
        p.setBrush(QColor('#b4b0a6'))
        p.drawEllipse(QPointF(cx, 26), 22, 22)
        p.setBrush(QColor('#1a1a1c'))
        p.setPen(QPen(QColor('#3a3a3d'), 1))
        p.drawEllipse(QPointF(cx, 26), 16, 16)
        p.setPen(QPen(QColor('#2c2c30'), 1))
        for k in range(-2, 3):
            p.drawLine(QPointF(cx - 12, 26 + k * 4), QPointF(cx + 12, 26 + k * 4))
    rect(p, QRectF(56, 8, 18, 9), QColor('#c8c4bb'), QColor('#77746d'), 3)
    silk_title(p, 'HC-SR04', 65, 48, 8)
    header(p, mod, 64, label_y=57)
    readout(p, f'{float(mod.props.get("distance", 30)):.0f} cm', 65)


def p_dht(p, mod):
    model = mod.props.get('model', 'DHT11')
    body = QColor('#3a77b5') if model == 'DHT11' else QColor('#d9d6cf')
    edge = QColor('#24527e') if model == 'DHT11' else QColor('#8f8b83')
    rect(p, QRectF(0, 52, 56, 18), PCB_BLUE, PCB_BLUE_EDGE, 2)
    rect(p, QRectF(6, 0, 44, 56), body, edge, 2)
    grid = QColor(0, 0, 0, 70) if model == 'DHT22' else QColor(0, 0, 0, 90)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grid)
    for r in range(5):
        for c in range(4):
            p.drawRect(QRectF(12 + c * 9, 6 + r * 9, 5, 5))
    text(p, model, 28, 50, 7.5, QColor(255, 255, 255, 190) if model == 'DHT11' else QColor('#55524c'))
    header(p, mod, 70, labels=False)
    for name, x, y in mod.PINS:
        text(p, {'VCC': '+', 'DATA': 'S', 'GND': '−'}[name], x, 62, 9.5, SILK, bold=True)
    readout(p, f'{float(mod.props.get("temp", 24)):.0f}°C · {float(mod.props.get("humidity", 45)):.0f}%', 28)


def sensor_board(p, mod, w, h, title):
    pcb(p, w, h, PCB_BLUE, PCB_BLUE_EDGE)
    smd_led(p, 10, 14, bool(mod.state.get('powered')), 'red', 6, 4)
    out_on = bool(mod.state.get('out')) if mod.TYPE != 'ir_obstacle' else (mod.state.get('powered') and not mod.state.get('out'))
    smd_led(p, 10, 26, bool(mod.state.get('powered')) and bool(out_on), 'green', 6, 4)
    text(p, 'PWR', 16, 14, 7, SILK_DIM, align='l')
    text(p, 'OUT', 16, 26, 7, SILK_DIM, align='l')
    if title:
        silk_title(p, title, 30 if title == 'SOUND' else w / 2, h - 22)
    header(p, mod, h)


def p_ldr(p, mod):
    sensor_board(p, mod, 90, 60, 'LDR')
    light = mod.props.get('light', 60) / 100.0
    p.setPen(QPen(QColor('#5d4a30'), 1))
    p.setBrush(mix(QColor('#7a5a2c'), QColor('#d8b46a'), light))
    p.drawEllipse(QPointF(62, 22), 12, 12)
    p.setPen(QPen(QColor('#4a2e18'), 1.6))
    path = QPainterPath(QPointF(54, 18))
    for k in range(4):
        path.lineTo(70, 18 + k * 2.6)
        path.lineTo(54, 19.3 + k * 2.6)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    rect(p, QRectF(36, 10, 12, 12), QColor('#2a5ea8'), QColor('#183a6c'), 1)
    readout(p, f'밝기 {mod.props.get("light", 60)}%', 45)


def p_sound(p, mod):
    sensor_board(p, mod, 90, 60, 'SOUND')
    p.setPen(QPen(QColor('#77746d'), 1))
    p.setBrush(QColor('#b9b5ab'))
    p.drawEllipse(QPointF(64, 24), 15, 15)
    p.setBrush(QColor('#202022'))
    p.drawEllipse(QPointF(64, 24), 11, 11)
    rect(p, QRectF(36, 10, 12, 12), QColor('#2a5ea8'), QColor('#183a6c'), 1)
    readout(p, f'소리 {mod.props.get("level", 10)}%', 45)


def p_pir(p, mod):
    pcb(p, 72, 72, PCB_GREEN, PCB_GREEN_EDGE)
    p.setPen(QPen(QColor('#b2aea5'), 1))
    p.setBrush(QColor('#ece8df'))
    p.drawEllipse(QPointF(36, 34), 28, 28)
    p.setPen(QPen(QColor('#cfcbc2'), 1))
    for r in (8, 15, 22):
        p.drawEllipse(QPointF(36, 34), r, r)
    if mod.state.get('out') and mod.state.get('powered'):
        p.setPen(QPen(QColor(theme.MUTED), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(36, 34), 31, 31)
    header(p, mod, 72)
    readout(p, '감지됨' if (mod.state.get('out') and mod.state.get('powered')) else '감지 없음', 36)


def p_tilt(p, mod):
    sensor_board(p, mod, 70, 50, '')
    tilted = mod.props.get('tilted')
    p.save()
    p.translate(50, 20)
    p.rotate(-35 if tilted else 0)
    rect(p, QRectF(-8, -12, 16, 24), QColor('#2a2b2e'), QColor('#0c0c0d'), 3)
    p.restore()
    readout(p, '기울어짐' if tilted else '바로 섬', 35)


def p_ir(p, mod):
    sensor_board(p, mod, 90, 50, '')
    # 적외선 송수신 LED(오른쪽으로 돌출)
    for k, col in enumerate(('#1b1b1d', '#d8d4cb')):
        y = 14 + k * 18
        lead(p, 84, y, 96, y)
        rect(p, QRectF(96, y - 6, 18, 12), QColor(col), QColor('#555'), 4)
    rect(p, QRectF(40, 8, 14, 14), QColor('#2a5ea8'), QColor('#183a6c'), 1)
    silk_title(p, 'IR', 66, 16)
    readout(p, '물체 있음' if mod.props.get('obstacle') else '물체 없음', 45)


def p_temp(p, mod):
    for _, x, y in mod.PINS:
        lead(p, x, 30, x, y, METAL, 1.6)
    path = QPainterPath()
    path.moveTo(0, 30)
    path.lineTo(0, 12)
    path.arcTo(QRectF(0, 0, 40, 24), 180, -180)
    path.lineTo(40, 30)
    path.closeSubpath()
    p.setPen(QPen(QColor('#050505'), 1))
    p.setBrush(QColor('#1b1b1d'))
    p.drawPath(path)
    text(p, mod.props.get('model', 'LM35'), 20, 20, 7.5, QColor('#8a877f'), mono=True)
    for name, x, y in mod.PINS:
        text(p, {'VS': '+', 'OUT': 'V', 'GND': '−'}[name], x + 7, 42, 9.5, QColor(theme.TEXT), bold=True)
    readout(p, f'{float(mod.props.get("temp", 25)):.0f}°C', 20)


PAINTERS = {
    'led': p_led, 'resistor': p_resistor, 'rgb_led': p_rgb_led, 'button': p_button,
    'slide_switch': p_slide_switch, 'toggle': p_toggle, 'pot': p_pot, 'joystick': p_joystick,
    'buzzer_passive': lambda p, m: p_buzzer(p, m, False), 'buzzer_active': lambda p, m: p_buzzer(p, m, True),
    'servo': p_servo, 'dc_motor': p_dc_motor, 'relay': p_relay, 'lcd1602': p_lcd, 'seg7': p_seg7,
    'tm1637': p_tm1637, 'matrix': p_matrix, 'hcsr04': p_hcsr04, 'dht': p_dht, 'ldr': p_ldr,
    'sound': p_sound, 'pir': p_pir, 'tilt': p_tilt, 'ir_obstacle': p_ir, 'temp_sensor': p_temp,
}


def extra_rect(mod):
    """모듈 몸체 밖으로 나가는 그림(글자, 모터 팬 등)까지 포함한 영역."""
    r = module_rect(mod)
    r = r.united(QRectF(-30, -26, mod.SIZE[0] + 60, 26))
    if mod.TYPE == 'dc_motor':
        r = r.united(QRectF(-40, -12, 50, 50))
    if mod.TYPE == 'servo':
        r = r.united(QRectF(-12, -12, 120, 30))
    if mod.TYPE == 'ir_obstacle':
        r = r.united(QRectF(80, 0, 40, 40))
    if mod.TYPE in ('buzzer_passive', 'buzzer_active'):
        r = r.united(QRectF(-24, -26, 98, 40))
    return r.adjusted(-2, -2, 2, 2)


def interactive_hit(mod, x, y):
    """캔버스에서 눌러 조작할 수 있는 곳: 'press'(누르는 동안) 또는 'toggle'(누를 때마다)."""
    t = mod.TYPE
    if t == 'button' and (x - 25) ** 2 + (y - 25) ** 2 <= 14 ** 2:
        return 'press'
    if t == 'joystick' and (x - 50) ** 2 + (y - 38) ** 2 <= 18 ** 2:
        return 'press'
    if t == 'slide_switch' and 0 <= x <= 60 and 0 <= y <= 36:
        return 'toggle'
    if t == 'toggle' and 0 <= x <= 50 and 0 <= y <= 46:
        return 'toggle'
    return None


_ICONS = {}


def module_icon(type_id, size=34):
    """부품 목록에 쓰는 작은 그림(투명 바탕)."""
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    from . import modules as M
    key = (type_id, size)
    if key in _ICONS:
        return _ICONS[key]
    mod = M.TYPES[type_id]('icon')
    r = module_rect(mod)
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    k = (size * 2 - 4) / max(r.width(), r.height())
    p.translate(size - r.center().x() * k, size - r.center().y() * k)
    p.scale(k, k)
    paint_module(p, mod)
    p.end()
    pm.setDevicePixelRatio(2)
    icon = QIcon(pm)
    _ICONS[key] = icon
    return icon
