"""작업 공간 공통 규약.

BreadLab 창은 상단 탭으로 작업 공간(브레드보드, Arduino UNO)을 바꿉니다.
각 작업 공간은 Workspace를 상속한 QWidget 하나이며, 메뉴·파일 처리·타이머를 스스로 관리합니다.
창(shell)은 활성 작업 공간의 menus()를 메뉴바에 꽂고, 맨 끝에 공통 '도움말' 메뉴를 붙입니다.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QMenu, QVBoxLayout, QWidget


class Workspace(QWidget):
    #: 탭 이름
    title = ''
    #: 이 작업 공간이 여는 파일 확장자(점 포함). 명령줄로 받은 파일을 어느 탭이 열지 정할 때 씁니다.
    extensions: tuple[str, ...] = ()

    #: 상태바에 잠깐 보여 줄 메시지 (문구, 표시 시간 ms; 0이면 계속)
    status_message = Signal(str, int)
    #: 문서 이름이나 수정 여부가 바뀌면 보냅니다. 창 제목을 다시 그립니다.
    title_changed = Signal()

    def menus(self) -> list[QMenu]:
        """메뉴바에 넣을 메뉴(보통 파일, 편집, 보기 …). 한 번 만들어 두고 같은 객체를 돌려주세요."""
        return []

    def status_widgets(self):
        """창 상태바에 붙일 (왼쪽 안내, 오른쪽 상태) 위젯. 없으면 빈 튜플."""
        return ()

    def document_title(self) -> str:
        """창 제목에 쓸 문서 이름. 저장하지 않은 변경이 있으면 끝에 * 를 붙입니다."""
        return self.title

    def maybe_close(self) -> bool:
        """창을 닫기 전에 호출됩니다. 저장하지 않은 작업이 있으면 물어보고, 닫아도 되면 True."""
        return True

    def open_path(self, path: str) -> bool:
        """파일 경로를 엽니다(명령줄 인자 등). 성공하면 True."""
        return False

    def activated(self):
        """탭이 선택될 때. 타이머 재개 등에 씁니다."""

    def deactivated(self):
        """다른 탭으로 바뀔 때. 무거운 타이머는 멈춰 주세요."""


class Placeholder(Workspace):
    """아직 준비되지 않았거나 불러오지 못한 작업 공간."""

    def __init__(self, title, reason):
        super().__init__()
        self.title = title
        lay = QVBoxLayout(self)
        lab = QLabel(f'{title} 작업 공간을 불러오지 못했습니다.\n\n{reason}')
        lab.setObjectName('muted')
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab.setWordWrap(True)
        lay.addWidget(lab)
