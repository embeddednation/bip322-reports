"""Assemble the report: balances, movements, reconciliation, proof coverage."""

from __future__ import annotations

import contextlib
import hashlib
import json
import shlex
from datetime import datetime, timezone
from pathlib import Path

from bip322audit.holdings import format_holdings, holdings, holdings_command
from bip322audit.rpc import BitcoinCli, RpcError, btc, to_sat
from bip322core.cli import format_address_text, format_verify_text
from bip322core.core import BIP322Error
from bip322core.engines import EngineError, available_engines
from bip322core.verify import describe_address, verify_message

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
    onchain: bool = True,
    dust_sat: int = 0,
) -> dict:
    """The report as a plain dict (what report.json holds and the templates render).

    ``cli`` is needed to re-verify the ledger's proofs against the chain and to
    cross-check the closing balance with ``listunspent`` when the period runs
    to the tip; without it the proofs are verified for their signatures only.
    Outputs of at most ``dust_sat`` satoshi are dust and left out of every
    figure, as if they had never been the wallet's (``History.without_dust``);
    those held at the closing block are listed in the report's ``dust`` block
    for the record.  Spending them would cost more than they hold, so a
    holder leaves them; and it is control that is proven, not its absence.
    """
    dust = [c for c in history.coins_at(period.end.height) if dust_sat and c.amount_sat <= dust_sat]
    history = history.without_dust(dust_sat)
    opening = history.coins_at(period.start.height)
    closing = history.coins_at(period.end.height)
    created = {tx.txid: tx.iso_time for tx in history.txs}  # when each coin was received: the time of its creating transaction's block
    movements = history.between(period.start.height, period.end.height)
    opening_sat = sum(c.amount_sat for c in opening)
    closing_sat = sum(c.amount_sat for c in closing)
    dust_sat_total = sum(c.amount_sat for c in dust)
    net_sat = sum(tx.net_sat for tx in movements)

    bundles = load_ledger(cli, ledger_roots, engines=engines, progress=progress) if ledger_roots else []
    covers = cover_coins(closing, bundles)
    used: dict[str, int] = {}  # bundle name -> closing outputs it backs
    closing_rows = []
    covered_sat = 0
    for coin in closing:
        best = covers[coin.outpoint][0] if covers[coin.outpoint] else None
        row = {
            **coin.to_dict(),
            "created_utc": created.get(coin.txid),
            "proof": best.to_dict() if best else None,
            "other_proofs": len(covers[coin.outpoint]) - 1 if best else 0,
        }
        if best and best.verified:
            covered_sat += coin.amount_sat
            used[best.bundle.name] = used.get(best.bundle.name, 0) + 1
        closing_rows.append(row)
    for row in closing_rows:
        if row["proof"]:
            row["proof"]["after_period"] = int(row["proof"]["stamp"]["height"]) > period.end.height
    for row in closing_rows:
        row["timeline"] = None
        if row["proof"]:
            stamp = row["proof"]["stamp"]
            row["timeline"] = {
                "received": {"height": row["height"], "time_utc": created.get(row["txid"])},
                "proof": {"height": int(stamp["height"]), "time_utc": stamp["time"]},
                "closing": {"height": period.end.height, "time_utc": period.end.iso_time},
                "held_when_proven": row["height"] is not None and row["height"] <= int(stamp["height"]),
            }
    closing_addresses = _by_address(closing_rows)
    opening_addresses = _by_address([{**c.to_dict(), "created_utc": created.get(c.txid)} for c in opening])
    for a in closing_addresses:
        a["script"] = _address_step(a["address"])
        if a["proof"]:
            _verify_by_script(a, engines)
    onchain_result = _onchain(cli, closing_rows, period, progress) if cli is not None and onchain and closing_rows else None
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
        amount = tx.net_sat + (tx.fee_sat or 0)  # what moved between the wallet and others, before the fee: received, or (sent)
        row["amount_sat"] = amount
        row["amount_btc"] = btc(amount)
        if tx.kind == "receive":
            row["others_out"] = []  # a payer's own change is not the wallet's business
        if rates:
            row["fiat"] = {
                "currency": rates.currency,
                "rate": str(rates.rate_on(tx.time)) if rates.rate_on(tx.time) is not None else None,
                "amount": rates.value(amount, tx.time),
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
            "coins": [{**c.to_dict(), "created_utc": created.get(c.txid)} for c in opening],
            "addresses": opening_addresses,
        },
        "closing": {
            "height": period.end.height,
            "total_sat": closing_sat,
            "total_btc": btc(closing_sat),
            "coins": closing_rows,
            "addresses": closing_addresses,
        },
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
        "dust": {
            "threshold_sat": dust_sat,
            "count": len(dust),
            "total_sat": dust_sat_total,
            "total_btc": btc(dust_sat_total),
            "coins": [{**c.to_dict(), "created_utc": created.get(c.txid), "script_pubkey": _script_of(c.address)} for c in dust],
        },
        "coverage": {
            "covered_sat": covered_sat,
            "covered_btc": btc(covered_sat),
            "uncovered_sat": closing_sat - covered_sat,
            "uncovered_btc": btc(closing_sat - covered_sat),
            "covered_count": len(closing_rows) - len(uncovered),
            "covered_after_period_count": after_period,
            "addresses_total": len(closing_addresses),
            "addresses_covered": sum(1 for a in closing_addresses if a["proof"] and a["proof"]["verified"]),
            "addresses_after_period": sum(
                1 for a in closing_addresses if a["proof"] and a["proof"]["verified"] and a["proof"]["after_period"]
            ),
            "total_count": len(closing_rows),
            "complete": not uncovered,
            "uncovered": [{k: r[k] for k in ("txid", "vout", "address", "amount_sat", "amount_btc")} for r in uncovered],
        },
        "bundles": [
            {**b.to_dict(), "after_period": int(b.stamp["height"]) > period.end.height, "used_for": used.get(b.name, 0)} for b in bundles
        ],
        "policy": _single({b.document.get("policy") for b in bundles} - {None}),
        "pending_bundles": [_relative_dir(p, ledger_roots) for p in pending_bundles(ledger_roots)] if ledger_roots else [],
        "pending_transactions": [tx.to_dict() for tx in history.pending],
        "onchain": onchain_result,
        "fiat": rates.to_dict() if rates else None,
        "node_check": _node_check(cli, history, period, closing, dust_sat) if cli is not None else None,
    }
    report["report_id"] = _report_id(report)
    node_ok = report["node_check"] is None or report["node_check"].get("ok") is not False  # None: could not be checked, not a failure
    chain_ok = onchain_result is None or bool(onchain_result.get("error")) or onchain_result["contradicted"] == 0
    report["ok"] = bool(report["reconciliation"]["ok"] and report["coverage"]["complete"] and node_ok and chain_ok)
    return report


WIDTH = 84  # characters per printed command line: fits an A4 page in the statement's monospace size, and a mainnet block line


def shell_words(argv: list[str]) -> str:
    """A command of plain words, printed over lines of at most WIDTH characters with ``\\`` continuations (long words split too)."""
    lines: list[str] = []
    current = ""
    for word in (shlex.quote(w) for w in argv):
        if len(word) > WIDTH:
            if current:
                lines.append(current + " \\")
            chunks = [word[i : i + WIDTH] for i in range(0, len(word), WIDTH)]
            lines.extend(c + "\\" for c in chunks[:-1])
            current = chunks[-1]
        elif current and len(current) + 1 + len(word) > WIDTH:
            lines.append(current + " \\")
            current = word
        else:
            current = f"{current} {word}" if current else word
    return "\n".join([*lines, current])


def shell_command(argv: list[str]) -> str:
    """A command a reader pastes into a shell, printed over several lines with ``\\`` continuations.

    Bash removes a backslash-newline pair anywhere outside single quotes, so a
    long token can be split across lines too, as long as the continuation
    line is not indented.  The last argument (the message) is double quoted
    with the characters that matter to the shell escaped; the newline inside
    the message stays a real newline, which double quotes allow.  What the
    shell reassembles is exactly ``argv``.
    """

    def split(text: str) -> list[str]:
        chunks: list[str] = []
        while len(text) > WIDTH:
            cut = WIDTH
            space = text.rfind(" ", WIDTH // 2, WIDTH + 1)
            if space > 0:  # a line of the message: break after a space, so the block line keeps its hash and time whole
                cut = space + 1
            while cut > 1 and text[cut - 1] == "\\":  # never break right after a backslash
                cut -= 1
            chunks.append(text[:cut])
            text = text[cut:]
        return [*chunks, text]

    lines: list[str] = []
    current = ""
    for word in (shlex.quote(w) for w in argv[:-1]):
        if len(word) > WIDTH:
            if current:
                lines.append(current + " \\")
            *head, tail = split(word)
            lines.extend(c + "\\" for c in head)
            current = tail
        elif current and len(current) + 1 + len(word) > WIDTH:
            lines.append(current + " \\")
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        lines.append(current + " \\")
    escaped = argv[-1].replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    body: list[str] = []
    for raw in escaped.split("\n"):
        *head, tail = split(raw)
        body.extend(c + "\\" for c in head)
        body.append(tail)
    body[0] = '"' + body[0]
    body[-1] = body[-1] + '"'
    return "\n".join(lines + body)


def _script_of(address: str) -> str | None:
    """The scriptPubKey an address encodes, as hex; None when the address cannot be decoded."""
    try:
        return describe_address(address)["scriptPubKey"]
    except (BIP322Error, ValueError):
        return None


def _address_step(address: str) -> dict:
    """The address opened into its scriptPubKey: the script the proof is for and the outputs are locked to."""
    argv = ["bip322", "validateaddress", address]
    try:
        info = describe_address(address)
    except (BIP322Error, ValueError) as exc:
        return {"command": shell_words(argv), "output": f"(cannot decode: {exc})", "script_pubkey": None, "type": None}
    return {"command": shell_words(argv), "output": format_address_text(info), "script_pubkey": info["scriptPubKey"], "type": info["type"]}


def _verify_by_script(a: dict, engines) -> None:
    """Verify the proof against the scriptPubKey bytes, and keep that command and its output for the statement.

    The bundle's own verification used the address; BIP-322 proves the
    scriptPubKey, so the statement runs the verifier on the bytes the chain
    reports for the UTXO and quotes exactly that.
    """
    spk = a["script"]["script_pubkey"] or a["address"]
    proof = a["proof"]
    message = bytes.fromhex(proof["message_hex"]) if proof.get("message_hex") else proof["message"].encode("utf-8")
    try:
        result = verify_message(spk, proof["signature"], message, engines=engines or available_engines())
        verdict = result.to_dict()
        proof["state"], proof["verified"] = verdict["state"], verdict["state"] == "valid" and proof["verified"]
    except EngineError as exc:
        verdict = None
        proof["output"] = f"(not verified: {exc})"
    proof["command"] = shell_command(["bip322", "verifymessage", spk, proof["signature"], proof["message"]])
    if verdict:
        proof["output"] = format_verify_text(verdict)
        proof["verifier"] = verdict.get("tool")
        proof["engines"] = [f"{e['engine']} {e.get('version') or ''}".strip() for e in verdict.get("engines", []) if e.get("ok")]
    proof["script_pubkey"] = spk


def _onchain(cli: BitcoinCli, closing_rows: list[dict], period: Period, progress=None) -> dict:
    """Run the reader's on-chain step now, per UTXO, at the block named in its proof, and keep the command with its output.

    ``holdings TXID:VOUT --at <proof block>`` is a direct lookup.  A UTXO
    confirmed by that block and unspent now was held at that block: together
    with the proof dated the same block that is one claim with no gap, and
    "still unspent" carries it to the closing block, whichever side of the
    proof it lies on.  A UTXO confirmed after its proof's block is not a
    contradiction; the proof predates it and a later proof is needed.  A
    different scriptPubKey or amount is a contradiction.  UTXOs without a
    proof are looked up at the closing block.
    """
    if progress:
        progress("looking up the closing UTXOs on chain at the blocks of their proofs (bip322 audit holdings)")
    expected_script = {}
    for r in closing_rows:
        with contextlib.suppress(BIP322Error, ValueError):
            expected_script[r["address"]] = describe_address(r["address"])["scriptPubKey"]
    counts = {"matches": 0, "spent_since": 0, "after_proof": 0, "contradicted": 0, "not_run": 0}
    groups: dict[int, list[dict]] = {}
    for r in closing_rows:
        at = int(r["proof"]["stamp"]["height"]) if r.get("proof") else period.end.height
        groups.setdefault(at, []).append(r)
    error = None
    for at, rows in groups.items():
        try:
            result = holdings(cli, [f"{r['txid']}:{r['vout']}" for r in rows], at=at)
        except (RpcError, ValueError) as exc:
            error = str(exc)
            for r in rows:
                r["onchain"] = {
                    "command": shell_words(holdings_command([f"{r['txid']}:{r['vout']}"], at).split()),
                    "output": f"(not run: {exc})",
                    "status": "not run",
                    "at": at,
                }
            counts["not_run"] += len(rows)
            continue
        found = {(o["txid"], o["vout"]): o for o in result["outputs"]}
        for r in rows:
            o = found[(r["txid"], r["vout"])]
            same = (
                o["amount_sat"] == r["amount_sat"]
                and o["address"] == r["address"]
                and (not o.get("script") or o["script"] == expected_script.get(r["address"], o["script"]))
            )
            if not o["unspent"]:
                status = "spent_since"
            elif not same:
                status = "contradicted"
            elif o["counted"]:
                status = "matches"
            else:
                status = "after_proof"
            counts[status] += 1
            counted_sat = o["amount_sat"] if o["counted"] else 0
            r["onchain"] = {
                "command": shell_words(holdings_command([f"{r['txid']}:{r['vout']}"], at).split()),
                "output": format_holdings({**result, "outputs": [o], "total_sat": counted_sat, "total_btc": btc(counted_sat)}),
                "status": status,
                "at": at,
                "tip": result["tip"]["height"],
            }
    return {**counts, "outputs": len(closing_rows), "error": error}


def _by_address(rows: list[dict]) -> list[dict]:
    """Coins grouped per address, in order of first appearance: the statement's unit, since proofs are per address."""
    groups: dict[str, dict] = {}
    for row in rows:
        g = groups.setdefault(row["address"], {"address": row["address"], "total_sat": 0, "outputs": [], "proof": row.get("proof")})
        g["total_sat"] += row["amount_sat"]
        g["outputs"].append(row)  # the same dict as in closing["coins"]: the on-chain result lands on it later
    out = []
    for g in groups.values():
        g["total_btc"] = btc(g["total_sat"])
        times = sorted(o["created_utc"] for o in g["outputs"] if o["created_utc"])
        g["received_first"], g["received_last"] = (times[0], times[-1]) if times else (None, None)
        if g["proof"]:
            stamp = int(g["proof"]["stamp"]["height"])
            heights = [o["height"] for o in g["outputs"] if o["height"] is not None]
            before = "all" if heights and stamp < min(heights) else ("some" if heights and stamp < max(heights) else None)
            g["proof"] = {**g["proof"], "before_coins": before}
        out.append(g)
    return out


def _single(values: set) -> str | None:
    return next(iter(values)) if len(values) == 1 else (" / ".join(sorted(values)) if values else None)


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


def _node_check(cli: BitcoinCli, history: History, period: Period, closing: list[Coin], dust_sat: int = 0) -> dict | None:
    """When the period ends at the history's tip, the node's listunspent must agree with the closing coins (dust left out on both sides)."""
    if period.end.height != history.tip_height:
        return None
    try:
        rows = cli.call("listunspent", 1, 9999999) or []
    except RpcError as exc:
        return {"ok": None, "error": str(exc)}
    node = {(r["txid"], int(r["vout"])) for r in rows if int(r.get("confirmations", 0)) > 0 and to_sat(r["amount"]) > dust_sat}
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
    d = report.get("dust") or {}
    if d.get("count"):
        lines.append(f"dust: {d['count']} outputs of at most {d['threshold_sat']} sat, {d['total_btc']} BTC, left out of every figure")
    for b in report["bundles"]:
        lines.append(
            f"  bundle {b['bundle']}: stamp {b['stamp']['height']}, signatures {b['signatures']}, {'verified' if b['verified'] else 'NOT VERIFIED'}, used for {b['used_for']}"
        )
    if report["pending_bundles"]:
        lines.append("  awaiting signatures: " + ", ".join(report["pending_bundles"]))
    oc = report.get("onchain")
    if oc:
        lines.append(
            "on chain (holdings by UTXO at the block of its proof): "
            + (
                f"not run ({oc['error']})"
                if oc.get("error")
                else f"{oc['matches']}/{oc['outputs']} held when proven"
                + (f", {oc['after_proof']} received after their proof" if oc["after_proof"] else "")
                + (f", {oc['spent_since']} spent since" if oc["spent_since"] else "")
                + (f", {oc['contradicted']} CONTRADICTED" if oc["contradicted"] else "")
            )
        )
    nc = report.get("node_check")
    if nc and nc.get("ok") is None:
        lines.append(f"node check (listunspent vs closing coins): not done ({nc.get('error')})")
    elif nc:
        lines.append("node check (listunspent vs closing coins): " + ("ok" if nc["ok"] else f"MISMATCH {nc}"))
    lines.append("RESULT: " + ("OK" if report["ok"] else "ATTENTION"))
    return "\n".join(lines)
