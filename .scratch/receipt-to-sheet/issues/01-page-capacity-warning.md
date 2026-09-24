# Warn in the preview when a Page is nearly full

Status: resolved

The preview shows how many rows remain in the target Page's data region, and
warns when fewer than three are left.

## Why now

Pages fill in about a week of normal use — `เงินสดย่อย5` took 24 Entries over
eight days. At cutover the two active Pages stand at:

| Page | Free rows | Region |
| --- | --- | --- |
| `เงินฉุกเฉิน3` | **5** | rows 8–33, last Entry on 28 |
| `เงินสดย่อย6` | 11 | rows 8–31, last Entry on 20 |

So `เงินฉุกเฉิน3` fills within roughly a week of the app being trusted. Without
this warning, the first thing the app does after people start relying on it is
refuse to save, with no notice. With it, someone opens the next Page a few days
ahead and nothing ever blocks.

## Scope

- The row count comes from the data region the app already discovers to find its
  write target, so no new lookup.
- Warn only. Never block, and never create a Page — that is deliberately out of
  scope for this phase (see [spec.md](../spec.md)); a Page made by hand is
  already usable because the picker plus "remember this Page" re-points the
  config tab.
- Threshold of three is a guess at "a couple of days of headroom". Worth
  revisiting once we see the real rate.

## Done when

- The preview states the remaining row count for the chosen Page.
- Below three remaining, it is visually a warning, and the text says what to do:
  duplicate the Page, clear the data region, add the `ยกยอดมา` row with the
  closing balance, then pick the new Page here once.
- A full region still produces the hard error, unchanged.
- Covered by offline tests against the baseline fixture — the counts in the
  table above are the obvious cases.

## Comments

**Domain half done, UI half outstanding.** `Page.rows_remaining` reports the free
rows on a Page, and `Placement.rows_remaining` reports what is left after the
Entry; below three, `place()` emits the warning string. Covered by
`tests/test_page.py::CapacityWarning`, both the quiet case and the warning case.

Still to do: the preview has to surface `rows_remaining` and render the warning
visibly, with the text telling the user to duplicate the Page, clear the data
region, add the `ยกยอดมา` row and pick the new Page here once. Reopen for the UI
work when the preview exists.

**Resolved.** The preview screen shows `เหลือที่ว่าง N แถว` for the chosen Page
on every check, and below three rows it renders the Thai warning
`หน้านี้เหลือที่ว่างอีก N แถว ควรเปิดหน้าใหม่เร็ว ๆ นี้`. The confirmation screen
repeats it, so the person who wrote the Entry sees it even if they skimmed the
preview. A full region still raises the hard error, unchanged.

Covered by `tests/test_page.py::CapacityWarning` (quiet and warning cases) and
`tests/test_web.py::Preview::test_shows_rows_remaining`.
