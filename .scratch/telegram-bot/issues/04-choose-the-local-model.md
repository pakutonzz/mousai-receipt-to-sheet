# Draft Descriptions with a local model, chosen by measurement

Status: ready-for-agent
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
