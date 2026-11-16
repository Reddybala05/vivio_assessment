from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


class InputError(Exception):
    """Raised when source data cannot be safely interpreted."""


def money(value: str, label: str, *, integer_values_are_cents: bool = False) -> Decimal:
    try:
        parsed = Decimal(value)
        if integer_values_are_cents and "." not in value:
            parsed /= 100
        result = parsed.quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise InputError(f"{label}: invalid money value {value!r}") from None
    if not result.is_finite():
        raise InputError(f"{label}: value must be finite")
    return result


def read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                raise InputError(f"{path}: missing CSV header")
            return list(reader)
    except OSError as exc:
        raise InputError(f"Cannot read {path}: {exc}") from exc


@dataclass(frozen=True)
class Plan:
    deductible: Decimal
    oop_max: Decimal
    coinsurance_rate: Decimal
    coinsurance_cap: Decimal


@dataclass(frozen=True)
class PricedClaim:
    status: str
    member_pay: Decimal = ZERO
    plan_pay: Decimal = ZERO
    deductible_applied: Decimal = ZERO


@dataclass(frozen=True)
class ClaimLedgerEntry:
    member_id: str
    allowed_amount: Decimal
    transaction_type: str
    priced: PricedClaim


def load_accumulators(data_dir: Path, known_members: set[str]) -> tuple[
    dict[str, tuple[Decimal, Decimal]],
    dict[str, list[tuple[datetime, tuple[Decimal, Decimal]]]],
    list[tuple[datetime, bool]],
    dict[str, list[datetime]],
]:
    """Read snapshots and track malformed-file/member events for safe claim holds."""
    inbound = data_dir / "inbound"
    manifest_path = inbound / "manifest.csv"
    manifest = read_csv(manifest_path)
    files: list[tuple[datetime, Path]] = []
    for row in manifest:
        try:
            received = datetime.fromisoformat(row["received_at"])
            file_path = inbound / row["filename"]
        except (KeyError, ValueError) as exc:
            raise InputError(f"{manifest_path}: invalid manifest row {row}") from exc
        if not file_path.is_file():
            raise InputError(f"{manifest_path}: missing inbound file {file_path.name}")
        files.append((received, file_path))
    files.sort(key=lambda item: item[0])

    snapshots: dict[str, tuple[Decimal, Decimal]] = {}
    history: dict[str, list[tuple[datetime, tuple[Decimal, Decimal]]]] = {}
    file_health: list[tuple[datetime, bool]] = []
    member_issues: dict[str, list[datetime]] = {}
    member_aliases: dict[str, list[str]] = {}
    for known_member in known_members:
        if known_member.isdigit():
            member_aliases.setdefault(known_member.lstrip("0") or "0", []).append(known_member)
    for received, path in files:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        if not lines:
            raise InputError(f"{path}: empty accumulator file")
        header = lines[0].split("|")
        if len(header) != 5 or header[0] != "H" or header[1] != "CVHP":
            raise InputError(f"{path}: invalid header")
        filename_date = path.stem.rsplit("_", 1)[-1]
        if header[2] != filename_date:
            print(f"WARNING: {path.name}: header date {header[2]} differs from filename date {filename_date}; manifest receipt time is used", file=sys.stderr)
        detail_lines: list[tuple[int, list[str]]] = []
        trailer_count: int | None = None
        trailer_total_text: str | None = None
        trailer_line: int | None = None
        for number, line in enumerate(lines[1:], start=2):
            fields = line.split("|")
            if fields[0] == "D":
                detail_lines.append((number, fields))
            elif fields[0] == "T":
                if trailer_count is not None or len(fields) != 3:
                    raise InputError(f"{path}:{number}: invalid or duplicate trailer")
                try:
                    trailer_count = int(fields[1])
                except ValueError:
                    raise InputError(f"{path}:{number}: invalid trailer record count") from None
                trailer_total_text = fields[2]
                trailer_line = number
            else:
                raise InputError(f"{path}:{number}: unsupported record type {fields[0]!r}")

        if trailer_line is not None and trailer_line != len(lines):
            print(f"WARNING: {path.name}: trailer is not the final record", file=sys.stderr)

        for number, fields in detail_lines:
            if len(fields) != 7 or fields[0] != "D":
                raise InputError(f"{path}:{number}: invalid detail row")
        relevant_amounts = [fields[5] for _, fields in detail_lines if fields[3] == "2026" and fields[4] in {"DED", "OOP"}]
        integer_values_are_cents = bool(relevant_amounts) and all("." not in value for value in relevant_amounts)
        if integer_values_are_cents:
            print(f"WARNING: {path.name}: integer-only accumulator values are interpreted as cents", file=sys.stderr)
        grouped: dict[str, dict[str, Decimal]] = {}
        detail_total = ZERO
        for number, fields in detail_lines:
            _, member_id, _plan_id, year, accum_type, amount, _snapshot_date = fields
            if member_id not in known_members and member_id.isdigit():
                matches = member_aliases.get(member_id.lstrip("0") or "0", [])
                if len(matches) == 1:
                    member_id = matches[0]
            if year != "2026" or accum_type not in {"DED", "OOP"}:
                continue
            per_member = grouped.setdefault(member_id, {})
            if accum_type in per_member:
                raise InputError(f"{path}:{number}: duplicate {accum_type} for {member_id}")
            parsed_amount = money(amount, f"{path}:{number}", integer_values_are_cents=integer_values_are_cents)
            if parsed_amount < ZERO:
                raise InputError(f"{path}:{number}: accumulator amounts cannot be negative")
            per_member[accum_type] = parsed_amount
            detail_total += parsed_amount

        trailer_count_ok = trailer_count is not None and trailer_count == len(detail_lines)
        trailer_total_ok = False
        if trailer_total_text is not None:
            try:
                trailer_total = money(trailer_total_text, f"{path} trailer total", integer_values_are_cents=integer_values_are_cents)
                trailer_total_ok = trailer_total == detail_total
            except InputError:
                trailer_total_ok = False
        trailer_ok = trailer_count_ok and trailer_total_ok
        file_health.append((received, trailer_ok))
        if trailer_count is None:
            print(f"WARNING: {path.name}: missing trailer; PAID claims are held until a later valid file arrives", file=sys.stderr)
        elif not trailer_count_ok:
            print(f"WARNING: {path.name}: trailer count {trailer_count} does not match {len(detail_lines)} detail rows", file=sys.stderr)
        if trailer_total_text is not None and not trailer_total_ok:
            print(f"WARNING: {path.name}: trailer total does not match the accumulator detail total", file=sys.stderr)
        for member_id, values in grouped.items():
            if set(values) != {"DED", "OOP"}:
                member_issues.setdefault(member_id, []).append(received)
                print(f"WARNING: {path.name}: incomplete DED/OOP pair for {member_id}; that member's PAID claims are held until a complete snapshot arrives", file=sys.stderr)
                continue
            amount_pair = (values["DED"], values["OOP"])
            snapshots[member_id] = amount_pair
            history.setdefault(member_id, []).append((received, amount_pair))
    return snapshots, history, file_health, member_issues


def run(data_dir: Path, output_dir: Path) -> None:
    plans: dict[str, Plan] = {}
    for row in read_csv(data_dir / "plans.csv"):
        plan_id = row["plan_id"]
        if plan_id in plans:
            raise InputError(f"Duplicate plan {plan_id}")
        try:
            rate = Decimal(row["coinsurance_rate"])
        except InvalidOperation:
            raise InputError(f"{plan_id}: invalid coinsurance rate") from None
        if not rate.is_finite() or rate < 0 or rate > 1:
            raise InputError(f"{plan_id}: coinsurance rate must be between 0 and 1")
        deductible = money(row["deductible"], f"{plan_id} deductible")
        oop_max = money(row["oop_max"], f"{plan_id} oop_max")
        coinsurance_cap = money(row["coinsurance_max_per_claim"], f"{plan_id} coinsurance cap")
        if min(deductible, oop_max, coinsurance_cap) < ZERO:
            raise InputError(f"{plan_id}: plan amounts cannot be negative")
        plans[plan_id] = Plan(deductible, oop_max, rate, coinsurance_cap)

    roster: dict[str, list[tuple[date, date | None, str]]] = {}
    for row in read_csv(data_dir / "roster.csv"):
        member = row["member_id"]
        try:
            start = date.fromisoformat(row["coverage_start"])
            end = date.fromisoformat(row["coverage_end"]) if row["coverage_end"] else None
        except ValueError as exc:
            raise InputError(f"Invalid coverage date for {member}") from exc
        if row["plan_id"] not in plans:
            raise InputError(f"Roster references unknown plan {row['plan_id']}")
        if end is not None and end < start:
            raise InputError(f"Coverage ends before it starts for {member}")
        roster.setdefault(member, []).append((start, end, row["plan_id"]))

    external, snapshot_history, file_health, member_issues = load_accumulators(data_dir, set(roster))
    claims = read_csv(data_dir / "claims.csv")
    claim_counts = Counter(row["claim_id"] for row in claims)
    duplicate_claim_ids = {claim_id for claim_id, count in claim_counts.items() if count > 1}
    for claim_id in sorted(duplicate_claim_ids):
        print(f"WARNING: claims.csv: duplicate claim_id {claim_id}; all rows with this ID are held", file=sys.stderr)
    # Keep the freshest carrier snapshot that had arrived by the time each claim arrived.
    output_rows: list[dict[str, str]] = []
    vivio_ded: dict[str, Decimal] = {}
    vivio_oop: dict[str, Decimal] = {}
    claim_ledger: dict[str, ClaimLedgerEntry] = {}
    reversed_claims: set[str] = set()

    for row in claims:
        claim_id = row["claim_id"]
        try:
            received = datetime.fromisoformat(row["received_at"])
            fill_date = date.fromisoformat(row["fill_date"])
            allowed = money(row["allowed_amount"], f"{claim_id} allowed_amount")
        except (KeyError, ValueError) as exc:
            raise InputError(f"Invalid date or amount on {claim_id}") from exc
        member = row["member_id"]
        result = PricedClaim("HELD")
        kind = row["transaction_type"].strip().upper()

        if claim_id in duplicate_claim_ids:
            result = PricedClaim("HELD")
            claim_ledger[claim_id] = ClaimLedgerEntry(member, allowed, kind, result)
        elif kind == "REVERSAL":
            original_id = row.get("original_claim_id", "")
            original = claim_ledger.get(original_id)
            reversal_is_valid = (
                original is not None
                and original.transaction_type == "PAID"
                and original.priced.status == "ACCEPTED"
                and original.member_id == member
                and allowed == -original.allowed_amount
                and original_id not in reversed_claims
            )
            if reversal_is_valid:
                assert original is not None  # narrowed by reversal_is_valid
                # A reversal returns the original member and plan payments and reverses its accumulators.
                result = PricedClaim("ACCEPTED", -original.priced.member_pay, -original.priced.plan_pay,
                                     -original.priced.deductible_applied)
                vivio_oop[member] = vivio_oop.get(member, ZERO) + result.member_pay
                vivio_ded[member] = vivio_ded.get(member, ZERO) + result.deductible_applied
                reversed_claims.add(original_id)
            else:
                result = PricedClaim("HELD")
            claim_ledger[claim_id] = ClaimLedgerEntry(member, allowed, kind, result)
        elif kind != "PAID":
            result = PricedClaim("REJECTED")
            claim_ledger[claim_id] = ClaimLedgerEntry(member, allowed, kind, result)
        elif allowed < 0:
            result = PricedClaim("REJECTED")
            claim_ledger[claim_id] = ClaimLedgerEntry(member, allowed, kind, result)
        else:
            files_as_of_claim = [valid for when, valid in file_health if when <= received]
            data_ready = files_as_of_claim[-1] if files_as_of_claim else True
            member_history = snapshot_history.get(member, [])
            snapshot_index = bisect_right(member_history, received, key=lambda item: item[0]) - 1
            latest_snapshot_at = member_history[snapshot_index][0] if snapshot_index >= 0 else None
            latest_member_issue = max((when for when in member_issues.get(member, []) if when <= received), default=None)
            if latest_member_issue is not None and (latest_snapshot_at is None or latest_member_issue > latest_snapshot_at):
                data_ready = False
            if not data_ready:
                result = PricedClaim("HELD")
            else:
                active = [entry for entry in roster.get(member, []) if entry[0] <= fill_date and (entry[1] is None or fill_date <= entry[1])]
                if len(active) != 1:
                    result = PricedClaim("HELD")
                else:
                    plan = plans[active[0][2]]
                    ext_ded, ext_oop = member_history[snapshot_index][1] if snapshot_index >= 0 else (ZERO, ZERO)
                    ded_met = ext_ded + vivio_ded.get(member, ZERO)
                    oop_met = ext_oop + vivio_oop.get(member, ZERO)
                    ded_remaining = max(ZERO, plan.deductible - ded_met)
                    oop_remaining = max(ZERO, plan.oop_max - oop_met)
                    ded_part = min(allowed, ded_remaining)
                    coins_part = min(((allowed - ded_part) * plan.coinsurance_rate).quantize(CENT, rounding=ROUND_HALF_UP), plan.coinsurance_cap)
                    member_pay = min(ded_part + coins_part, oop_remaining)
                    deductible_applied = min(ded_part, member_pay)
                    result = PricedClaim("ACCEPTED", member_pay, allowed - member_pay, deductible_applied)
                    vivio_oop[member] = vivio_oop.get(member, ZERO) + member_pay
                    vivio_ded[member] = vivio_ded.get(member, ZERO) + deductible_applied
            claim_ledger[claim_id] = ClaimLedgerEntry(member, allowed, kind, result)

        output_rows.append({
            "claim_id": claim_id,
            "received_at": row["received_at"],
            "status": result.status,
            "member_pay": f"{result.member_pay:.2f}",
            "plan_pay": f"{result.plan_pay:.2f}",
            "deductible_applied": f"{result.deductible_applied:.2f}",
        })

    output_dir.mkdir(parents=True, exist_ok=True)
    claims_path = output_dir / "claims.csv"
    with claims_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["claim_id", "received_at", "status", "member_pay", "plan_pay", "deductible_applied"])
        writer.writeheader()
        writer.writerows(output_rows)

    # Report all known roster/external members with both accumulator types.
    member_ids = sorted(set(roster) | set(external) | set(vivio_ded) | set(vivio_oop))
    with (output_dir / "balances.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["member_id", "accum_type", "external_amount", "vivio_amount", "total_amount"])
        for member in member_ids:
            ext_ded, ext_oop = external.get(member, (ZERO, ZERO))
            for accum_type, ext, vivio in (("DED", ext_ded, vivio_ded.get(member, ZERO)), ("OOP", ext_oop, vivio_oop.get(member, ZERO))):
                writer.writerow([member, accum_type, f"{ext:.2f}", f"{vivio:.2f}", f"{(ext + vivio):.2f}"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Price VIVIO specialty claims against plan and carrier accumulators.")
    parser.add_argument("--data", type=Path, default=Path("data"), help="input data directory (default: ./data)")
    parser.add_argument("--output", type=Path, default=Path("output"), help="output directory (default: ./output)")
    args = parser.parse_args()
    try:
        run(args.data, args.output)
    except (InputError, InvalidOperation, KeyError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {args.output / 'claims.csv'} and {args.output / 'balances.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
