"""가상 UNO 보드: 핀 상태, 모듈·배선, 논리 수준 회로 해석.

해석 순서
1) 점퍼선과 닫힌 스위치로 이어진 점들을 한 망(net)으로 묶습니다.
2) 강한 구동: UNO 전원 핀, OUTPUT 핀, 모듈 출력 → 망 전압. 서로 다르면 단락.
3) 저항으로만 이어진 망은 '약하게' 같은 전압을 받습니다(풀업·풀다운, LED 직렬 저항).
4) INPUT_PULLUP 핀은 아무것도 구동하지 않는 망을 약하게 5V로 올립니다.
5) 각 모듈이 망 전압을 보고 표시 상태와 경고를 정합니다.
"""
import itertools
import threading

from . import modules as M
from .lang import josa

# ---------------------------------------------------------------- UNO 핀 배치
# 보드 크기(px). 실제 68.6 × 53.3mm를 1mm ≈ 7.87px로 그립니다(핀 간격 2.54mm = 20px).
BOARD_W, BOARD_H = 540, 420
PWM_PINS = (3, 5, 6, 9, 10, 11)


def _uno_pins():
    pins = []   # (물리 핀 id, 표시 이름, x, y, 전기 노드)
    top = ['SCL', 'SDA', 'AREF', 'GND.3', 'D13', 'D12', 'D11', 'D10', 'D9', 'D8']
    x = 148
    for name in top:
        pins.append((name, name.split('.')[0], x, 18))
        x += 20
    x += 12
    for k in range(7, -1, -1):
        pins.append((f'D{k}', f'D{k}', x, 18))
        x += 20
    bottom = ['NC', 'IOREF', 'RESET', '3V3', '5V', 'GND.1', 'GND.2', 'VIN']
    x = 216
    for name in bottom:
        pins.append((name, name.split('.')[0], x, BOARD_H - 18))
        x += 20
    x = 396
    for k in range(6):
        pins.append((f'A{k}', f'A{k}', x, BOARD_H - 18))
        x += 20
    out = []
    for pid, label, px, py in pins:
        node = {'SCL': 'A5', 'SDA': 'A4', 'GND.1': 'GND', 'GND.2': 'GND', 'GND.3': 'GND', 'IOREF': '5V'}.get(pid, pid)
        out.append((pid, label, px, py, node))
    return out


UNO_PINS = _uno_pins()
UNO_PIN_POS = {p[0]: (p[2], p[3]) for p in UNO_PINS}
UNO_PIN_NODE = {p[0]: p[4] for p in UNO_PINS}
UNO_PIN_LABEL = {p[0]: p[1] for p in UNO_PINS}


def pin_node(num):
    """스케치 핀 번호(0~19) → 전기 노드 이름."""
    return f'D{num}' if num < 14 else f'A{num - 14}'


def pin_title(num):
    return f'D{num}' if num < 14 else f'A{num - 14}'


class Net:
    __slots__ = ('v', 'strong', 'duty', 'freq', 'servo', 'pullup', 'weak', 'short', 'n', 'uno', 'sources')

    def __init__(self):
        self.v = None
        self.strong = False
        self.duty = None
        self.freq = None
        self.servo = None
        self.pullup = False
        self.weak = False
        self.short = False
        self.n = 0
        self.uno = set()
        self.sources = []

    def high(self):
        return self.v is not None and self.v >= 2.5

    def level(self):
        """디지털 출력 정도(0~1): PWM이면 듀티, 아니면 0/1."""
        if self.v is None or self.v < 2.5:
            return 0.0
        return self.duty if self.duty is not None else 1.0


FLOATING = Net()


class Wire:
    _ids = itertools.count(1)

    def __init__(self, a, b, color=None, wid=None):
        self.a = tuple(a)
        self.b = tuple(b)
        self.color = color
        self.id = wid or next(Wire._ids)

    def to_json(self):
        return {'a': list(self.a), 'b': list(self.b), 'color': self.color}


class UnionFind:
    def __init__(self):
        self.p = {}

    def find(self, x):
        p = self.p
        if x not in p:
            p[x] = x
            return x
        root = x
        while p[root] != root:
            root = p[root]
        while p[x] != root:
            p[x], x = root, p[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


class Solution:
    def __init__(self):
        self.root = {}
        self.nets = {}
        self.warnings = []    # (문구, 모듈 id 또는 None)

    def net(self, key):
        r = self.root.get(key)
        if r is None:
            return FLOATING
        return self.nets[r]

    def net_of(self, mod):
        mid = mod.id
        return lambda pin: self.net((mid, pin))

    def same(self, a, b):
        ra, rb = self.root.get(a), self.root.get(b)
        return ra is not None and ra == rb


def uno_key(pin_id):
    return ('uno', UNO_PIN_NODE.get(pin_id, pin_id))


class Board:
    def __init__(self):
        self.lock = threading.RLock()
        self.modules = {}
        self.wires = []
        self.machine = None
        self.version = 0
        self.dirty = True
        self.sol = Solution()
        self.runtime_warnings = []
        self.serial_used = False
        self.wire_started = False
        self.tx_t = self.rx_t = -10**9
        self._mid = itertools.count(1)
        self.reset_outputs()

    # --- 시간
    def now(self):
        m = self.machine
        return m.t if m is not None else 0

    def touch(self):
        self.dirty = True
        self.version += 1

    # --- 구성
    def new_id(self, type_id):
        while True:
            mid = f'{type_id}{next(self._mid)}'
            if mid not in self.modules:
                return mid

    def add_module(self, mod):
        with self.lock:
            self.modules[mod.id] = mod
            self.touch()

    def remove_module(self, mod):
        with self.lock:
            self.modules.pop(mod.id, None)
            self.touch()

    def add_wire(self, w):
        with self.lock:
            self.wires.append(w)
            self.touch()

    def remove_wire(self, w):
        with self.lock:
            if w in self.wires:
                self.wires.remove(w)
            self.touch()

    def clear(self):
        with self.lock:
            self.modules.clear()
            self.wires.clear()
            self.touch()

    def wires_at(self, end):
        return [w for w in self.wires if w.a == end or w.b == end]

    # --- 핀 출력 상태(스케치가 바꿈)
    def reset_outputs(self):
        with self.lock:
            self.mode = [0] * 20          # 0 INPUT, 1 OUTPUT, 2 INPUT_PULLUP
            self.out = [0] * 20
            self.pwm = [None] * 20
            self.tones = {}               # 핀 → (주파수, 끝 시각 µs 또는 None)
            self.servos = {}              # 핀 → 각도
            self.last_high = [-10**12] * 20
            self.runtime_warnings = []
            self.serial_used = False
            self.wire_started = False
            self.tx_t = self.rx_t = -10**9
            self.read_warned = set()
            for mod in self.modules.values():
                mod.reset()
            self.touch()

    def pin_mode(self, p, mode):
        with self.lock:
            self.mode[p] = mode
            if mode == 2:
                self.out[p] = 1
            elif mode == 0:
                self.out[p] = 0
            self.pwm[p] = None
            self.touch()

    def digital_write(self, p, v):
        with self.lock:
            if self.mode[p] != 1:
                if v and p not in self.servos and p not in self.tones:
                    self.machine and self.machine.warn(
                        ('dw-input', p),
                        f'{pin_title(p)}: pinMode({p}, OUTPUT) 없이 digitalWrite()를 썼습니다. '
                        f'내부 풀업만 켜져 LED가 희미합니다')
                self.out[p] = v
                self.mode[p] = 2 if v else 0
                self.touch()
                return
            if v and not self.out[p]:
                self.last_high[p] = self.now()
            if self.out[p] != v or self.pwm[p] is not None:
                self.out[p] = v
                self.pwm[p] = None
                self.touch()

    def analog_write(self, p, v):
        with self.lock:
            self.mode[p] = 1
            if p not in PWM_PINS:
                if 0 < v < 255:
                    self.machine and self.machine.warn(
                        ('pwm', p), f'{pin_title(p)}{josa(pin_title(p), '은는')} PWM 핀이 아닙니다. analogWrite()는 ~ 핀(3, 5, 6, 9, 10, 11)에 씁니다')
                self.out[p] = 1 if v >= 128 else 0
                self.pwm[p] = None
            elif v <= 0:
                self.out[p], self.pwm[p] = 0, None
            elif v >= 255:
                self.out[p], self.pwm[p] = 1, None
            else:
                self.out[p], self.pwm[p] = 1, v
            self.touch()

    def tone(self, p, freq, end):
        with self.lock:
            self.mode[p] = 1
            self.tones = {p: (freq, end)}      # UNO의 tone()은 한 번에 한 핀
            self.touch()

    def no_tone(self, p):
        with self.lock:
            if p in self.tones:
                del self.tones[p]
                self.out[p] = 0
                self.touch()

    def servo_attach(self, p, angle):
        with self.lock:
            self.mode[p] = 1
            self.servos[p] = angle
            self.touch()

    def servo_write(self, p, angle):
        with self.lock:
            if self.servos.get(p) != angle:
                self.servos[p] = angle
                self.touch()

    def servo_detach(self, p):
        with self.lock:
            self.servos.pop(p, None)
            self.touch()

    def shift_out(self, dpin, cpin, order, val):
        pass

    def serial_activity(self, kind, t):
        if kind == 'tx':
            self.tx_t = t
        else:
            self.rx_t = t

    def add_runtime_warning(self, msg):
        with self.lock:
            if msg not in self.runtime_warnings:
                self.runtime_warnings.append(msg)
            self.version += 1

    # --- 입력 읽기(스케치가 부름)
    def uno_net(self, p):
        return self.solve().net(('uno', pin_node(p)))

    def digital_level(self, p):
        if self.mode[p] == 1:
            return self.out[p]
        net = self.uno_net(p)
        if net.v is None:
            return 0
        return 1 if net.v >= 2.5 else 0

    def digital_read(self, p):
        if self.mode[p] == 1:
            return self.out[p]
        net = self.uno_net(p)
        if net.v is None:
            m = self.machine
            if p not in self.read_warned and m is not None:
                self.read_warned.add(p)
                m.warn(('float', p), (f'{pin_title(p)} 입력 전압이 정해지지 않아 값이 흔들립니다(플로팅). ' if net.n else
                                       f'{pin_title(p)} 입력이 연결되지 않아 값이 흔들립니다(플로팅). ') +
                                      'INPUT_PULLUP이나 풀다운 저항을 쓰십시오')
            return m.rng.randrange(2) if m is not None else 0
        if net.duty is not None and self.machine is not None:
            return 1 if self.machine.rng.random() < net.duty else 0
        return 1 if net.v >= 2.5 else 0

    def analog_read(self, p):
        net = self.uno_net(p)
        if net.v is None:
            m = self.machine
            if m is not None:
                m.warn(('afloat', p), f'{pin_title(p)}{josa(pin_title(p), '이가')} 연결되지 않아 analogRead() 값이 흔들립니다')
                return 280 + m.rng.randrange(-60, 60)
            return 0
        v = net.v * (net.duty if net.duty is not None else 1.0)
        return max(0, min(1023, int(v / 5.0 * 1023 + 0.5)))

    def pulse_in(self, p, level):
        sol = self.solve()
        key = ('uno', pin_node(p))
        for mod in self.modules.values():
            if mod.TYPE == 'hcsr04' and sol.same((mod.id, 'ECHO'), key):
                if not self.powered(mod):
                    self.machine.warn(('us-pwr', mod.id), '초음파 센서에 전원(VCC, GND)이 연결되지 않았습니다')
                    return None
                trig = sol.net((mod.id, 'TRIG'))
                fired = any(self.now() - self.last_high[q] < 60_000 for q in range(20)
                            if ('uno', pin_node(q)) in trig.uno and self.mode[q] == 1)
                if not fired:
                    self.machine.warn(('us-trig', mod.id), '초음파 센서 TRIG에 10µs 펄스를 먼저 보내야 합니다')
                    return None
                if not level:
                    return None
                d = float(mod.props['distance'])
                if d > 400 or d < 2:
                    return None
                return d * 58.3
        return None

    # --- 라이브러리가 장치를 찾을 때
    def find_i2c(self, addr, quiet=False):
        sol = self.solve()
        for mod in self.modules.values():
            if mod.TYPE == 'lcd1602' and int(mod.props.get('addr', 0x27)) == addr:
                if sol.same((mod.id, 'SDA'), ('uno', 'A4')) and sol.same((mod.id, 'SCL'), ('uno', 'A5')) \
                        and self.powered(mod):
                    return mod
        return None

    def find_module_on_pins(self, types, pinmap):
        sol = self.solve()
        for mod in self.modules.values():
            if mod.TYPE in types and all(sol.same((mod.id, mp), ('uno', pin_node(up)))
                                         for mp, up in pinmap.items()):
                return mod
        return None

    def powered(self, mod):
        if not mod.POWER:
            return True
        sol = self.sol
        vcc = sol.net((mod.id, mod.POWER[0]))
        gnd = sol.net((mod.id, mod.POWER[1]))
        return vcc.v is not None and vcc.v >= 2.7 and gnd.v is not None and gnd.v < 0.5

    # --- 해석
    def solve(self):
        with self.lock:
            if not self.dirty:
                # tone(핀, 주파수, 길이)의 끝 시각 확인
                if self.tones:
                    now = self.now()
                    for p, (f, end) in list(self.tones.items()):
                        if end is not None and now >= end:
                            del self.tones[p]
                            self.dirty = True
                if not self.dirty:
                    return self.sol
            for _ in range(4):
                sol = self._solve_once()
                self.sol = sol
                changed = False
                now = self.now()
                for mod in self.modules.values():
                    if mod.update(sol.net_of(mod), now, self):
                        changed = True
                if not changed:
                    break
            self._board_warnings(sol)
            self.dirty = False
            return sol

    def _solve_once(self):
        now = self.now()
        for p, (f, end) in list(self.tones.items()):
            if end is not None and now >= end:
                del self.tones[p]
        uf = UnionFind()
        for node in ('5V', '3V3', 'VIN', 'GND', 'AREF', 'RESET', 'NC'):
            uf.find(('uno', node))
        for p in range(20):
            uf.find(('uno', pin_node(p)))
        endpoints = {}
        for w in self.wires:
            ka = self.key(w.a)
            kb = self.key(w.b)
            if ka is None or kb is None:
                continue
            uf.union(ka, kb)
            endpoints[ka] = endpoints.get(ka, 0) + 1
            endpoints[kb] = endpoints.get(kb, 0) + 1
        res_edges = []
        for mod in self.modules.values():
            for pin, _x, _y in mod.PINS:
                uf.find((mod.id, pin))
            for a, b, kind in mod.links():
                if kind == 'short':
                    uf.union((mod.id, a), (mod.id, b))
                else:
                    res_edges.append(((mod.id, a), (mod.id, b)))
        sol = Solution()
        for k in list(uf.p):
            r = uf.find(k)
            sol.root[k] = r
            net = sol.nets.get(r)
            if net is None:
                net = sol.nets[r] = Net()
            if k[0] == 'uno':
                net.uno.add(k)
            net.n += endpoints.get(k, 0)

        def drive(key, v, src, duty=None, freq=None, servo=None):
            net = sol.nets[sol.root[key]]
            if net.strong and net.v is not None and abs(net.v - v) > 0.6:
                net.short = True
                net.sources.append((src, v))
                net.v = min(net.v, v)
                return
            net.strong = True
            net.v = v
            net.sources.append((src, v))
            if duty is not None:
                net.duty = duty
            if freq is not None:
                net.freq = freq
            if servo is not None:
                net.servo = servo

        drive(('uno', '5V'), 5.0, '5V')
        drive(('uno', '3V3'), 3.3, '3.3V')
        drive(('uno', 'VIN'), 5.0, 'VIN')
        drive(('uno', 'GND'), 0.0, 'GND')
        for p in range(20):
            key = ('uno', pin_node(p))
            if p in self.servos:
                drive(key, 5.0, pin_title(p), duty=0.075, servo=self.servos[p])
            elif p in self.tones:
                drive(key, 5.0, pin_title(p), duty=0.5, freq=self.tones[p][0])
            elif self.mode[p] == 1:
                if self.pwm[p] is not None:
                    drive(key, 5.0, pin_title(p), duty=self.pwm[p] / 255.0)
                else:
                    drive(key, 5.0 if self.out[p] else 0.0, pin_title(p))
        # 모듈 출력은 UNO가 구동한 전압(전원 등)을 보고 정합니다
        for mod in self.modules.values():
            outs = mod.drive(sol.net_of(mod))
            for pin, v in outs.items():
                if v is not None:
                    drive((mod.id, pin), float(v), mod.id)
        # 저항을 통한 약한 전달: 강한 구동 → 내부 풀업 순서로 우선합니다
        adj = {}
        for a, b in res_edges:
            ra, rb = sol.root[a], sol.root[b]
            if ra != rb:
                adj.setdefault(ra, []).append(rb)
                adj.setdefault(rb, []).append(ra)
        self._propagate(sol, adj, [r for r, net in sol.nets.items() if net.strong])
        pulled = []
        for p in range(20):
            if self.mode[p] != 1 and self.out[p]:
                r = sol.root[('uno', pin_node(p))]
                net = sol.nets[r]
                if net.v is None:
                    net.v = 5.0
                    net.weak = True
                    net.pullup = True
                    pulled.append(r)
        self._propagate(sol, adj, pulled)
        return sol

    @staticmethod
    def _propagate(sol, adj, sources):
        """sources 망의 전압을 저항 너머의 빈 망으로 전달합니다. 여러 곳에서 오면 평균(분압)."""
        if not adj or not sources:
            return
        got = {}
        for src in sources:
            if src not in adj:
                continue
            sn = sol.nets[src]
            seen = {src}
            stack = [src]
            while stack:
                r = stack.pop()
                for nb in adj.get(r, ()):
                    if nb in seen:
                        continue
                    seen.add(nb)
                    if sol.nets[nb].v is not None and nb not in got:
                        continue
                    got.setdefault(nb, []).append(sn)
                    stack.append(nb)
        for r, srcs in got.items():
            net = sol.nets[r]
            vs = [s.v for s in srcs]
            net.v = sum(vs) / len(vs)
            net.weak = True
            net.pullup = all(s.pullup for s in srcs)
            if len(set(round(v, 1) for v in vs)) == 1:
                s0 = srcs[0]
                net.duty, net.freq, net.servo = s0.duty, s0.freq, s0.servo

    def key(self, end):
        owner, pin = end
        if owner == 'uno':
            return uno_key(pin)
        if owner not in self.modules:
            return None
        return (owner, pin)

    def _board_warnings(self, sol):
        warns = []
        seen = set()
        for net in sol.nets.values():
            if net.short:
                names = sorted(set(s for s, _ in net.sources))
                key = tuple(names)
                if key in seen:
                    continue
                seen.add(key)
                labels = [M.source_name(s, self.modules) for s in names]
                names_txt = ''.join(f'{n}{josa(n, "와과")} ' for n in labels[:-1]) + labels[-1]
                warns.append((f'단락: {names_txt}{josa(names_txt, "이가")} 직접 연결되었습니다. 실제 보드에서는 부품이 손상될 수 있습니다', None))
        if self.serial_used:
            for p in (0, 1):
                net = sol.net(('uno', pin_node(p)))
                if net.n > 0:
                    warns.append((f'D{p}{josa(p, '은는')} 시리얼 통신에 쓰입니다. Serial 사용 중에는 D0, D1을 비워 두십시오', None))
        for mod in self.modules.values():
            for msg in mod.warnings:
                warns.append((msg, mod.id))
        sol.warnings = warns

    def all_warnings(self):
        sol = self.solve()
        return list(sol.warnings) + [(w, None) for w in self.runtime_warnings]

    # --- 저장
    def to_json(self):
        with self.lock:
            return {
                'modules': [m.to_json() for m in self.modules.values()],
                'wires': [w.to_json() for w in self.wires],
            }

    def load_json(self, data):
        with self.lock:
            self.modules.clear()
            self.wires.clear()
            for md in data.get('modules', []):
                mod = M.from_json(md)
                self.modules[mod.id] = mod
            for wd in data.get('wires', []):
                w = Wire(wd['a'], wd['b'], wd.get('color'))
                if self.valid_end(w.a) and self.valid_end(w.b):
                    self.wires.append(w)
            self.touch()

    def valid_end(self, end):
        owner, pin = end
        if owner == 'uno':
            return pin in UNO_PIN_POS
        mod = self.modules.get(owner)
        return mod is not None and pin in mod.pin_names()
