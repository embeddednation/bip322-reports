"""The node wallet's transaction history, and the wallet's coins at any block height.

Everything comes from the node wallet (``listtransactions``, ``gettransaction``,
``getaddressinfo``); no index is needed, because every transaction that spends
one of the wallet's outputs is itself a wallet transaction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bip322audit.rpc import BitcoinCli, RpcError, btc, to_sat

from . import TOOL

Outpoint = tuple[str, int]
PAGE = 1000


@dataclass(frozen=True)
class Coin:
    """An output paying one of the wallet's addresses."""

    txid: str
    vout: int
    address: str
    amount_sat: int
    height: int | None = None  # the block that created it

    @property
    def outpoint(self) -> Outpoint:
        return (self.txid, self.vout)

    def to_dict(self) -> dict:
        return {
            "txid": self.txid,
            "vout": self.vout,
            "address": self.address,
            "amount_sat": self.amount_sat,
            "amount_btc": btc(self.amount_sat),
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Coin:
        return cls(d["txid"], int(d["vout"]), d["address"], int(d["amount_sat"]), d.get("height"))


@dataclass
class WalletTx:
    """One transaction that touches the wallet: what it took from the wallet, what it gave, what left."""

    txid: str
    height: int | None  # None while unconfirmed
    blockhash: str | None
    time: int  # block time when confirmed, else the wallet's first-seen time
    ours_in: list[Coin] = field(default_factory=list)  # the wallet's outputs this transaction spent
    ours_out: list[Coin] = field(default_factory=list)  # outputs to the wallet's addresses
    others_out: list[Coin] = field(default_factory=list)  # outputs to addresses outside the wallet
    fee_sat: int | None = None  # exact, when every input was the wallet's

    @property
    def net_sat(self) -> int:
        return sum(c.amount_sat for c in self.ours_out) - sum(c.amount_sat for c in self.ours_in)

    @property
    def kind(self) -> str:
        """receive (nothing of ours spent), internal (everything came back), send."""
        if not self.ours_in:
            return "receive"
        if not self.others_out:
            return "internal"
        return "send"

    @property
    def iso_time(self) -> str:
        return datetime.fromtimestamp(self.time, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_dict(self) -> dict:
        return {
            "txid": self.txid,
            "height": self.height,
            "blockhash": self.blockhash,
            "time": self.time,
            "time_utc": self.iso_time,
            "kind": self.kind,
            "net_sat": self.net_sat,
            "net_btc": btc(self.net_sat),
            "fee_sat": self.fee_sat,
            "fee_btc": btc(self.fee_sat) if self.fee_sat is not None else None,
            "ours_in": [c.to_dict() for c in self.ours_in],
            "ours_out": [c.to_dict() for c in self.ours_out],
            "others_out": [c.to_dict() for c in self.others_out],
        }

    @classmethod
    def from_dict(cls, d: dict) -> WalletTx:
        return cls(
            d["txid"],
            d.get("height"),
            d.get("blockhash"),
            int(d["time"]),
            [Coin.from_dict(c) for c in d.get("ours_in", [])],
            [Coin.from_dict(c) for c in d.get("ours_out", [])],
            [Coin.from_dict(c) for c in d.get("others_out", [])],
            d.get("fee_sat"),
        )


@dataclass
class History:
    chain: str
    wallet: str | None
    tip_height: int
    tip_hash: str
    fetched_utc: str
    txs: list[WalletTx]  # confirmed, oldest first
    pending: list[WalletTx]  # unconfirmed at fetch time

    # ---- queries ----------------------------------------------------------- #

    def coins_at(self, height: int) -> list[Coin]:
        """The wallet's unspent outputs after every block up to and including ``height``."""
        spent = {c.outpoint for tx in self.txs if tx.height is not None and tx.height <= height for c in tx.ours_in}
        return [c for tx in self.txs if tx.height is not None and tx.height <= height for c in tx.ours_out if c.outpoint not in spent]

    def balance_at(self, height: int) -> int:
        return sum(c.amount_sat for c in self.coins_at(height))

    def between(self, start_height: int, end_height: int) -> list[WalletTx]:
        """Confirmed transactions with ``start_height < height <= end_height``."""
        return [tx for tx in self.txs if tx.height is not None and start_height < tx.height <= end_height]

    def without_dust(self, threshold_sat: int) -> History:
        """This history as if outputs of at most ``threshold_sat`` had never been the wallet's.

        Such outputs are dropped from every transaction, received or spent, so
        balances, movements and the reconciliation are all computed without
        them; a transaction that touched nothing else disappears.  With a
        threshold of 0 the history is returned unchanged.
        """
        if threshold_sat <= 0:
            return self

        def keep(tx: WalletTx) -> WalletTx:
            return WalletTx(
                tx.txid,
                tx.height,
                tx.blockhash,
                tx.time,
                [c for c in tx.ours_in if c.amount_sat > threshold_sat],
                [c for c in tx.ours_out if c.amount_sat > threshold_sat],
                tx.others_out,
                tx.fee_sat,
            )

        txs = [t for t in (keep(tx) for tx in self.txs) if t.ours_in or t.ours_out]
        pending = [t for t in (keep(tx) for tx in self.pending) if t.ours_in or t.ours_out]
        return History(self.chain, self.wallet, self.tip_height, self.tip_hash, self.fetched_utc, txs, pending)

    def spender_of(self, outpoint: Outpoint) -> WalletTx | None:
        for tx in self.txs:
            if any(c.outpoint == outpoint for c in tx.ours_in):
                return tx
        return None

    # ---- (de)serialization ------------------------------------------------- #

    def to_dict(self) -> dict:
        return {
            "tool": TOOL,
            "chain": self.chain,
            "wallet": self.wallet,
            "tip_height": self.tip_height,
            "tip_hash": self.tip_hash,
            "fetched_utc": self.fetched_utc,
            "transactions": [tx.to_dict() for tx in self.txs],
            "pending": [tx.to_dict() for tx in self.pending],
        }

    @classmethod
    def from_dict(cls, d: dict) -> History:
        return cls(
            d["chain"],
            d.get("wallet"),
            int(d["tip_height"]),
            d["tip_hash"],
            d.get("fetched_utc", ""),
            [WalletTx.from_dict(t) for t in d.get("transactions", [])],
            [WalletTx.from_dict(t) for t in d.get("pending", [])],
        )

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> History:
        return cls.from_dict(json.loads(Path(path).read_text()))


# --------------------------------------------------------------------------- #
# fetching
# --------------------------------------------------------------------------- #


def fetch_history(cli: BitcoinCli, *, progress=None) -> History:
    """Every transaction of the node wallet, with the wallet's side of each resolved exactly.

    Two passes: first every output paying a wallet address (``getaddressinfo``
    says which), then every input that spends one of those.  The fee is
    computed from the inputs and outputs when all inputs are the wallet's,
    so it does not depend on the wallet's own bookkeeping.
    """
    try:
        wallet_name = str(cli.call("getwalletinfo")["walletname"])
    except RpcError as exc:
        raise RpcError(f"a node wallet is needed for the transaction history: {exc}") from exc
    chain = cli.chain()
    tip_height, tip_hash = cli.tip()
    txids = _wallet_txids(cli)
    if progress:
        progress(f"{len(txids)} wallet transactions to read")
    mine: dict[str, bool] = {}

    def is_mine(address: str) -> bool:
        if address not in mine:
            info = cli.call("getaddressinfo", address)
            mine[address] = bool(info.get("ismine") or info.get("iswatchonly"))
        return mine[address]

    raw: list[tuple[dict, list[Coin], list[Coin]]] = []
    known: dict[Outpoint, Coin] = {}
    for txid in txids:
        tx = cli.call("gettransaction", txid, True, True)
        if int(tx.get("confirmations", 0)) < 0:
            continue  # conflicted: never part of the chain
        height = int(tx["blockheight"]) if tx.get("blockheight") is not None else None
        ours_out: list[Coin] = []
        others_out: list[Coin] = []
        for v in tx["decoded"]["vout"]:
            address = v.get("scriptPubKey", {}).get("address")
            if not address:
                continue  # OP_RETURN and non-standard outputs carry no address
            coin = Coin(txid, int(v["n"]), address, to_sat(v["value"]), height)
            (ours_out if is_mine(address) else others_out).append(coin)
        for c in ours_out:
            known[c.outpoint] = c
        raw.append((tx, ours_out, others_out))

    txs: list[WalletTx] = []
    pending: list[WalletTx] = []
    for tx, ours_out, others_out in raw:
        vin = [v for v in tx["decoded"]["vin"] if "coinbase" not in v]
        ours_in = [known[(v["txid"], int(v["vout"]))] for v in vin if (v["txid"], int(v["vout"])) in known]
        fee = None
        if vin and len(ours_in) == len(vin):
            fee = sum(c.amount_sat for c in ours_in) - sum(to_sat(v["value"]) for v in tx["decoded"]["vout"])
        height = int(tx["blockheight"]) if tx.get("blockheight") is not None else None
        entry = WalletTx(
            tx["txid"],
            height,
            tx.get("blockhash"),
            int(tx.get("blocktime") or tx.get("time") or 0),
            ours_in,
            ours_out,
            others_out,
            fee,
        )
        (txs if height is not None else pending).append(entry)
    txs.sort(key=lambda t: (t.height, t.txid))
    return History(chain, wallet_name, tip_height, tip_hash, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), txs, pending)


def _wallet_txids(cli: BitcoinCli) -> list[str]:
    """Every txid the wallet knows, oldest first, paged through listtransactions."""
    seen: list[str] = []
    skip = 0
    while True:
        rows = cli.call("listtransactions", "*", PAGE, skip, True) or []
        for row in rows:
            if row["txid"] not in seen:
                seen.append(row["txid"])
        if len(rows) < PAGE:
            return seen
        skip += PAGE
