"""BreadLab: 브레드보드 회로 실습 · 가상 Arduino UNO.

실행: python BreadLab.py [회로 파일]
"""
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtCore import QProcess
from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeySequence
from PySide6.QtWidgets import (QApplication, QLabel, QMainWindow, QMenu, QMessageBox, QStackedWidget, QTabBar,
                               QVBoxLayout, QWidget)

import theme
from workspace import Placeholder

APP = 'BreadLab'


def resource(name):
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return str(base / name)


def load_workspaces():
    from breadboard import BreadboardWorkspace
    spaces = [BreadboardWorkspace()]
    for title, module, cls in (('Arduino UNO', 'arduino_lab', 'ArduinoWorkspace'),):
        try:
            mod = __import__(module, fromlist=[cls])
            spaces.append(getattr(mod, cls)())
        except Exception as e:   # 선택 작업 공간이 깨져도 브레드보드는 열려야 합니다
            traceback.print_exc()
            spaces.append(Placeholder(title, f'{type(e).__name__}: {e}'))
    return spaces


class MainWindow(QMainWindow):
    def __init__(self, spaces=None):
        super().__init__()
        self.resize(1560, 960)
        self.spaces = spaces or load_workspaces()
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.stack = QStackedWidget()
        for ws in self.spaces:
            self.tabs.addTab(ws.title)
            self.stack.addWidget(ws)
            ws.title_changed.connect(self.update_title)
            ws.status_message.connect(self.show_status)
        lay.addWidget(self.tabs)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.statusBar().setSizeGripEnabled(False)

        def window_action(text, fn, keys=()):
            a = QAction(text, self)
            if keys:
                a.setShortcuts([QKeySequence(k) for k in keys])
                a.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            a.triggered.connect(lambda _=False: fn())
            self.addAction(a)
            return a

        self.help_menu = QMenu('도움말(&H)', self)
        self.help_menu.addAction(window_action('도움말 · 단축키', self.show_help, ['F1']))
        self.help_menu.addSeparator()
        import i18n
        lang_menu = self.help_menu.addMenu('언어 · Language')
        group = QActionGroup(self)
        for code, name in i18n.LANGS.items():
            a = QAction(name, self)
            a.setCheckable(True)
            a.setChecked(code == i18n.lang())
            a.triggered.connect(lambda _=False, c=code: self.set_language(c))
            group.addAction(a)
            lang_menu.addAction(a)
        self.help_menu.addSeparator()
        self.help_menu.addAction(window_action('BreadLab 정보', self.show_about))
        self.quit_action = window_action('끝내기', self.close, ['Ctrl+Q'])
        window_action('다음 탭', lambda: self.tabs.setCurrentIndex((self.tabs.currentIndex() + 1) % self.tabs.count()),
                      ['Ctrl+Tab'])
        window_action('이전 탭', lambda: self.tabs.setCurrentIndex((self.tabs.currentIndex() - 1) % self.tabs.count()),
                      ['Ctrl+Shift+Tab'])

        self.current = None
        self.tabs.currentChanged.connect(self.switch)
        self.switch(0)

    def switch(self, index):
        if self.current is not None:
            self.current.deactivated()
            for a in self.current.actions():
                a.setEnabled(False)
        ws = self.spaces[index]
        self.stack.setCurrentWidget(ws)
        bar = self.statusBar()
        bar.clearMessage()                  # 앞 탭의 안내가 새 탭 상태 줄과 겹치지 않게
        for w in getattr(self, '_status_widgets', ()):
            bar.removeWidget(w)
        self._status_widgets = ws.status_widgets()
        if self._status_widgets:
            left, right = self._status_widgets
            bar.addWidget(left, 1)
            bar.addPermanentWidget(right)
            left.show()
            right.show()
        for a in ws.actions():
            a.setEnabled(True)
        if hasattr(ws, '_update_undo'):
            ws._update_undo()
        self.current = ws
        mb = self.menuBar()
        mb.clear()
        menus = ws.menus()
        for m in menus:      # '끝내기'는 어느 탭이든 파일 메뉴 맨 아래에
            for a in list(m.actions()):
                if a is self.quit_action or (a.isSeparator() and a.property('quit_sep')):
                    m.removeAction(a)
        if menus:
            sep = menus[0].addSeparator()
            sep.setProperty('quit_sep', True)
            menus[0].addAction(self.quit_action)
        for m in menus:
            mb.addMenu(m)
        mb.addMenu(self.help_menu)
        ws.activated()
        self.update_title()

    def update_title(self):
        if self.current is not None:
            self.setWindowTitle(f'{self.current.document_title()} — {APP}')

    def show_status(self, text, ms):
        if text:
            self.statusBar().showMessage(text, ms)
        else:
            self.statusBar().clearMessage()

    def open_path(self, path):
        ext = Path(path).suffix.lower()
        for i, ws in enumerate(self.spaces):
            if ext in ws.extensions:
                self.tabs.setCurrentIndex(i)
                return ws.open_path(path)
        QMessageBox.warning(self, '열기 실패', f'이 형식의 파일은 열 수 없습니다: {ext}')
        return False

    def closeEvent(self, e):
        for i, ws in enumerate(self.spaces):
            if ws.document_title().endswith('*'):
                self.tabs.setCurrentIndex(i)
            if not ws.maybe_close():
                e.ignore()
                self._restart = False
                return
        e.accept()
        if getattr(self, '_restart', False):          # 언어를 바꾼 뒤 다시 시작
            args = sys.argv[1:] if getattr(sys, 'frozen', False) else sys.argv
            QProcess.startDetached(sys.executable, args)

    def show_help(self):
        """F1: 현재 탭의 도움말(브레드보드는 사용법·단축키, UNO는 둘러보기)."""
        fn = getattr(self.current, 'show_help', None) or getattr(self.current, 'start_tour', None)
        if fn:
            fn()
        else:
            QMessageBox.information(self, '사용법', HELP)

    def set_language(self, code):
        import i18n
        if code == i18n.lang():
            return
        i18n.save_language(code)
        ask = ('언어를 바꿨습니다. 지금 다시 시작할까요?' if i18n.lang() == 'ko'
               else 'Language changed. Restart now?')
        if QMessageBox.question(self, 'BreadLab', ask) == QMessageBox.StandardButton.Yes:
            self._restart = True
            self.close()

    def show_about(self):
        QMessageBox.about(self, 'BreadLab 정보', ABOUT)


HELP = '''<b>브레드보드</b><br>
왼쪽에서 부품을 고른 뒤 구멍에서 구멍으로 끌거나 두 구멍을 차례로 클릭해 꽂습니다.
보드 왼쪽의 장비 단자(전원 CH1·CH2, 함수 발생기)에 점퍼선을 꽂아 회로에 전원을 넣습니다.<br><br>
<b>전원 공급기</b> 채널마다 전압과 전류 제한을 정하고 출력을 켭니다. 부하 전류가 제한값을 넘으면 CC로 바뀌어 전압이 내려갑니다.<br>
<b>함수 발생기</b> 사인·사각·삼각·톱니파와 DC를 50 Ω 출력으로 냅니다.<br>
<b>오실로스코프</b> 도구에서 'CH1/CH2 프로브'를 고르고 구멍을 클릭해 물립니다. 접지는 CH1 −(공통 접지)입니다.
시간축을 빠르게 두면 계산이 실시간보다 느려지며, 아래 상태 줄에 배율이 나옵니다.<br><br>
선택한 부품의 다리 끝을 끌면 다른 구멍으로 옮길 수 있습니다. 스위치는 더블클릭으로 전환합니다.
구멍에 마우스를 올리면 이어진 구멍이 표시되고 전압이 나옵니다.<br><br>
계산은 교육용 단순 모델입니다. 실제 부품과 값이 다를 수 있습니다.'''

ABOUT = '''<b>BreadLab</b><br>
브레드보드 회로를 꾸미고 계측 장비로 확인해 보는 교육용 프로그램입니다.<br><br>
<b>주의</b><br>
계산 결과는 단순화한 모델의 값입니다. 이를 바탕으로 한 실제 회로 제작·실험 중 생긴 오작동, 부품 손상, 사고에 대해
제작자는 책임을 지지 않습니다.<br><br>
<b>사용한 오픈소스</b><br>
Python (PSF License) · PySide6 (LGPL v3) · NumPy (BSD 3-Clause)<br><br>
<b>배포</b><br>
실행 파일과 회로 파일은 자유롭게 나눠도 됩니다. 상업적 이용과 수익 창출은 허용하지 않습니다.<br><br>
버그 제보와 기능 문의: Instagram @silica._.cat<br>
소스 코드가 필요하면 연락 주십시오.'''


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    import i18n
    i18n.load()
    i18n.install()
    theme.apply_theme(app)
    app.setWindowIcon(QIcon(resource('breadlab.ico')))
    from splash import StartupCard, warm_up
    card = StartupCard(resource('breadlab.ico'))
    card.show_card()
    spaces = warm_up(card)
    win = MainWindow(spaces)
    card.finish()
    win.show()
    if len(sys.argv) > 1:
        win.open_path(sys.argv[1])
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
