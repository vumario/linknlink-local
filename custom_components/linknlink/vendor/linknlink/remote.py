"""Support for universal remotes."""
import struct
import socket
import time
import threading

from . import exceptions as e
from .device import Device
from .device import Device
from.const import PID_DOORSENSOR, PID_HUMITURE, PID_REMOTE
import json

class ehub(Device):
    """Controls a LinknLink ehub."""

    TYPE = "EHUB"
    
    # sensor function
    def _send(self, command: int, data: bytes = b"") -> bytes:
        """Send a packet to the device."""
        if 20000 <= self.devtype <= 29999:
            packet = struct.pack("<HI", len(data) + 4, command) + data
        else:
            packet = struct.pack("<I", command) + data
        resp = self.send_packet(0x6A, packet)
        e.check_error(resp[0x22:0x24])
        payload = self.decrypt(resp[0x38:])
        if 20000 <= self.devtype <= 29999:
            p_len = struct.unpack("<H", payload[:0x2])[0]
            return payload[0x6 : p_len + 2]
        return payload[0x4:]
    
    def check_sensors(self) -> dict:
        """Return the state of the sensors."""
        resp = self._send(0x24)
        return {
            "envtemp": resp[0x0] + resp[0x1] / 100.0,
            "envhumid": resp[0x2] + resp[0x3] / 100.0,
            "pir_detected": resp[0x6],
        }

    def check_temperature(self) -> float:
        """Return the temperature."""
        return self.check_sensors()["temperature"]

    def check_humidity(self) -> float:
        """Return the humidity."""
        return self.check_sensors()["humidity"]
    
    def check_pir(self) -> str:
        """Return the pirDetected."""
        return self.check_sensors()["pir_detected"]

    # remote function
    def sweep_frequency(self) -> None:
        """Sweep frequency."""
        self._send(0x19)

    def check_frequency(self) -> bool:
        """Return True if the frequency was identified successfully."""
        resp = self._send(0x1A)
        return resp[0] == 1

    def find_rf_packet(self) -> None:
        """Enter radiofrequency learning mode."""
        self._send(0x1B)

    def cancel_sweep_frequency(self) -> None:
        """Cancel sweep frequency."""
        self._send(0x1E)

    def update(self) -> None:
        """Update device name and lock status."""
        resp = self._send(0x1)
        self.name = resp[0x48:].split(b"\x00")[0].decode()
        self.is_locked = bool(resp[0x87])

    def send_data(self, data: bytes) -> None:
        """Send a code to the device."""
        self._send(0x2, data)

    def enter_learning(self) -> None:
        """Enter infrared learning mode."""
        self._send(0x3)

    def check_data(self) -> bytes:
        """Return the last captured code."""
        return self._send(0x4)

class ehome_rf_ha(Device):
    """Controls a LinknLink eHome HA RF remote (without sensors)."""

    TYPE = "EHOME_RF_HA"
    
    def _send(self, command: int, data: bytes = b"") -> bytes:
        """Send a packet to the device."""
        if 20000 <= self.devtype <= 29999:
            packet = struct.pack("<HI", len(data) + 4, command) + data
        else:
            packet = struct.pack("<I", command) + data
        resp = self.send_packet(0x6A, packet)
        e.check_error(resp[0x22:0x24])
        payload = self.decrypt(resp[0x38:])
        if 20000 <= self.devtype <= 29999:
            p_len = struct.unpack("<H", payload[:0x2])[0]
            return payload[0x6 : p_len + 2]
        return payload[0x4:]
    
    # remote function
    def sweep_frequency(self) -> None:
        """Sweep frequency."""
        self._send(0x19)

    def check_frequency(self) -> bool:
        """Return True if the frequency was identified successfully."""
        resp = self._send(0x1A)
        return resp[0] == 1

    def find_rf_packet(self) -> None:
        """Enter radiofrequency learning mode."""
        self._send(0x1B)

    def cancel_sweep_frequency(self) -> None:
        """Cancel sweep frequency."""
        self._send(0x1E)

    def update(self) -> None:
        """Update device name and lock status."""
        resp = self._send(0x1)
        self.name = resp[0x48:].split(b"\x00")[0].decode()
        self.is_locked = bool(resp[0x87])

    def send_data(self, data: bytes) -> None:
        """Send a code to the device."""
        self._send(0x2, data)

    def enter_learning(self) -> None:
        """Enter infrared learning mode."""
        self._send(0x3)

    def check_data(self) -> bytes:
        """Return the last captured code."""
        return self._send(0x4)

class eremote(Device):
    """Controls a LinknLink eremote."""

    TYPE = "EREMOTE"
    UdpFlag = False
    Port = 61212
    PID_CACHE_TTL = 30
    SENSOR_CACHE_TTL = 2
    LOOPBACK_BIND_IP = "127.0.0.1"

    def __init__(self, *args, **kwargs) -> None:
        """Initialize an eRemote device."""
        super().__init__(*args, **kwargs)
        self.UdpFlag = False
        self.Port = 61212
        self._stop_event = threading.Event()
        self._thread_lock = threading.Lock()
        self._udp_thread = None
        self._timeout_thread = None
        self._udp_server_socket = None
        self._pid_cache = None
        self._pid_cache_expires = 0.0
        self._did_snapshot_cache = {}
        self._last_sensor_snapshot = {}
        self._last_sensor_snapshot_expires = 0.0
    
    def _send(self, command: int, data: bytes = b"") -> bytes:
        """Send a packet to the device."""
        if 20000 <= self.devtype <= 29999:
            packet = struct.pack("<HI", len(data) + 4, command) + data
        else:
            packet = struct.pack("<I", command) + data
        resp = self.send_packet(0x6A, packet)
        e.check_error(resp[0x22:0x24])
        payload = self.decrypt(resp[0x38:])
        if 20000 <= self.devtype <= 29999:
            p_len = struct.unpack("<H", payload[:0x2])[0]
            return payload[0x6 : p_len + 2]
        return payload[0x4:]
    
    def _sendV2(self, command: int, data: bytes = b"") -> bytes:
        """Send a packet to the device."""
        cmdstu = self.build_cmdstuV2(command, data)
        resp = self.send_packet(0x6A, cmdstu)
        e.check_error(resp[0x22:0x24])
        payload = self.decrypt(resp[0x38:])
        res = self.analysis_data(payload)
        return res[2]
    
    def startUdpServer(self):
        """Start a UDP server for callback events."""
        udp_server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        bind_ip = self._get_bind_ip()
        while True:
            server_address = (bind_ip, self.Port)
            try:
                udp_server_socket.bind(server_address)
                break
            except OSError as err:
                if err.errno == socket.errno.EADDRINUSE:
                    self.Port += 1
                    continue
                udp_server_socket.close()
                raise

        udp_server_socket.settimeout(1)
        self._udp_server_socket = udp_server_socket

        while not self._stop_event.is_set():
            try:
                data, client_address = udp_server_socket.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break

            if self.cb:
                try:
                    data_dict = json.loads(data.decode("utf-8"))
                    for key, value in data_dict.items():
                        if key.startswith("rmkey") and value != 0:
                            self.cb(key)
                except Exception as err:
                    print(err)

            try:
                udp_server_socket.sendto(b"ok", client_address)
            except OSError:
                break

        udp_server_socket.close()
        if self._udp_server_socket is udp_server_socket:
            self._udp_server_socket = None

    def sendTimeout(self) -> bytes:
        """Send a packet to the device."""
        while not self._stop_event.wait(60):
            data = (("""{"port":%s, "timeout":60}""") % (self.Port)).encode('utf-8')
            packet = struct.pack("<I", 20000) + data
            # packet = struct.pack("<HI", len(data) + 4, 20000) + data
            try: 
                resp = self.send_packet(0x6A, packet)
            except Exception as e:
                print(e)

    def _get_bind_ip(self) -> str:
        """Return the local interface IP used to reach this device."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect((self.host[0], self.host[1]))
                return probe.getsockname()[0]
        except OSError:
            return self.LOOPBACK_BIND_IP

    def _ensure_background_workers(self) -> None:
        """Ensure UDP workers are running once."""
        if self.UdpFlag:
            return
        with self._thread_lock:
            if self.UdpFlag:
                return
            self._stop_event.clear()
            self._udp_thread = threading.Thread(
                target=self.startUdpServer,
                name=f"linknlink-udp-{self.mac.hex()}",
                daemon=True,
            )
            self._timeout_thread = threading.Thread(
                target=self.sendTimeout,
                name=f"linknlink-timeout-{self.mac.hex()}",
                daemon=True,
            )
            self._udp_thread.start()
            self._timeout_thread.start()
            self.UdpFlag = True

    def stop_background_workers(self) -> None:
        """Stop UDP background workers and close socket."""
        with self._thread_lock:
            self._stop_event.set()
            if self._udp_server_socket is not None:
                self._udp_server_socket.close()
                self._udp_server_socket = None
            self.UdpFlag = False
    
    def getalldev(self) -> dict:
        """Return the all devices."""
        now = time.monotonic()
        if self._pid_cache is not None and now < self._pid_cache_expires:
            return self._pid_cache

        resp = self._sendV2(0x0b0e, """{"count":16,"index":0,}""".encode('utf-8')) # max 16dev
        try:
            json_string = resp.decode('utf-8')
            json_object = json.loads(json_string)
        except Exception:
            return {}
        # 使用字典推导式创建pid到did的映射
        pid_to_did_map = {}
        for item in json_object['list']:
            pid = item['pid']
            did = item['did']
            if pid in pid_to_did_map:
                pid_to_did_map[pid].append(did)
            else:
                pid_to_did_map[pid] = [did]
        self._pid_cache = pid_to_did_map
        self._pid_cache_expires = now + self.PID_CACHE_TTL
        return pid_to_did_map
    
    def check_sensors(self) -> dict:
        """Return the state of the sensors."""
        self._ensure_background_workers()
        big_dict = {}
        now = time.monotonic()

        if now < self._last_sensor_snapshot_expires:
            return dict(self._last_sensor_snapshot)

        pid_to_did_map = self.getalldev()
        # print(pid_to_did_map)
        for pid in PID_HUMITURE, PID_DOORSENSOR, PID_REMOTE:
            if pid in pid_to_did_map:
                for did in pid_to_did_map[pid]:
                    did_key = (pid, did)
                    cache_entry = self._did_snapshot_cache.get(did_key)
                    if cache_entry and now < cache_entry[0]:
                        big_dict.update(cache_entry[1])
                        continue

                    resp = self._sendV2(0x0b01, ("""{"did":"%s"}"""%(did)).encode('utf-8'))
                    try:
                        json_string = resp.decode('utf-8')
                        json_object = json.loads(json_string)
                    except Exception:
                        continue
                    # print(json_object)
                    self._did_snapshot_cache[did_key] = (
                        now + self.SENSOR_CACHE_TTL,
                        json_object,
                    )
                    big_dict.update(json_object)
        if "envtemp" in big_dict:
            big_dict["envtemp"] = round(float(big_dict["envtemp"])/100, 2)
        if "envhumid" in big_dict:
            big_dict["envhumid"] = round(float(big_dict["envhumid"])/100, 2)

        if big_dict:
            self._last_sensor_snapshot = dict(big_dict)
            self._last_sensor_snapshot_expires = now + self.SENSOR_CACHE_TTL
            return big_dict
        return big_dict

    def check_temperature(self) -> float:
        """Return the temperature."""
        return round(float(self.check_sensors()["envtemp"])/100, 2)

    def check_humidity(self) -> float:
        """Return the humidity."""
        return round(float(self.check_sensors()["envhumid"])/100, 2)
    
    def check_doorsensor(self) -> str:
        """Return the pirDetected."""
        return self.check_sensors()["doorsensor_status"]

    # remote function
    def sweep_frequency(self) -> None:
        """Sweep frequency."""
        self._send(0x19)

    def check_frequency(self) -> bool:
        """Return True if the frequency was identified successfully."""
        resp = self._send(0x1A)
        return resp[0] == 1

    def find_rf_packet(self) -> None:
        """Enter radiofrequency learning mode."""
        self._send(0x1B)

    def cancel_sweep_frequency(self) -> None:
        """Cancel sweep frequency."""
        self._send(0x1E)

    def update(self) -> None:
        """Update device name and lock status."""
        resp = self._send(0x1)
        self.name = resp[0x48:].split(b"\x00")[0].decode()
        self.is_locked = bool(resp[0x87])

    def send_data(self, data: bytes) -> None:
        """Send a code to the device."""
        self._send(0x2, data)

    def enter_learning(self) -> None:
        """Enter infrared learning mode."""
        self._send(0x3)

    def check_data(self) -> bytes:
        """Return the last captured code."""
        return self._send(0x4)
