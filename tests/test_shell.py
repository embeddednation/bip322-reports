"""The printed verifymessage command reassembles to its argv in bash, line by line as the statement shows it."""

import subprocess

from bip322reports.report import WIDTH, shell_command

SPK = "0020" + "ab" * 32
SIG = "smp" + "A" * 300 + "+/=="
HASH = "0000000000000000000123456789abcdef0123456789abcdef0123456789abcd"
MESSAGE = f'Proof of control 2026-09-18 "quoted" $HOME `x`\nblock: 967247 {HASH} 2026-09-18T10:37:00Z'


def test_bash_reassembles_the_printed_command():
    argv = ["printf", "%s\x1f", SPK, SIG, MESSAGE]
    text = shell_command(argv)
    assert all(len(line) <= WIDTH + 2 for line in text.splitlines())  # WIDTH plus " \\"
    assert any(line.startswith(f"block: 967247 {HASH}") for line in text.splitlines())  # the block line keeps its hash whole
    out = subprocess.run(["bash", "-c", text], capture_output=True, text=True, check=True).stdout
    assert out.split("\x1f")[:-1] == argv[2:]
