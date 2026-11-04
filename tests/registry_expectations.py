"""The one place where tests list every registered driver ID.

``DRIVER_IDS`` is the explicit, reviewed content of
``build_default_registry().driver_ids`` in registration order. Adding a driver
changes one line here (append its ID to a group, or add a group). Tests that
need the full list or a group import it from this module; no test repeats the
IDs. The registry contents are still asserted explicitly, so an unreviewed
registration or a missing one fails.
"""

# ``mock_device`` first, then the phase 1 and phase 2 registrations, in the
# order of ``core/device_management/registrations.py``.
PHASE1_DRIVER_IDS = (
    "mock_device",
    "ni6423",
    "nidaq",
    "pem100",
    "sp150",
    "hp34401a",
    "keithley24xx",
    "sr860",
    "sr830",
    "demo_device",
    "bbd30x",
    "k10cr1",
)

PHASE2_DRIVER_IDS = (
    "four9",
    "montana2",
    "opticool",
    "attodry",
    "tlpm",
    "mc2000b",
    "spectraphysicsx3_laser",
    "auto_focus",
    "auto_position",
    "arduino_steppers",
    "nema11_stepper",
    "andor",
)

# Registered after the phase 2 group by ``build_default_registry``.
LATE_DRIVER_IDS = ("mfli",)

DRIVER_IDS = PHASE1_DRIVER_IDS + PHASE2_DRIVER_IDS + LATE_DRIVER_IDS
