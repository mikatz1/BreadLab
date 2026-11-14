"""단독 실행: python -m arduino_lab [파일.uno]"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QLabel, QMainWindow  # noqa: E402

import theme  # noqa: E402
from arduino_lab import ArduinoWorkspace  # noqa: E402


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ws = ArduinoWorkspace()
        self.setCentralWidget(self.ws)
        for m in self.ws.menus():
            self.menuBar().addMenu(m)
        self.msg = QLabel()
        self.statusBar().addWidget(self.msg, 1)
        self.ws.status_message.connect(self.show_message)
        self.ws.title_changed.connect(self.update_title)
        self.update_title()
        self.resize(1440, 860)

    def show_message(self, text, ms):
        if ms:
            self.statusBar().showMessage(text, ms)
        else:
            self.statusBar().clearMessage()
            self.msg.setText(text)

    def update_title(self):
        self.setWindowTitle(f'{self.ws.document_title()} — BreadLab Arduino UNO')

    def closeEvent(self, e):
        if self.ws.maybe_close():
            e.accept()
        else:
            e.ignore()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply_theme(app)
    w = Window()
    if len(sys.argv) > 1:
        w.ws.open_path(sys.argv[1])
    w.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
