"""Compatibility launcher for the promoted device; retains local bench defaults."""
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from devices.mfli.MFLI_main import main
from devices.MFLI_temp.connection_demo import DEVICE_ID, SERVER_HOST


if __name__ == "__main__":
    address = f"{DEVICE_ID}, {SERVER_HOST}" if SERVER_HOST.strip() else DEVICE_ID
    raise SystemExit(main(address))
