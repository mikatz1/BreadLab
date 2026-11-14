"""회로 실습 예제 10개. 쉬운 것부터 차례로 배치했습니다. 보드는 (0, 0)~(540, 420)에 놓입니다.

모듈: (종류, id, x, y, 속성)   배선: (끝, 끝, 색)   끝 = ('uno', 핀) 또는 (모듈 id, 핀)
"""

BLINK = '''// 1. LED 깜박이기
// 13번 핀 → 220Ω 저항 → LED 긴 다리(+), LED 짧은 다리(−) → GND
// 보드의 L LED도 함께 깜박입니다.

const int ledPin = 13;

void setup() {
  pinMode(ledPin, OUTPUT);
}

void loop() {
  digitalWrite(ledPin, HIGH);  // 켜기
  delay(1000);                 // 1초 기다리기
  digitalWrite(ledPin, LOW);   // 끄기
  delay(1000);
}
'''

TRAFFIC = '''// 2. 신호등
// 초록 → 노랑 → 빨강 순서로 켭니다.
// LED마다 저항이 하나씩 필요합니다.

const int red = 12;
const int yellow = 11;
const int green = 10;

void setup() {
  pinMode(red, OUTPUT);
  pinMode(yellow, OUTPUT);
  pinMode(green, OUTPUT);
}

// LED 하나만 켜고 ms(밀리초)만큼 기다립니다.
void light(int pin, int ms) {
  digitalWrite(red, LOW);
  digitalWrite(yellow, LOW);
  digitalWrite(green, LOW);
  digitalWrite(pin, HIGH);
  delay(ms);
}

void loop() {
  light(green, 3000);
  light(yellow, 1000);
  light(red, 3000);
}
'''

BUTTON = '''// 3. 버튼으로 LED 켜기
// INPUT_PULLUP: 평소 HIGH, 누르면 LOW입니다.
// 캔버스의 버튼을 마우스로 눌러 봅니다.

const int buttonPin = 2;
const int ledPin = 13;

void setup() {
  pinMode(buttonPin, INPUT_PULLUP);
  pinMode(ledPin, OUTPUT);
}

void loop() {
  if (digitalRead(buttonPin) == LOW) {   // 눌렀을 때
    digitalWrite(ledPin, HIGH);
  } else {
    digitalWrite(ledPin, LOW);
  }
}
'''

DIMMER = '''// 4. 가변저항으로 LED 밝기 조절
// analogRead()는 0~1023, analogWrite()는 0~255입니다.
// 가변저항을 마우스 휠로 돌려 봅니다.

const int potPin = A0;
const int ledPin = 9;    // ~ 표시가 있는 PWM 핀

void setup() {
  Serial.begin(9600);
}

void loop() {
  int value = analogRead(potPin);
  int brightness = map(value, 0, 1023, 0, 255);
  analogWrite(ledPin, brightness);

  Serial.print("가변저항: ");
  Serial.print(value);
  Serial.print("  밝기: ");
  Serial.println(brightness);
  delay(200);
}
'''

NIGHT_LIGHT = '''// 5. 조도 센서로 자동 조명 만들기
// 어두워지면 LED가 켜집니다.
// 조도 센서를 선택하고 왼쪽 패널에서 밝기를 바꿔 봅니다.

const int sensorPin = A0;
const int ledPin = 9;
const int threshold = 300;   // 이 값보다 어두우면 켜기

void setup() {
  pinMode(ledPin, OUTPUT);
  Serial.begin(9600);
}

void loop() {
  int light = analogRead(sensorPin);   // 밝을수록 큰 값
  Serial.print("밝기 값: ");
  Serial.println(light);

  if (light < threshold) {
    digitalWrite(ledPin, HIGH);
  } else {
    digitalWrite(ledPin, LOW);
  }
  delay(300);
}
'''

MELODY = '''// 6. 부저로 음계 연주하기
// tone(핀, 주파수, 길이)로 소리를 냅니다.

#define NOTE_C4 262
#define NOTE_D4 294
#define NOTE_E4 330
#define NOTE_F4 349
#define NOTE_G4 392
#define NOTE_A4 440
#define NOTE_B4 494
#define NOTE_C5 523

const int buzzerPin = 8;
int melody[] = {NOTE_C4, NOTE_D4, NOTE_E4, NOTE_F4, NOTE_G4, NOTE_A4, NOTE_B4, NOTE_C5};

void setup() {}

void loop() {
  for (int i = 0; i < 8; i++) {
    tone(buzzerPin, melody[i], 250);
    delay(300);
  }
  delay(1000);
}
'''

SERVO_KNOB = '''// 7. 가변저항으로 서보 모터 각도 조절
// 가변저항 값(0~1023)을 각도(0~180)로 바꿉니다.
#include <Servo.h>

Servo myServo;
const int potPin = A0;

void setup() {
  myServo.attach(9);
  Serial.begin(9600);
}

void loop() {
  int value = analogRead(potPin);
  int angle = map(value, 0, 1023, 0, 180);
  myServo.write(angle);

  Serial.print("각도: ");
  Serial.println(angle);
  delay(50);
}
'''

PARKING = '''// 8. 초음파 센서로 주차 경보기 만들기
// 가까울수록 부저가 빠르게 울립니다.
// 초음파 센서를 선택하고 거리를 바꿔 봅니다.

const int trigPin = 7;
const int echoPin = 6;
const int buzzerPin = 4;

void setup() {
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);
  Serial.begin(9600);
}

float readDistance() {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);   // 10µs 펄스 보내기
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  long duration = pulseIn(echoPin, HIGH);
  return duration / 58.0;        // cm로 바꾸기
}

void loop() {
  float distance = readDistance();
  Serial.print("거리: ");
  Serial.print(distance, 1);
  Serial.println(" cm");

  if (distance > 0 && distance < 10) {
    tone(buzzerPin, 1000);       // 아주 가까우면 계속 울림
    delay(200);
  } else if (distance > 0 && distance < 50) {
    tone(buzzerPin, 1000, 100);
    delay(distance * 10);        // 가까울수록 짧게 쉼
  } else {
    noTone(buzzerPin);
    delay(200);
  }
}
'''

WEATHER = '''// 9. 온습도를 LCD에 표시하기
// DHT11 온습도를 I2C LCD에 표시합니다.
// LCD: SDA → A4, SCL → A5
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>

#define DHTPIN 2
#define DHTTYPE DHT11

DHT dht(DHTPIN, DHTTYPE);
LiquidCrystal_I2C lcd(0x27, 16, 2);   // 주소, 칸 수, 줄 수

void setup() {
  dht.begin();
  lcd.init();
  lcd.backlight();
}

void loop() {
  float t = dht.readTemperature();
  float h = dht.readHumidity();

  lcd.setCursor(0, 0);
  if (isnan(t) || isnan(h)) {
    lcd.print("Sensor error    ");
  } else {
    lcd.print("Temp: ");
    lcd.print(t, 1);
    lcd.print((char)223);         // ° 기호
    lcd.print("C   ");
    lcd.setCursor(0, 1);
    lcd.print("Humi: ");
    lcd.print(h, 0);
    lcd.print(" %    ");
  }
  delay(2000);
}
'''

RGB = '''// 10. RGB LED로 색 섞기
// R, G, B 세기를 PWM으로 조절해 색을 만듭니다.

const int redPin = 9;
const int greenPin = 10;
const int bluePin = 11;

void setColor(int r, int g, int b) {
  analogWrite(redPin, r);
  analogWrite(greenPin, g);
  analogWrite(bluePin, b);
}

void setup() {}

void loop() {
  setColor(255, 0, 0);     // 빨강
  delay(1000);
  setColor(0, 255, 0);     // 초록
  delay(1000);
  setColor(0, 0, 255);     // 파랑
  delay(1000);
  setColor(255, 255, 0);   // 노랑
  delay(1000);
  setColor(0, 255, 255);   // 하늘색
  delay(1000);
  setColor(255, 0, 255);   // 보라
  delay(1000);
}
'''

# 자주 쓰는 배치
_LED_D13 = [('resistor', 'r1', 245, -100, {'ohms': 220}), ('led', 'led1', 340, -180, {'color': 'red'})]
_LED_D13_WIRES = [(('uno', 'D13'), ('r1', '1'), 'orange'), (('r1', '2'), ('led1', 'A'), 'orange'),
                  (('led1', 'K'), ('uno', 'GND.3'), 'black')]
_LED_D9 = [('resistor', 'r1', 245, -100, {'ohms': 220}), ('led', 'led1', 340, -180, {'color': 'yellow'})]
_LED_D9_WIRES = [(('uno', 'D9'), ('r1', '1'), 'orange'), (('r1', '2'), ('led1', 'A'), 'orange'),
                 (('led1', 'K'), ('uno', 'GND.3'), 'black')]
_POT = [('pot', 'pot1', 380, 480, {'value': 512})]
_POT_WIRES = [(('pot1', '1'), ('uno', '5V'), 'red'), (('pot1', 'W'), ('uno', 'A0'), 'yellow'),
              (('pot1', '2'), ('uno', 'GND.2'), 'black')]

EXAMPLES = [
    {
        'title': '1. LED 깜박이기', 'sketch': BLINK,
        'modules': _LED_D13, 'wires': _LED_D13_WIRES,
    },
    {
        'title': '2. 신호등', 'sketch': TRAFFIC,
        'modules': [('resistor', 'r1', 120, -110, {'ohms': 220}), ('resistor', 'r2', 120, -150, {'ohms': 220}),
                    ('resistor', 'r3', 120, -190, {'ohms': 220}),
                    ('led', 'red', 230, -290, {'color': 'red'}), ('led', 'yellow', 280, -290, {'color': 'yellow'}),
                    ('led', 'green', 330, -290, {'color': 'green'})],
        'wires': [(('uno', 'D12'), ('r1', '2'), 'orange'), (('r1', '1'), ('red', 'A'), 'orange'),
                  (('uno', 'D11'), ('r2', '2'), 'yellow'), (('r2', '1'), ('yellow', 'A'), 'yellow'),
                  (('uno', 'D10'), ('r3', '2'), 'green'), (('r3', '1'), ('green', 'A'), 'green'),
                  (('red', 'K'), ('uno', 'GND.3'), 'black'), (('yellow', 'K'), ('uno', 'GND.3'), 'black'),
                  (('green', 'K'), ('uno', 'GND.3'), 'black')],
    },
    {
        'title': '3. 버튼으로 LED 켜기', 'sketch': BUTTON,
        'modules': [('button', 'btn1', 440, -150, {})] + _LED_D13,
        'wires': [(('btn1', '1'), ('uno', 'D2'), 'blue'), (('btn1', '2'), ('uno', 'GND.3'), 'black')] + _LED_D13_WIRES,
    },
    {
        'title': '4. 가변저항으로 LED 밝기 조절', 'sketch': DIMMER,
        'modules': _POT + _LED_D9, 'wires': _POT_WIRES + _LED_D9_WIRES,
    },
    {
        'title': '5. 조도 센서로 자동 조명', 'sketch': NIGHT_LIGHT,
        'modules': [('ldr', 'ldr1', 380, 480, {'light': 60})] + _LED_D9,
        'wires': [(('ldr1', 'VCC'), ('uno', '5V'), 'red'), (('ldr1', 'GND'), ('uno', 'GND.2'), 'black'),
                  (('ldr1', 'AO'), ('uno', 'A0'), 'yellow')] + _LED_D9_WIRES,
    },
    {
        'title': '6. 부저로 음계 연주', 'sketch': MELODY,
        'modules': [('buzzer_passive', 'bz1', 300, -150, {})],
        'wires': [(('bz1', '+'), ('uno', 'D8'), 'orange'), (('bz1', '-'), ('uno', 'GND.3'), 'black')],
    },
    {
        'title': '7. 가변저항으로 서보 모터 조절', 'sketch': SERVO_KNOB,
        'modules': _POT + [('servo', 'servo1', 250, -190, {})],
        'wires': _POT_WIRES + [(('servo1', 'GND'), ('uno', 'GND.3'), 'brown'), (('servo1', '5V'), ('uno', '5V'), 'red'),
                               (('servo1', 'SIG'), ('uno', 'D9'), 'orange')],
    },
    {
        'title': '8. 초음파 주차 경보기', 'sketch': PARKING,
        'modules': [('hcsr04', 'us1', 230, -180, {'distance': 40.0}), ('buzzer_passive', 'bz1', 440, -140, {})],
        'wires': [(('us1', 'VCC'), ('uno', '5V'), 'red'), (('us1', 'TRIG'), ('uno', 'D7'), 'yellow'),
                  (('us1', 'ECHO'), ('uno', 'D6'), 'green'), (('us1', 'GND'), ('uno', 'GND.3'), 'black'),
                  (('bz1', '+'), ('uno', 'D4'), 'orange'), (('bz1', '-'), ('uno', 'GND.3'), 'black')],
    },
    {
        'title': '9. 온습도를 LCD에 표시', 'sketch': WEATHER,
        'modules': [('lcd1602', 'lcd1', 40, -260, {'addr': 0x27}),
                    ('dht', 'dht1', 440, -170, {'model': 'DHT11', 'temp': 24, 'humidity': 45})],
        'wires': [(('lcd1', 'GND'), ('uno', 'GND.3'), 'black'), (('lcd1', 'VCC'), ('uno', '5V'), 'red'),
                  (('lcd1', 'SDA'), ('uno', 'SDA'), 'blue'), (('lcd1', 'SCL'), ('uno', 'SCL'), 'green'),
                  (('dht1', 'VCC'), ('uno', '5V'), 'red'), (('dht1', 'DATA'), ('uno', 'D2'), 'yellow'),
                  (('dht1', 'GND'), ('uno', 'GND.3'), 'black')],
    },
    {
        'title': '10. RGB LED로 색 섞기', 'sketch': RGB,
        'modules': [('rgb_led', 'rgb1', 250, -170, {})],
        'wires': [(('rgb1', 'R'), ('uno', 'D9'), 'red'), (('rgb1', 'G'), ('uno', 'D10'), 'green'),
                  (('rgb1', 'B'), ('uno', 'D11'), 'blue'), (('rgb1', 'GND'), ('uno', 'GND.3'), 'black')],
    },
]

NEW_SKETCH = '''void setup() {
  // 처음에 한 번 실행됩니다.

}

void loop() {
  // 계속 반복 실행됩니다.

}
'''


def example_doc(ex):
    """예제를 .uno 문서(dict) 형태로 바꿉니다."""
    return {
        'format': 'breadlab-uno', 'version': 1, 'sketch': ex['sketch'],
        'board': {
            'modules': [{'id': mid, 'type': t, 'x': x, 'y': y, 'props': dict(props)}
                        for t, mid, x, y, props in ex['modules']],
            'wires': [{'a': list(a), 'b': list(b), 'color': c} for a, b, c in ex['wires']],
        },
    }
