"""스케치에서 쓰는 라이브러리 객체. 실제 장치 상태는 배선으로 찾은 모듈에 기록합니다.

메서드 이름은 m_<스케치에서 부르는 이름>, 인자는 (값 목록, 자료형 목록)입니다.
API 표: 이름 → (돌려주는 자료형, 최소 인자 수, 최대 인자 수)
"""
import math


class LibError(Exception):
    pass


def _i(v):
    if isinstance(v, float):
        if v != v:
            return 0
        return int(v)
    if isinstance(v, str):
        raise _run_error('문자열을 숫자 자리에 넣었습니다')
    return int(v)


def _run_error(msg):
    from .interpreter import RunError
    return RunError(msg)


def _text(v, t, fmt=None):
    from .interpreter import to_text
    return to_text(v, t, fmt)


class LibObject:
    API = {}

    def __init__(self, m, args, line):
        self.m = m
        self.board = m.board
        self.line = line


# ---------------------------------------------------------------- Servo
class Servo(LibObject):
    API = {'attach': ('uchar', 1, 3), 'detach': ('void', 0, 0), 'write': ('void', 1, 1),
           'writeMicroseconds': ('void', 1, 1), 'read': ('int', 0, 0), 'readMicroseconds': ('int', 0, 0),
           'attached': ('bool', 0, 0)}

    def __init__(self, m, args, line):
        super().__init__(m, args, line)
        if args:
            raise _run_error('Servo는 인자 없이 선언합니다. 예: Servo myServo;')
        self.pin = None
        self.angle = 90
        self.min_us, self.max_us = 544, 2400

    def m_attach(self, a, t):
        p = _i(a[0])
        if not 0 <= p <= 19:
            raise _run_error(f'{p}번 핀은 없습니다')
        if len(a) >= 3:
            self.min_us, self.max_us = _i(a[1]), _i(a[2])
        self.pin = p
        self.board.servo_attach(p, self.angle)
        return 1

    def m_detach(self, a, t):
        if self.pin is not None:
            self.board.servo_detach(self.pin)
        self.pin = None

    def m_write(self, a, t):
        v = _i(a[0])
        if v >= self.min_us and v > 200:          # 큰 값은 마이크로초로 해석(실제 라이브러리와 같음)
            return self.m_writeMicroseconds([v], t)
        self.angle = max(0, min(180, v))
        if self.pin is None:
            self.m.warn('servo-attach', 'Servo.write() 전에 attach()로 핀을 지정해야 합니다')
            return
        self.board.servo_write(self.pin, self.angle)

    def m_writeMicroseconds(self, a, t):
        us = max(self.min_us, min(self.max_us, _i(a[0])))
        self.angle = round((us - self.min_us) * 180 / (self.max_us - self.min_us))
        if self.pin is not None:
            self.board.servo_write(self.pin, self.angle)

    def m_read(self, a, t):
        return self.angle

    def m_readMicroseconds(self, a, t):
        return round(self.min_us + self.angle * (self.max_us - self.min_us) / 180)

    def m_attached(self, a, t):
        return 1 if self.pin is not None else 0


# ---------------------------------------------------------------- LCD 1602 (I2C)
class LiquidCrystal_I2C(LibObject):
    API = {'init': ('void', 0, 0), 'begin': ('void', 0, 3), 'backlight': ('void', 0, 0),
           'noBacklight': ('void', 0, 0), 'setBacklight': ('void', 1, 1), 'clear': ('void', 0, 0),
           'home': ('void', 0, 0), 'setCursor': ('void', 2, 2), 'print': ('uint', 1, 2),
           'println': ('uint', 0, 2), 'write': ('uint', 1, 1), 'cursor': ('void', 0, 0),
           'noCursor': ('void', 0, 0), 'blink': ('void', 0, 0), 'noBlink': ('void', 0, 0),
           'display': ('void', 0, 0), 'noDisplay': ('void', 0, 0), 'scrollDisplayLeft': ('void', 0, 0),
           'scrollDisplayRight': ('void', 0, 0), 'createChar': ('void', 2, 2),
           'leftToRight': ('void', 0, 0), 'rightToLeft': ('void', 0, 0),
           'autoscroll': ('void', 0, 0), 'noAutoscroll': ('void', 0, 0)}

    def __init__(self, m, args, line):
        super().__init__(m, args, line)
        if len(args) != 3:
            raise _run_error('형식: LiquidCrystal_I2C lcd(0x27, 16, 2);')
        self.addr, self.cols, self.rows = (_i(x) for x in args)
        self.backlight_on = False

    def lcd(self):
        mod = self.board.find_i2c(self.addr)
        if mod is None:
            self.m.warn(('lcd', self.addr),
                        f'I2C 주소 0x{self.addr:02X}에서 LCD를 찾지 못했습니다. '
                        f'SDA→A4, SCL→A5, 전원 연결과 주소 설정을 확인하십시오')
        return mod

    def _do(self, fn):
        mod = self.lcd()
        self.m.t += 120
        if mod is not None:
            with self.board.lock:
                fn(mod.lcd)
            self.board.touch()

    def m_init(self, a, t):
        self._do(lambda s: s.init(self.backlight_on))

    def m_begin(self, a, t):
        self.m_init(a, t)

    def m_backlight(self, a, t):
        self.backlight_on = True
        self._do(lambda s: setattr(s, 'backlight', True))

    def m_noBacklight(self, a, t):
        self.backlight_on = False
        self._do(lambda s: setattr(s, 'backlight', False))

    def m_setBacklight(self, a, t):
        (self.m_backlight if _i(a[0]) else self.m_noBacklight)([], [])

    def m_clear(self, a, t):
        self._do(lambda s: s.clear())
        self.m.t += 1500

    def m_home(self, a, t):
        self._do(lambda s: s.set_cursor(0, 0))
        self.m.t += 1500

    def m_setCursor(self, a, t):
        c, r = _i(a[0]), _i(a[1])
        if r >= self.rows:
            r = self.rows - 1
        self._do(lambda s: s.set_cursor(c, r))

    def m_print(self, a, t):
        text = _text(a[0], t[0], a[1] if len(a) > 1 else None)
        self._do(lambda s: s.write_text(text))
        self.m.t += 100 * len(text)
        return len(text)

    def m_println(self, a, t):
        text = (_text(a[0], t[0], a[1] if len(a) > 1 else None) if a else '') + '\r\n'
        self._do(lambda s: s.write_text(text))
        return len(text)

    def m_write(self, a, t):
        v = a[0]
        text = v if isinstance(v, str) else chr(_i(v) & 0xFF)
        self._do(lambda s: s.write_text(text))
        return len(text)

    def m_cursor(self, a, t):
        self._do(lambda s: setattr(s, 'show_cursor', True))

    def m_noCursor(self, a, t):
        self._do(lambda s: setattr(s, 'show_cursor', False))

    def m_blink(self, a, t):
        self._do(lambda s: setattr(s, 'blink', True))

    def m_noBlink(self, a, t):
        self._do(lambda s: setattr(s, 'blink', False))

    def m_display(self, a, t):
        self._do(lambda s: setattr(s, 'display_on', True))

    def m_noDisplay(self, a, t):
        self._do(lambda s: setattr(s, 'display_on', False))

    def m_scrollDisplayLeft(self, a, t):
        self._do(lambda s: s.scroll(1))

    def m_scrollDisplayRight(self, a, t):
        self._do(lambda s: s.scroll(-1))

    def m_createChar(self, a, t):
        n = _i(a[0]) & 7
        rows = a[1]
        if not isinstance(rows, list):
            raise _run_error('createChar()의 두 번째 인자는 byte 배열이어야 합니다')
        data = [(_i(x) & 0x1F) for x in rows[:8]] + [0] * (8 - len(rows[:8]))
        self._do(lambda s: s.custom.__setitem__(n, data))

    def m_leftToRight(self, a, t):
        self._do(lambda s: setattr(s, 'ltr', True))

    def m_rightToLeft(self, a, t):
        self._do(lambda s: setattr(s, 'ltr', False))

    def m_autoscroll(self, a, t):
        pass

    def m_noAutoscroll(self, a, t):
        pass


class LcdState:
    """HD44780 표시 상태(한 줄 40칸 메모리, 화면은 16칸 창)."""

    def __init__(self, cols=16, rows=2):
        self.cols, self.rows = cols, rows
        self.reset()

    def reset(self):
        self.ram = [[' '] * 40 for _ in range(self.rows)]
        self.col = self.row = 0
        self.shift = 0
        self.initialized = False
        self.backlight = False
        self.display_on = True
        self.show_cursor = False
        self.blink = False
        self.ltr = True
        self.custom = {}

    def init(self, backlight):
        self.reset()
        self.initialized = True
        self.backlight = backlight

    def clear(self):
        self.ram = [[' '] * 40 for _ in range(self.rows)]
        self.col = self.row = 0
        self.shift = 0

    def set_cursor(self, c, r):
        self.col = max(0, min(39, c))
        self.row = max(0, min(self.rows - 1, r))

    def write_text(self, text):
        if not self.initialized:
            return
        for ch in text:
            code = ord(ch)
            if code < 8:
                ch = chr(code)       # 사용자 정의 문자 번호
            elif code > 0x7E and code not in (0xDF,):
                ch = '?'
            self.ram[self.row][self.col] = ch
            if self.ltr:
                self.col += 1
                if self.col >= 40:
                    self.col = 0
                    self.row = (self.row + 1) % self.rows
            else:
                self.col = max(0, self.col - 1)

    def scroll(self, d):
        self.shift = (self.shift + d) % 40

    def visible(self):
        """화면에 보이는 글자: rows × cols 문자열 목록."""
        out = []
        for r in range(self.rows):
            out.append(''.join(self.ram[r][(self.shift + c) % 40] for c in range(self.cols)))
        return out


# ---------------------------------------------------------------- DHT
class DHT(LibObject):
    API = {'begin': ('void', 0, 1), 'readTemperature': ('float', 0, 2), 'readHumidity': ('float', 0, 1),
           'computeHeatIndex': ('float', 2, 3), 'convertCtoF': ('float', 1, 1), 'convertFtoC': ('float', 1, 1),
           'read': ('bool', 0, 1)}

    def __init__(self, m, args, line):
        super().__init__(m, args, line)
        if len(args) < 2:
            raise _run_error('형식: DHT dht(핀, DHT11);')
        self.pin = _i(args[0])
        self.kind = _i(args[1])
        self.started = False

    def sensor(self):
        mod = self.board.find_module_on_pins(('dht',), {'DATA': self.pin})
        if mod is None:
            self.m.warn(('dht', self.pin), f'{self.pin}번 핀에 연결된 DHT 센서가 없습니다. DATA 배선을 확인하십시오')
            return None
        if not self.board.powered(mod):
            self.m.warn(('dht-pwr', self.pin), 'DHT 센서에 전원(VCC, GND)이 연결되지 않았습니다')
            return None
        model = 11 if mod.props.get('model') == 'DHT11' else 22
        if model != (11 if self.kind == 11 else 22):
            self.m.warn(('dht-kind', self.pin), f'스케치는 DHT{self.kind}, 연결된 센서는 DHT{model}입니다')
            return None
        if not self.started:
            self.m.warn(('dht-begin', self.pin), 'dht.begin()이 없습니다. setup()에서 호출하십시오')
        return mod

    def m_begin(self, a, t):
        self.started = True

    def m_read(self, a, t):
        self.m.t += 5000
        return 1 if self.sensor() is not None else 0

    def m_readTemperature(self, a, t):
        self.m.t += 5000
        mod = self.sensor()
        if mod is None:
            return math.nan
        v = float(mod.props['temp'])
        v = round(v) if mod.props.get('model') == 'DHT11' else round(v, 1)
        if a and a[0]:
            v = v * 1.8 + 32
        return float(v)

    def m_readHumidity(self, a, t):
        self.m.t += 5000
        mod = self.sensor()
        if mod is None:
            return math.nan
        v = float(mod.props['humidity'])
        return float(round(v) if mod.props.get('model') == 'DHT11' else round(v, 1))

    def m_convertCtoF(self, a, t):
        return a[0] * 1.8 + 32

    def m_convertFtoC(self, a, t):
        return (a[0] - 32) / 1.8

    def m_computeHeatIndex(self, a, t):
        temp, hum = float(a[0]), float(a[1])
        is_f = bool(a[2]) if len(a) > 2 else True
        tf = temp if is_f else temp * 1.8 + 32
        hi = 0.5 * (tf + 61.0 + ((tf - 68.0) * 1.2) + (hum * 0.094))
        if hi > 79:
            hi = (-42.379 + 2.04901523 * tf + 10.14333127 * hum - .22475541 * tf * hum
                  - .00683783 * tf * tf - .05481717 * hum * hum + .00122874 * tf * tf * hum
                  + .00085282 * tf * hum * hum - .00000199 * tf * tf * hum * hum)
        return hi if is_f else (hi - 32) / 1.8


# ---------------------------------------------------------------- TM1637 4자리 7세그먼트
DIGIT_SEGS = [0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F, 0x77, 0x7C, 0x39, 0x5E, 0x79, 0x71]


class TM1637Display(LibObject):
    API = {'setBrightness': ('void', 1, 2), 'showNumberDec': ('void', 1, 4), 'showNumberDecEx': ('void', 1, 5),
           'showNumberHexEx': ('void', 1, 5), 'setSegments': ('void', 1, 3), 'clear': ('void', 0, 0),
           'encodeDigit': ('uchar', 1, 1)}

    def __init__(self, m, args, line):
        super().__init__(m, args, line)
        if len(args) < 2:
            raise _run_error('형식: TM1637Display display(CLK, DIO);')
        self.clk, self.dio = _i(args[0]), _i(args[1])
        self.brightness = 7
        self.on = True

    def disp(self):
        mod = self.board.find_module_on_pins(('tm1637',), {'CLK': self.clk, 'DIO': self.dio})
        if mod is None:
            self.m.warn(('tm', self.clk), f'CLK={self.clk}, DIO={self.dio}번 핀에 연결된 TM1637이 없습니다')
        elif not self.board.powered(mod):
            self.m.warn(('tm-pwr', self.clk), 'TM1637에 전원(VCC, GND)이 연결되지 않았습니다')
            return None
        return mod

    def _set(self, segs, pos=0):
        self.m.t += 800
        mod = self.disp()
        if mod is None:
            return
        with self.board.lock:
            st = mod.state
            for k, s in enumerate(segs):
                if 0 <= pos + k < 4:
                    st['segs'][pos + k] = s & 0xFF
            st['brightness'] = self.brightness
            st['on'] = self.on
        self.board.touch()

    def m_setBrightness(self, a, t):
        self.brightness = max(0, min(7, _i(a[0])))
        self.on = bool(a[1]) if len(a) > 1 else True
        mod = self.disp()
        if mod is not None:
            mod.state['brightness'] = self.brightness
            mod.state['on'] = self.on
            self.board.touch()

    def m_clear(self, a, t):
        self._set([0, 0, 0, 0])

    def m_encodeDigit(self, a, t):
        return DIGIT_SEGS[_i(a[0]) & 0x0F]

    def m_setSegments(self, a, t):
        segs = a[0]
        if not isinstance(segs, list):
            raise _run_error('setSegments()에는 byte 배열이 필요합니다')
        length = _i(a[1]) if len(a) > 1 else len(segs)
        pos = _i(a[2]) if len(a) > 2 else 0
        self._set([_i(x) for x in segs[:length]], pos)

    def _number(self, num, dots, leading, length, pos, base):
        num = _i(num)
        neg = num < 0 and base == 10
        n = abs(num)
        digits = []
        for _ in range(length):
            digits.append(n % base)
            n //= base
        digits.reverse()
        segs = []
        started = False
        for k, d in enumerate(digits):
            if d or leading or k == length - 1 or started:
                segs.append(DIGIT_SEGS[d])
                started = True
            else:
                segs.append(0)
        if neg:
            for k in range(length):
                if segs[k] == 0 and (k == length - 1 or segs[k + 1] != 0):
                    segs[k] = 0x40
                    break
        for k in range(length):
            if dots & (0x80 >> k):
                segs[k] |= 0x80
        self._set(segs, pos)

    def m_showNumberDec(self, a, t):
        leading = bool(a[1]) if len(a) > 1 else False
        length = _i(a[2]) if len(a) > 2 else 4
        pos = _i(a[3]) if len(a) > 3 else 0
        self._number(a[0], 0, leading, length, pos, 10)

    def m_showNumberDecEx(self, a, t):
        dots = _i(a[1]) if len(a) > 1 else 0
        leading = bool(a[2]) if len(a) > 2 else False
        length = _i(a[3]) if len(a) > 3 else 4
        pos = _i(a[4]) if len(a) > 4 else 0
        self._number(a[0], dots, leading, length, pos, 10)

    def m_showNumberHexEx(self, a, t):
        dots = _i(a[1]) if len(a) > 1 else 0
        leading = bool(a[2]) if len(a) > 2 else False
        length = _i(a[3]) if len(a) > 3 else 4
        pos = _i(a[4]) if len(a) > 4 else 0
        self._number(_i(a[0]) & 0xFFFF, dots, leading, length, pos, 16)


# ---------------------------------------------------------------- MAX7219 8x8 (LedControl)
class LedControl(LibObject):
    API = {'shutdown': ('void', 2, 2), 'setIntensity': ('void', 2, 2), 'clearDisplay': ('void', 1, 1),
           'setLed': ('void', 4, 4), 'setRow': ('void', 3, 3), 'setColumn': ('void', 3, 3),
           'getDeviceCount': ('int', 0, 0), 'setScanLimit': ('void', 2, 2)}

    def __init__(self, m, args, line):
        super().__init__(m, args, line)
        if len(args) < 3:
            raise _run_error('형식: LedControl lc(DIN, CLK, CS, 1);')
        self.din, self.clk, self.cs = (_i(x) for x in args[:3])
        self.count = _i(args[3]) if len(args) > 3 else 1

    def mat(self, addr):
        if _i(addr) != 0:
            self.m.warn('lc-addr', '모듈이 하나이므로 주소(addr)는 0만 씁니다')
            return None
        mod = self.board.find_module_on_pins(('matrix',), {'DIN': self.din, 'CLK': self.clk, 'CS': self.cs})
        if mod is None:
            self.m.warn(('lc', self.din), f'DIN={self.din}, CLK={self.clk}, CS={self.cs}번 핀에 연결된 8x8 매트릭스가 없습니다')
            return None
        if not self.board.powered(mod):
            self.m.warn(('lc-pwr', self.din), '8x8 매트릭스에 전원(VCC, GND)이 연결되지 않았습니다')
            return None
        return mod

    def _edit(self, addr, fn):
        self.m.t += 200
        mod = self.mat(addr)
        if mod is not None:
            with self.board.lock:
                fn(mod.state)
            self.board.touch()

    def m_getDeviceCount(self, a, t):
        return self.count

    def m_shutdown(self, a, t):
        self._edit(a[0], lambda s: s.__setitem__('shutdown', bool(a[1])))

    def m_setIntensity(self, a, t):
        self._edit(a[0], lambda s: s.__setitem__('intensity', max(0, min(15, _i(a[1])))))

    def m_setScanLimit(self, a, t):
        pass

    def m_clearDisplay(self, a, t):
        self._edit(a[0], lambda s: s.__setitem__('rows', [0] * 8))

    def m_setLed(self, a, t):
        row, col, on = _i(a[1]), _i(a[2]), bool(a[3])
        if not (0 <= row < 8 and 0 <= col < 8):
            return

        def fn(s):
            bit = 0x80 >> col
            s['rows'][row] = (s['rows'][row] | bit) if on else (s['rows'][row] & ~bit)
        self._edit(a[0], fn)

    def m_setRow(self, a, t):
        row = _i(a[1])
        if 0 <= row < 8:
            self._edit(a[0], lambda s: s['rows'].__setitem__(row, _i(a[2]) & 0xFF))

    def m_setColumn(self, a, t):
        col = _i(a[1])
        val = _i(a[2]) & 0xFF
        if not 0 <= col < 8:
            return

        def fn(s):
            bit = 0x80 >> col
            for r in range(8):
                if val & (0x80 >> r):
                    s['rows'][r] |= bit
                else:
                    s['rows'][r] &= ~bit
        self._edit(a[0], fn)


# ---------------------------------------------------------------- Wire (I2C)
WIRE_API = {'begin': ('void', 0, 1), 'beginTransmission': ('void', 1, 1), 'write': ('uint', 1, 1),
            'endTransmission': ('uchar', 0, 1), 'requestFrom': ('uchar', 2, 3), 'available': ('int', 0, 0),
            'read': ('int', 0, 0), 'setClock': ('void', 1, 1)}


class Wire:
    @staticmethod
    def m_begin(m, a):
        m.board.wire_started = True

    @staticmethod
    def m_setClock(m, a):
        pass

    @staticmethod
    def m_beginTransmission(m, a):
        m.board.wire_addr = _i(a[0])

    @staticmethod
    def m_write(m, a):
        m.t += 100
        return 1

    @staticmethod
    def m_endTransmission(m, a):
        m.t += 200
        addr = getattr(m.board, 'wire_addr', None)
        return 0 if addr is not None and m.board.find_i2c(addr, quiet=True) is not None else 2

    @staticmethod
    def m_requestFrom(m, a):
        return 0

    @staticmethod
    def m_available(m, a):
        return 0

    @staticmethod
    def m_read(m, a):
        return -1


CLASSES = {'Servo': Servo, 'LiquidCrystal_I2C': LiquidCrystal_I2C, 'DHT': DHT,
           'TM1637Display': TM1637Display, 'LedControl': LedControl}
