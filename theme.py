"""BreadLab 공통 디자인 토큰과 Qt 스타일.

모든 작업 공간(브레드보드, Arduino UNO)이 이 모듈만 사용합니다.
원칙: 무채색 어두운 바탕 + 포인트색 하나(빨강). 포인트색은 선택·진행 표시에만 씁니다.
모서리 2~3px, 1px 선으로 영역 구분, 그림자·그라데이션·이모지 없음, 촘촘한 데스크톱 앱 밀도.
"""
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QFrame, QLabel

BG = '#131418'        # 창 바탕
PANEL = '#191a1f'     # 메뉴바·상태바·패널
BASE = '#0d0e12'      # 입력칸·목록·캔버스 바탕
CANVAS = '#16171b'    # 그래픽 뷰 바탕
LINE = '#24252b'      # 구분선
LINE2 = '#30323a'     # 입력칸 테두리
HOVER = '#202127'
TEXT = '#d8d5ce'
MUTED = '#8b8983'
DIM = '#5c5b57'
ACCENT = '#ef5350'    # 유일한 포인트색(점퍼선 기본 빨강)
ACCENT_BG = '#2e1b1c'
ACCENT_TEXT = '#ff9a96'
WARN = '#e8836f'      # 경고 글자
DANGER = '#d0453a'    # 경고 표시(배지)
FIX = '#7cc47f'       # 경고의 고치는 법(초록)
DATA2 = '#7f9cc0'     # 그래프 두 번째 계열

FONT_FAMILIES = ['Segoe UI', 'Malgun Gothic', '맑은 고딕', 'Apple SD Gothic Neo', 'Noto Sans CJK KR']
MONO_FAMILIES = ['Consolas', 'D2Coding', 'Menlo', 'monospace']

STYLE = f'''
QWidget {{ background: {BG}; color: {TEXT}; font-size: 12px; }}
QMainWindow::separator {{ background: {LINE}; width: 1px; height: 1px; }}
QMenuBar {{ background: {PANEL}; border-bottom: 1px solid {LINE}; padding: 0 2px; }}
QMenuBar::item {{ background: transparent; padding: 4px 10px; }}
QMenuBar::item:selected {{ background: {HOVER}; }}
QMenu {{ background: {PANEL}; border: 1px solid {LINE2}; padding: 3px 0; }}
QMenu::item {{ padding: 4px 28px 4px 14px; }}
QMenu::item:selected {{ background: {HOVER}; }}
QMenu::item:disabled {{ color: {DIM}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 3px 0; }}
QMenu::indicator {{ width: 12px; height: 12px; left: 6px; }}
QTabBar {{ background: {PANEL}; }}
QTabBar::tab {{ background: {PANEL}; color: {MUTED}; padding: 5px 14px; border: 0;
               border-right: 1px solid {LINE}; border-bottom: 1px solid {LINE}; }}
QTabBar::tab:selected {{ background: {BG}; color: {TEXT}; border-bottom: 1px solid {ACCENT}; }}
QTabBar::tab:hover:!selected {{ color: {TEXT}; }}
QPushButton {{ background: #1f2026; border: 1px solid {LINE2}; border-radius: 2px; padding: 4px 10px; }}
QPushButton:hover {{ background: #26272e; }}
QPushButton:pressed {{ background: #2c2d34; }}
QPushButton:checked {{ background: {ACCENT_BG}; border-color: {ACCENT}; color: {ACCENT_TEXT}; }}
QPushButton:disabled {{ color: {DIM}; border-color: {LINE}; }}
QPushButton#tool {{ text-align: left; padding: 4px 8px; background: transparent; border: 1px solid transparent; }}
QPushButton#tool:hover {{ background: {HOVER}; }}
QPushButton#tool:checked {{ background: {ACCENT_BG}; border-color: #6a2a28; color: {ACCENT_TEXT}; }}
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {BASE}; border: 1px solid {LINE2}; border-radius: 2px; padding: 3px 5px;
    selection-background-color: {ACCENT_BG}; selection-color: {ACCENT_TEXT}; }}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {DIM}; }}
QComboBox QAbstractItemView {{ background: {PANEL}; border: 1px solid {LINE2}; selection-background-color: {HOVER}; }}
QListWidget, QTreeWidget, QTableWidget {{ background: {BASE}; border: 1px solid {LINE}; outline: 0; }}
QListWidget::item, QTreeWidget::item {{ padding: 3px 6px; }}
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{ background: {ACCENT_BG}; color: {ACCENT_TEXT}; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: 0; border-bottom: 1px solid {LINE}; padding: 3px 6px; }}
QLabel#section {{ color: {MUTED}; font-weight: 600; padding: 8px 0 2px 0; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#readout {{ background: {BASE}; border: 1px solid {LINE}; padding: 6px 8px; font-size: 18px; }}
QLabel#alerts {{ color: {WARN}; }}
QFrame#rule {{ background: {LINE}; border: 0; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {LINE}; color: {MUTED}; }}
QStatusBar QLabel {{ background: transparent; color: {MUTED}; padding: 0 6px; }}
QSplitter::handle {{ background: {LINE}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QScrollArea {{ border: 0; }}
QScrollBar:vertical {{ background: {BG}; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: {BG}; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {LINE2}; border-radius: 2px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: #3c3e47; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSlider::groove:horizontal {{ height: 3px; background: {LINE2}; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; }}
QSlider::handle:horizontal {{ width: 10px; margin: -5px 0; background: {TEXT}; border-radius: 1px; }}
QCheckBox::indicator {{ width: 12px; height: 12px; border: 1px solid {LINE2}; background: {BASE}; border-radius: 1px; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {LINE2}; padding: 4px 6px; }}
QDialog {{ background: {BG}; }}
'''


def apply_theme(app: QApplication):
    app.setStyle('Fusion')
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPixelSize(12)
    app.setFont(font)
    pal = QPalette()
    for role, color in ((QPalette.ColorRole.Window, BG), (QPalette.ColorRole.WindowText, TEXT),
                        (QPalette.ColorRole.Base, BASE), (QPalette.ColorRole.AlternateBase, PANEL),
                        (QPalette.ColorRole.Text, TEXT), (QPalette.ColorRole.Button, PANEL),
                        (QPalette.ColorRole.ButtonText, TEXT), (QPalette.ColorRole.Highlight, ACCENT_BG),
                        (QPalette.ColorRole.HighlightedText, ACCENT_TEXT), (QPalette.ColorRole.ToolTipBase, PANEL),
                        (QPalette.ColorRole.ToolTipText, TEXT), (QPalette.ColorRole.PlaceholderText, DIM),
                        (QPalette.ColorRole.Link, ACCENT)):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(STYLE)


def mono_font(px=12):
    f = QFont()
    f.setFamilies(MONO_FAMILIES)
    f.setPixelSize(px)
    return f


def section(text):
    """패널 안의 작은 소제목(그룹박스 대신 사용)."""
    label = QLabel(text)
    label.setObjectName('section')
    return label


def rule():
    """1px 가로 구분선."""
    line = QFrame()
    line.setObjectName('rule')
    line.setFixedHeight(1)
    return line


def alerts_html(warnings, limit=8):
    """경고 목록을 읽기 쉬운 카드로: 부품 이름(굵게) · 무엇이 문제인지 · 왜 위험한지(흐리게) · 고치는 법(→).
    영어 화면이면 먼저 번역한 뒤 나눕니다."""
    import html
    import re
    try:
        import i18n
        tr, english = i18n.tr, i18n.lang() != 'ko'
    except ImportError:
        tr, english = (lambda x: x), False
    cards = []
    for w in warnings[:limit]:
        w = tr(w)
        tag, sep, body = w.partition(': ')
        if not sep or len(tag) > 24:
            tag, body = '', w
        parts = [x for x in re.split(r'(?<=[.!])\s+', body.strip()) if x]
        fix = ''
        if len(parts) >= 2 and ('십시오' in parts[-1] or english):
            fix = parts.pop()
        problem = parts[0] if parts else body
        why = ' '.join(parts[1:])
        lines = [(f'<span style="color:{ACCENT_TEXT}; font-weight:600">{html.escape(tag)}</span>&nbsp; ' if tag else '')
                 + f'<span style="color:{TEXT}">{html.escape(problem)}</span>']
        if why:
            lines.append(f'<span style="color:#b5b1a8">{html.escape(why)}</span>')
        if fix:
            lines.append(f'<span style="color:{FIX}">→ {html.escape(fix)}</span>')
        cards.append('<table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:6px">'
                     f'<tr><td width="3" bgcolor="{ACCENT}"></td>'
                     f'<td bgcolor="{ACCENT_BG}" style="padding:6px 8px">' + '<br>'.join(lines) + '</td></tr></table>')
    if len(warnings) > limit:
        more = tr(f'외 {len(warnings) - limit}개')
        cards.append(f'<span style="color:{MUTED}">{html.escape(more)}</span>')
    return ''.join(cards)
