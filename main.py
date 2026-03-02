import sys
import os
from src.gui import EmailValidatorApp
from PyQt5 import QtWidgets, QtGui, QtCore

if __name__ == '__main__':
    # Enable high DPI scaling
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    
    app = QtWidgets.QApplication(sys.argv)
    
    # Set application icon
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'favicon.ico')
    app.setWindowIcon(QtGui.QIcon(icon_path))
    
    window = EmailValidatorApp()
    window.show()
    sys.exit(app.exec_())