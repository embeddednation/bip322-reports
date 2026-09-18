"""``bip322-reports``: balance reports backed by verified BIP-322 proofs, from the owner's node wallet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bip322audit.audit import AuditError
from bip322audit.ledger import find_proofs
from bip322audit.rpc import BitcoinCli, RpcError, btc
from bip322core._version import SPEC
from bip322core.cli import CLIError, add_help_command, emit
from bip322core.core import BIP322Error

from . import TOOL
from .coverage import relative_name
from .fiat import Rates
from .history import History, fetch_history
from .period import block, last_block_before, parse_when, period_between, period_for_heights, period_for_year
from .render import render_html, write_csv, write_pdf
from .report import build_report, format_summary


def _opt(args, name: str):
    """A node option given after the subcommand wins over the same option given before it."""
    return getattr(args, f"{name}_sub", None) or getattr(args, name, None)


def _cli(args) -> BitcoinCli:
    cli = BitcoinCli(_opt(args, "cli") or "bitcoin-cli")
    wallet = _opt(args, "wallet")
    if wallet:
        cli.argv.append(f"-rpcwallet={wallet}")
    return cli


def _add_node_args(p: argparse.ArgumentParser, wallet: bool = True) -> None:
    p.add_argument("--cli", dest="cli_sub", metavar="CMD", help="how to reach the node (may also be given before the command)")
    if wallet:
        p.add_argument("--wallet", "-w", dest="wallet_sub", metavar="NAME", help="the node wallet (may also be given before the command)")


def _progress(line: str) -> None:
    print(line, file=sys.stderr)


def _history(args, cli: BitcoinCli) -> History:
    if getattr(args, "history", None):
        return History.load(Path(args.history))
    return fetch_history(cli, progress=_progress)


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #


def cmd_block(args) -> int:
    cli = _cli(args)
    found = last_block_before(cli, parse_when(args.when))
    emit(json.dumps(found.to_dict(), indent=2), args.output)
    return 0


def cmd_history(args) -> int:
    history = fetch_history(_cli(args), progress=_progress)
    emit(json.dumps(history.to_dict(), indent=2), args.output)
    print(
        json.dumps(
            {
                "wallet": history.wallet,
                "chain": history.chain,
                "tip": history.tip_height,
                "transactions": len(history.txs),
                "pending": len(history.pending),
            }
        ),
        file=sys.stderr,
    )
    return 0


def cmd_balance(args) -> int:
    cli = _cli(args)
    history = _history(args, cli)
    if args.height is not None:
        at = block(cli, args.height) if not args.history else None
        height = args.height
    elif args.at:
        at = last_block_before(cli, parse_when(args.at))
        height = at.height
    else:
        at, height = None, history.tip_height
    coins = history.coins_at(height)
    total = sum(c.amount_sat for c in coins)
    out = {
        "height": height,
        "block": at.to_dict() if at else None,
        "total_sat": total,
        "total_btc": btc(total),
        "coins": [c.to_dict() for c in coins],
    }
    emit(json.dumps(out, indent=2), args.output)
    return 0


def cmd_report(args) -> int:
    cli = _cli(args)
    history = _history(args, cli)
    if history.wallet and not any(a.startswith("-rpcwallet=") for a in cli.argv):
        cli.argv.append(f"-rpcwallet={history.wallet}")  # a cached history knows its wallet; the node cross-check needs it
    if args.year is not None:
        period = period_for_year(cli, args.year)
    elif args.from_height is not None or args.to_height is not None:
        if args.from_height is None or args.to_height is None:
            raise CLIError("--from-height and --to-height go together")
        period = period_for_heights(cli, args.from_height, args.to_height)
    elif args.from_when or args.to_when:
        if not args.from_when or not args.to_when:
            raise CLIError("--from and --to go together")
        period = period_between(cli, parse_when(args.from_when), parse_when(args.to_when))
    else:
        raise CLIError("give the period: --year YEAR, --from DATE --to DATE, or --from-height H --to-height H")
    if period.end.height > history.tip_height:
        raise CLIError(f"the history (tip {history.tip_height}) is older than the period's end block {period.end.height}; refresh it")
    rates = None
    if args.rates:
        rates = Rates.from_csv(args.currency, Path(args.rates))
    elif args.rate:
        rates = Rates.constant_rate(args.currency, args.rate)
    label = history.wallet or "wallet"
    report = build_report(
        history,
        period,
        label=label,
        holder=args.holder,
        ledger_roots=[Path(p) for p in (args.ledger or [])],
        cli=cli,
        rates=rates,
        engines=args.engines.split(",") if args.engines else None,
        progress=_progress,
    )
    directory = Path(args.output) if args.output else Path(f"report-{label}-{period.label}".replace(" ", "_").replace("/", "_"))
    if directory.exists() and any(directory.iterdir()) and not args.force:
        raise CLIError(f"{directory} exists and is not empty (use --force to overwrite)")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    html = render_html(report, explorer=args.explorer)
    (directory / "report.html").write_text(html)
    write_csv(report, directory / "transactions.csv")
    if args.pdf:
        write_pdf(html, directory / "report.pdf")
    if not args.no_proofs and args.ledger:
        # what the reader needs next to the report: each bundle's proofs.json under the name the report uses.
        # Never the bundle directories themselves: their PSBTs carry the wallet's xpubs.
        roots = [Path(p) for p in args.ledger]
        for path, _ in find_proofs(roots):
            target = directory / "ledger" / relative_name(path, roots)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
    print(format_summary(report), file=sys.stderr)
    print(str(directory))
    return 0


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bip322-reports",
        description=f"Balance reports in which every coin is backed by a verified BIP-322 proof of control, from the owner's node wallet ({SPEC}).",
    )
    parser.add_argument("--version", action="version", version=f"{TOOL} ({SPEC})")
    parser.add_argument(
        "--cli", default=None, metavar="CMD", help='how to reach the node, e.g. "bitcoin-cli -signet" (default: bitcoin-cli)'
    )
    parser.add_argument(
        "--wallet",
        "-w",
        default=None,
        metavar="NAME",
        help="the node wallet (bitcoin-cli -rpcwallet=NAME); required when several are loaded",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    p = sub.add_parser(
        "block",
        help="the last block before a UTC date or time",
        description="Height, hash and time of the last block whose header time is before the instant (YYYY-MM-DD is midnight UTC).",
    )
    p.add_argument("when", metavar="WHEN", help="YYYY-MM-DD or an ISO 8601 instant")
    _add_node_args(p, wallet=False)
    p.add_argument("--output", "-o", metavar="FILE", help="write the JSON here instead of stdout")
    p.set_defaults(func=cmd_block, examples=["block 2026-01-01", "block 2025-12-31T23:00:00Z"])

    p = sub.add_parser(
        "history",
        help="the node wallet's transaction history as JSON (a cache for balance and report)",
        description=(
            "Read every transaction of the node wallet (listtransactions, gettransaction, getaddressinfo) and resolve the wallet's side of each: "
            "outputs to the wallet, the wallet's outputs spent, outputs to outside, the exact fee. No index is needed. "
            "balance and report take the result with --history so they can run without the wallet, or repeatably on the same data."
        ),
    )
    _add_node_args(p)
    p.add_argument("--output", "-o", metavar="FILE", help="write history.json here instead of stdout")
    p.set_defaults(func=cmd_history, examples=["-w treasury history -o history.json"])

    p = sub.add_parser(
        "balance",
        help="the wallet's coins and balance at a height or date",
        description="The unspent outputs after every block up to the given height (or the last block before the date), from the history.",
    )
    _add_node_args(p)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--height", type=int, metavar="H")
    g.add_argument("--at", metavar="WHEN", help="YYYY-MM-DD or an ISO 8601 instant; the last block before it")
    p.add_argument("--history", metavar="FILE", help="use this history.json instead of reading the node wallet")
    p.add_argument("--output", "-o", metavar="FILE", help="write the JSON here instead of stdout")
    p.set_defaults(func=cmd_balance, examples=["-w treasury balance --at 2026-01-01", "balance --history history.json --height 912345"])

    p = sub.add_parser(
        "report",
        help="the balance report for a period: report.json, report.html, transactions.csv (and report.pdf)",
        description=(
            "Opening and closing balances, every movement between them, a reconciliation, and for each closing output the BIP-322 proof of "
            "control from the ledger that lists it, re-verified against the node now. The period is a calendar year, two instants, or two "
            "heights; opening figures are as of the start block, closing figures as of the end block."
        ),
    )
    _add_node_args(p)
    p.add_argument("--year", "-y", type=int, metavar="YEAR", help="the calendar year, UTC")
    p.add_argument("--from", dest="from_when", metavar="WHEN", help="start instant (YYYY-MM-DD or ISO 8601, UTC)")
    p.add_argument("--to", dest="to_when", metavar="WHEN", help="end instant, exclusive; in the future means up to the tip")
    p.add_argument("--from-height", type=int, metavar="H", help="opening block height")
    p.add_argument("--to-height", type=int, metavar="H", help="closing block height")
    p.add_argument(
        "--ledger", "-l", metavar="DIR", action="append", help="directory tree of bip322-audit bundles (proofs.json); may repeat"
    )
    p.add_argument("--holder", metavar="NAME", help="the holder of the wallet, as named in the statement's header (optional)")
    p.add_argument("--history", metavar="FILE", help="use this history.json instead of reading the node wallet")
    p.add_argument("--rates", metavar="CSV", help="date,rate rows (rate per BTC) for a fiat valuation of the movements")
    p.add_argument("--rate", metavar="RATE", help="a constant rate per BTC instead of --rates")
    p.add_argument("--currency", default="FIAT", metavar="CODE", help="the fiat currency's name for --rates/--rate (default %(default)s)")
    p.add_argument(
        "--explorer",
        default="https://mempool.space",
        metavar="URL",
        help="block explorer for links in the HTML; '' for no links (default %(default)s)",
    )
    p.add_argument("--pdf", action="store_true", help="also write report.pdf (needs WeasyPrint: ./setup.sh --pdf)")
    p.add_argument(
        "--no-proofs", action="store_true", help="do not copy the ledger's proofs.json files into <DIR>/ledger/ next to the report"
    )
    p.add_argument("--engines", default=None, help="comma separated bip322 engines for re-verifying the proofs (default: all installed)")
    p.add_argument("--output", "-o", metavar="DIR", help="report directory (default report-<label>-<period>)")
    p.add_argument("--force", action="store_true", help="write into a non-empty directory")
    p.set_defaults(
        func=cmd_report,
        examples=[
            "-w treasury report --year 2026 --ledger ledger",
            "-w treasury report --from 2026-01-01 --to 2026-07-01 --ledger ledger --rates sek.csv --currency SEK --pdf",
            "report --history history.json --from-height 900000 --to-height 912345 --ledger ledger -o q3",
        ],
    )

    add_help_command("bip322-reports", sub, {"Workflow": ["history", "block", "balance", "report", "help"]})
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (CLIError, BIP322Error, RpcError, AuditError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc.strerror or exc}: {exc.filename}" if getattr(exc, "filename", None) else f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
