#import pythoncom
#pythoncom.CoInitialize()
# py -3.10 -m pip install pywin32
# py -3.10 -m pip install pythonnet
# adding the code above solves the 'QWindowsContext: OleInitialize() failed:  "COM error 0xffffffff80010106 RPC_E_CHANGED_MODE (Unknown error 0x080010106)"' error
# refer to https://github.com/pythonnet/pythonnet/issues/439
# https://stackoverflow.com/questions/20525554/pyside-qt-could-not-initialize-ole-error-80010106
# this must be added before calling clr / importing clr so I'm putting it here.
