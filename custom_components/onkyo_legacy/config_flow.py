"""Config flow for Onkyo (legacy)."""

from collections.abc import Mapping
import logging
from typing import Any, override

from aioonkyo import ReceiverInfo
import probatio

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_MODEL, CONF_PORT
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    Selector,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from . import OnkyoConfigEntry
from .const import (
    DEFAULT_MODEL,
    DEFAULT_PORT,
    DOMAIN,
    OPTION_INPUT_SOURCES,
    OPTION_LISTENING_MODES,
    OPTION_MAX_VOLUME,
    OPTION_MAX_VOLUME_DEFAULT,
    OPTION_VOLUME_RESOLUTION,
    OPTION_VOLUME_RESOLUTION_DEFAULT,
    VOLUME_RESOLUTION_ALLOWED,
    InputSource,
    ListeningMode,
)
from .receiver import async_get_identifier, async_probe
from .util import get_meaning

_LOGGER = logging.getLogger(__name__)

INPUT_SOURCES_DEFAULT: list[InputSource] = []
LISTENING_MODES_DEFAULT: list[ListeningMode] = []
INPUT_SOURCES_ALL_MEANINGS = {
    get_meaning(input_source): input_source for input_source in InputSource
}
LISTENING_MODES_ALL_MEANINGS = {
    get_meaning(listening_mode): listening_mode for listening_mode in ListeningMode
}
STEP_USER_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST): str,
        probatio.Required(CONF_MODEL, default=DEFAULT_MODEL): str,
        probatio.Required(CONF_PORT, default=DEFAULT_PORT): probatio.All(
            probatio.Coerce(int), probatio.Range(min=1, max=65535)
        ),
    }
)
STEP_RECONFIGURE_SCHEMA = probatio.Schema(
    {
        probatio.Required(OPTION_VOLUME_RESOLUTION): probatio.In(
            VOLUME_RESOLUTION_ALLOWED
        ),
    }
)
STEP_CONFIGURE_SCHEMA = STEP_RECONFIGURE_SCHEMA.extend(
    {
        probatio.Required(OPTION_INPUT_SOURCES): SelectSelector(
            SelectSelectorConfig(
                options=list(INPUT_SOURCES_ALL_MEANINGS),
                multiple=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        probatio.Required(OPTION_LISTENING_MODES): SelectSelector(
            SelectSelectorConfig(
                options=list(LISTENING_MODES_ALL_MEANINGS),
                multiple=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
    }
)


class OnkyoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Onkyo config flow."""

    _receiver_info: ReceiverInfo

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual device entry."""
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            _LOGGER.debug("Config flow user: %s:%s", host, port)
            try:
                await async_probe(host, port)
            except TimeoutError:
                _LOGGER.warning("Timed out probing: %s:%s", host, port)
                errors["base"] = "cannot_connect"
            except OSError:
                _LOGGER.warning("Could not connect to: %s:%s", host, port)
                errors["base"] = "cannot_connect"
            else:
                if self.source == SOURCE_RECONFIGURE:
                    identifier = self._get_reconfigure_entry().unique_id
                    assert identifier is not None
                else:
                    identifier = await async_get_identifier(self.hass, host)
                    await self.async_set_unique_id(identifier, raise_on_progress=False)
                    self._abort_if_unique_id_configured(
                        updates={CONF_HOST: host, CONF_PORT: port}
                    )

                self._receiver_info = ReceiverInfo(
                    host=host,
                    ip=host,
                    port=port,
                    model_name=user_input[CONF_MODEL],
                    identifier=identifier,
                )

                return await self.async_step_configure_receiver()

        suggested_values = user_input
        if suggested_values is None and self.source == SOURCE_RECONFIGURE:
            entry_data = self._get_reconfigure_entry().data
            suggested_values = {
                CONF_HOST: entry_data[CONF_HOST],
                CONF_MODEL: entry_data[CONF_MODEL],
                CONF_PORT: entry_data[CONF_PORT],
            }

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, suggested_values
            ),
            errors=errors,
        )

    async def async_step_configure_receiver(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the configuration of a single receiver."""
        errors = {}

        reconfigure_entry = None
        schema = STEP_CONFIGURE_SCHEMA
        if self.source == SOURCE_RECONFIGURE:
            schema = STEP_RECONFIGURE_SCHEMA
            reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            volume_resolution = user_input[OPTION_VOLUME_RESOLUTION]

            if reconfigure_entry is not None:
                entry_options = reconfigure_entry.options
                result = self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data={
                        CONF_HOST: self._receiver_info.host,
                        CONF_MODEL: self._receiver_info.model_name,
                        CONF_PORT: self._receiver_info.port,
                    },
                    options={
                        **entry_options,
                        OPTION_VOLUME_RESOLUTION: volume_resolution,
                    },
                )

                _LOGGER.debug("Reconfigured receiver, result: %s", result)
                return result

            input_source_meanings: list[str] = user_input[OPTION_INPUT_SOURCES]
            if not input_source_meanings:
                errors[OPTION_INPUT_SOURCES] = "empty_input_source_list"

            listening_modes: list[str] = user_input[OPTION_LISTENING_MODES]
            if not listening_modes:
                errors[OPTION_LISTENING_MODES] = "empty_listening_mode_list"

            if not errors:
                input_sources_store: dict[str, str] = {}
                for input_source_meaning in input_source_meanings:
                    input_source = INPUT_SOURCES_ALL_MEANINGS[input_source_meaning]
                    input_sources_store[input_source.value] = input_source_meaning

                listening_modes_store: dict[str, str] = {}
                for listening_mode_meaning in listening_modes:
                    listening_mode = LISTENING_MODES_ALL_MEANINGS[
                        listening_mode_meaning
                    ]
                    listening_modes_store[listening_mode.value] = listening_mode_meaning

                result = self.async_create_entry(
                    title=self._receiver_info.model_name,
                    data={
                        CONF_HOST: self._receiver_info.host,
                        CONF_MODEL: self._receiver_info.model_name,
                        CONF_PORT: self._receiver_info.port,
                    },
                    options={
                        OPTION_VOLUME_RESOLUTION: volume_resolution,
                        OPTION_MAX_VOLUME: OPTION_MAX_VOLUME_DEFAULT,
                        OPTION_INPUT_SOURCES: input_sources_store,
                        OPTION_LISTENING_MODES: listening_modes_store,
                    },
                )

                _LOGGER.debug("Configured receiver, result: %s", result)
                return result

        _LOGGER.debug("Configuring receiver, info: %s", self._receiver_info)

        suggested_values = user_input
        if suggested_values is None:
            if reconfigure_entry is None:
                suggested_values = {
                    OPTION_VOLUME_RESOLUTION: OPTION_VOLUME_RESOLUTION_DEFAULT,
                    OPTION_INPUT_SOURCES: [
                        get_meaning(input_source)
                        for input_source in INPUT_SOURCES_DEFAULT
                    ],
                    OPTION_LISTENING_MODES: [
                        get_meaning(listening_mode)
                        for listening_mode in LISTENING_MODES_DEFAULT
                    ],
                }
            else:
                entry_options = reconfigure_entry.options
                suggested_values = {
                    OPTION_VOLUME_RESOLUTION: entry_options[OPTION_VOLUME_RESOLUTION],
                }

        return self.async_show_form(
            step_id="configure_receiver",
            data_schema=self.add_suggested_values_to_schema(schema, suggested_values),
            errors=errors,
            description_placeholders={
                "name": f"{self._receiver_info.model_name} ({self._receiver_info.host})"
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of the receiver."""
        _LOGGER.debug("Config flow start reconfigure")
        return await self.async_step_user()

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: OnkyoConfigEntry) -> OptionsFlowWithReload:
        """Return the options flow."""
        return OnkyoOptionsFlowHandler()


OPTIONS_STEP_INIT_SCHEMA = probatio.Schema(
    {
        probatio.Required(OPTION_MAX_VOLUME): NumberSelector(
            NumberSelectorConfig(min=1, max=100, mode=NumberSelectorMode.BOX)
        ),
        probatio.Required(OPTION_INPUT_SOURCES): SelectSelector(
            SelectSelectorConfig(
                options=list(INPUT_SOURCES_ALL_MEANINGS),
                multiple=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        probatio.Required(OPTION_LISTENING_MODES): SelectSelector(
            SelectSelectorConfig(
                options=list(LISTENING_MODES_ALL_MEANINGS),
                multiple=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
    }
)


class OnkyoOptionsFlowHandler(OptionsFlowWithReload):
    """Handle an options flow for Onkyo."""

    _data: dict[str, Any]
    _input_sources: dict[InputSource, str]
    _listening_modes: dict[ListeningMode, str]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors = {}

        entry_options: Mapping[str, Any] = self.config_entry.options
        entry_options = {
            OPTION_LISTENING_MODES: {
                listening_mode.value: get_meaning(listening_mode)
                for listening_mode in LISTENING_MODES_DEFAULT
            },
            **entry_options,
        }

        if user_input is not None:
            input_source_meanings: list[str] = user_input[OPTION_INPUT_SOURCES]
            if not input_source_meanings:
                errors[OPTION_INPUT_SOURCES] = "empty_input_source_list"

            listening_mode_meanings: list[str] = user_input[OPTION_LISTENING_MODES]
            if not listening_mode_meanings:
                errors[OPTION_LISTENING_MODES] = "empty_listening_mode_list"

            if not errors:
                self._input_sources = {}
                for input_source_meaning in input_source_meanings:
                    input_source = INPUT_SOURCES_ALL_MEANINGS[input_source_meaning]
                    input_source_name = entry_options[OPTION_INPUT_SOURCES].get(
                        input_source.value, input_source_meaning
                    )
                    self._input_sources[input_source] = input_source_name

                self._listening_modes = {}
                for listening_mode_meaning in listening_mode_meanings:
                    listening_mode = LISTENING_MODES_ALL_MEANINGS[
                        listening_mode_meaning
                    ]
                    listening_mode_name = entry_options[OPTION_LISTENING_MODES].get(
                        listening_mode.value, listening_mode_meaning
                    )
                    self._listening_modes[listening_mode] = listening_mode_name

                self._data = {
                    OPTION_VOLUME_RESOLUTION: entry_options[OPTION_VOLUME_RESOLUTION],
                    OPTION_MAX_VOLUME: user_input[OPTION_MAX_VOLUME],
                }

                return await self.async_step_names()

        suggested_values = user_input
        if suggested_values is None:
            suggested_values = {
                OPTION_MAX_VOLUME: entry_options[OPTION_MAX_VOLUME],
                OPTION_INPUT_SOURCES: [
                    get_meaning(InputSource(input_source))
                    for input_source in entry_options[OPTION_INPUT_SOURCES]
                ],
                OPTION_LISTENING_MODES: [
                    get_meaning(ListeningMode(listening_mode))
                    for listening_mode in entry_options[OPTION_LISTENING_MODES]
                ],
            }

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_STEP_INIT_SCHEMA, suggested_values
            ),
            errors=errors,
        )

    async def async_step_names(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure names."""
        if user_input is not None:
            input_sources_store: dict[str, str] = {}
            for input_source_meaning, input_source_name in user_input[
                OPTION_INPUT_SOURCES
            ].items():
                input_source = INPUT_SOURCES_ALL_MEANINGS[input_source_meaning]
                input_sources_store[input_source.value] = input_source_name

            listening_modes_store: dict[str, str] = {}
            for listening_mode_meaning, listening_mode_name in user_input[
                OPTION_LISTENING_MODES
            ].items():
                listening_mode = LISTENING_MODES_ALL_MEANINGS[listening_mode_meaning]
                listening_modes_store[listening_mode.value] = listening_mode_name

            return self.async_create_entry(
                data={
                    **self._data,
                    OPTION_INPUT_SOURCES: input_sources_store,
                    OPTION_LISTENING_MODES: listening_modes_store,
                }
            )

        input_sources_schema_dict: dict[Any, Selector] = {}
        for input_source, input_source_name in self._input_sources.items():
            input_sources_schema_dict[
                probatio.Required(get_meaning(input_source), default=input_source_name)
            ] = TextSelector()

        listening_modes_schema_dict: dict[Any, Selector] = {}
        for listening_mode, listening_mode_name in self._listening_modes.items():
            listening_modes_schema_dict[
                probatio.Required(
                    get_meaning(listening_mode), default=listening_mode_name
                )
            ] = TextSelector()

        return self.async_show_form(
            step_id="names",
            data_schema=probatio.Schema(
                {
                    probatio.Required(OPTION_INPUT_SOURCES): section(
                        probatio.Schema(input_sources_schema_dict)
                    ),
                    probatio.Required(OPTION_LISTENING_MODES): section(
                        probatio.Schema(listening_modes_schema_dict)
                    ),
                }
            ),
        )
