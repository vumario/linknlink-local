"""Focused performance-oriented tests for vendor LinknLink modules."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import socket
import sys
import types


VENDOR_PKG = (
    pathlib.Path(__file__).resolve().parent.parent
    / "custom_components"
    / "linknlink"
    / "vendor"
    / "linknlink"
)


def _load_vendor_module(name: str):
    package_name = "vendor_linknlink"
    if package_name not in sys.modules:
        pkg = types.ModuleType(package_name)
        pkg.__path__ = [str(VENDOR_PKG)]
        sys.modules[package_name] = pkg

    full_name = f"{package_name}.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]

    spec = importlib.util.spec_from_file_location(full_name, VENDOR_PKG / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


const = _load_vendor_module("const")
device_mod = _load_vendor_module("device")
remote_mod = _load_vendor_module("remote")


def _make_scan_response(devtype: int, mac: bytes, name: str, locked: bool = False) -> bytes:
    payload = bytearray(0x80)
    payload[0x34] = devtype & 0xFF
    payload[0x35] = (devtype >> 8) & 0xFF
    payload[0x3A:0x40] = mac[::-1]
    payload[0x40 : 0x40 + len(name)] = name.encode()
    payload[0x7F] = int(locked)
    return bytes(payload)


def test_scan_deduplicates_with_set(monkeypatch):
    recv_payload = _make_scan_response(0xAC7B, b"\xaa\xbb\xcc\xdd\xee\xff", "dev")
    recv_host = ("192.168.1.10", 80)

    class FakeSocket:
        def __init__(self):
            self._responses = [
                (recv_payload, recv_host),
                (recv_payload, recv_host),  # duplicate
            ]

        def setsockopt(self, *_):
            return None

        def bind(self, *_):
            return None

        def getsockname(self):
            return ("0.0.0.0", 12345)

        def settimeout(self, *_):
            return None

        def sendto(self, *_):
            return None

        def recvfrom(self, *_):
            if self._responses:
                return self._responses.pop(0)
            raise socket.timeout()

        def close(self):
            return None

    fake_sock = FakeSocket()
    monkeypatch.setattr(device_mod.socket, "socket", lambda *a, **k: fake_sock)

    clock = {"t": 0.0}

    def fake_time():
        clock["t"] += 0.2
        return clock["t"]

    monkeypatch.setattr(device_mod.time, "time", fake_time)
    results = list(device_mod.scan(timeout=0.5))
    assert len(results) == 1


def test_send_packet_uses_lock_and_reuses_socket(monkeypatch):
    class FakeLock:
        def __init__(self):
            self.entered = 0

        def __enter__(self):
            self.entered += 1
            return self

        def __exit__(self, *_):
            return False

    class FakeSocket:
        def __init__(self, response: bytes):
            self._response = response

        def settimeout(self, *_):
            return None

        def sendto(self, *_):
            return None

        def recvfrom(self, *_):
            return self._response, ("192.168.1.2", 80)

        def close(self):
            return None

    class SocketFactory:
        def __init__(self, response: bytes):
            self.created = 0
            self._socket = FakeSocket(response)

        def __call__(self, *_args, **_kwargs):
            self.created += 1
            return self._socket

    class TestDevice(device_mod.Device):
        def update_aes(self, _key):
            self.aes = None

        def encrypt(self, payload: bytes) -> bytes:
            return payload

        def decrypt(self, payload: bytes) -> bytes:
            return payload

    response = bytearray(0x30)
    checksum = (sum(response, 0xBEAF) - sum(response[0x20:0x22])) & 0xFFFF
    response[0x20:0x22] = checksum.to_bytes(2, "little")

    factory = SocketFactory(bytes(response))
    monkeypatch.setattr(device_mod.socket, "socket", factory)
    lock = FakeLock()

    dev = TestDevice(("192.168.1.2", 80), b"\xaa\xbb\xcc\xdd\xee\xff", 0xAC7B)
    dev.lock = lock
    dev.send_packet(0x6A, b"\x01")
    dev.send_packet(0x6A, b"\x02")

    assert lock.entered == 2
    assert factory.created == 1


def test_eremote_sensor_cache_avoids_repeat_calls():
    class TestERemote(remote_mod.eremote):
        def __init__(self):
            super().__init__(("192.168.1.2", 80), b"\xaa\xbb\xcc\xdd\xee\xff", 0xAC99)
            self.calls = []

        def _ensure_background_workers(self):
            return None

        def _sendV2(self, command: int, data: bytes = b"") -> bytes:
            self.calls.append((command, data))
            if command == 0x0B0E:
                listing = {
                    "list": [
                        {"pid": const.PID_HUMITURE, "did": "did_h"},
                        {"pid": const.PID_DOORSENSOR, "did": "did_d"},
                    ]
                }
                return json.dumps(listing).encode("utf-8")
            payload = json.loads(data.decode("utf-8"))
            if payload["did"] == "did_h":
                return json.dumps({"envtemp": 2500, "envhumid": 5000}).encode("utf-8")
            return json.dumps({"doorsensor_status": 1}).encode("utf-8")

    dev = TestERemote()
    first = dev.check_sensors()
    before = len(dev.calls)
    second = dev.check_sensors()

    assert first["envtemp"] == 25.0
    assert first["envhumid"] == 50.0
    assert first["doorsensor_status"] == 1
    assert second == first
    assert len(dev.calls) == before


def test_eremote_stop_background_workers_closes_socket():
    class FakeSocket:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    dev = remote_mod.eremote(("192.168.1.2", 80), b"\xaa\xbb\xcc\xdd\xee\xff", 0xAC99)
    dev.UdpFlag = True
    fake_socket = FakeSocket()
    dev._udp_server_socket = fake_socket
    dev.stop_background_workers()
    assert dev.UdpFlag is False
    assert fake_socket.closed is True
