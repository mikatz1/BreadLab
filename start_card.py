"""작업 공간이 비어 있을 때 캔버스 가운데에 띄우는 시작 카드(초보자용 첫 행동 안내)."""
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

import theme


class StartCard(QFrame):
    """actions: [(제목, 설명, 함수, 주 버튼 여부)]. 버튼을 누르면 카드는 닫힙니다."""

    def __init__(self, view, title, subtitle, actions):
        super().__init__(view)
        self.view = view
        self.dismissed = False
        self.setObjectName('startcard')
        self.setStyleSheet(
            f'QFrame#startcard {{ background: {theme.PANEL}; border: 1px solid {theme.LINE2}; border-radius: 3px; }}'
            f'QFrame#startcard QLabel {{ background: transparent; border: 0; }}'
            f'QPushButton#big {{ text-align: left; padding: 10px 14px; min-height: 40px; }}'
            f'QPushButton#primary {{ text-align: left; padding: 10px 14px; min-height: 40px; '
            f'border-color: {theme.ACCENT}; background: {theme.ACCENT_BG}; color: {theme.TEXT}; }}'
            f'QPushButton#primary:hover {{ background: #3a2224; }}')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(8)
        t = QLabel(title)
        f = t.font()
        f.setPixelSize(17)
        f.setBold(True)
        t.setFont(f)
        lay.addWidget(t)
        sub = QLabel(subtitle)
        sub.setObjectName('muted')
        sub.setWordWrap(True)
        lay.addWidget(sub)
        lay.addSpacing(4)
        for text, desc, fn, primary in actions:
            b = QPushButton(f'{text}\n{desc}')
            b.setObjectName('primary' if primary else 'big')
            b.clicked.connect(lambda _=False, fn=fn: (self.dismiss(), fn()))
            lay.addWidget(b)
        self.setFixedWidth(360)
        self.adjustSize()
        view.installEventFilter(_Follow(self, view))

    def dismiss(self):
        self.dismissed = True
        self.hide()

    def show_if(self, cond):
        self.setVisible(bool(cond) and not self.dismissed)
        if self.isVisible():
            self.reposition()
            self.raise_()

    def reposition(self):
        v = self.view
        self.move((v.width() - self.width()) // 2, int(v.height() * 0.5 - self.height() / 2))


class _Follow(QObject):
    def __init__(self, card, view):
        super().__init__(view)
        self.card = card

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.Resize and self.card.isVisible():
            self.card.reposition()
        return False
