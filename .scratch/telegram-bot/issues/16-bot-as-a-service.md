# Run the bot as a service on the Mac

Status: ready-for-human
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

**2026-09-28, agent.** The operator is now told when the bot comes back from a
stop that was not clean: a marker file beside the store (`mousai.db.running`)
is written at start and removed at a clean stop, which launchd's SIGTERM gives
on `kickstart -k`, logout and shutdown; found at start, the last run crashed,
was killed, or lost power. README: restarting both services, the bot's log,
pulling a new version.

Found on the Mac for the reboot check: FileVault is off, but automatic login is
set to another account, while the web page, the bot and Ollama all run in
`rukz`'s session. After a reboot none of them starts until someone logs in as
`rukz`. Two ways out, a person's choice since both change the Mac's security
settings: set automatic login to `rukz` (keeps deploys sudo-free and brings
Ollama up too), or move the services to LaunchDaemons with `UserName rukz`
(starts at boot whoever logs in, but every restart then needs sudo, and Ollama
would need the same). Then reboot and message the bot.
