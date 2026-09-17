# bip322-reports

Balance reports in which every coin is backed by a verified BIP-322 proof of
control. Built on [bip322-audit](https://github.com/embeddednation/bip322-audit)
(the proof bundles) and [bip322-core](https://github.com/embeddednation/bip322-core)
(the BIP-322 work), for the owner's side: it reads the node wallet's transaction
history and the ledger of proof bundles, and writes a report for a period.

A report answers, for a wallet and a period:

* what the wallet held at the start and at the end (as of two block heights),
* every movement in between, with the wallet's side of each transaction and the exact fee,
* that opening + net = closing,
* and for each closing coin, the proof of control that lists it, re-verified against the node when the report is made.

Two ways of working with it, the same tool for both:

* **Continuously, for yourself.** Before broadcasting a spend, prove its change address (`bip322-audit prove ADDRESS --ledger LEDGER`, sign, finalize): a valid proof means the quorum controls where the change goes, and the output that lands there later is covered by it. New deposit addresses the same way, or with `snapshot --skip-proven LEDGER` after the fact. A report can then be produced at any time, with every coin backed by your own signed message.
* **On demand, for an auditor.** After the period's end, take one bundle over every output under a message that names the audit, and produce the report for the year; the report says for each closing coin whether its proof is stamped after the period's end. The auditor verifies the bundles and the report on their own node with `bip322-audit verify` and `bitcoin-cli`.

## Install

One line, into a fresh venv; bip322-audit and bip322-core come along at their
pinned tags, and the three commands land in the venv's `bin`:

```sh
python3 -m venv ~/.bip322 && ~/.bip322/bin/pip install "bip322-reports[kernel] @ git+ssh://git@github.com/embeddednation/bip322-reports.git@v0.4.2"
export PATH="$HOME/.bip322/bin:$PATH"
bip322 engines && bip322-audit help && bip322-reports help
```

Leave out `[kernel]` on anything but CPython 3.12 / Linux x86_64 (btclib
remains as the verifier). For a reproducible, hash-pinned install, clone and
use the setup script:

```sh
git clone git@github.com:embeddednation/bip322-reports.git && cd bip322-reports
./setup.sh                    # venv, hash-pinned dependencies, bip322-core and bip322-audit at their pinned tags, tests
export PATH="$PWD/.venv/bin:$PATH"
```

`setup.sh` installs the two packages from git at the tags named in the script
(`CORE_REF`, `AUDIT_REF`); `./setup.sh --core ../bip322-core --audit ../bip322-audit`
uses local checkouts, which is the development setup. Nothing here needs the
wallet descriptor: the history comes from the node wallet, the proofs from the
ledger.

PDF output is optional. It needs WeasyPrint's system libraries, then the
renderer itself, hash-pinned like everything else:

```sh
sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b   # Debian/Ubuntu
./setup.sh --pdf                                                   # installs requirements-pdf.lock
```

Without it `report` still writes `report.html` (print it to PDF from a browser)
plus `report.json` and `transactions.csv`; `--pdf` then says what is missing.

## The flow

```sh
# a ledger: any directory where the bip322-audit bundles accumulate.
# before broadcasting a spend: prove its change address
bip322-audit -w treasury prove bc1q...change... --text "Proof of control {date}" --ledger ledger
#   sign to_sign/*.psbt on the cosigners' devices, put the results in signed/, then
bip322-audit finalize ledger/snapshot-<date>-<height>     # valid -> broadcast
# anything that arrived on addresses not yet proven (deposits):
bip322-audit -w treasury snapshot --text "Proof of control {date}" --skip-proven ledger

# the year's report
bip322-reports -w treasury report --year 2026 --ledger ledger
#   -> report-treasury-2026/report.json, report.html, transactions.csv
```

`report` prints a summary on stderr and the directory on stdout:

```
treasury: 2026  blocks 878000 -> 931234  (to tip)
opening 1.23400000 BTC  closing 1.03398110 BTC  net -0.20001890 BTC  (3 transactions, fees 0.00001890 BTC)
reconciliation: ok
proof coverage: 2/2 closing outputs, 1.03398110 BTC
  bundle snapshot-2026-01-05-878123/proofs.json: stamp 878123, signatures 2/2, verified, used for 1
  bundle snapshot-2026-06-14-905410/proofs.json: stamp 905410, signatures 1/1, verified, used for 1
node check (listunspent vs closing coins): ok
RESULT: OK
```

`RESULT: ATTENTION` means the reconciliation failed, a closing coin has no
verified proof, or the node disagrees with the closing coins; the summary and
the report say which. An uncovered coin is fixed by a new bundle with
`--skip-proven`.

## Commands

```
bip322-reports [--cli CMD] [-w NAME] history [-o history.json]
bip322-reports [--cli CMD]           block WHEN
bip322-reports [--cli CMD] [-w NAME] balance [--at WHEN | --height H] [--history FILE]
bip322-reports [--cli CMD] [-w NAME] report (--year Y | --from WHEN --to WHEN | --from-height H --to-height H)
                                            [--ledger DIR]... [--label NAME] [--holder NAME] [--history FILE]
                                            [--rates CSV | --rate N] [--currency CODE] [--explorer URL] [--pdf] [-o DIR]
bip322-reports help [COMMAND]
```

* `history` reads every transaction of the node wallet once and writes it as
  JSON; `balance` and `report` accept it with `--history`, so reports can be
  regenerated without the wallet, or exactly reproduced from the same data.
* `block` resolves a UTC date or instant to the last block before it, the
  rule every period uses. `--year 2026` opens on the last block before
  2026-01-01 and closes on the last block before 2027-01-01, or on the tip when
  that is still in the future. The heights used are printed in the report,
  and `--from-height/--to-height` reproduce a report exactly.
* `--rates date,rate.csv` or `--rate N` with `--currency` adds a fiat value
  per movement (the rate in force is the latest dated row on or before the
  transaction's day). Nothing is fetched; the rates are yours.
* `--explorer URL` sets the block explorer behind the links in the HTML
  (`''` for none).

## What is in the report

The report is laid out as a statement the holder prepares for examination,
following the conventions accountants expect: units declared once in the
header, negatives in parentheses, a single rule above and a double rule under
totals, right-aligned tabular figures with all eight decimals, a running
balance in the movements table, a reference number on every page, and a
section on the basis of preparation and its limitations (point in time,
control is not title, completeness rests on the holder's representation).
`--holder NAME` puts the holder's name in the header.

* Period: the instants asked for and the two blocks they resolved to.
* Summary: opening and closing balance, received, sent, fees, net, the
  reconciliation, the proof coverage, the node cross-check.
* Holdings at the start of the period, per address, and at the end: a
  summary of addresses, control status and amounts, then one page per
  address. The page shows the proof of control in the shape the verifier
  takes it (address, message, proof) with the pasteable `bip322
  verifymessage ...` command and its printed verdict, then each output locked
  to the address with the pasteable `bip322 audit holdings TXID:VOUT --at
  <closing block>` command and its printed answer: the script the output is
  locked to, the amount, and that it was held at the closing block. That
  answer is the link between what a BIP-322 proof is about (a script) and
  what coins are (outputs locked to scripts). A proof is per address, so one
  made before the coins arrived (a change address proven before the spend)
  covers them; the statement says when that is the case.
* Every movement: time, txid, kind (receive, send, internal), net, fee, the
  running balance, and for a payment the address paid.
* How to verify all of it independently.

The report names no descriptor, no xpub and no derivation path; the bundles
it references carry none either. Bundle names are relative to the ledger.

**What to hand over:** the report directory. Besides `report.html`,
`report.json`, `transactions.csv` (and `report.pdf`) it holds `ledger/` with
a copy of every referenced `proofs.json` under the name the report uses, so a
reader can run `bip322-audit verify` on each. Never hand over the ledger
itself: the bundles' PSBT files carry the wallet's xpubs. `--no-proofs`
skips the copy.

## Layout

```
bip322reports/history.py    the node wallet's transactions; coins and balance at any height
bip322reports/period.py     a period resolved to block heights
bip322reports/coverage.py   the ledger's bundles, re-verified; which proof backs which coin
bip322reports/fiat.py       optional valuation from user-supplied rates
bip322reports/report.py     the report as data, and the text summary
bip322reports/render.py     report.html (Jinja2 template), transactions.csv, report.pdf
bip322reports/cli.py        the bip322-reports command
tests/                      a fake node covering both packages' RPCs; an end-to-end test on regtest Core
examples/reports_walkthrough.sh   the flow on a throwaway regtest node
```

The regtest test and the walkthrough need a Bitcoin Core binary: set
`BITCOIN_CORE_DIR`, or run `refcheck/fetch.sh` in the bip322-core checkout the
venv was set up from. CI checks out both dependencies at their pinned tags over
SSH; the repository secrets `BIP322_CORE_DEPLOY_KEY` and
`BIP322_AUDIT_DEPLOY_KEY` must hold read-only deploy keys of those repositories.
