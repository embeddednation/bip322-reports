"""report.html, transactions.csv and, when WeasyPrint is installed, report.pdf."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from bip322audit.rpc import btc
from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from markupsafe import Markup, escape

SOLARIZED = {
    "base03": "#002b36",
    "base02": "#073642",
    "base01": "#586e75",
    "base00": "#657b83",
    "base0": "#839496",
    "base1": "#93a1a1",
    "base2": "#eee8d5",
    "base3": "#fdf6e3",
    "yellow": "#b58900",
    "orange": "#cb4b16",
    "red": "#dc322f",
    "magenta": "#d33682",
    "violet": "#6c71c4",
    "blue": "#268bd2",
    "cyan": "#2aa198",
    "green": "#859900",
}  # Ethan Schoonover's palette; the accents keep their weight on either background
_S = SOLARIZED

MARBER = {  # The Economist's Marber design system: the brand red, "base" colours named after global cities, London greys, canvases
    "red": "#E3120B",
    "red42": "#CC100A",
    "red95": "#FEE7E7",
    "chicago20": "#141F52",
    "chicago45": "#2E45B8",
    "hongkong35": "#169C7F",
    "tokyo35": "#9C1633",
    "tokyo45": "#C91D42",
    "shanghai35": "#4C9C16",
    "singapore55": "#F97A1F",
    "newyork55": "#F9C31F",
    "london5": "#0D0D0D",
    "london10": "#1A1A1A",
    "london20": "#333333",
    "london35": "#595959",
    "london70": "#B3B3B3",
    "london85": "#D9D9D9",
    "london95": "#F2F2F2",
    "losangeles85": "#E1DFD0",
    "losangeles90": "#EBE9E0",
    "losangeles95": "#F5F4EF",
}
_M = MARBER

# The page's colours by theme, and the colours of the values a reader matches
# across a page (scriptPubKey, block, proof, UTXO, amount): one thing, one
# colour.  Solarized in the Solarized themes; The Economist's base colours in
# the economist theme.
_SOLARIZED_VALUES = {
    "script": _S["blue"],
    "block": _S["magenta"],
    "proof": _S["violet"],
    "utxo": _S["orange"],
    "amount": _S["green"],
    "good": _S["green"],
    "bad_text": _S["red"],
    "tab": None,
}
THEMES = {
    "paper": {  # a white page; only the terminal blocks are Solarized light
        "bg": "#ffffff",
        "ink": "#1b1b1b",
        "strong": "#111111",
        "muted": "#6b6b6b",
        "rule": "#d6d6d6",
        "rule_strong": "#333333",
        "head": "#f2f3f5",
        "zebra": "#fafafa",
        "accent": "#1f3a5f",
        "term_bg": _S["base3"],
        "term_ink": _S["base00"],
        "term_border": _S["base2"],
        "prompt": _S["base1"],
        "ok": "#0f7a3a",
        "bad": "#b3261e",
        "on_pill": "#ffffff",
        "tile": "#f2f3f5",
        **_SOLARIZED_VALUES,
    },
    "light": {  # Solarized light over the whole page; terminal blocks on base2, the palette's highlight
        "bg": _S["base3"],
        "ink": _S["base01"],
        "strong": _S["base02"],
        "muted": _S["base00"],
        "rule": _S["base2"],
        "rule_strong": _S["base01"],
        "head": _S["base2"],
        "zebra": "#f7f0dc",
        "accent": _S["base01"],
        "term_bg": _S["base2"],
        "term_ink": _S["base00"],
        "term_border": "#e2dac0",
        "prompt": _S["base1"],
        "ok": _S["green"],
        "bad": _S["red"],
        "on_pill": _S["base3"],
        "tile": _S["base2"],
        **_SOLARIZED_VALUES,
    },
    "dark": {  # Solarized dark
        "bg": _S["base03"],
        "ink": _S["base0"],
        "strong": _S["base1"],
        "muted": _S["base00"],
        "rule": _S["base02"],
        "rule_strong": _S["base1"],
        "head": _S["base02"],
        "zebra": "#04303c",
        "accent": _S["base1"],
        "term_bg": _S["base02"],
        "term_ink": _S["base0"],
        "term_border": "#0f4a5a",
        "prompt": _S["base01"],
        "ok": _S["green"],
        "bad": _S["red"],
        "on_pill": _S["base03"],
        "tile": _S["base02"],
        **_SOLARIZED_VALUES,
    },
    "economist": {  # Marber: Los Angeles canvas, London greys, a red tab on each heading, tables ruled not striped
        "bg": _M["losangeles95"],
        "ink": _M["london10"],
        "strong": _M["london5"],
        "muted": _M["london35"],
        "rule": _M["london85"],
        "rule_strong": _M["london20"],
        "head": _M["losangeles95"],
        "zebra": _M["losangeles95"],
        "tile": _M["losangeles90"],
        "accent": _M["london5"],
        "term_bg": _M["losangeles95"],
        "term_ink": _M["london20"],
        "term_border": _M["losangeles85"],
        "prompt": _M["london70"],
        "ok": _M["shanghai35"],
        "bad": _M["red42"],
        "on_pill": "#ffffff",
        # the values: the base colours that carry text on a light canvas; the proof, a blob the reader
        # only matches with the row above it, stays grey so that the other four stand out
        "script": _M["chicago45"],
        "block": _M["tokyo45"],
        "proof": _M["london35"],
        "utxo": _M["hongkong35"],
        "amount": _M["shanghai35"],
        "good": _M["shanghai35"],
        "bad_text": _M["red42"],
        "tab": _M["red"],
    },
}


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
    env.filters["hl"] = _highlight
    env.filters["utc"] = lambda iso: (str(iso).replace("T", " ").replace("Z", " UTC")) if iso else ""
    env.filters["short"] = lambda s, n=16: (s[:n] + "…") if s and len(s) > n else s
    return env


def _breakable(text: str, every: int = 12) -> Markup:
    """A long token with a break opportunity every few characters, so it wraps evenly rather than at slashes.

    ``<wbr>`` adds no character: copying the text yields the token unchanged.
    """
    text = str(text)
    return Markup("<wbr>".join(str(escape(text[i : i + every])) for i in range(0, len(text), every)))


def _highlight(text: str, tokens: list) -> Markup:
    """The values that recur on a UTXO page, coloured so the reader matches them by eye: one thing, one colour, wherever it appears.

    ``tokens`` is a list of ``[role, value]`` or ``[role, value, prefix]``:
    every occurrence of ``value`` (after ``prefix``, which stays uncoloured)
    gets ``<span class="hl-ROLE">``.  A printed command may split a value
    with a backslash-newline; the split stays inside the span.  Earlier
    tokens win where they overlap.  The text is escaped; nothing is added
    that would change what a reader copies.
    """
    text = str(text)
    taken = [False] * len(text)
    spans: list[tuple[int, int, str]] = []
    for role, value, *rest in tokens:
        if not value:
            continue
        prefix = re.escape(rest[0]) if rest else ""
        pattern = prefix + "(" + r"(?:\\\n)?".join(re.escape(c) for c in str(value)) + ")"
        for m in re.finditer(pattern, text):
            start, end = m.span(1)
            if not any(taken[start:end]):
                spans.append((start, end, str(role)))
                taken[start:end] = [True] * (end - start)
    spans.sort()
    parts: list[Markup] = []
    pos = 0
    for start, end, role in spans:
        parts.append(escape(text[pos:start]))
        parts.append(Markup('<span class="hl-{}">{}</span>').format(role, text[start:end]))
        pos = end
    parts.append(escape(text[pos:]))
    return Markup("").join(parts)


def render_html(report: dict, *, explorer: str | None = "https://mempool.space", theme: str = "light") -> str:
    if theme not in THEMES:
        raise ValueError(f"unknown theme {theme!r}; one of {', '.join(THEMES)}")
    return _env().get_template("report.html").render(r=report, explorer=(explorer or "").rstrip("/") or None, t=THEMES[theme])


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
