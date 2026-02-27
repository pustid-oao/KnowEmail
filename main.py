import sys
from src.gui import EmailValidatorApp
from PyQt5 import QtWidgets

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    window = EmailValidatorApp()
    window.show()
    sys.exit(app.exec_())