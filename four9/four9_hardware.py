"""Low-level TCP client for the maintained Four9 temperature server."""

from __future__ import annotations

import json
import math
import socket
import threading
from typing import Any, BinaryIO


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5050
DEFAULT_SOCKET_TIMEOUT_S = 10.0
MIN_TEMPERATURE_K = 0.0
MAX_TEMPERATURE_K = 300.0
EXPECTED_GREETING = "Temperature control API ready"


class Four9Error(RuntimeError):
    """Base error for Four9 client operations."""


class Four9ConnectionError(Four9Error):
    """Raised when the TCP connection cannot be used."""


class Four9ProtocolError(Four9Error):
    """Raised when a response does not follow the Four9 protocol."""


class Four9ServerError(Four9ProtocolError):
    """Raised for a valid ``ok:false`` response from the server."""


class Four9Hardware:
    """Synchronized persistent connection to the Four9 TCP service.

    One lock covers each complete command/response exchange. This is required
    because ZMeter scan calls and UI jobs can execute on different threads.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        socket_timeout_s: float = DEFAULT_SOCKET_TIMEOUT_S,
    ) -> None:
        self.host = str(host)
        self.port = int(port)
        self.socket_timeout_s = float(socket_timeout_s)
        self.greeting = ""

        self._socket: socket.socket | None = None
        self._file: BinaryIO | None = None
        self._command_lock = threading.RLock()

    @property
    def is_connected(self) -> bool:
        return self._socket is not None and self._file is not None

    @staticmethod
    def validate_temperature(target_k: float) -> float:
        target = float(target_k)
        if not math.isfinite(target):
            raise ValueError("Temperature target must be finite.")
        if target < MIN_TEMPERATURE_K or target > MAX_TEMPERATURE_K:
            raise ValueError(
                f"Temperature target must be between {MIN_TEMPERATURE_K:g} K "
                f"and {MAX_TEMPERATURE_K:g} K."
            )
        return target

    @staticmethod
    def _validate_endpoint(host: str, port: int, timeout_s: float) -> None:
        if not str(host).strip():
            raise ValueError("Four9 host cannot be empty.")
        if not 1 <= int(port) <= 65535:
            raise ValueError("Four9 port must be between 1 and 65535.")
        if not math.isfinite(float(timeout_s)) or float(timeout_s) <= 0:
            raise ValueError("Socket timeout must be a positive finite value.")

    def connect_hardware(
        self,
        host: str | None = None,
        port: int | None = None,
    ) -> bool:
        new_host = self.host if host is None else str(host).strip()
        new_port = self.port if port is None else int(port)
        self._validate_endpoint(new_host, new_port, self.socket_timeout_s)

        with self._command_lock:
            self._close_locked()
            self.host = new_host
            self.port = new_port

            try:
                sock = socket.create_connection(
                    (self.host, self.port), timeout=self.socket_timeout_s
                )
                sock.settimeout(self.socket_timeout_s)
                stream = sock.makefile("rwb")
            except (OSError, ValueError) as exc:
                raise Four9ConnectionError(
                    f"Could not connect to {self.host}:{self.port}: {exc}"
                ) from exc

            self._socket = sock
            self._file = stream
            try:
                greeting = self._read_response_locked()
                if greeting != EXPECTED_GREETING:
                    raise Four9ProtocolError(
                        "Unexpected Four9 greeting: " + repr(greeting)
                    )
                self.greeting = str(greeting)

                pong = self._command_locked("PING")
                if pong != "PONG":
                    raise Four9ProtocolError(
                        f"Unexpected Four9 PING response: {pong!r}"
                    )
            except Four9ServerError:
                self._close_locked()
                raise
            except (Four9ConnectionError, Four9ProtocolError):
                self._close_locked()
                raise

        return True

    def ping(self) -> str:
        result = self._command("PING")
        if result != "PONG":
            self._invalidate_and_raise(
                Four9ProtocolError(f"Unexpected Four9 PING response: {result!r}")
            )
        return str(result)

    def set_temperature(self, target_k: float) -> float:
        target = self.validate_temperature(target_k)
        data = self._command(f"SET_TEMPERATURE {target:.15g}")
        if not isinstance(data, dict) or "target" not in data:
            self._invalidate_and_raise(
                Four9ProtocolError("SET_TEMPERATURE response is missing target data.")
            )
        try:
            returned_target = float(data["target"])
        except (TypeError, ValueError) as exc:
            self._invalidate_and_raise(
                Four9ProtocolError(
                    "SET_TEMPERATURE returned a non-numeric target."
                ),
                cause=exc,
            )
        if not math.isfinite(returned_target):
            self._invalidate_and_raise(
                Four9ProtocolError("SET_TEMPERATURE returned a non-finite target.")
            )
        return returned_target

    def get_status(self) -> dict[str, Any]:
        data = self._command("GET_STATUS")
        if not isinstance(data, dict):
            self._invalidate_and_raise(
                Four9ProtocolError("GET_STATUS response data must be an object.")
            )
        return data

    def disconnect(self) -> None:
        with self._command_lock:
            if not self.is_connected:
                return
            try:
                self._command_locked("QUIT")
            except Four9Error:
                # QUIT only closes this client; it never stops the server.
                pass
            finally:
                self._close_locked()

    def _command(self, command: str) -> Any:
        with self._command_lock:
            try:
                return self._command_locked(command)
            except Four9ServerError:
                # A valid ok:false response does not invalidate the TCP stream.
                raise
            except (Four9ConnectionError, Four9ProtocolError):
                self._close_locked()
                raise

    def _command_locked(self, command: str) -> Any:
        if not self.is_connected or self._file is None:
            raise Four9ConnectionError("Four9 is not connected.")
        if "\n" in command or "\r" in command:
            raise ValueError("Four9 commands must contain exactly one line.")

        try:
            self._file.write((command + "\n").encode("utf-8"))
            self._file.flush()
        except (OSError, ValueError) as exc:
            raise Four9ConnectionError(
                f"Failed to send Four9 command {command!r}: {exc}"
            ) from exc
        return self._read_response_locked()

    def _read_response_locked(self) -> Any:
        if self._file is None:
            raise Four9ConnectionError("Four9 is not connected.")
        try:
            raw_line = self._file.readline()
        except (OSError, ValueError) as exc:
            raise Four9ConnectionError(
                f"Failed to read Four9 response: {exc}"
            ) from exc
        if not raw_line:
            raise Four9ConnectionError("Four9 server closed the connection.")

        try:
            response = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Four9ProtocolError(
                "Four9 returned an invalid UTF-8 JSON response."
            ) from exc
        if not isinstance(response, dict):
            raise Four9ProtocolError("Four9 response must be a JSON object.")
        if type(response.get("ok")) is not bool:
            raise Four9ProtocolError("Four9 response is missing a boolean 'ok' field.")
        if not response["ok"]:
            error = response.get("error")
            if not isinstance(error, str) or not error:
                raise Four9ProtocolError(
                    "Four9 error response is missing an error message."
                )
            raise Four9ServerError(error)
        if "data" not in response:
            raise Four9ProtocolError("Four9 success response is missing 'data'.")
        return response["data"]

    def _invalidate_and_raise(
        self,
        error: Four9ProtocolError,
        *,
        cause: BaseException | None = None,
    ) -> None:
        with self._command_lock:
            self._close_locked()
        if cause is None:
            raise error
        raise error from cause

    def _close_locked(self) -> None:
        stream, sock = self._file, self._socket
        self._file = None
        self._socket = None
        self.greeting = ""
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
