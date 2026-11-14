"""예제 회로 10개. 쉬운 것부터 전자·전기 전공 수준까지 순서대로 놓았습니다.

각 항목은 (제목, 설명, 회로 문서)이며 문서는 .bd 파일과 같은 형식입니다.
회로는 넷리스트(부품 ↔ 마디)로 적고, 브레드보드 배치는 회로도 가져오기와 같은 자동 배치기(place_best)가
선이 덜 엇갈리게 꽂아 줍니다. '0'은 접지(전원 CH1 −)입니다.
"""
from circuit_core import BLUE, GREEN, RED, YELLOW, make_document
from circuit_import import Comp, Plan, place_best


def _fg(wave, freq, vpp, offset=0.0):
    return dict(wave=wave, freq=freq, vpp=vpp, offset=offset, duty=50.0, on=True)


def _build(comps, ch1=None, ch2=None, fg=None, probes=()):
    """comps: (종류, [마디…], {속성}) 목록. ch1·ch2: (+마디, −마디, 전압). fg: (+마디, −마디, 설정)."""
    plan = Plan([Comp(k, list(nets), dict(props)) for k, nets, props in comps], '0', ch1=ch1, ch2=ch2, fg=fg)
    plan.rails = {'0': 'gnd'}
    if ch1:
        plan.rails[ch1[0]] = 'vp'
    if ch2 and ch2[0] == '0':
        plan.rails[ch2[1]] = 'vn'
    plan.probes = list(probes)
    parts, inst = place_best(plan)
    return make_document(parts, inst)


EXAMPLES = [
    ('LED 켜기',
     '5 V → 330 Ω → LED. 전원 CH1을 켜면 LED가 켜집니다. 저항이 전류를 약 9 mA로 줄여 LED를 지킵니다.',
     _build([('resistor', ['vp', 'a'], {'value': 330}),
             ('led', ['a', '0'], {'color': RED})],
            ch1=('vp', '0', 5.0))),

    ('전압 나누기',
     '9 V를 10 kΩ과 4.7 kΩ으로 나눕니다. 가운데 마디는 9 × 4.7 ÷ 14.7 ≈ 2.88 V입니다. '
     '구멍에 마우스를 올려 전압을 확인하십시오.',
     _build([('resistor', ['vp', 'm'], {'value': 10e3}),
             ('resistor', ['m', '0'], {'value': 4.7e3})],
            ch1=('vp', '0', 9.0), probes=['m'])),

    ('가변저항으로 밝기 조절',
     '가변저항의 와이퍼 전압으로 LED 전류를 바꿉니다. 가변저항을 고르고 오른쪽 패널의 위치를 움직여 보십시오.',
     _build([('pot', ['vp', 'w', '0'], {'value': 10e3, 'pos': 30}),
             ('resistor', ['w', 'a'], {'value': 220}),
             ('led', ['a', '0'], {'color': YELLOW})],
            ch1=('vp', '0', 5.0), probes=['w'])),

    ('커패시터 충전과 방전',
     '10 kΩ × 100 µF, 시정수 1초. 전원을 켜면 커패시터가 천천히 충전됩니다. '
     '전환 스위치를 더블클릭하면 방전됩니다. 스코프 Time/div는 500 ms입니다.',
     _build([('spdt', ['vp', 'n', '0'], {'closed': True}),
             ('resistor', ['n', 'c'], {'value': 10e3}),
             ('capacitor', ['c', '0'], {'value': 100e-6})],
            ch1=('vp', '0', 5.0), probes=['c'])),

    ('어두우면 켜지는 등',
     '광저항(LDR)과 10 kΩ이 베이스 전압을 정하고, NPN 트랜지스터가 LED를 켜고 끕니다. '
     '광저항을 고르고 밝기를 낮추면 LED가 켜집니다.',
     _build([('resistor', ['vp', 'd'], {'value': 10e3}),
             ('ldr', ['d', '0'], {'light': 80}),
             ('resistor', ['d', 'b'], {'value': 1e3}),
             ('npn', ['k', 'b', '0'], {'value': 100}),
             ('resistor', ['vp', 'a'], {'value': 330}),
             ('led', ['a', 'k'], {'color': GREEN})],
            ch1=('vp', '0', 5.0), probes=['d'])),

    ('제너 다이오드 정전압',
     '470 Ω과 5.1 V 제너 다이오드로 일정한 전압을 만듭니다. 전원 CH1을 9~15 V로 바꿔도 출력은 약 5.1 V로 거의 그대로입니다.',
     _build([('resistor', ['vp', 'z'], {'value': 470}),
             ('zener', ['0', 'z'], {'value': 5.1}),
             ('resistor', ['z', '0'], {'value': 1e3})],
            ch1=('vp', '0', 12.0), probes=['z'])),

    ('반파 정류와 평활',
     '함수 발생기의 50 Hz 교류를 다이오드로 한쪽만 통과시키고, 100 µF 커패시터로 고르게 만듭니다. '
     '스코프 CH1은 입력, CH2는 출력입니다. 커패시터를 빼 보면 차이가 보입니다.',
     _build([('diode', ['in', 'o'], {}),
             ('capacitor', ['o', '0'], {'value': 100e-6}),
             ('resistor', ['o', '0'], {'value': 1e3})],
            fg=('in', '0', _fg('sine', 50, 12)), probes=['o'])),

    ('555 타이머로 LED 깜빡이기',
     '555 비안정 발진: 1 kΩ, 47 kΩ, 10 µF로 약 1.5 Hz. 스코프 CH1은 커패시터 전압(1/3~2/3 VCC 사이를 오감), '
     'CH2는 출력입니다.',
     _build([('timer555', ['0', 't', 'o', 'vp', 'cv', 't', 'dis', 'vp'], {}),
             ('resistor', ['vp', 'dis'], {'value': 1e3}),
             ('resistor', ['dis', 't'], {'value': 47e3}),
             ('capacitor', ['t', '0'], {'value': 10e-6}),
             ('capacitor', ['cv', '0'], {'value': 10e-9}),
             ('resistor', ['o', 'a'], {'value': 330}),
             ('led', ['a', '0'], {'color': RED})],
            ch1=('vp', '0', 9.0), probes=['t', 'o'])),

    ('공통 이미터 증폭기',
     '전압 분배 바이어스(47 kΩ·10 kΩ), 컬렉터 4.7 kΩ, 이미터 1 kΩ. 1 kHz 0.2 Vpp 신호를 커플링 커패시터로 넣으면 '
     '출력은 약 3배로 커지고 위상이 뒤집힙니다.',
     _build([('resistor', ['vp', 'b'], {'value': 47e3}),
             ('resistor', ['b', '0'], {'value': 10e3}),
             ('resistor', ['vp', 'c'], {'value': 4.7e3}),
             ('npn', ['c', 'b', 'e'], {'value': 150}),
             ('resistor', ['e', '0'], {'value': 1e3}),
             ('capacitor', ['in', 'b'], {'value': 10e-6}),
             ('capacitor', ['c', 'o'], {'value': 10e-6}),
             ('resistor', ['o', '0'], {'value': 10e3})],
            ch1=('vp', '0', 12.0), fg=('in', '0', _fg('sine', 1000, 0.2)), probes=['o'])),

    ('연산 증폭기 반전 증폭기',
     '±12 V 전원(CH1과 CH2를 쌓음), 입력 10 kΩ, 되먹임 100 kΩ. 배율은 −100k ÷ 10k = −10입니다. '
     '1 kHz 1 Vpp를 넣으면 출력은 10 Vpp, 위상은 반대입니다.',
     _build([('resistor', ['in', 'm'], {'value': 10e3}),
             ('resistor', ['m', 'o'], {'value': 100e3}),
             ('opamp', [None, 'm', '0', 'vn', None, 'o', 'vp', None], {}),
             ('resistor', ['o', '0'], {'value': 10e3})],
            ch1=('vp', '0', 12.0), ch2=('0', 'vn', 12.0), fg=('in', '0', _fg('sine', 1000, 1.0)), probes=['o'])),
]
