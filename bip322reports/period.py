"""A reporting period, resolved to block heights.

Opening figures are "after every block up to and including ``start_height``";
closing figures likewise for ``end_height``; movements are the transactions
confirmed in between.  A calendar period ``[start, end)`` in UTC maps to the
last block *before* each instant, so a year's report opens on the last block
of the previous year and closes on the last block of the year.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from bip322audit.rpc import BitcoinCli


@dataclass(frozen=True)
class Block:
    height: int
    hash: str
    time: int

    @property
    def iso_time(self) -> str:
        return datetime.fromtimestamp(self.time, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_dict(self) -> dict:
        return {"height": self.height, "hash": self.hash, "time": self.time, "time_utc": self.iso_time}


@dataclass(frozen=True)
class Period:
    label: str
    start: Block  # opening balance is as of this block
    end: Block  # closing balance is as of this block
    start_when: str | None = None  # the instants asked for, when the period came from dates
    end_when: str | None = None
    to_tip: bool = False  # the end instant lies in the future: the period runs to the chain tip

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "start_when": self.start_when,
            "end_when": self.end_when,
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
            "to_tip": self.to_tip,
        }


def parse_when(text: str) -> datetime:
    """``YYYY-MM-DD`` (midnight UTC) or an ISO 8601 instant; naive times are UTC."""
    text = text.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    when = datetime.fromisoformat(text)
    return when.replace(tzinfo=timezone.utc) if when.tzinfo is None else when.astimezone(timezone.utc)


def block(cli: BitcoinCli, height: int) -> Block:
    header = cli.block_header(cli.block_hash(height))
    return Block(int(header["height"]), header["hash"], int(header["time"]))


def last_block_before(cli: BitcoinCli, when: datetime) -> Block:
    """The highest block whose header time is before ``when`` (binary search over header times).

    Header times are not strictly monotonic, so this is the natural boundary
    rather than a mathematically unique one; the report prints the height it
    used, which is what makes it reproducible.
    """
    ts = int(when.timestamp())
    tip_height, _ = cli.tip()
    lo, hi = 0, tip_height
    if block(cli, 0).time >= ts:
        return block(cli, 0)  # the chain starts inside the period: nothing precedes its first block
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if block(cli, mid).time < ts:
            lo = mid
        else:
            hi = mid - 1
    return block(cli, lo)


def period_between(cli: BitcoinCli, start: datetime, end: datetime, label: str | None = None) -> Period:
    if end <= start:
        raise ValueError("the period's end must be after its start")
    tip_height, _ = cli.tip()
    start_block = last_block_before(cli, start)
    now = datetime.now(timezone.utc)
    to_tip = end > now
    end_block = block(cli, tip_height) if to_tip else last_block_before(cli, end)
    if end_block.height <= start_block.height:
        raise ValueError(f"no block lies inside the period (both ends resolve to height {start_block.height})")
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return Period(
        label or f"{start.strftime('%Y-%m-%d')}..{end.strftime('%Y-%m-%d')}",
        start_block,
        end_block,
        start.strftime(fmt),
        end.strftime(fmt),
        to_tip,
    )


def period_for_year(cli: BitcoinCli, year: int) -> Period:
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    return period_between(cli, start, datetime(year + 1, 1, 1, tzinfo=timezone.utc), label=str(year))


def period_for_heights(cli: BitcoinCli, start_height: int, end_height: int, label: str | None = None) -> Period:
    if end_height <= start_height:
        raise ValueError("the end height must be above the start height")
    tip_height, _ = cli.tip()
    if end_height > tip_height:
        raise ValueError(f"end height {end_height} is above the tip {tip_height}")
    return Period(label or f"{start_height}..{end_height}", block(cli, start_height), block(cli, end_height))
