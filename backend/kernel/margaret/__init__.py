"""Margaret persona layer (I4). Emits text, a persuasion float and at most a draft proposal.

Nothing in this package may import `kernel.state`, `kernel.service`, `kernel.certs`,
`kernel.attest` or `kernel.db`. A `DraftPayment` is a proposal; the kernel turns it into a
payment in PENDING_REVIEW where the extractor and the policy engine decide.
"""

from kernel.margaret.types import (
    SAFE_REPLY,
    DraftPayment,
    Margaret,
    MargaretTurn,
    extract_draft,
    update_persuasion,
)

__all__ = [
    "SAFE_REPLY",
    "DraftPayment",
    "Margaret",
    "MargaretTurn",
    "extract_draft",
    "update_persuasion",
]
