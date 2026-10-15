"""Who may manage which cinemas.

An *owner* is an operator (role admin) who is not scoped: they manage everything, including the things that are
global rather than per-cinema (the film catalogue, promotions, catalogue syncs, the audit log, operator accounts).
A *scoped* operator manages only the cinemas listed for them, and is refused the global things.
Customers are never operators; role checks stay in `security.require_roles`.
"""
import sqlalchemy as sa
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from .models import CinemaOperator, Role, User
from .security import require_roles

def scope_of(db: Session, user: User) -> frozenset[str] | None:
    """The cinema names `user` may manage, or None when they may manage all of them (an owner)."""
    if user.role != Role.ADMIN or not user.cinema_scoped:
        return None
    return frozenset(db.scalars(sa.select(CinemaOperator.cinema_name).where(CinemaOperator.user_id == user.id)).all())

def allows(scope: frozenset[str] | None, cinema_name: str) -> bool:
    return scope is None or cinema_name in scope

def require_owner(user: User = Depends(require_roles(Role.ADMIN))) -> User:
    if user.cinema_scoped:
        raise HTTPException(403, "This needs an owner account; your access is limited to your own cinemas")
    return user

owner = Depends(require_owner)

def assignment_map(db: Session) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {}
    for user_id, name in db.execute(sa.select(CinemaOperator.user_id, CinemaOperator.cinema_name)
                                    .order_by(CinemaOperator.cinema_name)):
        result.setdefault(user_id, []).append(name)
    return result
