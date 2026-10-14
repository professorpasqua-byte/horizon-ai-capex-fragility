"""Bronze: take every source exactly as delivered, plus load metadata. No cleaning."""

import numpy as np


def to_bronze(landing: dict, batch_id: str = "batch-001") -> dict:
    out = {}
    for name, table in landing.items():
        if name.startswith("latent_"):
            raise ValueError(f"the pipeline may not read answer-key table: {name}")
        n = len(next(iter(table.values())))
        out[name] = dict(
            table, _row_id=np.arange(n), _source=np.full(n, name), _batch_id=np.full(n, batch_id)
        )
    return out
