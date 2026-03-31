from __future__ import annotations

from copy import deepcopy
import uuid

from PyQt6 import QtCore


class DeviceCommandRouter(QtCore.QObject):
    sig_command_requested = QtCore.pyqtSignal(object)
    sig_command_responded = QtCore.pyqtSignal(object)
    sig_catalog_changed = QtCore.pyqtSignal(object)

    SUPPORTED_ACTIONS = {"read", "write", "list_catalog"}
    REQUIRED_REQUEST_KEYS = {
        "request_id",
        "source_device",
        "action",
        "target_device",
        "channel",
        "value",
    }

    def __init__(self, main_window, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self.main_window = main_window
        self.sig_command_requested.connect(
            self._handle_request,
            QtCore.Qt.ConnectionType.QueuedConnection,
        )

    @QtCore.pyqtSlot(object)
    def _handle_request(self, request: object) -> None:
        response = self.route_command(request)
        self.sig_command_responded.emit(response)

    def route_command(self, request: object) -> dict:
        if not isinstance(request, dict):
            return self._make_error_response(
                request_id=None,
                source_device="unknown",
                action=None,
                target_device=None,
                channel=None,
                error_code="invalid_request",
                error_message="Command request must be a dictionary.",
            )

        missing_keys = sorted(self.REQUIRED_REQUEST_KEYS.difference(request))
        if missing_keys:
            return self._make_error_response(
                request_id=request.get("request_id"),
                source_device=request.get("source_device", "unknown"),
                action=request.get("action"),
                target_device=request.get("target_device"),
                channel=request.get("channel"),
                error_code="invalid_request",
                error_message=f"Missing required request keys: {', '.join(missing_keys)}.",
            )

        request_id = request.get("request_id")
        source_device = request.get("source_device")
        action = request.get("action")
        target_device = request.get("target_device")
        channel = request.get("channel")
        value = request.get("value")

        if not source_device:
            return self._make_error_response(
                request_id=request_id,
                source_device="unknown",
                action=action,
                target_device=target_device,
                channel=channel,
                error_code="invalid_request",
                error_message="source_device is required.",
            )

        if action not in self.SUPPORTED_ACTIONS:
            return self._make_error_response(
                request_id=request_id,
                source_device=source_device,
                action=action,
                target_device=target_device,
                channel=channel,
                error_code="unsupported_action",
                error_message=f"Unsupported action '{action}'.",
            )

        catalog = self.main_window.get_device_channel_catalog()

        if action == "list_catalog":
            return self._make_success_response(
                request_id=request_id,
                source_device=source_device,
                action=action,
                target_device=target_device,
                channel=channel,
                value=None,
                catalog=catalog,
            )

        if not target_device:
            return self._make_error_response(
                request_id=request_id,
                source_device=source_device,
                action=action,
                target_device=target_device,
                channel=channel,
                error_code="unknown_device",
                error_message="target_device is required.",
            )

        target_catalog = catalog.get(target_device)
        if target_catalog is None:
            return self._make_error_response(
                request_id=request_id,
                source_device=source_device,
                action=action,
                target_device=target_device,
                channel=channel,
                error_code="unknown_device",
                error_message=f"Unknown target device '{target_device}'.",
            )

        if not channel:
            return self._make_error_response(
                request_id=request_id,
                source_device=source_device,
                action=action,
                target_device=target_device,
                channel=channel,
                error_code="unknown_channel",
                error_message="channel is required.",
            )

        allowed_channels = (
            target_catalog["readable"] if action == "read" else target_catalog["writable"]
        )
        if channel not in allowed_channels:
            return self._make_error_response(
                request_id=request_id,
                source_device=source_device,
                action=action,
                target_device=target_device,
                channel=channel,
                error_code="unknown_channel",
                error_message=(
                    f"Channel '{channel}' is not available for action '{action}' "
                    f"on device '{target_device}'."
                ),
            )

        if action == "write" and value is None:
            return self._make_error_response(
                request_id=request_id,
                source_device=source_device,
                action=action,
                target_device=target_device,
                channel=channel,
                error_code="missing_value",
                error_message="Write requests require a non-null value.",
            )

        full_channel_name = f"{target_device}_{channel}"
        try:
            if action == "read":
                result_value = self.main_window.read_info(full_channel_name)
            else:
                self.main_window.write_info(value, full_channel_name)
                result_value = value
        except Exception as exc:
            return self._make_error_response(
                request_id=request_id,
                source_device=source_device,
                action=action,
                target_device=target_device,
                channel=channel,
                error_code="execution_error",
                error_message=str(exc),
            )

        return self._make_success_response(
            request_id=request_id,
            source_device=source_device,
            action=action,
            target_device=target_device,
            channel=channel,
            value=result_value,
            catalog=None,
        )

    def publish_catalog(self, catalog: dict) -> None:
        self.sig_catalog_changed.emit(deepcopy(catalog))

    def _make_success_response(
        self,
        *,
        request_id,
        source_device,
        action,
        target_device,
        channel,
        value,
        catalog,
    ) -> dict:
        return {
            "request_id": request_id,
            "ok": True,
            "action": action,
            "source_device": source_device,
            "target_device": target_device,
            "channel": channel,
            "value": value,
            "catalog": deepcopy(catalog),
            "error_code": None,
            "error_message": None,
        }

    def _make_error_response(
        self,
        *,
        request_id,
        source_device,
        action,
        target_device,
        channel,
        error_code,
        error_message,
    ) -> dict:
        return {
            "request_id": request_id,
            "ok": False,
            "action": action,
            "source_device": source_device,
            "target_device": target_device,
            "channel": channel,
            "value": None,
            "catalog": None,
            "error_code": error_code,
            "error_message": error_message,
        }


class DeviceCommandClient(QtCore.QObject):
    sig_response = QtCore.pyqtSignal(object)
    sig_catalog_changed = QtCore.pyqtSignal(object)

    def __init__(
        self,
        command_router: DeviceCommandRouter,
        source_device: str,
        parent: QtCore.QObject | None = None,
    ):
        super().__init__(parent)
        self.command_router = command_router
        self.source_device = source_device
        self._pending_request_ids: set[str] = set()

        self.command_router.sig_command_responded.connect(self._handle_response)
        self.command_router.sig_catalog_changed.connect(self._forward_catalog_changed)

    def request_catalog(self, request_id: str | None = None) -> str:
        return self.send_request(
            action="list_catalog",
            target_device=None,
            channel=None,
            value=None,
            request_id=request_id,
        )

    def request_read(
        self,
        target_device: str,
        channel: str,
        request_id: str | None = None,
    ) -> str:
        return self.send_request(
            action="read",
            target_device=target_device,
            channel=channel,
            value=None,
            request_id=request_id,
        )

    def request_write(
        self,
        target_device: str,
        channel: str,
        value,
        request_id: str | None = None,
    ) -> str:
        return self.send_request(
            action="write",
            target_device=target_device,
            channel=channel,
            value=value,
            request_id=request_id,
        )

    def send_request(
        self,
        *,
        action: str,
        target_device,
        channel,
        value,
        request_id: str | None = None,
    ) -> str:
        request_id = request_id or str(uuid.uuid4())
        self._pending_request_ids.add(request_id)
        self.command_router.sig_command_requested.emit(
            {
                "request_id": request_id,
                "source_device": self.source_device,
                "action": action,
                "target_device": target_device,
                "channel": channel,
                "value": value,
            }
        )
        return request_id

    @QtCore.pyqtSlot(object)
    def _handle_response(self, response: object) -> None:
        if not isinstance(response, dict):
            return
        request_id = response.get("request_id")
        if request_id not in self._pending_request_ids:
            return
        self._pending_request_ids.discard(request_id)
        self.sig_response.emit(response)

    @QtCore.pyqtSlot(object)
    def _forward_catalog_changed(self, catalog: object) -> None:
        self.sig_catalog_changed.emit(catalog)
