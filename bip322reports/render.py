"""report.html, transactions.csv and, when WeasyPrint is installed, report.pdf."""

from __future__ import annotations

import csv
import re
import shutil
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
    "gold": "#7D6210",  # New York 55 at half strength: the palette's yellow made fit for text
    "losangeles85": "#E1DFD0",
    "losangeles90": "#EBE9E0",
    "losangeles95": "#F5F4EF",
}
_M = MARBER

# The page's colours by theme, and the colours of the values a reader matches
# across a page (scriptPubKey, block, proof, UTXO, amount): one thing, one
# colour.  Solarized in the Solarized themes; The Economist's base colours in
# the economist theme.
#: Bundled typefaces (SIL OFL; see fonts/LICENSE.md): Adobe's Source Serif 4 and Source Sans 3, the open
#: counterparts of a newspaper's serif for reading and sans for labels and tables, and JetBrains Mono for hashes.
FONTS_DIR = Path(__file__).parent / "fonts"
FONT_FACES = [  # family, file, weight, style
    ("Source Serif 4", "SourceSerif4-Regular.woff2", 400, "normal"),
    ("Source Serif 4", "SourceSerif4-It.woff2", 400, "italic"),
    ("Source Serif 4", "SourceSerif4-Semibold.woff2", 600, "normal"),
    ("Source Serif 4", "SourceSerif4-Bold.woff2", 700, "normal"),
    ("Source Sans 3", "SourceSans3-Regular.woff2", 400, "normal"),
    ("Source Sans 3", "SourceSans3-It.woff2", 400, "italic"),
    ("Source Sans 3", "SourceSans3-Semibold.woff2", 600, "normal"),
    ("Source Sans 3", "SourceSans3-Bold.woff2", 700, "normal"),
    ("JetBrains Mono", "JetBrainsMono-Regular.woff2", 400, "normal"),
    ("JetBrains Mono", "JetBrainsMono-Bold.woff2", 700, "normal"),
]
SANS = '"Source Sans 3", "Helvetica Neue", Arial, "DejaVu Sans", sans-serif'
SERIF = '"Source Serif 4", Georgia, "Times New Roman", "DejaVu Serif", serif'
MONO = '"JetBrains Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace'

#: How section headings are set: coloured text over a coloured rule; a red tab over a grey rule (The
#: Economist's chart signature); black text with the section number in red; black text over a thin red rule.
HEADINGS = ("underline", "tab", "number", "redrule")

#: The values a reader matches across the statement, each with one colour; hash and txid appear in section 4 only.
VALUE_ROLES = ("script", "block", "proof", "utxo", "amount", "hash", "txid")


_SOLARIZED_VALUES = {
    "script": _S["blue"],
    "block": _S["magenta"],
    "proof": _S["violet"],
    "utxo": _S["orange"],
    "amount": _S["green"],
    "hash": _S["cyan"],
    "txid": _S["yellow"],
    "good": _S["green"],
    "bad_text": _S["red"],
    "tab": None,
    "heading": "underline",
    "font_body": SANS,
    "font_heading": SANS,
    "font_label": SANS,
    "font_mono": MONO,
    "oldstyle": False,
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
        # the values: the brand red for the block, base colours that carry text for the rest; the proof, a blob
        # matched only with the row above it, takes the one light colour
        "script": _M["chicago45"],
        "block": _M["red"],
        "proof": _M["singapore55"],
        "utxo": _M["hongkong35"],
        "amount": _M["shanghai35"],
        "hash": _M["tokyo35"],
        "txid": _M["gold"],
        "good": _M["shanghai35"],
        "bad_text": _M["tokyo45"],
        "tab": _M["red"],
        "heading": "number",
        # like Economist Serif and Sans: serif for reading and headlines, sans for labels, tables and metadata
        "font_body": SERIF,
        "font_heading": SERIF,
        "font_label": SANS,
        "font_mono": MONO,
        "oldstyle": True,
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


def render_html(
    report: dict,
    *,
    explorer: str | None = "https://mempool.space",
    theme: str = "economist",
    heading: str | None = None,
    fonts_url: str = "fonts/",
) -> str:
    """The statement as HTML.  Fonts are referenced at ``fonts_url`` (see ``copy_fonts``); ``heading`` overrides the theme's heading style."""
    if theme not in THEMES:
        raise ValueError(f"unknown theme {theme!r}; one of {', '.join(THEMES)}")
    if heading is not None and heading not in HEADINGS:
        raise ValueError(f"unknown heading style {heading!r}; one of {', '.join(HEADINGS)}")
    t = {**THEMES[theme], "heading": heading or THEMES[theme]["heading"]}
    faces = [{"family": f, "url": fonts_url + file, "weight": w, "style": s} for f, file, w, s in FONT_FACES]
    return _env().get_template("report.html").render(r=report, explorer=(explorer or "").rstrip("/") or None, t=t, faces=faces)


def copy_fonts(directory: Path) -> Path:
    """Put the bundled fonts next to a report, in ``fonts/``, where its HTML and PDF find them."""
    target = directory / "fonts"
    target.mkdir(parents=True, exist_ok=True)
    for _family, file, _w, _s in FONT_FACES:
        shutil.copyfile(FONTS_DIR / file, target / file)
    shutil.copyfile(FONTS_DIR / "LICENSE.md", target / "LICENSE.md")
    return target


def write_csv(report: dict, path: Path) -> None:
    fiat = report.get("fiat")
    fields = (
        ["time_utc", "height", "txid", "kind", "amount_btc", "fee_btc", "net_btc"]
        + (["rate", "amount_fiat", "fee_fiat", "net_fiat"] if fiat else [])
        + ["ours_in", "ours_out", "others_out"]
    )
    with Path(path).open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for tx in report["transactions"]:
            row = {k: tx.get(k) for k in ("time_utc", "height", "txid", "kind", "amount_btc", "fee_btc", "net_btc")}
            if fiat:
                row.update(
                    {
                        "rate": tx["fiat"]["rate"],
                        "amount_fiat": tx["fiat"]["amount"],
                        "fee_fiat": tx["fiat"]["fee"],
                        "net_fiat": tx["fiat"]["net"],
                    }
                )
            for key in ("ours_in", "ours_out", "others_out"):
                row[key] = " ".join(f"{c['address']}={c['amount_btc']}" for c in tx[key])
            w.writerow(row)


def write_pdf(html: str, path: Path) -> None:
    """Render the HTML to ``path``; relative URLs in it (the fonts) resolve next to ``path``."""
    try:
        from weasyprint import HTML
    except Exception as exc:  # ImportError, or an OSError when its system libraries (Pango) are missing
        raise RuntimeError(
            f"PDF output needs WeasyPrint and its system libraries: pip install 'bip322-reports[pdf]' (see the README) [{exc}]"
        ) from exc
    HTML(string=html, base_url=str(path.parent) + "/").write_pdf(str(path))
