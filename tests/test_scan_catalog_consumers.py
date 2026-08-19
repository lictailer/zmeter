import copy
import os
import pickle
import unittest
from unittest import mock


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from core.nested_menu import NestedMenu
from core.scan_info import ScanInfo
from core.scanlist import ManualSetItem, ReferenceUse, ScanItem, ScanList


def _scan_info(name="test scan"):
    info = copy.deepcopy(ScanInfo)
    info["name"] = name
    info["comments"] = ""
    info["scan_log"] = []
    info["plots"] = {"line_plots": {}, "image_plots": {}}
    return info


def _one_level_model(*, setter=None, getters=(), before=(), after=()):
    setters = {}
    if setter is not None:
        setters["setter0"] = {"channel": setter}
    return {
        "level0": {
            "setters": setters,
            "getters": list(getters) or ["none"],
            "manual_set_before": [{channel: 1.0} for channel in before],
            "manual_set_after": [{channel: 2.0} for channel in after],
        }
    }


class ScanCatalogConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            if isinstance(widget, ScanList):
                widget.shutdown(timeout_ms=500)
                widget.logic.current_worker = None
                widget.logic.workers = []
        for widget in reversed(self.widgets):
            widget.close()
            widget.deleteLater()
        self.app.processEvents()

    def _track(self, widget):
        self.widgets.append(widget)
        return widget

    def test_nested_menu_replaces_actions_and_marks_invalid_selection(self):
        menu = self._track(NestedMenu({"device_with_underscores": ["x", "y"]}))
        menu.set_chosen_one("device_with_underscores_x")

        emitted = []
        menu.sig_self_changed.connect(lambda _menu: emitted.append(menu.name))
        for _ in range(4):
            menu.set_choices({"device_with_underscores": ["x", "z"]})

        self.assertEqual(menu.name, "device_with_underscores_x")
        self.assertEqual(
            menu.choice_names,
            frozenset(
                {
                    "device_with_underscores_x",
                    "device_with_underscores_z",
                }
            ),
        )
        self.assertEqual(
            len(
                [
                    child
                    for child in menu.children()
                    if isinstance(child, QtWidgets.QMenu)
                ]
            ),
            1,
        )

        z_action = next(
            action
            for action in NestedMenu._iter_leaf_actions(menu.menu)
            if action.data() == "device_with_underscores_z"
        )
        z_action.trigger()
        self.assertEqual(emitted, ["device_with_underscores_z"])

        stale_action = z_action
        menu.set_choices({"other_device": ["out"]})
        self.assertEqual(menu.name, "")
        self.assertEqual(menu.unresolved_name, "device_with_underscores_z")
        self.assertIn("Unresolved", menu.button.text())
        stale_action.trigger()
        self.assertEqual(emitted, ["device_with_underscores_z"])
        self.assertEqual(menu.name, "")
        self.assertEqual(menu.unresolved_name, "device_with_underscores_z")
        menu.set_choices({"other_device": ["out"]})
        self.assertEqual(menu.unresolved_name, "device_with_underscores_z")

    def test_one_refresh_reaches_all_scan_items_and_drag_clone_sources(self):
        old_setters = {"old_device": ["out"]}
        old_getters = {"old_device": ["in"]}
        scan_list = self._track(
            ScanList(
                info=_scan_info(),
                setter_equipment_info=old_setters,
                getter_equipment_info=old_getters,
            )
        )

        initial = scan_list.list_available.get_widgets()
        scan_list.list_queue.layout.addWidget(initial[1])
        scan_list.list_past.layout.addWidget(initial[2])
        initial[3].setParent(None)
        self.widgets.append(initial[3])
        scan_list.logic.current_worker = initial[3]
        scan_list.logic.workers = [initial[1], initial[3]]

        new_setters = {
            "old_device": ["out"],
            "new_device": ["new_out"],
        }
        new_getters = {
            "old_device": ["in"],
            "new_device": ["new_in"],
        }
        definitions_before = {
            id(item): (
                pickle.dumps(item.scan.all_level_setting.all_level_info),
                pickle.dumps(item.scan.all_plot_setting.info),
            )
            for item in scan_list.iter_scan_items()
        }
        definition_emissions = []
        for item in scan_list.iter_scan_items():
            item.scan.all_level_setting.sig_info_changed.connect(
                lambda _info: definition_emissions.append("changed")
            )
        scan_list.manual_set_menu.set_chosen_one("old_device_out")
        scan_list.refresh_catalog(new_setters, new_getters)

        self.assertEqual(scan_list.setter_equipment_info, new_setters)
        self.assertEqual(scan_list.getter_equipment_info, new_getters)
        self.assertEqual(scan_list.manual_set_menu.name, "old_device_out")
        for container in (
            scan_list.list_available,
            scan_list.list_queue,
            scan_list.list_past,
            scan_list.list_manual,
        ):
            self.assertEqual(container.setter_equipment_info, new_setters)
            self.assertEqual(container.getter_equipment_info, new_getters)

        scan_items = list(scan_list.iter_scan_items())
        self.assertEqual(len(scan_items), 4)
        self.assertEqual(len({id(item) for item in scan_items}), 4)
        for item in scan_items:
            self.assertEqual(item.scan.setter_equipment_info, new_setters)
            self.assertEqual(item.scan.getter_equipment_info, new_getters)
            self.assertEqual(
                pickle.dumps(item.scan.all_level_setting.all_level_info),
                definitions_before[id(item)][0],
            )
            self.assertEqual(
                pickle.dumps(item.scan.all_plot_setting.info),
                definitions_before[id(item)][1],
            )
        self.assertEqual(definition_emissions, [])

        scan_list.refresh_catalog(new_setters, new_getters)
        self.assertEqual(
            len(
                [
                    child
                    for child in scan_list.manual_set_menu.children()
                    if isinstance(child, QtWidgets.QMenu)
                ]
            ),
            1,
        )

        clone = scan_list.list_queue.clone_scan_item(initial[0])
        self.widgets.append(clone.scan)
        clone.deleteLater()
        self.assertEqual(clone.scan.setter_equipment_info, new_setters)
        self.assertEqual(clone.scan.getter_equipment_info, new_getters)

    def test_refresh_rolls_back_earlier_consumers_when_second_scan_fails(self):
        old_setters = {"old_device": ["out"]}
        old_getters = {"old_device": ["in"]}
        new_setters = {"new_device": ["out"]}
        new_getters = {"new_device": ["in"]}
        scan_list = self._track(
            ScanList(
                info=_scan_info(),
                setter_equipment_info=old_setters,
                getter_equipment_info=old_getters,
            )
        )
        first, second = list(scan_list.iter_scan_items())[:2]
        original_refresh = second.refresh_catalog
        calls = []

        def fail_new_catalog_once(setters, getters):
            calls.append((copy.deepcopy(setters), copy.deepcopy(getters)))
            if len(calls) == 1:
                raise RuntimeError("injected second-consumer failure")
            return original_refresh(setters, getters)

        with mock.patch.object(
            second,
            "refresh_catalog",
            side_effect=fail_new_catalog_once,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "injected second-consumer failure",
            ):
                scan_list.refresh_catalog(new_setters, new_getters)

        self.assertEqual(scan_list.setter_equipment_info, old_setters)
        self.assertEqual(scan_list.getter_equipment_info, old_getters)
        self.assertEqual(first.scan.setter_equipment_info, old_setters)
        self.assertEqual(first.scan.getter_equipment_info, old_getters)
        self.assertEqual(second.scan.setter_equipment_info, old_setters)
        self.assertEqual(second.scan.getter_equipment_info, old_getters)
        for container in (
            scan_list.list_available,
            scan_list.list_queue,
            scan_list.list_past,
            scan_list.list_manual,
        ):
            self.assertEqual(container.setter_equipment_info, old_setters)
            self.assertEqual(container.getter_equipment_info, old_getters)

    def test_catalog_mutation_waits_for_queue_ui_completion_delivery(self):
        scan_list = self._track(
            ScanList(
                info=_scan_info(),
                setter_equipment_info={"device": ["out"]},
                getter_equipment_info={"device": ["in"]},
            )
        )
        scan_list._queue_run_started = True
        scan_list._queue_completion_delivered = False

        self.assertIn("queue UI completion", scan_list.catalog_mutation_blockers())
        self.assertFalse(scan_list.is_idle_for_catalog_mutation())

        scan_list._queue_completion_delivered = True
        self.assertNotIn("queue UI completion", scan_list.catalog_mutation_blockers())

    def test_reference_report_covers_live_scans_plots_and_all_manual_locations(self):
        device = "device_with_underscores"
        prefix_device = "device"
        channels = {
            "out": f"{device}_out",
            "in": f"{device}_in",
            "before": f"{device}_before",
            "after": f"{device}_after",
            "queue": f"{device}_queue",
            "past": f"{device}_past",
            "active": f"{device}_active",
            "detached": f"{device}_detached",
            "manual": f"{device}_manual",
            "queued_manual": f"{device}_queued_manual",
            "past_manual": f"{device}_past_manual",
        }
        setters = {
            prefix_device: ["other"],
            device: [
                "out",
                "before",
                "after",
                "queue",
                "past",
                "active",
                "detached",
                "manual",
                "queued_manual",
                "past_manual",
            ],
        }
        getters = {device: ["in"]}
        scan_list = self._track(
            ScanList(
                info=_scan_info(),
                setter_equipment_info=setters,
                getter_equipment_info=getters,
            )
        )
        scan_list.info = {
            "name": "New Scan template",
            "levels": _one_level_model(setter=channels["out"]),
            "plots": {"line_plots": {}, "image_plots": {}},
        }

        available, queued, past, active = scan_list.list_available.get_widgets()
        scan_list.list_queue.layout.addWidget(queued)
        scan_list.list_past.layout.addWidget(past)
        active.setParent(None)
        self.widgets.append(active)
        detached = ScanItem(
            name="detached worker",
            info=_scan_info("detached worker"),
            setter_equipment_info=setters,
            getter_equipment_info=getters,
        )
        detached.setParent(None)
        self.widgets.extend((detached.scan, detached))
        scan_list.logic.current_worker = active
        scan_list.logic.workers = [queued, active, detached]

        available.scan.all_level_setting.all_level_info = {
            **_one_level_model(
                setter=channels["out"],
                getters=(channels["in"],),
                before=(channels["before"],),
                after=(channels["after"],),
            ),
            "level1": {
                "setters": {},
                "getters": [f"level0_average_{channels['in']}"],
                "manual_set_before": [],
                "manual_set_after": [],
            },
        }
        # Deliberately leave Scan.info stale to prove live editor state wins.
        available.scan.info["levels"] = _one_level_model(setter="stale_device_out")
        available.scan.all_plot_setting.info = {
            "line_plots": {
                "0": {
                    "x": f"L0S0_{channels['out']}",
                    "y": f"L0G0_{channels['in']}",
                }
            },
            "image_plots": {
                "0": {
                    "x": "level0",
                    "y": "level1",
                    "z": f"L1G0_level0_average_{channels['in']}",
                }
            },
        }
        queued.scan.all_level_setting.all_level_info = _one_level_model(
            setter=channels["queue"]
        )
        past.scan.all_level_setting.all_level_info = _one_level_model(
            setter=channels["past"]
        )
        active.scan.all_level_setting.all_level_info = _one_level_model(
            setter=channels["active"]
        )
        detached.scan.all_level_setting.all_level_info = _one_level_model(
            setter=channels["detached"]
        )

        manual = ManualSetItem(channels["manual"], 1.0)
        queued_manual = ManualSetItem(channels["queued_manual"], 2.0)
        past_manual = ManualSetItem(channels["past_manual"], 3.0)
        scan_list.list_manual.add_item(manual)
        scan_list.list_queue.add_item(queued_manual)
        scan_list.list_past.add_item(past_manual)

        uses = scan_list.reference_uses()
        self.assertTrue(all(isinstance(use, ReferenceUse) for use in uses))
        self.assertEqual(
            {
                "available-template",
                "available",
                "queue",
                "past",
                "active",
                "queue_worker",
                "manual",
            },
            {use.collection for use in uses},
        )
        self.assertEqual(
            {"setter", "getter", "average_getter", "manual_set_before",
             "manual_set_after", "plot_setter", "plot_getter",
             "plot_average_getter", "manual_set_item"},
            {use.kind for use in uses},
        )
        self.assertNotIn("stale_device_out", {use.channel for use in uses})
        self.assertTrue(
            all(
                use.device_id == device
                for use in uses
                if use.channel.startswith(f"{device}_")
            )
        )
        self.assertEqual(
            (),
            scan_list.find_device_references(prefix_device),
        )

        detached_uses = [
            use for use in uses if use.channel == channels["detached"]
        ]
        self.assertEqual([use.collection for use in detached_uses], ["queue_worker"])

        removed = scan_list.find_channel_references(
            removed_setters={channels["out"]},
            removed_getters={channels["in"]},
        )
        self.assertEqual(
            {"setter", "getter", "average_getter", "plot_setter",
             "plot_getter", "plot_average_getter"},
            {use.kind for use in removed},
        )
        getter_only = scan_list.find_channel_references(
            removed_setters={channels["in"]},
        )
        self.assertEqual(getter_only, ())
        self.assertTrue(all(str(use) for use in removed))

        manual_items = list(scan_list.iter_manual_set_items())
        self.assertEqual(len(manual_items), 3)
        self.assertEqual(len({id(item) for item in manual_items}), 3)


if __name__ == "__main__":
    unittest.main()
