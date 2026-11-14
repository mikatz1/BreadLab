"""Arduino UNO 탭 E2E 점검: 실제 마우스·키보드 이벤트로 사용자가 하는 그대로 조작합니다.

실행: python e2e_uno.py [스크린샷 폴더]  (화면 없이 실행되며, 실패가 있으면 종료 코드 1)
"""
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('BREADLAB_NO_TOUR', '1')
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMenu, QMessageBox

import theme
from e2e_test import RESULTS, Mouse, check, key, pump

SHOTS = sys.argv[1] if len(sys.argv) > 1 else None


def wait_until(cond, sec=3.0):
    end = time.perf_counter() + sec
    while time.perf_counter() < end:
        if cond():
            return True
        pump(0.02)
    return cond()


def type_text(widget, text):
    """사람이 치듯 입력합니다. 줄바꿈은 실제 Enter 키로 보냅니다(편집기 자동 들여쓰기 경로 포함)."""
    widget.setFocus()
    pump(0.02)
    for i, line in enumerate(text.split(chr(10))):
        if i:
            QTest.keyClick(widget, Qt.Key.Key_Return)
        if line:
            QTest.keyClicks(widget, line)
    pump(0.02)


def main():
    app = QApplication([])
    theme.apply_theme(app)
    dialogs = []
    QMessageBox.exec = lambda self: dialogs.append(self.text()) or 0
    QMessageBox.question = staticmethod(lambda *a, **k: (dialogs.append(str(a[2]) if len(a) > 2 else ''),
                                                         QMessageBox.StandardButton.Yes)[1])
    QMessageBox.warning = staticmethod(lambda *a, **k: dialogs.append('warning: ' + str(a[2] if len(a) > 2 else '')))
    QMessageBox.information = staticmethod(lambda *a, **k: dialogs.append('info: ' + str(a[2] if len(a) > 2 else '')))
    menus_shown = []
    QMenu.exec = lambda self, *a, **k: menus_shown.append([x.text() for x in self.actions()]) or None
    QDialog.exec = lambda self: dialogs.append('dialog: ' + self.windowTitle()) or 0

    import BreadLab
    import arduino_lab.canvas as canvas_mod

    class FakeMenu(QMenu):
        def exec(self, *a, **k):
            menus_shown.append([x.text() for x in self.actions()])
            return None
    canvas_mod.QMenu = FakeMenu
    win = BreadLab.MainWindow()
    win.resize(1600, 960)
    win.show()
    pump(0.3)
    key(win, 'Ctrl+Tab')
    pump(0.4)
    uno = win.spaces[1]
    check('Ctrl+Tab으로 UNO 탭 열기', win.tabs.currentIndex() == 1)
    view, sc = uno.view, uno.scene
    m = Mouse(view)

    def shot(name):
        if SHOTS:
            win.grab().save(f'{SHOTS}/uno_{name}.png')

    shot('start')
    check('빈 보드에 시작 카드 표시', uno.start_card.isVisible())
    check('상태 줄에 사용 안내', uno.guide.isVisible() and '핀' in uno.guide.text())
    s = view.transform().m11()
    check('처음 열면 보드가 화면에 맞춰짐', s > 0.6, f'scale={s:.2f}')

    # ---------- 부품 목록: 두 번 눌러 추가
    def palette_item(type_id):
        pal = uno.palette
        for i in range(pal.topLevelItemCount()):
            top = pal.topLevelItem(i)
            top.setExpanded(True)
            for j in range(top.childCount()):
                it = top.child(j)
                if it.data(0, Qt.ItemDataRole.UserRole) == type_id:
                    return it
        return None

    def add_by_dclick(type_id):
        it = palette_item(type_id)
        pal = uno.palette
        pal.scrollToItem(it)
        pump(0.05)
        r = pal.visualItemRect(it)
        QTest.mouseClick(pal.viewport(), Qt.MouseButton.LeftButton, pos=r.center())
        QTest.mouseDClick(pal.viewport(), Qt.MouseButton.LeftButton, pos=r.center())
        pump(0.1)

    n = len(uno.board.modules)
    add_by_dclick('led')
    check('부품 목록 두 번 클릭으로 LED 추가', len(uno.board.modules) == n + 1)
    check('부품을 추가하면 시작 카드가 사라짐', not uno.start_card.isVisible())
    led = next(mm for mm in uno.board.modules.values() if mm.TYPE == 'led')
    add_by_dclick('resistor')
    res = next(mm for mm in uno.board.modules.values() if mm.TYPE == 'resistor')
    check('저항 추가', res is not None)
    QTest.mouseClick(uno.palette.viewport(), Qt.MouseButton.LeftButton,
                     pos=uno.palette.visualItemRect(palette_item('button')).center())
    pump(0.1)
    check('부품 목록 한 번 클릭하면 설명 표시', 'button' in str(getattr(uno.inspector, 'target', '')) or
          uno.inspector.isVisible())

    # ---------- 검색
    uno.search.setFocus()
    uno.search.setText('부저')      # 한글은 IME를 거치므로 키 입력 대신 내용을 넣습니다
    pump(0.05)
    visible = [palette_item(t) for t in ('buzzer', 'led')]
    check('부품 검색으로 목록 거르기', visible[1] is None or visible[1].isHidden(), '검색해도 LED가 보임')
    uno.search.clear()
    pump(0.05)

    # ---------- 배선: 클릭-클릭, 끌기, Esc
    def end_pt(end):
        return sc.end_pos(end)

    view.setFocus()
    w0 = len(uno.board.wires)
    m.click(end_pt(('uno', 'D13')))
    m.click(end_pt((res.id, '1')))
    check('핀 클릭-클릭으로 선 연결', len(uno.board.wires) == w0 + 1)
    m.drag(end_pt((res.id, '2')), end_pt((led.id, 'A')))
    check('핀에서 핀으로 끌어 선 연결', len(uno.board.wires) == w0 + 2)
    m.click(end_pt((led.id, 'K')))
    key(win, 'Esc')
    check('Esc로 연결 취소', view.pending is None)
    m.click(end_pt((led.id, 'K')))
    m.click(end_pt(('uno', 'GND.3')))
    check('GND 연결', len(uno.board.wires) == w0 + 3)
    m.click(end_pt((led.id, 'K')))
    m.click(end_pt(('uno', 'GND.3')))
    check('같은 연결을 다시 하면 막음', len(uno.board.wires) == w0 + 3)
    shot('wired')

    # ---------- 선택·삭제·실행 취소
    it = sc.mod_items[led.id]
    body = it.mapToScene(it.boundingRect().center())
    m.click(body)
    check('모듈 클릭으로 선택', it.isSelected())
    key(win, 'Del')
    check('Del로 모듈 삭제', led.id not in uno.board.modules)
    key(win, 'Ctrl+Z')
    check('Ctrl+Z로 되살리기', led.id in uno.board.modules and len(uno.board.wires) == w0 + 3)
    key(win, 'Ctrl+Y')
    check('Ctrl+Y 다시 실행', led.id not in uno.board.modules)
    key(win, 'Ctrl+Z')
    key(win, 'Ctrl+Shift+Z')
    check('Ctrl+Shift+Z 다시 실행', led.id not in uno.board.modules)
    key(win, 'Ctrl+Z')
    m.click(sc.mod_items[led.id].mapToScene(sc.mod_items[led.id].boundingRect().center()))
    key(win, 'Backspace')
    check('Backspace로 삭제', led.id not in uno.board.modules)
    key(win, 'Ctrl+Z')

    # 빈 곳 클릭 → 선택 해제
    m.click(QPointF(-400, 900))
    check('빈 곳 클릭하면 선택 해제', not sc.selectedItems())

    # 모듈 끌어 옮기기 + 실행 취소
    it = sc.mod_items[res.id]
    x0, y0 = res.x, res.y
    c = it.mapToScene(it.boundingRect().center())
    m.drag(c, QPointF(c.x() + 60, c.y() - 40))
    check('모듈 끌어 옮기기', abs(res.x - x0) > 20)
    key(win, 'Ctrl+Z')
    check('옮기기 실행 취소', abs(res.x - x0) < 1 and abs(res.y - y0) < 1)

    # 오른쪽 클릭 메뉴
    menus_shown.clear()
    view.contextMenuEvent(type('E', (), {'pos': lambda s: view.mapFromScene(c), 'globalPos': lambda s: view.mapToGlobal(view.mapFromScene(c))})())
    check('모듈 우클릭 메뉴', menus_shown and any('삭제' in t for t in menus_shown[-1]), str(menus_shown[-1:]))

    # ---------- 스케치: 편집기 입력 → 실행 → LED 깜박임
    ed = uno.editor
    ed.selectAll()
    type_text(ed, 'void setup() {\npinMode(13, OUTPUT);\nSerial.begin(9600);\nSerial.println("hello");\n}\n'
                  'void loop() {\ndigitalWrite(13, HIGH);\ndelay(200);\ndigitalWrite(13, LOW);\ndelay(200);\n}\n')
    check('편집기에 코드 입력', 'digitalWrite(13' in ed.toPlainText())
    # 편집기 안에서 Del/Ctrl+Z는 글자에만
    n_mod = len(uno.board.modules)
    key(win, 'Ctrl+Z')
    check('편집기 포커스에서 Ctrl+Z는 코드만 되돌림', len(uno.board.modules) == n_mod)
    key(win, 'Ctrl+Y')
    key(win, 'F5')
    check('F5 실행', wait_until(lambda: uno.running, 1.0))
    levels = set()
    wait_until(lambda: levels.add(led.state.get('level', 0) > 0.5) or len(levels) == 2, 2.5)
    check('D13 LED 깜박임(켜짐·꺼짐 모두 관찰)', len(levels) == 2, str(levels))
    check('시리얼 모니터에 출력', wait_until(lambda: 'hello' in uno.serial.out.toPlainText(), 1.5),
          uno.serial.out.toPlainText()[:40])
    shot('running')
    check('실행 막대에 중복 문구·내부 배율 없음', '실행 중' not in uno.state_label.text() and '×' not in uno.state_label.text(),
          uno.state_label.text())
    key(win, 'Shift+F5')
    check('Shift+F5 정지', wait_until(lambda: not uno.running, 1.0))

    # ---------- 컴파일 오류
    ed.selectAll()
    type_text(ed, 'void setup() {\nint a = 1\n}\nvoid loop() {}\n')
    dialogs.clear()
    key(win, 'F5')
    pump(0.3)
    check('문법 오류면 실행하지 않음', not uno.running)
    probs = [uno.problems.item(i).text() for i in range(uno.problems.count())]
    check('문제 탭에 오류와 줄 번호', any('2' in p for p in probs), str(probs))
    key(win, 'Ctrl+R')
    pump(0.1)

    # ---------- 시리얼 입력
    ed.selectAll()
    type_text(ed, 'void setup(){Serial.begin(9600);}\nvoid loop(){ if (Serial.available()) { char c = Serial.read(); '
                  'Serial.print("got "); Serial.println(c); } }\n')
    key(win, 'F5')
    wait_until(lambda: uno.running, 1.0)
    type_text(uno.serial.input, 'x')
    QTest.keyClick(uno.serial.input, Qt.Key.Key_Return)
    check('시리얼 입력 보내고 응답 받기', wait_until(lambda: 'got x' in uno.serial.out.toPlainText(), 2.0),
          uno.serial.out.toPlainText()[-40:])
    key(win, 'Shift+F5')
    wait_until(lambda: not uno.running, 1.0)

    # ---------- 버튼 모듈 누르기(실행 중)
    view.setFocus()
    add_by_dclick('button')
    btn = next(mm for mm in uno.board.modules.values() if mm.TYPE == 'button')
    m.click(end_pt((btn.id, '1')))
    m.click(end_pt(('uno', 'D2')))
    m.click(end_pt((btn.id, '2')))
    m.click(end_pt(('uno', 'GND.1')))
    ed.selectAll()
    type_text(ed, 'void setup(){pinMode(2, INPUT_PULLUP); Serial.begin(9600);}\nint last = 1;\n'
                  'void loop(){ int v = digitalRead(2); if (v != last) { Serial.println(v); last = v; } }\n')
    key(win, 'F5')
    wait_until(lambda: uno.running, 1.0)
    pump(0.3)
    bit = sc.mod_items[btn.id]
    bc = bit.mapToScene(bit.boundingRect().center())
    m.press(bc)
    pressed = wait_until(lambda: '0' in uno.serial.out.toPlainText().split(), 1.5)
    m.release(bc)
    check('버튼 모듈을 누르면 digitalRead가 0', pressed, uno.serial.out.toPlainText()[-30:])
    key(win, 'Shift+F5')
    wait_until(lambda: not uno.running, 1.0)

    # ---------- 저장·열기·새로 만들기
    tmp = Path(tempfile.mkdtemp()) / '왕복.uno'
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(tmp), ''))
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(tmp), ''))
    view.setFocus()
    key(win, 'Ctrl+S')
    pump(0.1)
    check('Ctrl+S 저장', tmp.exists())
    check('저장 후 제목에 * 없음', not win.windowTitle().split(' — ')[0].endswith('*'), win.windowTitle())
    mods_before = sorted(mm.TYPE for mm in uno.board.modules.values())
    key(win, 'Ctrl+N')
    pump(0.1)
    check('Ctrl+N 새 스케치', not uno.board.modules)
    key(win, 'Ctrl+O')
    pump(0.2)
    check('Ctrl+O 열기 왕복', sorted(mm.TYPE for mm in uno.board.modules.values()) == mods_before)

    # ---------- 보기
    s0 = view.transform().m11()
    key(win, 'Ctrl+=')
    check('Ctrl+= 확대', view.transform().m11() > s0)
    key(win, 'Ctrl+0')
    check('Ctrl+0 화면 맞춤', view.transform().m11() != s0 * 1.2)
    key(win, 'Ctrl+Shift+M')
    check('Ctrl+Shift+M 시리얼 모니터', uno.tabs.currentIndex() == 0)

    # ---------- 예제 열고 실행
    from arduino_lab.examples import EXAMPLES
    for i, ex in enumerate(EXAMPLES):
        uno.open_example(ex)
        pump(0.1)
        key(win, 'F5')
        ok = wait_until(lambda: uno.running, 1.0)
        pump(0.4)
        err = uno.machine.state == 'error'
        key(win, 'Shift+F5')
        wait_until(lambda: not uno.running, 1.0)
        check(f'예제 실행: {ex["title"]}', ok and not err, uno.machine.state)

    # ---------- 단축키 충돌
    from collections import defaultdict
    seen = defaultdict(list)
    for a in win.findChildren(type(win.menuBar().actions()[0])):
        for sc_ in a.shortcuts():
            if sc_.toString() and a.isEnabled():
                seen[sc_.toString()].append(a.text())
    clashes = {k: v for k, v in seen.items() if len(v) > 1}
    check('활성 단축키 중복 없음(UNO 탭)', not clashes, str(clashes))

    # ---------- F1, 끝내기
    key(win, 'F1')
    pump(0.3)
    tour = getattr(uno, 'tour', None)
    check('F1 → 둘러보기', tour is not None and tour.isVisible())
    if tour is not None:
        tour.hide()
    check('파일 메뉴에 끝내기', any(a.text() == '끝내기' for a in uno.menus()[0].actions()))

    print()
    failed = [r for r in RESULTS if not r[1]]
    print(f'{len(RESULTS) - len(failed)}/{len(RESULTS)} 통과')
    for name, _, detail in failed:
        print(f'  실패: {name}  {detail}')
    return 1 if failed else 0


if __name__ == '__main__':
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        code = 2
    os._exit(code)
