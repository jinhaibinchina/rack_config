from PyQt6.QtWidgets import QWidget, QLabel,QHBoxLayout,QVBoxLayout
from PyQt6.QtCore import QObject

class NameValLabel(QWidget):
    def __init__(self,name:str='', parent = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        self.name_label =QLabel(name)
        self.val_label =QLabel()
        layout.addWidget(self.name_label)
        layout.addWidget(self.val_label)

    def setName(self,name:str):
        self.name_label.setText(name)
    
    def setVal(self,val_name:str):
        self.val_label.setText(val_name)