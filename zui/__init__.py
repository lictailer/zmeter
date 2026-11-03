"""zui: Qt user interface of the v2 architecture (v2 transition).

``zui`` may import ``zcore`` and ``PyQt6``. ``zcore`` must never import ``zui``
(enforced by ``tests/test_layering.py``). Nothing here is on the active runtime
path until a phase switches its default. See
``documents/decisions/003-v2-architecture.md``.
"""
