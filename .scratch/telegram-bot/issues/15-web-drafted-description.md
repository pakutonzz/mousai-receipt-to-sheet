# The web page drafts the Description too

Status: resolved
Blocked by: 01, 04

Today a blank รายละเอียด is written as the English text `(no detail)`.

## Scope

- The web page asks the same Describer for a draft after a photo is read, and
  fills the field with it, tagged like the OCR fields.
- A Description is required; `(no detail)` goes away.
- With no Describer available, the field is simply empty and required.

## Done when

- Web tests for a drafted field and for a refused blank Description.

## Comments

**2026-09-28, agent.** Done. `/api/read` asks the same Describer as the bot
after a photo is read and returns its draft as the Description, tagged
"ร่างจากใบเสร็จ" like the OCR fields; nobody states a purpose on the web page,
so the draft names only what was bought. The OCR's merchant line is no longer
offered. `(no detail)` is gone: `Desk.confirm` refuses a blank Description for
every front end, `/confirm` says so in Thai with the fields kept, and the page
keeps ตรวจสอบก่อนบันทึก disabled with "กรอกรายละเอียดก่อนบันทึก" in the bar,
since the form's own `required` check cannot reach a field behind the modal
Review. Checked in the browser against the test fakes. Also fixed on the way:
the bar's spinner showed in its idle state, because an `<svg>` has no `hidden`
property.
