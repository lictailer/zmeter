"""zcore: ZMeter core code with no Qt and no hardware dependency (v2 transition).

Import rules, enforced by ``tests/test_layering.py``:

* zcore never imports ``PyQt6``, ``core``, ``devices`` or ``zui``.
* Optional vendor libraries are never imported at module top level.

Nothing here is on the active runtime path until a phase switches its default.
See ``documents/decisions/003-v2-architecture.md``.
"""
