# Set the Mac mini up to run mousai

Status: ready-for-human

A Mac mini on the clinic's side runs the web page, the bot and the local model,
reached over SSH. The repo is cloned there on `main` with a Python 3.11 `.venv`;
Ollama is installed and running with the candidate models pulled. Sleep is
disabled.

## Needs a person

- Bring the Mac back online when it drops off the network.
- Add the deploy key's public half to GitHub: repo **Settings → Deploy keys**,
  read-only. The key is generated on the Mac as part of this ticket.
- Create the bot in @BotFather from the Telegram account logged in on the Mac,
  run `/setjoingroups` → Disable, and paste the token into the Mac's `.env` as
  `TELEGRAM_BOT_TOKEN=`. Never into a chat.

## Then an agent can

- Generate the read-only deploy key and switch the Mac's clone to it, once the
  public half is on GitHub.
- Copy `.env`, `secrets/service-account.json` and `tests/fixtures/baseline.json`
  from the development machine over SSH.
- Install `requirements.txt` into the `.venv` and run the full test suite there.
- Run the web page as a LaunchAgent on `127.0.0.1` that starts at login and
  restarts on crash, logging to `~/Library/Logs/mousai/`. LaunchAgents start
  when their account logs in; if the Mac must come back unattended after a
  power cut, it needs automatic login to that account.
- Document the tunnel: `ssh -N -L 8000:127.0.0.1:8000 <mac>`, then
  `http://127.0.0.1:8000`.

## Done when

- `curl http://127.0.0.1:8000/health` answers through the tunnel after a
  reboot of the Mac.
- `git pull` on the Mac works with the deploy key and nobody's personal login.

## Comments

**2026-09-28, agent.** Done on the Mac:

- Clone pulled to `main`. `.env`, `secrets/service-account.json` and
  `tests/fixtures/baseline.json` copied over SSH, readable by the account
  alone, all gitignored.
- The full suite passes there: 226 tests, 22/22 amounts, 21/21 dates. The
  `.venv` has no pip; the current requirements were already installed.
- LaunchAgent `com.mousai.web` runs the web page on `127.0.0.1:8000` only,
  logging to `~/Library/Logs/mousai/web.log`. Through an SSH tunnel from the
  laptop it served the live Workbook.
- A read-only deploy key generated on the Mac, with its own SSH host alias.
  GitHub's host key pinned and checked against its published fingerprint.

**2026-09-28, agent.** The deploy key is on GitHub, read-only, its
fingerprint matching the Mac's; the clone's remote uses it, and
`git fetch`/`git pull` work with it alone. The bot token is in the Mac's
`.env`. Left: the reboot check.
