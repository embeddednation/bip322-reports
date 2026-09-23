# The yearly proof of control, end to end

What the holder does, what the auditor does, and what the pieces are. The
command references are the three READMEs ([bip322-core](https://github.com/embeddednation/bip322-core),
[bip322-audit](https://github.com/embeddednation/bip322-audit),
[bip322-reports](https://github.com/embeddednation/bip322-reports)); this is the flow. `bip322-reports handbook` prints this file. Everything here is
exercised by `examples/reports_walkthrough.sh` on a throwaway regtest node,
which is the executable version of this document.

## The pieces

* **The wallet.** A descriptor wallet: a 2-of-3 P2WSH quorum on Coldcards,
  or a single-key P2WPKH wallet; the tools do not care which. Bitcoin Core
  holds it watch-only (`importdescriptors`), so the node knows the wallet's
  addresses, coins and transactions and can build PSBTs. No private key
  ever touches a machine running these tools.
* **A proof** (BIP-322, simple format, prefix `smp`) is a message signed by
  the keys that control a scriptPubKey. Its message ends with a block line,
  `block: HEIGHT HASH TIME`, which dates it: a proof cannot be older than
  the block it names. Control of a scriptPubKey covers every UTXO locked to
  it, before or after the proof; a UTXO that arrived after the proof is
  covered only by a later proof.
* **A bundle** is one round of proofs: `bip322-audit snapshot` or `prove`
  writes `snapshot.json`, `message.txt` and `to_sign/to_sign-NN.psbt` (one
  per address); the signers fill `signed/`; `finalize` writes
  `proofs.json`, the only file an auditor needs from it. `proofs.json`
  names addresses, proofs and outputs, and the policy (`2 of 3`); it carries
  no descriptor, xpub, derivation path or wallet name.
* **The ledger** is a directory in which bundles accumulate over the years,
  for example `~/bip322/ledger/`. The PSBTs in it carry the wallet's xpubs,
  so the ledger stays with the holder; the statement copies out only each
  `proofs.json`. Back the ledger up like the wallet's own records.
* **The statement** (`bip322-reports report`) is the document for the
  auditor: opening and closing balances, the movements, the closing UTXOs
  each backed by a verified proof, one page per UTXO with the two commands
  that check it, a section on how a proof works, and notes.

## Install

One line into a fresh venv brings all three packages and the commands
`bip322`, `bip322-audit`, `bip322-reports` (and `bip322 audit …`,
`bip322 reports …` as git-style aliases):

```sh
python3 -m venv ~/.bip322
~/.bip322/bin/pip install "bip322-reports[kernel] @ git+ssh://git@github.com/embeddednation/bip322-reports.git@vX.Y.Z"
```

with the current tag from the reports CHANGELOG. `[kernel]` adds Bitcoin
Core's consensus library as a second verification engine; `[pdf]` adds
WeasyPrint for the PDF (it needs Pango on the machine; see the README).
Upgrading is the same line with the new tag. The commands talk to the node
through `bitcoin-cli`; `--cli "bitcoin-cli -rpcwallet=…"` or `-w NAME`
selects the wallet.

## The year, for the holder

### At year end: the full bundle

Some days into January, when the closing block is buried:

```sh
bip322-audit -w treasury snapshot --text "Proof of control {date}" -o ledger/2026-year-end
```

The stamp is the block six behind the tip; the bundle lists every funded
address and writes one `to_sign` PSBT per address. This is a **full**
snapshot, not `--skip-proven`: every closing UTXO must have a proof dated
after the closing block, including change proven earlier in the year.

### Signing on the Coldcards

Each PSBT is a BIP-322 `to_sign` transaction: it spends a virtual 0-satoshi
output, so the device shows a spend of nothing to `OP_RETURN` and asks for
the message. Sign each PSBT on two devices, each from the unsigned copy,
and put the results into the bundle's `signed/` directory with any names
(`to_sign-01-ccA.psbt`, `to_sign-01-ccC.psbt`, …). A Coldcard refuses to add
a third signature to a PSBT that already carries two; signing the unsigned
copy on each device avoids the question. `finalize` combines them.

### Finalize, verify, report

```sh
bip322-audit finalize ledger/2026-year-end          # combines, finalises, self-verifies, writes proofs.json
bip322-audit verify ledger/2026-year-end             # what the auditor will run; should end in OK
bip322-reports -w treasury report --year 2026 --ledger ledger --dust 1000 --pdf -o treasury-2026
```

`report` reads the wallet's history from the node, verifies every bundle in
the ledger against the node, picks for each closing UTXO the newest proof
that covers it, looks each UTXO up on the chain at the block of its proof,
cross-checks the node's `listunspent`, and prints a summary ending in
`RESULT: OK` or `RESULT: ATTENTION`. `--dust N` leaves outputs of at most N
satoshi out of every figure (unsolicited dust is never spent and never
booked); the notes state the rule.

### What to hand over

The output directory, `treasury-2026/`: the PDF, the JSON with every figure,
the CSV of movements, `fonts/`, and `ledger/…/proofs.json` for each bundle
the statement relies on. Never the ledger itself.

## During the year, for the holder

**Before a spend.** Build the transaction, note its change address, and
prove it before broadcasting:

```sh
bip322-audit -w treasury prove bc1q…change… --text "Proof of control {date}" --ledger ledger
# sign to_sign/*.psbt, put the results in signed/, then
bip322-audit finalize ledger/snapshot-<date>-<height>     # VALID -> broadcast
```

A valid proof means the quorum controls where the change goes. In a
statement produced before the year-end bundle, that UTXO shows AFTER THE
PROOF (received after the block its proof names); the year-end bundle gives
it a proof dated after it.

**New deposit addresses.** Prove them the same way, or after the fact:

```sh
bip322-audit -w treasury snapshot --text "Proof of control {date}" --skip-proven ledger
```

which takes a bundle over the funded addresses the ledger has not proven
yet, and exits non-zero saying so when there are none (in a script, treat
that as "nothing to do").

**A statement at any time.** `bip322-reports report --from 2026-01-01 --to 2026-07-01 --ledger ledger`,
or `--year`, or block heights. Everything in it is backed by the holder's own
proofs; the year-end statement is the same document with the auditor's
bundle.

## The auditor's procedure

What arrives: the statement directory. What is needed: a Bitcoin Core node
with the chain (no wallet, no txindex), and the three packages.

1. **Read the statement.** Page 1: the movements, whose closing row is the
   holdings on the chain, and the closing UTXOs. Any failed check appears
   on page 1 as ATTENTION with a checklist; otherwise nothing says OK
   beyond the figures.
2. **Re-verify the bundles** on your own node:
   `bip322-audit verify treasury-2026/ledger/2026-year-end/proofs.json`.
   This checks every signature with two independent engines, that the
   block named in the message exists at that height with that time, and
   that every output the file lists existed at that block.
3. **Re-run any page.** Each UTXO page prints two commands with their
   output: `bip322 verifymessage <scriptPubKey> <proof> "<message>"`, and
   `bip322 audit holdings <txid>:<vout> --at <block>`. Paste them as they
   stand; the backslashes continue the lines. For a second opinion on a
   proof, `bip322-refcheck` runs reference implementations beside the
   verifier.
4. **Read section 4** for what a proof shows: that at the block named the
   holder could produce a valid spend from the scriptPubKey, which is what
   controlling the UTXOs locked to it means; not who owns the coins, not
   what liabilities stand against them, nothing about any later time.

## Privacy

The auditor learns the wallet's funded addresses, their UTXOs and the
movements, which the statement is for. The auditor does not learn the
descriptor or the xpubs, so cannot derive addresses beyond those shown or
follow the wallet after the period: `proofs.json` and the statement carry
none of that, and the ledger's PSBTs, which do, are never handed over.

## Known limitations

* A spend that is in the mempool but not yet confirmed when the statement
  is made can trip the node cross-check (`listunspent` drops outputs that
  a mempool transaction spends); wait for confirmation or check the summary.
* Completeness rests on the node wallet: the statement covers the
  addresses the node knows, which is the descriptor's whole range as
  imported. That the wallet is the holder's only one is the holder's
  representation.
* The dust rule is the holder's choice, stated in the notes; an auditor may
  ask for a lower threshold.
