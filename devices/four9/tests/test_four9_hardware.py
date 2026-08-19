import json
import socketserver
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from devices.four9.four9_hardware import (
    Four9ConnectionError,
    Four9Hardware,
    Four9ProtocolError,
    Four9ServerError,
)


_CLOSE_CONNECTION = object()


class _ProtocolState:
    def __init__(self):
        self.greeting = {"ok": True, "data": "Temperature control API ready"}
        self.target = 0.0
        self.commands = []
        self.responses = {}
        self.lock = threading.Lock()

    def response_for(self, command):
        with self.lock:
            self.commands.append(command)
        override = self.responses.get(command)
        if override is not None:
            return override
        if command == "PING":
            return {"ok": True, "data": "PONG"}
        if command.startswith("SET_TEMPERATURE "):
            self.target = float(command.split()[1])
            return {"ok": True, "data": {"target": self.target}}
        if command == "GET_STATUS":
            return {
                "ok": True,
                "data": {
                    "target": self.target,
                    "stable": False,
                    "latest_temperature": 4.25,
                    "stability_metrics": {"stable_reason": "unstable"},
                    "last_error": "",
                },
            }
        if command == "QUIT":
            return {"ok": True, "data": "BYE"}
        return {"ok": False, "error": "unknown command"}


class _ProtocolHandler(socketserver.StreamRequestHandler):
    def handle(self):
        state = self.server.state
        greeting = state.greeting
        if isinstance(greeting, bytes):
            self.wfile.write(greeting)
        else:
            self.wfile.write(
                (json.dumps(greeting, separators=(",", ":")) + "\n").encode()
            )
        for raw_line in self.rfile:
            command = raw_line.decode("utf-8").strip()
            response = state.response_for(command)
            if response is _CLOSE_CONNECTION:
                return
            if isinstance(response, bytes):
                self.wfile.write(response)
            else:
                self.wfile.write(
                    (json.dumps(response, separators=(",", ":")) + "\n").encode()
                )
            if command == "QUIT":
                return


class _FakeProtocolServer:
    def __init__(self, state=None):
        self.state = state or _ProtocolState()
        self.server = socketserver.ThreadingTCPServer(
            ("127.0.0.1", 0), _ProtocolHandler
        )
        self.server.daemon_threads = True
        self.server.state = self.state
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def port(self):
        return self.server.server_address[1]

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class Four9HardwareTests(unittest.TestCase):
    def test_connect_commands_and_disconnect_use_json_line_protocol(self):
        with _FakeProtocolServer() as server:
            hardware = Four9Hardware(port=server.port, socket_timeout_s=1)
            self.assertTrue(hardware.connect_hardware())
            self.assertTrue(hardware.is_connected)
            self.assertEqual(hardware.set_temperature(0), 0.0)
            self.assertEqual(hardware.set_temperature(300), 300.0)
            status = hardware.get_status()
            self.assertEqual(status["latest_temperature"], 4.25)
            hardware.disconnect()
            self.assertFalse(hardware.is_connected)

        self.assertEqual(
            server.state.commands,
            [
                "PING",
                "SET_TEMPERATURE 0",
                "SET_TEMPERATURE 300",
                "GET_STATUS",
                "QUIT",
            ],
        )

    def test_temperature_range_is_validated_before_transmission(self):
        with _FakeProtocolServer() as server:
            hardware = Four9Hardware(port=server.port, socket_timeout_s=1)
            hardware.connect_hardware()
            with self.assertRaises(ValueError):
                hardware.set_temperature(-0.001)
            with self.assertRaises(ValueError):
                hardware.set_temperature(300.001)
            with self.assertRaises(ValueError):
                hardware.set_temperature(float("nan"))
            hardware.disconnect()
        self.assertEqual(server.state.commands, ["PING", "QUIT"])

    def test_valid_server_error_preserves_connection(self):
        state = _ProtocolState()
        state.responses["SET_TEMPERATURE 20"] = {
            "ok": False,
            "error": "target rejected",
        }
        with _FakeProtocolServer(state) as server:
            hardware = Four9Hardware(port=server.port, socket_timeout_s=1)
            hardware.connect_hardware()
            with self.assertRaisesRegex(Four9ServerError, "target rejected"):
                hardware.set_temperature(20)
            self.assertTrue(hardware.is_connected)
            self.assertEqual(hardware.ping(), "PONG")
            hardware.disconnect()

    def test_malformed_json_invalidates_connection(self):
        state = _ProtocolState()
        state.responses["GET_STATUS"] = b"not-json\n"
        with _FakeProtocolServer(state) as server:
            hardware = Four9Hardware(port=server.port, socket_timeout_s=1)
            hardware.connect_hardware()
            with self.assertRaises(Four9ProtocolError):
                hardware.get_status()
            self.assertFalse(hardware.is_connected)

    def test_transport_loss_invalidates_connection(self):
        state = _ProtocolState()
        state.responses["GET_STATUS"] = _CLOSE_CONNECTION
        with _FakeProtocolServer(state) as server:
            hardware = Four9Hardware(port=server.port, socket_timeout_s=1)
            hardware.connect_hardware()
            with self.assertRaises(Four9ConnectionError):
                hardware.get_status()
            self.assertFalse(hardware.is_connected)

    def test_invalid_greeting_is_rejected(self):
        state = _ProtocolState()
        state.greeting = {"ok": True, "data": "wrong service"}
        with _FakeProtocolServer(state) as server:
            hardware = Four9Hardware(port=server.port, socket_timeout_s=1)
            with self.assertRaises(Four9ProtocolError):
                hardware.connect_hardware()
            self.assertFalse(hardware.is_connected)

    def test_concurrent_callers_receive_their_own_responses(self):
        with _FakeProtocolServer() as server:
            hardware = Four9Hardware(port=server.port, socket_timeout_s=1)
            hardware.connect_hardware()
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(lambda _index: hardware.ping(), range(40)))
            hardware.disconnect()
        self.assertEqual(results, ["PONG"] * 40)
        self.assertEqual(server.state.commands.count("PING"), 41)


if __name__ == "__main__":
    unittest.main()
