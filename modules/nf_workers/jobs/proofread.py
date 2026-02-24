from __future__ import annotations

from modules.nf_workers.contracts import JobContext


def run(ctx: JobContext) -> None:
    from modules.nf_workers import runner

    runner._handle_proofread(ctx)
