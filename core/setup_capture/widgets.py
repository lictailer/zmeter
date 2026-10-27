"""Qt widgets for setup capture: the settings dialog, the scan window's
Questionnaire tab and the queue questionnaire pop-up."""

from __future__ import annotations

import copy
from typing import Mapping

from PyQt6 import QtCore, QtGui, QtWidgets

from . import profile
from . import questionnaire as qn

TAB_TITLE = "Questionnaire"
UNKNOWN_TEXT = "unknown"


def default_questionnaire_data() -> dict:
    return {"enabled": False, "record": None}


def questionnaire_data_from_info(info: dict) -> dict:
    """The scan's stored questionnaire, or a fresh default one.

    A fresh default is not attached to ``info``; see :func:`sync_questionnaire_to_info`.
    """

    data = info.get("questionnaire")
    if not isinstance(data, dict):
        data = default_questionnaire_data()
    data.setdefault("enabled", False)
    data.setdefault("record", None)
    return data


def sync_questionnaire_to_info(info: dict, data: dict) -> None:
    """Store the questionnaire only once it is used, so scans that never
    use it save exactly the same keys as before."""

    if data.get("enabled") or data.get("record"):
        info["questionnaire"] = data
    else:
        info.pop("questionnaire", None)


def answered_count(items) -> int:
    return sum(
        1
        for item in items or ()
        if item.get("status") in (qn.STATUS_ANSWERED, qn.STATUS_UNKNOWN, qn.STATUS_PREFILLED)
    )


def record_status_text(record: Mapping | None) -> str:
    if not record:
        return "No questions yet."
    items = record.get("items") or []
    when = record.get("generated_at") or ""
    if record.get("source") == "agent":
        head = f"{len(items)} fields from {record.get('model')} at {when}"
    elif record.get("source") == "suggestions":
        head = f"{len(items)} suggested fields at {when} (model unavailable)"
    else:
        head = f"{len(items)} fields"
    text = f"{head}. {answered_count(items)} filled."
    inferences = record.get("inferences") or []
    if inferences:
        to_check = sum(1 for inf in inferences if qn.needs_check(inf))
        text += f" {len(inferences)} conclusions"
        text += f", {to_check} to check." if to_check else "."
    if record.get("error"):
        text += f"\nModel note: {record['error']}"
    return text


# ------------------------------------------------------------ form look --

LABEL_WIDTH = 210
MAX_CHIPS = 5
MAX_CHIP_CHARS = 48
CHECK_COLOR = "#d98c00"  # readable on light and dark backgrounds

FORM_STYLE = """
QFrame#fieldRow { border-radius: 3px; }
QFrame#fieldRow[odd="true"] { background: palette(alternate-base); }
QLabel#fieldLabel { font-weight: 600; }
QLabel#sectionTitle { font-size: 11pt; font-weight: 700; padding-top: 8px; }
QLabel#sectionHint { font-style: italic; }
QLabel#checkTag { color: %s; font-weight: 700; }
QToolButton#chip { padding: 1px 8px; }
""" % CHECK_COLOR


def _clear_layout(layout: QtWidgets.QLayout) -> None:
    while layout.count():
        child = layout.takeAt(0)
        widget = child.widget()
        if widget is not None:
            widget.deleteLater()


def _section_header(title: str, hint: str = "") -> QtWidgets.QWidget:
    box = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(box)
    layout.setContentsMargins(2, 0, 2, 2)
    layout.setSpacing(0)
    label = QtWidgets.QLabel(title)
    label.setObjectName("sectionTitle")
    layout.addWidget(label)
    if hint:
        note = QtWidgets.QLabel(hint)
        note.setObjectName("sectionHint")
        note.setWordWrap(True)
        layout.addWidget(note)
    line = QtWidgets.QFrame()
    line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
    line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
    layout.addWidget(line)
    return box


def _field_row(index: int, text: str, tooltip: str) -> tuple[QtWidgets.QFrame, QtWidgets.QHBoxLayout]:
    """One document line: bold label on the left, editors added by the caller."""

    row = QtWidgets.QFrame()
    row.setObjectName("fieldRow")
    row.setProperty("odd", index % 2 == 1)
    layout = QtWidgets.QHBoxLayout(row)
    layout.setContentsMargins(6, 3, 6, 3)
    layout.setSpacing(6)
    label = QtWidgets.QLabel(text)
    label.setObjectName("fieldLabel")
    label.setWordWrap(True)
    label.setFixedWidth(LABEL_WIDTH)
    label.setToolTip(tooltip)
    layout.addWidget(label, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
    return row, layout


def _small_button(text: str, *, checkable: bool = False) -> QtWidgets.QToolButton:
    button = QtWidgets.QToolButton()
    button.setObjectName("chip")
    button.setText(text)
    button.setCheckable(checkable)
    button.setAutoRaise(False)
    return button


class QuestionListWidget(QtWidgets.QWidget):
    """Questionnaire items shown as a filled-in document: one line per field,
    grouped into "This scan" and "Setup".  Edits the items in place."""

    sig_edited = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict] = []
        self._rows: list[QtWidgets.QFrame] = []
        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(1)

    @property
    def items(self) -> list[dict]:
        return self._items

    def set_items(self, items: list[dict] | None) -> None:
        self._items = items if items is not None else []
        self._rows = []
        _clear_layout(self._layout)
        sections = (
            ("scan", "This scan", ""),
            ("setup", "Setup", "Usually unchanged; prefilled from earlier answers. Fix only what changed."),
        )
        for section, title, hint in sections:
            items_here = [item for item in self._items if item.get("section", "scan") == section]
            if not items_here:
                continue
            self._layout.addWidget(_section_header(title, hint))
            for index, item in enumerate(items_here):
                row = self._make_row(index, item)
                self._rows.append(row)
                self._layout.addWidget(row)

    def _make_row(self, index: int, item: dict) -> QtWidgets.QFrame:
        text = str(item.get("text", ""))
        if item.get("unit"):
            text += f" ({item['unit']})"
        tips = [item.get("reason") or "", f"source: {item.get('origin', '')}"]
        row, layout = _field_row(index, text, "\n".join(tip for tip in tips if tip))

        options = list(item.get("options") or [])
        if item.get("kind") == "yes_no" and not options:
            options = ["yes", "no"]
        chips_fit = len(options) <= MAX_CHIPS and sum(len(o) for o in options) <= MAX_CHIP_CHARS
        if options and not chips_fit:
            editor = QtWidgets.QComboBox()
            editor.setEditable(True)
            editor.addItems([""] + options)
            editor.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
            line = editor.lineEdit()
        else:
            editor = QtWidgets.QLineEdit()
            line = editor
        line.setPlaceholderText("type or pick" if options else "type")
        layout.addWidget(editor, 1)
        chips = []
        if options and chips_fit:
            for option in options:
                chip = _small_button(option)
                chips.append(chip)
                layout.addWidget(chip)
        unknown = _small_button("Unknown", checkable=True)
        unknown.setToolTip("Mark as unknown")
        layout.addWidget(unknown)

        def set_enabled(enabled):
            editor.setEnabled(enabled)
            for chip in chips:
                chip.setEnabled(enabled)

        status = item.get("status")
        if status == qn.STATUS_UNKNOWN or (
            status == qn.STATUS_PREFILLED and str(item.get("answer")).lower() == UNKNOWN_TEXT
        ):
            unknown.setChecked(True)
            set_enabled(False)
        elif item.get("answer") not in (None, ""):
            line.setText(str(item["answer"]))
        if status == qn.STATUS_PREFILLED:
            line.setToolTip("Prefilled from an earlier answer. Edit it if it changed.")

        def on_text(value, item=item):
            if unknown.isChecked():
                return
            value = value.strip()
            item["answer"] = value or None
            item["status"] = qn.STATUS_ANSWERED if value else qn.STATUS_NOT_ANSWERED
            self.sig_edited.emit()

        def on_unknown(checked, item=item):
            set_enabled(not checked)
            if checked:
                item["answer"] = UNKNOWN_TEXT
                item["status"] = qn.STATUS_UNKNOWN
            else:
                value = line.text().strip()
                item["answer"] = value or None
                item["status"] = qn.STATUS_ANSWERED if value else qn.STATUS_NOT_ANSWERED
            self.sig_edited.emit()

        line.textEdited.connect(on_text)
        if isinstance(editor, QtWidgets.QComboBox):
            editor.activated.connect(lambda _i: on_text(line.text()))
        for chip in chips:
            chip.clicked.connect(lambda _c=False, text=chip.text(): (line.setText(text), on_text(text)))
        unknown.toggled.connect(on_unknown)
        return row


class ConclusionListWidget(QtWidgets.QWidget):
    """The model's conclusions (``record["inferences"]``) as document lines.

    Medium-confidence ones come first, tagged "check", with a Correct
    button.  Editing a value marks it ``user_corrected``; Wrong marks it
    ``rejected``; Correct marks it ``user_confirmed``.  The model's original
    value is kept in ``model_value``.
    """

    sig_edited = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._inferences: list[dict] = []
        self._rows: list[tuple[dict, QtWidgets.QLineEdit, QtWidgets.QToolButton]] = []
        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(1)
        self.hide()

    def set_inferences(self, inferences: list[dict] | None) -> None:
        self._inferences = inferences if inferences is not None else []
        self._rows = []
        _clear_layout(self._layout)
        if self._inferences:
            self._layout.addWidget(
                _section_header(
                    "Concluded from the scan",
                    "Saved without asking. Check the ones tagged “check”; "
                    "edit a value or press Wrong if needed.",
                )
            )
        to_check = [inf for inf in self._inferences if inf.get("confidence") == "medium"]
        sure = [inf for inf in self._inferences if inf.get("confidence") != "medium"]
        for index, inference in enumerate(to_check + sure):
            self._add_row(index, inference)
        self.setVisible(bool(self._inferences))

    def _add_row(self, index: int, inference: dict) -> None:
        scope = inference.get("scope")
        tip = [
            f"Basis: {inference.get('basis') or '-'}",
            f"Confidence: {inference.get('confidence')}",
            f"Model said: {inference.get('model_value')}",
        ]
        if scope not in (None, "scan"):
            tip.append(f"Scope: {scope}")
        row, layout = _field_row(
            index, qn.inference_label(str(inference.get("field", ""))), "\n".join(tip)
        )
        line = QtWidgets.QLineEdit(str(inference.get("value", "")))
        line.setToolTip("\n".join(tip))
        layout.addWidget(line, 1)

        medium = inference.get("confidence") == "medium"
        tag = QtWidgets.QLabel("check")
        tag.setObjectName("checkTag")
        correct = _small_button("Correct", checkable=True)
        correct.setChecked(inference.get("status") == qn.INFERENCE_CONFIRMED)
        if medium:
            layout.addWidget(tag)
            layout.addWidget(correct)
        wrong = _small_button("Wrong", checkable=True)
        rejected = inference.get("status") == qn.INFERENCE_REJECTED
        wrong.setChecked(rejected)
        line.setEnabled(not rejected)
        layout.addWidget(wrong)

        def update_tag():
            tag.setVisible(qn.needs_check(inference))

        def on_text(value, inference=inference):
            qn.set_inference_value(inference, value, confirmed=correct.isChecked())
            update_tag()
            self.sig_edited.emit()

        def on_correct(checked, inference=inference):
            if checked and wrong.isChecked():
                wrong.setChecked(False)
            qn.set_inference_value(inference, line.text(), confirmed=checked)
            update_tag()
            self.sig_edited.emit()

        def on_wrong(checked, inference=inference):
            line.setEnabled(not checked)
            if checked:
                if correct.isChecked():
                    correct.blockSignals(True)
                    correct.setChecked(False)
                    correct.blockSignals(False)
                inference["status"] = qn.INFERENCE_REJECTED
            else:
                qn.set_inference_value(inference, line.text(), confirmed=correct.isChecked())
            update_tag()
            self.sig_edited.emit()

        line.textEdited.connect(on_text)
        correct.toggled.connect(on_correct)
        wrong.toggled.connect(on_wrong)
        update_tag()
        self._layout.addWidget(row)
        self._rows.append((inference, line, wrong))


class QuestionnaireDocument(QtWidgets.QScrollArea):
    """Conclusions and questions in one scrolling form."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        body = QtWidgets.QWidget()
        body.setStyleSheet(FORM_STYLE)
        layout = QtWidgets.QVBoxLayout(body)
        layout.setContentsMargins(4, 0, 4, 4)
        layout.setSpacing(6)
        self.conclusion_list = ConclusionListWidget()
        self.question_list = QuestionListWidget()
        layout.addWidget(self.conclusion_list)
        layout.addWidget(self.question_list)
        layout.addStretch(1)
        self.setWidget(body)


class QuestionnaireTab(QtWidgets.QWidget):
    """The scan window's Questionnaire tab.

    The tab edits ``scan.info["questionnaire"]`` in place, so the scan's own
    save, autosave and clone paths carry the answers without extra code.
    """

    sig_enabled_changed = QtCore.pyqtSignal(bool)
    sig_ask_now = QtCore.pyqtSignal()
    sig_save_answers = QtCore.pyqtSignal()
    sig_edited = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: dict = default_questionnaire_data()
        layout = QtWidgets.QVBoxLayout(self)

        self.enabled_checkBox = QtWidgets.QCheckBox(
            "Ask setup questions when this scan starts (sends the scan settings and "
            "instrument snapshot to the AI model)"
        )
        layout.addWidget(self.enabled_checkBox)

        buttons = QtWidgets.QHBoxLayout()
        self.ask_now_button = QtWidgets.QPushButton("Ask now")
        self.ask_now_button.setToolTip(
            "Generate questions now from the scan settings and the last snapshot."
        )
        self.save_answers_button = QtWidgets.QPushButton("Save answers")
        self.save_answers_button.setToolTip(
            "Write the answers next to the saved scan file (NNNN_name.setup.json). "
            "The scan file itself is never rewritten."
        )
        buttons.addWidget(self.ask_now_button)
        buttons.addWidget(self.save_answers_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.status_label = QtWidgets.QLabel("No questions yet.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.save_state_label = QtWidgets.QLabel("")
        self.save_state_label.setWordWrap(True)
        layout.addWidget(self.save_state_label)

        self.document = QuestionnaireDocument()
        self.conclusion_list = self.document.conclusion_list
        self.question_list = self.document.question_list
        layout.addWidget(self.document, 1)

        self.enabled_checkBox.toggled.connect(self._on_enabled)
        self.ask_now_button.clicked.connect(self.sig_ask_now)
        self.save_answers_button.clicked.connect(self.sig_save_answers)
        self.question_list.sig_edited.connect(self._on_edited)
        self.conclusion_list.sig_edited.connect(self._on_edited)

    # ---------------------------------------------------------------- data --
    def bind(self, data: dict) -> None:
        self._data = data
        self.enabled_checkBox.blockSignals(True)
        self.enabled_checkBox.setChecked(bool(data.get("enabled")))
        self.enabled_checkBox.blockSignals(False)
        self._show_record()
        self.set_save_state("")

    @property
    def data(self) -> dict:
        return self._data

    @property
    def enabled(self) -> bool:
        return bool(self._data.get("enabled"))

    def set_record(self, record: dict | None, *, queue: dict | None = None) -> None:
        self._data["record"] = record
        if queue is not None:
            self._data["queue"] = queue
        else:
            self._data.pop("queue", None)
        self._show_record()

    def set_busy(self, text: str) -> None:
        self.status_label.setText(text)

    def set_save_state(self, text: str) -> None:
        self.save_state_label.setText(text)

    def items(self) -> list[dict]:
        record = self._data.get("record") or {}
        return record.get("items") or []

    def inferences(self) -> list[dict]:
        record = self._data.get("record") or {}
        return record.get("inferences") or []

    def _show_record(self) -> None:
        record = self._data.get("record")
        text = record_status_text(record)
        self.status_label.setText(self._queue_note() + text)
        self.conclusion_list.set_inferences(record.setdefault("inferences", []) if record else [])
        self.question_list.set_items(record.get("items") if record else [])

    def _queue_note(self) -> str:
        queue = self._data.get("queue")
        if not isinstance(queue, Mapping):
            return ""
        note = (
            f"Copied from the queue questionnaire submitted at "
            f"{queue.get('submitted_at', '?')}"
        )
        if queue.get("added_after_submit"):
            note += " (this scan was added to the queue after Submit)"
        return note + ". Edits here change only this scan.\n"

    def _on_enabled(self, checked: bool) -> None:
        self._data["enabled"] = bool(checked)
        self.sig_enabled_changed.emit(bool(checked))

    def _on_edited(self) -> None:
        record = self._data.get("record")
        if record:
            self.status_label.setText(self._queue_note() + record_status_text(record))
        self.sig_edited.emit()


class QueueQuestionnaireDialog(QtWidgets.QDialog):
    """Non-modal pop-up for the one questionnaire that covers a queue."""

    sig_submitted = QtCore.pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Queue questionnaire")
        self.setModal(False)
        self.resize(820, 680)
        self.record: dict | None = None
        layout = QtWidgets.QVBoxLayout(self)
        self.status_label = QtWidgets.QLabel(
            "Taking an instrument snapshot and asking the model. The queue keeps running."
        )
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.document = QuestionnaireDocument()
        self.conclusion_list = self.document.conclusion_list
        self.question_list = self.document.question_list
        layout.addWidget(self.document, 1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        self.submit_button = QtWidgets.QPushButton("Submit to all scans in the queue")
        self.submit_button.setEnabled(False)
        row.addWidget(self.submit_button)
        layout.addLayout(row)
        self.submit_button.clicked.connect(self._submit)

    def set_record(self, record: dict) -> None:
        self.record = record
        self.status_label.setText(
            record_status_text(record)
            + "\nFill in what you can, then Submit. Every scan gets its own copy."
        )
        self.conclusion_list.set_inferences(record.setdefault("inferences", []))
        self.question_list.set_items(record.get("items") or [])
        self.submit_button.setEnabled(True)

    def _submit(self) -> None:
        if self.record is None:
            return
        self.submit_button.setEnabled(False)
        self.status_label.setText(
            "Submitted. Answers were copied to every scan in the queue; edit them "
            "per scan in each scan's Questionnaire tab."
        )
        self.sig_submitted.emit(copy.deepcopy(self.record))


class SetupCaptureDialog(QtWidgets.QDialog):
    """Per-PC settings: AI provider, API key, model, experiment description,
    lab folder.  Each provider keeps its own key and model."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Setup capture")
        self.resize(560, 520)
        layout = QtWidgets.QVBoxLayout(self)

        key_box = QtWidgets.QGroupBox("AI provider and API key")
        key_layout = QtWidgets.QGridLayout(key_box)
        self.provider_comboBox = QtWidgets.QComboBox()
        for provider, info in profile.PROVIDERS.items():
            self.provider_comboBox.addItem(info["label"], provider)
        self.provider_comboBox.setToolTip(
            "Which AI service writes the questionnaire. Each keeps its own key and model."
        )
        self._models = {
            provider: controller.settings.model_for(provider) for provider in profile.PROVIDERS
        }
        self.key_lineEdit = QtWidgets.QLineEdit()
        self.key_lineEdit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.key_save_button = QtWidgets.QPushButton("Save key")
        self.key_test_button = QtWidgets.QPushButton("Test")
        self.key_status_label = QtWidgets.QLabel(
            "Stored in Windows Credential Manager. Never written to scan files."
            if controller.keys.keyring_available
            else "keyring is not installed: the key is kept only until ZMeter closes."
        )
        self.key_status_label.setWordWrap(True)
        key_layout.addWidget(self.provider_comboBox, 0, 0)
        key_layout.addWidget(self.key_lineEdit, 0, 1)
        key_layout.addWidget(self.key_save_button, 0, 2)
        key_layout.addWidget(self.key_test_button, 0, 3)
        key_layout.setColumnStretch(1, 1)
        key_layout.addWidget(QtWidgets.QLabel("Model"), 1, 0)
        self.model_lineEdit = QtWidgets.QLineEdit()
        key_layout.addWidget(self.model_lineEdit, 1, 1)
        self.effort_label = QtWidgets.QLabel("Effort")
        self.effort_comboBox = QtWidgets.QComboBox()
        self.effort_comboBox.addItems(list(profile.EFFORT_LEVELS))
        self.effort_comboBox.setCurrentText(controller.settings.effort)
        self.effort_comboBox.setToolTip(
            "Claude thinking effort. Low is cheapest and usually enough; "
            "higher may ask sharper questions at a few times the cost."
        )
        key_layout.addWidget(self.effort_label, 1, 2)
        key_layout.addWidget(self.effort_comboBox, 1, 3)
        self.thinking_checkBox = QtWidgets.QCheckBox("Thinking")
        self.thinking_checkBox.setChecked(controller.settings.thinking)
        self.thinking_checkBox.setToolTip(
            "Let DeepSeek reason before answering. Off is several times faster "
            "and usually good enough for this job."
        )
        key_layout.addWidget(self.thinking_checkBox, 1, 2, 1, 2)
        self.base_url_label = QtWidgets.QLabel("Base URL")
        self.base_url_lineEdit = QtWidgets.QLineEdit()
        self.base_url_lineEdit.setPlaceholderText("https://.../v1")
        self.base_url_lineEdit.setToolTip("The provider's OpenAI-compatible API address.")
        key_layout.addWidget(self.base_url_label, 2, 0)
        key_layout.addWidget(self.base_url_lineEdit, 2, 1, 1, 3)
        self._base_urls = {
            provider: controller.settings.base_url_for(provider) for provider in profile.PROVIDERS
        }
        key_layout.addWidget(self.key_status_label, 3, 0, 1, 4)
        layout.addWidget(key_box)
        self._current_provider = None
        self.provider_comboBox.currentIndexChanged.connect(self._on_provider_changed)
        index = self.provider_comboBox.findData(controller.provider)
        self.provider_comboBox.setCurrentIndex(max(0, index))
        self._on_provider_changed()

        desc_box = QtWidgets.QGroupBox("Experiment description (sent with every questionnaire)")
        form = QtWidgets.QFormLayout(desc_box)
        self.description_edits = {}
        description = controller.description
        for key, label in profile.DESCRIPTION_FIELDS:
            if key == "notes":
                edit = QtWidgets.QPlainTextEdit(description.get(key, ""))
                edit.setFixedHeight(80)
            else:
                edit = QtWidgets.QLineEdit(description.get(key, ""))
            self.description_edits[key] = edit
            form.addRow(label, edit)
        layout.addWidget(desc_box)

        lab_box = QtWidgets.QGroupBox("Lab context files")
        lab_layout = QtWidgets.QHBoxLayout(lab_box)
        folder_label = QtWidgets.QLabel(str(controller.lab_folder))
        folder_label.setWordWrap(True)
        folder_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        open_button = QtWidgets.QPushButton("Open folder")
        lab_layout.addWidget(folder_label, 1)
        lab_layout.addWidget(open_button)
        layout.addWidget(lab_box)

        answers_row = QtWidgets.QHBoxLayout()
        self.answers_label = QtWidgets.QLabel(
            f"{len(controller.last_answers())} remembered answers are offered as prefills."
        )
        self.forget_button = QtWidgets.QPushButton("Forget remembered answers")
        self.forget_button.setToolTip(
            "Clear the answers kept on this PC for prefilling. Answers saved in scan "
            "files are not touched."
        )
        answers_row.addWidget(self.answers_label, 1)
        answers_row.addWidget(self.forget_button)
        layout.addLayout(answers_row)
        self.forget_button.clicked.connect(self._forget_answers)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Close
        )
        layout.addWidget(buttons)

        self.key_save_button.clicked.connect(self._save_key)
        self.key_test_button.clicked.connect(self._test_key)
        open_button.clicked.connect(
            lambda: QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(str(controller.lab_folder))
            )
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

    @property
    def provider(self) -> str:
        return self.provider_comboBox.currentData() or profile.DEFAULT_PROVIDER

    def _on_provider_changed(self, _index=None) -> None:
        if self._current_provider is not None:
            self._models[self._current_provider] = self.model_lineEdit.text().strip()
            self._base_urls[self._current_provider] = self.base_url_lineEdit.text().strip()
        provider = self.provider
        self._current_provider = provider
        info = profile.provider_info(provider)
        self.model_lineEdit.setText(self._models.get(provider) or info["default_model"])
        self.model_lineEdit.setPlaceholderText(info["default_model"])
        is_claude = provider == profile.PROVIDER_ANTHROPIC
        self.effort_label.setVisible(is_claude)
        self.effort_comboBox.setVisible(is_claude)
        self.thinking_checkBox.setVisible(provider == profile.PROVIDER_DEEPSEEK)
        self.base_url_label.setVisible(not is_claude)
        self.base_url_lineEdit.setVisible(not is_claude)
        self.base_url_lineEdit.setText(self._base_urls.get(provider, ""))
        self.key_lineEdit.clear()
        has_key = bool(self.controller.keys.get(provider))
        self.key_lineEdit.setPlaceholderText(
            f"A {info['label']} key is saved. Type a new one to replace it."
            if has_key
            else f"{info['label']} key ({info['key_hint']})"
        )

    def _forget_answers(self) -> None:
        self.controller.forget_answers()
        self.answers_label.setText("Remembered answers cleared.")

    def _save_key(self) -> None:
        key = self.key_lineEdit.text().strip()
        if not key:
            self.key_status_label.setText("Type a key first.")
            return
        persistent = self.controller.keys.set(key, self.provider)
        self.key_lineEdit.clear()
        label = profile.provider_info(self.provider)["label"]
        self.key_lineEdit.setPlaceholderText(f"A {label} key is saved. Type a new one to replace it.")
        self.key_status_label.setText(
            "Key saved in Windows Credential Manager."
            if persistent
            else "Key kept for this session only (keyring unavailable)."
        )

    def _test_key(self) -> None:
        provider = self.provider
        key = self.key_lineEdit.text().strip() or self.controller.keys.get(provider)
        model = self.model_lineEdit.text().strip() or profile.default_model(provider)
        base_url = self.base_url_lineEdit.text().strip()
        if not key:
            self.key_status_label.setText("No key to test.")
            return
        self.key_test_button.setEnabled(False)
        self.key_status_label.setText("Testing...")

        def done(result):
            self.key_test_button.setEnabled(True)
            if isinstance(result, dict):
                error = str(result.get("error", "unknown error"))
                error = error.removeprefix("QuestionnaireUnavailable: ")
                self.key_status_label.setText(f"Test failed: {error}")
            else:
                self.key_status_label.setText(f"Test passed ({model}).")

        self.controller.run_job(lambda: qn.test_api_key(key, model, provider, base_url), done)

    def _save(self) -> None:
        self.controller.settings.data["effort"] = self.effort_comboBox.currentText()
        self.controller.settings.data["thinking"] = self.thinking_checkBox.isChecked()
        if self.provider != profile.PROVIDER_ANTHROPIC:
            self.controller.settings.set_base_url(self.provider, self.base_url_lineEdit.text())
        self.controller.set_provider_model(self.provider, self.model_lineEdit.text())
        description = {}
        for key, edit in self.description_edits.items():
            if isinstance(edit, QtWidgets.QPlainTextEdit):
                description[key] = edit.toPlainText()
            else:
                description[key] = edit.text()
        self.controller.settings.set_description(description)
        if self.key_lineEdit.text().strip():
            self._save_key()
        self.accept()
