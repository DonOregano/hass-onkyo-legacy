"""The Onkyo (legacy) component."""

from dataclasses import dataclass
import logging

from aioonkyo import ReceiverInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MODEL, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    OPTION_INPUT_SOURCES,
    OPTION_LISTENING_MODES,
    InputSource,
    ListeningMode,
)
from .coordinator import ChannelMutingCoordinator
from .receiver import ReceiverManager, async_probe
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.SWITCH]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class OnkyoData:
    """Config Entry data."""

    manager: ReceiverManager
    sources: dict[InputSource, str]
    sound_modes: dict[ListeningMode, str]
    channel_muting_coordinator: ChannelMutingCoordinator


type OnkyoConfigEntry = ConfigEntry[OnkyoData]


async def async_setup(hass: HomeAssistant, _: ConfigType) -> bool:
    """Set up Onkyo component."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OnkyoConfigEntry) -> bool:
    """Set up the Onkyo config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]

    try:
        await async_probe(host, port)
    except TimeoutError as exc:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="probe_timeout",
            translation_placeholders={"host": host},
        ) from exc
    except OSError as exc:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"host": host},
        ) from exc

    # Legacy receivers cannot be interviewed, so the info comes from the entry
    assert entry.unique_id is not None
    info = ReceiverInfo(
        host=host,
        ip=host,
        port=port,
        model_name=entry.data[CONF_MODEL],
        identifier=entry.unique_id,
    )

    manager = ReceiverManager(hass, entry, info)

    sources_store: dict[str, str] = entry.options[OPTION_INPUT_SOURCES]
    sources = {InputSource(k): v for k, v in sources_store.items()}

    sound_modes_store: dict[str, str] = entry.options.get(OPTION_LISTENING_MODES, {})
    sound_modes = {ListeningMode(k): v for k, v in sound_modes_store.items()}

    channel_muting_coordinator = ChannelMutingCoordinator(hass, entry, manager)

    entry.runtime_data = OnkyoData(
        manager, sources, sound_modes, channel_muting_coordinator
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if error := await manager.start():
        try:
            await error
        except OSError as exc:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"host": host},
            ) from exc

    return True


async def async_unload_entry(hass: HomeAssistant, entry: OnkyoConfigEntry) -> bool:
    """Unload Onkyo config entry."""
    entry.runtime_data.manager.start_unloading()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
