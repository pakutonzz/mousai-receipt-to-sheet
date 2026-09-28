# Moving the Active Page, and holding items when a Page is full

Status: resolved
Blocked by: 10

## Scope

- When a Keeper picks a Page other than the Active one, offer to make it the
  Active Page for its Fund, the same change as the web page's switch.
- A full Page never blocks silently and never opens a new Page (D09). A queued
  Transaction stays queued; a Keeper can pick another Page. A Keeper's own
  receipt can be parked in the Queue to wait.

## Done when

- Tests for the offer and for a full Page with and without another Page open.

## Comments

**2026-09-28, agent.** Done; `tests/test_bot_pages.py`. The offer comes with
the saved message, when the Entry went to a Page other than its Fund's Active
Page (the remembered one, or with none remembered, the Fund's last Page); a
button makes it the Active Page for everyone, the same `_mousai` tab the web
page's switch writes. Only a Keeper can press it, and only once the Entry is
saved. A full Page shows why, the field buttons to pick another Page, and a way
to wait: a Keeper parks their own receipt in the Queue (the other Keepers get
the card, the parker keeps an open button), a Recorder hands it in as usual,
and a queued item simply stays queued. A Page that fills between the Review
and the confirm comes back as the same view, with the claim released. No Page
is ever opened by the bot (D09).
