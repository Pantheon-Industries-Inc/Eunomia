# `consoles/` — the operator/supervisor/HQ UIs (web stack; each an island)

**Single responsibility:** the live UIs. Each console is an independent app that talks ONLY to
`edge/api/` and knows ONLY the contract. Changing or replacing one touches nothing else.

**Dependency rule:** depends only on `contracts/` (the contract-typed client) + `edge/api/`. Consoles
never import each other's internals; they remain separately deployable islands.

**Web stack: not chosen in Run 0a** (OQ-14; MODULE_MAP open-Q 1 — deferred to the console design).
0a creates the directories + READMEs only.

## Layout (READMEs only in 0a)

| Path | Responsibility |
|---|---|
| `_shared/` | common components + the contract-typed client (so the apps don't reinvent it) — still separately deployable. |
| `site-setup/` | HQ: site WiFi + telemetry endpoint + task-menu (the config the fob pulls). |
| `provisioning/` | bench flash/assign UI; calls the `camera-image` core; captures provisioning facts; runs the per-kit ship-gate. |
| `inventory/` | receiving (receipt capture), box-scan, periodic count. |
| `workforce/` | onboarding, qualify, offboard, observations, fault-logging. |
| `gods-view/` | the live ops dashboard (consumes `contracts/events/`). Exception-first, not live video. |
