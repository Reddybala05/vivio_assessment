# Decisions and assumptions

## Decisions made for this exercise

- The manifest's `received_at` time determines when a carrier file becomes usable. A claim uses the newest snapshot received at or before that claim's `received_at`; if no snapshot was yet available for that member, external amounts start at zero.
- Each inbound file is treated as a complete snapshot for the members it lists, not a delta. A member omitted from a newer snapshot retains their last available snapshot. Accumulator history is selected by member; source plan IDs are not cross-checked against the roster.
- Claims are priced in their input order, which is also the required output order. The supplied queue is chronological. A reversal must reference an earlier accepted claim for the same member with an equal and opposite allowed amount; it negates that claim's payment amounts and removes its member-pay and deductible contributions from the running balance. Duplicate, unmatched, or inconsistent reversals are HELD. Partial reversals are not supported.
- If a `claim_id` occurs more than once, every row for that ID is HELD and contributes nothing to balances. This avoids arbitrarily selecting or pricing one row from an ambiguous duplicate; an operator can resolve it and rerun.
- A PAID claim with no unique active roster row on its fill date is HELD. Unsupported transaction types and negative PAID amounts are REJECTED. Held and rejected rows have zero amounts.
- `Decimal` and half-up rounding are used for money. Coinsurance is rounded to cents before applying the per-claim cap. Plan payment is allowed amount less member payment.
- Ending balances include every roster member and every member present in the inbound accumulator snapshots. External amounts are the latest snapshot in the supplied data; VIVIO amounts are net of accepted reversals. Reversal rows may therefore contain negative payments.
- The inbound header's fourth field does not match the number of detail rows in the supplied sample (for example, `1001` versus 80 rows), so it is treated as opaque batch metadata rather than a detail count. The trailer's record count and accumulator total are checked against detail rows. A missing/mismatched trailer makes PAID claims HELD until the next valid file; a member with an incomplete DED/OOP pair is HELD until a later complete pair arrives. Recoverable file issues are warnings rather than whole-run failures. Invalid headers or malformed detail records still fail fast.
- The manifest controls when a file is usable. A file's header date can differ from its filename date (the March 4 file says March 3), so this mismatch is warned about rather than used to reject the file.
- The March 7 accumulator file has integer-only amounts (for example, `72000`) where the other files use fixed-point dollars (`720.00`). I interpret integer-only accumulator fields in a file as cents (`72000` → `$720.00`), consistent with that file's trailer total and the surrounding file formats. This is a data-specific assumption that should be confirmed with the carrier.
- Numeric accumulator member IDs that do not exactly match the roster are matched to a roster ID after ignoring leading zeros only when that match is unique. This lets the malformed March 6 ID `648583` map to roster-style ID `000648583` without stripping meaningful zeros from the IDs used in outputs.

## Questions before production

- Are carrier files complete member snapshots or deltas? How should a member omitted from a snapshot be interpreted, and what is the authoritative as-of timestamp?
- Does a carrier accumulator snapshot already include VIVIO claims? The exercise describes external amounts as claims handled elsewhere, so this solution adds VIVIO payments.
- Should an accumulator file be effective by carrier snapshot date, delivery time, or another watermark? Can late-arriving files require repricing prior claims?
- What is the required reversal workflow: immediate negative ledger entries, voiding the original and replaying subsequent claims, or another transaction lifecycle? How should partial reversals work?
- What should happen on overlapping coverage, missing eligibility, accumulator/roster plan mismatch, duplicate claims, or a claim whose fill date and receipt date fall in different plan years?
- Does the deductible accumulator mean member-paid deductible only? Are copays, non-covered amounts, and other benefit categories in scope?
- Should a reversal produce negative amounts in this output schema, and does the receiver accept them?
- What audit trail, idempotency, rerun behavior, data retention, operational alerting, and reconciliation controls are required?
