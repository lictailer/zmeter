import zhinst.ziPython as zi
import time

# Create API session
daq = zi.ziDAQServer('localhost', 8004, 6)
print("Scanning for devices...")

# Method 1: Try discovery to find all available devices
try:
    discovery = zi.ziDiscovery()
    devices = discovery.findAll()
    print(f"Discovery found: {devices}")
   
    # Look for MFLI devices
    mfli_device = None
    for device_serial in devices:
        if 'dev30037' in device_serial.lower() or '30037' in device_serial:
            mfli_device = device_serial
            break
           
    if mfli_device:
        print(f"Found MFLI: {mfli_device}")
        device_id = mfli_device.lower()
       
        # Try different interfaces for MFLI
        # For MFLI, the interface is typically empty string or 'auto'
        interfaces = ['', 'auto', '1GbE', 'USB3']
        connected = False
       
        for interface in interfaces:
            try:
                print(f"Trying interface: '{interface}' (empty string means auto-detect)")
                daq.connectDevice(device_id, interface)
                print(f"✓ Connected via interface '{interface}'")
                connected = True
                break
            except Exception as e:
                print(f"✗ Interface '{interface}' failed: {str(e)[:100]}...")
       
        if not connected:
            print("Could not connect with any interface")
            
            # Try to get more information about available interfaces
            try:
                # Check what interfaces are actually available
                device_info = daq.getDeviceSerial(device_id)
                print(f"Device info: {device_info}")
            except Exception as e:
                print(f"Could not get device info: {e}")
            
            exit()
    else:
        print("MFLI device not found in discovery")
        exit()
       
except Exception as e:
    print(f"Discovery method failed: {e}")
   
    # Method 2: Direct connection attempt
    print("Trying direct connection...")
    device_id = 'dev30037'
   
    # Try direct connection with empty interface (auto-detect)
    try:
        print("Attempting direct connection with auto-detect interface...")
        daq.connectDevice(device_id, '')
        print(f"Connected to {device_id}")
    except Exception as e:
        print(f"Direct connection failed: {e}")
        
        # Get list of all nodes to see what's actually available
        try:
            all_devices = daq.listNodes('/zi/devices/visible', 0)
            print(f"All visible device nodes: {all_devices}")
           
            # Try to find the actual device ID
            for potential_device in all_devices:
                if potential_device.startswith('dev') and '30037' in potential_device:
                    device_id = potential_device
                    print(f"Found device in visible list: {device_id}")
                    break
                    
        except Exception as e2:
            print(f"Could not list visible devices: {e2}")
            
        print("Connection troubleshooting:")
        print("1. Ensure LabOne GUI is completely closed")
        print("2. Check device is powered and connected via USB")
        print("3. Try restarting the LabOne Data Server")
        print("4. Check if device is already connected to another process")
        print("5. Verify device serial number matches (DEV30037)")
        exit()

# If we get here, we're connected
print(f"Successfully connected to {device_id}")

# Verify connection by reading device info
try:
    device_type = daq.getString(f'/{device_id}/features/devtype')
    print(f"Device type: {device_type}")
    serial = daq.getString(f'/{device_id}/features/serial')
    print(f"Serial number: {serial}")
    options = daq.getString(f'/{device_id}/features/options')
    print(f"Device options: {options}")
except Exception as e:
    print(f"Warning: Could not read device info: {e}")

# Basic demodulator setup
print("\nConfiguring demodulator...")
try:
    # Enable demodulator 0
    daq.setInt(f'/{device_id}/demods/0/enable', 1)
    
    # Set sampling rate (Hz)
    daq.setDouble(f'/{device_id}/demods/0/rate', 1000)
    
    # Set filter order
    daq.setInt(f'/{device_id}/demods/0/order', 4)
    
    # Set time constant (seconds)
    daq.setDouble(f'/{device_id}/demods/0/timeconstant', 0.01)
    
    # Wait for settings to apply
    time.sleep(0.1)
    
    # Sync to ensure all settings are applied
    daq.sync()
    
    print("Demodulator configured successfully")
    
except Exception as e:
    print(f"Error configuring demodulator: {e}")
    daq.disconnect()
    exit()

# Read measurements
print("\nReading values...")
try:
    # For MFLI, the correct paths are different - let's first explore what's available
    print("Exploring available demodulator nodes...")
    try:
        demod_nodes = daq.listNodes(f'/{device_id}/demods/0/', 7)  # 7 = recursive + leaves
        print(f"Available demod nodes: {demod_nodes[:10]}...")  # Show first 10
        
        # Look for sample nodes specifically
        sample_nodes = [node for node in demod_nodes if 'sample' in node.lower()]
        print(f"Sample-related nodes: {sample_nodes}")
        
    except Exception as e:
        print(f"Could not list nodes: {e}")
    
    # Try different possible paths for MFLI samples
    sample_paths = [
        f'/{device_id}/demods/0/sample',
        f'/{device_id}/demods/0/sample/x',
        f'/{device_id}/demods/0/sample/y', 
        f'/{device_id}/demods/0/sample/r',
        f'/{device_id}/demods/0/sample/theta',
        f'/{device_id}/demods/0/sample/phase',
        f'/{device_id}/demods/0/sample/auxin0',
        f'/{device_id}/demods/0/sample/auxin1'
    ]
    
    print("\nTrying to read sample values...")
    results = {}
    
    for path in sample_paths:
        try:
            value = daq.getDouble(path)
            results[path.split('/')[-1]] = value
            print(f"✓ {path}: {value:.6f}")
        except Exception as e:
            print(f"✗ {path}: {str(e)[:50]}...")
    
    if results:
        print(f"\nSuccessful Measurements:")
        for key, value in results.items():
            if key in ['x', 'y', 'r']:
                print(f"{key.upper()}: {value:.6f} V")
            elif key in ['theta', 'phase']:
                print(f"Phase: {value:.3f} rad ({value*180/3.14159:.1f}°)")
    
    # Alternative: Try using poll() method which is more reliable for MFLI
    print("\nTrying poll() method...")
    try:
        # Subscribe to the sample node
        daq.subscribe(f'/{device_id}/demods/0/sample')
        
        # Poll for data
        poll_data = daq.poll(0.1, 100, 0, True)  # 100ms timeout
        
        if poll_data:
            print("Poll data received:")
            for path, data_dict in poll_data.items():
                print(f"Path: {path}")
                if 'value' in data_dict:
                    values = data_dict['value']
                    if len(values) > 0:
                        latest_value = values[-1]  # Get most recent value
                        print(f"  Latest value: {latest_value}")
        
        # Unsubscribe
        daq.unsubscribe('*')
        
    except Exception as e:
        print(f"Poll method failed: {e}")
    
except Exception as e:
    print(f"Error reading measurements: {e}")

# Disconnect
try:
    daq.disconnect()
    print("\nDisconnected successfully.")
except Exception as e:
    print(f"Error during disconnect: {e}")