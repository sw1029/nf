"""Worker job dispatch adapters."""

from .consistency import run as run_consistency  # noqa: F401
from .export import run as run_export  # noqa: F401
from .index_fts import run as run_index_fts  # noqa: F401
from .index_vec import run as run_index_vec  # noqa: F401
from .ingest import run as run_ingest  # noqa: F401
from .proofread import run as run_proofread  # noqa: F401
from .retrieve_vec import run as run_retrieve_vec  # noqa: F401
from .suggest import run as run_suggest  # noqa: F401
