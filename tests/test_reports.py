"""bip322-reports against a fake node: history, balances, periods, proof coverage, rendering, CLI."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from bip322audit.audit import finalize_bundle
from bip322audit.ledger import proven_addresses
from bip322audit.snapshot import take_snapshot, write_bundle
from bip322core.dev.signing import sign_psbt
from bip322core.psbt import parse_psbt
from fake_node import T0, FakeNode, block_time, fake_hash

from bip322reports.coverage import cover_coins, load_ledger, pending_bundles
from bip322reports.fiat import Rates
from bip322reports.history import History, fetch_history
from bip322reports.period import block, last_block_before, parse_when, period_between, period_for_heights, period_for_year
from bip322reports.render import render_html, write_csv
from bip322reports.report import build_report, format_summary

BTC = 100_000_000
EXTERNAL = "bc1qexternal0000000000000000000000000000000ext"
EXTERNAL2 = "bc1qexternal1111111111111111111111111111111ext"


def _node(wallet, tip=1000) -> FakeNode:
    """Coins arriving at heights 980-993, a spend and an internal move after 1000, a pending and a conflicted tx."""
    node = FakeNode(tip=tip)
    a0, a1, a2, a3 = wallet.derive(0).address, wallet.derive(0, 1).address, wallet.derive(1, 1).address, wallet.derive(1).address
    node.mine |= {a0, a1, a2, a3}
    node.add("aa" * 32, 990, [(EXTERNAL, 0)], [(a0, 50_000_000)])
    node.add("bb" * 32, 993, [(EXTERNAL2, 0)], [(a0, 25_000_000)])
    node.add("cc" * 32, 980, [(EXTERNAL, 1)], [(a1, 10_000_000)])
    if tip >= 1010:
        node.add("dd" * 32, 1005, [("aa" * 32, 0)], [(EXTERNAL, 20_000_000), (a2, 29_000_000)])  # send: fee 0.01
        node.add("ee" * 32, 1010, [("cc" * 32, 0)], [(a3, 9_900_000)])  # internal: fee 0.001
        node.add("ff" * 32, None, [("bb" * 32, 0)], [(EXTERNAL, 24_990_000)])  # pending
        node.add("99" * 32, 1011, [("bb" * 32, 0)], [(EXTERNAL2, 24_000_000)], conflicted=True)
    return node


def test_history_resolves_the_wallets_side_of_every_transaction(wallet):
    node = _node(wallet, tip=1012)
    history = fetch_history(node)
    assert history.wallet == "watch" and history.chain == "main" and history.tip_height == 1012
    assert [tx.txid[:2] for tx in history.txs] == ["cc", "aa", "bb", "dd", "ee"] and [tx.txid[:2] for tx in history.pending] == ["ff"]
    kinds = {tx.txid[:2]: tx.kind for tx in history.txs}
    assert kinds == {"cc": "receive", "aa": "receive", "bb": "receive", "dd": "send", "ee": "internal"}
    dd = next(tx for tx in history.txs if tx.txid.startswith("dd"))
    assert dd.fee_sat == 1_000_000 and dd.net_sat == -21_000_000 and [c.amount_sat for c in dd.others_out] == [20_000_000]
    assert history.spender_of(("aa" * 32, 0)) is dd and history.spender_of(("bb" * 32, 0)) is None  # pending spends do not count
    assert history.balance_at(1000) == 85_000_000 and history.balance_at(1012) == 63_900_000 and history.balance_at(979) == 0
    assert {c.outpoint for c in history.coins_at(1012)} == {("bb" * 32, 0), ("dd" * 32, 1), ("ee" * 32, 0)}
    assert [tx.txid[:2] for tx in history.between(1000, 1012)] == ["dd", "ee"]
    # exact JSON round trip
    again = History.from_dict(json.loads(json.dumps(history.to_dict())))
    assert again.to_dict() == history.to_dict() and again.balance_at(1012) == 63_900_000


def test_periods_resolve_to_the_last_block_before_an_instant(wallet):
    node = _node(wallet)
    at = datetime.fromtimestamp(block_time(500), timezone.utc)
    assert last_block_before(node, at).height == 499  # strictly before
    assert last_block_before(node, datetime.fromtimestamp(block_time(500) + 1, timezone.utc)).height == 500
    assert last_block_before(node, datetime.fromtimestamp(T0 - 5, timezone.utc)).height == 0  # chain starts inside the period
    assert last_block_before(node, datetime(2099, 1, 1, tzinfo=timezone.utc)).height == 1000
    p = period_between(node, datetime.fromtimestamp(block_time(100), timezone.utc), datetime.fromtimestamp(block_time(900), timezone.utc))
    assert (p.start.height, p.end.height, p.to_tip) == (99, 899, False) and p.start.hash == fake_hash(99)
    p = period_between(node, datetime.fromtimestamp(block_time(100), timezone.utc), datetime(2099, 1, 1, tzinfo=timezone.utc))
    assert (p.end.height, p.to_tip) == (1000, True)
    p = period_for_year(node, 2023)  # every fake block lies in November 2023
    assert (p.label, p.start.height, p.end.height) == ("2023", 0, 1000)
    assert period_for_heights(node, 10, 20).end == block(node, 20)
    with pytest.raises(ValueError):
        period_for_heights(node, 20, 10)
    with pytest.raises(ValueError):
        period_for_heights(node, 10, 5000)
    assert parse_when("2026-01-01") == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert parse_when("2026-01-01T12:00:00Z") == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    assert parse_when("2026-01-01T12:00:00+02:00") == datetime(2026, 1, 1, 10, tzinfo=timezone.utc)


def _bundle(directory: Path, node: FakeNode, wallet, signers, template="Proof of control {date}", skip=None, addresses=None) -> dict:
    """snapshot (or prove given addresses), sign with two cosigners, finalize (recording spends from the fake wallet)."""
    snapshot, psbts = take_snapshot(node, wallet, template, skip_addresses=skip, addresses=addresses)
    write_bundle(directory, snapshot, psbts)
    for entry in snapshot.addresses:
        psbt = parse_psbt((directory / entry["file"]).read_text())
        for signer in signers[:2]:
            assert sign_psbt(psbt, signer) == 1
        (directory / "signed" / Path(entry["file"]).name.replace(".psbt", "-part.psbt")).write_text(psbt.to_string())
    document = finalize_bundle(directory, cli=node)
    (directory / "proofs.json").write_text(json.dumps(document, indent=2))
    return document


def test_report_backs_every_closing_coin_with_a_verified_proof(tmp_path, wallet, signer_expressions):
    ledger = tmp_path / "ledger"
    node = _node(wallet, tip=1000)
    first = _bundle(ledger / "snapshot-1", node, wallet, signer_expressions, "Owner proof {date}")
    assert {(u["txid"][:2], u["vout"]) for p in first["proofs"] for u in p["utxos"]} == {("aa", 0), ("bb", 0), ("cc", 0)}

    node = _node(wallet, tip=1020)  # time passes: a spend, an internal move, and enough blocks for a depth-6 stamp to cover them
    history = fetch_history(node)
    period = period_for_heights(node, 1000, 1020, label="test")
    # only the first bundle: the two new outputs have no proof yet
    report = build_report(history, period, label="Treasury", ledger_roots=[ledger], cli=node)
    assert report["opening"]["total_sat"] == 85_000_000 and report["closing"]["total_sat"] == 63_900_000
    assert report["reconciliation"]["ok"] and report["totals"] == {
        "received_sat": 0, "received_btc": "0.00000000", "sent_sat": 20_000_000, "sent_btc": "0.20000000",
        "fees_sat": 1_100_000, "fees_btc": "0.01100000", "net_sat": -21_100_000, "net_btc": "-0.21100000", "transactions": 2,
    }  # fmt: skip
    cov = report["coverage"]
    assert (cov["covered_count"], cov["total_count"], cov["covered_sat"], cov["complete"]) == (1, 3, 25_000_000, False)
    assert {(u["txid"][:2], u["vout"]) for u in cov["uncovered"]} == {("dd", 1), ("ee", 0)}
    assert report["bundles"][0]["verified"] and report["bundles"][0]["signatures"] == "2/2" and report["bundles"][0]["used_for"] == 1
    assert report["node_check"]["ok"] and not report["ok"]
    assert [t["txid"][:2] for t in report["pending_transactions"]] == ["ff"]
    assert "ATTENTION" in format_summary(report) and "UNCOVERED 0.38900000 BTC" in format_summary(report)

    # a second bundle for the outputs no bundle proves yet; now the closing balance is fully covered
    second = _bundle(ledger / "snapshot-2", node, wallet, signer_expressions, skip=proven_addresses([ledger]))
    assert {(u["txid"][:2], u["vout"]) for p in second["proofs"] for u in p["utxos"]} == {("dd", 1), ("ee", 0)}
    (ledger / "snapshot-3").mkdir()
    (ledger / "snapshot-3" / "snapshot.json").write_text("{}")  # taken, not yet signed
    report = build_report(history, period, label="Treasury", ledger_roots=[ledger], cli=node, rates=Rates.constant_rate("SEK", "1000000"))
    cov = report["coverage"]
    assert cov["complete"] and cov["covered_sat"] == 63_900_000 and report["ok"]
    by_out = {(c["txid"][:2], c["vout"]): c["proof"] for c in report["closing"]["coins"]}
    assert by_out[("bb", 0)]["message"].startswith("Owner proof") and by_out[("bb", 0)]["verified"]
    assert by_out[("dd", 1)]["bundle"].endswith("snapshot-2/proofs.json") and by_out[("dd", 1)]["stamp"]["height"] == 1014
    assert [b["used_for"] for b in report["bundles"]] == [1, 2] and report["pending_bundles"] == ["snapshot-3"]
    dd = next(t for t in report["transactions"] if t["txid"].startswith("dd"))
    assert dd["fiat"] == {"currency": "SEK", "rate": "1000000", "net": "-210000.00", "fee": "10000.00"}

    html = render_html(report)
    assert (
        "Treasury" in html
        and "pill bad" not in html
        and "0.63900000" in html
        and "Owner proof" in html
        and 'href="https://mempool.space/tx/' in html
    )
    assert "verified" in html and "no proof" not in html
    assert report["report_id"] and len(report["report_id"]) == 16 and report["report_id"] in html and report["holder"] is None
    again = build_report(history, period, label="Treasury", ledger_roots=[ledger], cli=node, rates=Rates.constant_rate("SEK", "1000000"))
    assert again["report_id"] == report["report_id"]  # the same facts give the same reference, whenever generated
    assert [t["balance_after_sat"] for t in report["transactions"]] == [64_000_000, 63_900_000]  # a running balance
    assert "(0.21000000)" in html  # accounting negatives in the statement
    with_holder = render_html(build_report(history, period, label="Treasury", holder="Demo Holdings AB", ledger_roots=[ledger], cli=node))
    assert "Demo Holdings AB" in with_holder
    assert 'href="https://mempool.space' not in render_html(report, explorer="")
    csv_path = tmp_path / "t.csv"
    write_csv(report, csv_path)
    lines = csv_path.read_text().splitlines()
    assert lines[0] == "time_utc,height,txid,kind,net_btc,fee_btc,rate,net_fiat,fee_fiat,ours_in,ours_out,others_out" and len(lines) == 3
    assert "send,-0.21000000,0.01000000,1000000,-210000.00,10000.00" in lines[1]

    # coverage prefers a verified proof with the latest stamp; the ledger can be given as its bundles too
    bundles = load_ledger(node, [ledger / "snapshot-1", ledger / "snapshot-2"])
    covers = cover_coins(history.coins_at(1020), bundles)
    assert [c.bundle.path.parent.name for c in covers[("bb" * 32, 0)]] == ["snapshot-1"]
    assert pending_bundles([ledger]) == [ledger / "snapshot-3"]


def test_report_without_a_node_verifies_signatures_only(tmp_path, wallet, signer_expressions):
    ledger = tmp_path / "ledger"
    node = _node(wallet, tip=1000)
    _bundle(ledger / "b", node, wallet, signer_expressions)
    history = fetch_history(node)
    period = period_for_heights(node, 979, 1000)
    report = build_report(history, period, label="x", ledger_roots=[ledger], cli=None, engines=["btclib"])
    assert (
        report["opening"]["total_sat"] == 0
        and report["closing"]["total_sat"] == 85_000_000
        and report["totals"]["received_sat"] == 85_000_000
    )
    assert report["node_check"] is None and report["coverage"]["complete"] and report["bundles"][0]["stamp_ok"] is None
    assert all(c["proof"]["verified"] for c in report["closing"]["coins"])


def test_rates_from_csv_pick_the_latest_dated_row(tmp_path):
    csv_file = tmp_path / "rates.csv"
    csv_file.write_text("date,rate\n2023-11-10,100\n2023-11-16,200\n# comment\n")
    rates = Rates.from_csv("EUR", csv_file)
    assert rates.rate_on(block_time(0)) == 100  # 2023-11-14
    assert rates.rate_on(block_time(300)) == 200  # 2023-11-17
    assert rates.value(150_000_000, block_time(300)) == "300.00"
    assert Rates.from_csv("EUR", csv_file).rate_on(0) is None  # 1970: before the table
    (tmp_path / "empty.csv").write_text("date,rate\n")
    with pytest.raises(ValueError, match="no date,rate rows"):
        Rates.from_csv("EUR", tmp_path / "empty.csv")


def test_cli_end_to_end_with_fake_node(tmp_path, wallet, signer_expressions, monkeypatch, capsys):
    import bip322reports.cli as cli_module

    node = _node(wallet, tip=1012)
    ledger = tmp_path / "ledger"
    _bundle(ledger / "one", _node(wallet, tip=1000), wallet, signer_expressions)
    monkeypatch.setattr(cli_module, "BitcoinCli", lambda command: node)
    monkeypatch.chdir(tmp_path)

    assert cli_module.main(["block", "2023-11-15"]) == 0
    assert json.loads(capsys.readouterr().out)["height"] == last_block_before(node, parse_when("2023-11-15")).height
    assert cli_module.main(["-w", "watch", "history", "-o", "history.json"]) == 0
    out, err = capsys.readouterr()
    assert (
        out == ""
        and json.loads(err.strip().splitlines()[-1])["transactions"] == 5
        and History.load(Path("history.json")).balance_at(1012) == 63_900_000
    )
    assert cli_module.main(["balance", "--history", "history.json", "--height", "1000"]) == 0
    assert json.loads(capsys.readouterr().out)["total_btc"] == "0.85000000"
    assert cli_module.main(["balance", "--at", "2023-11-21T10:00:00Z"]) == 0
    assert json.loads(capsys.readouterr().out)["block"]["height"] == last_block_before(node, parse_when("2023-11-21T10:00:00Z")).height

    assert (
        cli_module.main(
            [
                "report",
                "--history",
                "history.json",
                "--from-height",
                "1000",
                "--to-height",
                "1012",
                "--ledger",
                str(ledger),
                "-o",
                "out",
            ]
        )
        == 0
    )
    out, err = capsys.readouterr()
    assert out.strip() == "out" and "RESULT: ATTENTION" in err and "proof coverage: 1/3" in err
    written = json.loads(Path("out/report.json").read_text())
    assert (
        written["label"] == "watch"
        and not written["coverage"]["complete"]
        and Path("out/report.html").exists()
        and Path("out/transactions.csv").exists()
    )
    assert (
        Path("out/ledger/one/proofs.json").read_bytes() == (ledger / "one" / "proofs.json").read_bytes()
    )  # what the reader gets, no PSBTs
    assert not any(p.suffix == ".psbt" for p in Path("out").rglob("*")) and written["bundles"][0]["bundle"] == "one/proofs.json"
    assert (
        cli_module.main(["report", "--history", "history.json", "--from-height", "1000", "--to-height", "1012", "-o", "out"]) == 2
    )  # not empty
    assert "not empty" in capsys.readouterr().err
    assert cli_module.main(["report", "--history", "history.json", "--from-height", "1000", "-o", "x"]) == 2  # incomplete period
    assert cli_module.main(["report", "--history", "history.json", "-o", "x"]) == 2
    assert cli_module.main(["report", "--history", "history.json", "--year", "2023", "-o", "y", "--rate", "5", "--currency", "USD"]) == 0
    capsys.readouterr()
    written = json.loads(Path("y/report.json").read_text())
    assert (
        written["period"]["label"] == "2023"
        and written["fiat"] == {"currency": "USD", "source": "constant 5 USD/BTC"}
        and written["ok"] is False
    )
    assert cli_module.main(["help", "report"]) == 0 and "Examples:" in capsys.readouterr().out


def test_node_check_that_cannot_run_is_not_a_failure(tmp_path, wallet):
    from bip322audit.rpc import RpcError

    node = _node(wallet, tip=1012)
    history = fetch_history(node)
    original = node.call

    def call(method, *params):
        if method == "listunspent":
            raise RpcError("Multiple wallets are loaded")
        return original(method, *params)

    node.call = call
    report = build_report(history, period_for_heights(node, 1000, 1012), label="x", cli=node)
    assert report["node_check"]["ok"] is None and report["coverage"]["complete"] is False and "not done" in format_summary(report)
    history_only = build_report(history, period_for_heights(node, 1000, 1012), label="x", cli=None)
    assert history_only["node_check"] is None


def test_pdf_without_weasyprint_explains_itself(tmp_path, monkeypatch):
    import sys

    from bip322reports.render import write_pdf

    monkeypatch.setitem(sys.modules, "weasyprint", None)  # makes `from weasyprint import HTML` raise ImportError
    with pytest.raises(RuntimeError, match=r"bip322-reports\[pdf\]"):
        write_pdf("<html></html>", tmp_path / "x.pdf")


def test_change_address_proven_before_the_spend_covers_the_change_output(tmp_path, wallet, signer_expressions):
    """The owner's flow: prove the change address, then broadcast; the report covers the change by that proof."""
    ledger = tmp_path / "ledger"
    before = _node(wallet, tip=1000)
    _bundle(ledger / "all", before, wallet, signer_expressions)
    change = wallet.derive(1, 1).address  # a2: where the 0.29 change of the spend at 1005 will land
    ahead = _bundle(ledger / "change-ahead", before, wallet, signer_expressions, addresses=[change])
    assert ahead["proofs"][0]["address"] == change and ahead["proofs"][0]["utxos"] == []

    node = _node(wallet, tip=1020)
    history = fetch_history(node)
    report = build_report(history, period_for_heights(node, 1000, 1020), label="T", ledger_roots=[ledger], cli=node)
    by_out = {(c["txid"][:2], c["vout"]): c["proof"] for c in report["closing"]["coins"]}
    dd = by_out[("dd", 1)]
    assert dd["verified"] and dd["bundle"] == "change-ahead/proofs.json" and dd["before_output"] and not dd["lists_output"]
    assert not dd["after_period"] and report["coverage"]["covered_after_period_count"] == 0  # every proof here predates block 1020
    # before a year-end bundle, only a3 (the internal move's destination) is left to prove
    snapshot, _ = take_snapshot(node, wallet, "x", skip_addresses=proven_addresses([ledger]))
    assert [a["address"] for a in snapshot.addresses] == [wallet.derive(1).address]
    later = _bundle(ledger / "year-end", _node(wallet, tip=1040), wallet, signer_expressions, "Proof of control, audit FY2023, {date}")
    assert int(later["stamp"]["height"]) == 1034
    node40 = _node(wallet, tip=1040)
    report40 = build_report(fetch_history(node40), period_for_heights(node40, 1000, 1020), label="T", ledger_roots=[ledger], cli=node40)
    assert report40["coverage"]["covered_after_period_count"] == 3 and "stamped after the period's end: 3/3" in format_summary(report40)
    assert all(c["proof"]["after_period"] and c["proof"]["bundle"] == "year-end/proofs.json" for c in report40["closing"]["coins"])
    assert "after the period's end" in render_html(report40)
    assert by_out[("bb", 0)]["lists_output"] and not by_out[("bb", 0)]["before_output"]
    assert by_out[("ee", 0)] is None  # the internal move went to a3, never proven
    html = render_html(report)
    assert "The proof predates this UTXO" in html and "verifymessage" in html and "VALID" in html
    by_addr = {a["address"]: a for a in report["closing"]["addresses"]}
    assert (
        by_addr[wallet.derive(1, 1).address]["proof"]["before_coins"] == "all"
        and by_addr[wallet.derive(1, 1).address]["total_sat"] == 29_000_000
    )
    assert report["coverage"]["addresses_total"] == 3 and report["coverage"]["addresses_covered"] == 2
    # after the year-end bundle nothing is left to prove
    with pytest.raises(Exception, match="already proven"):
        take_snapshot(node40, wallet, "x", skip_addresses=proven_addresses([ledger]))
