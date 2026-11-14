"""회로도 파일을 읽어 브레드보드 위에 자동으로 꾸밉니다 (Qt 비의존).

1. 해석: Falstad CircuitJS 회로 파일(.txt)은 부품마다 화면 좌표를 적어 둡니다. 부품 다리(포스트)의
   좌표를 원래 프로그램과 같은 식으로 계산하고, 같은 좌표·전선으로 이어진 다리를 한 마디로 묶어
   넷리스트(부품 ↔ 마디)를 만듭니다.
2. 대응: 각 부품을 BreadLab 부품으로 바꾸고, 전원을 장비에 나눠 줍니다.
   교류 전원 → 함수 발생기, 접지 기준 직류 → 전원 CH1, 다음 직류 → CH2(절연), 나머지 → 건전지.
   연산 증폭기의 ±전원처럼 회로도에 숨어 있는 전원도 꺼내 붙입니다.
3. 배치: 접지·전원은 레일에, IC는 가운데 홈을 걸쳐 꽂고, 나머지 마디는 세로 다섯 칸 줄 하나씩
   나눠 줍니다. 한 줄이 모자라면 옆 줄을 점퍼선으로 이어 늘립니다. 2단자 부품은 되도록 같은 행에
   가로로 눕혀 다른 부품과 겹치지 않게 놓습니다.
4. 검증: 보드 위 연결을 다시 계산해 원래 넷리스트와 마디가 1:1로 맞는지 확인합니다.
"""
from dataclasses import dataclass, field
import math

from circuit_core import (COLS, FG_MAX_F, FG_MAX_OFFSET, FG_MAX_VPP, FG_MIN_F, IC_KINDS, PSU_MAX_V, THREE_PIN, Part,
                          RED, GREEN, YELLOW, BLUE, WHITE, default_instruments, dip_pins, net_map)

GRID = 8
GND = 'GND'


class ImportError_(ValueError):
    pass


# ---------------------------------------------------------------- Falstad 좌표 계산
def _interp(a, b, f, g=0.0):
    x = a[0] * (1 - f) + b[0] * f
    y = a[1] * (1 - f) + b[1] * f
    if g:
        gx, gy = b[1] - a[1], a[0] - b[0]
        n = math.hypot(gx, gy)
        x += g * gx / n
        y += g * gy / n
    return (math.floor(x + .48), math.floor(y + .48))


def _sign(v):
    return (v > 0) - (v < 0)


def _dsign(p1, p2):
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    return _sign(dx) if dy == 0 else _sign(dy)


def _chip_posts(x, y, flags, pins, size_x, size_y):
    """ChipElm 핀 좌표. pins: [(pos, side)], side: N S W E."""
    csize = 1 if flags & 1 else 2
    cspc = 8 * csize
    cspc2 = cspc * 2
    x0, y0 = x + cspc2, y
    xs, ys = size_x * cspc2, size_y * cspc2
    out = []
    for pos, side in pins:
        px, py, dx, dy, dax, day, sx, sy = {
            'N': (x0, y0, 1, 0, 0, -1, 0, 0), 'S': (x0, y0, 1, 0, 0, 1, 0, ys - cspc2),
            'W': (x0, y0, 0, 1, -1, 0, 0, 0), 'E': (x0, y0, 0, 1, 1, 0, xs - cspc2, 0)}[side]
        if flags & 1024:
            dx, dax, px, sx = -dx, -dax, px + cspc2 * (size_x - 1), -sx
        if flags & 2048:
            dy, day, py, sy = -dy, -day, py + cspc2 * (size_y - 1), -sy
        xa = px + cspc2 * dx * pos + sx
        ya = py + cspc2 * dy * pos + sy
        out.append((xa + dax * cspc2, ya + day * cspc2))
    return out


def _f(tok, i, default):
    try:
        return float(tok[i])
    except (IndexError, ValueError):
        return default


@dataclass
class Comp:
    kind: str
    posts: list                 # 좌표 또는(마디 계산 뒤) 마디 이름
    props: dict = field(default_factory=dict)
    line: int = 0


@dataclass
class Netlist:
    comps: list
    sources: list               # Comp(kind='dc'|'ac', posts=[+, −], props)
    probes: list                # 마디(관찰 지점)
    unsupported: list
    nets: list = field(default_factory=list)
    dangling: list = field(default_factory=list)


LED_RGB = {RED: (1, 0, 0), YELLOW: (1, 1, 0), GREEN: (0, 1, 0), BLUE: (0, 0, 1), WHITE: (1, 1, 1)}
IGNORE = {'$', 'o', 'h', 'x', '&', 'b', '403', '38', '%', '?', 'B'}


def parse_falstad(text):
    """Falstad 회로 파일 → Netlist(마디 이름으로 정리된)."""
    comps, sources, probes, unsupported, wires, grounds = [], [], [], [], [], []
    for ln, raw in enumerate(text.splitlines(), 1):
        tok = raw.split()
        if not tok or tok[0] in IGNORE:
            continue
        t = tok[0]
        try:
            x1, y1, x2, y2, flags = (int(float(v)) for v in tok[1:6])
        except ValueError:
            unsupported.append(f'{ln}행: 읽을 수 없는 줄')
            continue
        p1, p2 = (x1, y1), (x2, y2)
        prm = tok[6:]
        if t == 'w' or t == '370':                       # 전선, 전류계(0 Ω)
            wires.append((p1, p2))
        elif t == 'g':
            grounds.append(p1)
        elif t == 'r':
            comps.append(Comp('resistor', [p1, p2], dict(value=_f(prm, 0, 1000)), ln))
        elif t == 'c':
            comps.append(Comp('capacitor', [p1, p2], dict(value=_f(prm, 0, 1e-6), v0=_f(prm, 1, 0.0)), ln))
        elif t == 'l':
            comps.append(Comp('inductor', [p1, p2], dict(value=_f(prm, 0, 1e-3), v0=_f(prm, 1, 0.0)), ln))
        elif t == 'd':
            comps.append(Comp('diode', [p1, p2], {}, ln))
        elif t == 'z':
            vz = _f(prm, 1, 5.6) if flags & 1 else 5.6
            comps.append(Comp('zener', [p1, p2], dict(value=vz), ln))
        elif t == '162':
            rgb = (_f(prm, -3, 1), _f(prm, -2, 0), _f(prm, -1, 0)) if len(prm) >= 3 else (1, 0, 0)
            color = min(LED_RGB, key=lambda c: sum((a - b) ** 2 for a, b in zip(LED_RGB[c], rgb)))
            comps.append(Comp('led', [p1, p2], dict(color=color), ln))
        elif t == 's':
            pos = prm[0] if prm else '0'
            closed = pos == 'false' or pos == '0'
            comps.append(Comp('switch', [p1, p2], dict(closed=closed), ln))
        elif t == 'S':
            lead2 = p2
            a = _interp(p1, p2, 1, 16)
            b = _interp(p1, p2, 1, -16)
            pos = prm[0] if prm else '0'
            pos = 0 if pos in ('true', '0') else 1
            comps.append(Comp('spdt', [a, p1, b], dict(closed=pos == 0), ln))
        elif t == 'L':
            pos = prm[0] if prm else '0'
            pos = 0 if pos in ('true', '0') else 1
            hi = _f(prm, 2, 5.0)
            comps.append(Comp('logic', [p1], dict(high=pos == 1, hi=hi), ln))
        elif t == 't':
            pnp = int(_f(prm, 0, 1)) == -1
            ds = _dsign(p1, p2)
            if flags & 1:
                ds = -ds
            hs2 = 16 * ds * (-1 if pnp else 1)
            coll, emit = _interp(p1, p2, 1, hs2), _interp(p1, p2, 1, -hs2)
            beta = _f(prm, 3, 100.0)
            comps.append(Comp('pnp' if pnp else 'npn', [coll, p1, emit], dict(value=min(max(beta, 10), 1000)), ln))
        elif t == 'f':
            if flags & 1:
                unsupported.append(f'{ln}행: P채널 MOSFET')
                continue
            hs2 = 16 * _dsign(p1, p2)
            if flags & 8:
                hs2 = -hs2
            src, drn = _interp(p1, p2, 1, -hs2), _interp(p1, p2, 1, hs2)
            vt = _f(prm, 0, 1.5)
            comps.append(Comp('nmos', [drn, p1, src], dict(value=min(max(vt, 0.5), 5.0)), ln))
        elif t == 'a':
            hs = (8 if flags & 2 else 16) * _dsign(p1, p2)
            if flags & 1:
                hs = -hs
            inm, inp = _interp(p1, p2, 0, hs), _interp(p1, p2, 0, -hs)
            comps.append(Comp('opamp', [inm, inp, p2], dict(vmax=_f(prm, 0, 15), vmin=_f(prm, 1, -15)), ln))
        elif t == '165':
            pins = [(1, 'W'), (3, 'W'), (4, 'W'), (1, 'N'), (1, 'S'), (2, 'E')]
            if flags & 6:
                pins.append((1, 'E'))
            if flags & 4:
                pins.append((2, 'S'))
            posts = _chip_posts(x1, y1, flags, pins, 3, 5)
            comps.append(Comp('timer555', posts, dict(reset=bool(flags & 6), ground=bool(flags & 4)), ln))
        elif t == '174':
            dx, dy = x2 - x1, y2 - y1
            if abs(dx) > abs(dy):
                n = 2 * GRID * _sign(dx) * ((abs(dx) + 2 * GRID - 1) // (2 * GRID))
                q2 = (x1 + n, y1)
                off = dy if dx < 0 else -dy
            else:
                n = 2 * GRID * _sign(dy) * ((abs(dy) + 2 * GRID - 1) // (2 * GRID))
                q2 = (x1, y1 + n) if dy else p2
                off = dx if dy > 0 else -dx
            off = off or GRID
            wiper = _interp(p1, q2, .5, off)
            comps.append(Comp('pot', [p1, wiper, q2], dict(value=_f(prm, 0, 1000),
                                                             pos=min(max(_f(prm, 1, .5), 0), 1) * 100), ln))
        elif t in ('v', 'R', '172', '170'):
            wave = int(_f(prm, 0, 0))
            props = dict(wave=wave, freq=_f(prm, 1, 40), amp=_f(prm, 2, 5), bias=_f(prm, 3, 0),
                         duty=_f(prm, 5, .5))
            if t == '172':                                # 가변 전원: 현재 전압이 주파수 칸에 있음
                props.update(wave=0, amp=_f(prm, 1, 5), bias=0)
            if t == '170':                                # 주파수 훑기: 가운데 주파수의 사인파
                props = dict(wave=1, freq=math.sqrt(max(_f(prm, 0, 20), .1) * max(_f(prm, 1, 4000), .1)),
                             amp=_f(prm, 2, 5), bias=0, duty=.5)
            pos, neg = (p2, p1) if t == 'v' else (p1, GND)
            kind = 'dc' if props['wave'] == 0 else 'ac'
            if props['wave'] not in (0, 1, 2, 3, 4):
                unsupported.append(f'{ln}행: 지원하지 않는 전원 파형({props["wave"]})')
                continue
            sources.append(Comp(kind, [pos, neg], props, ln))
        elif t in ('O', 'M', '211'):
            probes.append(p1)
        elif t == 'p':
            probes.append(p1)
        else:
            unsupported.append(f'{ln}행: 알 수 없는 부품({t})')

    # 좌표 → 마디
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            if rb == GND:
                ra, rb = rb, ra
            parent[rb] = ra

    find(GND)
    for a, b in wires:
        union(a, b)
    for g in grounds:
        union(g, GND)
    names = {}

    def net(pt):
        r = find(pt)
        if r == GND:
            return GND
        if r not in names:
            names[r] = f'n{len(names) + 1}'
        return names[r]

    for c in comps + sources:
        c.posts = [net(p) for p in c.posts]
    probes = [net(p) for p in probes]
    nl = Netlist(comps, sources, probes, unsupported)
    count = {}
    for c in comps + sources:
        for n in c.posts:
            count[n] = count.get(n, 0) + 1
    nl.nets = sorted(count)
    nl.dangling = [n for n, k in count.items() if k == 1 and n != GND]
    return nl


# ---------------------------------------------------------------- BreadLab 부품·장비로 바꾸기
@dataclass
class Plan:
    comps: list                 # Comp(kind=BreadLab 종류, posts=마디 목록(IC는 8핀, 빈 핀은 None))
    ground: str
    ch1: tuple | None = None    # (+마디, −마디, 전압)
    ch2: tuple | None = None
    fg: tuple | None = None     # (+마디, −마디, 설정)
    rails: dict = field(default_factory=dict)    # 마디 → 'gnd' | 'vp' | 'vn'
    probes: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def make_plan(nl):
    notes = list(nl.unsupported)
    comps = [Comp(c.kind, list(c.posts), dict(c.props), c.line) for c in nl.comps]
    ac = [s for s in nl.sources if s.kind == 'ac']
    dcs = []
    for s in nl.sources:
        if s.kind != 'dc':
            continue
        v = s.props['amp'] + s.props['bias']
        pos, neg = s.posts
        if v < 0:
            pos, neg, v = neg, pos, -v
        if v < 1e-9 or pos == neg:
            continue
        dcs.append([pos, neg, v])
    if len(ac) > 1:
        notes.append(f'교류 전원이 {len(ac)}개라 첫 번째만 함수 발생기에 연결했습니다.')
    used_gnd = any(GND in c.posts for c in comps) or any(GND in s.posts for s in nl.sources)
    if ac:
        ground = ac[0].posts[1]
    elif used_gnd:
        ground = GND
    elif dcs:
        ground = dcs[0][1]
    else:
        raise ImportError_('회로에 전원이 없습니다.')

    def need_rail(v, negative=False):
        """접지 기준 v 볼트 마디(negative면 −v). 없으면 새 직류 전원을 만듭니다."""
        for pos, neg, vv in dcs:
            if abs(vv - v) < 1e-6 and (neg == ground if not negative else pos == ground):
                return neg if negative else pos
        name = f'{"vn" if negative else "vp"}{v:g}'
        dcs.append([ground, name, v] if negative else [name, ground, v])
        return name

    out = []
    for c in comps:
        if c.kind == 'logic':                                   # 논리 입력 → 누름 전환 스위치
            hi = need_rail(c.props['hi'])
            out.append(Comp('spdt', [ground, c.posts[0], hi], dict(closed=not c.props['high']), c.line))
        elif c.kind == 'opamp':
            vp = need_rail(c.props['vmax']) if c.props['vmax'] > 0 else ground
            vn = need_rail(-c.props['vmin'], negative=True) if c.props['vmin'] < 0 else ground
            inm, inp, o = c.posts
            out.append(Comp('opamp', [None, inm, inp, vn, None, o, vp, None], {}, c.line))
        elif c.kind == 'timer555':
            dis, trig, thr, vin, ctl, o = c.posts[:6]
            rst = c.posts[6] if c.props['reset'] else vin
            gnd = c.posts[7] if c.props['ground'] else ground
            out.append(Comp('timer555', [gnd, trig, o, rst, ctl, thr, dis, vin], {}, c.line))
        else:
            out.append(c)
    comps = out

    # 같은 마디 쌍의 직류 전원은 하나로
    uniq = []
    for d in dcs:
        if not any({d[0], d[1]} == {u[0], u[1]} for u in uniq):
            uniq.append(d)
    dcs = uniq
    plan = Plan(comps, ground)
    if ac:
        s = ac[0]
        p = s.props
        wave = {1: 'sine', 2: 'square', 3: 'triangle', 4: 'ramp'}[p['wave']]
        freq = min(max(p['freq'], FG_MIN_F), FG_MAX_F)
        vpp = min(2 * abs(p['amp']), FG_MAX_VPP)
        off = min(max(p['bias'], -FG_MAX_OFFSET), FG_MAX_OFFSET)
        if abs(freq - p['freq']) > 1e-9 or abs(vpp - 2 * abs(p['amp'])) > 1e-9:
            notes.append('함수 발생기 범위(0.1 Hz~20 kHz, 20 Vpp)에 맞게 값을 줄였습니다.')
        plan.fg = (s.posts[0], s.posts[1], dict(wave=wave, freq=freq, vpp=vpp, offset=off,
                                                 duty=min(max(p['duty'] * 100, 1), 99), on=True))
    grounded = sorted([d for d in dcs if d[1] == ground], key=lambda d: -d[2])
    negative = [d for d in dcs if d[0] == ground]
    rest = [d for d in dcs if d not in grounded and d not in negative]
    if grounded:
        plan.ch1 = tuple(grounded.pop(0))
    order = negative + grounded + rest
    if order:
        plan.ch2 = tuple(order.pop(0))
    for pos, neg, v in order:                                   # 남은 직류 전원은 건전지로
        plan.comps.append(Comp('battery', [pos, neg], dict(value=v)))
        notes.append(f'직류 전원 {v:g} V는 장비가 모자라 건전지로 넣었습니다.')
    for src in (plan.ch1, plan.ch2):
        if src and src[2] > PSU_MAX_V:
            notes.append(f'{src[2]:g} V는 전원 공급기 최대 {PSU_MAX_V:g} V로 줄였습니다.')
    plan.ch1 = plan.ch1 and (plan.ch1[0], plan.ch1[1], min(plan.ch1[2], PSU_MAX_V))
    plan.ch2 = plan.ch2 and (plan.ch2[0], plan.ch2[1], min(plan.ch2[2], PSU_MAX_V))
    plan.rails = {ground: 'gnd'}
    if plan.ch1:
        plan.rails[plan.ch1[0]] = 'vp'
    if plan.ch2 and plan.ch2[0] == ground:
        plan.rails[plan.ch2[1]] = 'vn'
    plan.probes = [n for n in nl.probes if n is not None]
    if 'vn' in plan.rails.values():
        notes.append('±전원 회로라 아래쪽 빨간 레일을 V−(음전원)으로 썼습니다.')
    plan.notes = notes
    return plan


# ---------------------------------------------------------------- 브레드보드 배치
TOP_RAIL = {'vp': 'r0', 'gnd': 'r1', 'vn': 'r2'}
BOT_RAIL = {'vp': 'r2', 'gnd': 'r3', 'vn': 'r2'}


class Board:
    def __init__(self, plan):
        self.plan = plan
        self.used = set()
        self.strips = {}          # 마디 → [(블록, 열)]
        self.owner = {}           # (블록, 열) → 마디
        self.spans = {}           # (블록, 행) → [(열1, 열2)] 가로 부품이 차지한 구간
        self.parts = []
        self.vn = 'vn' in plan.rails.values()

    # ---------- 구멍
    @staticmethod
    def hole(block, row, col):
        return f'{block}{row}:{col}'

    def free_rows(self, strip):
        b, c = strip
        return [r for r in range(5) if self.hole(b, r, c) not in self.used]

    def take(self, h):
        assert h not in self.used, h
        self.used.add(h)
        return h

    def rail_row(self, net, block):
        kind = self.plan.rails[net]
        if kind == 'vp' and self.vn:
            return 'r0'
        return (TOP_RAIL if block == 't' else BOT_RAIL)[kind]

    def rail_hole(self, row, col):
        for d in sorted(range(COLS), key=lambda k: (abs(k - col), k)):
            h = f'{row}:{d}'
            if h not in self.used:
                return self.take(h)
        raise ImportError_('레일 구멍이 모자랍니다.')

    def add(self, kind, a, b, c=None, **kw):
        pid = len(self.parts) + 1
        self.parts.append(Part(pid, kind, a, b, c=c, **kw))
        return self.parts[-1]

    # ---------- 줄 나누기
    def free_strip_cols(self, block):
        return [c for c in range(COLS) if (block, c) not in self.owner]

    def give(self, net, strip):
        self.owner[strip] = net
        self.strips.setdefault(net, []).append(strip)


def _legs(plan):
    legs = {}
    for c in plan.comps:
        if c.kind in IC_KINDS:          # IC 핀은 이미 제 줄의 구멍 하나를 쓰고 있음
            continue
        for n in c.posts:
            if n is not None:
                legs[n] = legs.get(n, 0) + 1
    return legs


def _order_nets(plan):
    """+ 전원에서 시작해 부품을 따라가며 마디 순서를 정합니다(이어진 마디가 가까이 놓이게)."""
    rails = set(plan.rails)
    start = [plan.ch1[0]] if plan.ch1 else []
    if plan.fg:
        start.insert(0, plan.fg[0])
    seen, order = set(rails), []
    queue = [n for n in start if n not in rails]
    for n in start:
        for c in plan.comps:
            if n in c.posts:
                queue += [m for m in c.posts if m is not None]
    for c in plan.comps:
        queue += [m for m in c.posts if m is not None]
    i = 0
    while i < len(queue):
        n = queue[i]
        i += 1
        if n in seen:
            continue
        seen.add(n)
        order.append(n)
        nxt = []
        for c in plan.comps:
            if n in c.posts:
                nxt += [m for m in c.posts if m is not None and m not in seen]
        queue[i:i] = nxt
    return order


def place(plan, variant=0):
    """variant: 마디를 놓는 순서·시작 블록을 바꾼 배치안 번호(place_best가 여러 안을 비교합니다)."""
    bd = Board(plan)
    rails = plan.rails
    three = [c for c in plan.comps if c.kind in THREE_PIN]
    ics = [c for c in plan.comps if c.kind in IC_KINDS]
    legs = {}
    for c in plan.comps:
        if c.kind in IC_KINDS or c.kind in THREE_PIN:       # 이 부품들은 제 줄을 따로 받습니다
            continue
        for n in c.posts:
            legs[n] = legs.get(n, 0) + 1
    extra = [n for src in (plan.fg, plan.ch2) if src for n in src[:2]]
    extra += ([plan.fg[0]] if plan.fg else []) + plan.probes[:2]
    for n in extra:
        if n not in rails:
            legs[n] = legs.get(n, 0) + 1
    bd.vcols = {'t': set(), 'b': set()}          # 레일로 세로 다리가 지나는 열

    def find_run(block, k, start):
        for c0 in range(start, COLS - k + 1):
            if all((block, c0 + j) not in bd.owner for j in range(k)):
                return c0
        return None

    # 1. IC: 가운데 홈을 걸쳐 왼쪽부터
    x, nc, ic_parts = 1, 0, []
    for c in ics:
        if x + 3 >= COLS:
            raise ImportError_('IC가 너무 많아 보드에 다 꽂을 수 없습니다.')
        anchor = f'b0:{x}'
        for i, h in enumerate(dip_pins(anchor)):
            bd.take(h)
            n = c.posts[i]
            if n is None:
                nc += 1
                n = f'nc{nc}'
            bd.give(n, (h[0], int(h.split(':')[1])))
        ic_parts.append((c, anchor))
        x += 6
    cursor = {'t': x if ics else 1, 'b': x if ics else 1}

    # 2. 트랜지스터·가변저항·전환 스위치: 실물처럼 이웃한 세 열에 나란히
    three_holes = []
    room = 2 * COLS - 6 * len(ics) - 2 * len(plan.comps)
    # 자리가 넉넉하면 다리를 벌려, 다리마다 세로로 선 부품의 값 표시가 서로 겹치지 않게
    step = 3 if len(three) * 9 <= room else 2 if len(three) * 6 <= room else 1

    def find_spread(block, start):
        for c0 in range(start, COLS - 2 * step):
            if all((block, c0 + j * step) not in bd.owner for j in range(3)):
                return c0
        return None

    vn = {n for n, k in rails.items() if k == 'vn'}

    def touches_vn(nets):
        return any(m in vn for c in plan.comps if set(c.posts) & set(nets) for m in c.posts)

    seq = list(range(len(three)))
    if variant >= 8:                                 # 3단자 부품 순서도 바꿔 봅니다(서로 이어진 것끼리 가까이)
        import random
        random.Random(variant * 7919).shuffle(seq)
    holes_of = {}
    for k in seq:
        c = three[k]
        if touches_vn(c.posts):                      # 음전원은 아래 레일에만 있으니 아래 블록에
            blocks = ('b', 't')
        else:
            blocks = ('t', 'b') if (variant // 2) % 2 == 0 else ('b', 't')
        for block in blocks:
            c0 = find_spread(block, cursor[block])
            if c0 is not None:
                break
        else:
            raise ImportError_('3단자 부품을 꽂을 자리가 모자랍니다.')
        holes = []
        for i, n in enumerate(c.posts):
            strip = (block, c0 + i * step)
            bd.give(n, strip)
            holes.append(bd.take(bd.hole(block, 2, c0 + i * step)))
        holes_of[k] = holes
        cursor[block] = c0 + 2 * step + 2

    three_holes = [holes_of[k] for k in range(len(three))]

    # 3. 나머지 마디에 줄 나눠 주기(모자라면 옆 줄을 더 받아 점퍼선으로 잇습니다)
    order = [n for n in _order_nets(plan) if n not in rails]
    if variant:
        import random
        rng = random.Random(variant)
        if variant % 4 == 1:
            order.reverse()
        elif variant % 4 >= 2:
            k = rng.randrange(len(order) + 1)
            order = order[k:] + order[:k]
            if variant % 4 == 3:
                rng.shuffle(order)

    def capacity(n):
        st = bd.strips.get(n, [])
        return sum(len(bd.free_rows(s)) for s in st) - 2 * max(len(st) - 1, 0)

    need = {}
    for n in order:
        k, cap = 0, capacity(n)
        while cap < legs.get(n, 0):
            k += 1
            cap += 5 - (2 if (bd.strips.get(n) or k > 1) else 0)
        need[n] = k
    total = sum(need.values())
    free_total = sum(len(bd.free_strip_cols(b)) for b in 'tb')
    if total > free_total:
        raise ImportError_(f'마디가 많아 보드 한 장에 다 꽂을 수 없습니다(줄 {total}개 필요, {free_total}개 남음).')
    gap = max(1, min(3, (free_total - total) // max(total, 1)))
    block = 'b' if variant % 8 >= 4 else 't'
    for n in order:
        k = need[n]
        if not k:
            continue
        # 이미 자리를 받은 이웃 마디(같은 부품에 달린 마디) 가까이, 같은 블록에 두면 부품이 짧고 곧게 놓입니다
        neigh = [st for c in plan.comps if n in c.posts for m in c.posts
                 if m is not None and m != n and m not in rails for st in bd.strips.get(m, [])]
        if neigh:
            blocks = [st[0] for st in neigh]
            nb = max(set(blocks), key=blocks.count)
            if vn and touches_vn([n]):
                nb = 'b'
            want = sum(st[1] for st in neigh if st[0] == nb) / blocks.count(nb)
            runs = [c for c in range(COLS - k + 1) if all((nb, c + j) not in bd.owner for j in range(k))]
            if runs:
                c0 = min(runs, key=lambda c: (abs(abs(c - want) - 3), c))
                for j in range(k):
                    bd.give(n, (nb, c0 + j))
                continue
        c0 = find_run(block, k, cursor[block])
        if c0 is None:
            block = 'b' if block == 't' else 't'
            c0 = find_run(block, k, cursor[block]) or find_run(block, k, 0)
        if c0 is None:
            frees = [(b, c) for b in 'tb' for c in bd.free_strip_cols(b)]
            for s in frees[:k]:
                bd.give(n, s)
            continue
        for j in range(k):
            bd.give(n, (block, c0 + j))
        cursor[block] = c0 + k - 1 + gap

    # ---------- 구멍 고르기 도우미
    def hpair(s1, s2):
        """같은 블록 두 줄을 가로로 잇는 한 행을 고릅니다(다른 가로 부품과 겹치지 않게)."""
        lo, hi = sorted((s1[1], s2[1]))
        best = None
        for r in set(bd.free_rows(s1)) & set(bd.free_rows(s2)):
            clash = any(not (hi < a or lo > b) for a, b in bd.spans.get((s1[0], r), []))
            key = (clash, abs(r - 2))
            if best is None or key < best[0]:
                best = (key, r)
        if best is None:
            return None
        r = best[1]
        bd.spans.setdefault((s1[0], r), []).append((lo, hi))
        return bd.take(bd.hole(s1[0], r, s1[1])), bd.take(bd.hole(s2[0], r, s2[1]))

    def to_rail(net, strip_or_hole):
        """줄의 구멍(레일 쪽 행) → 레일 구멍. 세로 다리가 다른 다리와 겹치지 않는 열을 고릅니다."""
        if isinstance(strip_or_hole, tuple):
            b, col = strip_or_hole
            rows = bd.free_rows(strip_or_hole)
            if not rows:
                raise ImportError_('레일로 이을 구멍이 모자랍니다.')
            h = bd.take(bd.hole(b, min(rows) if b == 't' else max(rows), col))
        else:
            h = strip_or_hole
            b, col = h[0], int(h.split(':')[1])
        row = bd.rail_row(net, b)
        near = lambda k: (k - 1 in bd.vcols[b]) or (k + 1 in bd.vcols[b])
        for d in sorted(range(COLS), key=lambda k: (abs(k - col) + 2 * near(k), k)):
            if d not in bd.vcols[b] and f'{row}:{d}' not in bd.used:
                bd.vcols[b].update({d, col})
                return h, bd.take(f'{row}:{d}')
        return h, bd.rail_hole(row, col)

    def strip_hole(n, near_col, prefer_block=None, toward_rail=False):
        best = None
        for s in bd.strips.get(n, []):
            rows = bd.free_rows(s)
            if not rows:
                continue
            score = abs(s[1] - near_col) + (0 if prefer_block in (None, s[0]) else 6) \
                + (3 if toward_rail and s[1] in bd.vcols[s[0]] else 0)
            if best is None or score < best[0]:
                best = (score, s, rows)
        if best is None:
            raise ImportError_(f'마디 {n}에 꽂을 구멍이 모자랍니다.')
        _, s, rows = best
        if toward_rail:
            r = min(rows) if s[0] == 't' else max(rows)
        else:
            mid = sorted(rows, key=lambda r: abs(r - 2))
            r = mid[0]
        return bd.take(bd.hole(s[0], r, s[1]))

    # 4. 한 마디의 여러 줄은 점퍼선으로, 레일 마디의 줄은 레일까지 점퍼선으로
    for n, st in list(bd.strips.items()):
        st.sort(key=lambda s: (s[0], s[1]))
        if n in rails:
            for s in st:
                a, b = to_rail(n, s)
                bd.add('wire', a, b, color=RED if rails[n] == 'vp' else ('#151b28' if rails[n] == 'gnd' else BLUE))
            continue
        for s1, s2 in zip(st, st[1:]):
            pair = hpair(s1, s2) if s1[0] == s2[0] else None
            if pair is None:
                r1, r2 = bd.free_rows(s1), bd.free_rows(s2)
                if not r1 or not r2:
                    raise ImportError_('줄을 이을 구멍이 모자랍니다.')
                pick = lambda rows, s: max(rows) if s[0] == 't' else min(rows)
                pair = (bd.take(bd.hole(s1[0], pick(r1, s1), s1[1])), bd.take(bd.hole(s2[0], pick(r2, s2), s2[1])))
            bd.add('wire', pair[0], pair[1], color=GREEN)

    # 5. 2단자 부품 꽂기
    def col_of(n):
        st = bd.strips.get(n)
        return (sum(s[1] for s in st) / len(st), st[0][0]) if st else (None, None)

    for c in plan.comps:
        if c.kind in IC_KINDS or c.kind in THREE_PIN:
            continue
        n1, n2 = c.posts
        holes = None
        if n1 not in rails and n2 not in rails:
            opts = [(abs(s1[1] - s2[1]), s1, s2) for s1 in bd.strips[n1] for s2 in bd.strips[n2]
                    if s1[0] == s2[0] and bd.free_rows(s1) and bd.free_rows(s2)]
            for _, s1, s2 in sorted(opts):
                holes = hpair(s1, s2)
                if holes:
                    break
            if holes is None:
                c1, b1 = col_of(n2)
                h1 = strip_hole(n1, c1 or 0)
                c2, _ = col_of(n1)
                holes = (h1, strip_hole(n2, c2 or 0, prefer_block=h1[0]))
        elif n1 in rails and n2 in rails:
            col = 2 + (len(bd.parts) * 3) % 24
            holes = (bd.rail_hole(bd.rail_row(n1, 't'), col), bd.rail_hole(bd.rail_row(n2, 't'), col))
        else:
            sn, rn = (n2, n1) if n1 in rails else (n1, n2)
            h = strip_hole(sn, col_of(sn)[0] or 0, toward_rail=True)
            h, rh = to_rail(rn, h)
            holes = (rh, h) if n1 in rails else (h, rh)
        kw = {k: v for k, v in c.props.items() if k in ('value', 'color', 'closed', 'pos', 'v0', 'light')}
        if 'v0' in kw:
            kw['v0'] = max(min(kw['v0'], 1000.0), -1000.0)
        kw['rating'] = {'capacitor': 50.0}.get(c.kind, 0.25)
        if c.kind == 'capacitor':
            kw['value'] = min(max(kw.get('value', 1e-6), 1e-12), 1.0)
        bd.add(c.kind, holes[0], holes[1], **kw)
    for c, holes in zip(three, three_holes):
        kw = {k: v for k, v in c.props.items() if k in ('value', 'closed', 'pos', 'light')}
        kw['rating'] = {'pot': 0.5}.get(c.kind, 0.625)
        bd.add(c.kind, holes[0], holes[1], holes[2], **kw)
    for c, anchor in ic_parts:
        bd.add(c.kind, anchor, dip_pins(anchor)[7])

    # 6. 장비 리드와 프로브
    inst = default_instruments()
    leads = inst['leads']

    def lead_hole(n, side='t'):
        if n in rails:
            row = 'r0' if rails[n] == 'vp' and bd.vn else (TOP_RAIL if side == 't' else BOT_RAIL)[rails[n]]
            return bd.rail_hole(row, 0)
        return strip_hole(n, 0)

    if plan.ch1:
        pos, neg, v = plan.ch1
        leads['p:1+'] = lead_hole(pos)
        leads['p:1-'] = lead_hole(neg)
        inst['psu']['ch1'].update(voltage=round(v, 3), limit=0.5, on=True)
    if plan.ch2:
        pos, neg, v = plan.ch2
        leads['p:2+'] = lead_hole(pos, 'b')
        leads['p:2-'] = lead_hole(neg, 'b')
        inst['psu']['ch2'].update(voltage=round(v, 3), limit=0.5, on=True)
    if plan.fg:
        pos, neg, cfg = plan.fg
        leads['g:+'] = lead_hole(pos)
        leads['g:-'] = lead_hole(neg)
        inst['fg'].update(cfg)
    if not plan.ch1 and not plan.fg:
        leads['p:1-'] = lead_hole(plan.ground)            # 스코프 기준을 회로 접지에
    probes = ([plan.fg[0]] if plan.fg else []) + [n for n in plan.probes if not plan.fg or n != plan.fg[0]]
    for ch, n in zip(('ch1', 'ch2'), probes[:2]):
        inst['scope'][ch] = lead_hole(n)

    # 7. 위·아래 레일을 함께 쓰면 오른쪽 끝에서 이어 줍니다
    rows_used = {h.split(':')[0] for h in bd.used if h.startswith('r')}
    rows_used |= {h.split(':')[0] for h in list(leads.values()) + list(inst['scope'].values()) if h and h.startswith('r')}
    for top, bot, col in (('r1', 'r3', COLS - 1), ('r0', 'r2', COLS - 2)):
        if top == 'r0' and bd.vn:
            continue
        if top in rows_used and bot in rows_used:
            bd.add('wire', bd.rail_hole(top, col), bd.rail_hole(bot, col), color=RED if top == 'r0' else '#151b28')
    return bd.parts, inst


def _xy(h):
    side, col = h.split(':')
    x = 96 + int(col) * 27
    if side[0] == 'r':
        return x, [90, 116, 504, 530][int(side[1])]
    return x, (180 if side[0] == 't' else 336) + int(side[1]) * 26


def board_tangle(parts):
    """보드 배치 점수: 다리·점퍼선끼리 엇갈림, IC 몸체를 덮는 부품, 전체 길이."""
    segs, ics = [], []
    for p in parts:
        if p.kind in IC_KINDS:
            x, _ = _xy(p.a)
            ics.append((x - 11, 290, x + 92, 330))
            continue
        a, b = _xy(p.a), _xy(p.b)
        segs.append((a, b, p.id))
        if p.kind in THREE_PIN and p.c:
            m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            segs.append((m, _xy(p.c), p.id))

    def cross(s1, s2):
        (p1, p2), (p3, p4) = s1, s2
        def o(a, b, c):
            v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            return (v > 1e-9) - (v < -1e-9)
        if {p1, p2} & {p3, p4}:
            return False
        o1, o2, o3, o4 = o(p1, p2, p3), o(p1, p2, p4), o(p3, p4, p1), o(p3, p4, p2)
        if o1 == o2 == o3 == o4 == 0:          # 한 줄 위에 겹침
            ax = sorted((p1[0], p2[0])); bx = sorted((p3[0], p4[0]))
            ay = sorted((p1[1], p2[1])); by = sorted((p3[1], p4[1]))
            return ax[0] < bx[1] and bx[0] < ax[1] or ay[0] < by[1] and by[0] < ay[1]
        return o1 != o2 and o3 != o4
    n = 0
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            if segs[i][2] != segs[j][2] and cross(segs[i][:2], segs[j][:2]):
                n += 1
    over = 0
    for (a, b, _pid) in segs:
        for x0, y0, x1, y1 in ics:
            if min(a[1], b[1]) < y0 and max(a[1], b[1]) > y1 and x0 < (a[0] + b[0]) / 2 < x1:
                over += 1
    length = sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b, _ in segs)
    # 값 표시가 붙는 부품(저항·커패시터 …)이 이웃한 열에 나란히 서면 글자가 겹칩니다
    crowd = 0
    bodies = []
    for p in parts:
        if p.kind in ('wire',) or p.kind in IC_KINDS or p.kind in THREE_PIN:
            continue
        (x1, y1), (x2, y2) = _xy(p.a), _xy(p.b)
        bodies.append(((x1 + x2) / 2, (y1 + y2) / 2, abs(y1 - y2) > abs(x1 - x2)))
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            (ax, ay, av), (bx, by, bv) = bodies[i], bodies[j]
            if abs(ax - bx) < 40 and abs(ay - by) < 40:
                crowd += 1
    return n * 10 + over * 8 + crowd * 6 + length * 0.02


def place_best(plan, tries=24):
    """여러 배치안 가운데 연결이 맞고 가장 덜 꼬인 것을 고릅니다."""
    best = None
    for v in range(tries):
        try:
            parts, inst = place(plan, v)
        except ImportError_:
            continue
        if verify(plan, parts, inst):
            continue
        sc = board_tangle(parts)
        if best is None or sc < best[0] - 1e-9:
            best = (sc, parts, inst)
    if best is None:
        return place(plan)
    return best[1], best[2]


# ---------------------------------------------------------------- 검증
def verify(plan, parts, inst):
    """보드 위 연결이 원래 넷리스트와 1:1인지 확인합니다. 문제 목록을 돌려줍니다."""
    nm = net_map(parts, inst['leads'])
    problems = []
    seen = {}
    by_kind = {}
    for p in parts:
        if p.kind != 'wire':
            by_kind.setdefault(p.kind, []).append(p)
    used = {k: 0 for k in by_kind}
    for c in plan.comps:
        lst = by_kind.get(c.kind, [])
        if used.get(c.kind, 0) >= len(lst):
            problems.append(f'{c.kind} 부품이 보드에 없습니다.')
            continue
        p = lst[used[c.kind]]
        used[c.kind] += 1
        for n, h in zip(c.posts, p.pins()):
            if n is None:
                continue
            b = nm[h]
            if seen.setdefault(n, b) != b:
                problems.append(f'마디 {n}이 보드에서 둘로 나뉘었습니다.')
    rev = {}
    for n, b in seen.items():
        if rev.setdefault(b, n) != n:
            problems.append(f'마디 {rev[b]}와 {n}가 보드에서 이어져 버렸습니다.')
    for key, src in (('1', plan.ch1), ('2', plan.ch2)):
        if src:
            for n, t in zip(src[:2], (f'p:{key}+', f'p:{key}-')):
                if n in seen and seen[n] != nm[t]:
                    problems.append(f'전원 CH{key} 리드가 엉뚱한 마디에 물렸습니다.')
    if plan.fg:
        for n, t in zip(plan.fg[:2], ('g:+', 'g:-')):
            if n in seen and seen[n] != nm[t]:
                problems.append('함수 발생기 리드가 엉뚱한 마디에 물렸습니다.')
    return problems


def import_falstad(text):
    """Falstad 회로 → (부품, 장비 설정, 알림 목록)."""
    nl = parse_falstad(text)
    if not nl.comps:
        raise ImportError_('부품이 없는 회로입니다.')
    plan = make_plan(nl)
    parts, inst = place_best(plan)
    problems = verify(plan, parts, inst)
    if problems:
        raise ImportError_('배치 검증 실패: ' + '; '.join(problems[:3]))
    return parts, inst, plan.notes
