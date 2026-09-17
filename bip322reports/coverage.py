"""Which proof covers which coin.

The ledger (any directory tree of bip322-audit bundles) is read and every
``proofs.json`` in it is re-verified against the node at report time.  A coin
is *covered* when a verified proof exists for its address: a BIP-322 proof is
about the script behind an address, so it covers every output paid there,
whether the proof was made before the output existed (a change address proven
before the spend was broadcast) or after (a snapshot that listed it).  Among
several proofs the verified ones come first, then those whose snapshot listed
the exact output, then the latest stamp; all are kept for the record.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bip322audit.audit import AuditError, verify_proofs
from bip322audit.ledger import find_proofs, outpoints_in
from bip322audit.rpc import BitcoinCli

from .history import Coin, Outpoint


@dataclass
class Bundle:
    """One proofs document from the ledger and the result of verifying it now."""

    path: Path
    document: dict
    report: dict | None  # verify_proofs output; None when verification could not run
    error: str | None = None
    name: str = ""  # how the bundle is named in the report: relative to the ledger it came from, never an absolute path

    @property
    def stamp(self) -> dict:
        return self.document["stamp"]

    @property
    def message(self) -> str:
        return self.document["message"]

    @property
    def ok(self) -> bool:
        return bool(self.report and self.report.get("ok"))

    def proof_state(self, address: str) -> str:
        verdict = self.verdict(address)
        return verdict["state"] if verdict else ("not verified" if not self.report else "missing")

    def verdict(self, address: str) -> dict | None:
        """The verifier's own record for one address: state, tool, engines."""
        if not self.report:
            return None
        for row in self.report["proofs"]:
            if row["address"] == address:
                return row["bip322"]
        return None

    def to_dict(self) -> dict:
        s = (self.report or {}).get("summary") or {}
        return {
            "bundle": self.name,
            "stamp": self.stamp,
            "message": self.message,
            "finalized_utc": self.document.get("finalized_utc"),
            "policy": self.document.get("policy"),
            "outputs": len(outpoints_in(self.document)),
            "total_sat": self.document.get("total_sat"),
            "verified": self.ok,
            "signatures": f"{sum(1 for p in (self.report or {}).get('proofs', []) if p['bip322']['state'] == 'valid')}/{len(self.document['proofs'])}",
            "stamp_ok": s.get("stamp_ok"),
            "contradictions": s.get("contradictions"),
            "error": self.error,
        }


@dataclass
class Cover:
    """The proof chosen for one coin."""

    bundle: Bundle
    address: str
    signature: str
    variant: str
    state: str  # the signature's verdict now
    lists_output: bool  # the bundle's snapshot listed this very output
    coin_height: int | None = None

    @property
    def verified(self) -> bool:
        return self.state == "valid" and self.bundle.ok

    @property
    def before_output(self) -> bool:
        """The proof was made before the output existed (an address proven ahead of use)."""
        return self.coin_height is not None and int(self.bundle.stamp["height"]) < self.coin_height

    def to_dict(self) -> dict:
        verdict = self.bundle.verdict(self.address) or {}
        return {
            "bundle": self.bundle.name,
            "message": self.bundle.message,
            "stamp": self.bundle.stamp,
            "address": self.address,
            "signature": self.signature,
            "variant": self.variant,
            "state": self.state,
            "verified": self.verified,
            "verifier": verdict.get("tool"),
            "engines": _engine_names(verdict.get("engines", [])),
            "lists_output": self.lists_output,
            "before_output": self.before_output,
        }


def _engine_names(runs) -> list[str]:
    """The script engines that passed, by public name and version, once each (the verifier runs btclib with two rule sets)."""
    names = {"btclib": "btclib", "kernel": "libbitcoinkernel"}
    out: list[str] = []
    for run in runs:
        if not isinstance(run, dict) or not run.get("ok"):
            continue
        name = names.get(str(run.get("engine", "")).split("-")[0], str(run.get("engine")))
        label = f"{name} {run['version']}" if run.get("version") else name
        if label not in out:
            out.append(label)
    return out


def load_ledger(cli: BitcoinCli | None, roots, *, engines=None, progress=None) -> list[Bundle]:
    """Every proofs document under the roots, verified against the node (signatures only when ``cli`` is None)."""
    bundles = []
    for path, document in find_proofs(roots):
        if progress:
            progress(f"verifying {path}")
        name = relative_name(path, roots)
        try:
            report = verify_proofs(document, cli, engines=engines)
            bundles.append(Bundle(path, document, report, name=name))
        except AuditError as exc:
            bundles.append(Bundle(path, document, None, str(exc), name=name))
    return bundles


def relative_name(path: Path, roots) -> str:
    """``<bundle dir>/proofs.json`` relative to the ledger root it lies under."""
    for root in roots:
        root = Path(root).resolve()
        base = root.parent if root.is_file() else root
        try:
            return str(path.relative_to(base))
        except ValueError:
            continue
    return f"{path.parent.name}/{path.name}"


def cover_coins(coins: list[Coin], bundles: list[Bundle]) -> dict[Outpoint, list[Cover]]:
    """For each coin, the proofs for its address, best first (verified, then listing the output, then latest stamp)."""
    by_outpoint: dict[Outpoint, list[Cover]] = {c.outpoint: [] for c in coins}
    for bundle in bundles:
        for proof in bundle.document["proofs"]:
            listed = {(u["txid"], int(u["vout"])) for u in proof["utxos"]}
            for coin in coins:
                if coin.address != proof["address"]:
                    continue
                by_outpoint[coin.outpoint].append(
                    Cover(
                        bundle,
                        proof["address"],
                        proof["signature"],
                        proof.get("variant", proof["signature"][:3]),
                        bundle.proof_state(proof["address"]),
                        coin.outpoint in listed,
                        coin.height,
                    )
                )
    for covers in by_outpoint.values():
        covers.sort(key=lambda c: (not c.verified, not c.lists_output, -int(c.bundle.stamp["height"])))
    return by_outpoint


def pending_bundles(roots) -> list[Path]:
    """Snapshot directories that have no proofs.json yet: signatures still to collect."""
    out = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for snap in sorted(root.rglob("snapshot.json")):
            if not (snap.parent / "proofs.json").exists():
                out.append(snap.parent)
    return out
