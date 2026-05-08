"""Constants for the linknlink integration."""
from homeassistant.const import Platform

DOMAIN = "linknlink"

PLATFORM_INFRARED = "infrared"
PLATFORM_RADIO_FREQUENCY = "radio_frequency"

DOMAINS_AND_TYPES = {
    Platform.REMOTE: {"EHUB", "EHOME_RF_HA", "EREMOTE"},
    Platform.SENSOR: {"EHUB", "ETHS"},
    Platform.BINARY_SENSOR: {"EHUB", "EMOTION"},
    PLATFORM_INFRARED: {"EHUB", "EREMOTE"},
    PLATFORM_RADIO_FREQUENCY: {"EHUB", "EHOME_RF_HA", "EREMOTE"},
}
DEVICE_TYPES = set.union(*DOMAINS_AND_TYPES.values())

DEFAULT_PORT = 80
DEFAULT_TIMEOUT = 5


def get_domains(device_type: str) -> set[str]:
    """Return the domains available for a device type."""
    return {d for d, t in DOMAINS_AND_TYPES.items() if device_type in t}