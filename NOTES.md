# Notes

## Built

- A dependency-free Python CLI to parse the plan, roster, manifest, carrier snapshots, and claims; price the queue; and emit the required two CSV files.
- Input validation for plan references and amounts, coverage dates, claim dates and money, duplicate claim IDs, snapshot header shape, detail rows, and DED/OOP pairs.
- Reversal handling with matching member/amount checks and one reversal per accepted claim.

## Data observations

- The queue has 26 rows: 25 `PAID` transactions and one `REVERSAL`; the seven listed carrier files span March 2 through March 9, 2026.
- Reversal `SP45163` points to `SP45113` for the same member and has the exact opposite allowed amount (`-7222.00` vs. `7222.00`), so it meets the implemented full-reversal checks.
- The claims cover 19 distinct members. The roster has 40 members, so balances also report roster members with no VIVIO claims in this queue.
- `SP45120` appears twice with otherwise identical claim data but different receipt times. Both rows are HELD pending resolution, and neither is counted in member accumulators.
- `SP45256` is HELD because its fill date is March 6 but its roster coverage ends March 4.
- The carrier header's fourth field is opaque batch metadata, while `T` is the trailer record. March 5 has no trailer, and the March 6 trailer is followed by a final detail row that leaves one member's accumulator pair incomplete. The March 7 file omits decimal points from all money values; the integer-cents interpretation matches its total. The program warns, holds affected claims, and continues processing rather than aborting the whole queue.
- The March 4 filename and manifest receipt date are March 4, while its header and detail snapshot dates say March 3; the manifest receipt time is used to order file availability.
- One March 6 inbound member ID has lost leading zeros and has only a DED row; it is matched to the roster ID only if that match is unique, and its claims remain held until a complete pair arrives.

## Left out / next steps

- I would add automated unit and integration coverage for deductible boundaries, OOP exhaustion, cents rounding, multiple daily snapshots, reversals, and malformed input.
- I would define a durable claim ledger and safe rerun/idempotency behavior, plus structured operational logs and reconciliation reports.
- I would add explicit handling for late carrier files, reprocessing, partial reversals, overlapping coverage, and plan changes after the product owner confirms the intended rules.
- I would validate the output with the carrier or hiring team's expected examples and confirm whether negative reversal rows are accepted.

## Time and environment

Approximately 30 minutes of implementation and data inspection. The authoring sandbox could not launch its Python app aliases. The program was subsequently run from the assessment workspace with Python 3.11+ and wrote both output files. A follow-up output inspection confirmed input/output claim row counts and order, required columns, zero amounts for HELD/REJECTED rows, accepted payment reconciliation, and balance totals.

## AI-assisted process

I used an AI coding assistant to inspect the README and data shapes, outline the processing assumptions, draft the CLI and documentation, and review edge cases. The useful corrections during review were preserving the full per-member snapshot history (so earlier claims use the snapshot available at that time) and checking reversal identity and amount to prevent accidentally undoing an unrelated claim or applying the same reversal twice. I did not use external services or provide additional prompt transcripts; this note is the process record.
