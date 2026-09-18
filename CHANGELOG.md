# Changelog

## 0.6.5 (2026-09-18)

- Bundled typefaces, embedded in the PDF and copied to `<out>/fonts/` for
  the HTML: Source Serif 4, Source Sans 3, Source Code Pro (SIL OFL,
  `bip322reports/fonts/LICENSE.md`). The Solarized themes are set in the
  sans and the mono; the economist theme in the serif for reading and
  headlines and the sans for labels, tables and metadata, with oldstyle
  figures in running text, as The Economist's own typography prescribes.
- `--heading number|tab|redrule|underline` for the section headings; the
  economist theme's default is `number` (the section number in Economist
  Red, no rules), the Solarized themes' `underline`.
- economist theme: the proof has its colour again (Hong Kong teal); the
  block is Economist Red, the UTXO Chicago navy; the eyebrow is red.

## 0.6.4 (2026-09-18)

- `--theme economist`: The Economist's Marber palette over the whole page;
  the value colours are part of each theme now (Solarized accents in the
  Solarized themes, Marber base colours there, with the proof in grey).
- UTXO pages: the row labels read `scriptPubKey`, `message`, `proof`,
  `verify`, `UTXO`, `lookup` as written; the scriptPubKey row has no
  subtitle; the introductory paragraph on each page is gone and the colour
  legend is stated once, where section 3 introduces the pages.

## 0.6.3 (2026-09-18)

- Solarized light is the default theme. Terminal blocks sit on the page's
  own background with no border, so the value colours read the same
  everywhere.
- The commands' output is the finding: the VALID and HELD badges are gone,
  and the verifier line under them with them (`verifymessage` now ends with
  the tool and specification, `holdings` with the node and the tool). A
  badge follows only for INVALID, NO PROOF, CONTRADICTED, SPENT SINCE,
  AFTER THE PROOF or NOT RUN.
- Requires bip322-audit 0.10.4 (bip322-core 0.9.2).

## 0.6.2 (2026-09-18)

- `report --theme paper|light|dark`: white paper (default), or Solarized
  light or dark over the whole page, margins included; the value colours are
  the same in every theme. Amounts are coloured in the holdings tables too.
- Type a size smaller throughout (9.5pt body, 7.5pt monospace); commands
  are printed 84 characters wide, and a line of the message breaks after a
  space, so a mainnet block line keeps its hash whole. A test runs the
  printed command through bash and compares the arguments.

## 0.6.1 (2026-09-18)

- The `kernel` extra pinned bip322-audit 0.10.2 while the package required
  0.10.3, so `pip install "bip322-reports[kernel] @ ...@v0.6.0"` could not
  resolve. Both pins are 0.10.3; a test now checks that every pin of a
  dependency, and setup.sh, name the same tag.

## 0.6.0 (2026-09-18)

- UTXO pages in colour: one thing, one colour wherever it appears on the
  page (scriptPubKey blue, block magenta, proof violet, UTXO orange, amount
  green; Solarized light), so the block in the message and the block of the
  lookup match by eye and the verifymessage arguments can be told apart.
  Commands and their output are set in terminal blocks in the same palette;
  the page stays white.
- UTXO pages: the timeline row is gone; the HELD line is one clause; all
  monospace values are the same size.
- Requires bip322-audit 0.10.3 (three-line `holdings` output).

## 0.5.5 (2026-09-18)

- The on-chain lookup of each closing UTXO is made at the block named in its
  proof's message (`holdings TXID:VOUT --at <that block>`), not at the
  closing block: control and holding are shown at one block, and "still
  unspent" carries the holding to the closing block. A UTXO received after
  its proof is marked AFTER THE PROOF (not a contradiction; the year-end
  bundle gives it a later proof) and the summary counts these separately.
- Smaller title, wrapping, for long wallet names.
- Walkthrough: a full year-end bundle before the report.

## 0.5.4 (2026-09-18)

- The statement is named after the node wallet; `--label` is gone.
- The checks are four short lines; the paragraph beneath them is gone.
- UTXO pages: no bold; a timeline line under the lookup: received, proof
  dated, closing block, and what that order means for the proof.

## 0.5.3 (2026-09-18)

- UTXO pages: no address line; the scriptPubKey and the UTXO are set alike,
  both linked to the transaction with details; the page heading links too.
- Requires bip322-audit 0.10.2 (terser holdings status).

## 0.5.2 (2026-09-18)

- Front page: opening balance, transactions, closing balance and the
  difference as the four figures and a reconciliation table; the checks are
  a short list without the assertion paragraph. Table 3 lists each UTXO with
  its scriptPubKey only, linked to the transaction with details expanded
  (`?showDetails=true`), where the explorer shows that scriptPubKey.

## 0.5.1 (2026-09-18)

- UTXO pages: proof of control first, then the chain's record. The lookup
  output is terse (locked to, amount, confirmed, status).
- Requires bip322-core 0.9.1 and bip322-audit 0.10.1.

## 0.5.0 (2026-09-18)

- Section 3 lists UTXOs with the scriptPubKey each is locked to (address
  beneath, as its encoding). Section 4 is one page per UTXO: the on-chain
  lookup, then the proof verified with `bip322 verifymessage <scriptPubKey>`
  on the bytes the lookup reported, quoted with its output. The statement
  re-verifies each proof that way when prepared.
- Requires bip322-core 0.9.0 and bip322-audit 0.10.0.

## 0.4.4 (2026-09-17)

- Section 3 lists the unspent outputs with the address each is locked to.
  Each address page is three steps: the address opened into its
  scriptPubKey (`bip322 validateaddress`), the proof of control verified,
  and the output looked up on the chain, locked to the same bytes. The
  `decodesignature` derivation is out of the page and into the procedures.
- Requires bip322-core 0.8.1 and bip322-audit 0.9.5.

## 0.4.3 (2026-09-17)

- Each address page has a *script* step: `bip322 decodesignature --text`
  and its output, deriving the scriptPubKey from the script inside the proof,
  with a badge saying it is the page's address. The page and the basis section
  say what is proven, a scriptPubKey, and how outputs are tied to it.
- Long single-word arguments in printed commands are split with `\` too.
- Requires bip322-core 0.7.0 and bip322-audit 0.9.3.

## 0.4.2 (2026-09-17)

- Section 3 is the summary of addresses, control status and amounts;
  section 4 is one page per address: proof of control, then each output
  locked to the address with its on-chain lookup, which now prints the
  locking script. The basis section states the link: a proof is about a
  script, coins are outputs locked to scripts, the node reports which.
- Requires bip322-audit 0.9.2.

## 0.4.1 (2026-09-17)

- Proof of control (section 3) and holdings (section 4) are separate
  sections: control per address; holdings as a summary table, then one
  block per output with the on-chain check by direct lookup (`holdings
  TXID:VOUT`, instant; the UTXO-set scan is no longer used).
- Printed commands are pasteable: lines end in `\` continuations, no
  soft wrapping, verified to reassemble exactly in bash. `--no-onchain` is gone.
- Requires bip322-audit 0.9.1.

## 0.4.0 (2026-09-17)

- Section 3 shows, per address, the two checks a reader repeats as the
  command to run and what it printed when the statement was prepared:
  `bip322 verifymessage ADDRESS PROOF MESSAGE` with its verdict and engine
  lines, and `bip322 audit holdings ADDRESS --at <closing block>` with the
  outputs it found. The on-chain step runs at preparation time (a UTXO-set
  scan; `--no-onchain` skips it) and the checks table gains a row for it:
  holding less than stated means coins were spent since, holding more means
  the statement missed coins and fails it.
- Requires bip322-audit 0.8.1 (the `holdings` command) and bip322-core 0.6.2.

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
