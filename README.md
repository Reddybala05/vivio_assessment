# VIVIO claims assessment

This standard-library Python program prices the supplied specialty claims against member coverage, plan rules, and the carrier's daily accumulator snapshots. It preserves the input claim order in the result file.

## Run

Requires Python 3.11 or later. From the project directory:

```powershell
python main.py
```

The supplied `data/` directory is required to run the program. Keep it beside `main.py`; it must contain `claims.csv`, `roster.csv`, `plans.csv`, and the `inbound/` manifest and accumulator files. The assessment handoff ZIP omits this input data, so copy the provided `data/` directory into the project folder before running.

The program creates `output/` automatically and writes `output/claims.csv` and `output/balances.csv`; you do not need to create the output directory first. To use different locations, replace these example paths with real directories:

```powershell
python main.py --data "C:\path\to\data" --output "C:\path\to\output"
```

The program exits nonzero for invalid headers or malformed detail records. Recoverable accumulator issues produce warnings and hold affected paid claims until valid data is available. `HELD` is also used for duplicate claim IDs, claims with no unique active coverage, or reversals that cannot be matched to an earlier accepted claim with the same member and opposite allowed amount. A claim can be reversed once. `REJECTED` is used for unsupported transaction types and negative paid claims.

## Results

- `output/claims.csv`: one result per input claim, in original order.
- `output/balances.csv`: ending DED and OOP amounts for known members, showing the latest carrier snapshot, net VIVIO amounts, and total.

See [DECISIONS.md](DECISIONS.md) for assumptions and [NOTES.md](NOTES.md) for scope and follow-up work. The supplied input data is intentionally not included in a handoff archive.
