"""Record who did what. Entries join the caller's transaction, so an action and its audit
entry succeed or fail together; the table itself is append-only (see alembic revision 0002)."""
import json
from sqlalchemy.orm import Session
from .models import AuditLog, User
from .observability import client_ip_var, request_id_var

def record(db: Session, actor: User | None, action: str, target_type: str | None = None,
           target_id: object = None, **details) -> AuditLog:
    """Add an entry to `db`; the caller commits. Details must stay small and free of secrets or card data."""
    entry = AuditLog(
        actor_id=actor.id if actor else None, actor_email=actor.email if actor else None, action=action,
        target_type=target_type, target_id=None if target_id is None else str(target_id),
        details=json.loads(json.dumps(details, default=str)),
        request_id=request_id_var.get() if request_id_var.get() != "-" else None,
        ip=client_ip_var.get())
    db.add(entry)
    return entry
