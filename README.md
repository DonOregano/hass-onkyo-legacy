# Onkyo (legacy) for Home Assistant

A custom integration for older Onkyo and Integra network receivers (roughly
pre-2011, e.g. the TX-NR3007) that stopped working with the built-in
[Onkyo integration](https://www.home-assistant.io/integrations/onkyo/).

## Why

Since Home Assistant 2024.9 the built-in integration "interviews" the receiver
with a UDP discovery query (`!xECNQSTN` on port 60128) before it creates any
entities, also when the host is entered manually. Older receivers speak eISCP
over TCP just fine, but never answer that UDP query, so setup times out
([home-assistant/core#130250](https://github.com/home-assistant/core/issues/130250)).

This integration is a fork of the built-in one (Home Assistant 2026.11.2) that
skips the interview and connects directly over TCP. The media players, input
sources, listening modes, zones and push updates work like the built-in integration.

Differences from the built-in integration:

- No discovery: you enter the host, the model name (used only for naming,
  since legacy receivers cannot report it) and the port (default 60128).
- Commands are spaced 50 ms apart, because legacy receivers silently drop
  commands that arrive too close together.
- Audio/video information is not queried: legacy receivers answer these
  with an empty parameter.
- The receiver is identified by its MAC address when Home Assistant can see it
  in its ARP table (same subnet), otherwise by the host.
- The HDMI output action is `onkyo_legacy.select_hdmi_output`.

It runs under its own domain (`onkyo_legacy`), so it can be installed next to
the built-in integration.

## Requirements

- Home Assistant 2026.11 or newer.
- Network control enabled on the receiver ("Network Standby" on, so it can be
  turned on over the network).
- TCP port 60128 reachable from Home Assistant to the receiver. Unlike the
  built-in integration, UDP and the same subnet are not required.

## Installation

### HACS

Add this repository as a custom repository (type: Integration) in HACS,
install "Onkyo (legacy)" and restart Home Assistant.

### Manual

Copy `custom_components/onkyo_legacy` into the `custom_components` directory of
your Home Assistant configuration and restart Home Assistant.

Then add the integration under **Settings → Devices & services → Add integration →
Onkyo (legacy)**.

## Known limitations

- Volume up/down steps by 0.5 dB, like the remote. The receiver reports volume
  in whole steps only, so Home Assistant's volume level changes on every
  second press.

## Tested receivers

| Model     | Notes |
|-----------|-------|
| TX-NR3007 | Power, volume, mute, input, listening mode, HDMI output and zone 2 power tested. Zones 2–4 found. |

## License

Apache License 2.0. Based on the Onkyo integration from
[Home Assistant core](https://github.com/home-assistant/core) by its authors.
