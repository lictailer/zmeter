import sys
from PyQt6 import QtWidgets, QtCore, QtGui, uic
from .scan_info import *



def create_menu_for_setter(d, menu):
    if isinstance(d, list):
        for e in d:
            create_menu_for_setter(e, menu)
    elif isinstance(d, dict):
        for key,value in d.items():
            if isinstance(value,int):
                action = menu.addAction(key)
                action.setIconVisibleInMenu(False)
            else:
                sub_menu = QtWidgets.QMenu(key, menu)
                # menus.append(sub_menu)
                # print(sub_menu.title())
                menu.addMenu(sub_menu)
                create_menu_for_setter(value, sub_menu)
    else:
            action = menu.addAction(d)
            action.setIconVisibleInMenu(False)
        
# def create_menu_for_level(d, menu):
#     for key,value in d.items():
#         sub_menu=QtWidgets.QMenu(key,menu)
#         for index,parameter in enumerate(value):
#             sub_sub_menu=QtWidgets.QMenu(str(index+1),sub_menu)
#             sub_menu.addMenu(sub_sub_menu)
#             for key in parameter.keys():
#                 action = sub_sub_menu.addAction(key)
#                 action.setIconVisibleInMenu(False)
            
#         menu.addMenu(sub_menu)


class NestedMenu(QtWidgets.QWidget):
    sig_self_changed = QtCore.pyqtSignal(object)

    def __init__(self, d=None, order=1):
        super().__init__()
        if 1 <= order <= 26:
            self.label  = QtWidgets.QLabel(f"{chr(ord('A') + order - 1)}: ")
        else:
            self.label  = QtWidgets.QLabel(f"{order}: ")
        self.button = QtWidgets.QPushButton()
        self.button.setFixedWidth(165)
        self.button.setFixedHeight(32)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.label)
        lay.addWidget(self.button)
        if d == None:
            d = ['None',
                {'Lockin1':
                ['x', 'y', 'r', 'p']},
                {'Lockin2':
                ['x', 'y', 'r', 'p']},
                ]
        self.set_choices(d)
        self.name = ''

    def set_choices(self, equipement_info):
        self.menu = QtWidgets.QMenu(self)
        create_menu_for_setter(equipement_info, self.menu)
        
        self.menu.triggered.connect(self.update_name)
        self.button.setMenu(self.menu)

    def set_chosen_one(self, chosen):
        self.name = chosen
        self.button.setText(chosen)
        self.sig_self_changed.emit(self)

    def update_name(self, action):
        tree = []
        tree.append(action.text())
        a = action
        while isinstance(a.parent(), QtWidgets.QMenu):
            tree.append(a.parent().title())
            a = a.parent()
        tree.pop(-1)
        name = ''
        for i in range(len(tree)):
            name += f'{tree[len(tree)-1-i]}_'
        name = name[0:-1]
        self.set_chosen_one(name)


if __name__ == "__main__":

    app = QtWidgets.QApplication(sys.argv)
    # equipment_info=copy.deepcopy(EquipmentInfo)
    d = [{'lockin_0': ['f','A','p']}]
    w = NestedMenu()
    w.show()
    w.set_choices(d)
    sys.exit(app.exec())
