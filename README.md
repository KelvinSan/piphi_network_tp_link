# PiPhi TP-Link Kasa Integration

Local API integration for TP-Link Kasa devices, aligned with PiPhi integration contract.

## Includes

- `manifest.json` and `behaviors.json`
- Required contract endpoints:
  - `/health`
  - `/discover`
  - `/entities`
  - `/state`
  - `/command`
  - `/config`
  - `/configs/sync`
  - `/config/sync`
  - `/deconfigure`
  - `/ui-config`
  - `/events`
  - `/manifest.json`
- Runtime startup config rehydrate via:
  - `PIPHI_CONTAINER_ID`
  - `PIPHI_INTEGRATION_INTERNAL_TOKEN`
- `python-kasa` discovery + state polling + command execution

## Run

```bash
cd /home/kelvinfor3xzorin/Documents/PiPhi/piphi_network_tp_link
pdm install
pdm run python -m piphi_network_tp_link.app
```

Integration API defaults to `http://127.0.0.1:3666`.
