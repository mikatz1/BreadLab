"""교육용 모듈의 논리 동작. 그림은 art.py에 있습니다.

PINS의 좌표는 모듈 왼쪽 위 기준(px)이고, 점퍼선이 닿는 핀 끝 위치입니다.
CONTROLS: 속성 패널에 나오는 조절기
  ('choice', 키, 이름, [(값, 표시), ...])  설정(실행 취소 가능)
  ('slider', 키, 이름, 최소, 최대, 단위)    센서 값(실행 중 조절)
  ('check',  키, 이름)                      센서 상태(실행 중 조절)
"""
import itertools
import math

from .libs import LcdState

TYPES = {}
CATEGORIES = ['기본 부품', '입력', '출력', '표시 장치', '센서']


def register(cls):
    TYPES[cls.TYPE] = cls
    return cls


def source_name(src, modules):
    mod = modules.get(src)
    if mod is not None:
        return mod.NAME
    return src


def header(names, x0, y, pitch=20):
    return [(n, x0 + i * pitch, y) for i, n in enumerate(names)]


class Module:
    TYPE = ''
    NAME = ''
    CATEGORY = ''
    DESC = ''
    SIZE = (60, 60)
    PINS = []
    POWER = None          # (VCC 핀, GND 핀)
    PROPS = {}
    CONTROLS = []
    LIVE = ()             # 실행 중 바꾸는 값(실행 취소 대상 아님)
    PIN_LABELS = {}

    def __init__(self, mid, props=None):
        self.id = mid
        self.props = dict(self.PROPS)
        if props:
            for k, v in props.items():
                if k in self.props:
                    self.props[k] = v
        self.x = 0.0
        self.y = 0.0
        self.state = {}
        self.warnings = []
        self.reset()

    def reset(self):
        pass

    def pin_names(self):
        return [p[0] for p in self.PINS]

    def pin_pos(self, name):
        for n, x, y in self.PINS:
            if n == name:
                return x, y
        return None

    def pin_label(self, name):
        return self.PIN_LABELS.get(name, name)

    def links(self):
        return []

    def drive(self, net):
        return {}

    def update(self, net, now, board):
        self.warnings = []
        return False

    # 공통: 전원 확인. 전원 전압(V) 또는 None
    def check_power(self, net):
        if not self.POWER:
            return 5.0
        vcc, gnd = net(self.POWER[0]), net(self.POWER[1])
        if vcc.v is not None and gnd.v is not None and vcc.v < 0.5 and gnd.v >= 2.7:
            self.warnings.append(f'{self.NAME}: 전원 극성이 반대입니다 ({self.POWER[0]}↔{self.POWER[1]})')
            return None
        if vcc.v is not None and vcc.v >= 2.7 and gnd.v is not None and gnd.v < 0.5:
            return vcc.v
        if any(net(p).n > 0 for p in self.pin_names()):
            missing = []
            if vcc.v is None or vcc.v < 2.7:
                missing.append(f'{self.pin_label(self.POWER[0])}→5V')
            if gnd.v is None or gnd.v >= 0.5:
                missing.append(f'{self.pin_label(self.POWER[1])}→GND')
            self.warnings.append(f'{self.NAME}: 전원이 연결되지 않았습니다 ({", ".join(missing)})')
        return None

    def to_json(self):
        return {'id': self.id, 'type': self.TYPE, 'x': round(self.x, 1), 'y': round(self.y, 1),
                'props': dict(self.props)}


def from_json(d):
    cls = TYPES.get(d.get('type'))
    if cls is None:
        raise ValueError(f"알 수 없는 모듈 종류 '{d.get('type')}'")
    mod = cls(d['id'], d.get('props'))
    mod.x = float(d.get('x', 0))
    mod.y = float(d.get('y', 0))
    return mod


def led_drive_level(a, k):
    """LED 양 끝 망 → (밝기 0~1, 방향 반대 여부)"""
    if a.v is None or k.v is None:
        return 0.0, False
    if k.v - a.v >= 1.8:
        return 0.0, True
    if a.v - k.v < 1.8:
        return 0.0, False
    level = 1.0
    if a.duty is not None:
        level *= a.duty
    if k.duty is not None:
        level *= (1 - k.duty)
    if a.pullup:
        level = 0.08
    return level, False


# ---------------------------------------------------------------- 기본 부품
LED_COLORS = [('red', '빨강'), ('yellow', '노랑'), ('green', '초록'), ('blue', '파랑'), ('white', '흰색')]


@register
class Led(Module):
    TYPE = 'led'
    NAME = 'LED'
    CATEGORY = '기본 부품'
    DESC = '긴 다리(+)는 출력 핀, 짧은 다리(−)는 GND에 연결합니다. 220Ω 저항을 직렬로 연결합니다.'
    SIZE = (30, 46)
    PINS = [('A', 9, 70), ('K', 21, 64)]
    PIN_LABELS = {'A': '+ (긴 다리)', 'K': '− (짧은 다리)'}
    PROPS = {'color': 'red'}
    CONTROLS = [('choice', 'color', '색', LED_COLORS)]

    def update(self, net, now, board):
        self.warnings = []
        a, k = net('A'), net('K')
        level, reverse = led_drive_level(a, k)
        self.state['level'] = level
        if reverse:
            self.warnings.append('LED 방향이 반대입니다. 긴 다리(+)를 출력 쪽에 연결하십시오')
        if level > 0 and a.strong and k.strong:
            self.warnings.append('LED에 저항이 없습니다. 220Ω 저항을 직렬로 연결하십시오')
            self.state['over'] = True
        else:
            self.state['over'] = False
        if (a.n > 0) != (k.n > 0):
            self.warnings.append('LED 다리 하나가 연결되지 않았습니다')
        return False


@register
class Resistor(Module):
    TYPE = 'resistor'
    NAME = '저항'
    CATEGORY = '기본 부품'
    DESC = '전류를 제한합니다. LED에는 220Ω, 풀다운에는 10kΩ을 씁니다.'
    SIZE = (80, 18)
    PINS = [('1', 0, 9), ('2', 80, 9)]
    PROPS = {'ohms': 220}
    CONTROLS = [('choice', 'ohms', '저항값', [(220, '220 Ω'), (330, '330 Ω'), (1000, '1 kΩ'), (10000, '10 kΩ')])]

    def links(self):
        return [('1', '2', 'res')]


@register
class RgbLed(Module):
    TYPE = 'rgb_led'
    NAME = 'RGB LED 모듈'
    CATEGORY = '출력'
    DESC = '저항 내장 RGB LED입니다. R·G·B를 PWM 핀(~)에 연결해 analogWrite()로 색을 섞습니다.'
    SIZE = (64, 58)
    PINS = header(['R', 'G', 'B', 'GND'], 2, 76)
    PIN_LABELS = {'GND': '−'}

    def update(self, net, now, board):
        self.warnings = []
        g = net('GND')
        out = []
        for ch in 'RGB':
            n = net(ch)
            if n.v is None or g.v is None or n.v - g.v < 1.8:
                out.append(0.0)
            else:
                out.append(n.duty if n.duty is not None else (0.08 if n.pullup else 1.0))
        self.state['rgb'] = out
        if any(net(c).n > 0 for c in 'RGB') and g.n == 0:
            self.warnings.append('RGB LED의 − 핀을 GND에 연결하십시오')
        return False


# ---------------------------------------------------------------- 입력
@register
class Button(Module):
    TYPE = 'button'
    NAME = '푸시 버튼'
    CATEGORY = '입력'
    DESC = '누르는 동안 두 핀이 연결됩니다. 입력 핀과 GND에 연결하고 INPUT_PULLUP을 쓰면 누를 때 LOW입니다. 캔버스에서 눌러 볼 수 있습니다.'
    SIZE = (50, 50)
    PINS = [('1', 15, 66), ('2', 35, 66)]
    PROPS = {'pressed': False, 'cap': 'black'}
    LIVE = ('pressed',)
    CONTROLS = [('check', 'pressed', '눌린 상태로 두기'),
                ('choice', 'cap', '버튼 색', [('black', '검정'), ('red', '빨강'), ('blue', '파랑'), ('yellow', '노랑')])]

    def links(self):
        return [('1', '2', 'short')] if self.props['pressed'] else []


@register
class SlideSwitch(Module):
    TYPE = 'slide_switch'
    NAME = '슬라이드 스위치'
    CATEGORY = '입력'
    DESC = 'COM 핀이 손잡이 쪽 핀과 연결됩니다. 캔버스에서 눌러 전환합니다.'
    SIZE = (60, 40)
    PINS = header(['1', 'COM', '2'], 10, 56)
    PROPS = {'pos': 0}
    LIVE = ('pos',)
    CONTROLS = [('choice', 'pos', '위치', [(0, '1번 쪽'), (1, '2번 쪽')])]

    def links(self):
        return [('COM', '1' if self.props['pos'] == 0 else '2', 'short')]


@register
class ToggleSwitch(Module):
    TYPE = 'toggle'
    NAME = '토글 스위치'
    CATEGORY = '입력'
    DESC = '켜면 두 핀이 연결되고 끄면 끊어집니다. 캔버스에서 눌러 전환합니다.'
    SIZE = (50, 50)
    PINS = [('1', 15, 66), ('2', 35, 66)]
    PROPS = {'on': False}
    LIVE = ('on',)
    CONTROLS = [('check', 'on', '켜짐')]

    def links(self):
        return [('1', '2', 'short')] if self.props['on'] else []


@register
class Potentiometer(Module):
    TYPE = 'pot'
    NAME = '가변저항'
    CATEGORY = '입력'
    DESC = '양 끝은 5V와 GND, 가운데는 아날로그 핀에 연결합니다. analogRead()로 0~1023을 읽습니다. 마우스 휠로 돌립니다.'
    SIZE = (64, 64)
    PINS = header(['1', 'W', '2'], 12, 82)
    PIN_LABELS = {'W': '가운데(와이퍼)'}
    PROPS = {'value': 512}
    LIVE = ('value',)
    CONTROLS = [('slider', 'value', '위치', 0, 1023, '')]

    def drive(self, net):
        a, b = net('1'), net('2')
        if a.v is None or b.v is None or not a.strong or not b.strong:
            return {}
        pos = self.props['value'] / 1023.0     # 1번 핀이 5V면 analogRead()가 이 값과 같아요
        return {'W': b.v + (a.v - b.v) * pos}

    def update(self, net, now, board):
        self.warnings = []
        a, b, w = net('1'), net('2'), net('W')
        if w.n > 0 and (a.v is None or b.v is None):
            self.warnings.append('가변저항 양 끝을 5V와 GND에 연결하십시오')
        return False


@register
class Joystick(Module):
    TYPE = 'joystick'
    NAME = '조이스틱'
    CATEGORY = '입력'
    DESC = 'VRx·VRy는 아날로그 핀(가운데 약 512), SW는 디지털 핀에 연결합니다. SW는 INPUT_PULLUP으로 읽고 누르면 LOW입니다.'
    SIZE = (100, 84)
    PINS = header(['GND', '5V', 'VRx', 'VRy', 'SW'], 10, 102)
    POWER = ('5V', 'GND')
    PROPS = {'x': 512, 'y': 512, 'pressed': False}
    LIVE = ('x', 'y', 'pressed')
    CONTROLS = [('slider', 'x', 'X축', 0, 1023, ''), ('slider', 'y', 'Y축', 0, 1023, ''),
                ('check', 'pressed', '버튼 누름')]

    def links(self):
        return [('SW', 'GND', 'short')] if self.props['pressed'] else []

    def drive(self, net):
        vcc, gnd = net('5V'), net('GND')
        if vcc.v is None or vcc.v < 2.7 or gnd.v is None or gnd.v > 0.5:
            return {}
        return {'VRx': vcc.v * self.props['x'] / 1023.0, 'VRy': vcc.v * self.props['y'] / 1023.0}

    def update(self, net, now, board):
        self.warnings = []
        self.check_power(net)
        return False


# ---------------------------------------------------------------- 출력
@register
class PassiveBuzzer(Module):
    TYPE = 'buzzer_passive'
    NAME = '수동 부저'
    CATEGORY = '출력'
    DESC = 'tone(핀, 주파수)로 소리를 냅니다. digitalWrite()로는 소리가 나지 않습니다.'
    SIZE = (50, 50)
    PINS = [('+', 15, 66), ('-', 35, 66)]

    def reset(self):
        self.state['freq'] = None

    def update(self, net, now, board):
        self.warnings = []
        a, k = net('+'), net('-')
        freq = None
        if a.v is not None and k.v is not None and k.v < 0.5 and a.freq:
            freq = a.freq
        self.state['freq'] = freq
        self.state['dc'] = freq is None and a.high() and k.v is not None and k.v < 0.5 and a.duty is None
        if self.state['dc']:
            self.warnings.append('수동 부저는 HIGH만으로 소리가 나지 않습니다. tone()을 쓰십시오')
        return False


@register
class ActiveBuzzer(Module):
    TYPE = 'buzzer_active'
    NAME = '능동 부저'
    CATEGORY = '출력'
    DESC = 'HIGH를 주면 약 2.3kHz 소리가 납니다.'
    SIZE = (50, 50)
    PINS = [('+', 15, 66), ('-', 35, 66)]

    def update(self, net, now, board):
        self.warnings = []
        a, k = net('+'), net('-')
        on = a.v is not None and k.v is not None and a.v - k.v >= 2.5 and not a.pullup
        self.state['on'] = on
        self.state['freq'] = 2300 if on else None
        return False


@register
class ServoMotor(Module):
    TYPE = 'servo'
    NAME = '서보 모터 (SG90)'
    CATEGORY = '출력'
    DESC = '갈색 GND, 빨강 5V, 주황 신호선입니다. Servo 라이브러리로 0~180°를 지정합니다.'
    SIZE = (96, 64)
    PINS = header(['GND', '5V', 'SIG'], 28, 84)
    POWER = ('5V', 'GND')
    PIN_LABELS = {'SIG': '신호'}

    def reset(self):
        self.state.setdefault('angle', 90.0)
        self.state['target'] = None
        self.state['t'] = None

    def update(self, net, now, board):
        self.warnings = []
        vcc = self.check_power(net)
        sig = net('SIG')
        target = sig.servo if vcc is not None else None
        if vcc is not None and sig.servo is None and sig.n > 0 and sig.duty is not None:
            self.warnings.append('서보는 analogWrite()가 아니라 Servo 라이브러리로 제어합니다')
        self.state['target'] = target
        self.state['powered'] = vcc is not None
        return False

    def animate(self, now):
        """화면 갱신 때 호출: 각도를 목표로 천천히(약 0.1초/60°) 움직입니다."""
        target = self.state.get('target')
        last = self.state.get('t')
        self.state['t'] = now
        if target is None or last is None:
            return False
        dt = max(0, now - last) / 1e6
        cur = self.state.get('angle', 90.0)
        if abs(cur - target) < 0.5:
            if cur != target:
                self.state['angle'] = float(target)
                return True
            return False
        step = 600.0 * dt
        if abs(target - cur) <= step:
            cur = float(target)
        else:
            cur += step if target > cur else -step
        self.state['angle'] = cur
        return True


@register
class DcMotor(Module):
    TYPE = 'dc_motor'
    NAME = 'DC 모터 + 드라이버'
    CATEGORY = '출력'
    DESC = 'L9110S 드라이버가 달린 모터입니다. IA에 PWM, IB에 LOW면 정방향, 반대면 역방향입니다. 모터를 핀에 직접 연결하면 안 됩니다.'
    SIZE = (120, 72)
    PINS = header(['VCC', 'GND', 'IA', 'IB'], 30, 90)
    POWER = ('VCC', 'GND')

    def reset(self):
        self.state['speed'] = 0.0
        self.state.setdefault('angle', 0.0)
        self.state['t'] = None

    def update(self, net, now, board):
        self.warnings = []
        vcc = self.check_power(net)
        if vcc is None:
            self.state['speed'] = 0.0
            return False
        self.state['speed'] = net('IA').level() - net('IB').level()
        return False

    def animate(self, now):
        last = self.state.get('t')
        self.state['t'] = now
        sp = self.state.get('speed', 0.0)
        if last is None or abs(sp) < 1e-3:
            return False
        dt = max(0, now - last) / 1e6
        self.state['angle'] = (self.state.get('angle', 0.0) + sp * 1080 * dt) % 360
        return True


@register
class Relay(Module):
    TYPE = 'relay'
    NAME = '릴레이 모듈'
    CATEGORY = '출력'
    DESC = 'IN이 HIGH면 COM이 NO에, LOW면 NC에 연결됩니다. 다른 회로를 켜고 끄는 스위치입니다.'
    SIZE = (130, 66)
    PINS = header(['IN', 'VCC', 'GND'], 12, 84) + header(['NO', 'COM', 'NC'], 78, 84)
    POWER = ('VCC', 'GND')

    def reset(self):
        self.state['on'] = False

    def links(self):
        return [('COM', 'NO' if self.state.get('on') else 'NC', 'short')]

    def update(self, net, now, board):
        self.warnings = []
        vcc = self.check_power(net)
        inp = net('IN')
        on = vcc is not None and inp.high() and not inp.pullup
        changed = on != self.state.get('on')
        self.state['on'] = on
        return changed


# ---------------------------------------------------------------- 표시 장치
@register
class Lcd1602(Module):
    TYPE = 'lcd1602'
    NAME = 'LCD 1602 (I2C)'
    CATEGORY = '표시 장치'
    DESC = 'I2C 방식 16×2 글자 LCD입니다. SDA는 A4, SCL은 A5에 연결합니다. 글자가 안 보이면 init()과 backlight()를 확인하십시오.'
    SIZE = (300, 112)
    PINS = header(['GND', 'VCC', 'SDA', 'SCL'], 14, 130)
    POWER = ('VCC', 'GND')
    PROPS = {'addr': 0x27}
    CONTROLS = [('choice', 'addr', 'I2C 주소', [(0x27, '0x27'), (0x3F, '0x3F')])]

    def __init__(self, mid, props=None):
        self.lcd = LcdState()
        super().__init__(mid, props)

    def reset(self):
        self.lcd.reset()

    def update(self, net, now, board):
        self.warnings = []
        vcc = self.check_power(net)
        self.state['powered'] = vcc is not None
        sda, scl = net('SDA'), net('SCL')
        if vcc is not None and (sda.n > 0 or scl.n > 0):
            if ('uno', 'A5') in sda.uno and ('uno', 'A4') in scl.uno:
                self.warnings.append('LCD의 SDA와 SCL이 바뀌었습니다. SDA는 A4, SCL은 A5입니다')
            elif ('uno', 'A4') not in sda.uno or ('uno', 'A5') not in scl.uno:
                self.warnings.append('LCD의 SDA는 A4, SCL은 A5에 연결해야 합니다')
        return False


SEG_NAMES = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'dp']


@register
class SevenSeg(Module):
    TYPE = 'seg7'
    NAME = '7세그먼트 (1자리)'
    CATEGORY = '표시 장치'
    DESC = 'a~g, dp를 디지털 핀에 연결합니다. COM은 캐소드형이면 GND, 애노드형이면 5V에 연결합니다.'
    SIZE = (116, 110)
    PINS = header(SEG_NAMES + ['COM'], 2, 128, 14)
    PROPS = {'common': 'cathode'}
    CONTROLS = [('choice', 'common', '공통 단자', [('cathode', '캐소드(−)'), ('anode', '애노드(+)')])]

    def update(self, net, now, board):
        self.warnings = []
        com = net('COM')
        lit = []
        cathode = self.props['common'] == 'cathode'
        for s in SEG_NAMES:
            n = net(s)
            on = 0.0
            if n.v is not None and com.v is not None:
                if cathode and n.v - com.v >= 1.8:
                    on = n.duty if n.duty is not None else (0.08 if n.pullup else 1.0)
                elif not cathode and com.v - n.v >= 1.8:
                    on = 1.0 - n.duty if n.duty is not None else 1.0
            lit.append(on)
        self.state['lit'] = lit
        if com.v is not None and com.strong:
            if cathode and com.v > 2.5:
                self.warnings.append('캐소드형 7세그먼트의 COM은 GND에 연결해야 합니다')
            if not cathode and com.v < 2.5:
                self.warnings.append('애노드형 7세그먼트의 COM은 5V에 연결해야 합니다')
        if any(net(s).n > 0 for s in SEG_NAMES) and com.n == 0:
            self.warnings.append('7세그먼트의 COM 핀이 연결되지 않았습니다')
        return False


@register
class Tm1637(Module):
    TYPE = 'tm1637'
    NAME = '4자리 7세그먼트 (TM1637)'
    CATEGORY = '표시 장치'
    DESC = 'CLK, DIO 두 핀으로 숫자 4자리를 표시합니다. TM1637Display 라이브러리를 씁니다.'
    SIZE = (170, 70)
    PINS = header(['CLK', 'DIO', 'VCC', 'GND'], 50, 88)
    POWER = ('VCC', 'GND')

    def reset(self):
        self.state['segs'] = [0, 0, 0, 0]
        self.state['brightness'] = 7
        self.state['on'] = True

    def update(self, net, now, board):
        self.warnings = []
        self.state['powered'] = self.check_power(net) is not None
        return False


@register
class Matrix(Module):
    TYPE = 'matrix'
    NAME = '8×8 도트 매트릭스 (MAX7219)'
    CATEGORY = '표시 장치'
    DESC = 'DIN, CS, CLK로 LED 64개를 제어합니다. LedControl 라이브러리를 쓰며, 먼저 shutdown(0, false)로 켜야 합니다.'
    SIZE = (130, 150)
    PINS = header(['VCC', 'GND', 'DIN', 'CS', 'CLK'], 25, 168)
    POWER = ('VCC', 'GND')

    def reset(self):
        self.state['rows'] = [0] * 8
        self.state['shutdown'] = True
        self.state['intensity'] = 8

    def update(self, net, now, board):
        self.warnings = []
        self.state['powered'] = self.check_power(net) is not None
        return False


# ---------------------------------------------------------------- 센서
class DigitalSensor(Module):
    """VCC, GND와 디지털 출력이 있는 모듈의 공통 부분."""
    OUT = 'OUT'

    def out_level(self):
        return 0

    def drive(self, net):
        vcc, gnd = net(self.POWER[0]), net(self.POWER[1])
        if vcc.v is None or vcc.v < 2.7 or gnd.v is None or gnd.v > 0.5:
            return {}
        return {self.OUT: vcc.v if self.out_level() else 0.0}

    def update(self, net, now, board):
        self.warnings = []
        self.state['powered'] = self.check_power(net) is not None
        self.state['out'] = self.out_level()
        return False


@register
class Ultrasonic(Module):
    TYPE = 'hcsr04'
    NAME = '초음파 센서 (HC-SR04)'
    CATEGORY = '센서'
    DESC = 'TRIG에 10µs 펄스를 보내고 pulseIn(ECHO, HIGH)로 시간을 잽니다. 거리(cm) = 시간(µs) ÷ 58.'
    SIZE = (130, 64)
    PINS = header(['VCC', 'TRIG', 'ECHO', 'GND'], 35, 82)
    POWER = ('VCC', 'GND')
    PIN_LABELS = {'TRIG': 'Trig', 'ECHO': 'Echo'}
    PROPS = {'distance': 30.0}
    LIVE = ('distance',)
    CONTROLS = [('slider', 'distance', '거리', 2, 400, 'cm')]

    def drive(self, net):
        vcc, gnd = net('VCC'), net('GND')
        if vcc.v is None or vcc.v < 2.7 or gnd.v is None or gnd.v > 0.5:
            return {}
        return {'ECHO': 0.0}

    def update(self, net, now, board):
        self.warnings = []
        self.state['powered'] = self.check_power(net) is not None
        return False


@register
class Dht(Module):
    TYPE = 'dht'
    NAME = '온습도 센서 (DHT)'
    CATEGORY = '센서'
    DESC = 'DATA 핀 하나로 온도와 습도를 보냅니다. DHT 라이브러리로 읽습니다.'
    SIZE = (56, 70)
    PINS = header(['VCC', 'DATA', 'GND'], 8, 88)
    POWER = ('VCC', 'GND')
    PIN_LABELS = {'VCC': '+', 'GND': '−'}
    PROPS = {'model': 'DHT11', 'temp': 24.0, 'humidity': 45.0}
    LIVE = ('temp', 'humidity')
    CONTROLS = [('choice', 'model', '종류', [('DHT11', 'DHT11 (파랑)'), ('DHT22', 'DHT22 (흰색)')]),
                ('slider', 'temp', '온도', -20, 60, '°C'), ('slider', 'humidity', '습도', 0, 100, '%')]

    def update(self, net, now, board):
        self.warnings = []
        self.state['powered'] = self.check_power(net) is not None
        return False


@register
class LightSensor(DigitalSensor):
    TYPE = 'ldr'
    NAME = '조도 센서 모듈'
    CATEGORY = '센서'
    DESC = '밝을수록 AO 값이 커집니다. 기준보다 어두우면 DO가 HIGH입니다.'
    SIZE = (90, 60)
    PINS = header(['VCC', 'GND', 'DO', 'AO'], 15, 78)
    POWER = ('VCC', 'GND')
    OUT = 'DO'
    PROPS = {'light': 60, 'threshold': 30}
    LIVE = ('light', 'threshold')
    CONTROLS = [('slider', 'light', '밝기', 0, 100, '%'), ('slider', 'threshold', 'DO 기준', 0, 100, '%')]

    def out_level(self):
        return 1 if self.props['light'] < self.props['threshold'] else 0

    def drive(self, net):
        d = super().drive(net)
        if d:
            d['AO'] = net('VCC').v * self.props['light'] / 100.0
        return d


@register
class SoundSensor(DigitalSensor):
    TYPE = 'sound'
    NAME = '사운드 센서 모듈'
    CATEGORY = '센서'
    DESC = '소리가 클수록 AO 값이 커집니다. 기준보다 크면 DO가 HIGH입니다.'
    SIZE = (90, 60)
    PINS = header(['VCC', 'GND', 'DO', 'AO'], 15, 78)
    POWER = ('VCC', 'GND')
    OUT = 'DO'
    PROPS = {'level': 10, 'threshold': 60}
    LIVE = ('level', 'threshold')
    CONTROLS = [('slider', 'level', '소리 크기', 0, 100, '%'), ('slider', 'threshold', 'DO 기준', 0, 100, '%')]

    def out_level(self):
        return 1 if self.props['level'] > self.props['threshold'] else 0

    def drive(self, net):
        d = super().drive(net)
        if d:
            d['AO'] = net('VCC').v * self.props['level'] / 100.0
        return d


@register
class Pir(DigitalSensor):
    TYPE = 'pir'
    NAME = 'PIR 동작 감지 센서'
    CATEGORY = '센서'
    DESC = '움직임을 감지하면 OUT이 HIGH입니다.'
    SIZE = (72, 72)
    PINS = header(['VCC', 'OUT', 'GND'], 16, 90)
    POWER = ('VCC', 'GND')
    PROPS = {'motion': False}
    LIVE = ('motion',)
    CONTROLS = [('check', 'motion', '움직임 있음')]

    def out_level(self):
        return 1 if self.props['motion'] else 0


@register
class Tilt(DigitalSensor):
    TYPE = 'tilt'
    NAME = '기울기 센서 모듈'
    CATEGORY = '센서'
    DESC = '기울이면 DO가 HIGH, 세우면 LOW입니다(SW-520D).'
    SIZE = (70, 50)
    PINS = header(['VCC', 'GND', 'DO'], 15, 68)
    POWER = ('VCC', 'GND')
    OUT = 'DO'
    PROPS = {'tilted': False}
    LIVE = ('tilted',)
    CONTROLS = [('check', 'tilted', '기울어짐')]

    def out_level(self):
        return 1 if self.props['tilted'] else 0


@register
class IrObstacle(DigitalSensor):
    TYPE = 'ir_obstacle'
    NAME = '적외선 장애물 센서'
    CATEGORY = '센서'
    DESC = '앞에 물체가 있으면 OUT이 LOW이고 초록 LED가 켜집니다.'
    SIZE = (90, 50)
    PINS = header(['VCC', 'GND', 'OUT'], 25, 68)
    POWER = ('VCC', 'GND')
    PROPS = {'obstacle': False}
    LIVE = ('obstacle',)
    CONTROLS = [('check', 'obstacle', '물체 있음')]

    def out_level(self):
        return 0 if self.props['obstacle'] else 1


@register
class TempSensor(Module):
    TYPE = 'temp_sensor'
    NAME = '온도 센서 (LM35/TMP36)'
    CATEGORY = '센서'
    DESC = 'Vout 전압이 온도에 비례합니다. LM35는 10mV/°C, TMP36은 0.5V + 10mV/°C입니다.'
    SIZE = (40, 46)
    PINS = header(['VS', 'OUT', 'GND'], 0, 70)
    POWER = ('VS', 'GND')
    PIN_LABELS = {'VS': '+Vs', 'OUT': 'Vout'}
    PROPS = {'model': 'LM35', 'temp': 25.0}
    LIVE = ('temp',)
    CONTROLS = [('choice', 'model', '종류', [('LM35', 'LM35'), ('TMP36', 'TMP36')]),
                ('slider', 'temp', '온도', -40, 125, '°C')]

    def drive(self, net):
        vcc, gnd = net('VS'), net('GND')
        if vcc.v is None or vcc.v < 2.7 or gnd.v is None or gnd.v > 0.5:
            return {}
        t = float(self.props['temp'])
        v = max(0.0, t * 0.01) if self.props['model'] == 'LM35' else max(0.0, 0.5 + t * 0.01)
        return {'OUT': min(v, vcc.v)}

    def update(self, net, now, board):
        self.warnings = []
        self.state['powered'] = self.check_power(net) is not None
        return False


def ordered_types():
    out = []
    for cat in CATEGORIES:
        out.append((cat, [c for c in TYPES.values() if c.CATEGORY == cat]))
    return out
