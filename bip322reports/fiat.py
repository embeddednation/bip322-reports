"""Optional valuation of movements in a fiat currency.

Rates come from the user: a constant, or a CSV of ``date,rate`` rows (rate per
whole BTC).  For a transaction the rate in force is the latest dated row on or
before its day.  Nothing is fetched from anywhere.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

SATOSHI = Decimal(100_000_000)


@dataclass
class Rates:
    currency: str
    constant: Decimal | None = None
    table: list[tuple[date, Decimal]] | None = None  # sorted by date
    source: str = ""

    @classmethod
    def constant_rate(cls, currency: str, rate: str) -> Rates:
        return cls(currency, Decimal(rate), None, f"constant {rate} {currency}/BTC")

    @classmethod
    def from_csv(cls, currency: str, path: Path) -> Rates:
        rows = []
        with Path(path).open(newline="") as fh:
            for row in csv.reader(fh):
                if not row or row[0].strip().lower() in ("date", "#") or row[0].startswith("#"):
                    continue
                rows.append((date.fromisoformat(row[0].strip()), Decimal(row[1].strip())))
        if not rows:
            raise ValueError(f"{path}: no date,rate rows")
        rows.sort()
        return cls(currency, None, rows, f"{path} ({len(rows)} daily rates)")

    def rate_on(self, when: int) -> Decimal | None:
        """The rate for a unix time, or None when the table starts later."""
        if self.constant is not None:
            return self.constant
        day = datetime.fromtimestamp(when, timezone.utc).date()
        rate = None
        for d, r in self.table or []:
            if d <= day:
                rate = r
            else:
                break
        return rate

    def value(self, sat: int, when: int) -> str | None:
        rate = self.rate_on(when)
        if rate is None:
            return None
        return str((Decimal(sat) / SATOSHI * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def to_dict(self) -> dict:
        return {"currency": self.currency, "source": self.source}
