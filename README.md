# Solar EV Studio — Home Assistant integration

A real `custom_components/solar_ev_studio` integration with a Python charging controller, a Devices & services entry, a solar-mode switch, a status sensor, and an administrator-only **Solar EV Studio** sidebar panel at `/solar-ev-studio`.

The Studio edits the integration's own settings. It does not compile or rewrite native automations. All physical entities, units, power directions, current steps, limits, sunlight model parameters, charger state names, freshness limits and timing controls are editable in the UI and validated again on the server. Settings are persisted in the Home Assistant config entry. Learned light calibration, enabled state and pending stop requests use Home Assistant's supported Store API.

## Defaults

Currents: **6, 8, 10, 13, 16, 20, 24, 32 A**. Maximum: **32 A**. Grid import and battery discharge tolerances: **500 W each**, including their urgent triggers. Starts paused after first installation.

Every amp change follows **stop → confirm off → write current → confirm current → wait → recheck conditions → start**. Missing off acknowledgement prevents the current write. A rejected current setting or changed conditions prevent restart. The timeout and settling settings are editable; this ordering is mandatory.

The controller probes higher currents to discover solar production that a demand-limited inverter is holding back. Light predicts whether to use the shorter probe interval, while a slower probe runs even without increased light. Measured PV, EV power, grid power, battery power and changes in house load determine whether to keep the higher current. This is a single-phase controller using a switch plus a number entity for current. Brief grid/battery draw can occur during reporting and device response delays.

## Install on another Home Assistant

1. Copy the complete `custom_components/solar_ev_studio` folder into Home Assistant's `custom_components` directory.
2. Restart Home Assistant.
3. Add **Solar EV Studio** under Settings → Devices & services → Add integration.
4. Open **Solar EV Studio** from the sidebar and select the correct entities and units. Defaults target the original installation and must be reviewed on another instance.
5. Save, then enable solar charging.

Saving validates all settings, pauses the controller, confirms the old and newly selected charger switches are off, then updates the config entry as a single settings object. Failed stop attempts are retained for retries, including across restarts. Stale browser revisions are rejected. The controller runs independently of the browser.

On activation, the integration disables the earlier Solar EV master helper and its three known controller automations. It repeats that handover after Home Assistant restarts if solar mode was enabled. It refuses to operate if the legacy controls are subsequently enabled again. The old automations are retained as a backup, not used as the integration's backend.

To return to the previous controller, first disable solar mode and disable the Solar EV Studio integration, confirm charging is off, then restore the earlier automations from the saved backup. Never run both controllers together.

## Validation

The Python decision engine passes 41 charging scenarios inherited from the deployed controller. Actuator tests cover normal sequencing, failure to acknowledge stop, failure to acknowledge current, changing solar conditions and disable requests during an adjustment. Server settings validation rejects invalid current steps, units, mappings and timing combinations. The Studio preview exercises integration save and enable commands with simulated responses. Live installation verification is recorded separately in `installation.json` when complete.

No full Home Assistant test environment is bundled. Unit tests use lightweight HA doubles for actuator checks. A daylight charging trial at the new upper currents remains a real-world verification step. Home Assistant or charger/cloud communication failure can prevent a physical command from taking effect.

`build.mjs` generates the shared form and settings metadata using the earlier Studio source one directory above. The packaged custom component itself has no Node.js dependency. `preview.html` requires a local HTTP server and uses simulated readings only.

Implementation references: [Home Assistant config flows](https://developers.home-assistant.io/docs/core/integration/config_flow/) and the installed Avatar Studio panel structure.
