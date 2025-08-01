import zhinst.ziPython as zi
import time
import math

daq = zi.ziDAQServer('localhost', 8004, 6)
device = 'dev30037'
daq.connectDevice(device, '1GbE')

# ===== Output Settings =====
daq.setInt(f'/{device}/sigouts/0/on', 1)
daq.setDouble(f'/{device}/sigouts/0/amplitudes/0', 0.5)
daq.setDouble(f'/{device}/sigouts/0/amplitudes/1', 0.5)
daq.setInt(f'/{device}/sigouts/0/enables/0', 1)
daq.setInt(f'/{device}/sigouts/0/enables/1', 1)
daq.setDouble(f'/{device}/sigouts/0/range', 1.0)

# ===== Oscillator =====
daq.setDouble(f'/{device}/oscs/0/freq', 10e3)

# ===== Demodulator =====
daq.setInt(f'/{device}/demods/0/oscselect', 0)
daq.setInt(f'/{device}/demods/0/adcselect', 0)
daq.setInt(f'/{device}/demods/0/enable', 1)
daq.setDouble(f'/{device}/demods/0/rate', 1000)
daq.setDouble(f'/{device}/demods/0/timeconstant', 0.01)
daq.setInt(f'/{device}/demods/0/order', 1)
daq.sync()
time.sleep(0.1)

# ===== Poll Data =====
sample_path = f'/{device}/demods/0/sample'
daq.subscribe(sample_path)
time.sleep(0.1)
data = daq.poll(0.1, 100, 0, True)
daq.unsubscribe('*')

# ===== Inspect Data =====
print(f"\nData keys: {list(data.keys())}")
if sample_path in data:
    sample_data = data[sample_path]
    print(f"Sample data keys: {list(sample_data.keys())}")

    # Some firmware returns x, y, r directly, not under 'value'
    if 'value' in sample_data:
        latest = sample_data['value'][-1]
        x, y = latest[0], latest[1]
    elif 'x' in sample_data and 'y' in sample_data:
        x, y = sample_data['x'][-1], sample_data['y'][-1]
    else:
        raise RuntimeError("Could not find X/Y in sample data")

    r = math.hypot(x, y)
    print(f"\nDemodulated signal:")
    print(f"X = {x:.6f} V")
    print(f"Y = {y:.6f} V")
    print(f"R = {r:.6f} V")
else:
    print("No data received from demodulator")

# ===== Disconnect =====
daq.disconnectDevice(device)
daq.disconnect()
print("\nDisconnected successfully.")
