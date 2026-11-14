"""시작 카드. 무거운 모듈 불러오기, 예제 미리 계산, 화면 캐시 데우기를 끝낸 뒤 편집 화면을 띄웁니다."""
import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

import theme

WAVE_TIME = 1.1       # 배경 사인파가 왼쪽부터 끝까지 그려지는 시간(초)
HOLD = 0.15           # 다 그려진 뒤 잠깐 머무는 시간(초)


def sans(px, weight=QFont.Weight.Normal):
    f = QFont()
    f.setFamilies(theme.FONT_FAMILIES)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


class StartupCard(QWidget):
    W, H = 480, 260

    def __init__(self, icon_path):
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setFixedSize(self.W, self.H)
        self.icon = QIcon(icon_path).pixmap(52, 52)
        self.text = ''
        self.progress = 0.0
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.W // 2, screen.center().y() - self.H // 2)
        self.shown_at = None
        # 켤 때마다 다른 배경 파형: (색, 진폭, 주기 수, 위상, 중심 높이, 굵기)
        rnd = random.Random()
        self.waves = [(QColor(239, 83, 80, 70), rnd.uniform(38, 52), rnd.uniform(1.2, 2.0),
                       rnd.uniform(0, 2 * math.pi), rnd.uniform(140, 158), 1.6),
                      (QColor(255, 255, 255, 32), rnd.uniform(14, 24), rnd.uniform(2.0, 3.2),
                       rnd.uniform(0, 2 * math.pi), rnd.uniform(146, 162), 1.2)]
        self.anim = QTimer(self)
        self.anim.setInterval(16)
        self.anim.timeout.connect(self.update)

    def reveal(self):
        """0→1. 끝으로 갈수록 느려지는(ease-out) 진행도."""
        if self.shown_at is None:
            return 0.0
        t = min((time.perf_counter() - self.shown_at) / WAVE_TIME, 1.0)
        return 1 - (1 - t) ** 3

    def show_card(self):
        self.show()
        self.raise_()
        self.shown_at = time.perf_counter()
        self.anim.start()
        QApplication.processEvents()

    def step(self, text, progress):
        self.text = text
        self.progress = max(self.progress, min(progress, 1.0))
        self.repaint()
        QApplication.processEvents()

    def finish(self):
        self.step('', 1.0)
        end = (self.shown_at or 0) + WAVE_TIME + HOLD
        while time.perf_counter() < end:      # 파형이 끝까지 그려질 때까지 기다림
            QApplication.processEvents()
            time.sleep(0.008)
        self.anim.stop()
        self.close()

    def paintEvent(self, e):
        W, H = self.W, self.H
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 바탕: 숯색 → 붉은 기운(아주 옅게)
        g = QLinearGradient(0, 0, W, H)
        g.setColorAt(0.0, QColor('#111216'))
        g.setColorAt(0.55, QColor('#17171a'))
        g.setColorAt(1.0, QColor('#2b1719'))
        p.fillRect(self.rect(), g)

        # 모눈(설계 도면 느낌)
        p.setPen(QPen(QColor(255, 255, 255, 10), 1))
        for x in range(0, W, 20):
            p.drawLine(QPointF(x + 0.5, 0), QPointF(x + 0.5, H))
        for y in range(0, H, 20):
            p.drawLine(QPointF(0, y + 0.5), QPointF(W, y + 0.5))

        # 배경 사인파 두 줄: 왼쪽에서 시작해 스르륵 그려짐
        reveal = self.reveal()
        x_end = W * reveal
        for color, amp, cycles, phase, yc, width in self.waves:
            path = QPainterPath()
            steps = max(2, int(x_end / 3))
            for i in range(steps + 1):
                x = x_end * i / steps
                y = yc - amp * math.sin(2 * math.pi * cycles * x / W + phase)
                path.lineTo(x, y) if i else path.moveTo(x, y)
            if x_end > 1:
                p.setPen(QPen(color, width))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)

        # 테두리와 모서리 재단선
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(0.5, 0.5, W - 1, H - 1))
        p.setPen(QPen(QColor(theme.MUTED), 1))
        m, L = 12.5, 10
        for cx, cy, sx, sy in ((m, m, 1, 1), (W - m, m, -1, 1), (m, H - m, 1, -1), (W - m, H - m, -1, -1)):
            p.drawLine(QPointF(cx, cy), QPointF(cx + L * sx, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy + L * sy))

        # 아이콘과 이름
        p.drawPixmap(36, 64, self.icon)
        p.setPen(QColor('#ece9e2'))
        p.setFont(sans(36, QFont.Weight.DemiBold))
        p.drawText(QRectF(104, 56, 340, 68), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, 'BreadLab')

        # 눈금자 + 진행 선
        base = H - 44
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        for i, x in enumerate(range(36, W - 35, 8)):
            h = 6 if i % 5 == 0 else 3
            p.drawLine(QPointF(x + 0.5, base - h), QPointF(x + 0.5, base))
        p.fillRect(QRectF(36, base + 4, W - 72, 1), QColor(255, 255, 255, 30))
        p.fillRect(QRectF(36, base + 4, (W - 72) * self.progress, 1), QColor(theme.ACCENT))

        if self.text:
            p.setPen(QColor(theme.MUTED))
            p.setFont(sans(12))
            p.drawText(QRectF(36, base + 10, W - 72, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       self.text)
        p.end()


def warm_up(card):
    """앱 안에서 처음 쓸 때 멈칫하지 않도록 무거운 준비를 미리 끝내고, 만든 작업 공간 목록을 돌려줍니다."""
    import traceback

    card.step('해석기 불러오는 중', 0.08)
    import numpy  # noqa: F401  (첫 가져오기가 가장 느립니다)
    import circuit_core
    from examples import EXAMPLES

    card.step('예제 회로 계산 중', 0.22)
    for i, (_, _, doc) in enumerate(EXAMPLES):
        parts, inst = circuit_core.validate_document(doc)
        for ch in ('ch1', 'ch2'):
            inst['psu'][ch]['on'] = True
        inst['fg']['on'] = True
        sim = circuit_core.Simulator()
        sim.step(parts, inst, 1e-3, 3)
        card.step('예제 회로 계산 중', 0.22 + 0.18 * (i + 1) / len(EXAMPLES))

    card.step('계측 장비 준비 중', 0.44)
    import instruments  # noqa: F401

    card.step('브레드보드 준비 중', 0.52)
    from breadboard import BreadboardWorkspace
    spaces = [BreadboardWorkspace()]

    card.step('화면 캐시 준비 중', 0.64)
    spaces[0]._rebuild()
    spaces[0].board_image()           # 글꼴·도형 캐시 데우기
    for kind in ('psu', 'fg', 'scope'):
        spaces[0].windows[kind].ensurePolished()
        spaces[0].windows[kind].grab()

    card.step('Arduino UNO 준비 중', 0.74)
    from workspace import Placeholder
    try:
        from arduino_lab import ArduinoWorkspace
        from arduino_lab.examples import EXAMPLES as UNO_EXAMPLES
        from arduino_lab.lang import parse
        uno = ArduinoWorkspace()
        card.step('스케치 해석기 준비 중', 0.86)
        for ex in UNO_EXAMPLES:
            try:
                parse(ex['sketch'])
            except Exception:
                pass
        uno.grab()
        spaces.append(uno)
    except Exception as e:
        traceback.print_exc()
        spaces.append(Placeholder('Arduino UNO', f'{type(e).__name__}: {e}'))

    card.step('편집 화면 여는 중', 0.95)
    return spaces
