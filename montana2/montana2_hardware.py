import ipaddress
import time
from .montana_libs.cryocore import CryoCore
from .montana_libs import instrument

Ports = instrument.Rest_Ports

class Montana2Hardware():
    def __init__(self, *args, **kwargs):
        self.connect = False
        pass

    def _unwrap_ok(self, result):
        """If result is a (ok, value) pair, return value when ok is True, else return False.
        If result isn't a pair, return it unchanged.
        """
        try:
            # handle lists/tuples with at least two items
            if isinstance(result, (list, tuple)) and len(result) >= 2:
                ok, val = result[0], result[1]
                return val if bool(ok) else False
        except Exception:
            pass
        return result
        

    def connect_hardware(self, address=None):
        if address is None:
            print("No address provided")
            return False
        else:
            try:
                ipaddress.ip_address(address)
            except ValueError:
                print(f"Invalid IP address: {address}")
                return False

        self.cryo = CryoCore(address)
        if self.cryo.is_up():
            print(f"Connected to Montana Instrument {address}")
            self.connect = True
        else:
            print(f"connect to Montana Instrument {address} failed")
            self.connect = False

        return self.connect  


    def cooldown(self):
        if not self.connect:
            print("Not connected to cryocore")
            return False
        self.cryo.cooldown()

    def warmup(self):
        if not self.connect:
            print("Not connected to cryocore")
            return False
        self.cryo.warmup()

    def vent(self):
        if not self.connect:
            print("Not connected to cryocore")
            return False
        self.cryo.vent()

    def pull_vacuum(self):
        if not self.connect:
            print("Not connected to cryocore")
            return False
        self.cryo.pull_vacuum()

    def abort_goal(self):
        if not self.connect:
            print("Not connected to cryocore")
            return False
        self.cryo.abort_goal()

    def get_system_goal(self):
        if not self.connect:
            print("Not connected to cryocore")
            return None
        return self.cryo.get_system_goal()
    
    def get_system_state(self):
        if not self.connect:
            print("Not connected to cryocore")
            return None
        return self.cryo.get_system_state()
    
    def get_sample_chamber_pressure(self):
        if not self.connect:
            print("Not connected to cryocore")
            return None
        return self.cryo.get_sample_chamber_pressure()
    
    def set_platform_bakeout_enabled(self, enabled: bool):
        if not self.connect:
            print("Not connected to cryocore")
            return False
        self.cryo.set_platform_bakeout_enabled(enabled)

    def set_platform_bakeout_temperature(self, temperature: float):
        if not self.connect:
            print("Not connected to cryocore")
            return False
        self.cryo.set_platform_bakeout_temperature(temperature)

    def set_platform_bakeout_time(self, time_minutes: int):
        if not self.connect:
            print("Not connected to cryocore")
            return False
        self.cryo.set_platform_bakeout_time(time_minutes)

    def set_dry_nitrogen_purge_enabled(self, enabled: bool):
        if not self.connect:
            print("Not connected to cryocore")
            return False
        self.cryo.set_dry_nitrogen_purge_enabled(enabled)

    def set_dry_nitrogen_purge_num_times(self, times: int):
        if not self.connect:
            print("Not connected to cryocore")
            return False
        self.cryo.set_dry_nitrogen_purge_num_times(times)

    def set_vent_continuously_enabled(self, enabled: bool):
        if not self.connect:
            print("Not connected to cryocore")
            return False
        return self.cryo.set_vent_continuously_enabled(enabled)

    def set_pull_vacuum_target_pressure(self, target: float):
        if not self.connect:
            print("Not connected to cryocore")
            return False
        return self.cryo.set_pull_vacuum_target_pressure(target)

    def get_stage1_temperature_sample(self):
        if not self.connect:
            print("Not connected to cryocore")
            return None
        return self.cryo.get_stage1_temperature_sample()

    def get_stage1_temperature(self):
        if not self.connect:
            print("Not connected to cryocore")
            return None
        return self._unwrap_ok(self.cryo.get_stage1_temperature())

    def get_stage2_temperature_sample(self):
        if not self.connect:
            print("Not connected to cryocore")
            return None
        return self.cryo.get_stage2_temperature_sample()

    def get_stage2_temperature(self):
        if not self.connect:
            print("Not connected to cryocore")
            return None
        return self._unwrap_ok(self.cryo.get_stage2_temperature())

    def get_platform_target_temperature(self):
        if not self.connect:
            print("Not connected to cryocore")
            return None
        return self.cryo.get_platform_target_temperature()

    def set_platform_target_temperature(self, target: float):
        if not self.connect:
            print("Not connected to cryocore")
            return False
        return self.cryo.set_platform_target_temperature(target)

    def get_platform_temperature(self):
        if not self.connect:
            print("Not connected to cryocore")
            return None
        return self._unwrap_ok(self.cryo.get_platform_temperature())

    def get_platform_temperature_stability(self):
        if not self.connect:
            print("Not connected to cryocore")
            return None
        return self._unwrap_ok(self.cryo.get_platform_temperature_stability())

    def set_platform_stability_target(self, target: float):
        if not self.connect:
            print("Not connected to cryocore")
            return False
        return self.cryo.set_platform_stability_target(target)

    def get_platform_temperature_stable(self):
        if not self.connect:
            print("Not connected to cryocore")
            return None
        return self._unwrap_ok(self.cryo.get_platform_temperature_stable())

    def get_platform_temperature_sample(self):
        if not self.connect:
            print("Not connected to cryocore")
            return None
        return self.cryo.get_platform_temperature_sample()

    def get_platform_heater_sample(self):
        if not self.connect:
            print("Not connected to cryocore")
            return None
        return self.cryo.get_platform_heater_sample()

    def get_user1_temperature_sample(self):
        if not self.connect:
            print("Not connected to cryocore")
            return None
        return self.cryo.get_user1_temperature_sample()

    def get_user1_temperature(self):
        if not self.connect:
            print("Not connected to cryocore")
            return None
        return self._unwrap_ok(self.cryo.get_user1_temperature())

    def get_user1_temperature_stability(self):
        if not self.connect:
            print("Not connected to cryocore")
            return None
        return self._unwrap_ok(self.cryo.get_user1_temperature_stability())

    def disconnect(self):
        if not self.connect:
            print("Not connected to cryocore")
            return False
        self.cryo.close()
        self.connect = False

if __name__ == "__main__":
    print("Montana2 Hardware Test")
    montana = Montana2Hardware()

    print("first try invalid IP")    
    montana.connect_hardware("1.1.1.1")

    print("then try valid IP")
    montana.connect_hardware("136.167.55.165")

    montana.set_platform_target_temperature(3.9)
    
    # print("platform temperature stable", montana.get_platform_temperature_stable())

    # print("platform temperature", montana.get_platform_temperature())

    # time.sleep(2)

    # print("platform temperature", montana.get_platform_temperature())

    # print("sample chamber pressure", montana.get_sample_chamber_pressure())

    # print("stage 1 temperature", montana.get_stage1_temperature())

    # montana.close()
