"""Regression tests for LinknLink integration fixes."""
from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import types
from types import SimpleNamespace


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
INTEGRATION_DIR = REPO_ROOT / "custom_components" / "linknlink"


def _clear_test_modules() -> None:
    """Remove stub modules between tests."""
    for name in list(sys.modules):
        if name.startswith("custom_components") or name.startswith("homeassistant"):
            sys.modules.pop(name)


def _new_module(name: str, **attrs):
    """Create and register a stub module."""
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _install_common_homeassistant_stubs() -> None:
    """Install minimal Home Assistant stubs needed by the tests."""
    _new_module("homeassistant")
    _new_module(
        "homeassistant.const",
        ATTR_COMMAND="command",
        CONF_HOST="host",
        CONF_MAC="mac",
        CONF_NAME="name",
        CONF_TIMEOUT="timeout",
        CONF_TYPE="type",
        STATE_OFF="off",
        Platform=SimpleNamespace(
            REMOTE="remote",
            SENSOR="sensor",
            BINARY_SENSOR="binary_sensor",
            BUTTON="button",
        ),
    )
    _new_module("homeassistant.core", HomeAssistant=object, callback=lambda func: func)
    _new_module(
        "homeassistant.data_entry_flow",
        AbortFlow=type("AbortFlow", (Exception,), {}),
        FlowResult=dict,
    )

    class ConfigFlow:
        def __init_subclass__(cls, **kwargs):
            return None

        async def async_set_unique_id(self, unique_id, raise_on_progress=True):
            self.unique_id = unique_id

        def _abort_if_unique_id_configured(self, updates=None):
            self.updates = updates

        def async_abort(self, reason):
            return {"type": "abort", "reason": reason}

        def async_show_form(self, **kwargs):
            return kwargs

        def async_create_entry(self, **kwargs):
            return kwargs

    class ConfigSubentryFlow:
        def async_show_form(self, **kwargs):
            return kwargs

        def async_show_progress(self, **kwargs):
            return kwargs

        def async_show_progress_done(self, **kwargs):
            return kwargs

        def async_show_menu(self, **kwargs):
            return kwargs

        def async_create_entry(self, **kwargs):
            return kwargs

        def async_update_and_abort(self, *args, **kwargs):
            return kwargs

    _new_module(
        "homeassistant.config_entries",
        ConfigEntry=object,
        ConfigFlow=ConfigFlow,
        ConfigSubentryFlow=ConfigSubentryFlow,
        SubentryFlowResult=dict,
        SOURCE_RECONFIGURE="reconfigure",
    )
    _new_module("homeassistant.components")
    _new_module("homeassistant.components.dhcp")
    _new_module(
        "homeassistant.helpers",
        config_validation=SimpleNamespace(
            positive_int=int,
            ensure_list=lambda value: value if isinstance(value, list) else [value],
            string=lambda value: str(value),
            boolean=lambda value: bool(value),
            multi_select=lambda options: lambda value: value,
        ),
    )
    _new_module(
        "homeassistant.helpers.config_validation",
        positive_int=int,
        ensure_list=lambda value: value if isinstance(value, list) else [value],
        string=lambda value: str(value),
        boolean=lambda value: bool(value),
        multi_select=lambda options: lambda value: value,
    )


def _install_common_package_stubs() -> None:
    """Install minimal package stubs for relative imports."""
    custom_components = _new_module("custom_components")
    custom_components.__path__ = [str(REPO_ROOT / "custom_components")]
    package = _new_module("custom_components.linknlink")
    package.__path__ = [str(INTEGRATION_DIR)]


def _load_module(module_name: str, file_name: str, predefs: dict | None = None):
    """Load a module from the integration directory."""
    spec = importlib.util.spec_from_file_location(module_name, INTEGRATION_DIR / file_name)
    module = importlib.util.module_from_spec(spec)
    if predefs:
        module.__dict__.update(predefs)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_dhcp_flow_calls_async_set_device():
    _clear_test_modules()
    _install_common_homeassistant_stubs()
    _install_common_package_stubs()

    class NetworkTimeoutError(Exception):
        pass

    class AuthenticationError(Exception):
        pass

    class LinknLinkException(Exception):
        pass

    vendor = _new_module("custom_components.linknlink.vendor")
    llk = _new_module("custom_components.linknlink.vendor.linknlink", Device=object)
    llk.hello = lambda host: SimpleNamespace(
        type="EREMOTE",
        devtype=0xAC99,
        mac=bytes.fromhex("001122334455"),
        name="Hub",
        model="EREMOTE",
        host=(host, 80),
        timeout=5,
    )
    vendor.linknlink = llk
    _new_module(
        "custom_components.linknlink.vendor.linknlink.exceptions",
        AuthenticationError=AuthenticationError,
        LinknLinkException=LinknLinkException,
        NetworkTimeoutError=NetworkTimeoutError,
    )
    _new_module(
        "custom_components.linknlink.const",
        COMMAND_TYPE_IR="ir",
        COMMAND_TYPE_RF="rf",
        CONF_COMMAND_TYPE="command_type",
        CONF_COMMANDS="commands",
        DEFAULT_TIMEOUT=5,
        DEVICE_TYPES={"EREMOTE"},
        DOMAIN="linknlink",
        SUBENTRY_TYPE_DEVICE="controlled_device",
    )
    _new_module("custom_components.linknlink.coordinator", LinknLinkCoordinator=object)
    _new_module("custom_components.linknlink.helpers", data_packet=lambda code: code)
    _new_module(
        "custom_components.linknlink.learn",
        async_learn_ir=lambda *_args, **_kwargs: None,
        async_learn_rf=lambda *_args, **_kwargs: None,
        async_sweep_rf=lambda *_args, **_kwargs: None,
    )

    module = _load_module(
        "custom_components.linknlink.config_flow",
        "config_flow.py",
        predefs={"DhcpServiceInfo": object},
    )

    class FakeHass:
        async def async_add_executor_job(self, function, *args, **kwargs):
            return function(*args, **kwargs)

    flow = module.LinknlinkConfigFlow()
    flow.hass = FakeHass()
    called = {}

    async def async_set_device(device):
        called["device"] = device

    async def async_step_auth():
        return {"type": "auth"}

    flow.async_set_device = async_set_device
    flow.async_step_auth = async_step_auth

    result = asyncio.run(
        flow.async_step_dhcp(
            SimpleNamespace(ip="192.168.1.2", macaddress="00:11:22:33:44:55")
        )
    )

    assert called["device"].host[0] == "192.168.1.2"
    assert result == {"type": "auth"}


def test_coordinator_stored_before_refresh():
    _clear_test_modules()
    _install_common_package_stubs()
    _new_module("homeassistant")
    _new_module("homeassistant.config_entries", ConfigEntry=object)
    _new_module("homeassistant.const", CONF_MAC="mac")
    _new_module("homeassistant.core", HomeAssistant=object)
    _new_module(
        "homeassistant.exceptions",
        ConfigEntryNotReady=type("ConfigEntryNotReady", (Exception,), {}),
    )

    call_order: list[str] = []

    class FakeCoordinator:
        def __init__(self, hass, mac):
            self.hass = hass
            self.mac = mac
            self.api = SimpleNamespace(type="EREMOTE")
            self.config_entry = SimpleNamespace(data={"mac": mac})

        async def async_setup(self):
            call_order.append("setup")
            return True

        async def async_config_entry_first_refresh(self):
            call_order.append("refresh")
            assert self.hass.data["linknlink"]["entry-1"] is self

    _new_module(
        "custom_components.linknlink.const",
        DOMAIN="linknlink",
        get_domains=lambda device_type: {"remote"} if device_type == "EREMOTE" else set(),
    )
    _new_module("custom_components.linknlink.coordinator", LinknLinkCoordinator=FakeCoordinator)

    module = _load_module("custom_components.linknlink", "__init__.py")

    class FakeConfigEntries:
        async def async_forward_entry_setups(self, entry, domains):
            call_order.append("forward")
            assert entry.hass.data["linknlink"][entry.entry_id] is coordinator

    class FakeEntry:
        def __init__(self, hass):
            self.hass = hass
            self.entry_id = "entry-1"
            self.data = {"mac": "001122334455"}

        def add_update_listener(self, listener):
            return listener

        def async_on_unload(self, _listener):
            return None

    hass = SimpleNamespace(data={}, config_entries=FakeConfigEntries())
    entry = FakeEntry(hass)
    coordinator = None

    original_cls = module.LinknLinkCoordinator

    class TrackingCoordinator(original_cls):
        def __init__(self, hass, mac):
            nonlocal coordinator
            super().__init__(hass, mac)
            coordinator = self

    module.LinknLinkCoordinator = TrackingCoordinator

    assert asyncio.run(module.async_setup_entry(hass, entry)) is True
    assert hass.data["linknlink"]["entry-1"] is coordinator
    assert call_order == ["setup", "refresh", "forward"]


def test_learn_result_with_missing_pending_command_returns_error():
    _clear_test_modules()
    _install_common_homeassistant_stubs()
    _install_common_package_stubs()

    class NetworkTimeoutError(Exception):
        pass

    class AuthenticationError(Exception):
        pass

    class LinknLinkException(Exception):
        pass

    vendor = _new_module("custom_components.linknlink.vendor")
    vendor.linknlink = _new_module("custom_components.linknlink.vendor.linknlink", Device=object)
    _new_module(
        "custom_components.linknlink.vendor.linknlink.exceptions",
        AuthenticationError=AuthenticationError,
        LinknLinkException=LinknLinkException,
        NetworkTimeoutError=NetworkTimeoutError,
    )
    _new_module(
        "custom_components.linknlink.const",
        COMMAND_TYPE_IR="ir",
        COMMAND_TYPE_RF="rf",
        CONF_COMMAND_TYPE="command_type",
        CONF_COMMANDS="commands",
        DEFAULT_TIMEOUT=5,
        DEVICE_TYPES={"EREMOTE"},
        DOMAIN="linknlink",
        SUBENTRY_TYPE_DEVICE="controlled_device",
    )
    _new_module("custom_components.linknlink.coordinator", LinknLinkCoordinator=object)
    _new_module("custom_components.linknlink.helpers", data_packet=lambda code: code)
    _new_module(
        "custom_components.linknlink.learn",
        async_learn_ir=lambda *_args, **_kwargs: None,
        async_learn_rf=lambda *_args, **_kwargs: None,
        async_sweep_rf=lambda *_args, **_kwargs: None,
    )

    module = _load_module(
        "custom_components.linknlink.config_flow",
        "config_flow.py",
        predefs={"DhcpServiceInfo": object},
    )

    flow = module.ControlledDeviceSubentryFlowHandler()
    seen = {}

    async def run_test():
        flow._learn_task = asyncio.get_running_loop().create_future()
        flow._learn_task.set_result("code")
        flow._pending_command = None
        flow._commands = {}

        async def async_step_learn(user_input=None, errors=None):
            seen["errors"] = errors
            return {"type": "form", "errors": errors}

        flow.async_step_learn = async_step_learn
        return await flow.async_step_learn_result()

    result = asyncio.run(run_test())

    assert result == {"type": "form", "errors": {"base": "learn_failed"}}
    assert seen["errors"] == {"base": "learn_failed"}
    assert flow._commands == {}
    assert flow._pending_command is None
    assert flow._learn_task is None


def test_send_command_initializes_missing_toggle_flags():
    _clear_test_modules()
    _install_common_package_stubs()
    _new_module("homeassistant")
    _new_module("homeassistant.config_entries", ConfigEntry=object)
    _new_module("homeassistant.const", ATTR_COMMAND="command", STATE_OFF="off")
    _new_module("homeassistant.core", HomeAssistant=object, callback=lambda func: func)
    _new_module(
        "homeassistant.components",
        persistent_notification=SimpleNamespace(
            async_create=lambda *args, **kwargs: None,
            async_dismiss=lambda *args, **kwargs: None,
        ),
    )
    _new_module(
        "homeassistant.components.remote",
        ATTR_ALTERNATIVE="alternative",
        ATTR_COMMAND_TYPE="command_type",
        ATTR_DELAY_SECS="delay_secs",
        ATTR_DEVICE="device",
        ATTR_NUM_REPEATS="num_repeats",
        DEFAULT_DELAY_SECS=0,
        DOMAIN="remote",
        SERVICE_DELETE_COMMAND="delete_command",
        SERVICE_LEARN_COMMAND="learn_command",
        SERVICE_SEND_COMMAND="send_command",
        RemoteEntity=type("RemoteEntity", (), {}),
        RemoteEntityFeature=SimpleNamespace(LEARN_COMMAND=1, DELETE_COMMAND=2),
    )
    _new_module(
        "homeassistant.helpers",
        config_validation=SimpleNamespace(
            ensure_list=lambda value: value if isinstance(value, list) else [value],
            string=lambda value: str(value),
            boolean=lambda value: bool(value),
        ),
    )
    _new_module(
        "homeassistant.helpers.config_validation",
        ensure_list=lambda value: value if isinstance(value, list) else [value],
        string=lambda value: str(value),
        boolean=lambda value: bool(value),
    )
    _new_module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    _new_module("homeassistant.helpers.restore_state", RestoreEntity=type("RestoreEntity", (), {}))
    _new_module("homeassistant.helpers.storage", Store=object)
    _new_module("custom_components.linknlink.const", DOMAIN="linknlink")
    _new_module("custom_components.linknlink.helpers", data_packet=lambda code: code.encode())
    _new_module("custom_components.linknlink.learn")
    _new_module("custom_components.linknlink.coordinator", LinknLinkCoordinator=object)

    class LinknLinkEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator
            self.hass = coordinator.hass
            self.entity_id = "remote.test"

        async def async_added_to_hass(self):
            return None

        def async_write_ha_state(self):
            return None

    _new_module("custom_components.linknlink.entity", LinknLinkEntity=LinknLinkEntity)
    _new_module(
        "custom_components.linknlink.vendor.linknlink.exceptions",
        AuthorizationError=type("AuthorizationError", (Exception,), {}),
        LinknLinkException=type("LinknLinkException", (Exception,), {}),
        NetworkTimeoutError=type("NetworkTimeoutError", (Exception,), {}),
    )

    module = _load_module("custom_components.linknlink.remote", "remote.py")

    class FakeStore:
        def __init__(self):
            self.saved = []

        async def async_load(self):
            return {}

        async def async_save(self, data):
            self.saved.append(data)

        def async_delay_save(self, callback, delay):
            self.saved.append((callback(), delay))

    class FakeCoordinator:
        def __init__(self):
            self.hass = object()
            self.api = SimpleNamespace(mac=bytes.fromhex("001122334455"), send_data=lambda code: code)
            self.sent = []

        async def async_request(self, function, code):
            self.sent.append(function(code))

    coordinator = FakeCoordinator()
    remote = module.LinknLinkRemote(coordinator, FakeStore(), FakeStore())
    remote._storage_loaded = True
    remote._codes = {"tv": {"power": ["first", "second"]}}
    remote._flags = {}

    asyncio.run(
        remote.async_send_command(
            ["power"], device="tv", num_repeats=1, delay_secs=0
        )
    )

    assert coordinator.sent == [b"first"]
    assert remote._flags["tv"] == 1
    assert remote._flag_storage.saved == [({"tv": 1}, module.FLAG_SAVE_DELAY)]
