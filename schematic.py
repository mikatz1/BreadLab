"""브레드보드 회로를 교과서식 회로도로 자동 배치해 그립니다.

1. 연결 정리: 점퍼선·보드 내부 연결·장비 리드를 합쳐 '부품 ↔ 마디(노드)' 목록을 만듭니다.
2. 전원 하나 + 2단자 부품으로 된 회로는 직렬·병렬 분해(series-parallel reduction)에 성공하면
   전원을 왼쪽 세로에 두고 부품을 위·아래 줄로 나눈 사각 루프로 그립니다. 병렬은 사다리처럼 쌓습니다.
3. 분해되지 않는 회로(트랜지스터, 브리지, 여러 전원 등)는 전위가 높은 마디를 위, 접지를 아래에 두는
   사다리형으로 그립니다.
그리기는 먼저 도형 목록(Drawing)으로 기록한 뒤, 화면·PNG·SVG·PDF 어디에나 같은 결과로 칠합니다.
"""
from dataclasses import dataclass
import math

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QImage, QPageLayout, QPageSize, QPainter, QPainterPath,
                           QPdfWriter, QPen, QPolygonF)

import theme
from circuit_core import COLOR_NAMES, FG_WAVES, IC_KINDS, designators, format_si, net_map

INK = '#111111'
LINE_W = 2.4
LEAF_W = 120          # 부품 하나가 차지하는 가로 길이(기호 60 + 양쪽 리드)
HALF = 30             # 기호 몸체 반 길이
GAP = 26              # 병렬 가지 사이 세로 간격
BUS = 26              # 병렬 버스와 가지 사이 가로 여백
COL = 130             # 사다리형 열 간격
ROW = 140             # 사다리형 행 간격
LABEL_PX = 15
TITLE_PX = 30


def _font(px, bold=False):
    f = QFont()
    f.setFamilies(theme.FONT_FAMILIES)
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def text_width(text, px=LABEL_PX, bold=False):
    return QFontMetricsF(_font(px, bold)).horizontalAdvance(text)


# ---------------------------------------------------------------- 도형 기록
class Drawing:
    """선·다각형·원·글자를 기록하고 크기를 계산합니다. render()로 아무 QPainter에나 칠합니다."""

    def __init__(self):
        self.ops = []
        self.box = None
        self.cur = None           # 지금 그리는 부품의 ID(클릭해서 고를 수 있게 영역을 모읍니다)
        self.tags = {}
        self.labels = []          # 부품 이름표 영역(선이 지나가지 않게)
        self.net = None           # 지금 그리는 선이 속한 마디(회로도 선을 눌러 마디를 보게)
        self.op_nets = []         # ops와 같은 순서로, 각 도형의 마디(없으면 None)

    def _grow(self, r):
        self.box = r if self.box is None else self.box.united(r)
        if self.cur is not None and self.net is None:      # 부품 영역은 기호·이름표만(다리 선은 마디 몫)
            t = self.tags.get(self.cur)
            self.tags[self.cur] = r if t is None else t.united(r)

    def line(self, x1, y1, x2, y2, w=LINE_W):
        self.ops.append(('line', (x1, y1, x2, y2, w), self.cur))
        self.op_nets.append(self.net)
        self._grow(QRectF(QPointF(min(x1, x2), min(y1, y2)), QPointF(max(x1, x2), max(y1, y2))).adjusted(-2, -2, 2, 2))

    def path(self, pts, w=LINE_W, closed=False, fill=False):
        self.ops.append(('path', (list(pts), w, closed, fill), self.cur))
        self.op_nets.append(None)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        self._grow(QRectF(min(xs) - 2, min(ys) - 2, max(xs) - min(xs) + 4, max(ys) - min(ys) + 4))

    def circle(self, x, y, r, w=LINE_W, fill=None):
        self.ops.append(('circle', (x, y, r, w, fill), self.cur))
        self.op_nets.append(self.net)
        self._grow(QRectF(x - r - 2, y - r - 2, 2 * r + 4, 2 * r + 4))

    def text(self, x, y, s, px=LABEL_PX, align='center', bold=False):
        """(x, y)는 글자 줄의 기준점. align: left·center·right."""
        w = text_width(s, px, bold)
        h = px * 1.4
        left = x - w / 2 if align == 'center' else x - w if align == 'right' else x
        self.ops.append(('text', (left, y - h / 2, w + 2, h, s, px, bold), self.cur))
        self.op_nets.append(None)
        if self.cur is not None and px == LABEL_PX:
            self.labels.append(QRectF(left, y - h / 2, w + 2, h))
        self._grow(QRectF(left, y - h / 2, w + 2, h))

    def rect(self):
        return self.box or QRectF(0, 0, 10, 10)

    def hit(self, x, y, pad=6):
        """(x, y)에 있는 부품 ID. 겹치면 가장 작은 영역."""
        best = None
        for tag, r in self.tags.items():
            if r.adjusted(-pad, -pad, pad, pad).contains(QPointF(x, y)):
                area = r.width() * r.height()
                if best is None or area < best[0]:
                    best = (area, tag)
        return best[1] if best else None

    def net_at(self, x, y, tol=6.0):
        """(x, y) 가까이 지나는 선의 마디."""
        best = None
        for (kind, a, _tag), net in zip(self.ops, self.op_nets):
            if net is None:
                continue
            if kind == 'line':
                x1, y1, x2, y2, w = a
                vx, vy = x2 - x1, y2 - y1
                L = vx * vx + vy * vy
                t = 0.0 if L == 0 else max(0.0, min(1.0, ((x - x1) * vx + (y - y1) * vy) / L))
                dist = math.hypot(x - (x1 + t * vx), y - (y1 + t * vy))
            elif kind == 'circle':
                dist = max(0.0, math.hypot(x - a[0], y - a[1]) - a[2])
            else:
                continue
            if dist <= tol and (best is None or dist < best[0]):
                best = (dist, net)
        return best[1] if best else None

    def net_anchor(self, net):
        """마디 전압을 적을 자리: 그 마디의 가장 긴 가로선 가운데(없으면 가장 긴 선)."""
        best = None
        for (kind, a, _tag), n in zip(self.ops, self.op_nets):
            if n != net or kind != 'line':
                continue
            x1, y1, x2, y2, _w = a
            horiz = abs(y1 - y2) < 0.5
            length = abs(x1 - x2) + abs(y1 - y2)
            key = (horiz, length)
            if best is None or key > best[0]:
                best = (key, QPointF((x1 + x2) / 2, (y1 + y2) / 2), horiz)
        return (best[1], best[2]) if best else (None, False)

    def nets(self):
        return {n for n in self.op_nets if n is not None}

    def render(self, p, dx=0.0, dy=0.0, marks=None):
        """marks: {부품 ID 또는 ('net', 마디): 색}. 해당 부품·마디의 선·글자를 그 색으로 칠합니다."""
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        base = QColor(INK)
        marks = marks or {}
        for (kind, a, tag), net in zip(self.ops, self.op_nets):
            if tag in marks:
                ink = QColor(marks[tag])
            elif net is not None and ('net', net) in marks:
                ink = QColor(marks[('net', net)])
            else:
                ink = base
            if kind == 'line':
                x1, y1, x2, y2, w = a
                if net is not None and ('net', net) in marks and tag not in marks:
                    w = w + 1.6                                  # 고른 마디는 조금 굵게
                p.setPen(QPen(ink, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
                p.drawLine(QPointF(x1 + dx, y1 + dy), QPointF(x2 + dx, y2 + dy))
            elif kind == 'path':
                pts, w, closed, fill = a
                path = QPainterPath(QPointF(pts[0][0] + dx, pts[0][1] + dy))
                for x, y in pts[1:]:
                    path.lineTo(x + dx, y + dy)
                if closed:
                    path.closeSubpath()
                p.setPen(QPen(ink, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin))
                p.setBrush(ink if fill else Qt.BrushStyle.NoBrush)
                p.drawPath(path)
            elif kind == 'circle':
                x, y, r, w, fill = a
                p.setPen(QPen(ink, w))
                if fill == INK and ink != base:
                    fill = ink.name()
                p.setBrush(QColor(fill) if fill else Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(x + dx, y + dy), r, r)
            else:
                x, y, w, h, s, px, bold = a
                p.setFont(_font(px, bold))
                p.setPen(ink)
                p.drawText(QRectF(x + dx, y + dy, w, h), Qt.AlignmentFlag.AlignCenter, s)


# ---------------------------------------------------------------- 연결 정리
@dataclass
class Elem:
    kind: str            # 부품 종류, 전원은 dc·fg
    label: str
    nets: tuple          # 2단자: (a, b) / 3단자: (a, b, c) / 전원: (+, −) / IC: 아래 IC_PINS 순서
    closed: bool = True
    pid: object = None   # 보드 부품 ID(전원 장비는 'ch1'·'ch2'·'fg')


# IC를 회로도에 그릴 때 쓰는 핀(보드 핀 번호 - 1)
IC_PINS = {'opamp': (1, 2, 5, 6, 3),               # IN−, IN+, OUT, V+, V−
           'timer555': (7, 0, 1, 5, 6, 2, 4, 3)}    # VCC, GND, TRIG, THR, DIS, OUT, CTRL, RESET


def extract(parts, inst):
    """(부품 목록, 전원 목록, 접지 마디)를 돌려줍니다."""
    leads = inst.get('leads', {})
    nm = net_map(parts, leads)
    tags = designators(parts)
    elems = []
    sources = []
    for p in parts:
        if p.kind == 'wire':
            continue
        nets = tuple(nm[h] for h in p.pins())
        if p.kind in IC_KINDS:
            nets = tuple(nets[i] for i in IC_PINS[p.kind])
        if len(set(nets)) < 2:
            continue                    # 두 다리가 같은 마디에 꽂힘(단락된 부품)
        tag = tags[p.id]
        if p.kind in ('resistor', 'ldr', 'pot'):
            label = f'{tag} = {format_si(p.resistance() if p.kind != "pot" else p.value)}'
        elif p.kind == 'capacitor':
            label = f'{tag} = {format_si(p.value, "F")}'
        elif p.kind == 'inductor':
            label = f'{tag} = {format_si(p.value, "H")}'
        elif p.kind == 'zener':
            label = f'{tag} ({p.value:g} V)'
        elif p.kind == 'led':
            label = f'{tag} ({COLOR_NAMES.get(p.color, "")})'
        elif p.kind in ('npn', 'pnp'):
            label = f'{tag} (β {p.value:g})'
        elif p.kind == 'opamp':
            label = f'{tag} (741)'
        elif p.kind == 'timer555':
            label = f'{tag} (555)'
        else:
            label = tag
        if p.kind == 'battery':
            sources.append(Elem('dc', f'{tag}  {p.value:g} V', nets, pid=p.id))
            continue
        elems.append(Elem(p.kind, label, nets, p.closed, pid=p.id))
    ground_linked = bool(leads.get('p:1-') or leads.get('g:-'))
    for n in ('1', '2'):
        neg_ok = leads.get(f'p:{n}-') or (n == '1' and ground_linked)
        if leads.get(f'p:{n}+') and neg_ok:
            v = inst['psu'][f'ch{n}']['voltage']
            sources.insert(int(n) - 1, Elem('dc', f'전원 CH{n}  {v:g} V', (nm[f'p:{n}+'], nm[f'p:{n}-']),
                                             pid=f'ch{n}'))
    if leads.get('g:+') and ground_linked:
        fg = inst['fg']
        if fg['wave'] == 'dc':
            desc = f'{fg["offset"]:+g} V'
        else:
            desc = f'{FG_WAVES[fg["wave"]]} {format_si(fg["freq"], "Hz", 3)} {fg["vpp"]:g} Vpp'
        sources.append(Elem('fg', f'함수 발생기  {desc}', (nm['g:+'], nm['g:-']), pid='fg'))
    ground = nm['p:1-'] if ground_linked else None
    return elems, sources, ground


# ---------------------------------------------------------------- 직렬·병렬 분해
def _rev(x):
    if x[0] == 'leaf':
        return ('leaf', x[1], not x[2])
    if x[0] == 'ser':
        return ('ser', [_rev(c) for c in reversed(x[1])])
    return ('par', [_rev(c) for c in x[1]])


def _ser(items):
    out = []
    for c in items:
        out.extend(c[1] if c[0] == 'ser' else [c])
    return ('ser', out)


def _par(items):
    out = []
    for c in items:
        out.extend(c[1] if c[0] == 'par' else [c])
    return ('par', out)


def sp_reduce(elems, src):
    """전원 +에서 −까지를 직렬·병렬 식으로 줄입니다. 실패하면 None.

    식: ('leaf', Elem, 뒤집힘) | ('ser', [...]) | ('par', [...]). 왼쪽→오른쪽이 + → − 방향입니다.
    """
    if any(len(e.nets) != 2 for e in elems):
        return None
    plus, minus = src.nets
    edges = [[e.nets[0], e.nets[1], ('leaf', e, False)] for e in elems]

    def orient(ed, frm):
        return ed[2] if ed[0] == frm else _rev(ed[2])

    changed = True
    while changed:
        changed = False
        edges = [ed for ed in edges if ed[0] != ed[1]]          # 고리(같은 마디로 돌아옴) 제거
        groups = {}
        for ed in edges:
            groups.setdefault(frozenset((ed[0], ed[1])), []).append(ed)
        for key, grp in groups.items():
            if len(grp) > 1:
                u, v = grp[0][0], grp[0][1]
                merged = [u, v, _par([orient(ed, u) for ed in grp])]
                edges = [ed for ed in edges if ed not in grp] + [merged]
                changed = True
                break
        if changed:
            continue
        deg = {}
        for ed in edges:
            for n in ed[:2]:
                deg[n] = deg.get(n, 0) + 1
        for n, d in deg.items():
            if n in (plus, minus):
                continue
            if d == 1:                                          # 한쪽만 이어진(매달린) 부품
                edges = [ed for ed in edges if n not in ed[:2]]
                changed = True
                break
            if d == 2:
                e1, e2 = [ed for ed in edges if n in ed[:2]]
                x = e1[0] if e1[1] == n else e1[1]
                y = e2[0] if e2[1] == n else e2[1]
                merged = [x, y, _ser([_rev(orient(e1, n)), orient(e2, n)])]
                edges = [ed for ed in edges if ed is not e1 and ed is not e2] + [merged]
                changed = True
                break
    if len(edges) == 1 and {edges[0][0], edges[0][1]} == {plus, minus}:
        return orient(edges[0], plus)
    return None


def classify_ladder(elems):
    kinds = {e.kind for e in elems}
    if 'opamp' in kinds:
        return '연산 증폭기 회로'
    if 'timer555' in kinds:
        return '555 타이머 회로'
    if kinds & {'npn', 'pnp', 'nmos'}:
        return '트랜지스터 회로'
    return '회로도'


def classify(expr):
    if expr[0] == 'leaf':
        return '기본 회로'
    if expr[0] == 'ser' and all(c[0] == 'leaf' for c in expr[1]):
        return '직렬 회로'
    if expr[0] == 'par' and all(c[0] == 'leaf' for c in expr[1]):
        return '병렬 회로'
    return '직병렬 회로'


# ---------------------------------------------------------------- 기호(가로, 몸체 중심 (cx, y))
def sym_h(d, e, cx, y, rev):
    """가로 기호. rev면 기호 방향(다이오드 등)을 오른쪽→왼쪽으로."""
    s = -1 if rev else 1
    k = e.kind
    if k in ('resistor', 'ldr'):
        n = 6
        span = 48 if k == 'ldr' else 2 * HALF
        x0 = cx - span / 2
        pts = [(cx - HALF, y), (x0, y)]
        for i in range(n):
            pts.append((x0 + span * (i + 0.5) / n, y + (-11 if i % 2 == 0 else 11)))
        pts += [(x0 + span, y), (cx + HALF, y)]
        d.path(pts)
        if k == 'ldr':
            d.circle(cx, y, 30, w=1.8)
            for ox in (-14, 2):          # 들어오는 빛 화살표
                d.line(cx + ox - 20, y - 46, cx + ox - 6, y - 32, w=1.8)
                d.path([(cx + ox - 6, y - 32), (cx + ox - 15, y - 34), (cx + ox - 8, y - 41)], w=1.8, closed=True, fill=True)
    elif k == 'capacitor':
        d.line(cx - HALF, y, cx - 6, y)
        d.line(cx + 6, y, cx + HALF, y)
        d.line(cx - 6, y - 18, cx - 6, y + 18, w=3)
        d.line(cx + 6, y - 18, cx + 6, y + 18, w=3)
    elif k in ('diode', 'led'):
        d.line(cx - HALF, y, cx + HALF, y)
        d.path([(cx - 13 * s, y - 15), (cx - 13 * s, y + 15), (cx + 13 * s, y)], closed=True, fill=True)
        d.line(cx + 13 * s, y - 15, cx + 13 * s, y + 15, w=3)
        if k == 'led':                   # 나가는 빛 화살표
            for ox in (-2, 10):
                x1, y1 = cx + ox, y - 20
                x2, y2 = x1 + 14, y1 - 14
                d.line(x1, y1, x2, y2, w=1.8)
                d.path([(x2, y2), (x2 - 9, y2 + 2), (x2 - 2, y2 + 9)], w=1.8, closed=True, fill=True)
    elif k == 'inductor':                # 코일: 반원 네 개
        d.line(cx - HALF, y, cx - 24, y)
        d.line(cx + 24, y, cx + HALF, y)
        for i in range(4):
            x0 = cx - 24 + 12 * i
            d.path([(x0 + 6 - 6 * math.cos(math.pi * t / 8), y - 9 * math.sin(math.pi * t / 8)) for t in range(9)])
    elif k == 'zener':                   # 제너: 끝이 꺾인 막대
        d.line(cx - HALF, y, cx + HALF, y)
        d.path([(cx - 13 * s, y - 15), (cx - 13 * s, y + 15), (cx + 13 * s, y)], closed=True, fill=True)
        bx = cx + 13 * s
        d.path([(bx - 6 * s, y - 19), (bx, y - 15), (bx, y + 15), (bx + 6 * s, y + 19)], w=3)
    elif k == 'switch':
        d.line(cx - HALF, y, cx - 22, y)
        d.line(cx + 22, y, cx + HALF, y)
        d.circle(cx - 18, y, 4, w=2)
        d.circle(cx + 18, y, 4, w=2)
        if e.closed:
            d.line(cx - 15, y - 2, cx + 15, y - 2)
        else:
            d.line(cx - 15, y - 2, cx + 16, y - 20)
    else:
        d.line(cx - HALF, y, cx + HALF, y)


def sym_source_v(d, e, x, ytop, ybot, plus_top=True):
    """세로 전원 기호(전지 또는 함수 발생기). ytop~ybot 사이를 잇습니다."""
    mid = (ytop + ybot) / 2
    top_net, bot_net = (e.nets[0], e.nets[1]) if plus_top else (e.nets[1], e.nets[0])
    if e.kind == 'fg':
        d.net = top_net
        d.line(x, ytop, x, mid - 26)
        d.net = bot_net
        d.line(x, mid + 26, x, ybot)
        d.net = None
        d.circle(x, mid, 26)
        pts = [(x - 15 + 30 * i / 30, mid - 9 * math.sin(2 * math.pi * i / 30)) for i in range(31)]
        d.path(pts, w=2)
        d.text(x - 34, mid - 26 if plus_top else mid + 26, '+', px=18, align='center')
        return
    long_y, short_y = (mid - 6, mid + 6) if plus_top else (mid + 6, mid - 6)
    d.net = top_net
    d.line(x, ytop, x, min(long_y, short_y))
    d.net = bot_net
    d.line(x, max(long_y, short_y), x, ybot)
    d.net = None
    d.line(x - 26, long_y, x + 26, long_y, w=2.6)
    d.line(x - 14, short_y, x + 14, short_y, w=4)
    sign_y = long_y - 18 if plus_top else long_y + 18
    d.text(x + 34, sign_y, '+', px=20, align='center')
    d.text(x + 34, short_y + (18 if plus_top else -18), '−', px=20, align='center')


def source_label(d, x, y, label, align):
    """전원 이름표를 두 줄(이름 / 값)로 써서 회로도가 옆으로 길어지지 않게 합니다."""
    name, _, value = label.partition('  ')
    if value:
        d.text(x, y - 10, name, align=align)
        d.text(x, y + 10, value, align=align)
    else:
        d.text(x, y, label, align=align)


def label_width(label):
    name, _, value = label.partition('  ')
    return max(text_width(name), text_width(value)) if value else text_width(label)


# ---------------------------------------------------------------- 블록 배치(직렬·병렬)
class Block:
    def __init__(self, w, up, down, draw, ln=None, rn=None):
        self.w, self.up, self.down, self._draw = w, up, down, draw
        self.ln, self.rn = ln, rn            # 왼쪽·오른쪽 끝의 마디

    def draw(self, d, x, y):
        self._draw(d, x, y)


def leaf_block(e, rev):
    w = max(LEAF_W, text_width(e.label) + 24)

    ln, rn = (e.nets[1], e.nets[0]) if rev else (e.nets[0], e.nets[1])

    def draw(d, x, y):
        cx = x + w / 2
        d.net = ln
        d.line(x, y, cx - HALF, y)
        d.net = rn
        d.line(cx + HALF, y, x + w, y)
        d.net = None
        sym_h(d, e, cx, y, rev)
        d.text(cx, y + 42, e.label)
    up = 52 if e.kind in ('ldr', 'led') else 30

    def tagged(d, x, y):
        d.cur = e.pid
        draw(d, x, y)
        d.cur = None
    return Block(w, up, 56, tagged, ln, rn)


def layout(expr):
    if expr[0] == 'leaf':
        return leaf_block(expr[1], expr[2])
    kids = [layout(c) for c in expr[1]]
    if expr[0] == 'ser':
        w = sum(k.w for k in kids)

        def draw(d, x, y):
            for k in kids:
                k.draw(d, x, y)
                x += k.w
        return Block(w, max(k.up for k in kids), max(k.down for k in kids), draw, kids[0].ln, kids[-1].rn)
    inner = max(k.w for k in kids)
    ys = [0.0]
    for a, b in zip(kids, kids[1:]):
        ys.append(ys[-1] + a.down + GAP + b.up)
    w = inner + 2 * BUS

    ln, rn = kids[0].ln, kids[0].rn

    def draw(d, x, y):
        lx, rx = x + BUS, x + BUS + inner
        d.net = ln
        d.line(x, y, lx, y)
        d.line(lx, y, lx, y + ys[-1])
        d.net = rn
        d.line(rx, y, x + w, y)
        d.line(rx, y, rx, y + ys[-1])
        for i, (k, oy) in enumerate(zip(kids, ys)):
            kx = lx + (inner - k.w) / 2
            d.net = ln
            d.line(lx, y + oy, kx, y + oy)
            d.net = rn
            d.line(kx + k.w, y + oy, rx, y + oy)
            d.net = None
            k.draw(d, kx, y + oy)
            if i < len(kids) - 1:            # T자 연결점
                d.net = ln
                d.circle(lx, y + oy, 4, w=1, fill=INK)
                d.net = rn
                d.circle(rx, y + oy, 4, w=1, fill=INK)
                d.net = None
    return Block(w, kids[0].up, ys[-1] + kids[-1].down, draw, ln, rn)


def draw_loop(d, src, expr):
    """보내 주신 교과서 그림처럼: 전원을 왼쪽 세로에, 부품을 위·아래 줄로 나눈 사각 루프."""
    items = expr[1] if expr[0] == 'ser' else [expr]
    widths = [layout(c).w for c in items]
    best = (None, 1e18)
    for k in range(1, len(items) + 1):
        top, bot = sum(widths[:k]), sum(widths[k:])
        score = max(top, bot) + (0 if k < len(items) or len(items) == 1 else 1e6)
        if score < best[1] - 1e-6:
            best = (k, score)
    k = best[0] if len(items) > 1 else 1
    top_b = layout(_ser(items[:k]) if k > 1 else items[0])
    # 아래 줄은 오른쪽→왼쪽으로 흐르지만, 직렬 부품은 순서를 바꿔도 같은 회로이므로
    # 왼쪽부터 원래 순서(R1, R2 …)로 읽히게 두고 각 부품의 방향만 뒤집습니다.
    bot_b = layout(_ser([_rev(c) for c in items[k:]])) if k < len(items) else None
    inner = max(top_b.w, bot_b.w if bot_b else 0, 240)
    left, right = 0.0, inner + 120
    ty = 0.0
    by = ty + max(top_b.down + (bot_b.up if bot_b else 0) + 70, 190)
    # 위쪽 줄
    tx = left + 60 + (inner - top_b.w) / 2
    d.net = top_b.ln
    d.line(left, ty, tx, ty)
    d.net = None
    top_b.draw(d, tx, ty)
    d.net = top_b.rn
    d.line(tx + top_b.w, ty, right, ty)
    d.line(right, ty, right, by)
    # 아래쪽 줄
    if bot_b:
        bx = left + 60 + (inner - bot_b.w) / 2
        d.line(right, by, bx + bot_b.w, by)
        d.net = None
        bot_b.draw(d, bx, by)
        d.net = bot_b.ln
        d.line(bx, by, left, by)
    else:
        d.line(right, by, left, by)
    d.net = None
    # 전원(왼쪽 세로, +가 위)
    d.cur = src.pid
    sym_source_v(d, src, left, ty, by, plus_top=True)
    source_label(d, left - 46, (ty + by) / 2, src.label, 'right')
    d.cur = None


# ---------------------------------------------------------------- 사다리형(일반 회로)
def _vertical_symbol(d, it, x, mid, rev):
    """가로 기호를 90° 돌려 (x, mid)를 중심으로 세로로 그립니다. rev가 아니면 a가 위."""
    sub = Drawing()
    sym_h(sub, it, 0, 0, rev=rev)
    for kind, args, _t in sub.ops:
        if kind == 'line':
            x1, y1, x2, y2, w = args
            d.line(x - y1, mid + x1, x - y2, mid + x2, w)
        elif kind == 'path':
            pts, w, closed, fill = args
            d.path([(x - py, mid + px) for px, py in pts], w, closed, fill)
        elif kind == 'circle':
            cx, cy, r, w, fill = args
            d.circle(x - cy, mid + cx, r, w, fill)


def _bjt_vertical(d, x, yc, ye, mid, side_right, pnp=False):
    """세로 트랜지스터: 컬렉터 yc, 이미터 ye. 베이스 쪽(side_right)으로 막대. 베이스 단자 x를 돌려줍니다."""
    m = 1 if side_right else -1
    s = 1 if yc < ye else -1
    c_end, e_end = mid - 20 * s, mid + 20 * s
    bar = x + 14 * m
    d.line(x, yc, x, c_end)
    d.line(x, e_end, x, ye)
    d.circle(x + 4 * m, mid, 26, w=2)
    d.line(bar, mid - 15, bar, mid + 15, w=3)
    d.line(bar, mid - 6 * s, x, c_end)
    d.line(bar, mid + 6 * s, x, e_end)
    if pnp:                                     # 화살표가 막대 쪽(안쪽)을 향함
        tip = (bar, mid + 6 * s)
        vx, vy = bar - x, mid + 6 * s - e_end
    else:                                       # 화살표가 이미터 끝(바깥)을 향함
        tip = (x, e_end)
        vx, vy = x - bar, e_end - (mid + 6 * s)
    n = math.hypot(vx, vy)
    vx, vy = vx / n, vy / n
    bx, by = tip[0] - 10 * vx, tip[1] - 10 * vy
    d.path([tip, (bx - 5 * vy, by + 5 * vx), (bx + 5 * vy, by - 5 * vx)], w=1.4, closed=True, fill=True)
    return bar


def _mos_vertical(d, x, yd, ys, mid, side_right):
    """세로 N채널 MOSFET(증가형): 드레인 yd, 소스 ys. 게이트 단자 x를 돌려줍니다."""
    m = 1 if side_right else -1
    s = 1 if yd < ys else -1
    ch = x + 14 * m                              # 채널 선
    d.line(x, yd, x, mid - 16 * s)
    d.line(x, mid - 16 * s, ch, mid - 16 * s)
    d.line(x, ys, x, mid + 16 * s)
    d.line(x, mid + 16 * s, ch, mid + 16 * s)
    d.line(x, mid, x, mid + 16 * s)
    for a, b in ((-22, -9), (-5, 5), (9, 22)):
        d.line(ch, mid + a, ch, mid + b, w=3)
    d.line(x, mid, ch, mid)
    d.path([(ch - 1 * m, mid), (ch - 10 * m, mid - 5), (ch - 10 * m, mid + 5)], w=1.4, closed=True, fill=True)
    gate = ch + 8 * m
    d.line(gate, mid - 20, gate, mid + 20)
    return gate


def _pot_vertical(d, it, x, yt, yb, mid, rev, side_right):
    """세로 가변저항: 저항 기호 + 옆에서 가리키는 와이퍼 화살표. 와이퍼 단자 x를 돌려줍니다."""
    m = 1 if side_right else -1
    d.line(x, yt, x, mid - HALF)
    d.line(x, mid + HALF, x, yb)
    _vertical_symbol(d, Elem('resistor', '', ()), x, mid, rev)
    tip = x + 13 * m
    d.line(x + 26 * m, mid, tip + 2 * m, mid)
    d.path([(tip, mid), (tip + 9 * m, mid - 5), (tip + 9 * m, mid + 5)], w=1.4, closed=True, fill=True)
    return x + 26 * m


def _spdt_vertical(d, it, x, yt, yb, mid, com_top, side_right):
    """세로 전환 스위치: COM과 A가 한 줄, B는 옆. B 단자 x를 돌려줍니다."""
    m = 1 if side_right else -1
    yc, ya = (mid - 18, mid + 18) if com_top else (mid + 18, mid - 18)
    d.line(x, yt, x, mid - 22)
    d.line(x, mid + 22, x, yb)
    d.circle(x, yc, 4, w=2)
    d.circle(x, ya, 4, w=2)
    bx = x + 26 * m
    d.circle(bx, ya, 4, w=2)
    tx, ty = (x + 2 * m, ya) if it.closed else (bx - 3 * m, ya)
    d.line(x, yc, tx, ty + (-4 if ya > yc else 4))
    d.line(bx + 4 * m, ya, x + 40 * m, ya)
    return x + 40 * m, ya


def _opamp_body(d, x, yt, yb, mid):
    """세로로 V+(위)–V−(아래)가 지나는 연산 증폭기 삼각형. 입력·출력 단자 좌표를 돌려줍니다."""
    lx, rx, h = x - 32, x + 36, 36
    d.path([(lx, mid - h), (lx, mid + h), (rx, mid)], w=2.4, closed=True)
    edge = h * (rx - x) / (rx - lx)
    d.line(x, yt, x, mid - edge)
    d.line(x, mid + edge, x, yb)
    d.text(lx + 10, mid - 15, '−', px=18)
    d.text(lx + 10, mid + 15, '+', px=18)
    return {'in-': (lx, mid - 15, -1), 'in+': (lx, mid + 15, -1), 'out': (rx, mid, 1)}


def _timer_body(d, x, yt, yb, mid):
    """555 타이머 상자. VCC(위)–GND(아래)가 세로로 지나고, 나머지 핀은 양옆."""
    w, h = 44, 48
    d.path([(x - w, mid - h), (x + w, mid - h), (x + w, mid + h), (x - w, mid + h)], w=2.2, closed=True)
    d.line(x, yt, x, mid - h)
    d.line(x, mid + h, x, yb)
    d.text(x, mid, '555', px=16, bold=True)
    pins = {'dis': (x - w, mid - 28, -1), 'thr': (x - w, mid, -1), 'trig': (x - w, mid + 28, -1),
            'rst': (x + w, mid - 28, 1), 'out': (x + w, mid, 1), 'ctrl': (x + w, mid + 28, 1)}
    names = {'dis': 'DIS', 'thr': 'THR', 'trig': 'TRIG', 'rst': 'RST', 'out': 'OUT', 'ctrl': 'CV'}
    for k, (px, py, side) in pins.items():
        d.text(px - 5 * side, py, names[k], px=10, align='right' if side > 0 else 'left')
    d.text(x, mid - h + 10, 'VCC', px=10)
    d.text(x, mid + h - 10, 'GND', px=10)
    return pins


# 사다리형에서 부품을 세로로 세울 때: (위·아래로 잇는 두 핀 번호, 옆으로 나가는 핀 번호(한 개, 방향은 자동))
MAIN = {'npn': (0, 2, 1), 'pnp': (0, 2, 1), 'nmos': (0, 2, 1), 'pot': (0, 2, 1), 'spdt': (1, 0, 2),
        'opamp': (3, 4, None), 'timer555': (0, 1, None)}
# 블록 부품의 옆 핀: (Elem.nets 번호, 이름)
BLOCK_PINS = {'opamp': ((0, 'in-'), (1, 'in+'), (2, 'out')),
              'timer555': ((4, 'dis'), (3, 'thr'), (2, 'trig'), (7, 'rst'), (5, 'out'), (6, 'ctrl'))}
SIDE_W = {'npn': 40, 'pnp': 40, 'nmos': 40, 'pot': 30, 'spdt': 46, 'opamp': 70, 'timer555': 90}


def draw_ladder(d, elems, sources, ground, potential, perm=None):
    """교과서식 배치: + 레일 위, 접지 레일 아래. 직렬로 이어지는 부품은 한 세로줄에 쌓고,
    가지가 갈라지는 마디만 가로선으로 잇습니다. 3단자·IC는 전원 쪽 두 핀을 세로로 세우고
    나머지 핀을 옆으로 뽑습니다."""
    items = sources + elems
    nets = []
    for it in items:
        for n in it.nets:
            if n not in nets:
                nets.append(n)
    plus = [s.nets[0] for s in sources if s.nets[0] != ground]      # 음전원의 +(=접지)는 위쪽이 아님
    below = {s.nets[1] for s in sources if s.nets[0] == ground}
    dist, frontier = {}, list(plus)
    for n in frontier:
        dist[n] = 0
    while frontier:
        nxt = []
        for n in frontier:
            for it in items:
                if n in it.nets:
                    for m in it.nets:
                        if m not in dist:
                            dist[m] = dist[n] + 1
                            nxt.append(m)
        frontier = nxt

    def key(n):
        cls = 3 if n in below else 2 if n == ground else 0 if n in plus else 1
        p = -potential[n] if potential and n in potential else 0.0
        return (cls, p, dist.get(n, 99), str(n))
    order = sorted(nets, key=key)
    idx = {n: i for i, n in enumerate(order)}

    def down(a, b):                       # 위(전위 높음) → 아래 방향으로
        return (a, b) if idx[a] < idx[b] else (b, a)

    def main_pair(e):
        if e.kind in MAIN:
            i, j, _ = MAIN[e.kind]
            if e.kind in ('opamp', 'timer555'):
                return e.nets[i], e.nets[j]     # 전원 핀은 늘 위(+)·아래(−)
            return down(e.nets[i], e.nets[j])
        return down(e.nets[0], e.nets[1])

    def side_nets(e):
        if e.kind in BLOCK_PINS:
            return [e.nets[i] for i, _ in BLOCK_PINS[e.kind]]
        if e.kind in MAIN:
            return [e.nets[MAIN[e.kind][2]]]
        return []

    edges = [[e, *main_pair(e)] for e in elems]
    # 층: + 에서 최장 경로(부품 하나 = 한 칸), 접지는 맨 아래
    rank = {n: 0 for n in nets}
    for _ in range(len(nets) + 1):
        changed = False
        for _e, t, b in edges:
            if t != b and rank[b] < rank[t] + 1 and rank[t] + 1 <= len(nets):
                rank[b] = rank[t] + 1
                changed = True
        if not changed:
            break
    for s in sources:
        rank[s.nets[1]] = max(rank[s.nets[1]], rank[s.nets[0]] + 1)
    if ground in rank:
        neg = {s.nets[1] for s in sources if s.nets[0] == ground}     # 음전원(V−)은 접지보다 한 칸 아래
        rank[ground] = max(max(r for n, r in rank.items() if n not in neg), 1)
        for n in neg:
            rank[n] = rank[ground] + 1
    mains = {n for _e, t, b in edges for n in (t, b)} | {n for s in sources for n in s.nets}
    for e in elems:                        # 옆 핀 마디가 세로 변에 없으면 부품 가운데 높이로
        t, b = main_pair(e)
        for n in side_nets(e):
            if n not in mains:
                rank[n] = rank[t]
    src_nets = {n for s in sources for n in s.nets}
    for e in elems:                        # 위에서만 내려오는 베이스·게이트 마디는 핀 높이(부품 가운데)로 올려
        if e.kind not in MAIN or e.kind in BLOCK_PINS:   # 핀 선이 곧게 들어가게 합니다
            continue
        t, b = main_pair(e)
        sn = side_nets(e)[0]
        if sn == ground or sn in src_nets or sn in (t, b) or any(t2 == sn for _e, t2, _b in edges):
            continue
        if all(rank[t2] <= rank[t] for _e, t2, b2 in edges if b2 == sn):
            rank[sn] = rank[t] + 0.5
    row = {n: 70 + rank[n] * ROW for n in nets}

    # 세로 사슬 만들기
    placed = set()
    columns = []
    for n in order:
        for ed in edges:
            if id(ed) in placed or ed[1] != n:
                continue
            chain = [ed]
            placed.add(id(ed))
            cur = ed[2]
            while cur != ground:
                nxt = [c for c in edges if id(c) not in placed and c[1] == cur]
                if not nxt:
                    break
                chain.append(nxt[0])
                placed.add(id(nxt[0]))
                cur = nxt[0][2]
            columns.append(chain)
    for ed in edges:                        # 남은(고리 안쪽) 변도 빠짐없이
        if id(ed) not in placed:
            columns.append([ed])
            placed.add(id(ed))
    if perm is not None:
        columns = [columns[i] for i in perm]
    d.ncols = len(columns)
    d.segs = []                              # (x1, y1, x2, y2, 마디): 교차 세기용 배선
    attach = {n: [] for n in nets}         # (x, 위쪽 선 있음, 아래쪽 선 있음)
    x = 60.0
    xs_src = []
    for i, s in enumerate(sources):              # 위치만 먼저 정하고, 그리기는 높이 조정 뒤에
        xs_src.append(x)
        x += COL + (label_width(s.label) + 10 if i else 0)
    col_x = []
    for chain in columns:
        extra = max((SIDE_W.get(ed[0].kind, 0) for ed in chain), default=0)
        x += extra
        col_x.append(x)
        widest = max(text_width(ed[0].label) for ed in chain)
        x += COL + max(0, widest - 70) + extra

    label_w = {cx: max(text_width(ed[0].label) for ed in chain) for cx, chain in zip(col_x, columns)}
    net_cols = {}
    for cx, chain in zip(col_x, columns):
        for e, t, b in chain:
            net_cols.setdefault(t, []).append(cx)
            net_cols.setdefault(b, []).append(cx)
    for i, s in enumerate(sources):
        for n in s.nets:
            net_cols.setdefault(n, []).append(xs_src[i])

    def side_x(e, cx):
        """옆 핀(베이스·게이트·와이퍼 …)을 어느 쪽으로 뽑을지와 그 세로선 x."""
        net = side_nets(e)[0]
        others = [v for v in net_cols.get(net, []) if v != cx]
        if not others:
            return cx - 50, False
        right = sum(others) / len(others) > cx
        target = min(v for v in others if v > cx) if right and any(v > cx for v in others) else \
            max((v for v in others if v < cx), default=cx - 74)
        if right:
            return target - 24, True
        lw = label_w.get(target)                     # 왼쪽 열 이름표(오른쪽에 붙음)를 피해 그 뒤에서 내려옴
        if lw and target + 38 + lw + 14 < cx - 45:
            return target + 38 + lw + 14, False
        return target + 24, False

    def block_stub(e, cx, k, side):
        return cx + side * (SIDE_W[e.kind] - 8 - 14 * k)

    for cx, chain in zip(col_x, columns):
        for e, _t, _b in chain:
            if e.kind in BLOCK_PINS:
                ks = {-1: 0, 1: 0}
                for i, name in BLOCK_PINS[e.kind]:
                    side = -1 if name in ('in-', 'in+', 'dis', 'thr', 'trig') else 1
                    net_cols.setdefault(e.nets[i], []).append(block_stub(e, cx, ks[side], side))
                    ks[side] += 1
            elif e.kind in MAIN:
                net_cols.setdefault(side_nets(e)[0], []).append(side_x(e, cx)[0])
    # 같은 층(높이)의 서로 다른 마디가 가로로 겹치면 거짓 연결처럼 보이므로 높이를 나눕니다
    by_rank = {}
    for n in nets:
        if n in net_cols:
            by_rank.setdefault(rank[n], []).append(n)
    for r, group in by_rank.items():
        lanes = []
        for n in sorted(group, key=lambda n: min(net_cols[n])):
            lo, hi = min(net_cols[n]), max(net_cols[n])
            for k, lane in enumerate(lanes):
                if all(hi < a - 12 or lo > b + 12 for a, b in lane):
                    lane.append((lo, hi))
                    row[n] += k * 34
                    break
            else:
                lanes.append([(lo, hi)])
                row[n] += (len(lanes) - 1) * 34

    for i, (s, sx) in enumerate(zip(sources, xs_src)):
        d.cur = s.pid
        yp, yn = row[s.nets[0]], row[s.nets[1]]
        sym_source_v(d, s, sx, min(yp, yn), max(yp, yn), plus_top=yp < yn)
        if i == 0:                                   # 첫 전원은 왼쪽, 나머지는 오른쪽에 이름표
            source_label(d, sx - 46, (yp + yn) / 2, s.label, 'right')
        else:
            source_label(d, sx + 48, (yp + yn) / 2, s.label, 'left')
        d.cur = None
        attach[s.nets[0]].append((sx, False, True))
        attach[s.nets[1]].append((sx, True, False))

    def to_row(px, py, net, sx):
        """핀 끝 (px, py)에서 가로로 sx까지, 다시 세로로 그 마디 높이까지."""
        y = row[net]
        d.net = net
        d.line(px, py, sx, py)
        d.segs.append((px, py, sx, py, net))
        if abs(y - py) > 0.5:
            d.line(sx, py, sx, y)
            d.segs.append((sx, py, sx, y, net))
        d.net = None
        attach[net].append((sx, y > py, y < py))

    for cx, chain in zip(col_x, columns):
        for e, t, b in chain:
            yt, yb = row[t], row[b]
            mid = (yt + yb) / 2 if yb - yt < ROW - 1 else yt + ROW / 2   # 반 칸짜리 변은 가운데에
            d.cur = e.pid
            if e.kind in BLOCK_PINS:
                body = (_opamp_body if e.kind == 'opamp' else _timer_body)(d, cx, yt, yb, mid)
                ks = {-1: 0, 1: 0}
                for i, name in BLOCK_PINS[e.kind]:
                    px, py, side = body[name]
                    to_row(px, py, e.nets[i], block_stub(e, cx, ks[side], side))
                    ks[side] += 1
                d.text(cx - (40 if e.kind == 'opamp' else 52), mid - (46 if e.kind == 'opamp' else 58), e.label,
                       align='right')
            elif e.kind in MAIN:
                sx, right = side_x(e, cx)
                m = 1 if right else -1
                sn = side_nets(e)[0]
                if e.kind in ('npn', 'pnp'):
                    bar = _bjt_vertical(d, cx, row[e.nets[0]], row[e.nets[2]], mid, right, e.kind == 'pnp')
                    to_row(bar, mid, sn, sx)
                elif e.kind == 'nmos':
                    gate = _mos_vertical(d, cx, row[e.nets[0]], row[e.nets[2]], mid, right)
                    to_row(gate, mid, sn, sx)
                elif e.kind == 'pot':
                    wx = _pot_vertical(d, e, cx, yt, yb, mid, e.nets[0] != t, right)
                    to_row(wx, mid, sn, sx)
                else:
                    px, py = _spdt_vertical(d, e, cx, yt, yb, mid, e.nets[1] == t, right)
                    to_row(px, py, sn, sx)
                lx = cx - 40 if right else cx + 40
                d.text(lx, mid, e.label, align='right' if right else 'left')
            else:
                d.net = t
                d.line(cx, yt, cx, mid - HALF)
                d.net = b
                d.line(cx, mid + HALF, cx, yb)
                d.net = None
                _vertical_symbol(d, e, cx, mid, rev=e.nets[0] != t)
                d.text(cx + (64 if e.kind in ('led', 'ldr') else 38), mid, e.label, align='left')
            d.cur = None
            attach[t].append((cx, False, True))
            attach[b].append((cx, True, False))

    # 마디 가로선과 연결점
    for n, pts in attach.items():
        if not pts:
            continue
        y = row[n]
        xs = sorted({p[0] for p in pts})
        d.net = n
        if len(xs) > 1:
            d.line(xs[0], y, xs[-1], y)
            d.segs.append((xs[0], y, xs[-1], y, n))
        for xx in xs:
            here = [p for p in pts if p[0] == xx]
            ways = (any(p[1] for p in here) + any(p[2] for p in here)
                    + (xx > xs[0]) + (xx < xs[-1]))
            if ways >= 3:
                d.circle(xx, y, 4, w=1, fill=INK)
        d.net = None
    for n, pts in attach.items():                # 아무 데도 이어지지 않은 끝: 열린 단자(○)
        if n != ground and len(pts) == 1:
            d.net = n
            d.circle(pts[0][0], row[n], 4.5, w=1.8, fill='#ffffff')
            d.net = None
    if ground in attach and attach[ground]:
        gx = min(p[0] for p in attach[ground])
        gy = row[ground]
        d.net = ground
        d.line(gx, gy, gx, gy + 18)
        for i, half in enumerate((18, 11, 4)):
            d.line(gx - half, gy + 18 + i * 6, gx + half, gy + 18 + i * 6)
        d.net = None


def _crossings(d, elems):
    """배치 점수: 서로 다른 마디 선의 교차, 남의 기호를 지나가는 선, 전체 선 길이."""
    segs = d.segs
    cross = 0
    hs = [x for x in segs if abs(x[1] - x[3]) < 0.5]
    vs = [x for x in segs if abs(x[0] - x[2]) < 0.5 and abs(x[1] - x[3]) >= 0.5]
    for x1, y, x2, _y, n in hs:
        lo, hi = sorted((x1, x2))
        for vx, y1, _vx, y2, m in vs:
            if m == n:
                continue
            a, b = sorted((y1, y2))
            if lo + 1 < vx < hi - 1 and a + 1 < y < b - 1:
                cross += 1
    nets_of = {e.pid: set(e.nets) for e in elems}
    through = 0
    for tag, r in d.tags.items():
        own = nets_of.get(tag, set())
        box = r.adjusted(3, 3, -3, -3)
        for x1, y1, x2, y2, n in segs:
            if n in own:
                continue
            seg = QRectF(QPointF(min(x1, x2), min(y1, y2)), QPointF(max(x1, x2) + 0.1, max(y1, y2) + 0.1))
            if box.intersects(seg):
                through += 1
    over = 0
    for lab in d.labels:
        box = lab.adjusted(1, 2, -1, -2)
        for x1, y1, x2, y2, _n in segs:
            seg = QRectF(QPointF(min(x1, x2), min(y1, y2)), QPointF(max(x1, x2) + 0.1, max(y1, y2) + 0.1))
            if box.intersects(seg):
                over += 1
    length = sum(abs(x1 - x2) + abs(y1 - y2) for x1, y1, x2, y2, _n in segs)
    return cross * 10 + through * 25 + over * 15 + length * 0.002


def draw_ladder_best(d, elems, sources, ground, potential, budget=160):
    """열 순서를 바꿔 가며 선이 덜 꼬이는 배치를 고릅니다(이웃 맞바꾸기·옮기기 언덕 오르기)."""
    probe = Drawing()
    draw_ladder(probe, elems, sources, ground, potential)
    n = probe.ncols
    best = list(range(n))
    best_score = _crossings(probe, elems)
    tried = {tuple(best)}
    improved = n > 1
    evals = 0
    while improved and evals < budget:
        improved = False
        moves = [(i, j) for i in range(n) for j in range(n) if i != j]
        for i, j in moves:
            cand = best[:]
            c = cand.pop(i)
            cand.insert(j, c)
            if tuple(cand) in tried:
                continue
            tried.add(tuple(cand))
            t = Drawing()
            draw_ladder(t, elems, sources, ground, potential, cand)
            evals += 1
            sc = _crossings(t, elems)
            if sc < best_score - 1e-9:
                best, best_score, improved = cand, sc, True
                break
            if evals >= budget:
                break
    draw_ladder(d, elems, sources, ground, potential, best)
    d.score = best_score


def _shape_boxes(d):
    """선·기호가 차지하는 작은 사각형들(글자가 피해야 할 곳)."""
    out = []
    for kind, a, _t in d.ops:
        if kind == 'line':
            x1, y1, x2, y2, w = a
            if abs(x1 - x2) > 0.5 and abs(y1 - y2) > 0.5:          # 비스듬한 선은 몇 조각으로
                for k in range(6):
                    t0, t1 = k / 6, (k + 1) / 6
                    xa, ya = x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0
                    xb, yb = x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1
                    out.append(QRectF(QPointF(min(xa, xb), min(ya, yb)), QPointF(max(xa, xb), max(ya, yb)))
                               .adjusted(-w / 2, -w / 2, w / 2, w / 2))
            else:
                out.append(QRectF(QPointF(min(x1, x2), min(y1, y2)), QPointF(max(x1, x2), max(y1, y2)))
                           .adjusted(-w / 2, -w / 2, w / 2, w / 2))
        elif kind == 'path':
            pts = a[0]
            xs, ys = [q[0] for q in pts], [q[1] for q in pts]
            out.append(QRectF(min(xs), min(ys), max(xs) - min(xs) + 0.5, max(ys) - min(ys) + 0.5))
        elif kind == 'circle':
            x, y, r, w, _f = a
            out.append(QRectF(x - r, y - r, 2 * r, 2 * r))
    return out


def text_clashes(d):
    """글자가 선·기호나 다른 글자와 겹치는 곳 수."""
    shapes = _shape_boxes(d)
    texts = [QRectF(a[0], a[1], a[2], a[3]).adjusted(1, 3, -1, -3) for k, a, _t in d.ops if k == 'text']
    n = sum(1 for t in texts for b in shapes if t.intersects(b))
    n += sum(1 for i in range(len(texts)) for j in range(i + 1, len(texts)) if texts[i].intersects(texts[j]))
    return n


def declutter(d):
    """선이나 다른 글자에 걸친 이름표를 가장 가까운 빈자리로 옮깁니다."""
    shapes = _shape_boxes(d)
    placed = []
    offsets = sorted({(dx, dy) for dx in (0, 8, -8, 18, -18, 32, -32, 50, -50)
                      for dy in (0, -10, 10, -18, 18, -28, 28, -40, 40)},
                     key=lambda o: (abs(o[0]) * 0.8 + abs(o[1]), o))
    for i, (kind, a, tag) in enumerate(d.ops):
        if kind != 'text':
            continue
        left, top, w, h, text, px, bold = a
        for dx, dy in offsets:
            r = QRectF(left + dx, top + dy, w, h).adjusted(1, 3, -1, -3)
            if not any(r.intersects(b) for b in shapes) and not any(r.intersects(q) for q in placed):
                break
        else:
            dx = dy = 0
            r = QRectF(left, top, w, h).adjusted(1, 3, -1, -3)
        if dx or dy:
            d.ops[i] = ('text', (left + dx, top + dy, w, h, text, px, bold), tag)
            moved = QRectF(left + dx, top + dy, w, h)
            d.box = d.box.united(moved)
            if tag is not None and tag in d.tags:
                d.tags[tag] = d.tags[tag].united(moved)
        placed.append(r)


# ---------------------------------------------------------------- 진입점
class Schematic:
    """회로도 한 장. drawing(도형 기록), title, mode('loop' 또는 'ladder')."""

    def __init__(self, parts, inst, potential=None, title=None, show_title=True):
        elems, sources, ground = extract(parts, inst)
        self.empty = not elems and not sources
        self.mode = 'empty'
        d = Drawing()
        auto_title = '회로도'
        if not self.empty:
            expr = sp_reduce(elems, sources[0]) if len(sources) == 1 else None
            if expr is not None:
                self.mode = 'loop'
                auto_title = classify(expr)
                draw_loop(d, sources[0], expr)
            else:
                self.mode = 'ladder'
                auto_title = classify_ladder(elems)
                draw_ladder_best(d, elems, sources, ground, potential)
        self.title = title or auto_title
        if not self.empty:
            declutter(d)
        if show_title and not self.empty:
            r = d.rect()
            d.text(r.center().x(), r.top() - 50, self.title, px=TITLE_PX, bold=True)
        self.drawing = d

    def rect(self, margin=40):
        return self.drawing.rect().adjusted(-margin, -margin, margin, margin)

    def paint(self, p, target: QRectF, background='#ffffff', marks=None):
        """target 안에 비율을 유지해 가운데 맞춰 그립니다."""
        r = self.rect()
        if background:
            p.fillRect(target, QColor(background))
        s = min(target.width() / r.width(), target.height() / r.height())
        p.save()
        p.translate(target.center())
        p.scale(s, s)
        p.translate(-r.center())
        self.drawing.render(p, marks=marks)
        p.restore()

    # ---------- 내보내기
    def image(self, scale=2.0):
        r = self.rect()
        img = QImage(int(r.width() * scale), int(r.height() * scale), QImage.Format.Format_ARGB32)
        img.fill(QColor('#ffffff'))
        p = QPainter(img)
        self.paint(p, QRectF(0, 0, img.width(), img.height()))
        p.end()
        return img

    def save_png(self, path, scale=2.0):
        return self.image(scale).save(str(path), 'PNG')

    def save_svg(self, path):
        from PySide6.QtSvg import QSvgGenerator
        r = self.rect()
        gen = QSvgGenerator()
        gen.setFileName(str(path))
        gen.setSize(QSize(int(r.width()), int(r.height())))
        gen.setViewBox(QRectF(0, 0, r.width(), r.height()))
        gen.setTitle(self.title)
        p = QPainter(gen)
        self.paint(p, QRectF(0, 0, r.width(), r.height()))
        p.end()
        return True

    def save_pdf(self, path):
        r = self.rect()
        landscape = r.width() >= r.height()
        w = QPdfWriter(str(path))
        w.setTitle(self.title)
        w.setResolution(300)
        w.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        w.setPageOrientation(QPageLayout.Orientation.Landscape if landscape else QPageLayout.Orientation.Portrait)
        w.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
        p = QPainter(w)
        page = QRectF(0, 0, w.width(), w.height())
        self.paint(p, page)
        p.end()
        return True
