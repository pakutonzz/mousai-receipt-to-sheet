# Draft Descriptions with a local model, chosen by measurement

Status: resolved
Blocked by: 03

The LLM drafts each Entry's Description from the receipt's *what* and the
Recorder's *why*, in the Workbook's style ("ค่า‹what› ‹why›"; median 27
characters across 258 real rows). It runs on the Mac's Ollama so that no
patient name leaves the machine (D06).

## Scope

- A `Describer` interface beside `ReceiptReader`: an Ollama implementation and a
  null one that returns nothing. The null one is what the bot falls back to.
- Structured output (JSON with a schema), so a draft is either valid or absent.
  It never returns an amount or a date, and callers do not accept one.
- An evaluation over the committed receipt fixtures, each with a purpose
  caption, run against `aisingapore/Gemma-SEA-LION-v4-27B-IT`, `aya-expanse:8b`
  and `qwen2.5:7b`. Graded on: starts the way real rows do, names what was
  bought without inventing items, carries the caption's purpose, stays short,
  and latency on the Mac. The Workbook's real rows are a style reference only;
  they contain patient names and must not be committed or sent anywhere.
- Record the scores and the choice in this ticket, with the model name pinned
  in configuration.

## Done when

- Scores for all three models are recorded below, and one is chosen.
- A draft for a fixture takes about five seconds or less on the Mac.
- With Ollama stopped, the Describer returns nothing and nothing raises.

## Comments

**2026-09-28, agent. Measured and chosen: `aisingapore/Gemma-SEA-LION-v4-27B-IT`.**

`scripts/eval_describer.py` over the 22 committed sample receipts, each with a
purpose caption from `tests/fixtures/receipts/purposes.json` (6 left blank), on
the Mac's Ollama 0.21.0, M4 Pro 64 GB. Timings exclude each model's first load.

| Model | Usable | Starts ค่า | Carries purpose | ≤ 45 chars | Median | Slowest |
| --- | --- | --- | --- | --- | --- | --- |
| **SEA-LION v4 27B** (final prompt) | **22/22** | **22/22** | **22/22** | **22/22** | 6.3 s | 11.7 s |
| SEA-LION v4 27B (first prompt) | 22/22 | 22/22 | 20/22 | 22/22 | 6.1 s | 12.1 s |
| Qwen 2.5 7B | 21/22 | 21/22 | 21/22 | 18/22 | 2.2 s | 4.3 s |
| Aya Expanse 8B | 3/22 | 1/22 | 6/22 | 2/22 | 7.1 s | 20.1 s |

Read by eye, as the checks cannot judge invention:

- **SEA-LION** reads like the Workbook's rows (ค่าเฉาก๊วยรับรองลูกค้า,
  ค่าตรวจสุขภาพพนักงาน). Its one bad draft copied OCR garbage off a badly
  blurred slip (ค่าโจรามีและธอดสุทธ); the Review exists for that.
- **Qwen** is faster but garbles Thai (ค่าขนมekenno.2, ค่าสเปรย์และเชลลด์),
  invents (ค่าบริการ Swensins Fanclub Card) and adds a purpose nobody gave.
- **Aya** mostly fails to return the schema.

The final prompt adds "no commas, join two things with และ" and caps the
answer at 80 tokens; it carried the purpose on all 22 and removed comma lists.
Sending less of the receipt did not speed it up: the time is the model's.

Latency is a little over the five seconds hoped for: 6.3 s median. A warm
short receipt takes 1.6 s. **Cold start is 12.6 s**: Ollama unloads a model
after five idle minutes, and the default is kept rather than pinning 18 GB on a
Mac other agents share. In chat, with a typing indicator, that is acceptable;
revisit `keep_alive` if the first receipt of the morning feels slow.

Configured through `MOUSAI_DESCRIBE_MODEL` (and `MOUSAI_OLLAMA_URL`).
