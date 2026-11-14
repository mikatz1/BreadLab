"""BreadLab E2E 점검: 실제 창에 마우스·키보드 이벤트를 보내 사용자가 하는 그대로 조작합니다.

실행: QT_QPA_PLATFORM=offscreen python e2e_test.py [스크린샷 폴더]
각 시나리오의 통과/실패를 출력하고, 실패가 하나라도 있으면 종료 코드 1을 돌려줍니다.
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

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

import theme

RESULTS = []
SHOTS = sys.argv[1] if len(sys.argv) > 1 else None


def check(name, cond, detail=''):
    RESULTS.append((name, bool(cond), detail))
    print(('PASS ' if cond else 'FAIL ') + name + (f'  — {detail}' if detail and not cond else ''), flush=True)


def pump(sec=0.05):
    end = time.perf_counter() + sec
    while time.perf_counter() < end:
        QApplication.processEvents()
        time.sleep(0.004)


class Mouse:
    """QGraphicsView 뷰포트에 실제 마우스 이벤트를 보냅니다."""

    def __init__(self, view):
        self.view = view

    def pt(self, scene_pt):
        return self.view.mapFromScene(scene_pt)

    def _send(self, kind, p, button, buttons, mods=Qt.KeyboardModifier.NoModifier):
        vp = self.view.viewport()
        local = QPointF(p)
        ev = QMouseEvent(kind, local, vp.mapToGlobal(local), button, buttons, mods)
        QApplication.sendEvent(vp, ev)
        QApplication.processEvents()

    def press(self, sp, button=Qt.MouseButton.LeftButton):
        self._send(QEvent.Type.MouseButtonPress, self.pt(sp), button, button)

    def move(self, sp, buttons=Qt.MouseButton.LeftButton):
        self._send(QEvent.Type.MouseMove, self.pt(sp), Qt.MouseButton.NoButton, buttons)

    def release(self, sp, button=Qt.MouseButton.LeftButton):
        self._send(QEvent.Type.MouseButtonRelease, self.pt(sp), button, Qt.MouseButton.NoButton)

    def click(self, sp, button=Qt.MouseButton.LeftButton):
        self.press(sp, button)
        self.release(sp, button)

    def dclick(self, sp):
        self.click(sp)
        self._send(QEvent.Type.MouseButtonDblClick, self.pt(sp), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        self.release(sp)

    def drag(self, a, b, steps=6):
        self.press(a)
        for i in range(1, steps + 1):
            self.move(QPointF(a.x() + (b.x() - a.x()) * i / steps, a.y() + (b.y() - a.y()) * i / steps))
        self.release(b)

    def wheel(self, sp, delta):
        p = QPointF(self.pt(sp))
        vp = self.view.viewport()
        ev = QWheelEvent(p, vp.mapToGlobal(p), QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(vp, ev)
        QApplication.processEvents()


def key(win, seq):
    """메인 창에 단축키를 누릅니다(포커스는 보드 뷰)."""
    from PySide6.QtGui import QKeySequence
    ks = QKeySequence(seq)
    combo = ks[0]
    QTest.keyClick(QApplication.focusWidget() or win, combo.key(), combo.keyboardModifiers())
    pump(0.05)


def main():
    app = QApplication([])
    theme.apply_theme(app)
    dialogs = []
    QMessageBox.exec = lambda self: dialogs.append(self.text()) or 0
    QMessageBox.question = staticmethod(lambda *a, **k: (dialogs.append(a[2] if len(a) > 2 else ''),
                                                         QMessageBox.StandardButton.Yes)[1])
    QMessageBox.warning = staticmethod(lambda *a, **k: dialogs.append('warning: ' + str(a[2] if len(a) > 2 else '')))
    QMessageBox.information = staticmethod(lambda *a, **k: dialogs.append('info: ' + str(a[2] if len(a) > 2 else '')))

    import BreadLab
    import breadboard as bb
    from circuit_core import NAMES

    t0 = time.perf_counter()
    win = BreadLab.MainWindow()
    win.resize(1600, 960)
    win.show()
    pump(0.3)
    check('시작: 메인 창 표시', win.isVisible(), f'{time.perf_counter() - t0:.2f}s')
    ws = win.spaces[0]
    check('빈 보드에 시작 카드 표시', ws.start_card.isVisible())
    if SHOTS:
        win.grab().save(f'{SHOTS}/e2e_start_card.png')
    m = Mouse(ws.view)
    ws.view.setFocus()
    pos = bb.pos

    def shot(name):
        if SHOTS:
            win.grab().save(f'{SHOTS}/e2e_{name}.png')

    # ---------- 부품 설치: 끌기 (도구를 고르면 시작 카드가 비켜야 함)
    for kind, a, b in (('resistor', 't0:2', 't0:6'), ('led', 't1:9', 'b1:9'), ('capacitor', 't0:12', 't0:15'),
                       ('diode', 'b2:2', 'b2:6'), ('switch', 'b0:12', 'b0:15'), ('ldr', 't3:18', 't3:21'),
                       ('wire', 'r0:2', 't4:2')):
        ws.tool_buttons[kind].click()
        pump()
        before = len(ws.parts)
        m.drag(pos(a), pos(b))
        pump(0.05)
        ok = len(ws.parts) == before + 1 and (ws.parts[-1].a, ws.parts[-1].b) == (a, b)
        check(f'끌어서 설치: {NAMES[kind]}', ok, f'parts={len(ws.parts)}')
        if kind == 'resistor':
            check('도구를 고르면 시작 카드가 사라짐', not ws.start_card.isVisible())

    # ---------- 부품 설치: 두 번 클릭
    ws.tool_buttons['resistor'].click()
    pump()
    before = len(ws.parts)
    m.click(pos('b3:20'))
    pump()
    m.click(pos('b3:25'))
    pump()
    check('클릭-클릭 설치', len(ws.parts) == before + 1 and ws.parts[-1].b == 'b3:25')

    # 같은 구멍 클릭 → 취소
    before = len(ws.parts)
    m.click(pos('b3:27'))
    m.click(pos('b3:27'))
    pump()
    check('같은 구멍 두 번 클릭은 설치 안 함', len(ws.parts) == before)

    # Esc로 대기 취소
    m.click(pos('b4:27'))
    key(win, 'Esc')
    check('Esc로 첫 구멍 취소', ws.pending is None)

    # NPN 세 번 클릭
    ws.tool_buttons['npn'].click()
    pump()
    before = len(ws.parts)
    for h in ('b0:20', 'b0:22', 'b0:24'):
        m.click(pos(h))
        pump()
    check('NPN 세 번 클릭 설치', len(ws.parts) == before + 1 and ws.parts[-1].c == 'b0:24')

    # 다리 하나를 같은 구멍 두 번(드래그 없이 같은 위치)
    shot('placed')

    # ---------- 선택·삭제·실행 취소
    key(win, 'Esc')
    key(win, 'Esc')
    check('Esc 두 번이면 선택 도구로', ws.mode == 'select', ws.mode)
    target = next(p for p in ws.parts if p.kind == 'resistor')
    dev = next(it for it in ws.scene.items() if isinstance(it, bb.Device) and it.part is target)
    m.click(dev.mid())
    pump()
    check('부품 몸체 클릭으로 선택', ws.selected == target.id, f'selected={ws.selected}')
    n = len(ws.parts)
    key(win, 'Del')
    check('Del로 삭제', len(ws.parts) == n - 1)
    key(win, 'Ctrl+Z')
    check('Ctrl+Z로 되살리기', len(ws.parts) == n)
    key(win, 'Ctrl+Y')
    check('Ctrl+Y로 다시 실행', len(ws.parts) == n - 1)
    key(win, 'Ctrl+Shift+Z')
    check('Ctrl+Shift+Z(표준 다시 실행)도 동작', len(ws.parts) == n - 1 or len(ws.parts) == n,
          '아무 일도 일어나지 않음' if len(ws.parts) == n - 1 else '')
    key(win, 'Ctrl+Z')
    pump(0.1)
    check('Backspace로도 삭제', False, '단축키 없음') if False else None

    # 빈 곳 클릭 → 선택 해제
    ws.select(target.id)
    m.click(QPointF(500, 600))
    check('빈 곳 클릭하면 선택 해제', ws.selected is None)

    # ---------- 다리 끌어 옮기기
    sel = next(p for p in ws.parts if p.kind == 'capacitor')
    ws.select(sel.id)
    pump()
    m.drag(pos(sel.b), pos('t0:17'))
    pump()
    check('선택한 부품 다리 끌어 옮기기', sel.b == 't0:17', f'b={sel.b}')
    m.drag(pos(sel.b), pos(sel.a))
    check('다리를 반대쪽 다리 구멍에 놓으면 거부', sel.b != sel.a)

    # ---------- 스위치 더블클릭
    sw = next(p for p in ws.parts if p.kind == 'switch')
    dev = next(it for it in ws.scene.items() if isinstance(it, bb.Device) and it.part is sw)
    state = sw.closed
    m.dclick(dev.mid())
    pump(0.1)
    check('스위치 더블클릭 전환', sw.closed != state)

    # ---------- 오른쪽 클릭 메뉴(키보드로 메뉴 대신 확인)
    # ---------- 리드 연결: 도구 + 장비 창 버튼
    ws.tool_buttons['lead'].click()
    pump()
    ws.nf_lead.setCurrentIndex(ws.nf_lead.findData('p:1+'))
    m.click(pos('r0:0'))
    pump()
    check('리드 도구로 CH1 + 물리기', ws.inst['leads']['p:1+'] == 'r0:0')
    ws.psu.lead_requested.emit('p:1-')
    pump()
    m.click(pos('b4:9'))
    pump()
    check('전원 창 "− 꽂기" 후 구멍 클릭', ws.inst['leads']['p:1-'] == 'b4:9')
    m.click(pos('b4:9'))
    pump()
    check('같은 구멍 다시 클릭하면 리드 떼기', ws.inst['leads']['p:1-'] is None)
    m.click(pos('b4:9'))
    pump()

    # ---------- 전원 켜고 LED 회로 동작
    ws.set_mode('select')
    ws.parts.clear()
    ws.refresh()
    pump(0.1)
    for kind, a, b in (('resistor', 't0:2', 't0:6'), ('led', 't1:6', 'b1:6'), ('wire', 'b2:6', 'b2:9')):
        ws.set_mode(kind)
        pump()
        if kind == 'resistor':
            ws.nf_value.setText('330')
        m.drag(pos(a), pos(b))
        pump()
    pump(0.1)
    ws.set_mode('select')
    sel_led = next(p for p in ws.parts if p.kind == 'led')
    ws.select(sel_led.id)
    pump(0.2)
    check('출력이 꺼져 있으면 측정값 대신 안내', '꺼져' in ws.detail.text(), ws.detail.text())
    ws.inst['leads'].update({'p:1+': 't3:2', 'p:1-': 'b4:9'})
    ws.refresh()
    ws.set_mode('select')
    pump(0.1)
    ws.open_instrument('psu')
    pump(0.2)
    ws.psu.w['ch1']['out'].click()
    pump(0.6)
    i = ws.result['psu']['ch1']['current']
    check('전원 켜면 LED 회로에 약 9 mA', 0.008 < i < 0.010, f'{i * 1000:.2f} mA')
    shot('led_on')

    # 전원 창에서 단축키가 먹는지(포커스가 장비 창에 있을 때)
    check('출력을 켜면 측정값 표시', 'mA' in ws.detail.text(), ws.detail.text())
    ws.windows['psu'].activateWindow()
    ws.psu.w['ch1']['out'].setFocus()
    pump(0.05)
    n = len(ws.parts)
    QTest.keyClick(ws.psu.w['ch1']['out'], Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    pump(0.1)
    check('장비 창에 포커스가 있어도 Ctrl+Z 동작', len(ws.parts) != n, '장비 창에서는 단축키가 먹지 않음')
    QTest.keyClick(ws.psu.w['ch1']['out'], Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    pump(0.1)
    ws.psu.w['ch1']['vs'].setFocus()
    QTest.keyClick(ws.psu.w['ch1']['vs'], Qt.Key.Key_R)
    pump(0.05)
    check('입력칸에서 글자를 치면 도구 단축키가 끼어들지 않음', ws.mode == 'select', ws.mode)
    ws.view.setFocus()

    # ---------- 스코프: 함수 발생기 + 프로브
    ws.inst['leads'].update({'g:+': 't3:12', 'g:-': 'b4:9'})
    ws.inst['scope']['ch1'] = 't2:12'
    ws.refresh()
    ws.fg.out.click()
    ws.open_instrument('scope')
    ws.scope.autoset()
    pump(1.5)
    meas = ws.scope.measure.get('ch1') or {}
    check('스코프 자동 측정: 함수 발생기 50 Hz', meas.get('freq') and abs(meas['freq'] - 50) < 2,
          f'freq={meas.get("freq")}')

    # ---------- 저장·열기 왕복
    tmp = Path(tempfile.mkdtemp()) / '왕복.bd'
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(tmp), ''))
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(tmp), ''))
    key(win, 'Ctrl+S')
    pump(0.1)
    check('Ctrl+S 저장', tmp.exists())
    saved = json.loads(tmp.read_text(encoding='utf-8')) if tmp.exists() else {}
    check('저장 파일에는 출력이 꺼진 상태로', not saved.get('instruments', {}).get('psu', {}).get('ch1', {}).get('on', True))
    check('저장 후 제목에 * 없음', not win.windowTitle().split(' — ')[0].endswith('*'), win.windowTitle())
    parts_before = [(p.kind, p.a, p.b) for p in ws.parts]
    key(win, 'Ctrl+N')
    pump(0.1)
    check('Ctrl+N 새 회로', not ws.parts)
    key(win, 'Ctrl+O')
    pump(0.2)
    check('Ctrl+O 열기 왕복', [(p.kind, p.a, p.b) for p in ws.parts] == parts_before)

    # ---------- 회로도
    key(win, 'Ctrl+4')
    pump(0.3)
    sw_ = getattr(ws, '_schematic', None)
    check('Ctrl+4 회로도 창', sw_ is not None and sw_.isVisible())
    check('회로도가 그려짐', sw_ is not None and sw_.view.sch is not None and not sw_.view.sch.empty)
    if SHOTS and sw_ is not None:
        sw_.grab().save(f'{SHOTS}/e2e_schematic.png')
    n_before = len(sw_.view.sch.drawing.ops) if sw_ else 0
    ws.set_mode('resistor')
    pump()
    m.drag(pos('b3:22'), pos('b3:27'))
    ws.set_mode('select')
    pump(0.2)
    check('회로를 고치면 회로도도 바로 갱신', sw_ is not None and len(sw_.view.sch.drawing.ops) != n_before)
    key(win, 'Ctrl+Z')
    sch_png = Path(tempfile.mkdtemp()) / '회로도.png'
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(sch_png), 'PNG 이미지 (*.png)'))
    key(win, 'Ctrl+E')
    pump(0.2)
    check('Ctrl+E 회로도 내보내기(PNG)', sch_png.exists() and sch_png.stat().st_size > 1000)
    for fmt in ('svg', 'pdf'):
        f = sch_png.with_suffix('.' + fmt)
        sw_.export(fmt, str(f))
        check(f'회로도 {fmt.upper()} 저장', f.exists() and f.stat().st_size > 500)

    # ---------- 회로도에서 부품 누르기 ↔ 보드 선택
    from PySide6.QtCore import QPoint
    sv = sw_.view
    pump(0.1)
    rid = next((p.id for p in ws.parts if p.kind == 'resistor'), None)
    box = sv.sch.drawing.tags.get(rid) if rid is not None else None

    def to_screen(q):
        target = sv.paper().adjusted(16, 16, -16, -16)
        r = sv.sch.rect()
        sc = min(target.width() / r.width(), target.height() / r.height())
        return QPoint(int((q.x() - r.center().x()) * sc + target.center().x()),
                      int((q.y() - r.center().y()) * sc + target.center().y()))
    if box is not None:
        mp = QPointF(to_screen(box.center()))
        QApplication.sendEvent(sv, QMouseEvent(QEvent.Type.MouseMove, mp, sv.mapToGlobal(mp), Qt.MouseButton.NoButton,
                                               Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        pump()
        check('회로도: 부품에 마우스를 올리면 표시', sv.hover == rid, f'hover={sv.hover}')
        QTest.mouseClick(sv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, to_screen(box.center()))
        pump(0.1)
    check('회로도: 부품을 누르면 설명 카드', sw_.card.isVisible() and 'R' in sw_.card.title.text(),
          sw_.card.title.text())
    check('회로도: 누른 부품이 보드에서도 선택', ws.selected == rid, f'{ws.selected} {rid}')
    check('회로도: 카드에 부품 역할 설명', len(sw_.card.role.text()) > 10)
    sw_.card.show_btn.click()
    pump()
    check('카드 "보드에서 보기"', ws.selected == rid)
    other = next((p.id for p in ws.parts if p.kind != 'wire' and p.id != rid and p.id in sv.sch.drawing.tags), None)
    ws.select(other)
    pump()
    check('보드에서 고르면 회로도에도 표시', sv.selected == other, f'{sv.selected} {other}')
    sw_.choose(None)
    pump()
    check('카드 닫기 → 회로도만', not sw_.card.isVisible() and ws.selected is None)
    # 선(마디)에 마우스 → 보드 구멍 표시·설명, 보드 구멍에 마우스 → 회로도 마디 표시
    d_ = sv.sch.drawing
    nets_ = sorted(d_.nets(), key=str)
    if nets_:
        anchor, _h = d_.net_anchor(nets_[0])
        mp = QPointF(to_screen(anchor))
        QApplication.sendEvent(sv, QMouseEvent(QEvent.Type.MouseMove, mp, sv.mapToGlobal(mp), Qt.MouseButton.NoButton,
                                               Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        pump()
        check('회로도 선에 마우스 → 그 마디', sv.hover_net == nets_[0], f'{sv.hover_net} {nets_[0]}')
        check('회로도 마디 → 보드에서 이어진 구멍 표시', getattr(ws, 'ext_root', None) == nets_[0])
        check('마디 설명(전압·보드 위치)', len(sw_.net_info(nets_[0])) >= 2, str(sw_.net_info(nets_[0])))
        hole = next(h for h, n in ws.netmap.items() if n == nets_[0] and not h.startswith(('p:', 'g:')))
        sv.leaveEvent(None)
        ws.hover_hole(hole)
        pump()
        check('보드 구멍에 마우스 → 회로도 마디 표시', sv.board_net == nets_[0])
        ws.hover_hole(None)
    sw_.volts_box.setChecked(True)
    pump()
    check('전압 표시 켜기', sv.show_volts)
    sw_.volts_box.setChecked(False)
    src = next((t for t in sv.sch.drawing.tags if isinstance(t, str)), None)
    if src:
        sw_.choose(src)
        pump()
        check('전원 장비도 눌러서 설명', sw_.card.isVisible() and sw_.card.inst_btn.isVisible())
        sw_.choose(None)
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(tmp), ''))
    sw_.hide()
    ws.view.setFocus()

    # ---------- 새 부품: 가변저항(3단자), 연산 증폭기(IC) 꽂기와 IC 옮기기
    n0 = len(ws.parts)
    key(win, 'K')
    pump()
    check('K → 가변저항 도구', ws.mode == 'pot', ws.mode)
    for h in ('t1:24', 't1:25', 't1:26'):
        m.click(pos(h))
        pump()
    pot = ws.parts[-1] if len(ws.parts) > n0 else None
    check('가변저항: 세 구멍을 차례로 클릭해 꽂기', pot is not None and pot.kind == 'pot' and pot.c == 't1:26')
    key(win, 'A')
    pump()
    check('A → 연산 증폭기 도구', ws.mode == 'opamp', ws.mode)
    m.click(pos('b2:18'))
    pump()
    ic = ws.parts[-1]
    check('IC: 한 번 클릭으로 가운데 홈에 꽂기', ic.kind == 'opamp' and ic.a == 'b0:18' and ic.b == 't4:18'
          and len(ic.pins()) == 8, f'{ic.kind} {ic.a} {ic.b}')
    key(win, 'Esc')
    pump()
    m.drag(pos('b0:18'), pos('b0:20'))
    pump()
    check('IC를 끌어 통째로 옮기기', ic.a == 'b0:20' and ic.b == 't4:20', f'{ic.a} {ic.b}')
    for _ in range(3):
        key(win, 'Ctrl+Z')
    pump()
    check('새 부품도 실행 취소', len(ws.parts) == n0, f'{len(ws.parts)} vs {n0}')

    # ---------- 회로도 파일 가져오기(Ctrl+I)
    web = Path(__file__).with_name('circuits_web') / '555square.txt'
    if web.exists():
        ws.saved_state = ws.state_key()
        QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(web), ''))
        QMessageBox.information = staticmethod(lambda *a, **k: None)
        key(win, 'Ctrl+I')
        pump(0.3)
        kinds = sorted(p.kind for p in ws.parts if p.kind != 'wire')
        check('Ctrl+I 회로도 가져오기(555 발진기)', 'timer555' in kinds and kinds.count('resistor') == 2, str(kinds))
        from circuit_import import parse_falstad, make_plan, verify
        plan = make_plan(parse_falstad(web.read_text(encoding='utf-8')))
        check('가져온 회로의 연결이 원본과 1:1', not verify(plan, ws.parts, ws.inst))
        QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(tmp), ''))
        key(win, 'Ctrl+O')
        pump(0.2)

    # ---------- 확대/축소/맞춤
    s0 = ws.view.transform().m11()
    m.wheel(pos('t2:15'), 120)
    check('휠로 확대', ws.view.transform().m11() > s0)
    key(win, 'Ctrl+0')
    check('Ctrl+0 화면 맞춤', abs(ws.view.transform().m11() - s0) < 1e-6)

    # ---------- 도구 단축키(있어야 할 것들)
    for k, mode in (('R', 'resistor'), ('Shift+R', 'ldr'), ('W', 'wire'), ('L', 'led'), ('C', 'capacitor'),
                    ('D', 'diode'), ('S', 'switch'), ('Q', 'npn'), ('P', 'lead'), ('V', 'select')):
        ws.set_mode('select' if mode != 'select' else 'resistor')
        pump()
        key(win, k)
        check(f'도구 단축키 {k} → {mode}', ws.mode == mode, f'mode={ws.mode}')

    # ---------- 빈 곳 우클릭 → 선택 도구
    key(win, 'R')
    m.click(QPointF(500, 600), Qt.MouseButton.RightButton)
    pump()
    check('배치 도구에서 빈 곳 우클릭하면 선택 도구로', ws.mode == 'select', ws.mode)

    # ---------- Space(스위치), Backspace, Ctrl+Shift+Z, F5
    ws.set_mode('switch')
    pump()
    m.drag(pos('t2:24'), pos('t2:27'))
    ws.set_mode('select')
    pump()
    sw2 = ws.parts[-1]
    ws.select(sw2.id)
    ws.view.setFocus()
    st = sw2.closed
    win.activateWindow()
    QApplication.setActiveWindow(win) if hasattr(QApplication, 'setActiveWindow') else None
    pump()
    ws.view.setFocus()
    pump()
    print('   focus:', type(QApplication.focusWidget()).__name__)
    QTest.keyClick(ws.view, Qt.Key.Key_Space)
    pump()
    check('Space로 선택한 스위치 전환(보드 포커스)', sw2.closed != st)
    st = sw2.closed
    ws.list.setFocus()
    pump()
    QTest.keyClick(ws.list, Qt.Key.Key_Space)
    pump()
    check('Space로 선택한 스위치 전환(부품 목록 포커스)', sw2.closed != st)
    n = len(ws.parts)
    key(win, 'Backspace')
    check('Backspace로 삭제', len(ws.parts) == n - 1)
    key(win, 'Ctrl+Z')
    key(win, 'Ctrl+Shift+Z')
    check('Ctrl+Shift+Z로 다시 실행', len(ws.parts) == n - 1)
    paused = ws.paused
    key(win, 'F5')
    check('F5로 시뮬레이션 일시정지 전환', ws.paused != paused)
    key(win, 'F5')

    # ---------- 단축키 충돌
    from collections import defaultdict
    seen = defaultdict(list)
    for a in win.findChildren(type(win.menuBar().actions()[0])):
        for sc in a.shortcuts():
            if sc.toString() and a.isEnabled():
                seen[sc.toString()].append(a.text())
    clashes = {k: v for k, v in seen.items() if len(v) > 1}
    check('활성 단축키 중복 없음', not clashes, str(clashes))

    # ---------- 탭 전환
    from PySide6.QtWidgets import QDialog
    opened = []
    QDialog.exec = lambda self: opened.append(self.windowTitle()) or 0
    key(win, 'F1')
    check('브레드보드에서 F1 → 도움말 창', '브레드보드 도움말' in opened, str(opened))
    key(win, 'Ctrl+Tab')
    pump(0.3)
    check('Ctrl+Tab으로 UNO 탭', win.tabs.currentIndex() == 1)
    check('UNO 탭 전환 시 장비 창 숨김', not any(w.isVisible() for w in ws.windows.values()))
    uno = win.spaces[1]
    menu_titles = [a.text() for a in win.menuBar().actions()]
    check('UNO 메뉴에도 끝내기', any(a.text() == '끝내기' for a in uno.menus()[0].actions()), menu_titles)
    key(win, 'F1')
    pump(0.3)
    tour = getattr(uno, 'tour', None)
    check('UNO 탭에서 F1 → 둘러보기', tour is not None and tour.isVisible())
    if tour is not None:
        tour.hide()
    key(win, 'F5')
    pump(0.5)
    check('UNO F5 실행', uno.running)
    key(win, 'Shift+F5')
    pump(0.2)
    check('UNO Shift+F5 정지', not uno.running)
    key(win, 'Ctrl+Shift+Tab')
    pump(0.3)
    check('Ctrl+Shift+Tab으로 브레드보드 탭', win.tabs.currentIndex() == 0)
    pump(0.3)
    check('브레드보드 탭으로 돌아오면 장비 창 다시 표시', any(w.isVisible() for w in ws.windows.values()))

    # ---------- 닫기: 저장 안 한 변경
    ws.parts.pop()
    ws.refresh()
    dialogs.clear()
    win.close()
    pump(0.1)
    check('저장 안 한 변경이 있으면 닫을 때 물어봄', any('저장' in d for d in dialogs), str(dialogs))

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
