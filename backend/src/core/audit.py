"""Audit logging utility for tracking AI interactions."""

import json
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from src.database.models import AuditLog
from src.database.session import SessionLocal

logger = structlog.get_logger()


def log_action(
    action: str,
    user_id: Optional[int] = None,
    detail: Optional[dict] = None,
    ip_address: Optional[str] = None,
):
    """Write an audit log entry to the database.

    Args:
        action: Action type (login, chat, upload_ifc, design, graph_query)
        user_id: ID of the user performing the action
        detail: Dict with request/response summary (will be JSON-serialized)
        ip_address: Client IP address
    """
    db: Session = SessionLocal()
    try:
        entry = AuditLog(
            user_id=user_id,
            action=action,
            detail=json.dumps(detail, ensure_ascii=False, default=str) if detail else None,
            ip_address=ip_address,
        )
        db.add(entry)
        db.commit()
    except Exception as e:
        logger.warning("audit_log_failed", error=str(e))
        db.rollback()
    finally:
        db.close()
