import sys
from PyQt6 import QtWidgets, QtCore, QtGui, uic
from .scan_info import *



def create_menu_for_setter(d, menu, path=()):
    if isinstance(d, list):
        for e in d:
            create_menu_for_setter(e, menu, path)
    elif isinstance(d, dict):
        for key,value in d.items():
            if isinstance(value,int):
                action = menu.addAction(key)
                action.setIconVisibleInMenu(False)
                action.setData("_".join((*path, str(key))))
            else:
                sub_menu = QtWidgets.QMenu(key, menu)
                # menus.append(sub_menu)
                # print(sub_menu.title())
                menu.addMenu(sub_menu)
                create_menu_for_setter(value, sub_menu, (*path, str(key)))
    else:
            action = menu.addAction(d)
            action.setIconVisibleInMenu(False)
            action.setData("_".join((*path, str(d))))
        
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
        self.name = ''
        self.unresolved_name = ''
        self._choice_names = frozenset()
        self.menu = None
        if d == None:
            d = ['None',
                {'Lockin1':
                ['x', 'y', 'r', 'p']},
                {'Lockin2':
                ['x', 'y', 'r', 'p']},
                ]
        self.set_choices(d)

    def set_choices(self, equipement_info):
        """Replace the menu while retaining only a still-valid selection.

        Detaching the old menu before ``deleteLater`` keeps repeated catalog
        refreshes from accumulating parented menus/actions.  Persisted scan
        definitions are not rewritten here: an invalid visible selection is
        cleared and marked unresolved for the operator instead.
        """
        previous_name = self.name
        previous_unresolved_name = self.unresolved_name
        previous_button_text = self.button.text()
        old_menu = self.menu

        menu = QtWidgets.QMenu(self)
        create_menu_for_setter(equipement_info, menu)
        menu.triggered.connect(self.update_name)
        self.menu = menu
        self.button.setMenu(menu)

        self._choice_names = frozenset(
            str(action.data())
            for action in self._iter_leaf_actions(menu)
            if action.data() not in (None, "")
        )

        if old_menu is not None and old_menu is not menu:
            try:
                old_menu.triggered.disconnect(self.update_name)
            except (RuntimeError, TypeError):
                pass
            old_menu.setParent(None)
            old_menu.deleteLater()

        if previous_name:
            self._apply_selection(previous_name)
        elif previous_unresolved_name:
            self._apply_selection(previous_unresolved_name)
        else:
            self.name = ''
            self.unresolved_name = ''
            self.button.setToolTip('')
            self.button.setText(previous_button_text)

    @staticmethod
    def _iter_leaf_actions(menu):
        for action in menu.actions():
            sub_menu = action.menu()
            if sub_menu is None:
                yield action
            else:
                yield from NestedMenu._iter_leaf_actions(sub_menu)

    @property
    def choice_names(self):
        return self._choice_names

    def _apply_selection(self, chosen):
        chosen = str(chosen)
        sentinel = chosen.lower() in {'none', 'void'}
        if chosen and (chosen in self._choice_names or sentinel):
            self.name = chosen
            self.unresolved_name = ''
            self.button.setText(chosen)
            self.button.setToolTip('')
            return True

        self.name = ''
        self.unresolved_name = chosen
        self.button.setText(f"Unresolved: {chosen}")
        self.button.setToolTip(
            f"The selected channel '{chosen}' is not available in the current catalog."
        )
        return False

    def set_chosen_one(self, chosen):
        self._apply_selection(chosen)
        self.sig_self_changed.emit(self)

    def update_name(self, action):
        action_name = action.data()
        if action_name not in (None, ''):
            self.set_chosen_one(str(action_name))
            return

        # Compatibility fallback for a caller-provided action without the
        # catalog path stored in QAction.data().
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
