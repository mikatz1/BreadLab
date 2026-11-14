"""가상 Arduino UNO(arduino_lab) 테스트: 인터프리터, 모듈 동작, 저장 형식, 예제.

실행: .venv\\Scripts\\python -m unittest test_arduino -v
"""
import json
import math
import os
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from arduino_lab import examples as EX  # noqa: E402
from arduino_lab import modules as M  # noqa: E402
from arduino_lab.board import Board, Wire  # noqa: E402
from arduino_lab.interpreter import Machine  # noqa: E402
from arduino_lab.lang import SketchError  # noqa: E402


# 예제에서 빠졌지만 모듈 동작 확인에 쓰는 스케치
POT = '''void setup() { Serial.begin(9600); }
void loop() {
  int value = analogRead(A0);
  Serial.print("A0 = ");
  Serial.println(value);
  delay(200);
}
'''

LCD = '''#include <Wire.h>
#include <LiquidCrystal_I2C.h>
LiquidCrystal_I2C lcd(0x27, 16, 2);
void setup() {
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("Hello, BreadLab");
}
void loop() {
  lcd.setCursor(0, 1);
  lcd.print("Time: ");
  lcd.print(millis() / 1000);
  lcd.print(" s   ");
  delay(250);
}
'''

ULTRASONIC = '''const int trigPin = 7;
const int echoPin = 6;
void setup() {
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);
  Serial.begin(9600);
}
void loop() {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  long duration = pulseIn(echoPin, HIGH);
  Serial.print("거리: ");
  Serial.print(duration / 58.0, 1);
  Serial.println(" cm");
  delay(300);
}
'''

DHT_SKETCH = '''#include <DHT.h>
DHT dht(2, DHT11);
void setup() { Serial.begin(9600); dht.begin(); }
void loop() {
  delay(2000);
  float h = dht.readHumidity();
  float t = dht.readTemperature();
  if (isnan(h) || isnan(t)) { Serial.println("센서를 읽지 못했어요"); return; }
  Serial.print("온도: "); Serial.print(t); Serial.print(" 습도: "); Serial.println(h);
}
'''

MATRIX = '''#include <LedControl.h>
LedControl lc(12, 10, 11, 1);
byte heart[8] = {B00000000, B01100110, B11111111, B11111111, B01111110, B00111100, B00011000, B00000000};
void setup() { lc.shutdown(0, false); lc.setIntensity(0, 8); lc.clearDisplay(0); }
void loop() {
  for (int r = 0; r < 8; r++) lc.setRow(0, r, heart[r]);
  delay(600);
  lc.clearDisplay(0);
  delay(300);
}
'''


def setup_loop(setup='', loop='', globals_=''):
    return f'{globals_}\nvoid setup() {{\n{setup}\n}}\nvoid loop() {{\n{loop}\n}}\n'


class Rig:
    """보드 + 기계 + 모듈 묶음. 끝나면 stop()."""

    def __init__(self, src, mods=(), wires=()):
        self.board = Board()
        self.m = Machine(self.board)
        self.mods = {}
        for t, mid, props in mods:
            mod = M.TYPES[t](mid, props)
            self.board.add_module(mod)
            self.mods[mid] = mod
        for a, b in wires:
            self.board.add_wire(Wire(a, b))
        self.m.load(src)

    def run(self, ms):
        self.m.run_for(ms)
        self.board.solve()
        return self

    def out(self):
        return ''.join(self.m.serial_out)

    def warnings(self):
        return [w for w, _ in self.board.all_warnings()]

    def stop(self):
        self.m.stop()


class SketchCase(unittest.TestCase):
    def setUp(self):
        self.rigs = []

    def tearDown(self):
        for r in self.rigs:
            r.stop()

    def rig(self, src, mods=(), wires=()):
        r = Rig(src, mods, wires)
        self.rigs.append(r)
        return r

    def output(self, body, ms=5, globals_=''):
        """setup()에서 body를 실행하고 시리얼 출력을 돌려줍니다."""
        r = self.rig(setup_loop('Serial.begin(115200);\n' + body, 'delay(1000);', globals_))
        r.run(ms)
        self.assertEqual(r.m.state, 'running', r.m.error)
        return r.out()

    def compile_error(self, src):
        with self.assertRaises(SketchError) as cm:
            Machine(Board()).load(src)
        return cm.exception


# ---------------------------------------------------------------- 언어
class LanguageTests(SketchCase):
    def test_int_is_16_bit(self):
        out = self.output('int a = 30000; int b = a + a; Serial.println(b);'
                          'long c = 60 * 1000; Serial.println(c);'
                          'long d = 60L * 1000; Serial.println(d);'
                          'unsigned int u = 0; u--; Serial.println(u);'
                          'byte x = 250; x += 10; Serial.println(x);')
        self.assertEqual(out.split(), ['-5536', '-5536', '60000', '65535', '4'])

    def test_division_and_modulo(self):
        out = self.output('Serial.println(7 / 2); Serial.println(-7 / 2); Serial.println(-7 % 3);'
                          'Serial.println(7.0 / 2); float f = 10 / 4; Serial.println(f);'
                          'Serial.println(1.0 / 3, 4);')
        self.assertEqual(out.split(), ['3', '-3', '-1', '3.50', '2.00', '0.3333'])

    def test_print_formats(self):
        out = self.output("char c = 'A'; Serial.println(c); Serial.println(c + 1); Serial.println(255, HEX);"
                          'Serial.println(5, BIN); Serial.println(-1, HEX); Serial.println(true);'
                          'Serial.print("a"); Serial.print(1.5); Serial.println();')
        self.assertEqual(out.split(), ['A', '66', 'FF', '101', 'FFFFFFFF', '1', 'a1.50'])

    def test_control_flow(self):
        src = '''
int sum = 0;
for (int i = 0; i < 10; i++) { if (i == 3) continue; if (i == 8) break; sum += i; }
Serial.println(sum);
int n = 0; while (n < 5) n++; Serial.println(n);
int k = 10; do { k--; } while (k > 7); Serial.println(k);
for (int v = 0; v < 4; v++) {
  switch (v) { case 0: Serial.print("z"); case 1: Serial.print("o"); break; default: Serial.print("d"); }
}
Serial.println();
Serial.println(n > 3 ? "big" : "small");
'''
        self.assertEqual(self.output(src).split(), ['25', '5', '7', 'zoodd', 'big'])

    def test_functions_recursion_refs_defaults(self):
        g = '''
long fact(int n) { if (n <= 1) return 1; return n * fact(n - 1); }
void swap(int &a, int &b) { int t = a; a = b; b = t; }
int add(int a, int b = 10) { return a + b; }
int counter() { static int c = 0; c++; return c; }
'''
        out = self.output('Serial.println(fact(10)); int x = 1, y = 2; swap(x, y); Serial.print(x); Serial.println(y);'
                          'Serial.println(add(1)); Serial.println(add(1, 2)); counter(); counter(); Serial.println(counter());',
                          globals_=g)
        self.assertEqual(out.split(), ['3628800', '21', '11', '3', '3'])

    def test_arrays_sizeof_defines_enum(self):
        g = '''
#define N 4
#define SQ(x) ((x) * (x))
enum Color { RED, GREEN = 5, BLUE };
int a[N] = {1, 2, 3};
int grid[2][3] = {{1, 2, 3}, {4, 5, 6}};
char greet[] = "hey";
'''
        out = self.output('int s = 0; for (int i = 0; i < sizeof(a) / sizeof(a[0]); i++) s += a[i];'
                          'Serial.println(s); Serial.println(grid[1][2]); Serial.println(SQ(1 + 2));'
                          'Serial.println(BLUE); Serial.println(greet); Serial.println(sizeof(greet));', globals_=g)
        self.assertEqual(out.split(), ['6', '6', '9', '6', 'hey', '4'])

    def test_string_class(self):
        out = self.output('String s = "Hello"; s += " "; s += 42; Serial.println(s);'
                          'Serial.println(s.length()); Serial.println(s.substring(1, 4)); Serial.println(s.indexOf("42"));'
                          'String t = "  12abc "; t.trim(); Serial.println(t.toInt() + 1); t.toUpperCase(); Serial.println(t);'
                          'Serial.println(String(3.14159, 3)); Serial.println(String(255, HEX)); Serial.println(s == "Hello 42");'
                          "Serial.println(s.charAt(0)); s.replace(\"l\", \"L\"); Serial.println(s);")
        self.assertEqual(out.split('\r\n')[:-1], ['Hello 42', '8', 'ell', '6', '13', '12ABC', '3.142', 'ff', '1',
                                                  'H', 'HeLLo 42'])

    def test_c_string_functions(self):
        out = self.output('char buf[24]; sprintf(buf, "T=%d.%02d %s|%5d|%-3d|%x", 23, 5, "ok", 42, 7, 255);'
                          'Serial.println(buf); char fb[10]; dtostrf(3.14159, 6, 2, fb); Serial.println(fb);'
                          'sprintf(buf, "%f", 1.5); Serial.println(buf); Serial.println(atoi("123x") + 1);'
                          'strcpy(buf, "ab"); strcat(buf, "cd"); Serial.println(buf); Serial.println(strlen(buf));'
                          'Serial.println(strcmp(buf, "abcd") == 0); String s = buf; Serial.println(s + "!");')
        self.assertEqual(out.split('\r\n')[:-1], ['T=23.05 ok|   42|7  |ff', '  3.14', '?', '124', 'abcd', '4', '1',
                                                  'abcd!'])
        r = self.rig(setup_loop('char small[4]; sprintf(small, "%d", 12345);'))
        r.run(5)
        self.assertEqual(r.m.state, 'error')
        self.assertIn('char 배열이 작습니다', r.m.error.msg)

    def test_math_builtins(self):
        out = self.output('Serial.println(map(512, 0, 1023, 0, 255)); Serial.println(constrain(300, 0, 255));'
                          'Serial.println(min(3, -2)); Serial.println(abs(-7)); Serial.println(sqrt(16));'
                          'Serial.println(pow(2, 10)); Serial.println(round(2.5)); Serial.println(bitRead(5, 2));'
                          'byte b = 0; bitSet(b, 3); Serial.println(b); Serial.println(highByte(0x1234), HEX);'
                          'randomSeed(1); long r = random(10, 20); Serial.println(r >= 10 && r < 20);')
        self.assertEqual(out.split(), ['127', '255', '-2', '7', '4.00', '1024.00', '3', '1', '8', '12', '1'])

    def test_millis_and_delay(self):
        r = self.rig(setup_loop('Serial.begin(9600);', 'delay(1000); Serial.println(millis());'))
        r.run(3100)
        vals = [int(x) for x in r.out().split()]
        self.assertEqual(len(vals), 3)
        for k, v in enumerate(vals, 1):
            self.assertAlmostEqual(v, 1000 * k, delta=15)
        # 가상 시간은 요청한 만큼만 진행합니다
        self.assertAlmostEqual(r.m.t / 1000, 3100, delta=2)

    def test_serial_input(self):
        r = self.rig(setup_loop('Serial.begin(9600);',
                                'if (Serial.available()) { int v = Serial.parseInt(); Serial.println(v * 2); '
                                'String rest = Serial.readStringUntil(\'\\n\'); Serial.println(rest); }'))
        r.run(10)
        r.m.feed_serial('21 abc\n')
        r.run(50)
        self.assertEqual(r.out().split('\r\n')[:2], ['42', ' abc'])

    def test_serial_without_begin_warns(self):
        r = self.rig(setup_loop('Serial.println("x");', 'delay(100);'))
        r.run(10)
        self.assertEqual(r.out(), '')
        self.assertTrue(any('Serial.begin' in w for w in r.warnings()))

    def test_interrupts(self):
        g = 'volatile int hits = 0;\nvoid onPress() { hits++; }'
        src = setup_loop('Serial.begin(9600); pinMode(2, INPUT_PULLUP);'
                         'attachInterrupt(digitalPinToInterrupt(2), onPress, FALLING);',
                         'delay(10);', g)
        src = src.replace('delay(10);', 'static int last = 0; if (hits != last) { last = hits; Serial.println(hits); } delay(10);')
        r = self.rig(src, [('button', 'b', {})], [(('b', '1'), ('uno', 'D2')), (('b', '2'), ('uno', 'GND.1'))])
        r.run(50)
        for _ in range(2):
            r.mods['b'].props['pressed'] = True
            r.board.touch()
            r.run(30)
            r.mods['b'].props['pressed'] = False
            r.board.touch()
            r.run(30)
        self.assertEqual(r.out().split(), ['1', '2'])


class ErrorTests(SketchCase):
    def test_missing_semicolon_points_to_line(self):
        e = self.compile_error('void setup() {\n  int a = 1\n  a++;\n}\nvoid loop() {}\n')
        self.assertEqual(e.line, 2)
        self.assertIn(';', e.msg)

    def test_undeclared(self):
        e = self.compile_error('void setup() {\n  x = 3;\n}\nvoid loop() {}')
        self.assertEqual(e.line, 2)
        self.assertIn("'x'", e.msg)

    def test_missing_loop(self):
        e = self.compile_error('void setup() {}')
        self.assertIn('loop()', e.msg)

    def test_unknown_library_and_missing_include(self):
        e = self.compile_error('#include <Foo.h>\nvoid setup() {}\nvoid loop() {}')
        self.assertIn('Foo.h', e.msg)
        e = self.compile_error('Servo s;\nvoid setup() {}\nvoid loop() {}')
        self.assertIn('#include <Servo.h>', e.msg)

    def test_string_literal_plus(self):
        e = self.compile_error('void setup() { Serial.println("a" + 1); }\nvoid loop() {}')
        self.assertIn('String', e.msg)

    def test_const_assignment(self):
        e = self.compile_error('const int p = 3;\nvoid setup() {\n p = 4;\n}\nvoid loop() {}')
        self.assertEqual(e.line, 3)

    def test_runtime_array_bounds(self):
        r = self.rig('int a[3];\nvoid setup() {\n  for (int i = 0; i <= 3; i++)\n    a[i] = i;\n}\nvoid loop() {}')
        r.run(10)
        self.assertEqual(r.m.state, 'error')
        self.assertEqual(r.m.error.line, 4)
        self.assertIn('범위', r.m.error.msg)

    def test_runtime_division_by_zero(self):
        r = self.rig('int z = 0;\nvoid setup() {\n  int q = 5 / z;\n}\nvoid loop() {}')
        r.run(10)
        self.assertEqual(r.m.state, 'error')
        self.assertEqual(r.m.error.line, 3)

    def test_deep_recursion(self):
        r = self.rig('int f(int n) { return f(n + 1); }\nvoid setup() { f(0); }\nvoid loop() {}')
        r.run(100)
        self.assertEqual(r.m.state, 'error')
        self.assertIn('깊습니다', r.m.error.msg)

    def test_infinite_loop_can_be_stopped(self):
        r = self.rig('void setup() {}\nvoid loop() { while (true) { } }')
        r.m.start()
        r.m.advance(10**12)          # 예산을 무한히 줘도
        time.sleep(0.2)
        t0 = time.monotonic()
        r.m.stop()                   # 정지가 바로 먹혀야 합니다
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertFalse(r.m.running())
        self.assertEqual(r.m.state, 'stopped')

    def test_delay_waits_for_budget(self):
        r = self.rig(setup_loop('', 'delay(5000);'))
        r.m.start()
        r.m.advance(1000)            # 1ms만 허락
        time.sleep(0.1)
        self.assertTrue(r.m.waiting)
        self.assertLessEqual(r.m.t, 1000)


# ---------------------------------------------------------------- 모듈
LED_WIRING = [(('uno', 'D13'), ('r', '1')), (('r', '2'), ('led', 'A')), (('led', 'K'), ('uno', 'GND.1'))]
LED_MODS = [('resistor', 'r', {'ohms': 220}), ('led', 'led', {'color': 'red'})]


class ModuleTests(SketchCase):
    def test_blink_led(self):
        r = self.rig(EX.BLINK, LED_MODS, LED_WIRING)
        r.run(500)
        self.assertEqual(r.mods['led'].state['level'], 1.0)
        r.run(1000)
        self.assertEqual(r.mods['led'].state['level'], 0.0)
        self.assertEqual(r.warnings(), [])

    def test_led_without_resistor_warns(self):
        r = self.rig(EX.BLINK, [('led', 'led', {})], [(('uno', 'D13'), ('led', 'A')), (('led', 'K'), ('uno', 'GND.1'))])
        r.run(100)
        self.assertGreater(r.mods['led'].state['level'], 0)
        self.assertTrue(any('저항이 없습니다' in w for w in r.warnings()))

    def test_reversed_led_warns(self):
        wiring = [(('uno', 'D13'), ('r', '1')), (('r', '2'), ('led', 'K')), (('led', 'A'), ('uno', 'GND.1'))]
        r = self.rig(EX.BLINK, LED_MODS, wiring)
        r.run(100)
        self.assertEqual(r.mods['led'].state['level'], 0)
        self.assertTrue(any('반대' in w for w in r.warnings()))

    def test_pwm_brightness_and_non_pwm_pin(self):
        src = setup_loop('pinMode(9, OUTPUT); analogWrite(9, 64); analogWrite(7, 64);', 'delay(100);')
        wiring = [(('uno', 'D9'), ('r', '1')), (('r', '2'), ('led', 'A')), (('led', 'K'), ('uno', 'GND.1'))]
        r = self.rig(src, LED_MODS, wiring)
        r.run(10)
        self.assertAlmostEqual(r.mods['led'].state['level'], 64 / 255, places=3)
        self.assertTrue(any('PWM 핀이 아닙니다' in w for w in r.warnings()))

    def test_button_pullup_and_floating(self):
        r = self.rig(EX.BUTTON, [('button', 'b', {})] + LED_MODS,
                     [(('b', '1'), ('uno', 'D2')), (('b', '2'), ('uno', 'GND.3'))] + LED_WIRING)
        r.run(50)
        self.assertEqual(r.mods['led'].state['level'], 0)
        r.mods['b'].props['pressed'] = True
        r.board.touch()
        r.run(50)
        self.assertEqual(r.mods['led'].state['level'], 1.0)
        # 풀업 없이 떠 있는 입력은 경고
        r2 = self.rig(setup_loop('pinMode(4, INPUT);', 'digitalRead(4); delay(10);'))
        r2.run(30)
        self.assertTrue(any('플로팅' in w for w in r2.warnings()))

    def test_pulldown_resistor(self):
        src = setup_loop('Serial.begin(9600); pinMode(2, INPUT);', 'Serial.println(digitalRead(2)); delay(100);')
        mods = [('button', 'b', {}), ('resistor', 'pd', {'ohms': 10000})]
        wires = [(('uno', '5V'), ('b', '1')), (('b', '2'), ('uno', 'D2')), (('uno', 'D2'), ('pd', '1')),
                 (('pd', '2'), ('uno', 'GND.1'))]
        r = self.rig(src, mods, wires)
        r.run(50)
        r.mods['b'].props['pressed'] = True
        r.board.touch()
        r.run(100)
        self.assertEqual(r.out().split(), ['0', '1'])
        self.assertEqual(r.warnings(), [])

    def test_potentiometer(self):
        r = self.rig(POT, [('pot', 'p', {'value': 300})],
                     [(('p', '1'), ('uno', '5V')), (('p', 'W'), ('uno', 'A0')), (('p', '2'), ('uno', 'GND.1'))])
        r.run(50)
        self.assertIn('A0 = 300', r.out())     # 1번 핀이 5V면 위치 값 그대로
        r.mods['p'].props['value'] = 1023
        r.board.touch()
        r.run(250)
        self.assertIn('A0 = 1023', r.out())

    def test_servo(self):
        r = self.rig('#include <Servo.h>\nServo s;\nvoid setup() { s.attach(9); s.write(45); }\nvoid loop() {}',
                     [('servo', 's1', {})],
                     [(('s1', 'GND'), ('uno', 'GND.1')), (('s1', '5V'), ('uno', '5V')), (('s1', 'SIG'), ('uno', 'D9'))])
        r.run(10)
        self.assertEqual(r.mods['s1'].state['target'], 45)
        mod = r.mods['s1']
        mod.animate(0)
        mod.animate(500_000)
        self.assertEqual(mod.state['angle'], 45)

    def test_servo_unpowered_warns(self):
        r = self.rig('#include <Servo.h>\nServo s;\nvoid setup() { s.attach(9); s.write(45); }\nvoid loop() {}',
                     [('servo', 's1', {})], [(('s1', 'SIG'), ('uno', 'D9'))])
        r.run(10)
        self.assertIsNone(r.mods['s1'].state['target'])
        self.assertTrue(any('전원' in w for w in r.warnings()))

    def lcd_rig(self, swap=False, addr=0x27):
        wires = [(('lcd', 'GND'), ('uno', 'GND.1')), (('lcd', 'VCC'), ('uno', '5V')),
                 (('lcd', 'SDA'), ('uno', 'A5' if swap else 'A4')), (('lcd', 'SCL'), ('uno', 'A4' if swap else 'A5'))]
        return self.rig(LCD, [('lcd1602', 'lcd', {'addr': addr})], wires)

    def test_lcd(self):
        r = self.lcd_rig()
        r.run(2100)
        lines = r.mods['lcd'].lcd.visible()
        self.assertEqual(lines[0], 'Hello, BreadLab ')
        self.assertTrue(lines[1].startswith('Time: 2 s'))
        self.assertTrue(r.mods['lcd'].lcd.backlight)
        self.assertEqual(r.warnings(), [])

    def test_lcd_wrong_wiring_and_address(self):
        r = self.lcd_rig(swap=True)
        r.run(100)
        ws = r.warnings()
        self.assertTrue(any('바뀌었습니다' in w for w in ws))
        self.assertTrue(any('0x27' in w for w in ws))
        r2 = self.lcd_rig(addr=0x3F)
        r2.run(100)
        self.assertTrue(any('0x27' in w for w in r2.warnings()))
        self.assertFalse(r2.mods['lcd'].lcd.initialized)

    def test_ultrasonic(self):
        mods = [('hcsr04', 'us', {'distance': 120})]
        wires = [(('us', 'VCC'), ('uno', '5V')), (('us', 'TRIG'), ('uno', 'D7')), (('us', 'ECHO'), ('uno', 'D6')),
                 (('us', 'GND'), ('uno', 'GND.1'))]
        r = self.rig(ULTRASONIC, mods, wires)
        r.run(100)
        self.assertIn('거리: 120.', r.out())
        # TRIG 펄스 없이 pulseIn만 하면 0
        src = setup_loop('Serial.begin(9600); pinMode(7, OUTPUT);', 'Serial.println(pulseIn(6, HIGH, 30000)); delay(100);')
        r2 = self.rig(src, mods, wires)
        r2.run(50)
        self.assertEqual(r2.out().split()[0], '0')
        self.assertTrue(any('TRIG' in w for w in r2.warnings()))

    def test_dht(self):
        wires = [(('d', 'VCC'), ('uno', '5V')), (('d', 'DATA'), ('uno', 'D2')), (('d', 'GND'), ('uno', 'GND.1'))]
        r = self.rig(DHT_SKETCH, [('dht', 'd', {'model': 'DHT11', 'temp': 31.4, 'humidity': 62})], wires)
        r.run(2100)
        self.assertIn('온도: 31.00', r.out())
        self.assertIn('습도: 62.00', r.out())
        r2 = self.rig(DHT_SKETCH, [('dht', 'd', {'model': 'DHT22'})], wires)
        r2.run(2100)
        self.assertIn('읽지 못했어요', r2.out())
        self.assertTrue(any('DHT22' in w for w in r2.warnings()))

    def test_tm1637(self):
        src = ('#include <TM1637Display.h>\nTM1637Display d(2, 3);\n'
               'void setup() { d.setBrightness(3); d.showNumberDecEx(1234, 0b01000000); }\nvoid loop() {}')
        wires = [(('t', 'CLK'), ('uno', 'D2')), (('t', 'DIO'), ('uno', 'D3')), (('t', 'VCC'), ('uno', '5V')),
                 (('t', 'GND'), ('uno', 'GND.1'))]
        r = self.rig(src, [('tm1637', 't', {})], wires)
        r.run(10)
        st = r.mods['t'].state
        self.assertEqual(st['segs'], [0x06, 0x5B | 0x80, 0x4F, 0x66])
        self.assertEqual(st['brightness'], 3)

    def test_matrix(self):
        wires = [(('mx', 'VCC'), ('uno', '5V')), (('mx', 'GND'), ('uno', 'GND.1')), (('mx', 'DIN'), ('uno', 'D12')),
                 (('mx', 'CS'), ('uno', 'D11')), (('mx', 'CLK'), ('uno', 'D10'))]
        r = self.rig(MATRIX, [('matrix', 'mx', {})], wires)
        r.run(100)
        st = r.mods['mx'].state
        self.assertFalse(st['shutdown'])
        self.assertEqual(st['rows'][1], 0b01100110)

    def test_relay_switches_led(self):
        src = setup_loop('pinMode(7, OUTPUT);', 'digitalWrite(7, HIGH); delay(500); digitalWrite(7, LOW); delay(500);')
        mods = [('relay', 'k', {}), ('led', 'led', {}), ('resistor', 'r', {})]
        wires = [(('k', 'IN'), ('uno', 'D7')), (('k', 'VCC'), ('uno', '5V')), (('k', 'GND'), ('uno', 'GND.1')),
                 (('uno', '5V'), ('k', 'COM')), (('k', 'NO'), ('r', '1')), (('r', '2'), ('led', 'A')),
                 (('led', 'K'), ('uno', 'GND.2'))]
        r = self.rig(src, mods, wires)
        r.run(100)
        self.assertTrue(r.mods['k'].state['on'])
        self.assertEqual(r.mods['led'].state['level'], 1.0)
        r.run(500)
        self.assertFalse(r.mods['k'].state['on'])
        self.assertEqual(r.mods['led'].state['level'], 0.0)

    def test_rgb_buzzers_motor(self):
        src = setup_loop('analogWrite(9, 255); analogWrite(10, 128); tone(8, 440); pinMode(4, OUTPUT);'
                         'digitalWrite(4, HIGH); analogWrite(5, 191); pinMode(6, OUTPUT);', 'delay(100);')
        mods = [('rgb_led', 'rgb', {}), ('buzzer_passive', 'pb', {}), ('buzzer_active', 'ab', {}), ('dc_motor', 'mo', {})]
        wires = [(('rgb', 'R'), ('uno', 'D9')), (('rgb', 'G'), ('uno', 'D10')), (('rgb', 'GND'), ('uno', 'GND.1')),
                 (('pb', '+'), ('uno', 'D8')), (('pb', '-'), ('uno', 'GND.1')),
                 (('ab', '+'), ('uno', 'D4')), (('ab', '-'), ('uno', 'GND.1')),
                 (('mo', 'VCC'), ('uno', '5V')), (('mo', 'GND'), ('uno', 'GND.2')), (('mo', 'IA'), ('uno', 'D6')),
                 (('mo', 'IB'), ('uno', 'D5'))]
        r = self.rig(src, mods, wires)
        r.run(10)
        rgb = r.mods['rgb'].state['rgb']
        self.assertEqual(rgb[0], 1.0)
        self.assertAlmostEqual(rgb[1], 128 / 255, places=3)
        self.assertEqual(rgb[2], 0)
        self.assertEqual(r.mods['pb'].state['freq'], 440)
        self.assertTrue(r.mods['ab'].state['on'])
        self.assertAlmostEqual(r.mods['mo'].state['speed'], -191 / 255, places=3)

    def test_tone_duration_ends(self):
        r = self.rig(setup_loop('tone(8, 1000, 200);', 'delay(10);'), [('buzzer_passive', 'pb', {})],
                     [(('pb', '+'), ('uno', 'D8')), (('pb', '-'), ('uno', 'GND.1'))])
        r.run(100)
        self.assertEqual(r.mods['pb'].state['freq'], 1000)
        r.run(200)
        self.assertIsNone(r.mods['pb'].state['freq'])

    def test_analog_and_digital_sensors(self):
        src = setup_loop('Serial.begin(9600);',
                         'Serial.print(analogRead(A0)); Serial.print(" "); Serial.print(digitalRead(2)); Serial.print(" ");'
                         'Serial.print(analogRead(A1)); Serial.print(" "); Serial.print(digitalRead(3)); Serial.print(" ");'
                         'Serial.print(digitalRead(4)); Serial.print(" "); Serial.print(digitalRead(5)); Serial.print(" ");'
                         'Serial.print(analogRead(A2)); Serial.print(" "); Serial.println(analogRead(A3)); delay(100);')
        pw = lambda mid, v='VCC', g='GND': [((mid, v), ('uno', '5V')), ((mid, g), ('uno', 'GND.1'))]
        mods = [('ldr', 'ldr', {'light': 20, 'threshold': 30}), ('sound', 'snd', {'level': 80, 'threshold': 60}),
                ('pir', 'pir', {'motion': True}), ('ir_obstacle', 'ir', {'obstacle': True}),
                ('temp_sensor', 'lm', {'model': 'LM35', 'temp': 25}),
                ('temp_sensor', 'tmp', {'model': 'TMP36', 'temp': 25})]
        wires = (pw('ldr') + [(('ldr', 'AO'), ('uno', 'A0')), (('ldr', 'DO'), ('uno', 'D2'))] +
                 pw('snd') + [(('snd', 'AO'), ('uno', 'A1')), (('snd', 'DO'), ('uno', 'D3'))] +
                 pw('pir') + [(('pir', 'OUT'), ('uno', 'D4'))] + pw('ir') + [(('ir', 'OUT'), ('uno', 'D5'))] +
                 pw('lm', 'VS') + [(('lm', 'OUT'), ('uno', 'A2'))] + pw('tmp', 'VS') + [(('tmp', 'OUT'), ('uno', 'A3'))])
        r = self.rig(src, mods, wires)
        r.run(50)
        vals = [int(x) for x in r.out().split()[:8]]
        self.assertEqual(vals, [205, 1, 818, 1, 1, 0, 51, 153])
        self.assertEqual(r.warnings(), [])

    def test_joystick_tilt_switches(self):
        src = setup_loop('Serial.begin(9600); pinMode(2, INPUT_PULLUP); pinMode(3, INPUT_PULLUP); pinMode(4, INPUT_PULLUP);',
                         'Serial.print(analogRead(A0)); Serial.print(" "); Serial.print(digitalRead(2)); Serial.print(" ");'
                         'Serial.print(digitalRead(3)); Serial.print(" "); Serial.print(digitalRead(4)); Serial.print(" ");'
                         'Serial.println(digitalRead(5)); delay(100);')
        mods = [('joystick', 'js', {'x': 1023, 'pressed': True}), ('slide_switch', 'sw', {'pos': 1}),
                ('toggle', 'tg', {'on': False}), ('tilt', 'tl', {'tilted': True})]
        wires = [(('js', '5V'), ('uno', '5V')), (('js', 'GND'), ('uno', 'GND.1')), (('js', 'VRx'), ('uno', 'A0')),
                 (('js', 'SW'), ('uno', 'D2')), (('sw', 'COM'), ('uno', 'D3')), (('sw', '2'), ('uno', 'GND.1')),
                 (('tg', '1'), ('uno', 'D4')), (('tg', '2'), ('uno', 'GND.1')),
                 (('tl', 'VCC'), ('uno', '5V')), (('tl', 'GND'), ('uno', 'GND.2')), (('tl', 'DO'), ('uno', 'D5'))]
        r = self.rig(src, mods, wires)
        r.run(50)
        self.assertEqual(r.out().split()[:5], ['1023', '0', '0', '1', '1'])

    def test_seven_segment(self):
        src = setup_loop('for (int p = 2; p <= 8; p++) pinMode(p, OUTPUT);'
                         'digitalWrite(2, HIGH); digitalWrite(3, HIGH); digitalWrite(4, LOW);', 'delay(100);')
        wires = [(('s', n), ('uno', f'D{p}')) for n, p in zip('abcdefg', range(2, 9))] + [(('s', 'COM'), ('uno', 'GND.1'))]
        r = self.rig(src, [('seg7', 's', {'common': 'cathode'})], wires)
        r.run(10)
        self.assertEqual(r.mods['s'].state['lit'][:3], [1.0, 1.0, 0.0])

    def test_short_circuit_warning(self):
        r = self.rig(EX.BLINK, [], [(('uno', '5V'), ('uno', 'GND.1'))])
        r.run(10)
        self.assertTrue(any('단락' in w for w in r.warnings()))

    def test_digitalwrite_without_pinmode_dims_led(self):
        src = setup_loop('digitalWrite(13, HIGH);', 'delay(100);')
        r = self.rig(src, LED_MODS, LED_WIRING)
        r.run(10)
        self.assertTrue(0 < r.mods['led'].state['level'] < 0.2)
        self.assertTrue(any('pinMode' in w for w in r.warnings()))

    def test_unpowered_sensor_warns(self):
        r = self.rig(setup_loop('', 'analogRead(A0); delay(100);'), [('ldr', 'l', {})], [(('l', 'AO'), ('uno', 'A0'))])
        r.run(10)
        self.assertTrue(any('전원이 연결되지 않았습니다' in w for w in r.warnings()))


# ---------------------------------------------------------------- 저장과 예제
class DocumentTests(SketchCase):
    def test_examples_compile_run_without_warnings(self):
        for ex in EX.EXAMPLES:
            with self.subTest(ex['title']):
                doc = EX.example_doc(ex)
                b = Board()
                b.load_json(doc['board'])
                m = Machine(b)
                m.load(doc['sketch'])
                try:
                    m.run_for(2500)
                    self.assertEqual(m.state, 'running', m.error)
                    b.solve()
                    self.assertEqual(b.all_warnings(), [])
                finally:
                    m.stop()

    def lesson(self, idx, ms):
        doc = EX.example_doc(EX.EXAMPLES[idx])
        b = Board()
        b.load_json(doc['board'])
        m = Machine(b)
        m.load(doc['sketch'])
        self.addCleanup(m.stop)
        m.run_for(ms)
        b.solve()
        return b, m

    def test_lessons_react(self):
        # 4. 가변저항 → LED 밝기
        b, m = self.lesson(3, 300)
        self.assertAlmostEqual(b.modules['led1'].state['level'], 127 / 255, places=2)
        # 5. 어두우면 LED 켜짐
        b, m = self.lesson(4, 100)
        self.assertEqual(b.modules['led1'].state['level'], 0)
        b.modules['ldr1'].props['light'] = 10
        b.touch()
        m.run_for(400)
        b.solve()
        self.assertEqual(b.modules['led1'].state['level'], 1.0)
        # 7. 가변저항 → 서보 각도
        b, m = self.lesson(6, 100)
        self.assertEqual(b.modules['servo1'].state['target'], 90)
        # 8. 가까우면 부저가 계속 울림
        b, m = self.lesson(7, 100)
        b.modules['us1'].props['distance'] = 5
        b.touch()
        m.run_for(700)
        b.solve()
        self.assertEqual(b.modules['bz1'].state['freq'], 1000)
        # 9. LCD에 온습도
        b, m = self.lesson(8, 100)
        lines = b.modules['lcd1'].lcd.visible()
        self.assertTrue(lines[0].startswith('Temp: 24.0\xdfC'))
        self.assertTrue(lines[1].startswith('Humi: 45 %'))
        # 10. RGB 첫 색은 빨강
        b, m = self.lesson(9, 100)
        self.assertEqual(b.modules['rgb1'].state['rgb'], [1.0, 0.0, 0.0])

    def test_board_json_roundtrip(self):
        doc = EX.example_doc(EX.EXAMPLES[2])
        b = Board()
        b.load_json(json.loads(json.dumps(doc['board'])))
        again = json.loads(json.dumps(b.to_json()))
        self.assertEqual(len(again['modules']), 3)
        self.assertEqual(len(again['wires']), 5)
        b2 = Board()
        b2.load_json(again)
        self.assertEqual(sorted(b2.modules), sorted(b.modules))
        self.assertEqual({(tuple(w.a), tuple(w.b)) for w in b2.wires}, {(w.a, w.b) for w in b.wires})

    def test_load_ignores_dangling_wires(self):
        b = Board()
        b.load_json({'modules': [], 'wires': [{'a': ['uno', 'D2'], 'b': ['gone', '1']}]})
        self.assertEqual(b.wires, [])


class WorkspaceSmokeTest(unittest.TestCase):
    """Qt 화면(offscreen)에서 예제를 열고 실행해 봅니다."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        import theme
        cls.app = QApplication.instance() or QApplication([])
        theme.apply_theme(cls.app)

    def pump(self, sec):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def test_open_run_save(self):
        import tempfile
        from pathlib import Path
        from arduino_lab import ArduinoWorkspace
        ws = ArduinoWorkspace()
        try:
            self.assertEqual(ws.title, 'Arduino UNO')
            self.assertEqual(ws.extensions, ('.uno',))
            self.assertEqual(len(ws.menus()), 4)
            self.assertIs(ws.menus()[0], ws.menus()[0])
            ws.open_example(EX.EXAMPLES[3])
            ws.run()
            self.pump(0.8)
            self.assertTrue(ws.machine.running())
            self.assertIn('가변저항: 512', ws.serial.out.toPlainText())
            ws.deactivated()
            t = ws.machine.t
            self.pump(0.3)
            self.assertLess(ws.machine.t - t, 120_000)   # 다른 탭에 있으면 멈춤
            ws.activated()
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / 'dimmer.uno'
                self.assertTrue(ws.write(p))
                self.assertFalse(ws.is_modified())
                ws.stop()
                self.assertTrue(ws.open_path(str(p)))
                self.assertEqual(len(ws.board.modules), 3)
                self.assertEqual(ws.document_title(), 'dimmer.uno')
            # 컴파일 오류는 줄 번호로 표시
            ws.editor.setPlainText('void setup() {\n  int a = 1\n}\nvoid loop() {}')
            ws.run()
            self.assertEqual(ws.editor.error_line, 2)
            self.assertFalse(ws.machine.running())
        finally:
            ws.stop()


    def test_tour(self):
        from arduino_lab import ArduinoWorkspace
        ws = ArduinoWorkspace()
        ws.resize(1200, 800)
        ws.show()
        try:
            self.pump(0.2)
            ws.start_tour()
            tour = ws.tour
            self.assertTrue(tour.isVisible())
            n = len(tour.steps)
            self.assertGreaterEqual(n, 6)
            for i in range(n - 1):
                self.assertEqual(tour.count.text(), f'{i + 1} / {n}')
                self.assertTrue(tour.card.geometry().intersects(tour.rect()))
                tour.next()
            self.assertEqual(tour.next_btn.text(), '마침')
            tour.run_action()                  # 마지막 단계: 1번 예제 열기
            self.assertFalse(tour.isVisible())
            self.assertIn('LED 깜박이기', ws.doc_name)
        finally:
            ws.stop()
            ws.close()


if __name__ == '__main__':
    unittest.main()
