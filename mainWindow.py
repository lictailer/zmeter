import random
import sympy as sp
import os
from PyQt6.QtGui import QCloseEvent
from PyQt6 import QtWidgets, uic, QtCore


# from sr830 import SR830
from nidaq.nidaq_main import NIDAQ
from keithley24xx.keithley24xx_main import Keithley24xx
# from k10cr1.k10cr1_main import K10CR1

from core.scan_info import *
from core.scanlist import ScanList


#Select Virtual Environment under zmeter_venv\.venv\Scripts\python.exe
class MainWindow(QtWidgets.QWidget):
    def __init__(self, info=None):
        super().__init__()
        print("Initiating the Program")
        uic.loadUi(r"core/ui/mainwindow.ui", self)
        self.info = info
        
        ####################################### edit this part##############################################
        self.save_path = os.path.join(os.getcwd(), "data")
        self.backup_main_path = r"Z:\Xuguo\SHG Desktop Backup"

        self.ppt_path.setPlainText(self.save_path + r"\log.pptx")
        self.save_info_path.setPlainText(self.save_path)
        self.backup_path = os.path.join(self.backup_main_path, os.path.basename(os.getcwd()))
        self.backup_Path.setPlainText(self.backup_path)

        # Equip name has to include a serial number
        self.equips = {
            # "lockin_0": SR830(),
            # "lockin_1": SR830(),
            "nidaq_0": NIDAQ(),
            # "HWP_0": K10CR1(),
            "Keithley_0": Keithley24xx(),
            # "Keithley_1": Keithley24xx()
        }
        
        self.equips["nidaq_0"].connect("Dev1")
        # self.equips["HWP_0"].connect(serial = "55369504")
        # self.equips["HWP_0"].connect(serial = "55243324")
        # self.equips["lockin_0"].connect_visa("GPIB0::7::INSTR")
        # self.equips["lockin_1"].connect_visa("GPIB0::8::INSTR")
        self.equips["Keithley_0"].connect_visa("GPIB0::1::INSTR")
        # self.equips["Keithley_1"].connect_visa("GPIB1::18::INSTR")


        daq_center = [0.26, 0.26]
        self.equips["nidaq_0"].pos_to_go_doubleSpinBox.setValue(daq_center[0])
        self.equips["nidaq_0"].pos_to_go_doubleSpinBox_2.setValue(daq_center[1])
        ####################################################################################################

        # {equipment name (e.g. lockin_0) : {variable name : set method},....}
        self.setter_equipment_info_for_scanning = {}
        # {equipment name (e.g. lockin_0) : {variable name : get method},....}
        self.getter_equipment_info_for_scanning = {}
        # {equipment(lockin_0) : [list of variable name]}
        self.setter_equipment_info = {}
        # {equipment : [list of variable name]}
        self.getter_equipment_info = {}
        # {artificial channel : "equation"}
        self.artificial_channels = {}

        self.make_equipment_info()
        self.set_artificial_channel_info()

        self.scanlist = ScanList(
            info=self.info,
            setter_equipment_info=self.setter_equipment_info,
            main_window=self,
            getter_equipment_info=self.getter_equipment_info,
        )
        self.scanlist.show()
        self.scanlist.setWindowTitle("Scan List")
        self.scan_list_button.clicked.connect(self.scanlist.show)

        self.open_equipment_buttons = []
        for equipment_name, equipment in self.equips.items():
            # equipment.show()
            equipment.setWindowTitle(equipment_name)
            open_button = QPushButton()
            open_button.setText(equipment_name)
            self.open_equipment_buttons.append(open_button)
            self.open_button_layout.addWidget(open_button)
            open_button.clicked.connect(equipment.show)

    # artificial channels

    def set_artificial_channel_info(self):
        self.equations = {
            # "A": "A=lockin_0_aux_1+lockin_0_aux_2",
            # "B": "B=lockin_0_aux_1-lockin_0_aux_2",
            "n": "n=Keithley_0_sour_volt_to+Keithley_1_sour_volt_to",
            "E": "E=Keithley_0_sour_volt_to-Keithley_1_sour_volt_to"
        }
        self.artificial_channels_values = {"n": 0, "E": 0}

        self.setter_equipment_info["artificial_channel"] = list(
            self.artificial_channels_values.keys()
        )
        self.getter_equipment_info["artificial_channel"] = list(
            self.artificial_channels_values.keys()
        )
        self.setter_equipment_info["control"] = ["wait"]

        self.simplified_equation = self.isolate_variables()
        for key, value in self.artificial_channels_values.items():
            if value == "measure":
                self.artificial_channels_values[key] = self.read_info(key)

        self.display()

    def display(self):
        self.eq_display = {}
        self.a_values_display = {}
        self.r_values_display = {}
        for artificial_channel, equation in self.equations.items():
            eq = QLabel()
            channel = QLabel()
            eq.setText(equation)
            channel.setText(
                f"{artificial_channel}: {self.artificial_channels_values[artificial_channel]}"
            )
            self.equation_layout.addWidget(eq)
            self.aritificial_value_layout.addWidget(channel)
            self.eq_display[artificial_channel] = eq
            self.a_values_display[artificial_channel] = channel

        for r_channel in self.simplified_equation.keys():
            r_channel_value = QLabel(f"{r_channel}: NA")
            self.regular_channel_layout.addWidget(r_channel_value)
            self.r_values_display[r_channel] = r_channel_value

    def isolate_variables(self):
        # Set to store all unique variables that are not keys
        all_rhs_symbols = set()

        # Collect all variables from the right-hand sides
        for equation in self.equations.values():
            _, rhs = equation.split("=")
            rhs = rhs.strip()
            all_rhs_symbols.update(sp.sympify(rhs).free_symbols)

        # Remove the variables that are already keys
        rhs_symbols = all_rhs_symbols - set(self.equations.keys())

        # Dictionary to store the simplified equations
        simplified_equations = {}

        # Collect all equations
        eqs = []
        for equation in self.equations.values():
            lhs, rhs = equation.split("=")
            lhs = lhs.strip()
            rhs = rhs.strip()
            eqs.append(sp.Eq(sp.sympify(lhs), sp.sympify(rhs)))

        # Solve for each variable in rhs_symbols
        solutions = sp.solve(eqs, list(rhs_symbols))

        # Add the simplified equations to the dictionary
        for symbol in rhs_symbols:
            if symbol in solutions:
                simplified_equations[str(symbol)] = f"{symbol} = {solutions[symbol]}"

        return simplified_equations

    def evaluate_equation(self, equation, variable_values):
        lhs, rhs = equation.split("=")
        rhs_expr = sp.sympify(rhs)
        result = rhs_expr.subs(variable_values)
        return float(result)

    def write_artificial_channel(self, val, variable):
        self.artificial_channels_values[variable] = val
        self.a_values_display[variable].setText(f"{variable}: {val}")
        print(variable, "set to", val)
        _, rhs = self.equations[variable].split("=")
        variables = set()
        rhs = rhs.strip()
        variables.update(sp.sympify(rhs).free_symbols)
        for var in variables:
            eq = self.simplified_equation[str(var)]
            value_to_write = self.evaluate_equation(eq, self.artificial_channels_values)
            self.write_info(value_to_write, str(var))
            self.r_values_display[str(var)].setText(f"{str(var)}: {value_to_write}")

    def read_artificial_channel(self, variable):
        eq = self.equations[variable]
        _, rhs = eq.split("=")
        variables = set()
        rhs = rhs.strip()
        variables.update(sp.sympify(rhs).free_symbols)
        var_values = {}
        for var in variables:
            var_values[str(var)] = self.read_info(str(var))
        self.artificial_channels_values[variable] = self.evaluate_equation(
            eq, var_values
        )
        return self.artificial_channels_values[variable]

    ## Adding devices and make equipment info

    def make_equipment_info(self):
        for key, equipment in self.equips.items():

            set_variable, get_variable = self.make_variables_dictionary(equipment)

            self.setter_equipment_info_for_scanning[key] = set_variable
            self.getter_equipment_info_for_scanning[key] = get_variable

            self.setter_equipment_info[key] = list(set_variable.keys())
            self.getter_equipment_info[key] = list(get_variable.keys())

    def make_variables_dictionary(self, equipment):
        get_variables = {}
        set_variables = {}
        get_methods = [
            method
            for method in dir(equipment.logic)
            if callable(getattr(equipment.logic, method))
        ]  ###################################
        set_methods = [
            method
            for method in dir(equipment.logic)
            if callable(getattr(equipment.logic, method))
        ]
        for method in get_methods:
            if method.startswith("get_"):
                var_name = method[4:]
                get_variables[var_name] = getattr(equipment.logic, method)
        for method in set_methods:
            if method.startswith("set_"):
                var_name = method[4:]
                set_variables[var_name] = getattr(equipment.logic, method)
        return set_variables, get_variables

    # execute control
    def execute_control(self, val, master):
        for index, character in enumerate(master):
            if character == "_":
                variable = master[index + 1 : :]
        if variable == "wait":
            time.sleep(val)

    # Read and write info

    def write_info(self, val, master):
        if np.isnan(val):
            return
        for key, equipment in self.setter_equipment_info_for_scanning.items():
            if key in master:  # key = lockin_0  master = lockin_0_amplitude
                time.sleep(0.01)
                variable = self.get_variable(master)
                equipment[variable](val)

    def get_variable(self, name):
        counter = False
        for index, character in enumerate(name):
            if character == "_":
                if counter:
                    return name[index + 1 : :]
                else:
                    counter = True

    def read_info(self, slave):

        if slave == "none":
            result = np.nan
        else:
            for key, equipment in self.getter_equipment_info_for_scanning.items():
                if key in slave:
                    variable = self.get_variable(slave)
                    result = equipment[variable]()
                # result=equipment.read_info(slave[-1])

        return result

    def stop_equipments_for_scanning(self):
        for name, equipment in self.equips.items():
            if hasattr(equipment, "stop_scan"):
                equipment.stop_scan()

    def start_equipments(self):
        for name, equipment in self.equips.items():
            if hasattr(equipment, "start_scan"):
                equipment.start_scan()

    def force_stop_equipments(self):
        for name, equipment in self.equips.items():
            if hasattr(equipment, "force_stop"):
                equipment.force_stop()

    def closeEvent(self, event: QCloseEvent):
        self.close()
        for equipment_name, equipment in self.equips.items():
            equipment.terminate_dev()
            print(equipment_name, "is closed")
        print("Main Window terminated.")
        event.accept()  # Accept the event to close the window

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow(info=ScanInfo)
    window.show()
    window.setWindowTitle("Main Window")
    app.exec()
