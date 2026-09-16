"""Pure address validation and explicit Data Server attachment helpers."""
import ipaddress
import json
import re

SERVER_PORT = 8004


def parse_address(address: str) -> tuple[str, str, int]:
    """Accept plain DEV12345 or DEV12345, IP without enclosing brackets."""
    if not isinstance(address, str):
        raise ValueError("MFLI address must be text: DEV12345, 192.168.1.2")
    text = address.strip()
    parts = [part.strip() for part in text.split(",")]
    if len(parts) not in (1, 2) or any(not part for part in parts):
        raise ValueError("Use DEV12345 or DEV12345, IP in the address cell.")
    device, host, port = validate_config(parts[0], "", SERVER_PORT)
    if len(parts) == 2:
        try:
            host = str(ipaddress.ip_address(parts[1]))
        except ValueError as exc:
            raise ValueError(f"Invalid MFLI IP address: {parts[1]!r}") from exc
    return device, host, port


def validate_config(device: str, host: str, port: int) -> tuple[str, str, int]:
    device = device.strip().lower()
    if not re.fullmatch(r"dev[0-9]+", device):
        raise ValueError("Set an explicit MFLI serial, for example DEV30037.")
    host = host.strip() or f"mf-{device}"
    if any(char.isspace() for char in host) or "://" in host or "/" in host:
        raise ValueError("Use a server hostname or IP address, without a URL or path.")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Server port must be an integer between 1 and 65535.")
    return device, host, port


def ensure_device_connected(daq, device: str) -> None:
    connected = {item.strip().lower() for item in daq.getString("/zi/devices/connected").split(",")}
    if device in connected:
        return
    devices = json.loads(daq.getString("/zi/devices"))
    info = next((value for key, value in devices.items() if key.lower() == device), None)
    if info is None:
        raise ValueError(f"{device} is not visible to this Data Server. Check serial and host.")
    undefined = {"", "none", "unknown"}
    interface = info.get("INTERFACE", "").strip()
    if interface.lower() in undefined:
        available = [item.strip() for item in info.get("INTERFACES", "").split(",")
                     if item.strip().lower() not in undefined]
        if not available:
            raise ValueError(f"No available server interface for {device}.")
        interface = next((item for item in available if item.lower() == "1gbe"), available[0])
    daq.connectDevice(device, interface)
