# The same photo twice, and several photos at once

Status: ready-for-agent
Blocked by: 07, 09

## Scope

- A photo whose `file_unique_id` already became an Entry carries a warning in
  its Review naming it: *รูปนี้บันทึกไปแล้ว: เงินสดย่อย6 แถว 21 ·
  ‹Description›*. It can still be confirmed. Only the same file is caught, not a
  second photo of the same receipt.
- An album becomes one Transaction per photo, each with its own Review.

## Done when

- Tests for a repeat photo and a three-photo album.
