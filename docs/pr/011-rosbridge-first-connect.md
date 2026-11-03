# Connected Before the First Command

## Goal

The first command after the voice started failed: "I could not read the outputs of the robot: cannot reach rosbridge at ws://stepit.local:9090". The rig was up. The bridge opened its connection only with the first command, and gave it 3 seconds; over the Pi's Wi-Fi, after 11 quiet minutes, it took longer. The same command, a second later, connected in about a second, and later connections take 0.04 seconds.

## Decisions

**Connected from the start.** The bridge connects to rosbridge as it starts, and tries again every 5 seconds while the connection is down, e.g. while the rig restarts. The first command finds the connection ready, and the websocket's own pings, every 20 seconds, keep the Wi-Fi awake.

**10 seconds to connect, not 3.** A slow first answer is not a missing robot. A command that has to connect itself, because the rig has just come back, now waits up to 10 seconds before it fails.

**A missing robot is reported once.** The bridge may run for hours with the rig off: the log says "cannot reach rosbridge ... trying again every 5 s" once per outage, not every 5 seconds.

## Left Out

**Why the Wi-Fi was slow.** The Pi has no `iw` to show its power saving, and `eth0` is down. A connection kept open makes the cause matter less.

## Open Items

- While the rig is off, a command waits for the bridge's own attempt to end before it tries, so it can take up to 20 seconds to fail.
