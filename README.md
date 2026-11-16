# VIVIO claims assessment

This standard-library Python program prices the supplied specialty claims against member coverage, plan rules, and the carrier's daily accumulator snapshots. It preserves the input claim order in the result file.

## Run

Requires Python 3.11 or later. From the project directory:

```powershell
python main.py
```

The defaults read `data/` and write `output/claims.csv` and `output/balances.csv`. To use different locations:

```powershell
python main.py --data path/to/data --output path/to/output
```

The program exits nonzero for invalid headers or malformed detail records. Recoverable accumulator issues produce warnings and hold affected paid claims until valid data is available. `HELD` is also used for duplicate claim IDs, claims with no unique active coverage, or reversals that cannot be matched to an earlier accepted claim with the same member and opposite allowed amount. A claim can be reversed once. `REJECTED` is used for unsupported transaction types and negative paid claims.

## Results

- `output/claims.csv`: one result per input claim, in original order.
- `output/balances.csv`: ending DED and OOP amounts for known members, showing the latest carrier snapshot, net VIVIO amounts, and total.

See [DECISIONS.md](DECISIONS.md) for assumptions and [NOTES.md](NOTES.md) for scope and follow-up work. The supplied input data is intentionally not included in a handoff archive.
