"""Audit trail for access to patient data ."""

import json
import logging
import sys
from datetime import UTC, datetime

logger = logging.getLogger("mshauri.audit")
_configured = False


def configure_audit_logging() -> None:
    """Send audit records to stdout as JSON lines. Idempotent."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    _configured = True


def audit(
    action: str,
    actor_sub: str,
    role: str | None,
    outcome: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    reason: str | None = None,
) -> None:
    record = {
        "ts": datetime.now(UTC).isoformat(),
        "action": action,
        "actor": actor_sub,
        "role": role,
        "outcome": outcome,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "reason": reason,
    }
    logger.info(json.dumps({key: value for key, value in record.items() if value is not None}))
