import sys
from PySide6.QtWidgets import QApplication
from .ui.main import MainWindow

def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Horo')
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        window.open_path(sys.argv[1])
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
