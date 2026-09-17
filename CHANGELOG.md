# Changelog

## 0.3.4 (2026-09-17)

- Section 3: each address heads its own block with the amount; then message,
  proof, verdict. The verdict names the verifier and each engine with its
  version; the stamp is read from the message itself and no longer repeated.

## 0.3.3 (2026-09-17)

- Holdings at the end of the period are stated per address, each with the
  three inputs of the verification (address, message with its block stamp,
  proof) and the verdict; the separate messages section is gone and outputs
  no longer appear in the statement (they stay in `report.json`). Five
  sections. Each proof names the verifier and the engines that passed.

## 0.3.2 (2026-09-17)

- Times instead of block numbers wherever the reader is not verifying
  something (period, holdings, stamps); blocks stay in parentheses.
- Movements: no block column, no per-transaction detail cards; a payment's
  payee address is listed under the transaction instead.
- Holdings at the end: address and amount, then one proof line (verdict,
  message, stamp time) and the proof itself. Each coin carries when it was
  received.

## 0.3.1 (2026-09-17)

- Closing holdings and their proofs are one table: per output the outpoint,
  address, amount, verdict, message label and stamp, with the signature
  beneath. The bundle section is replaced by a short list of the distinct
  messages signed (A, B, C ...), each with its stamp, verdict and file. Six
  sections instead of seven; nothing about the ledger's internals remains.
- Long signatures wrap evenly.

## 0.3.0 (2026-09-17)

- The report is a statement: header with holder, wallet, period, preparation
  and units; assertion paragraph; checks; holdings at start and end; movements
  with a running balance; proof bundles; signatures; basis of preparation and
  limitations; verification procedures. Accounting conventions: units once,
  negatives in parentheses, double-rule totals, tabular figures.
- `--holder NAME`; a report reference derived from the stated facts (the same
  facts give the same reference), printed on every page and in `report.json`.

## 0.2.3 (2026-09-17)

- Depends on bip322-audit 0.7.1 and, through it, bip322-core 0.6.0: `bip322 reports report ...` works via the core's git-style dispatch.

## 0.2.2 (2026-09-17)

- Report redesign: result on the first page, key figures, a checks table,
  numbered sections, running page headers and footers, tables that keep
  rows together, transaction cards. The "stamped after the period's end"
  check is marked not applicable when the period runs to the tip.

## 0.2.1 (2026-09-17)

- Each closing coin's proof says whether its stamp is after the period's end,
  and the summary counts them: the fact an annual audit wants, established by
  the block stamp alone.

## 0.2.0 (2026-09-17)

- Coverage is by address: a verified proof for a coin's address covers it,
  including a proof made before the output existed (`bip322-audit prove` on
  a change address before the spend is broadcast). The report marks such
  proofs. Requires bip322-audit 0.7.0.
- Packaging: `bip322-audit` is a direct git dependency at a pinned tag, so
  one `pip install` of a git URL installs the whole stack; `[kernel]` chains
  the consensus engine extra through.

## 0.1.1 (2026-09-17)

- `report` copies every referenced `proofs.json` into `<DIR>/ledger/` next
  to the report (`--no-proofs` to skip), so the hand-over needs nothing from
  the ledger directory itself.
- `report.html`: tables fit A4; undefined template variables are errors.
- `setup.sh --pdf` installs WeasyPrint hash-pinned from `requirements-pdf.lock`.

## 0.1.0 (2026-09-17)

- First release: `history`, `block`, `balance`, `report`. Reports with
  opening/closing balances, movements, reconciliation, proof coverage from a
  bip322-audit ledger (re-verified at report time), node cross-check, optional
  fiat valuation from user-supplied rates; HTML, CSV, optional PDF.
- Requires `bip322-audit>=0.6` (for `snapshot --skip-proven` and the ledger
  helper) and therefore `bip322-core>=0.5`.
