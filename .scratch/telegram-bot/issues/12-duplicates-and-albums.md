# The same photo twice, and several photos at once

Status: resolved
Blocked by: 07, 09

## Scope

- A photo whose `file_unique_id` already became an Entry carries a warning in
  its Review naming it: *รูปนี้บันทึกไปแล้ว: เงินสดย่อย6 แถว 21 ·
  ‹Description›*. It can still be confirmed. Only the same file is caught, not a
  second photo of the same receipt.
- An album becomes one Transaction per photo, each with its own Review.

## Done when

- Tests for a repeat photo and a three-photo album.

## Comments

**2026-09-28, agent.** Done; `tests/test_bot_photos.py`. A photo whose
`file_unique_id` became an Entry carries "รูปนี้บันทึกไปแล้ว: ‹Page› แถว ‹row› ·
‹Description›" in its Review and on the Keepers' Queue card; it can still be
confirmed. An album is one Transaction per photo sharing one purpose: the
caption (Telegram puts it on one photo) applies to all, and with no caption the
bot asks once. Questions are now asked one at a time per chat, so three photos
that each need a Description or an amount are asked about in turn rather than
overwriting each other. The photos of an album are confirmed separately, and
the second one's Review, worked out before the first was written, comes back
fresh when confirmed.
