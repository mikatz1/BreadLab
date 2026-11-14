"""BreadLab 회로 해석 모듈 (Qt 비의존).

전선과 브레드보드 내부 연결은 하나의 노드로 합친 뒤, 노드 전압법 + Newton 반복으로 풉니다.
- 커패시터: 후진 오일러(backward Euler)
- 다이오드·LED: Vf + 직렬 저항 모델(꺾임점을 수 mV 폭으로 완화)
- NPN: 단순화한 β 모델
- 전원 공급기: 2채널, 출력 단자는 서로 절연(플로팅). 채널마다 CV/CC 자동 전환
- 함수 발생기: 50 Ω 출력 임피던스의 전압원
- 오실로스코프: 프로브 입력 저항 10 MΩ, 접지는 전원 CH1 − 단자 기준
SPICE 모델이 아닌 교육용 근사입니다.
"""
from dataclasses import dataclass, asdict, field
import math
import re

import numpy as np

# ---------------------------------------------------------------- 구멍과 단자
COLS = 30
HOLES = [f'r{r}:{c}' for r in range(4) for c in range(COLS)] + [
    f'{s}{r}:{c}' for s in ('t', 'b') for r in range(5) for c in range(COLS)]
TERMINALS = ['p:1+', 'p:1-', 'p:2+', 'p:2-', 'g:+', 'g:-']
TERMINAL_NAMES = {'p:1+': 'CH1 +', 'p:1-': 'CH1 −', 'p:2+': 'CH2 +', 'p:2-': 'CH2 −',
                  'g:+': '함수 발생기 출력', 'g:-': '함수 발생기 COM'}
ALL_HOLES = HOLES + TERMINALS
BOARD_SET = frozenset(HOLES)
TERMINAL_SET = frozenset(TERMINALS)
HOLE_SET = frozenset(ALL_HOLES)
REFERENCE = 'p:1-'    # 0 V 기준(오실로스코프 접지)
# 벤치 장비의 공통 접지: CH1 −와 함수 발생기 COM은 장비 안에서 이어져 있습니다. CH2는 절연(직렬 연결용).
COMMON_GROUND = (('p:1-', 'g:-'),)

# ---------------------------------------------------------------- 부품
KINDS = ('wire', 'resistor', 'ldr', 'capacitor', 'led', 'diode', 'switch', 'npn',
         'pot', 'inductor', 'zener', 'pnp', 'nmos', 'spdt', 'battery', 'opamp', 'timer555')
NAMES = {'wire': '점퍼선', 'resistor': '저항', 'ldr': '광저항(LDR)', 'capacitor': '커패시터',
         'led': 'LED', 'diode': '다이오드', 'switch': '스위치', 'npn': 'NPN 트랜지스터',
         'pot': '가변저항', 'inductor': '인덕터(코일)', 'zener': '제너 다이오드', 'pnp': 'PNP 트랜지스터',
         'nmos': 'N채널 MOSFET', 'spdt': '전환 스위치', 'battery': '건전지', 'opamp': '연산 증폭기(741)',
         'timer555': '555 타이머'}
PREFIX = {'wire': 'W', 'resistor': 'R', 'ldr': 'LDR', 'capacitor': 'C',
          'led': 'LED', 'diode': 'D', 'switch': 'SW', 'npn': 'Q',
          'pot': 'VR', 'inductor': 'L', 'zener': 'ZD', 'pnp': 'Q', 'nmos': 'M', 'spdt': 'SW', 'battery': 'B',
          'opamp': 'U', 'timer555': 'U'}
THREE_PIN = ('npn', 'pnp', 'nmos', 'pot', 'spdt')
IC_KINDS = ('opamp', 'timer555')
# 다리 이름(설치 순서). IC는 1번 핀부터 반시계 방향.
PIN_NAMES = {'npn': ('C', 'B', 'E'), 'pnp': ('C', 'B', 'E'), 'nmos': ('D', 'G', 'S'),
             'pot': ('1', 'W', '3'), 'spdt': ('A', 'COM', 'B'),
             'opamp': ('NC', 'IN−', 'IN+', 'V−', 'NC', 'OUT', 'V+', 'NC'),
             'timer555': ('GND', 'TRIG', 'OUT', 'RESET', 'CTRL', 'THR', 'DIS', 'VCC')}

RED, YELLOW, GREEN, BLUE, WHITE, BLACK = '#ef5350', '#fdd835', '#66bb6a', '#42a5f5', '#ffffff', '#151b28'
COLOR_NAMES = {RED: '빨강', YELLOW: '노랑', GREEN: '초록', BLUE: '파랑', WHITE: '하양', BLACK: '검정'}
LED_VF = {RED: 1.9, YELLOW: 2.0, GREEN: 2.2, BLUE: 2.9, WHITE: 3.0}

VALUE_RANGE = {'capacitor': (1e-12, 1.0), 'npn': (10.0, 1000.0), 'pnp': (10.0, 1000.0),
               'pot': (10.0, 1e7), 'inductor': (1e-7, 10.0), 'zener': (1.0, 50.0), 'nmos': (0.5, 5.0),
               'battery': (0.1, 30.0)}
DEFAULT_VALUE_RANGE = (0.01, 1e9)
RATING_RANGE = {'capacitor': (1.0, 100.0)}
DEFAULT_RATING_RANGE = (0.001, 100.0)
MAX_PARTS = 500

# ---------------------------------------------------------------- 장비
PSU_MAX_V, PSU_MAX_I = 30.0, 5.0
FG_WAVES = {'sine': '사인파', 'square': '사각파', 'triangle': '삼각파', 'ramp': '톱니파', 'dc': 'DC'}
FG_MIN_F, FG_MAX_F = 0.1, 20000.0
FG_MAX_VPP, FG_MAX_OFFSET = 20.0, 10.0
FG_R = 50.0
SCOPE_R = 10e6

# ---------------------------------------------------------------- 수치 상수
GMIN = 1e-12
LEAK = 1e-10
KNEE = 0.005
OPEN_R = 1e12
G_ON = 1e4            # CV 채널 내부 컨덕턴스(0.1 mΩ)
G_OFF = 1e-9          # 꺼진 채널·CC 채널의 병렬 누설
R_TIE = 1e9           # 서로 절연된 출력 단자를 기준에 약하게 묶어 둠
MAX_NEWTON = 40
ZENER_R = 2.0         # 제너 항복 영역의 동저항
BATTERY_R = 0.1       # 건전지 내부 저항
MOS_K = 0.1           # MOSFET 전류 계수(A/V²)
OPAMP_GAIN = 1e5
OPAMP_RO = 50.0
OPAMP_HEAD = 1.5      # 출력이 전원 레일에서 모자라는 전압
T555_RO = 10.0
C_PAR_ROUGH = 1e-6   # 빠른 계산일 때 노드 기생 용량(1 µF): 트랜지스터 전환이 빨리 풀립니다
C_PAR = 1e-8         # 노드마다 붙는 기생 용량(10 nF). 트랜지스터가 상태를 뒤집는 순간을 연속적으로 만듭니다.
STUCK_LIMIT = 3
LINE_SEARCH = 10
JUNCTION_LIMIT = 0.0  # 접합 전압이 Newton 한 번에 움직일 수 있는 최대값(V, 0이면 쓰지 않음)
STEP_LIMIT = 2.0      # Newton 한 번에 움직일 수 있는 최대 전압
MAX_SPLIT = 9         # 수렴하지 않을 때 시간 간격을 4등분하는 최대 횟수(5 ms → 20 ns)


def default_instruments():
    return {
        'psu': {'ch1': {'voltage': 5.0, 'limit': 0.1, 'on': False},
                'ch2': {'voltage': 5.0, 'limit': 0.1, 'on': False}},
        'fg': {'wave': 'sine', 'freq': 50.0, 'vpp': 2.0, 'offset': 0.0, 'duty': 50.0, 'on': False},
        'scope': {'ch1': None, 'ch2': None},
        'leads': {t: None for t in TERMINALS},
    }


def strip(h):
    """구멍 → 내부 연결 단위(세로 5칸 줄, 가로 레일). 장비 단자는 그 자체."""
    if h in TERMINAL_SET:
        return h
    side, col = h.split(':')
    return side if side[0] == 'r' else side[0] + ':' + col


def format_si(value, unit='Ω', digits=4):
    if value == 0 or (unit == 'A' and abs(value) < 1e-9):
        return f'0 {unit}'
    for scale, prefix in ((1e9, 'G'), (1e6, 'M'), (1e3, 'k'), (1, ''), (1e-3, 'm'),
                          (1e-6, 'µ'), (1e-9, 'n'), (1e-12, 'p')):
        if abs(value) >= scale:
            return f'{value / scale:.{digits}g} {prefix}{unit}'
    return f'{value:.3g} {unit}'


_NUM = r'([+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)'


def parse_resistance(text):
    t = text.strip().replace('Ω', '').replace('ohm', '').replace('옴', '').strip()
    m = re.fullmatch(_NUM + r'\s*([kKMGm]?)', t)
    if not m:
        raise ValueError('저항은 330, 1k, 4.7k, 1M처럼 입력하십시오. M은 메가, m은 밀리입니다.')
    x = float(m[1]) * {'': 1, 'k': 1e3, 'K': 1e3, 'M': 1e6, 'G': 1e9, 'm': 1e-3}[m[2]]
    if not math.isfinite(x) or not 0.01 <= x <= 1e9:
        raise ValueError('저항은 0.01 Ω에서 1 GΩ 사이로 입력하십시오.')
    return x


def parse_capacitance(text):
    t = text.strip().replace('µ', 'u').replace('μ', 'u')
    t = re.sub(r'[fF]$', '', t).strip()
    m = re.fullmatch(_NUM + r'\s*([munp]?)', t)
    if not m:
        raise ValueError('용량은 100u, 4.7u, 10n, 0.001처럼 입력하십시오.')
    x = float(m[1]) * {'': 1, 'm': 1e-3, 'u': 1e-6, 'n': 1e-9, 'p': 1e-12}[m[2]]
    if not math.isfinite(x) or not 1e-12 <= x <= 1.0:
        raise ValueError('용량은 1 pF에서 1 F 사이로 입력하십시오.')
    return x


def parse_beta(text):
    try:
        x = float(text.strip())
    except ValueError:
        raise ValueError('β(전류 증폭률)는 숫자로 입력하십시오. 예: 100') from None
    if not math.isfinite(x) or not 10 <= x <= 1000:
        raise ValueError('β는 10에서 1000 사이로 입력하십시오.')
    return x


_SI = {'': 1, 'k': 1e3, 'K': 1e3, 'M': 1e6, 'm': 1e-3, 'u': 1e-6, 'µ': 1e-6, 'n': 1e-9, 'p': 1e-12}


def parse_si(text, unit, lo, hi, example, name):
    """'10m', '4.7u', '9' 같은 값을 읽습니다. unit 글자(H, V …)는 붙여도 됩니다."""
    t = text.strip().replace('μ', 'u').replace('µ', 'u')
    if t.endswith(unit):
        t = t[:-len(unit)].strip()
    m = re.fullmatch(_NUM + r'\s*([kKMmunp]?)', t)
    if not m:
        raise ValueError(f'{name}은(는) {example}처럼 입력하십시오.')
    x = float(m[1]) * _SI[m[2]]
    if not math.isfinite(x) or not lo <= x <= hi:
        raise ValueError(f'{name}은(는) {format_si(lo, unit)}에서 {format_si(hi, unit)} 사이로 입력하십시오.')
    return x


PARSERS = {
    'resistor': lambda t: parse_resistance(t),
    'pot': lambda t: parse_si(t.replace('Ω', ''), 'Ω', 10, 1e7, '1k, 10k, 100k', '가변저항 값'),
    'capacitor': lambda t: parse_capacitance(t),
    'inductor': lambda t: parse_si(t, 'H', 1e-7, 10, '10m, 100u, 1', '인덕턴스'),
    'zener': lambda t: parse_si(t, 'V', 1, 50, '5.1, 12', '제너 전압'),
    'battery': lambda t: parse_si(t, 'V', 0.1, 30, '1.5, 9', '건전지 전압'),
    'npn': lambda t: parse_beta(t),
    'pnp': lambda t: parse_beta(t),
    'nmos': lambda t: parse_si(t, 'V', 0.5, 5, '2, 2.1', '문턱 전압'),
}


def resistor_bands(ohm):
    """4색띠 저항의 (첫째 숫자, 둘째 숫자, 승수 지수). 색띠로 나타낼 수 없으면 None."""
    if not ohm > 0:
        return None
    exp = math.floor(math.log10(ohm) + 1e-9)
    sig = round(ohm / 10 ** (exp - 1))
    if sig >= 100:
        sig = round(sig / 10)
        exp += 1
    mult = exp - 1
    if not -2 <= mult <= 9:
        return None
    return sig // 10, sig % 10, mult


@dataclass
class Part:
    id: int
    kind: str
    a: str
    b: str
    value: float = 1000.0
    color: str = RED
    rating: float = 0.25
    closed: bool = True
    light: float = 50.0
    c: str | None = None
    pos: float = 50.0        # 가변저항 와이퍼 위치(%)
    v0: float = 0.0          # 처음 상태: 커패시터 전압(V) 또는 인덕터 전류(A)

    def resistance(self):
        if self.kind == 'ldr':
            return 1e6 * 1e-4 ** (self.light / 100)
        if self.kind == 'switch':
            return 0.05 if self.closed else OPEN_R
        return self.value

    def vf(self):
        return LED_VF.get(self.color, 1.9) if self.kind == 'led' else 0.7

    def pins(self):
        if self.kind in IC_KINDS:
            return dip_pins(self.a)
        return (self.a, self.b, self.c) if self.kind in THREE_PIN else (self.a, self.b)


def dip_pins(anchor):
    """DIP-8 IC: 1번 핀 구멍(F열, 'b0:x') → 1~8번 핀 구멍. 가운데 홈을 걸쳐 꽂습니다."""
    if isinstance(anchor, str) and anchor.startswith('b0:'):
        x = int(anchor[3:])
        if 0 <= x <= COLS - 4:
            return tuple([f'b0:{x + i}' for i in range(4)] + [f't4:{x + 3 - i}' for i in range(4)])
    return (anchor,)


def ic_anchor(h):
    """아무 구멍 → 그 열에 꽂을 IC의 1번 핀 구멍."""
    x = min(max(int(h.split(':')[1]), 0), COLS - 4)
    return f'b0:{x}'


def designators(parts):
    """부품 ID → 회로 기호(R1, C2, Q1 …). 종류별로 ID 순서대로 번호를 붙입니다."""
    count, out = {}, {}
    for p in sorted(parts, key=lambda q: q.id):
        k = PREFIX[p.kind]                      # NPN·PNP는 함께 Q1, Q2 …
        count[k] = count.get(k, 0) + 1
        out[p.id] = f'{k}{count[k]}'
    return out


class DSU:
    def __init__(self, xs):
        self.p = {x: x for x in xs}

    def find(self, x):
        root = x
        while self.p[root] != root:
            root = self.p[root]
        while self.p[x] != root:
            self.p[x], x = root, self.p[x]
        return root

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def _node_fn(parts, leads=None):
    d = DSU({strip(h) for h in ALL_HOLES})
    for a, b in COMMON_GROUND:
        d.union(a, b)
    for term, hole in (leads or {}).items():
        if hole:
            d.union(strip(term), strip(hole))
    for p in parts:
        if p.kind == 'wire':
            d.union(strip(p.a), strip(p.b))
    return lambda h: d.find(strip(h))


def net_map(parts, leads=None):
    """구멍 → 전기적 노드 이름. 값이 같으면 점퍼선·리드·보드 내부 연결로 이어진 구멍입니다."""
    node = _node_fn(parts, leads)
    return {h: node(h) for h in ALL_HOLES}


# ---------------------------------------------------------------- 파일 검증
def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _check(cond, msg):
    if not cond:
        raise ValueError(msg)


def _validate_instruments(raw):
    inst = default_instruments()
    if raw is None:
        return inst
    _check(isinstance(raw, dict), '장비 설정 형식이 잘못되었습니다.')
    psu = raw.get('psu', {})
    _check(isinstance(psu, dict), '전원 공급기 설정 형식이 잘못되었습니다.')
    for ch in ('ch1', 'ch2'):
        c = psu.get(ch, {})
        _check(isinstance(c, dict), '전원 공급기 설정 형식이 잘못되었습니다.')
        out = inst['psu'][ch]
        out.update({k: c[k] for k in ('voltage', 'limit', 'on') if k in c})
        _check(_num(out['voltage']) and 0 <= out['voltage'] <= PSU_MAX_V, '전원 전압 설정이 범위를 벗어났습니다.')
        _check(_num(out['limit']) and 0.001 <= out['limit'] <= PSU_MAX_I, '전류 제한 설정이 범위를 벗어났습니다.')
        _check(isinstance(out['on'], bool), '전원 출력 설정 형식이 잘못되었습니다.')
    fg = raw.get('fg', {})
    _check(isinstance(fg, dict), '함수 발생기 설정 형식이 잘못되었습니다.')
    inst['fg'].update({k: fg[k] for k in inst['fg'] if k in fg})
    f = inst['fg']
    _check(f['wave'] in FG_WAVES, '함수 발생기 파형이 잘못되었습니다.')
    _check(_num(f['freq']) and FG_MIN_F <= f['freq'] <= FG_MAX_F, '함수 발생기 주파수가 범위를 벗어났습니다.')
    _check(_num(f['vpp']) and 0 <= f['vpp'] <= FG_MAX_VPP, '함수 발생기 진폭이 범위를 벗어났습니다.')
    _check(_num(f['offset']) and abs(f['offset']) <= FG_MAX_OFFSET, '함수 발생기 오프셋이 범위를 벗어났습니다.')
    _check(_num(f['duty']) and 1 <= f['duty'] <= 99, '함수 발생기 듀티가 범위를 벗어났습니다.')
    _check(isinstance(f['on'], bool), '함수 발생기 출력 설정 형식이 잘못되었습니다.')
    sc = raw.get('scope', {})
    _check(isinstance(sc, dict), '오실로스코프 설정 형식이 잘못되었습니다.')
    for ch in ('ch1', 'ch2'):
        h = sc.get(ch)
        _check(h is None or h in BOARD_SET, '오실로스코프 프로브 위치가 잘못되었습니다.')
        inst['scope'][ch] = h
    leads = raw.get('leads', {})
    _check(isinstance(leads, dict), '장비 리드 설정 형식이 잘못되었습니다.')
    for term, h in leads.items():
        _check(term in TERMINAL_SET and (h is None or h in BOARD_SET), '장비 리드 연결 위치가 잘못되었습니다.')
        inst['leads'][term] = h
    return inst


def _wires_to_leads(parts, leads):
    """장비 단자에 꽂힌 점퍼선(예전 형식)을 리드 연결로 바꿉니다."""
    out, extra = [], []
    for p in parts:
        ends = [h for h in (p.a, p.b) if h in TERMINAL_SET]
        if not ends:
            out.append(p)
            continue
        if len(ends) == 2:   # 단자끼리 바로 이은 선: 한쪽이 보드에 물려 있으면 다른 쪽도 같은 구멍에
            a, b = ends
            hole = leads[a] or leads[b]
            _check(hole is not None, '장비 단자끼리만 이어진 선은 지원하지 않습니다. 보드 구멍을 거쳐 연결하십시오.')
            leads[a] = leads[a] or hole
            leads[b] = leads[b] or hole
            continue
        term = ends[0]
        hole = p.b if p.a == term else p.a
        if leads[term] is None:
            leads[term] = hole
        elif leads[term] != hole:
            extra.append((leads[term], hole, p))
    next_id = max((p.id for p in parts), default=0) + 1
    for a, b, p in extra:   # 한 단자에 선이 여러 개면 보드 위 점퍼선으로 이어 둡니다
        out.append(Part(next_id, 'wire', a, b, color=p.color))
        next_id += 1
    return out


def validate_document(data):
    """회로 파일을 검증해 (부품 목록, 장비 설정)을 돌려줍니다.

    장비 단자는 리드 집게로 보드 구멍에 물립니다(instruments['leads']).
    버전 1 파일의 +/GND 구멍 지정과, 장비 단자에 꽂힌 점퍼선은 리드 연결로 바꿔 읽습니다.
    """
    _check(isinstance(data, dict) and data.get('version') in (1, 2),
           'BreadLab 회로 파일이 아니거나 지원하지 않는 버전입니다.')
    raw = data.get('parts')
    _check(isinstance(raw, list) and len(raw) <= MAX_PARTS, f'부품 목록이 없거나 {MAX_PARTS}개를 넘습니다.')

    parts, ids = [], set()
    for item in raw:
        _check(isinstance(item, dict), '부품 데이터 형식이 잘못되었습니다.')
        try:
            p = Part(**item)
        except TypeError:
            raise ValueError('알 수 없는 부품 속성이 들어 있습니다.') from None
        _check(type(p.id) is int and p.id >= 1 and p.id not in ids, '부품 ID가 잘못되었거나 중복되었습니다.')
        ids.add(p.id)
        _check(p.kind in KINDS, f'알 수 없는 부품 종류입니다: {p.kind}')
        if p.kind not in THREE_PIN:
            p.c = None
        if p.kind in IC_KINDS:
            _check(len(dip_pins(p.a)) == 8, f'부품 #{p.id}: IC는 F열에서 가운데 홈을 걸쳐 꽂아야 합니다.')
            p.b = dip_pins(p.a)[7]
        pins = p.pins()
        _check(all(isinstance(h, str) and h in HOLE_SET for h in pins) and len(set(pins)) == len(pins),
               f'부품 #{p.id}의 연결 구멍이 잘못되었습니다.')
        _check(p.kind == 'wire' or not any(h in TERMINAL_SET for h in pins),
               f'부품 #{p.id}: 장비 단자에는 부품을 꽂을 수 없습니다.')
        _check(p.color in COLOR_NAMES, f'부품 #{p.id}의 색상 값이 잘못되었습니다.')
        _check(all(_num(x) for x in (p.value, p.rating, p.light, p.pos, p.v0)) and isinstance(p.closed, bool)
               and 0 <= p.pos <= 100 and abs(p.v0) <= 1000,
               f'부품 #{p.id}의 수치가 잘못되었습니다.')
        lo, hi = VALUE_RANGE.get(p.kind, DEFAULT_VALUE_RANGE)
        rlo, rhi = RATING_RANGE.get(p.kind, DEFAULT_RATING_RANGE)
        _check(lo <= p.value <= hi and rlo <= p.rating <= rhi and 0 <= p.light <= 100,
               f'부품 #{p.id}의 수치가 허용 범위를 벗어났습니다.')
        p.value, p.rating, p.light, p.pos = float(p.value), float(p.rating), float(p.light), float(p.pos)
        parts.append(p)

    if data['version'] == 1:
        for key in ('positive', 'ground'):
            _check(data.get(key) is None or data[key] in BOARD_SET, '전원 연결 위치가 잘못되었습니다.')
        for key, low, high in (('voltage', 0, 30), ('limit', 0.001, 5)):
            _check(_num(data.get(key)) and low <= data[key] <= high, '전원 공급기 설정값이 범위를 벗어났습니다.')
        inst = default_instruments()
        inst['psu']['ch1'].update(voltage=float(data['voltage']), limit=float(data['limit']))
        inst['leads'].update({'p:1+': data.get('positive'), 'p:1-': data.get('ground')})
    else:
        inst = _validate_instruments(data.get('instruments'))
    parts = _wires_to_leads(parts, inst['leads'])
    return parts, inst


def make_document(parts, inst):
    return {'version': 2, 'parts': [asdict(p) for p in parts], 'instruments': inst}


# ---------------------------------------------------------------- 소자 모델
def _softplus(z):
    return max(z, 0.0) + math.log1p(math.exp(-abs(z)))


def _sigmoid(z):
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


def _two_terminal(p, v, h, vprev):
    """a→b 방향 전류와 그 미분(컨덕턴스)."""
    k = p.kind
    if k in ('led', 'diode'):
        rs = 10.0 if k == 'led' else 1.0
        z = (v - p.vf()) / KNEE
        return LEAK * v + KNEE * _softplus(z) / rs, LEAK + _sigmoid(z) / rs
    if k == 'zener':
        z = (v - 0.7) / KNEE
        zr = (-v - p.value) / KNEE
        return (LEAK * v + KNEE * _softplus(z) - KNEE * _softplus(zr) / ZENER_R,
                LEAK + _sigmoid(z) + _sigmoid(zr) / ZENER_R)
    if k == 'capacitor':
        g = p.value / h
        return g * (v - vprev), g
    if k == 'inductor':                    # 후진 오일러: i = i_prev + (h/L)·v. 직류에서는 1 mΩ 도선
        g = min(h / p.value, 1e3)
        return vprev + g * v, g
    if k == 'battery':                     # a가 +. 내부 저항 0.1 Ω
        return (v - p.value) / BATTERY_R, 1 / BATTERY_R
    g = 1.0 / p.resistance()
    return g * v, g


def _npn(beta, vc, vb, ve):
    """(ib, ic, dib/dvbe, dic/dvbe, dic/dvce)."""
    vbe, vce = vb - ve, vc - ve
    # 베이스–이미터 접합: 0.65 V 근처에서 30 mV 폭으로 꺾이고, 그 위로는 약 20 Ω(실물처럼 V_BE ≈ 0.7 V)
    z = (vbe - 0.65) / 0.03
    ib = 0.05 * 0.03 * _softplus(z) + 1e-8 * vbe
    dib = 0.05 * _sigmoid(z) + 1e-8
    # 포화 영역: sat = 1 - exp(-3·max(V_CE, 0)). max를 부드럽게(폭 50 mV) 바꿔 기울기가 끊기지 않게 합니다.
    k = 20.0
    pos = _softplus(k * vce) / k
    e = math.exp(-3.0 * pos)
    sat, dsat = 1 - e, 3 * e * _sigmoid(k * vce)
    ic = beta * ib * sat + 1e-8 * vce
    return ib, ic, dib, beta * sat * dib, beta * ib * dsat + 1e-8


def _smooth_pos(x, eps):
    """eps·softplus(x/eps)와 그 미분. s(x) − s(−x) = x 이므로 전류를 두 전원 핀에 나눌 때 씁니다."""
    return eps * _softplus(x / eps), _sigmoid(x / eps)


def _nmos(vt, vg, vd, vs):
    """N채널 MOSFET (i_D, dI/dvg, dI/dvd, dI/dvs). 제곱 법칙, 드레인·소스는 대칭으로 다룹니다."""
    if vd < vs:
        i, gg, gd, gs = _nmos(vt, vg, vs, vd)
        return -i, -gg, -gs, -gd
    vov, dov = _smooth_pos(vg - vs - vt, 0.05)
    vds = vd - vs
    xp = max(vov - vds, 0.0)
    i = MOS_K * (vov * vov - xp * xp) + 1e-9 * vds
    di_dvov = MOS_K * (2 * vov - 2 * xp)
    di_dvds = MOS_K * 2 * xp + 1e-9
    gg = di_dvov * dov
    return i, gg, di_dvds, -gg - di_dvds


def _diode_iv(v, vf=0.7, rs=1.0):
    z = (v - vf) / KNEE
    return KNEE * _softplus(z) / rs + LEAK * v, _sigmoid(z) / rs + LEAK


def fg_value(fg, t):
    """함수 발생기의 무부하 출력 전압."""
    if fg['wave'] == 'dc':
        return fg['offset']
    a = fg['vpp'] / 2
    ph = (t * fg['freq']) % 1.0
    w = fg['wave']
    if w == 'sine':
        y = math.sin(2 * math.pi * ph)
    elif w == 'square':
        y = 1.0 if ph < fg['duty'] / 100 else -1.0
    elif w == 'triangle':
        y = 4 * ph - 1 if ph < 0.5 else 3 - 4 * ph
    else:
        y = 2 * ph - 1
    return fg['offset'] + a * y


@dataclass
class _Source:
    """두 단자 사이의 전원. mode: 'cv'(전압원), 'cc'(전류원), 'off'(개방), 'fg', 'tie', 'probe'."""
    name: str
    mode: str
    E: float = 0.0
    G: float = 0.0
    I: float = 0.0

    def law(self, v, t, fg):
        """+단자→소스 방향 전류와 미분. v = v(+) - v(−)."""
        if self.mode == 'cv':
            return G_ON * (v - self.E), G_ON
        if self.mode == 'cc':
            return -self.I + G_OFF * v, G_OFF
        if self.mode == 'fg':
            return (v - fg_value(fg, t)) / FG_R, 1 / FG_R
        return self.G * v, self.G


def _res(terms, jac, a, b, g, V):
    i = g * (V[a] - V[b])
    terms += [(a, i), (b, -i)]
    jac += [(a, a, g), (a, b, -g), (b, a, -g), (b, b, g)]


def _driven_output(terms, jac, out, vp, vn, vt, dvt, ro, V):
    """출력 핀을 목표 전압 vt로 끌어당기고(내부 저항 ro), 그 전류를 두 전원 핀에서 가져옵니다.
    dvt: {마디: ∂vt/∂V}."""
    io = (V[out] - vt) / ro                        # 출력 핀 → 소자 안으로
    d_io = {out: 1 / ro}
    for n, d in dvt.items():
        d_io[n] = d_io.get(n, 0.0) - d / ro
    sp, dsp = _smooth_pos(-io, 1e-4)               # V+ 에서 들어와 출력으로 나가는 전류
    sn, dsn = _smooth_pos(io, 1e-4)                # 출력에서 들어와 V− 로 나가는 전류
    terms += [(out, io), (vp, sp), (vn, -sn)]
    for n, d in d_io.items():
        jac += [(out, n, d), (vp, n, -dsp * d), (vn, n, -dsn * d)]
    return io


def _pot(p, ns, V, caps):
    a, w, c = ns
    r = max(p.value, 1.0)
    terms, jac = [], []
    _res(terms, jac, a, w, 1 / max(r * p.pos / 100, 0.5), V)
    _res(terms, jac, w, c, 1 / max(r * (1 - p.pos / 100), 0.5), V)
    return terms, jac


def _spdt(p, ns, V, caps):
    a, com, b = ns
    terms, jac = [], []
    _res(terms, jac, com, a, 20.0 if p.closed else 1 / OPEN_R, V)
    _res(terms, jac, com, b, 1 / OPEN_R if p.closed else 20.0, V)
    return terms, jac


def _mos(p, ns, V, caps):
    D, G, S = ns
    i, gg, gd, gs = _nmos(p.value, V[G], V[D], V[S])
    terms = [(D, i), (S, -i)]
    jac = [(D, G, gg), (D, D, gd), (D, S, gs), (S, G, -gg), (S, D, -gd), (S, S, -gs)]
    ib, gb = _diode_iv(V[S] - V[D])                # 몸체 다이오드(소스 → 드레인)
    terms += [(S, ib), (D, -ib)]
    jac += [(S, S, gb), (S, D, -gb), (D, S, -gb), (D, D, gb)]
    return terms, jac


def _opamp_target(V, inm, inp, vn, vp):
    span = V[vp] - V[vn] - 2 * OPAMP_HEAD
    sw, dsw = _smooth_pos(span, 0.1)
    half = sw / 2 + 1e-6
    mid = (V[vp] + V[vn]) / 2
    u = OPAMP_GAIN * (V[inp] - V[inm])
    th = math.tanh(u / half)
    sech2 = 1 - th * th
    vt = mid + half * th
    dvt_dh = th - (u / half) * sech2
    dvt = {inp: OPAMP_GAIN * sech2}
    dvt[inm] = dvt.get(inm, 0.0) - OPAMP_GAIN * sech2
    dvt[vp] = dvt.get(vp, 0.0) + 0.5 + dvt_dh * dsw / 2
    dvt[vn] = dvt.get(vn, 0.0) + 0.5 - dvt_dh * dsw / 2
    return vt, dvt


def _opamp(p, ns, V, caps):
    _, inm, inp, vn, _, out, vp, _ = ns
    terms, jac = [], []
    _res(terms, jac, vp, vn, 1 / 20e3, V)          # 대기 전류
    vt, dvt = _opamp_target(V, inm, inp, vn, vp)
    _driven_output(terms, jac, out, vp, vn, vt, dvt, OPAMP_RO, V)
    return terms, jac


def _timer_target(p, ns, V, caps):
    gnd, vcc = ns[0], ns[7]
    q = caps.get(('q', p.id), 0)
    hi, dhi = _smooth_pos(V[vcc] - V[gnd] - 1.7, 0.05)
    dvt = {gnd: 1 - q * dhi}
    dvt[vcc] = dvt.get(vcc, 0.0) + q * dhi
    return V[gnd] + q * hi, dvt, q


def _timer(p, ns, V, caps):
    gnd, _trig, out, _rst, ctl, _thr, dis, vcc = ns
    terms, jac = [], []
    _res(terms, jac, vcc, ctl, 1 / 5e3, V)
    _res(terms, jac, ctl, gnd, 1 / 10e3, V)
    vt, dvt, q = _timer_target(p, ns, V, caps)
    _driven_output(terms, jac, out, vcc, gnd, vt, dvt, T555_RO, V)
    _res(terms, jac, dis, gnd, 1e-9 if q else 10.0, V)   # 방전 트랜지스터(출력이 L일 때 켜짐)
    return terms, jac


def timer_update(ns, V, q):
    """555 내부 플립플롭: 한 걸음이 끝날 때 비교기 결과로 상태를 바꿉니다."""
    gnd, trig, _out, rst, ctl, thr, _dis, _vcc = ns
    vc = V[ctl] - V[gnd]
    if V[rst] - V[gnd] < 0.7:
        return 0
    if V[trig] - V[gnd] < vc / 2:
        return 1
    if V[thr] - V[gnd] > vc:
        return 0
    return q


LINEAR_KINDS = frozenset(('resistor', 'ldr', 'switch', 'capacitor', 'inductor', 'battery', 'pot', 'spdt'))
MULTI = {'pot': _pot, 'spdt': _spdt, 'nmos': _mos, 'opamp': _opamp, 'timer555': _timer}


class _Circuit:
    def __init__(self, parts, inst, modes):
        self.node = _node_fn(parts, inst.get('leads'))
        self.inst = inst
        self.c_par = C_PAR
        self.items = [('part', p, tuple(self.node(h) for h in p.pins())) for p in parts if p.kind != 'wire']
        self.ref = self.node(REFERENCE)
        self.channels = {}
        for ch, (pos, neg) in (('ch1', ('p:1+', 'p:1-')), ('ch2', ('p:2+', 'p:2-'))):
            cfg = inst['psu'][ch]
            mode = modes.get(ch, 'cv') if cfg['on'] else 'off'
            s = _Source(ch, mode, E=cfg['voltage'], G=G_OFF, I=cfg['limit'])
            self.channels[ch] = s
            self.items.append(('src', s, (self.node(pos), self.node(neg))))
        fg = inst['fg']
        self.fg = _Source('fg', 'fg' if fg['on'] else 'off', G=G_OFF)
        self.items.append(('src', self.fg, (self.node('g:+'), self.node('g:-'))))
        for term in ('p:2-', 'g:-'):
            if self.node(term) != self.ref:
                self.items.append(('src', _Source('tie', 'tie', G=1 / R_TIE), (self.node(term), self.ref)))
        self.probes = {}
        for ch in ('ch1', 'ch2'):
            h = inst['scope'].get(ch)
            if h:
                self.probes[ch] = self.node(h)
                self.items.append(('src', _Source('probe', 'probe', G=1 / SCOPE_R), (self.node(h), self.ref)))
        nodes = {n for _, _, ns in self.items for n in ns} | {self.ref}
        self.unknown = sorted(nodes - {self.ref})
        for nd in self.unknown:
            self.items.append(('par', None, (nd, self.ref)))
        self.linear = [it for it in self.items if it[0] != 'part' or it[1].kind in LINEAR_KINDS]
        self.nonlinear = [it for it in self.items if it[0] == 'part' and it[1].kind not in LINEAR_KINDS]

    def contrib(self, item, V, h, caps, t):
        typ, obj, ns = item
        if typ == 'part' and obj.kind in MULTI:
            return MULTI[obj.kind](obj, ns, V, caps)
        if typ == 'part' and obj.kind in ('npn', 'pnp'):
            C, B, E = ns
            s = 1 if obj.kind == 'npn' else -1      # PNP는 전압·전류 방향을 뒤집은 NPN
            ib, ic, dib, dic_be, dic_ce = _npn(obj.value, s * V[C], s * V[B], s * V[E])
            ib, ic = s * ib, s * ic
            d_ic = ((C, dic_ce), (B, dic_be), (E, -dic_be - dic_ce))
            d_ib = ((B, dib), (E, -dib))
            jac = [(C, m, v) for m, v in d_ic] + [(E, m, -v) for m, v in d_ic]
            jac += [(B, m, v) for m, v in d_ib] + [(E, m, -v) for m, v in d_ib]
            return ((C, ic), (B, ib), (E, -ic - ib)), jac
        a, b = ns
        if typ == 'par':
            g = self.c_par / h
            return ((a, g * (V[a] - caps.get(('n', a), 0.0))),), ((a, a, g),)
        if typ == 'part':
            i, g = _two_terminal(obj, V[a] - V[b], h, caps.get(obj.id, obj.v0))
        else:
            i, g = obj.law(V[a] - V[b], t, self.inst['fg'])
        return ((a, i), (b, -i)), ((a, a, g), (a, b, -g), (b, a, -g), (b, b, g))

    def newton(self, guess, h, caps, t):
        unknown = self.unknown
        n = len(unknown)
        V = {self.ref: 0.0}
        if n == 0:
            return V
        ix = {k: i for i, k in enumerate(unknown)}
        x = np.array([guess.get(k, 0.0) for k in unknown], dtype=float)

        # 선형 부품(저항·커패시터·전원 …)은 이번 걸음 동안 식이 변하지 않으므로 한 번만 쌓아 둡니다:
        # 전류 = G·v + b. Newton 반복마다 다시 계산하는 것은 다이오드·트랜지스터·IC뿐입니다.
        G = np.eye(n) * GMIN
        b = np.zeros(n)
        V0 = dict.fromkeys(unknown, 0.0)
        V0[self.ref] = 0.0
        for item in self.linear:
            terms, jac = self.contrib(item, V0, h, caps, t)
            for node, i in terms:
                k = ix.get(node)
                if k is not None:
                    b[k] += i
            for r, c, g in jac:
                kr, kc = ix.get(r), ix.get(c)
                if kr is not None and kc is not None:
                    G[kr, kc] += g

        def evaluate(x):
            V.update(zip(unknown, x.tolist()))
            F = G @ x + b
            J = G.copy()
            for item in self.nonlinear:
                terms, jac = self.contrib(item, V, h, caps, t)
                for node, i in terms:
                    k = ix.get(node)
                    if k is not None:
                        F[k] += i
                for r, c, g in jac:
                    kr, kc = ix.get(r), ix.get(c)
                    if kr is not None and kc is not None:
                        J[kr, kc] += g
            return F, J

        pairs = []
        for typ, obj, ns in self.nonlinear:
            if obj.kind in ('npn', 'pnp'):
                pairs.append((ns[1], ns[2]))
            elif obj.kind in ('diode', 'led', 'zener'):
                pairs.append((ns[0], ns[1]))
        junctions = np.array([[ix.get(a, n), ix.get(b, n)] for a, b in pairs], dtype=int) if pairs else None
        F, J = evaluate(x)
        norm = float(F @ F)
        stuck = 0
        tol = getattr(self, 'tol', 1e-10)
        for _ in range(getattr(self, 'max_newton', MAX_NEWTON)):
            if float(np.max(np.abs(F))) < tol:
                break
            if stuck >= STUCK_LIMIT:      # 계속 아주 작은 걸음만 가능하면 빨리 포기하고 시간 간격을 나눕니다
                break
            dx = np.linalg.solve(J, -F)
            big = float(np.max(np.abs(dx)))
            if big > STEP_LIMIT:
                dx *= STEP_LIMIT / big
            if junctions is not None and JUNCTION_LIMIT:                # 접합 전압(베이스–이미터, 다이오드)은 한 번에 조금씩만
                dxe = np.append(dx, 0.0)
                dj = float(np.max(np.abs(dxe[junctions[:, 0]] - dxe[junctions[:, 1]])))
                if dj > JUNCTION_LIMIT:
                    dx *= JUNCTION_LIMIT / dj
            alpha = 1.0
            for _ in range(LINE_SEARCH):
                xt = x + alpha * dx
                Ft, Jt = evaluate(xt)
                nt = float(Ft @ Ft)
                if nt < norm:
                    break
                alpha *= 0.5
            step = alpha * float(np.max(np.abs(dx)))
            stuck = stuck + 1 if alpha < 1 / 32 else 0
            x, F, J, norm = xt, Ft, Jt, nt
            if step < 1e-12:
                break
        if float(np.max(np.abs(F))) > getattr(self, 'accept', 1e-7):
            raise ArithmeticError('계산이 수렴하지 않았습니다.')
        V.update(zip(unknown, x.tolist()))
        return V

    def V_ref(self, V):
        return V.get(self.ref, 0.0)

    def channel_out(self, ch, V, t):
        """채널 출력 (전압, +단자에서 회로로 나가는 전류)."""
        s = self.channels[ch]
        pos, neg = self.node(f'p:{ch[-1]}+'), self.node(f'p:{ch[-1]}-')
        v = V[pos] - V[neg]
        i, _ = s.law(v, t, None) if s.mode != 'fg' else (0.0, 0.0)
        return v, -i


@dataclass
class Simulator:
    """시간 상태(커패시터 전압, 이전 해, CV/CC 상태)를 들고 회로를 한 걸음씩 진행합니다."""
    t: float = 0.0
    caps: dict = field(default_factory=dict)
    guess: dict = field(default_factory=dict)
    modes: dict = field(default_factory=dict)
    rough: bool = False      # 빠른 계산: 허용 오차를 넓히고 반복·시간 나누기를 줄입니다(정밀도 조금 낮음)

    def reset(self):
        self.t = 0.0
        self.caps.clear()
        self.guess.clear()
        self.modes.clear()

    def _solve(self, c, h, t):
        """채널 CV/CC 상태가 맞을 때까지 풀어 봅니다."""
        for _ in range(4):
            V = c.newton(self.guess, h, self.caps, t)
            changed = False
            for ch, s in c.channels.items():
                if s.mode == 'off':
                    continue
                v, i = c.channel_out(ch, V, t)
                if s.mode == 'cv' and i > s.I * (1 + 1e-9):
                    s.mode, changed = 'cc', True
                elif s.mode == 'cc' and v > s.E * (1 + 1e-9) + 1e-9:
                    s.mode, changed = 'cv', True
            if not changed:
                return V
            self.guess = V
        return V

    def _advance(self, c, h, t, depth=0):
        self._h = h
        try:
            return self._solve(c, h, t)
        except (ArithmeticError, np.linalg.LinAlgError):
            if depth >= MAX_SPLIT:
                raise
        # 수렴하지 않으면 시간 간격을 4등분해 다시 진행
        sub = h / 4
        for k in range(4):
            V = self._advance(c, sub, t - h + (k + 1) * sub, depth + 1)
            if k < 3:                      # 마지막 조각은 부른 쪽에서 반영합니다
                self._commit(c, V)
        return V

    def _commit(self, c, V):
        for typ, obj, ns in c.items:
            if typ == 'part' and obj.kind == 'capacitor':
                self.caps[obj.id] = V[ns[0]] - V[ns[1]]
            elif typ == 'part' and obj.kind == 'inductor':
                self.caps[obj.id] = _two_terminal(obj, V[ns[0]] - V[ns[1]], self._h, self.caps.get(obj.id, obj.v0))[0]
            elif typ == 'part' and obj.kind == 'timer555':
                self.caps[('q', obj.id)] = timer_update(ns, V, self.caps.get(('q', obj.id), 0))
            elif typ == 'par':
                self.caps[('n', ns[0])] = V[ns[0]]
        self.guess = V

    def step(self, parts, inst, h, n=1):
        """h초 간격으로 n번 진행. (결과, 스코프 샘플 [(t, v1, v2)])를 돌려줍니다."""
        c = _Circuit(parts, inst, self.modes)
        if self.rough:      # 빠른 계산: 허용 오차를 넓히고, 노드 기생 용량을 키워 급한 전환을 부드럽게 넘깁니다
            c.tol, c.max_newton, c.accept, c.c_par = 1e-8, 25, 1e-6, C_PAR_ROUGH
        samples = []
        try:
            for _ in range(n):
                t = self.t + h
                caps_before = dict(self.caps)
                V = self._advance(c, h, t)
                self._commit(c, V)
                self.t = t
                samples.append((t, V.get(c.probes.get('ch1')) if 'ch1' in c.probes else None,
                                V.get(c.probes.get('ch2')) if 'ch2' in c.probes else None))
        except (ArithmeticError, np.linalg.LinAlgError):
            r = empty_result()
            r['ok'] = False
            r['warnings'] = ['계산이 수렴하지 않았습니다. 연결을 확인하거나 전압을 낮춰 보십시오.']
            return r, samples
        self.modes = {ch: s.mode for ch, s in c.channels.items() if s.mode in ('cv', 'cc')}
        if n == 0:
            return empty_result(), samples
        return _report(c, V, h, caps_before, self.t, parts), samples


def empty_result():
    return dict(psu={ch: dict(voltage=0.0, current=0.0, mode='OFF') for ch in ('ch1', 'ch2')},
                fg=dict(voltage=0.0, current=0.0), nodes={}, parts={}, warnings=[], floating=set(), ok=True)


def _part_alerts(p, v, i, power):
    """부품 경고. '무엇이 문제인지 + 어떻게 고치는지'를 초보자도 알 수 있게 씁니다."""
    alerts = []
    if p.kind in ('resistor', 'ldr'):
        if power > p.rating:
            alerts.append(f'정격 전력 초과 ({format_si(power, "W")} > {format_si(p.rating, "W")}). '
                          '뜨거워질 수 있습니다. 저항값이나 정격을 키우십시오.')
    elif p.kind == 'led':
        if i > 0.020:
            alerts.append(f'전류가 20 mA를 넘습니다 ({format_si(i, "A")}). '
                          'LED가 망가질 수 있습니다. 저항을 더 큰 값으로 바꾸십시오.')
        if v < -5:
            alerts.append('역전압 5 V 초과. LED를 반대로 꽂았습니다. 긴 다리(+)가 전원 쪽입니다.')
    elif p.kind == 'diode':
        if i > 1:
            alerts.append('전류가 1 A를 넘습니다. 직렬 저항을 넣으십시오.')
        if v < -50:
            alerts.append('역전압 50 V 초과.')
        if power > 1:
            alerts.append('손실 전력 1 W 초과. 뜨거워질 수 있습니다.')
    elif p.kind == 'switch':
        if abs(i) > 0.5:
            alerts.append('스위치 전류 500 mA 초과. 회로의 전류를 줄이십시오.')
    elif p.kind == 'capacitor':
        if abs(v) > p.rating:
            alerts.append(f'정격 전압 {p.rating:g} V 초과. 정격 전압이 더 큰 커패시터를 쓰십시오.')
    elif p.kind == 'zener':
        if power > 0.5:
            alerts.append(f'손실 전력 0.5 W 초과 ({format_si(power, "W")}). 직렬 저항을 키우십시오.')
    elif p.kind == 'inductor':
        if abs(i) > 1:
            alerts.append('코일 전류 1 A 초과. 직렬 저항을 넣으십시오.')
    elif p.kind == 'pot':
        if power > 0.5:
            alerts.append('정격 전력 0.5 W 초과. 와이퍼를 끝까지 돌리면 전류가 커집니다.')
    elif p.kind == 'spdt':
        if abs(i) > 0.5:
            alerts.append('스위치 전류 500 mA 초과. 회로의 전류를 줄이십시오.')
    elif p.kind == 'battery':
        if abs(i) > 1:
            alerts.append('전류가 1 A를 넘습니다. 건전지가 단락된 것 같습니다. + 와 − 사이에 부품이 있는지 확인하십시오.')
    elif p.kind == 'nmos':
        if abs(i) > 0.2:
            alerts.append('드레인 전류 200 mA 초과. 드레인 쪽 저항을 키우십시오.')
        if power > 0.4:
            alerts.append('손실 전력 400 mW 초과. 뜨거워질 수 있습니다.')
        if v > 60:
            alerts.append('V_DS 60 V 초과.')
    elif p.kind == 'opamp':
        if v > 36:
            alerts.append('전원 전압(V+ − V−) 36 V 초과. ±15 V 이하로 쓰십시오.')
        if abs(i) > 0.025:
            alerts.append('출력 전류 25 mA 초과. 출력에 단 저항을 키우십시오.')
    elif p.kind == 'timer555':
        if v > 16:
            alerts.append('전원 전압 16 V 초과. 4.5~15 V로 쓰십시오.')
        if abs(i) > 0.2:
            alerts.append('출력 전류 200 mA 초과. 출력에 저항을 넣으십시오.')
    elif p.kind in ('npn', 'pnp'):
        v = abs(v)
        i = abs(i)
        if i > 0.2:
            alerts.append('컬렉터 전류 200 mA 초과. 컬렉터 쪽 저항을 키우십시오.')
        if power > 0.625:
            alerts.append('손실 전력 625 mW 초과. 뜨거워질 수 있습니다.')
        if v > 40:
            alerts.append('V_CE 40 V 초과. 전원 전압을 낮추십시오.')
    return alerts


def _reached(c, roots):
    adj = {}
    for typ, obj, ns in c.items:
        if typ == 'part' and obj.kind == 'switch' and not obj.closed:
            continue
        if typ == 'part' and obj.kind == 'spdt':
            ns = (ns[1], ns[0] if obj.closed else ns[2])
        if typ == 'par' or (typ == 'src' and obj.mode in ('off', 'tie', 'probe')):
            continue
        for x in ns:
            adj.setdefault(x, set()).update(ns)
    seen, stack = set(roots), list(roots)
    while stack:
        for m in adj.get(stack.pop(), ()):
            if m not in seen:
                seen.add(m)
                stack.append(m)
    return seen


def _report(c, V, h, caps, t, parts):
    tags = designators(parts)
    r = empty_result()
    warnings = []
    for typ, p, ns in c.items:
        if typ != 'part':
            continue
        if p.kind in ('npn', 'pnp'):
            C, B, E = ns
            sg = 1 if p.kind == 'npn' else -1
            ib, ic, *_ = _npn(p.value, sg * V[C], sg * V[B], sg * V[E])
            v, i = V[C] - V[E], sg * ic
            info = dict(voltage=v, current=i, power=abs(v * ic) + abs((V[B] - V[E]) * ib), ib=sg * ib,
                        vbe=V[B] - V[E])
        elif p.kind == 'nmos':
            D, G, S = ns
            i = _nmos(p.value, V[G], V[D], V[S])[0]
            v = V[D] - V[S]
            info = dict(voltage=v, current=i, power=abs(v * i), vgs=V[G] - V[S])
        elif p.kind == 'pot':
            a, w, e3 = ns
            rt = max(p.value, 1.0)
            i1 = (V[a] - V[w]) / max(rt * p.pos / 100, 0.5)
            i2 = (V[w] - V[e3]) / max(rt * (1 - p.pos / 100), 0.5)
            info = dict(voltage=V[a] - V[e3], current=i1, power=abs(i1 * (V[a] - V[w])) + abs(i2 * (V[w] - V[e3])),
                        wiper=V[w] - V[e3])
        elif p.kind == 'spdt':
            a, com, b = ns
            other = a if p.closed else b
            v = V[com] - V[other]
            info = dict(voltage=v, current=v * 20.0, power=abs(v * v * 20.0))
        elif p.kind == 'opamp':
            _, inm, inp, vn, _, out, vp, _ = ns
            vt, _d = _opamp_target(V, inm, inp, vn, vp)
            io = (V[out] - vt) / OPAMP_RO
            info = dict(voltage=V[vp] - V[vn], current=-io, power=abs(io) * (V[vp] - V[vn]) / 2,
                        vout=V[out] - c.V_ref(V), vdiff=V[inp] - V[inm])
        elif p.kind == 'timer555':
            gnd, out, vcc = ns[0], ns[2], ns[7]
            vt, _d, q = _timer_target(p, ns, V, caps)
            io = (V[out] - vt) / T555_RO
            info = dict(voltage=V[vcc] - V[gnd], current=-io, power=abs(io) * (V[vcc] - V[gnd]) / 2,
                        vout=V[out] - V[gnd], state=bool(q))
        else:
            a, b = ns
            v = V[a] - V[b]
            i, _ = _two_terminal(p, v, h, caps.get(p.id, p.v0))
            info = dict(voltage=v, current=i, power=abs(v * i))
        info['alerts'] = _part_alerts(p, info['voltage'], info['current'], info['power'])
        r['parts'][p.id] = info
        warnings += [f'{tags[p.id]}: {a}' for a in info['alerts']]

    for ch, s in c.channels.items():
        if s.mode == 'off':
            continue
        v, i = c.channel_out(ch, V, t)
        r['psu'][ch] = dict(voltage=v, current=i, mode=s.mode.upper())
        if s.mode == 'cc' and v < 0.05 * max(s.E, 0.1):
            warnings.append(f'전원 {ch.upper()}: 단락에 가깝습니다. + 와 − 가 바로 이어졌는지 확인하십시오.')
    if c.fg.mode == 'fg':
        vp, vn = V[c.node('g:+')], V[c.node('g:-')]
        r['fg'] = dict(voltage=vp - vn, current=(fg_value(c.inst['fg'], t) - (vp - vn)) / FG_R)

    roots = [c.ref] + [ns[1] for typ, s, ns in c.items if typ == 'src' and s.name in ('ch1', 'ch2', 'fg')]
    seen = _reached(c, roots)
    r['nodes'] = {hh: V[c.node(hh)] for hh in ALL_HOLES if c.node(hh) in seen and c.node(hh) in V}
    r['floating'] = {hh for hh in ALL_HOLES if c.node(hh) not in seen}
    r['warnings'] = warnings
    return r


def dc(parts, inst=None, **psu):
    """정상 상태(커패시터 개방) 결과. 테스트와 빠른 확인용.

    psu 키워드: voltage, limit (CH1에 적용하고 CH1을 켭니다).
    """
    inst = inst or default_instruments()
    if psu:
        inst['psu']['ch1'].update(on=True, **psu)
    sim = Simulator()
    r, _ = sim.step(parts, inst, 1e9, 1)
    return r
