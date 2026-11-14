"""스케치 편집기: 줄 번호, 간단한 구문 강조, 오류 줄 표시, 자동 들여쓰기."""
import re

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextFormat
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

import theme

KEYWORDS = r'\b(if|else|for|while|do|switch|case|default|break|continue|return|sizeof|static|const|volatile|true|false|HIGH|LOW|INPUT|OUTPUT|INPUT_PULLUP|LED_BUILTIN|enum)\b'
TYPES = r'\b(void|int|long|short|unsigned|signed|float|double|bool|boolean|byte|char|word|String|size_t|u?int(8|16|32)_t|Servo|LiquidCrystal_I2C|DHT|TM1637Display|LedControl)\b'
BUILTINS = (r'\b(setup|loop|pinMode|digitalWrite|digitalRead|analogRead|analogWrite|delay|delayMicroseconds|millis|'
            r'micros|map|constrain|min|max|abs|random|randomSeed|tone|noTone|pulseIn|Serial|Wire|attachInterrupt|'
            r'digitalPinToInterrupt|sqrt|pow|sin|cos)\b')


def fmt(color, bold=False, italic=False):
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.DemiBold)
    if italic:
        f.setFontItalic(True)
    return f


def code_font(px=13):
    """고정폭 글꼴 + 한글 대체 글꼴(주석·문자열의 한글이 작게 깨지지 않도록)."""
    f = theme.mono_font(px)
    f.setFamilies(theme.MONO_FAMILIES[:-1] + ['Malgun Gothic', '맑은 고딕'] + theme.MONO_FAMILIES[-1:])
    return f


class Highlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        self.rules = [
            (re.compile(TYPES), fmt(theme.DATA2)),
            (re.compile(KEYWORDS), fmt(theme.TEXT, bold=True)),
            (re.compile(BUILTINS), fmt(theme.DATA2)),
            (re.compile(r'\b(0x[0-9a-fA-F]+|0b[01]+|\d+\.?\d*([eE][+-]?\d+)?[uUlLfF]*)\b'), fmt(theme.TEXT)),
            (re.compile(r'^\s*#\s*\w+.*$'), fmt(theme.MUTED, bold=True)),
            (re.compile(r'"(\\.|[^"\\])*"|\'(\\.|[^\'\\])+\''), fmt(theme.MUTED)),
        ]
        self.comment = fmt(theme.DIM)

    def highlightBlock(self, text):
        for rx, f in self.rules:
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), f)
        # 주석: 줄 주석과 여러 줄 주석(/* */)
        self.setCurrentBlockState(0)
        i = 0
        if self.previousBlockState() == 1:
            end = text.find('*/')
            if end < 0:
                self.setFormat(0, len(text), self.comment)
                self.setCurrentBlockState(1)
                return
            self.setFormat(0, end + 2, self.comment)
            i = end + 2
        while True:
            start = self._find_comment_start(text, i)
            if start < 0:
                return
            if text.startswith('//', start):
                self.setFormat(start, len(text) - start, self.comment)
                return
            end = text.find('*/', start + 2)
            if end < 0:
                self.setFormat(start, len(text) - start, self.comment)
                self.setCurrentBlockState(1)
                return
            self.setFormat(start, end + 2 - start, self.comment)
            i = end + 2

    @staticmethod
    def _find_comment_start(text, pos):
        in_str = None
        i = pos
        while i < len(text):
            c = text[i]
            if in_str:
                if c == '\\':
                    i += 2
                    continue
                if c == in_str:
                    in_str = None
            elif c in '"\'':
                in_str = c
            elif text.startswith('//', i) or text.startswith('/*', i):
                return i
            i += 1
        return -1


class LineArea(QWidget):
    def __init__(self, ed):
        super().__init__(ed)
        self.ed = ed

    def sizeHint(self):
        return QSize(self.ed.line_area_width(), 0)

    def paintEvent(self, e):
        self.ed.paint_lines(e)


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(code_font(13))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 2)
        self.area = LineArea(self)
        self.hl = Highlighter(self.document())
        self.error_line = None
        self.blockCountChanged.connect(self._update_width)
        self.updateRequest.connect(self._update_area)
        self.cursorPositionChanged.connect(self._update_selections)
        self._update_width()
        self._update_selections()
        self.setStyleSheet(f'QPlainTextEdit {{ border: 0; border-radius: 0; padding: 0; background: {theme.BASE}; }}')

    def line_area_width(self):
        digits = max(3, len(str(self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance('9') * digits

    def _update_width(self, *_):
        self.setViewportMargins(self.line_area_width(), 0, 0, 0)

    def _update_area(self, rect, dy):
        if dy:
            self.area.scroll(0, dy)
        else:
            self.area.update(0, rect.y(), self.area.width(), rect.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self.area.setGeometry(QRect(cr.left(), cr.top(), self.line_area_width(), cr.height()))

    def paint_lines(self, e):
        p = QPainter(self.area)
        p.fillRect(e.rect(), QColor(theme.PANEL))
        p.setPen(QColor(theme.LINE))
        p.drawLine(self.area.width() - 1, e.rect().top(), self.area.width() - 1, e.rect().bottom())
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        cur = self.textCursor().blockNumber()
        p.setFont(self.font())
        while block.isValid() and top <= e.rect().bottom():
            if block.isVisible() and bottom >= e.rect().top():
                if self.error_line == num + 1:
                    p.fillRect(QRect(0, top, self.area.width() - 1, bottom - top), QColor(theme.DANGER))
                    p.setPen(QColor('#ffffff'))
                else:
                    p.setPen(QColor(theme.TEXT if num == cur else theme.DIM))
                p.drawText(QRect(0, top, self.area.width() - 7, self.fontMetrics().height()),
                           Qt.AlignmentFlag.AlignRight, str(num + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1

    def _update_selections(self):
        sels = []
        cur = QTextEdit.ExtraSelection()
        cur.format.setBackground(QColor(theme.HOVER))
        cur.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        cur.cursor = self.textCursor()
        cur.cursor.clearSelection()
        sels.append(cur)
        if self.error_line:
            block = self.document().findBlockByNumber(self.error_line - 1)
            if block.isValid():
                err = QTextEdit.ExtraSelection()
                c = QColor(theme.DANGER)
                c.setAlpha(45)
                err.format.setBackground(c)
                err.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                err.cursor = QTextCursor(block)
                sels.append(err)
        self.setExtraSelections(sels)

    def set_error_line(self, line):
        self.error_line = line or None
        self._update_selections()
        self.area.update()

    def goto_line(self, line):
        block = self.document().findBlockByNumber(max(0, line - 1))
        if block.isValid():
            c = QTextCursor(block)
            self.setTextCursor(c)
            self.centerCursor()
            self.setFocus()

    def keyPressEvent(self, e):
        key = e.key()
        if key == Qt.Key.Key_Tab and not e.modifiers():
            self.insertPlainText('  ')
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            c = self.textCursor()
            line = c.block().text()
            indent = re.match(r'\s*', line).group()
            before = line[:c.positionInBlock()].rstrip()
            if before.endswith('{'):
                indent += '  '
            super().keyPressEvent(e)
            self.insertPlainText(indent)
            return
        if e.text() == '}':
            c = self.textCursor()
            line = c.block().text()
            if line.strip() == '' and len(line) >= 2 and c.positionInBlock() == len(line):
                for _ in range(2):
                    c.deletePreviousChar()
        super().keyPressEvent(e)
