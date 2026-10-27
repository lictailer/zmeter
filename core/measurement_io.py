"""Hardware-independent channel references and checked coordinator routing."""
from dataclasses import dataclass
import math
import uuid


def finite(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def count(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer between {low} and {high}")
    return value


@dataclass(frozen=True)
class Channel:
    device: str = ""
    channel: str = ""

    def validate(self):
        if not self.device.strip() or not self.channel.strip():
            raise ValueError("Select both a device and a channel")


class RouterIO:
    def __init__(self, router, source_device="auto_focus"):
        self.router, self.source_device, self.catalog = router, source_device, {}

    def request(self, action, ref=None, value=None):
        if self.router is None:
            raise RuntimeError("This coordinator needs ZMeter's command router")
        response = self.router.route_command({
            "request_id": str(uuid.uuid4()), "source_device": self.source_device,
            "action": action, "target_device": ref.device if ref else None,
            "channel": ref.channel if ref else None, "value": value,
        })
        if not response.get("ok"):
            raise RuntimeError(f"{response.get('error_code')}: {response.get('error_message')}")
        return response

    def refresh(self):
        self.catalog = self.request("list_catalog")["catalog"]
        return self.catalog

    def validate(self, ref, access, value=None):
        ref.validate()
        if ref.device == self.source_device:
            raise ValueError("A coordinator cannot use its own scan channels as a hardware source")
        if ref.channel not in self.catalog.get(ref.device, {}).get(access, ()):
            raise ValueError(f"Unavailable {access} channel: {ref.device}/{ref.channel}")
        if access == "writable" and value is not None:
            value = finite(value, "Channel target")
            window = getattr(self.router, "main_window", None)
            limits = getattr(window, "active_scan_range_limits", {}).get((ref.device, ref.channel))
            # Core scan writes can skip out-of-range points. Coordinators must
            # refuse before recording a measurement at an unexecuted target.
            if limits is not None and not limits[0] <= value <= limits[1]:
                raise ValueError(f"{ref.device}/{ref.channel}={value:g} outside global limits {limits}")

    def read(self, ref):
        self.validate(ref, "readable")
        return finite(self.request("read", ref)["value"], f"{ref.device}/{ref.channel}")

    def write(self, ref, value):
        self.validate(ref, "writable", value)
        self.request("write", ref, float(value))
