import sys
import os
from src.gui import EmailValidatorApp
from PyQt5 import QtWidgets, QtGui

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    
    # Set application icon
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'favicon.ico')
    app.setWindowIcon(QtGui.QIcon(icon_path))
    
    window = EmailValidatorApp()
    window.show()
    sys.exit(app.exec_())