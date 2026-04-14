# PiPhi TP-Link Kasa Integration

PiPhi integration for TP-Link Kasa devices over the local network.

This runtime uses `python-kasa` for device discovery, polling, and command
execution, and now installs the published Python runtime kit directly from
PyPI.

## What this integration does

- discovers local TP-Link Kasa devices
- supports optional authenticated discovery inputs for devices that require account credentials
- applies and rehydrates PiPhi configs through `/config`, `/configs/sync`, and `/config/sync`
- polls device state on a background loop
- exposes entities, state, events, commands, and UI config endpoints
- delivers telemetry and events to PiPhi Core through `piphi-runtime-kit-python`

## Runtime SDK and testkit

- runtime SDK: `piphi-runtime-kit-python==0.3.1`
- local test helper during development: `piphi-runtime-testkit-python`

The runtime kit is now installed from PyPI. The local testkit path dependency is
only there for repo development and tests.

## Local development

Install dependencies:

```bash
pdm install -G dev
```

Run the runtime:

```bash
pdm run python -m piphi_network_tp_link.app
```

Run tests:

```bash
pdm run pytest -q
```

The integration API defaults to `http://127.0.0.1:3666`.

## Important routes

- `GET /health`
- `POST /discover`
- `GET /entities`
- `GET /state`
- `POST /command`
- `POST /config`
- `POST /configs/sync`
- `POST /config/sync`
- `POST /deconfigure`
- `GET /ui-config`
- `GET /events`
- `GET /manifest.json`

## Discovery notes

Discovery can run without account credentials for many local-network devices.
For models or firmware that require authenticated discovery, the manifest now
supports these optional inputs:

- `username`
- `password`

Those values are meant to be provided by the PiPhi UI, not hardcoded in source
control.

## Polling behavior

Configured devices are polled on a background loop. The current steady-state
polling interval is 30 seconds, with an immediate refresh path during config
apply and some command flows.

That makes the integration gentler on devices than the earlier 10-second loop
while still keeping state reasonably fresh.

## Contract and runtime details

The runtime supports:

- startup auth/config rehydrate via `PIPHI_CONTAINER_ID` and `PIPHI_INTEGRATION_INTERNAL_TOKEN`
- both snapshot sync route shapes, `/configs/sync` and `/config/sync`
- local event storage plus Core event delivery
- telemetry delivery with the published Python runtime kit

## Project layout

- `src/manifest.json` integration manifest
- `src/behaviors.json` optional behavior metadata for PiPhi UI
- `src/piphi_network_tp_link/app.py` FastAPI entrypoint
- `src/piphi_network_tp_link/contract/` PiPhi contract routes
- `src/piphi_network_tp_link/lib/` device and runtime helpers
- `tests/` integration tests using the Python testkit
