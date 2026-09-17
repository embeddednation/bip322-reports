"""report.html, transactions.csv and, when WeasyPrint is installed, report.pdf."""

from __future__ import annotations

import csv
from pathlib import Path

from bip322audit.rpc import btc
from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from markupsafe import Markup, escape


def _env() -> Environment:
    env = Environment(
        loader=PackageLoader("bip322reports", "templates"),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["btc"] = btc
    env.filters["acct"] = lambda text: f"({text[1:]})" if str(text).startswith("-") else str(text)  # accounting negatives
    env.filters["breakable"] = _breakable
    env.filters["utc"] = lambda iso: (str(iso).replace("T", " ").replace("Z", " UTC")) if iso else ""
    env.filters["short"] = lambda s, n=16: (s[:n] + "…") if s and len(s) > n else s
    return env


def _breakable(text: str, every: int = 12) -> Markup:
    """A long token with a break opportunity every few characters, so it wraps evenly rather than at slashes.

    ``<wbr>`` adds no character: copying the text yields the token unchanged.
    """
    text = str(text)
    return Markup("<wbr>".join(str(escape(text[i : i + every])) for i in range(0, len(text), every)))


def render_html(report: dict, *, explorer: str | None = "https://mempool.space") -> str:
    return _env().get_template("report.html").render(r=report, explorer=(explorer or "").rstrip("/") or None)


def write_csv(report: dict, path: Path) -> None:
    fiat = report.get("fiat")
    fields = (
        ["time_utc", "height", "txid", "kind", "net_btc", "fee_btc"]
        + (["rate", "net_fiat", "fee_fiat"] if fiat else [])
        + ["ours_in", "ours_out", "others_out"]
    )
    with Path(path).open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for tx in report["transactions"]:
            row = {k: tx.get(k) for k in ("time_utc", "height", "txid", "kind", "net_btc", "fee_btc")}
            if fiat:
                row.update({"rate": tx["fiat"]["rate"], "net_fiat": tx["fiat"]["net"], "fee_fiat": tx["fiat"]["fee"]})
            for key in ("ours_in", "ours_out", "others_out"):
                row[key] = " ".join(f"{c['address']}={c['amount_btc']}" for c in tx[key])
            w.writerow(row)


def write_pdf(html: str, path: Path) -> None:
    try:
        from weasyprint import HTML
    except Exception as exc:  # ImportError, or an OSError when its system libraries (Pango) are missing
        raise RuntimeError(
            f"PDF output needs WeasyPrint and its system libraries: pip install 'bip322-reports[pdf]' (see the README) [{exc}]"
        ) from exc
    HTML(string=html).write_pdf(str(path))
