# Moving the Active Page, and holding items when a Page is full

Status: ready-for-agent
Blocked by: 10

## Scope

- When a Keeper picks a Page other than the Active one, offer to make it the
  Active Page for its Fund, the same change as the web page's switch.
- A full Page never blocks silently and never opens a new Page (D09). A queued
  Transaction stays queued; a Keeper can pick another Page. A Keeper's own
  receipt can be parked in the Queue to wait.

## Done when

- Tests for the offer and for a full Page with and without another Page open.
