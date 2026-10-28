# Resolve `.local` Names on the Host

## Goal

The bridge reaches a rig named by its mDNS name, e.g. `ws://stepit.local:9090`.

## Decisions

**The host resolves, the container gets the address.** The bridge's container has no mDNS, so `stepit.local` did not resolve in it, and the voice said "cannot reach rosbridge at ws://stepit.local:9090" while the rig was running. `dock.sh` finds every `.local` name in the robot file, `VOICEBRIDGE_ROSBRIDGE`, `VOICEBRIDGE_UPSTREAM` and `VOICEBRIDGE_LLM_URL`, and resolves it with `getent` on the host.

**`--add-host` for `bridge` and `shell`, an extra compose file for `serve`.** Compose cannot take a list from a variable, so `serve` writes the bridge's `extra_hosts` into a temporary compose file merged with `docker/compose.yaml`.

**A name that does not resolve stops the start.** `Cannot resolve <name>: is the machine on the network?` is clearer than a bridge that cannot reach the rig.

## Open Items

**The address is fixed at start.** Our rig answers on two addresses, `.24` and `.25`, and `stepit.local` resolves to either. If the rig drops the one the bridge has, restart the bridge.
