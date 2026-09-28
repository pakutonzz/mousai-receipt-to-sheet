# Run the bot as a service on the Mac

Status: ready-for-agent
Blocked by: 03, 09

## Scope

- A LaunchAgent beside the web page's, starting at login and restarting on
  crash, logging to `~/Library/Logs/mousai/`.
- The operator is told when the bot starts after a crash.
- README: how to restart it, read its log, and pull a new version.

## Done when

- After a reboot of the Mac, the bot answers a Keeper without anyone logging in
  to start it by hand.
