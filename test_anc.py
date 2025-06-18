from anc300_harware_gpt import ANC300

# serial connection
stage = ANC300("COM6")          # Windows  COM‑port
# # stage = ANC300("/dev/ttyUSB0")  # Linux

# # ethernet connection
# # stage = ANC300("192.168.0.10:7230")

# stage.set_voltage(1, 40)        # 40 V step amplitude on axis 1
# stage.set_frequency(1, 1000)    # 1 kHz stepping
# stage.move_by(1, 100)           # 100 forward steps
# stage.move_by(1, -100)          # 100 backward steps
# stage.stop(1)                   # emergency stop
stage.close()