"""Standalone, read-only MFLI connection check. Run on real hardware manually.

Set DEVICE_ID below for an IDE's Run action, or pass --device dev12345.
Importing this module and requesting --help never load the vendor API.
"""

import argparse
import json
import math
import re
import sys


# Local bench configuration. Replace with the serial printed on your instrument.
DEVICE_ID = "DEV30037"
SERVER_HOST = "192.168.141.54"  # Blank uses mf-<device serial>; an IP address is also accepted.
SERVER_PORT = 8004
API_LEVEL = 6


def validate_config(device, host, port):
    """Validate all user configuration before importing or calling the API."""
    device = device.strip().lower()
    if not re.fullmatch(r"dev[0-9]+", device):
        raise ValueError("Set DEVICE_ID or pass --device with your serial, e.g. dev12345.")
    host = host.strip() or f"mf-{device}"
    if any(char.isspace() for char in host) or "://" in host or "/" in host:
        raise ValueError("Use a server hostname or IP address, without http:// or a path.")
    if not 1 <= port <= 65535:
        raise ValueError("The server port must be between 1 and 65535.")
    return device, host, port


def ensure_device_connected(daq, device):
    """Use the server's connection state and interface, not the PC cable type."""
    connected = {item.strip().lower() for item in daq.getString("/zi/devices/connected").split(",")}
    if device in connected:
        print(f"Device {device} is already attached to this Data Server.")
        return

    devices = json.loads(daq.getString("/zi/devices"))
    info = next((value for key, value in devices.items() if key.lower() == device), None)
    if info is None:
        raise ValueError(f"{device} is not visible to this Data Server. Check the serial and host.")
    # Follow Zurich's interface selection: use INTERFACE, then advertised choices.
    undefined = {"", "none", "unknown"}
    interface = info.get("INTERFACE", "").strip()
    if interface.lower() in undefined:
        available = [item.strip() for item in info.get("INTERFACES", "").split(",")
                     if item.strip().lower() not in undefined]
        if not available:
            raise ValueError(f"The server reports no available interface for {device}.")
        interface = next((item for item in available if item.lower() == "1gbe"), available[0])
    print(f"Attaching {device} using server-reported interface {interface}...")
    daq.connectDevice(device, interface)


def run_connection(device, host="", port=SERVER_PORT, *, server_factory=None):
    """Read identity and clock information; a supplied factory enables offline tests.

    The caller owns hardware authorization. No settings, subscriptions, discovery
    sweeps, or global device disconnections are performed here.
    """
    device, host, port = validate_config(device, host, port)
    if server_factory is None:
        import zhinst.core

        server_factory = zhinst.core.ziDAQServer

    print(f"Connecting to {device} via {host}:{port} (API {API_LEVEL})...")
    # Allow different LabOne releases; individual API/read failures still surface.
    daq = server_factory(host, port, API_LEVEL, allow_version_mismatch=True)
    try:
        ensure_device_connected(daq, device)
        device_type = daq.getString(f"/{device}/features/devtype").strip()
        if device_type.upper() != "MFLI":
            raise ValueError(f"Expected an MFLI at {device}, received {device_type!r}.")
        result = {
            "device": device,
            "host": host,
            "port": port,
            "api_version": daq.version(),
            "server_version": daq.getString("/zi/about/version"),
            "server_revision": daq.getInt("/zi/about/revision"),
            "device_type": device_type,
            "serial": daq.getString(f"/{device}/features/serial"),
            "options": daq.getString(f"/{device}/features/options"),
            "clockbase_hz": daq.getDouble(f"/{device}/clockbase"),
        }
        if not result["serial"].strip():
            raise ValueError("The instrument returned an empty serial number.")
        if not math.isfinite(result["clockbase_hz"]) or result["clockbase_hz"] <= 0:
            raise ValueError("The instrument returned an invalid clock frequency.")
    finally:
        pending_error = sys.exception()
        try:
            # Close only our client. disconnectDevice() would affect the shared server.
            daq.disconnect()
        except Exception as cleanup_error:
            if pending_error is None:
                raise
            print(f"Cleanup also failed: {cleanup_error}", file=sys.stderr)
    return result


def main(argv=None, *, server_factory=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default=DEVICE_ID, help="MFLI serial, e.g. dev12345")
    parser.add_argument("--host", default=SERVER_HOST, help="Data Server hostname or IP")
    parser.add_argument("--port", default=SERVER_PORT, type=int, help="Data Server port (8004)")
    args = parser.parse_args(argv)
    try:
        result = run_connection(args.device, args.host, args.port, server_factory=server_factory)
    except ModuleNotFoundError as exc:
        print(f"FAILED: Missing Python dependency: {exc.name}.", file=sys.stderr)
        print("Install this folder's requirements.txt with the intended environment's Python.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Connection check interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        print("Check the serial, USB RNDIS driver, server address/port, and the API error above.", file=sys.stderr)
        return 1

    print(f"Device: {result['device_type']} | serial: {result['serial']}")
    print(f"Options: {result['options'] or '(none)'}")
    print(f"Python API: {result['api_version']} | Data Server: {result['server_version']} "
          f"(revision {result['server_revision']})")
    print(f"Clock frequency: {result['clockbase_hz']:g} Hz ({result['clockbase_hz'] / 1e6:g} MHz)")
    print("SUCCESS: MFLI identity and clock read; client connection closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
