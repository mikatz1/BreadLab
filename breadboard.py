"""브레드보드 작업 공간: 보드 편집 + 전원 공급기·함수 발생기·오실로스코프."""
import copy
import csv
import json
import math
import re
import time
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import (QAction, QActionGroup, QBrush, QColor, QFont, QFontMetricsF, QIcon, QImage, QKeySequence, QPixmap, QPainter, QPainterPath,
                           QPainterPathStroker, QPen)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFrame, QGridLayout, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem, QGraphicsScene,
                               QGraphicsView, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMenu, QMessageBox,
                               QPushButton, QScrollArea, QSlider, QSplitter, QVBoxLayout, QWidget)

import theme
from circuit_core import (BOARD_SET, COLOR_NAMES, FG_WAVES, HOLES, IC_KINDS, NAMES, PARSERS, PIN_NAMES, PREFIX,
                          THREE_PIN, dip_pins, ic_anchor,
                          BLACK, BLUE, GREEN, RED, WHITE, YELLOW, Part, Simulator, designators,
                          default_instruments, empty_result, format_si, make_document, net_map, parse_beta,
                          parse_capacitance, parse_resistance, resistor_bands, validate_document)
from examples import EXAMPLES
from instruments import CH_COLORS, FgPanel, PsuPanel, Scope
from workspace import Workspace

FILE_FILTER = 'BreadLab 회로 (*.bd *.json)'
HISTORY_LIMIT = 80
DANGER_WORDS = ('단락', '망가', '초과', '넘습니다', '역전압')
SNAP = 13.0
TICK_MS = 20
WIRE_COLORS = [RED, BLACK, BLUE, GREEN, YELLOW, WHITE]
LED_COLORS = [RED, YELLOW, GREEN, BLUE, WHITE]
BAND = ['#1b1b1b', '#7b4a2a', '#c8372d', '#e07b24', '#e8c227', '#3f8f3f', '#2f62b3', '#7b4fa6', '#8c8c8c', '#f2f2f2']
GOLD, SILVER = '#c9a227', '#b9b9b9'
RES_DISPLAY = {'bands': '색띠만', 'number': '숫자만', 'both': '색띠 + 숫자'}
TOOLS = [('select', '선택'), ('lead', '리드·프로브'),
         ('wire', '점퍼선'), ('resistor', '저항'), ('ldr', '광저항(LDR)'), ('pot', '가변저항'),
         ('capacitor', '커패시터'), ('inductor', '인덕터(코일)'), ('switch', '스위치'), ('spdt', '전환 스위치'),
         ('battery', '건전지'),
         ('led', 'LED'), ('diode', '다이오드'), ('zener', '제너 다이오드'), ('npn', 'NPN 트랜지스터'),
         ('pnp', 'PNP 트랜지스터'), ('nmos', 'N채널 MOSFET'),
         ('opamp', '연산 증폭기(741)'), ('timer555', '555 타이머')]
TOOL_GROUPS = [('기본 부품', 'wire'), ('반도체', 'led'), ('IC', 'opamp')]
PIN_LABEL = {'npn': ('컬렉터(C)', '베이스(B)', '이미터(E)'), 'pnp': ('컬렉터(C)', '베이스(B)', '이미터(E)'),
             'nmos': ('드레인(D)', '게이트(G)', '소스(S)'), 'pot': ('한쪽 끝(1)', '와이퍼(W)', '다른 끝(3)'),
             'spdt': ('A 단자', '공통(COM)', 'B 단자')}
TOOL_TIPS = {
    'select': '부품을 고르고, 다리 끝을 끌어 옮깁니다.',
    'lead': '전원·함수 발생기 집게와 스코프 프로브를 구멍에 물립니다.',
    'wire': '두 구멍을 전선으로 잇습니다.',
    'resistor': '전류를 줄입니다. LED 앞에는 꼭 하나 넣습니다.',
    'ldr': '빛이 밝을수록 저항이 작아집니다.',
    'capacitor': '전기를 잠깐 모아 두었다가 내보냅니다.',
    'led': '전류가 흐르면 빛납니다. 첫 구멍이 긴 다리(+)입니다.',
    'diode': '전류를 한쪽으로만 흐르게 합니다.',
    'switch': '회로를 끊거나 잇습니다. 더블클릭하거나 Space로 전환합니다.',
    'npn': '작은 전류로 큰 전류를 켜고 끕니다. C → B → E 순서로 꽂습니다.',
    'pot': '손잡이를 돌려 저항을 바꿉니다. 1 → W(가운데) → 3 순서로 꽂습니다.',
    'inductor': '전류의 변화를 막는 코일입니다. 교류일수록 잘 막습니다.',
    'zener': '거꾸로 꽂으면 정해진 전압에서 전류를 흘려 전압을 일정하게 지킵니다.',
    'spdt': '공통 단자(COM)를 A 또는 B에 잇습니다. 더블클릭으로 전환합니다.',
    'battery': '정해진 전압을 내는 전원입니다. 첫 구멍이 +입니다.',
    'pnp': 'NPN과 반대 방향으로 동작하는 트랜지스터입니다. C → B → E 순서로 꽂습니다.',
    'nmos': '게이트 전압으로 켜고 끄는 스위치입니다. D → G → S 순서로 꽂습니다.',
    'opamp': '두 입력의 차이를 크게 키우는 IC입니다. 가운데 홈을 걸쳐 꽂습니다.',
    'timer555': '저항·커패시터로 박자를 만드는 IC입니다. 가운데 홈을 걸쳐 꽂습니다.',
}
TOOL_KEYS = {'select': 'V', 'lead': 'P', 'wire': 'W', 'resistor': 'R', 'ldr': 'Shift+R', 'capacitor': 'C',
             'led': 'L', 'diode': 'D', 'switch': 'S', 'npn': 'Q',
             'pot': 'K', 'inductor': 'Shift+L', 'zener': 'Shift+D', 'spdt': 'Shift+S', 'battery': 'B',
             'pnp': 'Shift+Q', 'nmos': 'M', 'opamp': 'A', 'timer555': 'T'}
HELP_TEXT = ('<b>부품 꽂기</b> 도구를 고르고 구멍에서 구멍으로 끌거나 두 구멍을 차례로 클릭합니다. '
             'NPN은 C → B → E 순서로 세 번 클릭합니다.<br>'
             '<b>옮기기</b> 선택한 부품의 다리 끝을 끌어 다른 구멍에 놓습니다.<br>'
             '<b>장비 연결</b> 리드·프로브 도구나 장비 창의 꽂기 버튼을 누르고 구멍을 클릭합니다. '
             '집게 표시를 우클릭하면 뗍니다.<br>'
             '<b>장비 창</b> 보드 위쪽 장비를 클릭하면 열립니다.<br>'
             '빈 곳을 우클릭하거나 Esc를 누르면 선택 도구로 돌아갑니다.<br>')
PART_TOOLS = tuple(k for k, _ in TOOLS[2:])

# 보드 색(실물 브레드보드 느낌의 따뜻한 흰색)
B_FILL, B_EDGE, B_CHANNEL, B_TEXT = '#e6e3db', '#b8b3a7', '#d4d0c6', '#8a867c'
HOLE_FILL, HOLE_EDGE = '#3a3832', '#25241f'
RAIL_RED, RAIL_BLUE = '#c8453a', '#3b6fb0'
INK = '#3d3a33'

# 장비는 실험대 위 보드 뒤쪽 선반에 나란히 놓입니다(아래쪽을 맞춤).
# 장비는 보드 오른쪽에 위에서부터 전원 → 함수 발생기 → 오실로스코프 순서로 한 줄로 세웁니다(보드 높이 가운데에 맞춤).
RACK_X, RACK_W, RACK_GAP = 962, 302, 16
_rack_top = 42 + (550 - (136 + 118 + 190 + 2 * RACK_GAP)) / 2
BOX_RECT = {'psu': QRectF(RACK_X + (RACK_W - 280) / 2, _rack_top, 280, 136),
            'fg': QRectF(RACK_X + (RACK_W - 280) / 2, _rack_top + 136 + RACK_GAP, 280, 118),
            'scope': QRectF(RACK_X, _rack_top + 136 + 118 + 2 * RACK_GAP, RACK_W, 190)}
INSTRUMENT_NAMES = {'psu': '전원 공급기', 'fg': '함수 발생기', 'scope': '오실로스코프'}
VIEW_RECT = QRectF(24, 30, RACK_X + RACK_W + 14 - 24, 592 + 14 - 30)

GUIDE = {
    'select': '부품을 클릭해 선택합니다. 선택한 부품의 다리 끝을 끌면 다른 구멍으로 옮깁니다. 빈 곳을 끌면 화면이 움직입니다.',
    'lead': '왼쪽 아래에서 고른 리드(전원·함수 발생기 집게, 스코프 프로브)를 물릴 구멍을 클릭하십시오. '
            '같은 구멍을 다시 클릭하거나 표시를 우클릭하면 뗍니다.',
    'wire': '점퍼선: 시작 구멍에서 끝 구멍까지 끌거나 두 구멍을 차례로 클릭하십시오.',
    'led': 'LED: 첫 구멍이 애노드(+, 긴 다리), 둘째 구멍이 캐소드(−)입니다.',
    'diode': '다이오드: 첫 구멍이 애노드, 둘째 구멍이 캐소드(띠 쪽)입니다.',
    'npn': 'NPN: 컬렉터(C) → 베이스(B) → 이미터(E) 순서로 구멍 세 개를 클릭하십시오.',
    'pnp': 'PNP: 컬렉터(C) → 베이스(B) → 이미터(E) 순서로 구멍 세 개를 클릭하십시오.',
    'nmos': 'MOSFET: 드레인(D) → 게이트(G) → 소스(S) 순서로 구멍 세 개를 클릭하십시오.',
    'pot': '가변저항: 한쪽 끝(1) → 와이퍼(W) → 다른 끝(3) 순서로 구멍 세 개를 클릭하십시오.',
    'spdt': '전환 스위치: A → 공통(COM) → B 순서로 구멍 세 개를 클릭하십시오.',
    'zener': '제너 다이오드: 첫 구멍이 애노드, 둘째 구멍이 캐소드(띠 쪽)입니다.',
    'battery': '건전지: 첫 구멍이 +, 둘째 구멍이 −입니다.',
    'opamp': 'IC: 1번 핀이 꽂힐 열을 클릭하십시오. 가운데 홈을 걸쳐 1~4번 핀은 F열, 5~8번 핀은 E열에 꽂힙니다.',
    'timer555': 'IC: 1번 핀이 꽂힐 열을 클릭하십시오. 가운데 홈을 걸쳐 1~4번 핀은 F열, 5~8번 핀은 E열에 꽂힙니다.',
}
GUIDE_PART = '첫 구멍에서 둘째 구멍까지 끌거나, 두 구멍을 차례로 클릭하십시오.'


# 장비 리드: (키, 이름, 집게 글자, 집게 색, 글자 색)
LEADS = [('p:1+', '전원 CH1 +', '1+', RAIL_RED, '#ffffff'), ('p:1-', '전원 CH1 −', '1−', '#222222', '#ffffff'),
         ('p:2+', '전원 CH2 +', '2+', RAIL_RED, '#ffffff'), ('p:2-', '전원 CH2 −', '2−', '#222222', '#ffffff'),
         ('g:+', '함수 발생기 출력', 'FG', '#2f7d4f', '#ffffff'), ('g:-', '함수 발생기 COM', 'COM', '#222222', '#ffffff'),
         ('scope:ch1', '오실로스코프 CH1 프로브', '1', CH_COLORS['ch1'], '#111111'),
         ('scope:ch2', '오실로스코프 CH2 프로브', '2', CH_COLORS['ch2'], '#111111')]
LEAD_INFO = {k: (name, tag, bg, fg) for k, name, tag, bg, fg in LEADS}
MARK_OFFSETS = [(-14, -24), (14, -24), (-28, -10), (28, -10), (-14, -40), (14, -40), (-30, -28), (30, -28)]


def pos(h):
    s, c = h.split(':')
    x = 96 + int(c) * 27
    if s[0] == 'r':
        y = [90, 116, 504, 530][int(s[1])]
    elif s[0] == 't':
        y = 180 + int(s[1]) * 26
    else:
        y = 336 + int(s[1]) * 26
    return QPointF(x, y)


def hole_label(h):
    s, c = h.split(':')
    if s[0] == 'r':
        return ['위 + 레일', '위 − 레일', '아래 + 레일', '아래 − 레일'][int(s[1])] + f' {int(c) + 1}'
    return ('ABCDE' if s[0] == 't' else 'FGHIJ')[int(s[1])] + f'{int(c) + 1}'


def value_text(p):
    if p.kind in ('resistor', 'ldr'):
        return format_si(p.resistance())
    if p.kind == 'capacitor':
        return format_si(p.value, 'F')
    if p.kind == 'npn':
        return f'β {p.value:g}'
    if p.kind in ('led', 'wire'):
        return COLOR_NAMES[p.color]
    if p.kind == 'switch':
        return '닫힘' if p.closed else '열림'
    if p.kind == 'pot':
        return f'{format_si(p.value)} · {p.pos:.0f}%'
    if p.kind == 'inductor':
        return format_si(p.value, 'H')
    if p.kind in ('zener', 'battery'):
        return f'{p.value:g} V'
    if p.kind == 'pnp':
        return f'β {p.value:g}'
    if p.kind == 'nmos':
        return f'Vth {p.value:g} V'
    if p.kind == 'spdt':
        return 'COM–A' if p.closed else 'COM–B'
    if p.kind == 'opamp':
        return '741'
    if p.kind == 'timer555':
        return 'NE555'
    return ''


def short_value(p):
    """입력칸에 다시 넣을 수 있는 형태(1k, 100u …)."""
    if p.kind == 'resistor':
        return format_si(p.value, '').replace(' ', '')
    if p.kind == 'capacitor':
        return format_si(p.value, '').replace(' ', '').replace('µ', 'u')
    if p.kind in ('npn', 'pnp', 'zener', 'battery', 'nmos'):
        return f'{p.value:g}'
    if p.kind in ('pot', 'inductor'):
        return format_si(p.value, '').replace(' ', '').replace('µ', 'u')
    return ''


def tag_candidates(p, text, a, b, mid):
    """값 꼬리표를 둘 수 있는 자리(먼저 오는 것이 기본 자리)."""
    f = QFont()
    f.setPixelSize(10)
    w = QFontMetricsF(f).horizontalAdvance(text) + 8
    if abs(b.x() - a.x()) >= abs(b.y() - a.y()):                # 가로 부품: 아래 → 위
        return [QRectF(mid.x() - w / 2, mid.y() + 11, w, 14), QRectF(mid.x() - w / 2, mid.y() - 25, w, 14),
                QRectF(mid.x() - w / 2, mid.y() + 27, w, 14)]
    return [QRectF(mid.x() + 15, mid.y() - 7, w, 14), QRectF(mid.x() - 15 - w, mid.y() - 7, w, 14),
            QRectF(mid.x() + 15, mid.y() + 9, w, 14), QRectF(mid.x() - 15 - w, mid.y() + 9, w, 14),
            QRectF(mid.x() + 15, mid.y() - 23, w, 14), QRectF(mid.x() - 15 - w, mid.y() - 23, w, 14)]


def ic_rect(anchor):
    """IC 몸체 사각형. anchor는 1번 핀 구멍(또는 끌고 있는 점)."""
    if isinstance(anchor, QPointF):
        return QRectF(anchor.x() - 11, anchor.y() - 46, 103, 40)
    a = ic_anchor(anchor)
    x0 = pos(a).x() - 11
    return QRectF(x0, 290, 3 * 27 + 22, 40)


# ---------------------------------------------------------------- 그래픽 아이템
class Hole(QGraphicsEllipseItem):
    def __init__(self, h, ws):
        super().__init__(-4.4, -4.4, 8.8, 8.8)
        self.h, self.ws = h, ws
        self.setPos(pos(h))
        self.setZValue(5)
        self.setAcceptHoverEvents(True)
        if ws.mode != 'select':
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_active(False)

    def set_active(self, on):
        self.setBrush(QColor(theme.ACCENT if on else HOLE_FILL))
        self.setPen(QPen(QColor('#8a2a26' if on else HOLE_EDGE), 1))

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self.ws.mode == 'select':
            e.ignore()
            return
        self.ws.hole_pressed(self.h)
        e.accept()

    def mouseMoveEvent(self, e):
        self.ws.drag_move(e.scenePos())

    def mouseReleaseEvent(self, e):
        self.ws.drag_release()

    def hoverEnterEvent(self, e):
        self.setToolTip(self.ws.hole_tooltip(self.h))
        self.ws.hover_hole(self.h)

    def hoverLeaveEvent(self, e):
        self.ws.hover_hole(None)


class Device(QGraphicsPathItem):
    def __init__(self, part, ws, ghost=False):
        super().__init__()
        self.part, self.ws, self.ghost = part, ws, ghost
        self.setZValue(10 if ghost else 6)
        if ghost:
            self.setOpacity(0.45)
            self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        else:
            self.setAcceptHoverEvents(True)
            if ws.mode != 'select':
                self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.update_path()

    @staticmethod
    def pt(h):
        return h if isinstance(h, QPointF) else pos(h)

    def ends(self):
        return self.pt(self.part.a), self.pt(self.part.b)

    def update_path(self):
        self.prepareGeometryChange()
        if self.part.kind in IC_KINDS:
            path = QPainterPath()
            path.addRect(ic_rect(self.part.a))
            self.setPath(path)
            return
        a, b = self.ends()
        path = QPainterPath(a)
        path.lineTo(b)
        self.setPath(path)

    def mid(self):
        if self.part.kind in IC_KINDS:
            return ic_rect(self.part.a).center()
        a, b = self.ends()
        return QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)

    def boundingRect(self):
        r = super().boundingRect()
        if self.part.kind in IC_KINDS:
            return r.adjusted(-20, -30, 20, 30)
        if self.part.kind in THREE_PIN and self.part.c:
            c = self.pt(self.part.c)
            r = r.united(QRectF(c.x() - 1, c.y() - 1, 2, 2))
        return r.adjusted(-75, -40, 75, 40)

    def shape(self):
        stroker = QPainterPathStroker()
        stroker.setWidth(10)
        if self.part.kind in IC_KINDS:            # 몸체와 다리 줄까지 잡을 수 있게
            r = ic_rect(self.part.a)
            path = QPainterPath()
            path.addRect(QRectF(r.left(), r.top() - 12, r.width(), r.height() + 24))
            return path
        shape = stroker.createStroke(self.path())
        if self.part.kind != 'wire':
            body = QPainterPath()
            body.addEllipse(self.mid(), 18, 18)
            shape = shape.united(body)
        if self.part.kind in THREE_PIN and self.part.c:
            leg = QPainterPath(self.mid())
            leg.lineTo(self.pt(self.part.c))
            shape = shape.united(stroker.createStroke(leg))
        return shape

    def pin_at(self, pt):
        if self.part.kind in IC_KINDS:
            for h in self.part.pins():
                q = pos(h) if isinstance(h, str) else h
                if math.hypot(q.x() - pt.x(), q.y() - pt.y()) < 10:
                    return 'a'
            return None
        names = ('c', 'a', 'b') if self.part.kind in THREE_PIN else ('a', 'b')
        for name in names:
            h = getattr(self.part, name)
            if h and not isinstance(h, QPointF):
                q = pos(h)
                if math.hypot(q.x() - pt.x(), q.y() - pt.y()) < 10:
                    return name
        return None

    # ---------- 이벤트
    def hoverEnterEvent(self, e):
        self.setToolTip(self.ws.part_tooltip(self.part))
        self.ws.part_hovered(self.part.id)

    def hoverLeaveEvent(self, e):
        self.ws.part_hovered(None)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self.ws.select(self.part.id)
            e.accept()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(e)
        self.ws.select(self.part.id)
        if self.part.kind in IC_KINDS:            # IC는 어디를 잡아도 통째로 옮깁니다
            self.ws.start_move(self, 'a')
            if self.ws.drag:
                grab = int(round((e.scenePos().x() - pos(self.part.a).x()) / 27))
                self.ws.drag['ic_off'] = max(0, min(3, grab))
            e.accept()
            return
        pin = self.pin_at(e.scenePos())
        if pin:
            self.ws.start_move(self, pin)
        e.accept()

    def mouseMoveEvent(self, e):
        self.ws.drag_move(e.scenePos())

    def mouseReleaseEvent(self, e):
        self.ws.drag_release()

    def mouseDoubleClickEvent(self, e):
        if self.part.kind in ('switch', 'spdt'):
            self.ws.toggle_switch()
        e.accept()

    def contextMenuEvent(self, e):
        self.ws.select(self.part.id)
        self.ws.part_menu(e.screenPos())
        e.accept()

    # ---------- 그리기
    def paint(self, painter, option, widget=None):
        p, ws = self.part, self.ws
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = not self.ghost and ws.selected == p.id
        a, b = self.ends()
        mid = self.mid()
        info = {} if self.ghost else ws.result['parts'].get(p.id, {})
        if p.kind in IC_KINDS:
            self.paint_ic(painter, p, info, selected)
            return
        cpt = self.pt(p.c) if p.kind in THREE_PIN and p.c else None

        hovered = not self.ghost and not selected and getattr(ws, 'hover_part', None) == p.id
        if selected or hovered:
            painter.setPen(QPen(QColor(239, 83, 80, 110 if selected else 60), 9, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap))
            painter.drawPath(self.path())
            if cpt:
                painter.drawLine(mid, cpt)

        if p.kind == 'wire':
            painter.setPen(QPen(QColor(0, 0, 0, 90), 5.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawPath(self.path())
            painter.setPen(QPen(QColor(p.color), 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawPath(self.path())
        else:
            painter.setPen(QPen(QColor('#8f8c84'), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawPath(self.path())
            if cpt:
                painter.drawLine(mid, cpt)
            painter.save()
            painter.translate(mid)
            self._flip = False
            if p.kind not in THREE_PIN and (a.x() != b.x() or a.y() != b.y()):
                angle = math.degrees(math.atan2(b.y() - a.y(), b.x() - a.x()))
                painter.rotate(angle)
                self._flip = angle > 90 or angle <= -90   # 글자·색띠를 늘 같은 방향으로 읽게
            self.paint_body(painter, p, info)
            painter.restore()
            # 표기 규칙: 값이 고정된 부품은 몸체에 인쇄, 값이 변하는 부품(LDR)은 옆 꼬리표.
            # 저항의 '색띠 + 숫자'는 색띠를 몸체에, 숫자를 꼬리표로.
            text = ''
            if p.kind in ('ldr', 'pot') or (p.kind == 'resistor' and ws.res_display == 'both'):
                text = value_text(p)
            if text and not self.ghost:
                # 값 꼬리표: 보드 색 바탕을 깔아 뒤의 구멍과 겹쳐도 읽히게 합니다.
                # 자리는 보드를 다시 그릴 때 다른 꼬리표·부품과 겹치지 않게 미리 정해 둡니다(layout_tags).
                f = QFont()
                f.setPixelSize(10)
                painter.setFont(f)
                tag = ws.tag_pos.get(p.id) or tag_candidates(p, text, a, b, mid)[0]
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(236, 233, 225, 240))
                painter.drawRoundedRect(tag, 2, 2)
                painter.setPen(QColor(INK))
                painter.drawText(tag, Qt.AlignmentFlag.AlignCenter, text)

        if p.kind in THREE_PIN and not self.ghost:
            f = QFont()
            f.setPixelSize(9)
            f.setBold(True)
            painter.setFont(f)
            for h, letter in zip((p.a, p.b, p.c), PIN_NAMES[p.kind]):
                if h and not isinstance(h, QPointF):
                    q = pos(h)
                    w = 7 + 6 * len(letter)
                    box = QRectF(q.x() + 5, q.y() - 15, w, 11)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(255, 255, 255, 200))
                    painter.drawRect(box)
                    painter.setPen(QColor(INK))
                    painter.drawText(box, Qt.AlignmentFlag.AlignCenter, letter)

        if selected:
            painter.setPen(QPen(QColor('#ffffff'), 1))
            painter.setBrush(QColor(theme.ACCENT))
            for h in p.pins():
                if h and not isinstance(h, QPointF):
                    painter.drawEllipse(pos(h), 4.5, 4.5)

        if info.get('alerts'):
            c = mid + QPointF(16, -16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.DANGER))
            painter.drawEllipse(c, 7, 7)
            painter.setPen(QColor('white'))
            f = QFont()
            f.setPixelSize(11)
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(QRectF(c.x() - 7, c.y() - 7, 14, 14), Qt.AlignmentFlag.AlignCenter, '!')

    def paint_ic(self, painter, p, info, selected):
        """DIP-8 IC: 가운데 홈 위에 걸친 검은 몸체, 1번 핀 쪽 홈과 점, 핀 이름."""
        r = ic_rect(p.a)
        if selected or (not self.ghost and getattr(self.ws, 'hover_part', None) == p.id):
            painter.setPen(QPen(QColor(239, 83, 80, 110 if selected else 60), 7))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(r.adjusted(-3, -3, 3, 3))
        pins = p.pins() if isinstance(p.a, str) and len(p.pins()) == 8 else dip_pins(ic_anchor(p.a)) \
            if isinstance(p.a, str) else ()
        painter.setPen(QPen(QColor('#9a978f'), 2.4))
        for h in pins:
            q = pos(h)
            painter.drawLine(q, QPointF(q.x(), r.top() if q.y() < r.top() else r.bottom()))
        painter.setPen(QPen(QColor('#111111'), 1))
        painter.setBrush(QColor('#2a2a2a'))
        painter.drawRoundedRect(r, 2, 2)
        painter.setBrush(QColor('#1a1a1a'))
        painter.drawChord(QRectF(r.left() - 6, r.center().y() - 6, 12, 12), -90 * 16, 180 * 16)
        painter.setBrush(QColor('#555555'))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(r.left() + 6, r.bottom() - 6), 2, 2)
        f = QFont()
        f.setPixelSize(11)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QColor('#e6e3db'))
        painter.drawText(r, Qt.AlignmentFlag.AlignCenter, '741' if p.kind == 'opamp' else 'NE555')
        if pins and not self.ghost:
            f.setPixelSize(7)
            f.setBold(False)
            painter.setFont(f)
            painter.setPen(QColor('#bdb9ae'))
            for i, h in enumerate(pins):
                q = pos(h)
                name = PIN_NAMES[p.kind][i]
                box = QRectF(q.x() - 13, r.bottom() - 10 if i < 4 else r.top() + 1, 26, 9)
                painter.drawText(box, Qt.AlignmentFlag.AlignCenter, name)
        if selected:
            painter.setPen(QPen(QColor('#ffffff'), 1))
            painter.setBrush(QColor(theme.ACCENT))
            for h in pins:
                painter.drawEllipse(pos(h), 4.5, 4.5)
        if info.get('alerts'):
            c = r.topRight() + QPointF(4, -4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.DANGER))
            painter.drawEllipse(c, 7, 7)
            painter.setPen(QColor('white'))
            f = QFont()
            f.setPixelSize(11)
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(QRectF(c.x() - 7, c.y() - 7, 14, 14), Qt.AlignmentFlag.AlignCenter, '!')

    def paint_body(self, painter, p, info):
        k = p.kind
        edge = QPen(QColor('#5c5a54'), 1.2)
        if k == 'resistor':
            printed = self.ws is not None and self.ws.res_display == 'number'
            text = format_si(p.value) if printed else ''
            w = max(42, body_text_width(text) + 10) if printed else 42
            painter.setPen(QPen(QColor('#8f7d58'), 1.2))
            painter.setBrush(QColor('#d9c7a0'))
            painter.drawRoundedRect(QRectF(-w / 2, -7, w, 14), 3, 3)
            if printed:
                print_on_body(painter, text, '#3d3424', getattr(self, '_flip', False))
            bands = None if printed else resistor_bands(p.value)
            if bands:
                d1, d2, m = bands
                mult = GOLD if m == -1 else SILVER if m == -2 else BAND[m]
                sx = -1 if getattr(self, '_flip', False) else 1      # 금색 띠가 늘 오른쪽(세로면 아래)에
                for x, col in ((-13, BAND[d1]), (-7, BAND[d2]), (-1, mult), (12, GOLD)):
                    x *= sx
                    painter.setPen(QPen(QColor(col), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
                    painter.drawLine(QPointF(x, -6.4), QPointF(x, 6.4))
        elif k == 'ldr':
            painter.setPen(edge)
            painter.setBrush(QColor('#d8a26b'))
            painter.drawEllipse(QPointF(0, 0), 12, 12)
            painter.setPen(QPen(QColor('#7a3f22'), 1.4))
            painter.drawPolyline([QPointF(-8, -5), QPointF(7, -5), QPointF(-7, 0), QPointF(7, 0),
                                  QPointF(-7, 5), QPointF(8, 5)])
        elif k == 'capacitor':      # 필름 커패시터: 용량을 몸체에 인쇄
            text = format_si(p.value, 'F')
            w = max(26, body_text_width(text) + 10)
            painter.setPen(edge)
            painter.setBrush(QColor('#3f6fa3'))
            painter.drawRoundedRect(QRectF(-w / 2, -8, w, 16), 3, 3)
            print_on_body(painter, text, '#eef3f8', getattr(self, '_flip', False))
        elif k == 'led':
            cur = info.get('current', 0.0)
            lit = min(1.0, max(0.0, (cur - 0.0005) / 0.0145))
            col = QColor(p.color)
            if lit > 0.01:
                glow = QColor(col)
                glow.setAlpha(int(40 + lit * 110))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow)
                r = 13 + lit * 9
                painter.drawEllipse(QPointF(0, 0), r, r)
                body = col.lighter(100 + int(lit * 35))
            else:
                body = col.darker(260)
            painter.setPen(edge)
            painter.setBrush(body)
            painter.drawEllipse(QPointF(0, 0), 10, 10)
            painter.setPen(QPen(QColor('#5c5a54'), 1.6))
            painter.drawLine(QPointF(8.5, -6), QPointF(8.5, 6))   # 캐소드 쪽 평평한 면
        elif k == 'diode':
            painter.setPen(edge)
            painter.setBrush(QColor('#2b2b2b'))
            painter.drawRect(QRectF(-15, -6, 30, 12))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor('#d0d0d0'))
            painter.drawRect(QRectF(9, -6, 3.5, 12))
        elif k == 'switch':
            painter.setPen(edge)
            painter.setBrush(QColor('#3a3d45'))
            painter.drawRect(QRectF(-17, -9, 34, 18))
            painter.setBrush(QColor('#d8d5ce' if p.closed else '#6d6b66'))
            painter.drawRect(QRectF(1 if p.closed else -13, -6, 12, 12))
        elif k in ('npn', 'pnp', 'nmos'):
            painter.setPen(edge)
            painter.setBrush(QColor('#262626'))
            path = QPainterPath()
            path.moveTo(-12, 8)
            path.lineTo(12, 8)
            path.lineTo(12, -2)
            path.arcTo(QRectF(-12, -14, 24, 24), 0, 180)
            path.closeSubpath()
            painter.drawPath(path)
            painter.setPen(QColor('#d8d5ce'))
            f = QFont()
            f.setPixelSize(8)
            painter.setFont(f)
            painter.drawText(QRectF(-12, -6, 24, 12), Qt.AlignmentFlag.AlignCenter,
                             {'npn': 'NPN', 'pnp': 'PNP', 'nmos': 'MOS'}[k])
        elif k == 'pot':            # 반고정 가변저항: 파란 몸체 + 돌리는 손잡이
            painter.setPen(edge)
            painter.setBrush(QColor('#3a6ea8'))
            painter.drawRoundedRect(QRectF(-12, -12, 24, 24), 3, 3)
            painter.setBrush(QColor('#f2f2ee'))
            painter.drawEllipse(QPointF(0, 0), 8, 8)
            ang = math.radians(-135 + 270 * p.pos / 100)
            painter.setPen(QPen(QColor('#3d3a33'), 2))
            painter.drawLine(QPointF(0, 0), QPointF(7 * math.sin(ang), -7 * math.cos(ang)))
        elif k == 'inductor':       # 코일: 초록 몸체에 감긴 구리선, 값 인쇄
            text = format_si(p.value, 'H')
            w = max(30, body_text_width(text) + 12)
            painter.setPen(edge)
            painter.setBrush(QColor('#41704a'))
            painter.drawRoundedRect(QRectF(-w / 2, -8, w, 16), 7, 7)
            painter.setPen(QPen(QColor('#c98b4a'), 1.2))
            for i in range(-2, 3):
                x = i * w / 6
                painter.drawLine(QPointF(x, -7.5), QPointF(x + 3, 7.5))
            print_on_body(painter, text, '#f3efe4', getattr(self, '_flip', False))
        elif k == 'zener':
            painter.setPen(edge)
            painter.setBrush(QColor('#d9822b'))
            painter.drawRect(QRectF(-15, -6, 30, 12))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor('#1d1d1d'))
            painter.drawRect(QRectF(9, -6, 3.5, 12))
        elif k == 'spdt':           # 슬라이드 스위치: 손잡이가 A쪽(왼쪽) 또는 B쪽
            painter.setPen(edge)
            painter.setBrush(QColor('#3a3d45'))
            painter.drawRect(QRectF(-17, -9, 34, 18))
            painter.setBrush(QColor('#d8d5ce'))
            painter.drawRect(QRectF(-13 if p.closed else 1, -6, 12, 12))
        elif k == 'battery':        # 건전지: + 단자가 a쪽, 전압 인쇄
            text = f'{p.value:g}V'
            w = max(40, body_text_width(text) + 18)
            painter.setPen(edge)
            painter.setBrush(QColor('#2b2b2b'))
            painter.drawRoundedRect(QRectF(-w / 2, -10, w, 20), 3, 3)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor('#c8a24a'))
            flip = getattr(self, '_flip', False)
            painter.drawRect(QRectF(w / 2 - 5, -10, 5, 20) if flip else QRectF(-w / 2, -10, 5, 20))
            print_on_body(painter, text, '#f3efe4', flip)


class LeadMarker(QGraphicsPathItem):
    """장비 리드 집게(전원·함수 발생기)나 스코프 프로브가 물린 자리. 우클릭으로 뗍니다."""

    def __init__(self, key, h, index, ws):
        super().__init__()
        self.key, self.ws = key, ws
        self.name, self.tag, self.bg, self.fg = LEAD_INFO[key]
        q = pos(h)
        self.tip = q + QPointF(*MARK_OFFSETS[index % len(MARK_OFFSETS)])
        path = QPainterPath(q)
        path.lineTo(self.tip)
        self.setPath(path)
        self.setPen(QPen(QColor(self.bg if self.bg != '#222222' else '#555555'), 2))
        self.setZValue(12)
        self.setToolTip(f'{self.name} · {hole_label(h)}\n우클릭: 떼기')
        f = QFont()
        f.setPixelSize(10)
        f.setBold(True)
        self.font = f
        self.w = max(16, 8 + 7 * len(self.tag))

    def tag_rect(self):
        return QRectF(self.tip.x() - self.w / 2, self.tip.y() - 8, self.w, 16)

    def boundingRect(self):
        return super().boundingRect().united(self.tag_rect()).adjusted(-3, -3, 3, 3)

    def shape(self):
        sh = QPainterPath()
        sh.addRect(self.tag_rect())
        return sh

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        super().paint(painter, option, widget)
        painter.setPen(QPen(QColor('#111111'), 1))
        painter.setBrush(QColor(self.bg))
        r = self.tag_rect()
        if self.key.startswith('scope'):
            painter.drawEllipse(r.center(), 8, 8)
        else:
            painter.drawRoundedRect(r, 2, 2)
        painter.setPen(QColor(self.fg))
        painter.setFont(self.font)
        painter.drawText(r, Qt.AlignmentFlag.AlignCenter, self.tag)

    def contextMenuEvent(self, e):
        QTimer.singleShot(0, lambda: self.ws.set_lead(self.key, None))
        e.accept()


class InstrumentBox(QGraphicsItem):
    """보드 왼쪽에 놓인 계측 장비 앞면. 실제 장비처럼 현재 상태를 보여 주고, 클릭하면 장비 창을 엽니다."""

    def __init__(self, kind, ws):
        super().__init__()
        self.kind, self.ws, self.rect = kind, ws, BOX_RECT[kind]
        self.hover = False
        self.setZValue(1)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f'클릭하면 {INSTRUMENT_NAMES[kind]} 창이 열립니다.')

    def boundingRect(self):
        return self.rect.adjusted(-2, -2, 2, 2)

    def hoverEnterEvent(self, e):
        self.hover = True
        self.update()

    def hoverLeaveEvent(self, e):
        self.hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            e.accept()
        else:
            e.ignore()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect.contains(e.pos()):
            QTimer.singleShot(0, lambda: self.ws.open_instrument(self.kind))

    # ---------- 그리기 도구
    @staticmethod
    def _rect(p, rect, fill, edge=None, radius=3, width=1.0):
        p.setPen(QPen(QColor(edge), width) if edge else Qt.PenStyle.NoPen)
        p.setBrush(QColor(fill))
        p.drawRoundedRect(rect, radius, radius)

    @staticmethod
    def _text(p, rect, text, color, px, bold=False, mono=False, align=Qt.AlignmentFlag.AlignLeft):
        f = theme.mono_font(px) if mono else QFont()
        if not mono:
            f.setFamilies(theme.FONT_FAMILIES)
            f.setPixelSize(px)
        f.setBold(bold)
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(rect, align | Qt.AlignmentFlag.AlignVCenter, text)

    @staticmethod
    def _knob(p, c, r, body, edge, mark, angle=-40, ridges=False):
        p.setPen(QPen(QColor(edge), 1.2))
        p.setBrush(QColor(edge))
        p.drawEllipse(c, r + 2, r + 2)
        p.setBrush(QColor(body))
        p.drawEllipse(c, r, r)
        if ridges:
            p.setPen(QPen(QColor(edge), 1))
            for k in range(24):
                a = math.radians(k * 15)
                p.drawLine(QPointF(c.x() + math.cos(a) * r * 0.78, c.y() + math.sin(a) * r * 0.78),
                           QPointF(c.x() + math.cos(a) * r * 0.96, c.y() + math.sin(a) * r * 0.96))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 45))
        p.drawEllipse(QPointF(c.x() - r * 0.25, c.y() - r * 0.3), r * 0.45, r * 0.35)
        a = math.radians(angle - 90)
        p.setPen(QPen(QColor(mark), max(1.5, r * 0.14), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(c.x() + math.cos(a) * r * 0.35, c.y() + math.sin(a) * r * 0.35),
                   QPointF(c.x() + math.cos(a) * r * 0.85, c.y() + math.sin(a) * r * 0.85))

    @staticmethod
    def _bnc(p, c, ring=None):
        if ring:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(ring))
            p.drawEllipse(c, 11, 11)
        p.setPen(QPen(QColor('#6d6e72'), 1))
        p.setBrush(QColor('#c4c5c9'))
        p.drawEllipse(c, 8, 8)
        p.setBrush(QColor('#26272a'))
        p.drawEllipse(c, 4.5, 4.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#e2e2e2'))
        p.drawEllipse(c, 1.5, 1.5)

    @staticmethod
    def _post(p, c, color):
        p.setPen(QPen(QColor('#111111'), 1))
        p.setBrush(QColor(color))
        p.drawEllipse(c, 7, 7)
        p.setBrush(QColor('#c9c9c9'))
        p.drawEllipse(c, 2.5, 2.5)

    @staticmethod
    def _led(p, c, on, color, r=3):
        p.setPen(QPen(QColor('#00000080'), 0.8))
        p.setBrush(QColor(color) if on else QColor('#3b3b3b'))
        p.drawEllipse(c, r, r)

    def paint(self, p, option, widget=None):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        getattr(self, 'paint_' + self.kind)(p, self.rect, self.ws)
        if self.hover:
            p.setPen(QPen(QColor(theme.ACCENT), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(self.rect.adjusted(-1, -1, 1, 1), 7, 7)

    # ---------- 전원 공급기
    def paint_psu(self, p, r, ws):
        L, T = r.left(), r.top()
        self._rect(p, r, '#2f3136', '#1c1d20', 6)
        self._rect(p, QRectF(L + 3, T + 3, r.width() - 6, 3), '#3d3f45', None, 1)
        self._rect(p, QRectF(L + 10, T + 12, 168, 92), '#141518', '#0c0c0e', 3)
        scr = QRectF(L + 14, T + 16, 160, 84)
        self._rect(p, scr, '#0e1522', None, 1)
        colors = {'ch1': '#e8c547', 'ch2': '#5fd068'}
        for i, ch in enumerate(('ch1', 'ch2')):
            res, cfg = ws.result['psu'][ch], ws.inst['psu'][ch]
            on = res['mode'] in ('CV', 'CC')
            col = QRectF(scr.left() + 3 + i * 79, scr.top() + 3, 75, scr.height() - 6)
            p.setPen(QPen(QColor(colors[ch] if on else '#3a4150'), 1.2))
            p.setBrush(QColor('#121c2c' if on else '#0e1522'))
            p.drawRoundedRect(col, 2, 2)
            self._text(p, QRectF(col.left() + 4, col.top() + 2, 20, 12), ch[-1], colors[ch], 9, bold=True)
            self._text(p, QRectF(col.right() - 30, col.top() + 2, 26, 12), res['mode'] if on else 'OFF',
                       colors[ch] if on else '#56607a', 8, bold=True, align=Qt.AlignmentFlag.AlignRight)
            v = res['voltage'] if on else cfg['voltage']
            a = res['current'] if on else 0.0
            vcol = '#f2f4f8' if on else '#7c8699'
            self._text(p, QRectF(col.left() + 2, col.top() + 16, col.width() - 14, 22), f'{v:6.3f}', vcol, 15,
                       bold=True, mono=True, align=Qt.AlignmentFlag.AlignRight)
            self._text(p, QRectF(col.right() - 12, col.top() + 20, 10, 16), 'V', vcol, 9)
            self._text(p, QRectF(col.left() + 2, col.top() + 40, col.width() - 14, 18), f'{a:6.3f}', vcol, 12,
                       mono=True, align=Qt.AlignmentFlag.AlignRight)
            self._text(p, QRectF(col.right() - 12, col.top() + 42, 10, 14), 'A', vcol, 9)
            self._text(p, QRectF(col.left() + 4, col.bottom() - 16, col.width() - 8, 12),
                       f'{cfg["voltage"]:.2f} V  {cfg["limit"]:.3f} A', '#56607a', 8, mono=True)
            # 채널 버튼
            c = QPointF(L + 198 + i * 32, T + 22)
            p.setPen(QPen(QColor('#111111'), 1))
            p.setBrush(QColor(colors[ch]) if on else QColor('#4a4c52'))
            p.drawEllipse(c, 9, 9)
            self._text(p, QRectF(c.x() - 9, c.y() - 9, 18, 18), ch[-1], '#111111' if on else '#9a9ca2', 10, bold=True,
                       align=Qt.AlignmentFlag.AlignHCenter)
        self._knob(p, QPointF(L + 202, T + 66), 15, '#3e4046', '#18191c', '#d8d5ce', -30)
        self._knob(p, QPointF(L + 248, T + 70), 11, '#3e4046', '#18191c', '#d8d5ce', 40)
        self._text(p, QRectF(L + 184, T + 86, 40, 12), 'Voltage', '#9a9ca2', 8, align=Qt.AlignmentFlag.AlignHCenter)
        self._text(p, QRectF(L + 228, T + 86, 40, 12), 'Current', '#9a9ca2', 8, align=Qt.AlignmentFlag.AlignHCenter)
        # 출력 단자
        y = T + 120
        for i, ch in enumerate(('ch1', 'ch2')):
            x0 = L + 30 + i * 78
            self._text(p, QRectF(x0 - 6, y - 7, 10, 14), ch[-1], colors[ch], 9, bold=True)
            self._post(p, QPointF(x0 + 14, y), '#c8453a')
            self._post(p, QPointF(x0 + 38, y), '#202020')
        on_any = any(ws.result['psu'][c]['mode'] in ('CV', 'CC') for c in ('ch1', 'ch2'))
        self._rect(p, QRectF(L + 196, y - 8, 54, 16), '#46484e', '#18191c', 2)
        self._text(p, QRectF(L + 196, y - 8, 54, 16), 'Output', '#d8d5ce', 8, align=Qt.AlignmentFlag.AlignHCenter)
        self._led(p, QPointF(L + 260, y), on_any, '#5fd068')

    # ---------- 함수 발생기
    def paint_fg(self, p, r, ws):
        L, T = r.left(), r.top()
        fg, on = ws.inst['fg'], ws.inst['fg']['on']
        self._rect(p, r, '#e7e2d2', '#b3ad9c', 6)
        disp = QRectF(L + 10, T + 10, 150, 40)
        self._rect(p, disp, '#1d1414', '#0e0a0a', 3)
        if fg['wave'] == 'dc':
            value, unit = f'{fg["offset"]:+6.2f}', 'V DC'
        else:
            f = fg['freq']
            value, unit = (f'{f / 1000:6.3f}', 'kHz') if f >= 1000 else (f'{f:6.2f}', 'Hz')
        self._text(p, QRectF(disp.left() + 6, disp.top() + 4, 108, 32), '888.88', '#3a1614', 24, bold=True, mono=True,
                   align=Qt.AlignmentFlag.AlignRight)
        self._text(p, QRectF(disp.left() + 6, disp.top() + 4, 108, 32), value.strip(), '#ff3b30', 24, bold=True,
                   mono=True, align=Qt.AlignmentFlag.AlignRight)
        self._text(p, QRectF(disp.right() - 34, disp.top() + 16, 30, 16), unit, '#c2332b', 8, bold=True)
        # 파형 버튼
        waves = ('sine', 'square', 'triangle', 'ramp', 'dc')
        for i, w in enumerate(waves):
            b = QRectF(L + 10 + i * 30, T + 60, 24, 16)
            self._rect(p, b, '#f6f2e6', '#a29c8a', 2)
            self._led(p, QPointF(b.center().x(), b.top() - 4), fg['wave'] == w, '#ff3b30', 2)
            p.setPen(QPen(QColor('#4a463c'), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            cx, cy, wd, hg = b.center().x(), b.center().y(), 14, 5
            path = QPainterPath()
            if w == 'sine':
                for k in range(21):
                    x = cx - wd / 2 + wd * k / 20
                    y = cy - hg * math.sin(2 * math.pi * k / 20)
                    path.lineTo(x, y) if k else path.moveTo(x, y)
            elif w == 'square':
                pts = [(-7, 5), (-7, -5), (0, -5), (0, 5), (7, 5), (7, -5)]
                path.moveTo(cx + pts[0][0], cy + pts[0][1])
                for x, y in pts[1:]:
                    path.lineTo(cx + x, cy + y)
            elif w == 'triangle':
                path.moveTo(cx - 7, cy + 5); path.lineTo(cx - 3.5, cy - 5); path.lineTo(cx + 3.5, cy + 5)
                path.lineTo(cx + 7, cy - 5)
            elif w == 'ramp':
                path.moveTo(cx - 7, cy + 5); path.lineTo(cx, cy - 5); path.lineTo(cx, cy + 5); path.lineTo(cx + 7, cy - 5)
            else:
                path.moveTo(cx - 7, cy); path.lineTo(cx + 7, cy)
            p.drawPath(path)
        self._text(p, QRectF(L + 10, T + 80, 150, 12),
                   f'{fg["vpp"]:.2f} Vpp   OFS {fg["offset"]:+.2f} V', '#6d685b', 8, mono=True)
        # 다이얼과 출력
        self._knob(p, QPointF(L + 210, T + 46), 28, '#f1ecdc', '#a9a390', '#6d685b', 30, ridges=True)
        self._bnc(p, QPointF(L + 250, T + 98))
        self._text(p, QRectF(L + 180, T + 92, 56, 12), 'OUTPUT', '#6d685b', 8, bold=True)
        self._led(p, QPointF(L + 175, T + 98), on, '#5fd068')
        self._bnc(p, QPointF(L + 30, T + 104))
        self._text(p, QRectF(L + 42, T + 98, 40, 12), 'SYNC', '#6d685b', 8, bold=True)

    # ---------- 오실로스코프
    def paint_scope(self, p, r, ws):
        s = ws.scope
        L, T = r.left(), r.top()
        self._rect(p, r, '#e9e8e3', '#b8b6ae', 6)
        self._rect(p, QRectF(L + 8, T + 10, 172, 140), '#1b1c1f', '#0d0d0f', 4)
        scr = QRectF(L + 14, T + 22, 140, 96)
        self._rect(p, scr, '#05070a', None, 0)
        # 상단 상태 줄
        y0 = T + 13
        self._text(p, QRectF(scr.left(), y0, 40, 8), f'1 {format_si(s.settings["ch1"]["vdiv"], "V", 3)}/',
                   CH_COLORS['ch1'], 7, mono=True)
        self._text(p, QRectF(scr.left() + 40, y0, 40, 8), f'2 {format_si(s.settings["ch2"]["vdiv"], "V", 3)}/',
                   CH_COLORS['ch2'], 7, mono=True)
        self._text(p, QRectF(scr.left() + 82, y0, 58, 8), f'{format_si(s.settings["tdiv"], "s", 3)}/', '#d8d5ce', 7,
                   mono=True, align=Qt.AlignmentFlag.AlignRight)
        p.setPen(QPen(QColor('#1d2129'), 1))
        for i in range(1, 10):
            x = scr.left() + i * scr.width() / 10
            p.drawLine(QPointF(x, scr.top()), QPointF(x, scr.bottom()))
        for j in range(1, 8):
            y = scr.top() + j * scr.height() / 8
            p.drawLine(QPointF(scr.left(), y), QPointF(scr.right(), y))
        frame = s.frame
        if frame is not None and len(frame['x']) > 1:
            p.save()
            p.setClipRect(scr)
            dx, dy, cy = scr.width() / 10, scr.height() / 8, scr.center().y()
            step = max(1, len(frame['x']) // 140)
            for ch in ('ch1', 'ch2'):
                v = frame.get(ch)
                c = s.settings[ch]
                if v is None or not c['on']:
                    continue
                if c['ac']:
                    v = v - v.mean()
                path = QPainterPath()
                for i in range(0, len(v), step):
                    pt = QPointF(scr.left() + float(frame['x'][i]) * dx, cy - (float(v[i]) / c['vdiv'] + c['pos']) * dy)
                    path.lineTo(pt) if i else path.moveTo(pt)
                p.setPen(QPen(QColor(CH_COLORS[ch]), 1.2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)
            p.restore()
        # 화면 아래 측정값
        y = scr.bottom() + 4
        for ch in ('ch1', 'ch2'):
            m = s.measure.get(ch)
            h = ws.inst['scope'][ch]
            text = f'{ch[-1]} ' + (f'{format_si(m["vpp"], "V", 3)}pp' if (m and h) else '--')
            self._text(p, QRectF(scr.left() + (0 if ch == 'ch1' else 70), y, 70, 10), text,
                       CH_COLORS[ch] if h else '#555a63', 7, mono=True)
        self._text(p, QRectF(scr.left(), y + 12, 140, 10), s.state_text(), '#9a9ca2', 7, mono=True)
        # 소프트키
        for k in range(5):
            self._rect(p, QRectF(L + 160, T + 26 + k * 18, 14, 11), '#d6d4ce', '#8f8d86', 2)
        # 조작부
        panel = QRectF(L + 186, T + 10, r.width() - 194, 140)
        self._rect(p, panel, '#dcdbd5', '#b3b1aa', 4)
        run = s.running
        rb = QRectF(panel.right() - 36, panel.top() + 6, 30, 18)
        self._rect(p, rb, '#6fe07a' if run else '#ff5b52', '#2f6d35' if run else '#8e2a24', 3)
        self._text(p, rb, 'Run' if run else 'Stop', '#103814' if run else '#4a0d0a', 8, bold=True,
                   align=Qt.AlignmentFlag.AlignHCenter)
        self._rect(p, QRectF(panel.right() - 36, panel.top() + 28, 30, 14), '#f1f0ec', '#8f8d86', 2)
        self._text(p, QRectF(panel.right() - 36, panel.top() + 28, 30, 14), 'Single', '#4a4a4a', 7,
                   align=Qt.AlignmentFlag.AlignHCenter)
        self._knob(p, QPointF(panel.left() + 16, panel.top() + 18), 9, '#e8e7e2', '#8f8d86', '#55554f', -20)
        self._knob(p, QPointF(panel.right() - 18, panel.top() + 64), 7, '#e8e7e2', '#8f8d86', '#55554f', 30)
        for i, ch in enumerate(('ch1', 'ch2')):
            cx = panel.left() + 16 + i * 32
            on = s.settings[ch]['on']
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(CH_COLORS[ch]))
            p.drawEllipse(QPointF(cx, panel.top() + 64), 12, 12)
            self._knob(p, QPointF(cx, panel.top() + 64), 9, '#e8e7e2', '#8f8d86', '#55554f', 0)
            b = QRectF(cx - 9, panel.top() + 84, 18, 20)
            self._rect(p, b, CH_COLORS[ch] if on else '#cfcec8', '#7f7d76', 3)
            self._text(p, b, ch[-1], '#1b1b1b', 11, bold=True, align=Qt.AlignmentFlag.AlignHCenter)
        # 아래 띠: 전원 버튼, BNC 입력
        self._rect(p, QRectF(L + 14, T + 160, 16, 14), '#f4f3ef', '#8f8d86', 2)
        for i, ch in enumerate(('ch1', 'ch2')):
            c = QPointF(L + 214 + i * 36, T + 170)
            self._bnc(p, c, CH_COLORS[ch])
            self._text(p, QRectF(c.x() - 20, c.y() - 7, 8, 14), ch[-1], '#1b1b1b', 9, bold=True)
        self._bnc(p, QPointF(L + 140, T + 170))
        self._text(p, QRectF(L + 152, T + 163, 34, 14), 'Gen', '#55554f', 8)


class InstrumentWindow(QWidget):
    """장비 패널을 담는 별도 창. 닫으면 숨기기만 합니다."""

    def __init__(self, title, panel, parent):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(f'{title} — BreadLab')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(panel)
        self.placed = False


def _body_font():
    f = QFont()
    f.setFamilies(theme.FONT_FAMILIES)
    f.setPixelSize(9)
    f.setBold(True)
    return f


def body_text_width(text):
    return QFontMetricsF(_body_font()).horizontalAdvance(text) if text else 0


def print_on_body(painter, text, color, flip):
    """몸체 가운데에 값을 인쇄합니다. 부품이 오른쪽→왼쪽으로 꽂혀도 글자가 거꾸로 서지 않게 합니다."""
    painter.save()
    if flip:
        painter.rotate(180)
    painter.setFont(_body_font())
    painter.setPen(QColor(color))
    painter.drawText(QRectF(-40, -7, 80, 14), Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()


class StartCard(QFrame):
    """보드가 비어 있을 때 가운데에 뜨는 시작 카드."""

    def __init__(self, ws):
        super().__init__(ws.view)
        self.ws = ws
        self.dismissed = False
        self.setObjectName('startcard')
        self.setStyleSheet(
            f'QFrame#startcard {{ background: {theme.PANEL}; border: 1px solid {theme.LINE2}; border-radius: 3px; }}'
            f'QFrame#startcard QLabel {{ background: transparent; border: 0; }}'
            f'QPushButton#big {{ text-align: left; padding: 10px 14px; min-height: 40px; }}'
            f'QPushButton#primary {{ text-align: left; padding: 10px 14px; min-height: 40px; '
            f'border-color: {theme.ACCENT}; background: {theme.ACCENT_BG}; color: {theme.TEXT}; }}'
            f'QPushButton#primary:hover {{ background: #3a2224; }}')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(8)
        title = QLabel('무엇부터 해 볼까요?')
        f = title.font()
        f.setPixelSize(17)
        f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)
        sub = QLabel('브레드보드에 부품을 꽂고 전원을 넣어 회로가 어떻게 움직이는지 봅니다.')
        sub.setObjectName('muted')
        sub.setWordWrap(True)
        lay.addWidget(sub)
        lay.addSpacing(4)
        for text, desc, fn in (
                ('LED 켜기 예제로 시작', '완성된 회로를 열고 전원만 켜 봅니다.', self.open_led),
                ('둘러보기', '화면 구성과 사용법을 한 단계씩 봅니다.', ws.start_tour),
                ('빈 보드에서 시작', '왼쪽에서 부품을 골라 직접 꽂습니다.', self.dismiss)):
            b = QPushButton(f'{text}\n{desc}')
            b.setObjectName('primary' if fn == self.open_led else 'big')
            b.clicked.connect(fn)
            lay.addWidget(b)
        self.setFixedWidth(360)
        self.adjustSize()

    def open_led(self):
        self.ws.load_example(0)
        self.ws.open_instrument('psu')

    def dismiss(self):
        self.dismissed = True
        self.hide()
        self.ws.set_mode('resistor')

    def update_visibility(self):
        empty = not self.ws.parts and not any(self.ws.lead(k) for k, *_ in LEADS)
        self.setVisible(empty and not self.dismissed)
        if self.isVisible():
            self.reposition()
            self.raise_()

    def reposition(self):
        v = self.parentWidget()
        self.move((v.width() - self.width()) // 2, int(v.height() * 0.55 - self.height() / 2))


def tool_icon(kind):
    """왼쪽 도구 목록의 작은 그림. 보드 위 부품과 같은 그리기 코드를 씁니다."""
    from types import SimpleNamespace
    pm = QPixmap(60, 36)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(30, 18)
    if kind == 'select':
        path = QPainterPath(QPointF(-6, -12))
        path.lineTo(-6, 10); path.lineTo(-1, 5); path.lineTo(3, 13); path.lineTo(6, 11); path.lineTo(2, 3)
        path.lineTo(9, 3); path.closeSubpath()
        p.setPen(QPen(QColor(theme.TEXT), 1.5)); p.setBrush(QColor(theme.PANEL)); p.drawPath(path)
    elif kind == 'lead':
        p.setPen(QPen(QColor('#888888'), 2)); p.drawLine(QPointF(-14, 8), QPointF(-2, -2))
        p.setPen(QPen(QColor('#111111'), 1)); p.setBrush(QColor(RAIL_RED))
        p.drawRoundedRect(QRectF(-4, -12, 20, 14), 2, 2)
        p.setPen(QColor('#ffffff')); f = QFont(); f.setPixelSize(10); f.setBold(True); p.setFont(f)
        p.drawText(QRectF(-4, -12, 20, 14), Qt.AlignmentFlag.AlignCenter, '1+')
    elif kind == 'wire':
        p.setPen(QPen(QColor(RED), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)); p.drawLine(QPointF(-20, 0), QPointF(20, 0))
    elif kind in IC_KINDS:
        p.setPen(QPen(QColor('#9a978f'), 2))
        for i in range(4):
            x = -15 + i * 10
            p.drawLine(QPointF(x, -14), QPointF(x, 14))
        p.setPen(QPen(QColor('#111111'), 1)); p.setBrush(QColor('#2a2a2a'))
        p.drawRoundedRect(QRectF(-21, -9, 42, 18), 2, 2)
        p.setPen(QColor('#e6e3db')); f = QFont(); f.setPixelSize(9); f.setBold(True); p.setFont(f)
        p.drawText(QRectF(-21, -9, 42, 18), Qt.AlignmentFlag.AlignCenter, '741' if kind == 'opamp' else '555')
    else:
        p.setPen(QPen(QColor('#8f8c84'), 2.5)); p.drawLine(QPointF(-26, 0), QPointF(26, 0))
        part = Part(0, kind, 't0:0', 't0:1', value={'capacitor': 100e-6, 'inductor': 10e-3, 'battery': 9.0,
                                                    'zener': 5.1}.get(kind, 1000.0))
        Device.paint_body(SimpleNamespace(ws=None), p, part,
                          {'current': 0.012} if kind == 'led' else {})
    p.end()
    return QIcon(pm)


class BoardView(QGraphicsView):
    def __init__(self, scene, ws):
        super().__init__(scene)
        self.ws = ws
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor(theme.CANVAS))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumSize(420, 260)
        self.auto_fit = True     # 사용자가 확대/축소하기 전까지는 창 크기에 맞춰 자동으로 맞춤

    def wheelEvent(self, e):
        self.zoom(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)
        e.accept()

    def zoom(self, f):
        if 0.35 < self.transform().m11() * f < 4:
            self.auto_fit = False
            self.scale(f, f)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.ws.__dict__.get('start_card') is not None:
            self.ws.start_card.reposition()
        if self.auto_fit:
            self.fitInView(VIEW_RECT, Qt.AspectRatioMode.KeepAspectRatio)

    def mousePressEvent(self, e):
        item = self.itemAt(e.position().toPoint())
        if e.button() == Qt.MouseButton.RightButton and not isinstance(item, (Device, LeadMarker, InstrumentBox)):
            if self.ws.mode != 'select' or self.ws.pending or self.ws.npn_pins:
                self.ws.set_mode('select')        # 배치 도구 중 빈 곳 우클릭 = 선택 도구로
                e.accept()
                return
        if e.button() == Qt.MouseButton.LeftButton and self.ws.mode == 'select':
            if not isinstance(self.itemAt(e.position().toPoint()), (Device, LeadMarker, InstrumentBox)):
                self.ws.select(None)
        super().mousePressEvent(e)


# ---------------------------------------------------------------- 작업 공간
class BreadboardWorkspace(Workspace):
    title = '브레드보드'
    extensions = ('.bd', '.json')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parts: list[Part] = []
        self.inst = default_instruments()
        self.mode, self.selected, self.pending, self.npn_pins, self.drag = 'select', None, None, [], None
        self.history, self.future = [], []
        self.path, self.saved_state = None, None
        self.sim = Simulator()
        self.result = empty_result()
        self.netmap, self.holes, self.hover_root = net_map([]), {}, None
        self.paused = False
        self.tag_pos = {}
        self._warned = set()
        self.coarse, self._slow = 1, 0
        self._hist, self._trial, self._cap_hint, self._cap_age = [], None, 16, 0
        self.fast_auto = QSettings('BreadLab', 'BreadLab').value('fast_auto', 'true') in ('true', True)
        mode = QSettings('BreadLab', 'BreadLab').value('resistor_display', 'both')
        self.res_display = mode if mode in RES_DISPLAY else 'both'
        self.rebuild_pending, self.step_cost, self.ratio = False, 2e-4, 1.0
        self.last_tick = time.perf_counter()
        self.new_vals = {'resistor': '1k', 'capacitor': '100u', 'npn': '100', 'pnp': '100', 'pot': '10k',
                         'inductor': '10m', 'zener': '5.1', 'nmos': '2', 'battery': '9'}
        self.new_rating = {'resistor': 0.25, 'ldr': 0.25, 'capacitor': 16.0}
        self.new_color = {'wire': RED, 'led': RED}

        self.scene = QGraphicsScene(-40, -60, 1380, 740)
        self.view = BoardView(self.scene, self)
        self._build_ui()
        self._build_menus()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)
        self.set_mode('select')
        self._rebuild()
        self.start_card.update_visibility()
        self.mark_saved()
        QTimer.singleShot(0, self.fit)

    # ------------------------------------------------------------ UI 구성
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split)
        self.left_panel = self._left_panel()
        split.addWidget(self.left_panel)

        board = QWidget()
        bl = QVBoxLayout(board)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        bl.addWidget(self.view, 1)
        self.start_card = StartCard(self)
        self.guide = QLabel()      # 창 상태바에 붙습니다(status_widgets)
        self.clock = QLabel()
        split.addWidget(board)
        self.psu = PsuPanel(self.inst)
        self.fg = FgPanel(self.inst)
        self.scope = Scope()
        self.windows = {'psu': InstrumentWindow('전원 공급기', self.psu, self),
                        'fg': InstrumentWindow('함수 발생기', self.fg, self),
                        'scope': InstrumentWindow('오실로스코프', self.scope, self)}
        self.windows['scope'].resize(980, 460)
        self._reopen = []
        self.right_panel = self._right_panel()
        split.addWidget(self.right_panel)
        split.setStretchFactor(1, 1)
        split.setSizes([176, 1040, 270])
        split.setChildrenCollapsible(False)

        self.psu.changed.connect(self.instrument_changed)
        self.fg.changed.connect(self.instrument_changed)
        self.scope.changed.connect(self.instrument_changed)
        for panel in (self.psu, self.fg, self.scope):
            panel.changed.connect(self.scene.update)
            panel.lead_requested.connect(self.start_lead)

    def _left_panel(self):
        w = QWidget()
        w.setMinimumWidth(160)
        w.setMaximumWidth(200)
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 4, 8, 8)
        v.setSpacing(1)
        self.tool_buttons = {}
        group = QButtonGroup(self)

        def add(kind, text):
            b = QPushButton(tool_icon(kind), text)
            b.setIconSize(QSize(30, 18))
            b.setObjectName('tool')
            b.setCheckable(True)
            b.setToolTip(f'<b>{text}</b> <span style="color:{theme.MUTED}">{TOOL_KEYS[kind]}</span><br>{TOOL_TIPS[kind]}')
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)    # 포커스는 보드에 남겨 둠(Space·화살표 등)
            b.clicked.connect(lambda _=False, k=kind: self.set_mode(k))
            group.addButton(b)
            v.addWidget(b)
            self.tool_buttons[kind] = b

        v.addWidget(theme.section('도구'))
        add('select', '선택')
        add('lead', '리드·프로브')
        groups = dict((first, title) for title, first in TOOL_GROUPS)
        for k, label in TOOLS[2:]:
            if k in groups:
                v.addWidget(theme.section(groups[k]))
            add(k, label)

        self.nf_section = theme.section('설정')
        v.addWidget(self.nf_section)
        self.new_form = QFormLayout()
        self.new_form.setSpacing(4)
        self.nf_lead = QComboBox()
        for k, name, *_ in LEADS:
            self.nf_lead.addItem(name, k)
        self.nf_lead.currentIndexChanged.connect(lambda _: self.paint_holes())
        self.new_form.addRow('리드', self.nf_lead)
        self.nf_color = QComboBox()
        self.nf_value = QLineEdit()
        self.nf_rating = QDoubleSpinBox()
        self.nf_rating.setDecimals(3)
        self.new_form.addRow('색', self.nf_color)
        self.new_form.addRow('값', self.nf_value)
        self.new_form.addRow('정격', self.nf_rating)
        v.addLayout(self.new_form)
        self.nf_hint = QLabel()
        self.nf_hint.setObjectName('muted')
        self.nf_hint.setWordWrap(True)
        v.addWidget(self.nf_hint)
        v.addStretch()
        scroll = QScrollArea()        # 부품이 많아 창이 낮으면 목록을 굴려 봅니다
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(w)
        scroll.setMinimumWidth(176)
        scroll.setMaximumWidth(216)
        return scroll

    def _right_panel(self):
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(8, 4, 8, 8)
        v.setSpacing(4)
        v.addWidget(theme.section('선택한 부품'))
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.detail)
        self.prop_form = QFormLayout()
        self.prop_form.setSpacing(4)
        self.pf_color = QComboBox()
        self.pf_value = QLineEdit()
        self.pf_rating = QDoubleSpinBox()
        self.pf_rating.setDecimals(3)
        self.pf_light = QSlider(Qt.Orientation.Horizontal)
        self.pf_light.setRange(0, 100)
        self.prop_form.addRow('색', self.pf_color)
        self.prop_form.addRow('값', self.pf_value)
        self.prop_form.addRow('정격', self.pf_rating)
        self.prop_form.addRow('밝기', self.pf_light)
        v.addLayout(self.prop_form)
        row = QHBoxLayout()
        self.apply_btn = QPushButton('적용')
        self.apply_btn.clicked.connect(self.apply_props)
        self.switch_btn = QPushButton('스위치 전환')
        self.switch_btn.clicked.connect(self.toggle_switch)
        row.addWidget(self.apply_btn)
        row.addWidget(self.switch_btn)
        row.addStretch()
        v.addLayout(row)
        self.pf_value.returnPressed.connect(self.apply_props)
        self.pf_light.sliderPressed.connect(self.snapshot)
        self.pf_light.valueChanged.connect(self.change_light)

        self.alerts_section = theme.section('경고')
        v.addWidget(self.alerts_section)
        self.alerts = QLabel()
        self.alerts.setObjectName('alerts')
        self.alerts.setWordWrap(True)
        self.alerts.setTextFormat(Qt.TextFormat.RichText)
        self.alerts.setAlignment(Qt.AlignmentFlag.AlignTop)
        v.addWidget(self.alerts)
        self.alerts_section.hide()
        self.alerts.hide()
        v.addWidget(theme.section('부품 목록'))
        self.list = QListWidget()
        self.list.setMinimumHeight(140)
        self.list.currentRowChanged.connect(self.list_selected)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.list_menu)
        v.addWidget(self.list, 1)


        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setMinimumWidth(250)
        scroll.setMaximumWidth(340)
        return scroll

    def _build_menus(self):
        def act(menu, text, fn, shortcut=None, checkable=False, checked=False, widget=None):
            """shortcut: 문자열 하나 또는 목록(첫 번째가 메뉴에 표시됨).
            단축키는 장비 창에 포커스가 있어도 동작하도록 앱 전체 범위로 둡니다.
            (다른 탭의 동작은 메인 창이 비활성화하므로 서로 부딪히지 않습니다.)"""
            a = QAction(text, self)
            if shortcut:
                keys = [shortcut] if isinstance(shortcut, str) else list(shortcut)
                a.setShortcuts([QKeySequence(k) for k in keys])
                a.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut if widget
                                     else Qt.ShortcutContext.ApplicationShortcut)
            if checkable:
                a.setCheckable(True)
                a.setChecked(checked)
                a.toggled.connect(fn)
            else:
                a.triggered.connect(lambda _=False: fn())
            menu.addAction(a)
            (widget or self).addAction(a)
            return a

        m_file = QMenu('파일(&F)', self)
        act(m_file, '새 회로', self.new_file, 'Ctrl+N')
        act(m_file, '열기…', self.open_file, 'Ctrl+O')
        act(m_file, '회로도 파일 가져오기…', self.import_schematic, 'Ctrl+I')
        act(m_file, '저장', self.save, 'Ctrl+S')
        act(m_file, '다른 이름으로 저장…', self.save_as, 'Ctrl+Shift+S')
        m_file.addSeparator()
        act(m_file, '보드 이미지 저장…', self.save_board_image)
        act(m_file, '보드 이미지 복사', self.copy_board_image, 'Ctrl+Shift+C')
        act(m_file, '스코프 화면 저장…', self.save_scope_image)
        act(m_file, '스코프 파형 CSV로 저장…', self.save_scope_csv)
        act(m_file, '회로도 내보내기…', lambda: self.schematic_window().export(), 'Ctrl+E')

        m_edit = QMenu('편집(&E)', self)
        self.a_undo = act(m_edit, '실행 취소', self.undo, 'Ctrl+Z')
        self.a_redo = act(m_edit, '다시 실행', self.redo, ['Ctrl+Y', 'Ctrl+Shift+Z'])
        m_edit.addSeparator()
        act(m_edit, '선택 부품 삭제', self.delete_selected, ['Del', 'Backspace'])
        act(m_edit, '스위치 전환', self.toggle_switch, 'Space', widget=self)
        act(m_edit, '취소 · 선택 해제', self.escape, 'Esc')
        m_edit.addSeparator()
        act(m_edit, '모두 지우기…', self.clear_all)

        m_tool = QMenu('도구(&T)', self)
        self.tool_actions = {}
        for kind, label in TOOLS:
            a = act(m_tool, label, lambda k=kind: self.set_mode(k), TOOL_KEYS[kind], checkable=False)
            a.setCheckable(True)
            self.tool_actions[kind] = a
            if kind == 'lead':
                m_tool.addSeparator()

        m_view = QMenu('보기(&V)', self)
        act(m_view, '화면 맞춤', self.fit, 'Ctrl+0')
        act(m_view, '확대', lambda: self.view.zoom(1.2), ['Ctrl+=', 'Ctrl++'])
        act(m_view, '축소', lambda: self.view.zoom(1 / 1.2), 'Ctrl+-')
        m_view.addSeparator()
        m_res = m_view.addMenu('저항 표시')
        group = QActionGroup(self)
        for key, label in RES_DISPLAY.items():
            a = QAction(label, self, checkable=True, checked=self.res_display == key)
            a.triggered.connect(lambda _=False, k=key: self.set_res_display(k))
            group.addAction(a)
            m_res.addAction(a)
        m_view.addSeparator()
        act(m_view, '전원 공급기', lambda: self.open_instrument('psu'), 'Ctrl+1')
        act(m_view, '함수 발생기', lambda: self.open_instrument('fg'), 'Ctrl+2')
        act(m_view, '오실로스코프', lambda: self.open_instrument('scope'), 'Ctrl+3')
        m_view.addSeparator()
        act(m_view, '회로도', self.open_schematic, 'Ctrl+4')

        m_sim = QMenu('시뮬레이션(&S)', self)
        self.a_pause = act(m_sim, '일시정지', self.set_paused, 'F5', checkable=True)
        act(m_sim, '회로 초기화 (시간 0, 커패시터 방전)', self.reset_sim, 'Ctrl+Shift+F5')
        act(m_sim, '모든 출력 끄기', self.all_outputs_off, 'F8')
        warn_on = QSettings('BreadLab', 'BreadLab').value('danger_popup', 'true') in ('true', True)
        self.danger_popup = warn_on
        act(m_sim, '단락·부품 손상 경고창 띄우기', self.set_danger_popup, checkable=True, checked=warn_on)
        act(m_sim, '느리면 빠른 계산으로 바꾸기 (정밀도 낮춤)', self.set_fast_auto, checkable=True,
            checked=self.fast_auto)
        m_sim.addSeparator()
        act(m_sim, '스코프 Run/Stop', lambda: self.scope.set_running(not self.scope.running), 'F9')
        act(m_sim, '스코프 자동 설정', self.scope.autoset, 'F4')
        act(m_sim, '모든 리드·프로브 떼기', self.detach_all)

        m_ex = QMenu('예제(&X)', self)
        for i, (title, _, _) in enumerate(EXAMPLES):
            act(m_ex, title, lambda i=i: self.load_example(i))
        self._menus = [m_file, m_edit, m_tool, m_view, m_sim, m_ex]

    def show_help(self):
        """F1: 사용법과 단축키(메뉴에서 자동으로 모아 묶음별로 보여 줍니다)."""
        dlg = QDialog(self)
        dlg.setWindowTitle('브레드보드 도움말')
        dlg.resize(560, 620)
        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)
        intro = QLabel(HELP_TEXT)
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(intro)
        tour = QPushButton('둘러보기 다시 보기')
        tour.clicked.connect(lambda: (dlg.accept(), self.start_tour()))
        lay.addWidget(tour, 0, Qt.AlignmentFlag.AlignLeft)
        for m in self._menus:
            rows = []
            for a in m.actions():
                keys = [k.toString(QKeySequence.SequenceFormat.NativeText) for k in a.shortcuts()]
                if keys:
                    rows.append((a.text(), ' · '.join(keys)))
            if not rows:
                continue
            lay.addWidget(theme.section(m.title().split('(')[0]))
            grid = QGridLayout()
            grid.setHorizontalSpacing(24)
            grid.setVerticalSpacing(3)
            for r, (name, keys) in enumerate(rows):
                grid.addWidget(QLabel(name), r, 0)
                k = QLabel(keys)
                k.setObjectName('muted')
                grid.addWidget(k, r, 1)
            grid.setColumnStretch(2, 1)
            lay.addLayout(grid)
        lay.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll)
        close = QPushButton('닫기')
        close.clicked.connect(dlg.accept)
        row = QHBoxLayout()
        row.setContentsMargins(12, 8, 12, 12)
        row.addStretch()
        row.addWidget(close)
        outer.addLayout(row)
        dlg.exec()

    # ---------- 둘러보기
    def tour_steps(self):
        from arduino_lab.tour import Step
        return [
            Step('브레드보드 실습실', '부품을 꽂고, 장비로 전원을 넣고, 오실로스코프로 재 봅니다. 다음(→)을 누르십시오.'),
            Step('1. 부품 고르기', '왼쪽에서 부품을 고릅니다. 마우스를 올리면 하는 일이 나옵니다. 저항은 R, LED는 L처럼 키보드로도 고릅니다.',
                 lambda: self.left_panel),
            Step('2. 보드에 꽂기', '구멍에서 구멍으로 끌면 꽂힙니다. 같은 번호의 세로 다섯 칸(A~E, F~J)은 안에서 이어져 있습니다. '
                 '구멍에 마우스를 올리면 이어진 구멍이 밝게 보입니다.', lambda: self.view),
            Step('3. 전원 연결하고 켜기', '위쪽 장비를 누르면 장비 창이 열립니다. 전원 창의 + 꽂기, − 꽂기를 누르고 보드 구멍을 누르면 '
                 '집게가 물립니다. 출력 ON을 누르면 전기가 흐릅니다.', lambda: self.view),
            Step('4. 값 보고 바꾸기', '부품을 누르면 여기에 전압과 전류가 나오고, 저항값 같은 설정도 바꿀 수 있습니다. '
                 '문제가 생기면 경고와 고치는 방법이 나옵니다.', lambda: self.right_panel),
            Step('시작해 볼까요?', 'LED 하나를 켜는 예제부터 해 보십시오. 도움말과 단축키는 F1, 실행 취소는 Ctrl+Z입니다.',
                 action=('LED 예제 열기', lambda: self.load_example(0))),
        ]

    def start_tour(self):
        from arduino_lab.tour import TourOverlay
        if getattr(self, 'tour', None) is None:
            self.tour = TourOverlay(self, self.tour_steps())
            self.tour.finished.connect(lambda _done: QSettings('BreadLab', 'BreadLab').setValue('breadboard/tour_seen', True))
        self.start_card.hide()
        self.tour.start()

    def maybe_first_tour(self):
        import os
        if os.environ.get('BREADLAB_NO_TOUR'):
            return
        if not QSettings('BreadLab', 'BreadLab').value('breadboard/tour_seen', False, type=bool):
            self.start_tour()

    def menus(self):
        return self._menus

    def status_widgets(self):
        return self.guide, self.clock

    # ------------------------------------------------------------ 문서 상태
    def document(self, outputs=True):
        inst = copy.deepcopy(self.inst)
        if not outputs:
            for ch in ('ch1', 'ch2'):
                inst['psu'][ch]['on'] = False
            inst['fg']['on'] = False
        return make_document(self.parts, inst)

    def state_key(self):
        return json.dumps(self.document(outputs=False), sort_keys=True)

    def mark_saved(self):
        self.saved_state = self.state_key()
        self.title_changed.emit()

    def is_modified(self):
        return self.state_key() != self.saved_state

    def document_title(self):
        name = self.path.name if self.path else '이름 없는 회로'
        return name + (' *' if self.is_modified() else '')

    def snapshot(self):
        self.history.append(self._state())
        del self.history[:-HISTORY_LIMIT]
        self.future.clear()
        self._update_undo()

    def _state(self):
        return [asdict(p) for p in self.parts], dict(self.inst['scope']), dict(self.inst['leads'])

    def _restore(self, state):
        parts, probes, leads = state
        self.parts = [Part(**d) for d in parts]
        self.inst['scope'].update(probes)
        self.inst['leads'].update(leads)
        self.selected = self.pending = None
        self.npn_pins = []
        self.refresh()

    def undo(self):
        if self.history:
            self.future.append(self._state())
            self._restore(self.history.pop())

    def redo(self):
        if self.future:
            self.history.append(self._state())
            self._restore(self.future.pop())

    def _update_undo(self):
        self.a_undo.setEnabled(bool(self.history))
        self.a_redo.setEnabled(bool(self.future))

    # ------------------------------------------------------------ 갱신
    def schematic_window(self):
        if getattr(self, '_schematic', None) is None:
            from schematic_window import SchematicWindow
            self._schematic = SchematicWindow(self)
        return self._schematic

    def open_schematic(self):
        w = self.schematic_window()
        w.show()
        w.raise_()
        w.activateWindow()

    def refresh(self):
        self.start_card.update_visibility()
        if getattr(self, '_schematic', None) is not None:
            self._schematic.refresh()
        self.update_list()
        self.update_detail(True)
        self._update_undo()
        self.title_changed.emit()
        self.schedule_rebuild()

    def schedule_rebuild(self):
        if not self.rebuild_pending:
            self.rebuild_pending = True
            QTimer.singleShot(0, self._rebuild)

    def _rebuild(self):
        self.rebuild_pending = False
        self._cancel_drag()
        sc = self.scene
        sc.clear()
        self.holes = {}
        self.netmap = net_map(self.parts, self.inst['leads'])
        pen0 = QPen(Qt.PenStyle.NoPen)

        # 장비 상자(클릭하면 장비 창이 열립니다)
        for kind in ('psu', 'fg', 'scope'):
            sc.addItem(InstrumentBox(kind, self))

        # 브레드보드
        sc.addRect(36, 42, 902, 550, QPen(QColor(B_EDGE)), QBrush(QColor(B_FILL)))
        sc.addRect(70, 299, 840, 22, pen0, QBrush(QColor(B_CHANNEL)))
        for c in range(30):
            for y in (151, 466):
                self._text(89 + c * 27, y, str(c + 1), B_TEXT, 8)
        for s in ('t', 'b'):
            for r in range(5):
                self._text(53, pos(f'{s}{r}:0').y() - 7, ('ABCDE' if s == 't' else 'FGHIJ')[r], B_TEXT, 10)
        for r in range(4):
            y = pos(f'r{r}:0').y()
            color = RAIL_RED if r % 2 == 0 else RAIL_BLUE
            sc.addLine(83, y - 11, 894, y - 11, QPen(QColor(color), 1.5))
            self._text(53, y - 9, '+' if r % 2 == 0 else '−', color, 13)

        self.layout_tags()
        for p in self.parts:
            sc.addItem(Device(p, self))
        for h in HOLES:
            item = Hole(h, self)
            sc.addItem(item)
            self.holes[h] = item
        placed = []
        for k, *_ in LEADS:
            h = self.lead(k)
            if not h:
                continue
            for idx in range(len(MARK_OFFSETS)):     # 다른 집게 표시와 겹치지 않는 방향을 고릅니다
                m = LeadMarker(k, h, idx, self)
                if not any(m.tag_rect().adjusted(-2, -2, 2, 2).intersects(r) for r in placed):
                    break
            placed.append(m.tag_rect())
            sc.addItem(m)
        self.scope.set_probes(self.inst['scope'])
        self.paint_holes()

    def layout_tags(self):
        """저항·LDR·가변저항의 값 꼬리표가 서로나 다른 부품 몸체와 겹치지 않는 자리를 고릅니다."""
        self.tag_pos = {}
        bodies = []
        for p in self.parts:
            if p.kind == 'wire':
                continue
            if p.kind in IC_KINDS:
                bodies.append(ic_rect(p.a))
                continue
            a, b = pos(p.a), pos(p.b)
            mid = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
            bodies.append(QRectF(mid.x() - 16, mid.y() - 12, 32, 24))
        placed = []
        for p in self.parts:
            if not (p.kind in ('ldr', 'pot') or (p.kind == 'resistor' and self.res_display == 'both')):
                continue
            a, b = pos(p.a), pos(p.b)
            mid = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
            cands = tag_candidates(p, value_text(p), a, b, mid)
            own = QRectF(mid.x() - 16, mid.y() - 12, 32, 24)
            def clash(r):
                return sum(r.intersects(o) for o in placed) * 3 + sum(
                    r.intersects(o) for o in bodies if o != own)
            best = min(cands, key=lambda r: (clash(r), cands.index(r)))
            self.tag_pos[p.id] = best
            placed.append(best)

    def _text(self, x, y, text, color, size, width=None):
        f = QFont()
        f.setPixelSize(size)
        t = self.scene.addSimpleText(text, f)
        t.setBrush(QColor(color))
        if width:
            x += (width - t.boundingRect().width()) / 2
        t.setPos(x, y)
        return t

    def paint_holes(self):
        marks = set(self.npn_pins)
        if self.pending:
            marks.add(self.pending)
        if self.drag and self.drag.get('target'):
            marks.add(self.drag['target'])
        if self.mode == 'lead' and self.lead(self.nf_lead.currentData()):
            marks.add(self.lead(self.nf_lead.currentData()))
        root = self.netmap.get(self.hover_root) if self.hover_root else getattr(self, 'ext_root', None)
        for h, item in self.holes.items():
            item.set_active(h in marks or (root is not None and self.netmap[h] == root))

    def hover_hole(self, h):
        self.hover_root = h
        self.paint_holes()
        if getattr(self, '_schematic', None) is not None:
            self._schematic.board_hover(net=self.netmap.get(h) if h else None)

    def highlight_net(self, root):
        """회로도에서 짚은 마디: 보드에서 이어진 구멍을 모두 표시합니다."""
        if getattr(self, 'ext_root', None) != root:
            self.ext_root = root
            self.paint_holes()

    def set_hover_part(self, pid):
        """회로도에서 마우스를 올린 부품을 보드에서 옅게 표시합니다."""
        if getattr(self, 'hover_part', None) != pid:
            self.hover_part = pid
            self.scene.update()

    def part_hovered(self, pid):
        if getattr(self, '_schematic', None) is not None:
            self._schematic.board_hover(part=pid)

    def hole_tooltip(self, h):
        lines = [hole_label(h)]
        root = self.netmap[h]
        same = sum(1 for x in self.netmap.values() if x == root) - 1
        if same:
            lines.append(f'이어진 구멍 {same}개')
        here = [LEAD_INFO[k][0] for k, *_ in LEADS if self.lead(k) == h]
        if here:
            lines.append('물린 리드: ' + ', '.join(here))
        if h in self.result['nodes']:
            lines.append(f'{self.result["nodes"][h]:+.4f} V (CH1 − 기준)')
        else:
            lines.append('전위 미정 (전원에 이어지지 않음)')
        return '\n'.join(lines)

    def part_tooltip(self, p):
        tag = designators(self.parts).get(p.id, '')
        lines = [f'{tag}  {NAMES[p.kind]}  {value_text(p)}', self.pins_text(p)]
        info = self.result['parts'].get(p.id)
        if info and self.powered(p):
            lines.append(self.measure_text(p, info))
            lines += info['alerts']
        elif p.kind != 'wire':
            lines.append(self.unpowered_text())
        return '\n'.join(x for x in lines if x)

    def instruments_on(self):
        r = self.result
        return any(r['psu'][c]['mode'] in ('CV', 'CC') for c in ('ch1', 'ch2')) or self.inst['fg']['on']

    def powered(self, p):
        """켜진 장비에 이어져 있어 측정값이 의미 있는 부품인가."""
        return self.instruments_on() and not any(h in self.result['floating'] for h in p.pins() if h)

    def unpowered_text(self):
        return '전원에 이어지지 않았습니다.' if self.instruments_on() else '장비 출력이 꺼져 있습니다.'

    def pins_text(self, p):
        if p.kind in ('led', 'diode', 'zener'):
            return f'애노드 {hole_label(p.a)} · 캐소드 {hole_label(p.b)}'
        if p.kind == 'battery':
            return f'+ {hole_label(p.a)} · − {hole_label(p.b)}'
        if p.kind in THREE_PIN:
            return ' · '.join(f'{n} {hole_label(h)}' for n, h in zip(PIN_NAMES[p.kind], p.pins()) if h)
        if p.kind in IC_KINDS:
            return f'1번 핀 {hole_label(p.a)} · 8번 핀 {hole_label(p.b)}'
        return f'{hole_label(p.a)} — {hole_label(p.b)}'

    @staticmethod
    def measure_text(p, info):
        if p.kind == 'nmos':
            return (f'V_DS {info["voltage"]:.3f} V · I_D {format_si(info["current"], "A")} · '
                    f'V_GS {info["vgs"]:.2f} V')
        if p.kind == 'pot':
            return (f'양 끝 {info["voltage"]:+.3f} V · 와이퍼 {info["wiper"]:+.3f} V(3번 끝 기준) · '
                    f'{format_si(info["current"], "A")}')
        if p.kind == 'opamp':
            return (f'출력 {info["vout"]:+.3f} V · 입력 차 {info["vdiff"] * 1000:+.3f} mV · '
                    f'출력 전류 {format_si(info["current"], "A")}')
        if p.kind == 'timer555':
            return (f'출력 {"H" if info["state"] else "L"} ({info["vout"]:+.2f} V) · 전원 {info["voltage"]:.2f} V · '
                    f'출력 전류 {format_si(info["current"], "A")}')
        if p.kind in ('npn', 'pnp'):
            return (f'V_CE {info["voltage"]:.3f} V · I_C {format_si(info["current"], "A")} · '
                    f'I_B {format_si(info["ib"], "A")}')
        return (f'{info["voltage"]:+.4f} V · {format_si(info["current"], "A")} · '
                f'{format_si(info["power"], "W")}')

    def update_list(self):
        tags = designators(self.parts)
        self.list.blockSignals(True)
        self.list.clear()
        for p in self.parts:
            self.list.addItem(f'{tags[p.id]:<5} {NAMES[p.kind]}  {value_text(p)}')
        self.list.setCurrentRow(next((i for i, p in enumerate(self.parts) if p.id == self.selected), -1))
        self.list.blockSignals(False)

    def selected_part(self):
        return next((p for p in self.parts if p.id == self.selected), None)

    def update_detail(self, fields=False):
        p = self.selected_part()
        k = p.kind if p else None
        f = self.prop_form
        f.setRowVisible(self.pf_color, k in ('wire', 'led'))
        f.setRowVisible(self.pf_value, k in PARSERS)
        f.setRowVisible(self.pf_rating, k in ('resistor', 'ldr', 'capacitor'))
        f.setRowVisible(self.pf_light, k in ('ldr', 'pot'))
        if k in ('ldr', 'pot'):
            f.labelForField(self.pf_light).setText('밝기' if k == 'ldr' else '위치')
        self.apply_btn.setVisible(k in PARSERS or k in ('wire', 'led', 'ldr'))
        self.switch_btn.setVisible(k in ('switch', 'spdt'))
        if not p:
            self.detail.setText('선택한 부품이 없습니다.')
            return
        tag = designators(self.parts)[p.id]
        lines = [f'{tag}  {NAMES[p.kind]}  {value_text(p)}', self.pins_text(p)]
        info = self.result['parts'].get(p.id)
        if p.kind == 'wire':
            lines.append('저항 0 Ω인 이상적인 전선으로 계산합니다.')
        elif info and self.powered(p):
            lines.append(self.measure_text(p, info))
            lines += info['alerts']
        else:
            lines.append(self.unpowered_text())
        text = '\n'.join(lines)
        if self.detail.text() != text:
            self.detail.setText(text)
        if not fields:
            return
        if k in ('wire', 'led'):
            self._fill_colors(self.pf_color, WIRE_COLORS if k == 'wire' else LED_COLORS, p.color)
        if k in PARSERS:
            self.pf_value.setText(short_value(p))
        if k in ('resistor', 'ldr', 'capacitor'):
            self._rating_range(self.pf_rating, k)
            self.pf_rating.setValue(p.rating)
        if k in ('ldr', 'pot'):
            self.pf_light.blockSignals(True)
            self.pf_light.setValue(int(p.light if k == 'ldr' else p.pos))
            self.pf_light.blockSignals(False)

    @staticmethod
    def _fill_colors(combo, colors, current):
        combo.blockSignals(True)
        combo.clear()
        for c in colors:
            combo.addItem(COLOR_NAMES[c] + (f' · {LED_VF_TEXT[c]}' if colors is LED_COLORS else ''), c)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.blockSignals(False)

    @staticmethod
    def _rating_range(spin, kind):
        if kind == 'capacitor':
            spin.setRange(1, 100)
            spin.setDecimals(0)
            spin.setSuffix(' V')
        else:
            spin.setRange(0.001, 100)
            spin.setDecimals(3)
            spin.setSuffix(' W')

    # ------------------------------------------------------------ 선택·도구
    def set_mode(self, mode):
        self._cancel_drag()
        self.pending, self.npn_pins = None, []
        self._store_new_fields()
        self.mode = mode
        self._load_new_fields()
        for k, b in self.tool_buttons.items():
            b.setChecked(k == mode)
        for k, a in getattr(self, 'tool_actions', {}).items():
            a.setChecked(k == mode)
        self.guide.setText(GUIDE.get(mode, GUIDE_PART))
        if mode != 'select' and getattr(self, 'start_card', None) is not None and self.start_card.isVisible():
            self.start_card.dismissed = True      # 도구를 고르면 시작 카드는 비켜 줍니다
            self.start_card.hide()
        self.schedule_rebuild()

    def _store_new_fields(self):
        k = getattr(self, 'mode', None)
        if k in self.new_vals:
            self.new_vals[k] = self.nf_value.text()
        if k in self.new_rating:
            self.new_rating[k] = self.nf_rating.value()
        if k in self.new_color and self.nf_color.currentData():
            self.new_color[k] = self.nf_color.currentData()

    def _load_new_fields(self):
        k = self.mode
        f = self.new_form
        f.setRowVisible(self.nf_lead, k == 'lead')
        f.setRowVisible(self.nf_color, k in self.new_color)
        f.setRowVisible(self.nf_value, k in self.new_vals)
        f.setRowVisible(self.nf_rating, k in self.new_rating)
        if k in self.new_color:
            self._fill_colors(self.nf_color, WIRE_COLORS if k == 'wire' else LED_COLORS, self.new_color[k])
        if k in self.new_vals:
            self.nf_value.setText(self.new_vals[k])
            self.nf_value.setPlaceholderText({'resistor': '330, 4.7k, 1M', 'capacitor': '100u, 47n',
                                              'npn': 'β 10~1000', 'pnp': 'β 10~1000', 'pot': '1k, 10k, 100k',
                                              'inductor': '10m, 100u', 'zener': '전압 5.1, 12',
                                              'nmos': '문턱 전압 2', 'battery': '전압 1.5, 9'}[k])
        if k in self.new_rating:
            self._rating_range(self.nf_rating, k)
            self.nf_rating.setValue(self.new_rating[k])
        hints = {'resistor': '정격은 전력(W)입니다.', 'capacitor': '정격은 내압(V)입니다. 비극성 모델입니다.',
                 'npn': 'β는 전류 증폭률입니다.', 'ldr': '밝기는 설치 후 오른쪽 패널에서 바꿉니다.',
                 'pnp': 'β는 전류 증폭률입니다.', 'pot': '값은 양 끝 사이 전체 저항입니다. 위치는 오른쪽 패널에서 돌립니다.',
                 'inductor': '값은 인덕턴스(H)입니다.', 'zener': '값은 항복 전압입니다.',
                 'nmos': '값은 켜지기 시작하는 게이트 전압입니다.', 'battery': '내부 저항 0.1 Ω으로 계산합니다.',
                 'opamp': '전원 7번(V+)·4번(V−) 핀을 꼭 이으십시오.', 'timer555': '8번 VCC, 1번 GND, 4번 RESET은 VCC에 이으십시오.',
                 'lead': 'CH1 −, 함수 발생기 COM, 스코프 접지는 장비 안에서 이어진 공통 접지입니다.'}
        self.nf_hint.setText(hints.get(k, ''))
        self.nf_hint.setVisible(k in hints)
        self.nf_section.setVisible(k in self.new_color or k in self.new_vals or k in self.new_rating
                                   or k in hints or k == 'lead')

    def new_part_values(self):
        self._store_new_fields()
        k = self.mode
        if k in ('resistor', 'capacitor'):
            return dict(value=PARSERS[k](self.new_vals[k]), rating=self.new_rating[k])
        if k in ('npn', 'pnp'):
            return dict(value=PARSERS[k](self.new_vals[k]), rating=0.625)
        if k in PARSERS:
            return dict(value=PARSERS[k](self.new_vals[k]), rating=0.5)
        if k == 'ldr':
            return dict(rating=self.new_rating[k])
        if k in ('wire', 'led'):
            return dict(color=self.new_color[k])
        return {}

    def select(self, pid):
        if pid != self.selected:
            self.selected = pid
            self.list.blockSignals(True)
            self.list.setCurrentRow(next((i for i, p in enumerate(self.parts) if p.id == pid), -1))
            self.list.blockSignals(False)
            self.update_detail(True)
            if getattr(self, '_schematic', None) is not None:
                self._schematic.set_selected(pid)
            self.scene.update()

    def list_selected(self, row):
        self.select(self.parts[row].id if 0 <= row < len(self.parts) else None)

    def escape(self):
        if self.drag or self.pending or self.npn_pins:
            self._cancel_drag()
            self.pending, self.npn_pins = None, []
            self.guide.setText(GUIDE.get(self.mode, GUIDE_PART))
            self.paint_holes()
        elif self.mode != 'select':
            self.set_mode('select')
        else:
            self.select(None)

    # ------------------------------------------------------------ 설치·이동
    def hole_pressed(self, h):
        if self.mode == 'lead':
            key = self.nf_lead.currentData()
            self.set_lead(key, None if self.lead(key) == h else h)
            return
        if self.mode in THREE_PIN:
            if h in self.npn_pins:
                return
            self.npn_pins.append(h)
            if len(self.npn_pins) < 3:
                nxt = PIN_LABEL[self.mode][len(self.npn_pins)]
                self.guide.setText(f'다음: {nxt} 구멍을 클릭하십시오. (Esc 취소)')
                self.paint_holes()
                return
            pins, self.npn_pins = self.npn_pins, []
            self.guide.setText(GUIDE[self.mode])
            self.place(pins[0], pins[1], pins[2])
            return
        if self.mode in IC_KINDS:
            a = ic_anchor(h)
            self.place(a, dip_pins(a)[7])
            return
        if self.mode not in PART_TOOLS:
            return
        if self.pending:
            start, self.pending = self.pending, None
            self.guide.setText(GUIDE.get(self.mode, GUIDE_PART))
            if h != start:
                self.place(start, h)
            self.paint_holes()
            return
        try:
            vals = self.new_part_values()
        except ValueError:
            vals = {}
        ghost = Part(0, self.mode, h, pos(h), **vals)
        item = Device(ghost, self, ghost=True)
        self.scene.addItem(item)
        self.drag = dict(kind='new', start=h, target=None, moved=False, ghost=item)

    def start_move(self, item, pin):
        ghost = Part(**asdict(item.part))
        g = Device(ghost, self, ghost=True)
        self.scene.addItem(g)
        item.setOpacity(0.25)
        self.drag = dict(kind='move', item=item, part=item.part, pin=pin, ghost=g, target=None, moved=False,
                         start=getattr(item.part, pin))

    def nearest_hole(self, pt, allow_terminals):
        best, dist = None, SNAP
        for h, item in self.holes.items():
            q = item.pos()
            d = math.hypot(q.x() - pt.x(), q.y() - pt.y())
            if d < dist:
                best, dist = h, d
        return best

    def drag_move(self, pt):
        d = self.drag
        if not d:
            return
        kind = d['part'].kind if d['kind'] == 'move' else self.mode
        target = self.nearest_hole(pt, kind == 'wire')
        start = pos(d['start'])
        if math.hypot(pt.x() - start.x(), pt.y() - start.y()) > 4:
            d['moved'] = True
        d['target'] = target
        gp = d['ghost'].part
        setattr(gp, 'b' if d['kind'] == 'new' else d['pin'], target or pt)
        d['ghost'].update_path()
        d['ghost'].update()
        self.paint_holes()

    def drag_release(self):
        d, self.drag = self.drag, None
        if not d:
            return
        self.scene.removeItem(d['ghost'])
        t = d['target']
        if d['kind'] == 'new':
            if d['moved']:
                if t and t != d['start']:
                    self.place(d['start'], t)
            else:
                self.pending = d['start']
                self.guide.setText(f'시작: {hole_label(d["start"])} → 둘째 구멍을 클릭하십시오. (Esc 취소)')
            self.paint_holes()
            return
        d['item'].setOpacity(1.0)
        part, pin = d['part'], d['pin']
        if part.kind in IC_KINDS:                 # IC는 통째로 옮깁니다(잡은 핀 위치만큼 당겨서)
            a = None
            if t:
                col = int(t.split(':')[1]) - d.get('ic_off', 0)
                a = ic_anchor(f'b0:{max(col, 0)}')
            if a and a != part.a:
                self.snapshot()
                part.a, part.b = a, dip_pins(a)[7]
                self.refresh()
            else:
                self.paint_holes()
            return
        if not t or t == getattr(part, pin):
            self.paint_holes()
            return
        others = [getattr(part, n) for n in ('a', 'b', 'c') if n != pin and getattr(part, n)]
        if t in others:
            self.status_message.emit('한 부품의 두 다리를 같은 구멍에 꽂을 수 없습니다.', 3000)
            self.paint_holes()
            return
        self.snapshot()
        setattr(part, pin, t)
        self.refresh()

    def _cancel_drag(self):
        d, self.drag = self.drag, None
        if d:
            try:
                self.scene.removeItem(d['ghost'])
                if d['kind'] == 'move':
                    d['item'].setOpacity(1.0)
            except RuntimeError:
                pass

    def place(self, a, b, c=None):
        try:
            vals = self.new_part_values()
        except ValueError as e:
            QMessageBox.warning(self, '입력 오류', str(e))
            return
        self.snapshot()
        pid = max((p.id for p in self.parts), default=0) + 1
        self.parts.append(Part(pid, self.mode, a, b, c=c, **vals))
        self.selected = pid
        self.refresh()

    def lead(self, key):
        if key.startswith('scope:'):
            return self.inst['scope'][key[6:]]
        return self.inst['leads'][key]

    def set_lead(self, key, h):
        if self.lead(key) == h:
            return
        self.snapshot()
        if key.startswith('scope:'):
            self.inst['scope'][key[6:]] = h
            self.scope.clear()
        else:
            self.inst['leads'][key] = h
        name = LEAD_INFO[key][0]
        self.status_message.emit(f'{name}: {hole_label(h)}에 물렸습니다.' if h else f'{name}를 뗐습니다.', 3000)
        self.refresh()

    def start_lead(self, key):
        """장비 창의 '꽂기' 버튼: 리드 도구로 바꾸고 해당 리드를 고릅니다."""
        self.set_mode('lead')
        self.nf_lead.setCurrentIndex(self.nf_lead.findData(key))
        self.guide.setText(f'{LEAD_INFO[key][0]}를 물릴 구멍을 클릭하십시오.')
        self.window().raise_()
        self.window().activateWindow()

    def detach_all(self):
        if not any(self.lead(k) for k, *_ in LEADS):
            return
        self.snapshot()
        for k in self.inst['leads']:
            self.inst['leads'][k] = None
        self.inst['scope'].update(ch1=None, ch2=None)
        self.scope.clear()
        self.refresh()

    # ------------------------------------------------------------ 편집
    def delete_selected(self):
        if self.selected_part():
            self.snapshot()
            self.parts = [p for p in self.parts if p.id != self.selected]
            self.selected = None
            self.refresh()

    def toggle_switch(self):
        p = self.selected_part()
        if p and p.kind in ('switch', 'spdt'):
            self.snapshot()
            p.closed = not p.closed
            self.refresh()

    def part_menu(self, where):
        p = self.selected_part()
        if not p:
            return
        menu = QMenu(self)
        sw = menu.addAction('스위치 전환') if p.kind in ('switch', 'spdt') else None
        rm = menu.addAction('삭제')
        chosen = menu.exec(where)
        if chosen is rm:
            QTimer.singleShot(0, self.delete_selected)
        elif sw is not None and chosen is sw:
            QTimer.singleShot(0, self.toggle_switch)

    def list_menu(self, point):
        item = self.list.itemAt(point)
        if item:
            self.list.setCurrentItem(item)
            self.part_menu(self.list.viewport().mapToGlobal(point))

    def apply_props(self):
        p = self.selected_part()
        if not p:
            return
        new = {}
        try:
            if p.kind in PARSERS:
                new['value'] = PARSERS[p.kind](self.pf_value.text())
        except ValueError as e:
            QMessageBox.warning(self, '입력 오류', str(e))
            return
        if p.kind in ('resistor', 'ldr', 'capacitor'):
            new['rating'] = self.pf_rating.value()
        if p.kind in ('wire', 'led'):
            new['color'] = self.pf_color.currentData()
        if all(getattr(p, k) == v for k, v in new.items()):
            return
        self.snapshot()
        for k, v in new.items():
            setattr(p, k, v)
        self.refresh()

    def change_light(self, value):
        p = self.selected_part()
        if p and p.kind in ('ldr', 'pot'):
            if not self.pf_light.isSliderDown():
                self.snapshot()
            if p.kind == 'ldr':
                p.light = float(value)
            else:
                p.pos = float(value)
            if getattr(self, '_schematic', None) is not None:
                self._schematic.refresh()
            self.update_list()
            self.update_detail()
            self.title_changed.emit()

    def set_res_display(self, mode):
        self.res_display = mode
        QSettings('BreadLab', 'BreadLab').setValue('resistor_display', mode)
        self.scene.update()

    def center_on_part(self, pid):
        """보드 화면을 이 부품 쪽으로 옮깁니다(크기는 그대로)."""
        p = next((q for q in self.parts if q.id == pid), None)
        if p is None:
            return
        if p.kind in IC_KINDS:
            c = ic_rect(p.a).center()
        else:
            pts = [pos(h) for h in p.pins() if h]
            c = QPointF(sum(q.x() for q in pts) / len(pts), sum(q.y() for q in pts) / len(pts))
        self.view.auto_fit = False
        self.view.centerOn(c)
        self.scene.update()

    def fit(self):
        self.view.auto_fit = True
        self.view.fitInView(VIEW_RECT, Qt.AspectRatioMode.KeepAspectRatio)

    # ------------------------------------------------------------ 시뮬레이션
    def instrument_changed(self):
        self.title_changed.emit()
        if getattr(self, '_schematic', None) is not None:
            self._schematic.refresh()

    def set_paused(self, on):
        self.paused = on
        self.update_clock()

    def reset_sim(self, quiet=False):
        self.sim.reset()
        self.step_cost = 2e-4
        self.coarse, self._slow = 1, 0
        self._hist, self._trial, self._cap_hint, self._cap_age = [], None, 16, 0
        self.sim.rough = False
        self.scope.clear()
        self.result = empty_result()
        if not quiet:
            self.status_message.emit('시간을 0으로 돌리고 커패시터를 모두 방전했습니다.', 3000)

    def all_outputs_off(self):
        self.psu.all_off()
        self.fg.out.setChecked(False)

    def sim_step(self):
        h = min(self.scope.sample_step(), 5e-3)
        fg = self.inst['fg']
        if fg['on'] and fg['wave'] != 'dc' and self.inst['leads']['g:+']:
            h = min(h, 1 / (fg['freq'] * 60))
        return max(h, 1e-6)

    def tick(self):
        now = time.perf_counter()
        real_dt = min(now - self.last_tick, 0.1)
        self.last_tick = now
        if self.paused or not self.isVisible():
            return
        base = self.sim_step()
        h = base * self.coarse
        want = max(1, round(real_dt / h))
        n = max(1, min(want, int(0.012 / max(self.step_cost, 1e-6))))
        t0 = time.perf_counter()
        result, samples = self.sim.step(self.parts, self.inst, h, n)
        spent = time.perf_counter() - t0
        self.step_cost = 0.8 * self.step_cost + 0.2 * spent / n
        self.ratio = n * h / real_dt if real_dt > 0 else 1.0
        self.adapt_precision(base, spent)
        self.result = result
        if not result['ok']:
            self.a_pause.setChecked(True)
            self.status_message.emit('계산이 수렴하지 않아 시뮬레이션을 멈췄습니다. 회로를 고친 뒤 일시정지를 해제하십시오.', 0)
        self.scope.add_samples(samples)
        self.psu.show_result(result)
        self.fg.show_result(result)
        self.update_alerts()
        self.update_detail()
        self.update_clock(h)
        self.scene.update()

    def adapt_precision(self, base, spent):
        """실시간을 따라가지 못하면 시간 간격을 2배씩(최대 16배) 늘려 빠르게, 여유가 생기면 되돌립니다.
        함수 발생기를 쓰는 동안에는 한 주기에 8점 이상은 남깁니다."""
        if not self.fast_auto:
            self.coarse = 1
        else:
            cap = 16
            fg = self.inst['fg']
            if fg['on'] and fg['wave'] != 'dc' and self.inst['leads']['g:+']:
                cap = max(1, int((1 / (fg['freq'] * 8)) / base))
            cap = max(1, min(cap, int(0.02 / base) or 1))
            cap = min(cap, self._cap_hint)
            self._hist.append(self.ratio)
            if len(self._hist) > 10:
                self._hist.pop(0)
            avg = sum(self._hist) / len(self._hist)
            if self._trial and len(self._hist) >= 8:     # 거칠게 바꾼 뒤 빨라지지 않았으면 되돌리고 한동안 그 한도로
                before, level = self._trial
                if avg < before * 1.2:
                    self.coarse = level
                    self._cap_hint = level
                    self._cap_age = 300
                self._trial = None
            if self._cap_age:
                self._cap_age -= 1
                if not self._cap_age:
                    self._cap_hint = 16
            if self.ratio < 0.7 and self.coarse < cap:
                self._slow += 1
                if self._slow >= 5 and not self._trial:  # 잠깐 느린 것은 넘기고, 계속 느리면
                    self._trial = (avg, self.coarse)
                    self.coarse = min(self.coarse * 2, cap)
                    self._slow = 0
                    self._hist.clear()
            else:
                self._slow = 0
                if self.coarse > 1 and self.ratio > 0.98 and spent < 0.004 and not self._trial:
                    self.coarse //= 2                       # 두 배로 정밀해져도 여유가 있으면 되돌림
            self.coarse = max(1, min(self.coarse, cap))
        self.sim.rough = self.coarse > 1

    def set_fast_auto(self, on):
        self.fast_auto = bool(on)
        QSettings('BreadLab', 'BreadLab').setValue('fast_auto', 'true' if on else 'false')
        if not on:
            self.coarse = 1
            self.sim.rough = False

    def update_clock(self, h=None):
        text = f't = {self.sim.t:.2f} s'
        if self.paused:
            text += '   일시정지 (F5)'
        else:
            if self.coarse > 1:
                text += f'   빠른 계산 ×{self.coarse} (정밀도 낮춤)'
            if self.ratio < 0.95:
                text += f'   실제 시간의 {self.ratio * 100:.0f}% 속도'
        self.clock.setText(text)

    def update_alerts(self):
        w = self.result['warnings']
        text = theme.alerts_html(w) if w else ''
        if self.alerts.text() != text:
            self.alerts.setText(text)
        self.alerts_section.setVisible(bool(text))
        self.alerts.setVisible(bool(text))
        self.check_danger(w)

    def set_danger_popup(self, on):
        self.danger_popup = bool(on)
        QSettings('BreadLab', 'BreadLab').setValue('danger_popup', 'true' if on else 'false')

    @staticmethod
    def _danger_key(text):
        return re.sub(r'[-+]?\d[\d.,]*\s*[a-zA-Zµ]*', '#', text)

    def check_danger(self, warnings):
        """단락·부품 손상 경고가 새로 생기면 경고창으로 알립니다(같은 문제는 사라졌다 다시 생길 때만 다시)."""
        danger = [x for x in warnings if any(k in x for k in DANGER_WORDS)]
        keys = {self._danger_key(x) for x in danger}
        new = keys - self._warned
        self._warned = keys
        if not new or not getattr(self, 'danger_popup', True) or not self.isVisible():
            return
        box = getattr(self, '_danger_box', None)
        if box is None:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle('위험 경고')
            box.setWindowModality(Qt.WindowModality.NonModal)
            off = box.addButton('모든 출력 끄기', QMessageBox.ButtonRole.AcceptRole)
            box.addButton('계속', QMessageBox.ButtonRole.RejectRole)
            box.buttonClicked.connect(lambda b: self.all_outputs_off() if b is off else None)
            self._danger_box = box
        shorted = any('단락' in x for x in danger)
        box.setText('단락(쇼트)이 생겼습니다.' if shorted else '부품이 망가질 수 있는 상태입니다.')
        box.setInformativeText('\n'.join('· ' + x for x in danger[:6])
                               + '\n\n실제 회로라면 부품이 뜨거워지거나 망가집니다. 출력을 끄고 연결을 확인하십시오.')
        box.show()
        box.raise_()

    # ------------------------------------------------------------ 파일
    def maybe_close(self):
        if not self.is_modified():
            return True
        box = QMessageBox(self)
        box.setWindowTitle('저장 확인')
        box.setText(f'"{self.document_title().rstrip(" *")}"의 변경 내용을 저장할까요?')
        save = box.addButton('저장', QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton('저장 안 함', QMessageBox.ButtonRole.DestructiveRole)
        box.addButton('취소', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is save:
            return self.save()
        return box.clickedButton() is discard

    def save(self):
        return self._write(self.path) if self.path else self.save_as()

    def save_as(self):
        start = str(self.path) if self.path else '회로.bd'
        path, _ = QFileDialog.getSaveFileName(self, '다른 이름으로 저장', start, FILE_FILTER)
        if not path:
            return False
        p = Path(path)
        if not p.suffix:
            p = p.with_suffix('.bd')
        return self._write(p)

    def _write(self, path):
        try:
            Path(path).write_text(json.dumps(self.document(outputs=False), ensure_ascii=False, indent=1),
                                  encoding='utf-8')
        except OSError as e:
            QMessageBox.warning(self, '저장 실패', str(e))
            return False
        self.path = Path(path)
        self.mark_saved()
        self.status_message.emit(f'{self.path.name}에 저장했습니다.', 3000)
        return True

    def open_file(self):
        if not self.maybe_close():
            return
        path, _ = QFileDialog.getOpenFileName(self, '회로 열기', str(self.path.parent) if self.path else '',
                                              FILE_FILTER)
        if path:
            self.open_path(path)

    def open_path(self, path):
        try:
            p = Path(path)
            if p.stat().st_size > 2_000_000:
                raise ValueError('파일이 2 MB보다 큽니다.')
            parts, inst = validate_document(json.loads(p.read_text(encoding='utf-8')))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, '열기 실패', f'{path}\n\n{e}')
            return False
        self._load(parts, inst)
        self.path = p
        self.mark_saved()
        return True

    def _load(self, parts, inst):
        for ch in ('ch1', 'ch2'):
            inst['psu'][ch]['on'] = False   # 파일을 열 때는 안전하게 출력을 끈 상태로
        inst['fg']['on'] = False
        self.parts = parts
        self.inst.clear()
        self.inst.update(inst)
        self.psu.load(self.inst)
        self.fg.load(self.inst)
        self.history.clear()
        self.future.clear()
        self.selected = self.pending = None
        self.npn_pins = []
        self.reset_sim(quiet=True)
        self.refresh()

    def new_file(self):
        if not self.maybe_close():
            return
        self._load([], default_instruments())
        self.path = None
        self.mark_saved()

    def clear_all(self):
        if QMessageBox.question(self, '모두 지우기', '모든 부품과 리드·프로브를 지울까요? 실행 취소로 되돌릴 수 있습니다.') \
                != QMessageBox.StandardButton.Yes:
            return
        self.snapshot()
        self.parts = []
        self.inst['scope'].update(ch1=None, ch2=None)
        for k in self.inst['leads']:
            self.inst['leads'][k] = None
        self.selected = None
        self.refresh()

    def import_schematic(self, path=None):
        """회로도 파일(Falstad CircuitJS .txt)을 읽어 보드에 자동으로 꾸밉니다."""
        if path is None:
            if not self.maybe_close():
                return False
            path, _ = QFileDialog.getOpenFileName(self, '회로도 파일 가져오기', str(Path.home()),
                                                  'Falstad 회로도 (*.txt *.circuitjs);;모든 파일 (*)')
            if not path:
                return False
        from circuit_import import import_falstad
        try:
            p = Path(path)
            if p.stat().st_size > 2_000_000:
                raise ValueError('파일이 2 MB보다 큽니다.')
            parts, inst, notes = import_falstad(p.read_text(encoding='utf-8', errors='replace'))
            doc = make_document(parts, inst)
            parts, inst = validate_document(copy.deepcopy(doc))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, '가져오기 실패', f'{path}' + chr(10) * 2 + str(e))
            return False
        self._load(parts, inst)
        self.path = None
        self.saved_state = None
        self.title_changed.emit()
        self._example_scope(doc)
        n = sum(1 for q in parts if q.kind != 'wire')
        msg = f'{p.name}: 부품 {n}개를 보드에 꽂았습니다. 장비 출력을 켜면 동작합니다.'
        self.guide.setText(msg)
        self.status_message.emit(msg, 6000)
        self.import_notes = notes
        if notes:
            QMessageBox.information(self, '가져오기', msg + chr(10) * 2 + chr(10).join('· ' + x for x in notes))
        QTimer.singleShot(0, self.fit)
        return True

    def load_example(self, i):
        title, note, doc = EXAMPLES[i]
        if self.parts and not self.maybe_close():
            return
        parts, inst = validate_document(copy.deepcopy(doc))
        self._load(parts, inst)
        self.path = None
        self.saved_state = None
        self.title_changed.emit()
        self.guide.setText(note)
        self._example_scope(doc)
        QTimer.singleShot(0, self.fit)

    def _example_scope(self, doc):
        fg = doc['instruments']['fg']
        uses_fg = bool(doc['instruments']['leads'].get('g:+'))
        if uses_fg:
            period = 1 / fg['freq']
            from instruments import TDIV
            tdiv = next((x for x in TDIV if 10 * x >= 3 * period), TDIV[-1])
            peak = abs(fg['offset']) + fg['vpp'] / 2
        else:
            tdiv, peak = (0.5 if any(p['kind'] == 'capacitor' for p in doc['parts']) else 0.01), \
                doc['instruments']['psu']['ch1']['voltage']
        from instruments import VDIV
        vdiv = next((x for x in VDIV if peak / x <= 3.5), VDIV[-1])
        s = self.scope
        s.tdiv.setCurrentIndex(s.tdiv.findData(tdiv))
        for ch, posv in (('ch1', 0.0), ('ch2', -2.0 if not uses_fg else 0.0)):
            s.ch_w[ch]['vdiv'].setCurrentIndex(s.ch_w[ch]['vdiv'].findData(vdiv))
            s.ch_w[ch]['pos'].setValue(posv)
        s.t_level.setValue(round(fg['offset'], 2) if uses_fg else round(peak / 2, 2))

    # ------------------------------------------------------------ 이미지·CSV
    def board_image(self):
        src = VIEW_RECT
        img = QImage(int(src.width() * 2), int(src.height() * 2), QImage.Format.Format_ARGB32)
        img.fill(QColor(theme.CANVAS))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.scene.render(p, QRectF(img.rect()), src)
        p.end()
        return img

    def save_board_image(self):
        path, _ = QFileDialog.getSaveFileName(self, '보드 이미지 저장', '보드.png', 'PNG 이미지 (*.png)')
        if path and not self.board_image().save(path, 'PNG'):
            QMessageBox.warning(self, '저장 실패', '이미지를 저장하지 못했습니다.')

    def copy_board_image(self):
        QApplication.clipboard().setImage(self.board_image())
        self.status_message.emit('보드 이미지를 클립보드에 복사했습니다.', 3000)

    def save_scope_image(self):
        path, _ = QFileDialog.getSaveFileName(self, '스코프 화면 저장', '스코프.png', 'PNG 이미지 (*.png)')
        if path and not self.scope.screen.grab().save(path, 'PNG'):
            QMessageBox.warning(self, '저장 실패', '이미지를 저장하지 못했습니다.')

    def save_scope_csv(self):
        rows = self.scope.csv_rows()
        if not rows:
            QMessageBox.information(self, '스코프 파형', '저장할 파형이 없습니다. 프로브를 물리고 시뮬레이션을 실행하십시오.')
            return
        path, _ = QFileDialog.getSaveFileName(self, '스코프 파형 저장', '파형.csv', 'CSV (*.csv)')
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(['시간 (s)', 'CH1 (V)', 'CH2 (V)'])
                w.writerows(rows)
        except OSError as e:
            QMessageBox.warning(self, '저장 실패', str(e))

    # ------------------------------------------------------------ 장비 창
    def open_instrument(self, kind):
        w = self.windows[kind]
        if not w.placed:
            if kind != 'scope':
                w.adjustSize()
            top = self.window().frameGeometry()
            dx, dy = {'psu': (60, 110), 'fg': (420, 110), 'scope': (60, 440)}[kind]
            w.move(top.left() + dx, top.top() + dy)
            w.placed = True
        w.show()
        w.raise_()
        w.activateWindow()

    # ------------------------------------------------------------ 탭 전환
    def activated(self):
        self.last_tick = time.perf_counter()
        self.timer.start(TICK_MS)
        if not getattr(self, '_tour_checked', False):
            self._tour_checked = True
            QTimer.singleShot(600, self.maybe_first_tour)
        for w in self._reopen:
            w.show()
        self._reopen = []

    def deactivated(self):
        self.timer.stop()
        extra = [self._schematic] if getattr(self, '_schematic', None) is not None else []
        self._reopen = [w for w in list(self.windows.values()) + extra if w.isVisible()]
        for w in self._reopen:
            w.hide()


LED_VF_TEXT = {RED: '1.9 V', YELLOW: '2.0 V', GREEN: '2.2 V', BLUE: '2.9 V', WHITE: '3.0 V'}
