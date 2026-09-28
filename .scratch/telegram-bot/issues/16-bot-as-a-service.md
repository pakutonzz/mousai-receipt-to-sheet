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

## Comments

**2026-09-28, agent.** Started early for ticket 08's live check: the LaunchAgent
`com.mousai.bot` runs `scripts/bot.py`, restarts on crash, and logs to
`~/Library/Logs/mousai/bot.log` without token-bearing URLs. Left: telling the
operator when it restarts after a crash, the README section, and the reboot
check.
