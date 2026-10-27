"""Application-wide setup-capture state owned by the main window.

One controller exists per ZMeter window.  It holds the per-PC settings and
the API key, runs model calls on worker threads, and remembers the last
answers so the next questionnaire can be prefilled.  It also tracks an
active queue questionnaire so scans in that queue skip their own model call.
"""

from __future__ import annotations

from typing import Callable, Iterable, Mapping

from PyQt6 import QtCore

from . import profile
from . import questionnaire as qn

LAST_ANSWERS_LIMIT = 60


class SetupCaptureController(QtCore.QObject):
    def __init__(self, main_window=None, parent=None, *, settings=None, keys=None, lab_folder=None):
        super().__init__(parent)
        self.main_window = main_window
        self.settings = settings if settings is not None else profile.SetupCaptureSettings()
        self.keys = keys if keys is not None else profile.ApiKeyStore()
        self.lab_folder = lab_folder or profile.lab_context_dir()
        self.queue_session = None
        self._workers: set[qn.QuestionnaireWorker] = set()

    # ----------------------------------------------------------- settings --
    @property
    def provider(self) -> str:
        return self.settings.provider

    @property
    def model(self) -> str:
        return self.settings.model

    def set_provider_model(self, provider: str, model: str) -> None:
        self.settings.set_provider_model(provider, model)

    @property
    def description(self) -> dict:
        return self.settings.description

    def last_answers(self) -> list[dict]:
        items = self.settings.data.get("last_answers", [])
        return [dict(item) for item in items if isinstance(item, Mapping)]

    def remember_answers(self, items: Iterable[Mapping]) -> None:
        """Keep answered items (newest first) for prefilling later forms."""

        fresh = [
            {
                "id": item.get("id"),
                "text": item.get("text"),
                "answer": item.get("answer"),
                "status": item.get("status"),
            }
            for item in items or ()
            if isinstance(item, Mapping)
            and item.get("status") in (qn.STATUS_ANSWERED, qn.STATUS_UNKNOWN, qn.STATUS_PREFILLED)
            and not qn.is_stale_item(item)
        ]
        if not fresh:
            return
        seen = {item["id"] for item in fresh}
        older = [item for item in self.last_answers() if item.get("id") not in seen]
        self.settings.data["last_answers"] = (fresh + older)[:LAST_ANSWERS_LIMIT]
        try:
            self.settings.save()
        except OSError:
            pass

    def forget_answers(self) -> None:
        self.settings.data["last_answers"] = []
        try:
            self.settings.save()
        except OSError:
            pass

    def previous_items_for(self, items: Iterable[Mapping] | None) -> list[dict]:
        """A scan's own answers first, then the most recent answers on this PC."""

        own = [dict(item) for item in items or () if isinstance(item, Mapping)]
        own_ids = {item.get("id") for item in own}
        return own + [item for item in self.last_answers() if item.get("id") not in own_ids]

    # ------------------------------------------------------------ workers --
    def run_job(self, job: Callable[[], object], callback: Callable[[object], None]):
        worker = qn.QuestionnaireWorker(job=job, parent=self)

        def done(result, worker=worker):
            self._workers.discard(worker)
            worker.deleteLater()
            callback(result)

        worker.sig_done.connect(done)
        self._workers.add(worker)
        worker.start()
        return worker

    def generate_async(
        self,
        *,
        mode: str,
        plan: list[dict],
        snapshot: Mapping | None,
        previous_items: list[Mapping],
        callback: Callable[[dict], None],
        snapshot_job: Callable[[], dict] | None = None,
        previous_inferences: list[Mapping] | None = None,
    ):
        """Generate questions off the UI thread.

        With ``snapshot_job`` the worker first takes a snapshot and stores it
        in the result under ``"snapshot"``.
        """

        provider = self.provider
        effort = self.settings.effort
        thinking = self.settings.thinking
        base_url = self.settings.base_url_for(provider)
        api_key = self.keys.get(provider)
        model = self.model
        description = self.description
        lab_folder = self.lab_folder

        def job():
            taken = snapshot_job() if snapshot_job is not None else snapshot
            if not api_key:
                record = qn.generate(
                    mode=mode,
                    plan=plan,
                    snapshot=taken,
                    description=description,
                    previous_items=previous_items,
                    api_key="",
                    model=model,
                    lab_folder=lab_folder,
                    model_call=_no_key_call,
                    previous_inferences=previous_inferences,
                    provider=provider,
                    effort=effort,
                    thinking=thinking,
                    base_url=base_url,
                )
            else:
                record = qn.generate(
                    mode=mode,
                    plan=plan,
                    snapshot=taken,
                    description=description,
                    previous_items=previous_items,
                    api_key=api_key,
                    model=model,
                    lab_folder=lab_folder,
                    previous_inferences=previous_inferences,
                    provider=provider,
                    effort=effort,
                    thinking=thinking,
                    base_url=base_url,
                )
            record["mode"] = mode
            if snapshot_job is not None:
                record["snapshot"] = taken
            return record

        return self.run_job(job, callback)

    def wait_for_workers(self, timeout_ms: int = 2000) -> None:
        for worker in list(self._workers):
            worker.wait(timeout_ms)


def _no_key_call(*_args, **_kwargs):
    raise qn.QuestionnaireUnavailable(
        "no API key saved (Setup capture settings); showing suggested questions"
    )
