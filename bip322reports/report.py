"""Assemble the report: balances, movements, reconciliation, proof coverage."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from bip322audit.rpc import BitcoinCli, RpcError, btc

from . import TOOL
from .coverage import cover_coins, load_ledger, pending_bundles
from .fiat import Rates
from .history import Coin, History
from .period import Period


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_report(
    history: History,
    period: Period,
    *,
    label: str,
    holder: str | None = None,
    ledger_roots=(),
    cli: BitcoinCli | None = None,
    rates: Rates | None = None,
    engines=None,
    progress=None,
) -> dict:
    """The report as a plain dict (what report.json holds and the templates render).

    ``cli`` is needed to re-verify the ledger's proofs against the chain and to
    cross-check the closing balance with ``listunspent`` when the period runs
    to the tip; without it the proofs are verified for their signatures only.
    """
    opening = history.coins_at(period.start.height)
    closing = history.coins_at(period.end.height)
    movements = history.between(period.start.height, period.end.height)
    opening_sat = sum(c.amount_sat for c in opening)
    closing_sat = sum(c.amount_sat for c in closing)
    net_sat = sum(tx.net_sat for tx in movements)

    bundles = load_ledger(cli, ledger_roots, engines=engines, progress=progress) if ledger_roots else []
    covers = cover_coins(closing, bundles)
    used: dict[str, int] = {}  # bundle name -> closing outputs it backs
    closing_rows = []
    covered_sat = 0
    for coin in closing:
        best = covers[coin.outpoint][0] if covers[coin.outpoint] else None
        row = {**coin.to_dict(), "proof": best.to_dict() if best else None, "other_proofs": len(covers[coin.outpoint]) - 1 if best else 0}
        if best and best.verified:
            covered_sat += coin.amount_sat
            used[best.bundle.name] = used.get(best.bundle.name, 0) + 1
        closing_rows.append(row)
    for row in closing_rows:
        if row["proof"]:
            row["proof"]["after_period"] = int(row["proof"]["stamp"]["height"]) > period.end.height
    uncovered = [r for r in closing_rows if not (r["proof"] and r["proof"]["verified"])]
    after_period = sum(1 for r in closing_rows if r["proof"] and r["proof"]["verified"] and r["proof"]["after_period"])

    tx_rows = []
    received = sent = fees = 0
    running = opening_sat
    for tx in movements:
        row = tx.to_dict()
        running += tx.net_sat
        row["balance_after_sat"] = running
        row["balance_after_btc"] = btc(running)
        if tx.kind == "receive":
            row["others_out"] = []  # a payer's own change is not the wallet's business
        if rates:
            row["fiat"] = {
                "currency": rates.currency,
                "rate": str(rates.rate_on(tx.time)) if rates.rate_on(tx.time) is not None else None,
                "net": rates.value(tx.net_sat, tx.time),
                "fee": rates.value(tx.fee_sat, tx.time) if tx.fee_sat is not None else None,
            }
        tx_rows.append(row)
        if tx.kind == "receive":
            received += tx.net_sat
        elif tx.kind == "send":
            sent += -tx.net_sat - (tx.fee_sat or 0)
        if tx.fee_sat:
            fees += tx.fee_sat

    report = {
        "tool": TOOL,
        "generated_utc": _now(),
        "label": label,
        "holder": holder,
        "chain": history.chain,
        "history_fetched_utc": history.fetched_utc,
        "period": period.to_dict(),
        "opening": {
            "height": period.start.height,
            "total_sat": opening_sat,
            "total_btc": btc(opening_sat),
            "coins": [c.to_dict() for c in opening],
        },
        "closing": {"height": period.end.height, "total_sat": closing_sat, "total_btc": btc(closing_sat), "coins": closing_rows},
        "transactions": tx_rows,
        "totals": {
            "received_sat": received,
            "received_btc": btc(received),
            "sent_sat": sent,
            "sent_btc": btc(sent),
            "fees_sat": fees,
            "fees_btc": btc(fees),
            "net_sat": net_sat,
            "net_btc": btc(net_sat),
            "transactions": len(tx_rows),
        },
        "reconciliation": {
            "opening_sat": opening_sat,
            "net_sat": net_sat,
            "closing_sat": closing_sat,
            "diff_sat": closing_sat - opening_sat - net_sat,
            "ok": closing_sat == opening_sat + net_sat,
        },
        "coverage": {
            "covered_sat": covered_sat,
            "covered_btc": btc(covered_sat),
            "uncovered_sat": closing_sat - covered_sat,
            "uncovered_btc": btc(closing_sat - covered_sat),
            "covered_count": len(closing_rows) - len(uncovered),
            "covered_after_period_count": after_period,
            "total_count": len(closing_rows),
            "complete": not uncovered,
            "uncovered": [{k: r[k] for k in ("txid", "vout", "address", "amount_sat", "amount_btc")} for r in uncovered],
        },
        "bundles": [{**b.to_dict(), "used_for": used.get(b.name, 0)} for b in bundles],
        "pending_bundles": [_relative_dir(p, ledger_roots) for p in pending_bundles(ledger_roots)] if ledger_roots else [],
        "pending_transactions": [tx.to_dict() for tx in history.pending],
        "fiat": rates.to_dict() if rates else None,
        "node_check": _node_check(cli, history, period, closing) if cli is not None else None,
    }
    report["report_id"] = _report_id(report)
    node_ok = report["node_check"] is None or report["node_check"].get("ok") is not False  # None: could not be checked, not a failure
    report["ok"] = bool(report["reconciliation"]["ok"] and report["coverage"]["complete"] and node_ok)
    return report


def _report_id(report: dict) -> str:
    """A short identifier of the facts stated: the same facts give the same id, whenever the report is generated."""
    facts = {k: report[k] for k in ("label", "chain", "period", "opening", "closing", "transactions")}
    return hashlib.sha256(json.dumps(facts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _relative_dir(path, roots) -> str:
    for root in roots:
        try:
            return str(Path(path).resolve().relative_to(Path(root).resolve()))
        except ValueError:
            continue
    return Path(path).name


def _node_check(cli: BitcoinCli, history: History, period: Period, closing: list[Coin]) -> dict | None:
    """When the period ends at the history's tip, the node's listunspent must agree with the closing coins."""
    if period.end.height != history.tip_height:
        return None
    try:
        rows = cli.call("listunspent", 1, 9999999) or []
    except RpcError as exc:
        return {"ok": None, "error": str(exc)}
    node = {(r["txid"], int(r["vout"])) for r in rows if int(r.get("confirmations", 0)) > 0}
    ours = {c.outpoint for c in closing}
    return {
        "ok": node == ours,
        "listunspent_count": len(node),
        "closing_count": len(ours),
        "missing_from_report": sorted(f"{t}:{v}" for t, v in node - ours),
        "not_in_listunspent": sorted(f"{t}:{v}" for t, v in ours - node),
    }


def format_summary(report: dict) -> str:
    """The terse text summary printed on stderr."""
    p, r, c = report["period"], report["reconciliation"], report["coverage"]
    lines = [
        f"{report['label']}: {p['label']}  blocks {p['start']['height']} -> {p['end']['height']}"
        + ("  (to tip)" if p["to_tip"] else "")
        + f"  ref {report['report_id']}",
        f"opening {report['opening']['total_btc']} BTC  closing {report['closing']['total_btc']} BTC  net {report['totals']['net_btc']} BTC  "
        f"({report['totals']['transactions']} transactions, fees {report['totals']['fees_btc']} BTC)",
        f"reconciliation: {'ok' if r['ok'] else 'FAILED (diff ' + btc(r['diff_sat']) + ' BTC)'}",
        f"proof coverage: {c['covered_count']}/{c['total_count']} closing outputs, {c['covered_btc']} BTC; "
        f"stamped after the period's end: {c['covered_after_period_count']}/{c['total_count']}"
        + ("" if c["complete"] else f"; UNCOVERED {c['uncovered_btc']} BTC"),
    ]
    for b in report["bundles"]:
        lines.append(
            f"  bundle {b['bundle']}: stamp {b['stamp']['height']}, signatures {b['signatures']}, {'verified' if b['verified'] else 'NOT VERIFIED'}, used for {b['used_for']}"
        )
    if report["pending_bundles"]:
        lines.append("  awaiting signatures: " + ", ".join(report["pending_bundles"]))
    nc = report.get("node_check")
    if nc and nc.get("ok") is None:
        lines.append(f"node check (listunspent vs closing coins): not done ({nc.get('error')})")
    elif nc:
        lines.append("node check (listunspent vs closing coins): " + ("ok" if nc["ok"] else f"MISMATCH {nc}"))
    lines.append("RESULT: " + ("OK" if report["ok"] else "ATTENTION"))
    return "\n".join(lines)
