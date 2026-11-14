"""UNO 보드 캔버스: 모듈 배치, 점퍼선 연결, 선택·이동·삭제, 실행 취소."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QMimeData
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QUndoCommand, QAction, QBrush,
                           QPainterPathStroker)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView, QMenu, QGraphicsPathItem

import theme
from . import art
from . import board as B
from . import modules as M

MIME = 'application/x-breadlab-uno-module'
PIN_HIT = 8.0


# ---------------------------------------------------------------- 그림 항목
class BoardItem(QGraphicsItem):
    def __init__(self, ws_board):
        super().__init__()
        self.board = ws_board
        self.state = {'ON': True}
        self.setZValue(0)

    def boundingRect(self):
        return QRectF(-20, -4, B.BOARD_W + 30, B.BOARD_H + 8)

    def paint(self, p, opt, widget=None):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        art.paint_board(p, self.state)

    def pin_at(self, pos):
        for pid, label, x, y, node in B.UNO_PINS:
            if pid == 'NC':
                continue
            if abs(pos.x() - x) <= PIN_HIT and abs(pos.y() - y) <= PIN_HIT:
                return pid
        return None

    def pin_scene(self, pid):
        x, y = B.UNO_PIN_POS[pid]
        return self.mapToScene(QPointF(x, y))

    def reset_hit(self, pos):
        return 26 <= pos.x() <= 54 and 8 <= pos.y() <= 36


class ModuleItem(QGraphicsItem):
    def __init__(self, mod):
        super().__init__()
        self.mod = mod
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setPos(mod.x, mod.y)
        self.setZValue(2)
        self.has_warning = False
        self._rect = art.extra_rect(mod)

    def boundingRect(self):
        return self._rect

    def shape(self):
        path = QPainterPath()
        path.addRect(art.module_rect(self.mod))
        return path

    def paint(self, p, opt, widget=None):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        art.paint_module(p, self.mod)
        r = art.module_rect(self.mod)
        if self.isSelected():
            p.setPen(QPen(QColor(theme.ACCENT), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r)
        if self.has_warning:
            badge = QRectF(r.right() - 12, r.top() - 2, 12, 12)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.DANGER))
            p.drawRect(badge)
            art.text(p, '!', badge.center().x(), badge.center().y(), 9, QColor('#ffffff'), bold=True)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # 5px 격자에 맞춥니다
            return QPointF(round(value.x() / 5) * 5, round(value.y() / 5) * 5)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.mod.x, self.mod.y = self.pos().x(), self.pos().y()
            sc = self.scene()
            if sc is not None:
                sc.module_moved(self.mod)
        return super().itemChange(change, value)

    def pin_at(self, pos):
        best = None
        for name, x, y in self.mod.PINS:
            d = abs(pos.x() - x) + abs(pos.y() - y)
            if abs(pos.x() - x) <= PIN_HIT and abs(pos.y() - y) <= PIN_HIT and (best is None or d < best[0]):
                best = (d, name)
        return best[1] if best else None

    def pin_scene(self, name):
        x, y = self.mod.pin_pos(name)
        return self.mapToScene(QPointF(x, y))


class WireItem(QGraphicsPathItem):
    def __init__(self, wire, scene):
        super().__init__()
        self.wire = wire
        self.sc = scene
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setZValue(5)
        self.rebuild()

    def color(self):
        return QColor(art.WIRE_HEX.get(self.wire.color, '#d48a3c'))

    def rebuild(self):
        sc = self.sc
        a = sc.end_pos(self.wire.a)
        b = sc.end_pos(self.wire.b)
        if a is None or b is None:
            return
        self.prepareGeometryChange()
        self.setPath(routed(a, sc.end_dir(self.wire.a), b, sc.end_dir(self.wire.b)))

    def shape(self):
        s = QPainterPathStroker()
        s.setWidth(8)
        return s.createStroke(self.path())

    def boundingRect(self):
        return self.path().boundingRect().adjusted(-6, -6, 6, 6)

    def paint(self, p, opt, widget=None):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = self.path()
        if self.isSelected():
            p.setPen(QPen(QColor(theme.ACCENT), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPath(path)
        p.setPen(QPen(QColor('#0b0b0d'), 4.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)
        p.setPen(QPen(self.color(), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)
        # 끝: 수 핀 머리
        for pt in (path.pointAtPercent(0), path.pointAtPercent(1)):
            p.setPen(QPen(QColor('#0b0b0d'), 1))
            p.setBrush(self.color())
            p.drawRect(QRectF(pt.x() - 2.5, pt.y() - 2.5, 5, 5))


def curve(a, da, b, db):
    dist = math.hypot(b.x() - a.x(), b.y() - a.y())
    k = min(90.0, 18 + dist * 0.35)
    path = QPainterPath(a)
    path.cubicTo(QPointF(a.x() + da[0] * k, a.y() + da[1] * k), QPointF(b.x() + db[0] * k, b.y() + db[1] * k), b)
    return path


BOARD_RECT = QRectF(0, 0, B.BOARD_W, B.BOARD_H)


def routed(a, da, b, db):
    """보드를 가로지르는 선(아래 헤더 ↔ 보드 위쪽 모듈 등)은 보드 옆으로 돌려 그립니다."""
    top, bottom = BOARD_RECT.top(), BOARD_RECT.bottom()
    for (p, dp, q, dq) in ((a, da, b, db), (b, db, a, da)):
        down_up = dp == (0, 1) and abs(p.y() - (bottom - 18)) < 1 and q.y() < top
        up_down = dp == (0, -1) and abs(p.y() - (top + 18)) < 1 and q.y() > bottom
        if not (down_up or up_down):
            continue
        right = (p.x() + q.x()) / 2 > BOARD_RECT.center().x()
        lane = (int(p.x()) // 20) % 4 * 7
        x_side = BOARD_RECT.right() + 22 + lane if right else BOARD_RECT.left() - 48 - lane
        sgn = 1 if down_up else -1
        y1 = (bottom + 16 + lane) if down_up else (top - 16 - lane)
        y2 = (top - 16 - lane) if down_up else (bottom + 16 + lane)
        r = 10.0
        sx = 1 if x_side > p.x() else -1
        path = QPainterPath(p)
        path.lineTo(p.x(), y1 - sgn * r)
        path.quadTo(p.x(), y1, p.x() + sx * r, y1)
        path.lineTo(x_side - sx * r, y1)
        path.quadTo(x_side, y1, x_side, y1 - sgn * r)
        path.lineTo(x_side, y2 + sgn * r)
        path.quadTo(x_side, y2, x_side - sx * r, y2)
        k = min(80.0, 18 + abs(q.x() - x_side) * 0.4)
        path.cubicTo(QPointF(x_side - sx * (r + k), y2), QPointF(q.x() + dq[0] * k, q.y() + dq[1] * k), q)
        if p is b:
            path = path.toReversed()
        return path
    return curve(a, da, b, db)


# ---------------------------------------------------------------- 실행 취소 명령
class AddModuleCmd(QUndoCommand):
    def __init__(self, scene, mod):
        super().__init__(f'{mod.NAME} 추가')
        self.sc, self.mod = scene, mod

    def redo(self):
        self.sc.add_module(self.mod)

    def undo(self):
        self.sc.remove_module(self.mod)


class RemoveCmd(QUndoCommand):
    def __init__(self, scene, mods, wires):
        super().__init__('삭제')
        self.sc = scene
        self.mods = list(mods)
        ids = {m.id for m in self.mods}
        extra = [w for w in scene.board.wires if w.a[0] in ids or w.b[0] in ids]
        self.wires = list(dict.fromkeys(list(wires) + extra))

    def redo(self):
        for w in self.wires:
            self.sc.remove_wire(w)
        for m in self.mods:
            self.sc.remove_module(m)

    def undo(self):
        for m in self.mods:
            self.sc.add_module(m)
        for w in self.wires:
            self.sc.add_wire(w)


class MoveCmd(QUndoCommand):
    def __init__(self, scene, moves):
        super().__init__('이동')
        self.sc, self.moves = scene, moves

    def redo(self):
        for mod, old, new in self.moves:
            self.sc.set_module_pos(mod, new)

    def undo(self):
        for mod, old, new in self.moves:
            self.sc.set_module_pos(mod, old)


class AddWireCmd(QUndoCommand):
    def __init__(self, scene, wire):
        super().__init__('점퍼선 연결')
        self.sc, self.wire = scene, wire

    def redo(self):
        self.sc.add_wire(self.wire)

    def undo(self):
        self.sc.remove_wire(self.wire)


class PropCmd(QUndoCommand):
    def __init__(self, scene, mod, key, old, new):
        super().__init__('속성 변경')
        self.sc, self.mod, self.key, self.old, self.new = scene, mod, key, old, new

    def redo(self):
        self.sc.set_prop(self.mod, self.key, self.new)

    def undo(self):
        self.sc.set_prop(self.mod, self.key, self.old)


class WireColorCmd(QUndoCommand):
    def __init__(self, scene, wire, old, new):
        super().__init__('선 색 변경')
        self.sc, self.wire, self.old, self.new = scene, wire, old, new

    def redo(self):
        self.sc.set_wire_color(self.wire, self.new)

    def undo(self):
        self.sc.set_wire_color(self.wire, self.old)


# ---------------------------------------------------------------- 장면
class UnoScene(QGraphicsScene):
    changed_doc = Signal()
    hover_text = Signal(str)

    def __init__(self, board, undo):
        super().__init__()
        self.board = board
        self.undo = undo
        self.board_item = BoardItem(board)
        self.addItem(self.board_item)
        self.mod_items = {}
        self.wire_items = {}
        self.setBackgroundBrush(QColor(theme.CANVAS))
        self.setSceneRect(QRectF(-1200, -1000, 3000, 2400))

    # --- 문서 동기화
    def rebuild(self):
        for it in list(self.mod_items.values()) + list(self.wire_items.values()):
            self.removeItem(it)
        self.mod_items.clear()
        self.wire_items.clear()
        for mod in self.board.modules.values():
            self._add_mod_item(mod)
        for w in self.board.wires:
            self._add_wire_item(w)

    def _add_mod_item(self, mod):
        it = ModuleItem(mod)
        self.addItem(it)
        self.mod_items[mod.id] = it
        return it

    def _add_wire_item(self, w):
        it = WireItem(w, self)
        self.addItem(it)
        self.wire_items[w.id] = it
        return it

    def add_module(self, mod):
        self.board.add_module(mod)
        self._add_mod_item(mod)
        self.changed_doc.emit()

    def remove_module(self, mod):
        it = self.mod_items.pop(mod.id, None)
        if it is not None:
            self.removeItem(it)
        self.board.remove_module(mod)
        self.changed_doc.emit()

    def add_wire(self, w):
        self.board.add_wire(w)
        self._add_wire_item(w)
        self.changed_doc.emit()

    def remove_wire(self, w):
        it = self.wire_items.pop(w.id, None)
        if it is not None:
            self.removeItem(it)
        self.board.remove_wire(w)
        self.changed_doc.emit()

    def set_module_pos(self, mod, pos):
        it = self.mod_items.get(mod.id)
        if it is not None:
            it.setPos(QPointF(*pos))
        self.changed_doc.emit()

    def set_prop(self, mod, key, value):
        with self.board.lock:
            mod.props[key] = value
        self.board.touch()
        it = self.mod_items.get(mod.id)
        if it is not None:
            it.update()
        self.changed_doc.emit()

    def set_wire_color(self, w, color):
        w.color = color
        it = self.wire_items.get(w.id)
        if it is not None:
            it.update()
        self.changed_doc.emit()

    def module_moved(self, mod):
        for w in self.board.wires:
            if w.a[0] == mod.id or w.b[0] == mod.id:
                it = self.wire_items.get(w.id)
                if it is not None:
                    it.rebuild()

    # --- 핀 위치
    def end_pos(self, end):
        owner, pin = end
        if owner == 'uno':
            if pin not in B.UNO_PIN_POS:
                return None
            return self.board_item.pin_scene(pin)
        it = self.mod_items.get(owner)
        if it is None or it.mod.pin_pos(pin) is None:
            return None
        return it.pin_scene(pin)

    def end_dir(self, end):
        owner, pin = end
        mod = self.board.modules.get(owner) if owner != 'uno' else None
        return art.pin_dir(owner, pin, mod)

    def pin_at(self, scene_pos):
        """장면 좌표의 핀: (주인, 핀) 또는 None. 위쪽 항목부터 찾습니다."""
        for it in sorted(self.mod_items.values(), key=lambda i: -i.zValue()):
            pin = it.pin_at(it.mapFromScene(scene_pos))
            if pin is not None:
                return (it.mod.id, pin)
        pin = self.board_item.pin_at(self.board_item.mapFromScene(scene_pos))
        if pin is not None:
            return ('uno', pin)
        return None

    def end_label(self, end):
        owner, pin = end
        if owner == 'uno':
            return f'UNO {B.UNO_PIN_LABEL[pin]}'
        mod = self.board.modules.get(owner)
        if mod is None:
            return pin
        return f'{mod.NAME} {mod.pin_label(pin)}'

    def refresh_states(self, warn_ids):
        for mid, it in self.mod_items.items():
            w = mid in warn_ids
            if w != it.has_warning:
                it.has_warning = w
            it.update()

    def auto_color(self, a, b):
        def kind(end):
            owner, pin = end
            if owner == 'uno':
                node = B.UNO_PIN_NODE[pin]
            else:
                node = pin
            node = node.upper()
            if node in ('5V', 'VCC', '3V3', 'VIN', '+', 'VS'):
                return 'red'
            if node in ('GND', '-', 'K'):
                return 'black'
            return None
        for end in (a, b):
            k = kind(end)
            if k:
                return k
        used = [w.color for w in self.board.wires]
        for c in art.SIGNAL_CYCLE:
            if c not in used:
                return c
        return art.SIGNAL_CYCLE[len(used) % len(art.SIGNAL_CYCLE)]


# ---------------------------------------------------------------- 뷰
class UnoView(QGraphicsView):
    request_reset = Signal()
    selection_info = Signal()

    def __init__(self, scene):
        super().__init__(scene)
        self.sc = scene
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setAcceptDrops(True)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setMouseTracking(True)
        self.pending = None           # 연결 중인 선: (시작 끝, 끌기 시작 위치)
        self.pending_item = None
        self.hover_end = None
        self.pressed_mod = None       # 누르고 있는 버튼 모듈
        self.press_positions = None
        self.panning = None
        self.live_changed = None      # 콜백: 모듈 실시간 값 변경
        scene.selectionChanged.connect(self.selection_info)

    # --- 확대
    def fit(self):
        r = self.sc.itemsBoundingRect().adjusted(-40, -40, 40, 40)
        self.fitInView(r, Qt.AspectRatioMode.KeepAspectRatio)
        if self.transform().m11() > 1.6:
            self.resetTransform()
            self.scale(1.6, 1.6)
            self.centerOn(r.center())

    def zoom(self, f):
        s = self.transform().m11() * f
        if 0.2 <= s <= 4:
            self.scale(f, f)

    def wheelEvent(self, e):
        pos = self.mapToScene(e.position().toPoint())
        it = self.module_item_at(pos)
        if it is not None and it.mod.TYPE == 'pot' and not (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            step = 16 if e.angleDelta().y() > 0 else -16
            v = max(0, min(1023, it.mod.props['value'] + step))
            self.set_live(it.mod, 'value', v)
            return
        self.zoom(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)

    def set_live(self, mod, key, value):
        with self.sc.board.lock:
            mod.props[key] = value
        self.sc.board.touch()
        it = self.sc.mod_items.get(mod.id)
        if it is not None:
            it.update()
        if self.live_changed:
            self.live_changed(mod)

    def module_item_at(self, scene_pos):
        for it in self.sc.items(scene_pos):
            if isinstance(it, ModuleItem):
                return it
        return None

    # --- 마우스
    def mousePressEvent(self, e):
        pos = self.mapToScene(e.position().toPoint())
        if e.button() == Qt.MouseButton.MiddleButton:
            self.panning = e.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if e.button() == Qt.MouseButton.RightButton:
            if self.pending:
                self.cancel_pending()
                return
            super().mousePressEvent(e)
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(e)
        end = self.sc.pin_at(pos)
        if self.pending is not None:
            if end is not None and end != self.pending[0]:
                self.finish_pending(end)
            else:
                self.cancel_pending()
            return
        if end is not None:
            self.start_pending(end, pos)
            return
        it = self.module_item_at(pos)
        if it is not None:
            local = it.mapFromScene(pos)
            act = art.interactive_hit(it.mod, local.x(), local.y())
            if act == 'press':
                self.pressed_mod = it.mod
                self.set_live(it.mod, 'pressed', True)
                return
            if act == 'toggle':
                key = 'pos' if it.mod.TYPE == 'slide_switch' else 'on'
                cur = it.mod.props[key]
                self.set_live(it.mod, key, (1 - cur) if key == 'pos' else (not cur))
                return
        if self.sc.board_item.reset_hit(self.sc.board_item.mapFromScene(pos)):
            self.request_reset.emit()
            return
        self.press_positions = {m.id: (m.x, m.y) for m in self.sc.board.modules.values()}
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.panning is not None:
            d = e.position() - self.panning
            self.panning = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        pos = self.mapToScene(e.position().toPoint())
        end = self.sc.pin_at(pos)
        if end != self.hover_end:
            self.hover_end = end
            self.sc.hover_text.emit(self.sc.end_label(end) if end else '')
            self.viewport().update()
        if self.pending is not None:
            self.update_pending(pos)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.panning is not None:
            self.panning = None
            self.unsetCursor()
            return
        if self.pressed_mod is not None:
            self.set_live(self.pressed_mod, 'pressed', False)
            self.pressed_mod = None
            return
        if self.pending is not None and e.button() == Qt.MouseButton.LeftButton:
            pos = self.mapToScene(e.position().toPoint())
            start_end, start_pos = self.pending
            moved = math.hypot(pos.x() - start_pos.x(), pos.y() - start_pos.y()) > 8
            if moved:
                end = self.sc.pin_at(pos)
                if end is not None and end != start_end:
                    self.finish_pending(end)
                else:
                    self.cancel_pending()
            return
        super().mouseReleaseEvent(e)
        if self.press_positions is not None:
            moves = []
            for mod in self.sc.board.modules.values():
                old = self.press_positions.get(mod.id)
                if old is not None and (abs(old[0] - mod.x) > 0.1 or abs(old[1] - mod.y) > 0.1):
                    moves.append((mod, old, (mod.x, mod.y)))
            self.press_positions = None
            if moves:
                self.sc.undo.push(MoveCmd(self.sc, moves))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and self.pending is not None:
            self.cancel_pending()
            return
        super().keyPressEvent(e)

    # --- 선 연결
    def start_pending(self, end, pos):
        self.sc.clearSelection()
        self.pending = (end, pos)
        it = QGraphicsPathItem()
        it.setZValue(20)
        it.setPen(QPen(QColor(theme.ACCENT), 2, Qt.PenStyle.DashLine, Qt.PenCapStyle.RoundCap))
        self.sc.addItem(it)
        self.pending_item = it
        self.update_pending(pos)
        self.sc.hover_text.emit(f'{self.sc.end_label(end)} → 연결할 핀을 누르십시오 (Esc: 취소)')

    def update_pending(self, pos):
        if self.pending_item is None:
            return
        start = self.pending[0]
        a = self.sc.end_pos(start)
        target = self.sc.pin_at(pos)
        b = self.sc.end_pos(target) if target else pos
        db = self.sc.end_dir(target) if target else (0, 0)
        self.pending_item.setPath(curve(a, self.sc.end_dir(start), b, db))

    def finish_pending(self, end):
        start = self.pending[0]
        self.cancel_pending()
        for w in self.sc.board.wires:
            if {w.a, w.b} == {start, end}:
                self.sc.hover_text.emit('이미 연결된 핀입니다')
                return
        wire = B.Wire(start, end, self.sc.auto_color(start, end))
        self.sc.undo.push(AddWireCmd(self.sc, wire))
        self.sc.hover_text.emit(f'연결됨: {self.sc.end_label(start)} — {self.sc.end_label(end)}')

    def cancel_pending(self):
        if self.pending_item is not None:
            self.sc.removeItem(self.pending_item)
        self.pending_item = None
        self.pending = None

    def drawForeground(self, p, rect):
        end = self.hover_end
        if end is None:
            return
        pt = self.sc.end_pos(end)
        if pt is None:
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(theme.TEXT), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(pt, 6, 6)

    # --- 오른쪽 메뉴
    def contextMenuEvent(self, e):
        pos = self.mapToScene(e.pos())
        items = self.sc.items(pos)
        wire_it = next((i for i in items if isinstance(i, WireItem)), None)
        mod_it = next((i for i in items if isinstance(i, ModuleItem)), None)
        menu = QMenu(self)
        if wire_it is not None:
            w = wire_it.wire
            sub = menu.addMenu('선 색')
            for key, name, _hex in art.WIRE_COLORS:
                a = sub.addAction(name)
                a.setCheckable(True)
                a.setChecked(w.color == key)
                a.triggered.connect(lambda _=False, k=key: self.sc.undo.push(WireColorCmd(self.sc, w, w.color, k)))
            menu.addAction('선 삭제').triggered.connect(lambda: self.sc.undo.push(RemoveCmd(self.sc, [], [w])))
        elif mod_it is not None:
            mod = mod_it.mod
            menu.addAction(f'{mod.NAME} 삭제').triggered.connect(
                lambda: self.sc.undo.push(RemoveCmd(self.sc, [mod], [])))
            menu.addAction('연결된 선 모두 삭제').triggered.connect(
                lambda: self.sc.undo.push(RemoveCmd(self.sc, [], [w for w in self.sc.board.wires
                                                                  if w.a[0] == mod.id or w.b[0] == mod.id])))
        else:
            return
        menu.exec(e.globalPos())

    # --- 끌어 놓기
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if not e.mimeData().hasFormat(MIME):
            return super().dropEvent(e)
        type_id = bytes(e.mimeData().data(MIME)).decode()
        pos = self.mapToScene(e.position().toPoint())
        self.place_module(type_id, pos)
        e.acceptProposedAction()

    def place_module(self, type_id, pos=None):
        cls = M.TYPES[type_id]
        mod = cls(self.sc.board.new_id(type_id))
        w, h = cls.SIZE
        if pos is None:
            mod.x, mod.y = self.free_spot(mod)
        else:
            mod.x = round((pos.x() - w / 2) / 5) * 5
            mod.y = round((pos.y() - h / 2) / 5) * 5
        self.sc.undo.push(AddModuleCmd(self.sc, mod))
        self.sc.clearSelection()
        it = self.sc.mod_items.get(mod.id)
        if it is not None:
            it.setSelected(True)
        self.setFocus()
        if pos is None and it is not None:
            self.ensureVisible(it, 40, 40)
        return mod

    def free_spot(self, mod):
        """보드 위쪽(헤더 핀 쪽)부터 다른 모듈과 겹치지 않는 자리를 찾습니다."""
        r = art.module_rect(mod).adjusted(-30, -34, 30, 10)
        taken = [QRectF(B.BOARD_W * 0, 0, B.BOARD_W, B.BOARD_H).adjusted(-30, -30, 30, 30)]
        for it in self.sc.mod_items.values():
            taken.append(it.mapRectToScene(art.module_rect(it.mod)))
        bottom_pins = max(y for _n, _x, y in mod.PINS) if mod.PINS else mod.SIZE[1]
        candidates = []
        for row in range(6):
            y = -60 - bottom_pins - row * 170
            for x in range(40, 520, 40):
                candidates.append((x, y))
        for row in range(4):
            for x in range(B.BOARD_W + 60, B.BOARD_W + 600, 50):
                candidates.append((x, row * 150))
        for x, y in candidates:
            cand = r.translated(x, y)
            if not any(cand.intersects(t) for t in taken):
                return float(x), float(y)
        return 40.0, -400.0

    def delete_selected(self):
        mods = [i.mod for i in self.sc.selectedItems() if isinstance(i, ModuleItem)]
        wires = [i.wire for i in self.sc.selectedItems() if isinstance(i, WireItem)]
        if mods or wires:
            self.sc.undo.push(RemoveCmd(self.sc, mods, wires))
