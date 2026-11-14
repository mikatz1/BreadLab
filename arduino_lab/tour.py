"""둘러보기(투어): 화면을 어둡게 덮고 설명할 영역만 밝게 남겨 단계별로 안내합니다."""
from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

import theme


class Step:
    def __init__(self, title, body, target=None, action=None):
        self.title = title
        self.body = body
        self.target = target      # () → QWidget 또는 None(가운데 카드)
        self.action = action      # (버튼 글자, 함수) 또는 None


class TourOverlay(QWidget):
    finished = Signal(bool)       # True: 끝까지 봄, False: 건너뜀

    def __init__(self, host, steps):
        super().__init__(host)
        self.host = host
        self.steps = steps
        self.index = 0
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self.setStyleSheet('background: transparent;')
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.card = QFrame(self)
        self.card.setObjectName('tourcard')
        self.card.setStyleSheet(
            f'QFrame#tourcard {{ background: {theme.PANEL}; border: 1px solid {theme.LINE2}; border-radius: 3px; }}'
            f'QFrame#tourcard QLabel {{ background: transparent; border: 0; }}')
        self.card.setFixedWidth(300)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(0, 0, 0, 12)
        lay.setSpacing(6)
        self.progress = QFrame()
        self.progress.setFixedHeight(2)
        self.progress.setStyleSheet(f'background: {theme.LINE}; border: 0;')
        self.bar = QFrame(self.progress)
        self.bar.setStyleSheet(f'background: {theme.ACCENT}; border: 0;')
        lay.addWidget(self.progress)
        inner = QVBoxLayout()
        inner.setContentsMargins(14, 6, 14, 0)
        inner.setSpacing(6)
        self.count = QLabel()
        self.count.setObjectName('muted')
        inner.addWidget(self.count)
        self.title = QLabel()
        f = self.title.font()
        f.setPixelSize(14)
        f.setBold(True)
        self.title.setFont(f)
        inner.addWidget(self.title)
        self.body = QLabel()
        self.body.setWordWrap(True)
        inner.addWidget(self.body)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.skip_btn = QPushButton('건너뛰기')
        self.skip_btn.setObjectName('tool')
        self.skip_btn.clicked.connect(lambda: self.close_tour(False))
        row.addWidget(self.skip_btn)
        row.addStretch(1)
        self.action_btn = QPushButton()
        self.action_btn.clicked.connect(self.run_action)
        row.addWidget(self.action_btn)
        self.prev_btn = QPushButton('이전')
        self.prev_btn.clicked.connect(self.prev)
        row.addWidget(self.prev_btn)
        self.next_btn = QPushButton('다음')
        self.next_btn.clicked.connect(self.next)
        row.addWidget(self.next_btn)
        inner.addSpacing(4)
        inner.addLayout(row)
        lay.addLayout(inner)
        host.installEventFilter(self)
        self.setGeometry(host.rect())

    # --- 진행
    def start(self):
        self.index = 0
        self.setGeometry(self.host.rect())
        self.show()
        self.raise_()
        self.setFocus()
        self.show_step()

    def show_step(self):
        st = self.steps[self.index]
        n = len(self.steps)
        self.count.setText(f'{self.index + 1} / {n}')
        self.title.setText(st.title)
        self.body.setText(st.body)
        self.prev_btn.setEnabled(self.index > 0)
        last = self.index == n - 1
        self.next_btn.setText('마침' if last else '다음')
        self.skip_btn.setVisible(not last)
        self.action_btn.setVisible(st.action is not None)
        if st.action:
            self.action_btn.setText(st.action[0])
        self.bar.setGeometry(0, 0, int(300 * (self.index + 1) / n), 2)
        self.card.adjustSize()
        self.place_card()
        self.update()

    def next(self):
        if self.index >= len(self.steps) - 1:
            self.close_tour(True)
            return
        self.index += 1
        self.show_step()

    def prev(self):
        if self.index > 0:
            self.index -= 1
            self.show_step()

    def run_action(self):
        st = self.steps[self.index]
        if st.action:
            self.close_tour(True)
            st.action[1]()

    def close_tour(self, done):
        self.hide()
        self.finished.emit(done)

    # --- 위치
    def target_rect(self):
        st = self.steps[self.index]
        w = st.target() if st.target else None
        if w is None or not w.isVisible():
            return None
        top_left = w.mapTo(self.host, QPoint(0, 0))
        return QRect(top_left, w.size()).adjusted(-3, -3, 3, 3)

    def place_card(self):
        r = self.target_rect()
        cw, ch = self.card.width(), self.card.sizeHint().height()
        self.card.resize(cw, ch)
        W, H = self.width(), self.height()
        gap = 14
        if r is None:
            x, y = (W - cw) // 2, (H - ch) // 2
        elif r.right() + gap + cw <= W:
            x, y = r.right() + gap, r.top() + 20
        elif r.left() - gap - cw >= 0:
            x, y = r.left() - gap - cw, r.top() + 20
        elif r.bottom() + gap + ch <= H:
            x, y = r.left() + 20, r.bottom() + gap
        else:
            x, y = r.left() + 20, r.top() - gap - ch
        x = max(8, min(W - cw - 8, x))
        y = max(8, min(H - ch - 8, y))
        self.card.move(x, y)

    # --- 그리기와 입력
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shade = QColor(theme.BASE)
        shade.setAlpha(200)
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        r = self.target_rect()
        if r is not None:
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(r), 3, 3)
            path = path.subtracted(hole)
        p.fillPath(path, shade)
        if r is not None:
            p.setPen(QPen(QColor(theme.ACCENT), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)

    def mousePressEvent(self, e):
        e.accept()     # 투어 중에는 아래 화면을 누르지 않습니다

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.close_tour(False)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.next()
        elif k == Qt.Key.Key_Left:
            self.prev()
        else:
            super().keyPressEvent(e)

    def eventFilter(self, obj, ev):
        if obj is self.host and ev.type() == QEvent.Type.Resize and self.isVisible():
            self.setGeometry(self.host.rect())
            self.place_card()
        return False
