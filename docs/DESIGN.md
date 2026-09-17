# bip322-reports: design notes

What the report claims, how each claim is established, and what the tool
deliberately does not do. The proofs themselves are bip322-audit's business
(see its `docs/DESIGN.md`); this package only reads and re-verifies them.

## Claims and their evidence

* **Balances at a block.** The wallet's unspent outputs after every block up
  to and including the height, computed from the wallet's own transaction
  history: every output paying a wallet address, minus every such output spent
  by a transaction confirmed at or before that height. Unconfirmed transactions
  count for nothing; conflicted ones are dropped.
* **Movements.** The transactions confirmed strictly after the opening block
  and up to the closing block, each reduced to the wallet's side: outputs it
  spent, outputs it received, outputs that left. Net is received minus spent.
  The fee is exact when every input was the wallet's (inputs minus all
  outputs); it does not rely on the wallet's own fee bookkeeping.
* **Reconciliation.** Opening + net = closing. Because both sides come from the
  same history this is an internal consistency check, not an external one; it
  catches gaps in the history (a transaction the wallet did not see).
* **Node cross-check.** When the period ends at the tip the history was taken
  at, the closing coins must equal `listunspent`. This is the external check
  on the history.
* **Coverage.** A closing coin is covered when a bundle's snapshot lists that
  exact output and the bundle verifies now: every signature valid, the stamp
  block in the main chain, no listed output contradicted by the node. Among
  several covering bundles the verified one with the latest stamp is shown;
  the others are counted. A stamp after the closing block is fine: an output
  unspent at a later block was unspent at the closing block, and control of the
  address is what the proof shows.
* **The verdict.** `RESULT: OK` when the reconciliation holds, every closing
  coin is covered, and the node cross-check either agrees or could not be run.

## Periods

Calendar bounds are instants in UTC. Each maps to the last block whose header
time is before the instant, found by binary search over headers. Header times
are not strictly monotonic, so the boundary is conventional rather than
unique; the report prints the heights it used, and `--from-height/--to-height`
reproduce any report exactly. An end instant in the future means the period
runs to the tip. A start before the chain's first block opens on block 0.

## Why a ledger and not a database

The legacy tool this replaces kept balance snapshots and signatures in a
database and picked the latest snapshot before a date, so a report was only
as fresh as the last snapshot taken. Here the history is recomputed from the
node every time, or reproduced from a cached `history.json`, and the record
of proofs is the ledger: bip322-audit's bundles on disk, each self-contained
and independently verifiable. There is nothing else to keep in sync.

## What is left out on purpose

* No descriptor, xpub or derivation path anywhere in the output: the report
  names addresses and outputs, like the bundles do.
* No fetched prices: a fiat valuation uses only rates the user supplies.
* No email, no database, no browser engine: HTML from a template, CSV, and
  optionally a PDF through WeasyPrint.
* No signing: proofs are produced with bip322-audit and the devices.

## Trust

Owner-side tooling: it needs the node wallet (watch-only is enough) and reads
the ledger. What it hands to a reader, the report and the bundles, is
checkable on any node with the chain and no wallet: `bip322-audit verify` for
the bundles, `gettxout` and the transactions by txid for the balances and
movements. The report says so in its last section.
