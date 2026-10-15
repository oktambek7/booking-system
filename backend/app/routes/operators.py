"""Operator accounts: who is an operator and which cinemas each may manage. Owners only."""
import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import sessions
from ..audit import record
from ..database import get_db
from ..models import Auditorium, CinemaOperator, Role, User
from ..operators import assignment_map, owner
from ..schemas import OperatorGrantIn, OperatorOut

router = APIRouter()

# Operator changes run one at a time, and the actor is re-read after taking the lock. An owner may not change
# themselves, so some owner always remains: the one making the request. Without the lock two owners could demote
# each other in the same instant and leave none.
OPERATOR_LOCK = 7_240_001

def _begin(db: Session, actor: User) -> None:
    db.execute(sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": OPERATOR_LOCK})
    db.refresh(actor)
    if actor.role != Role.ADMIN or actor.cinema_scoped or not actor.active:
        raise HTTPException(403, "Your access changed while this request was being processed")

def _out(user: User, cinemas: list[str]) -> OperatorOut:
    return OperatorOut(user_id=user.id, email=user.email, nickname=user.nickname, active=user.active,
                       owner=not user.cinema_scoped, cinemas=[] if not user.cinema_scoped else cinemas)

@router.get("/admin/operators", response_model=list[OperatorOut])
def list_operators(db: Session = Depends(get_db), _: User = owner):
    assigned = assignment_map(db)
    users = db.scalars(sa.select(User).where(User.role == Role.ADMIN).order_by(User.id)).all()
    return [_out(user, assigned.get(user.id, [])) for user in users]

@router.put("/admin/operators", response_model=OperatorOut)
def grant_operator(data: OperatorGrantIn, db: Session = Depends(get_db), actor: User = owner):
    """Make an existing, verified account an operator. `cinemas: null` makes them an owner; a list scopes them."""
    _begin(db, actor)
    target = db.scalar(sa.select(User).where(sa.func.lower(User.email) == str(data.email).lower()).with_for_update())
    if not target:
        raise HTTPException(404, "No account has this e-mail. They need to register first")
    if target.id == actor.id:
        raise HTTPException(409, "You cannot change your own access; ask another owner")
    if not target.active or not target.email_verified:
        raise HTTPException(409, "The account must be active and have a verified e-mail")
    cinemas = None if data.cinemas is None else sorted({name.strip() for name in data.cinemas if name.strip()})
    if cinemas is not None:
        known = set(db.scalars(sa.select(Auditorium.cinema_name).distinct()).all())
        unknown = [name for name in cinemas if name not in known]
        if unknown:
            raise HTTPException(422, "Unknown cinema: " + ", ".join(unknown))
    before = {"role": target.role.value, "owner": target.role == Role.ADMIN and not target.cinema_scoped,
              "cinemas": assignment_map(db).get(target.id, []) if target.cinema_scoped else []}
    target.role = Role.ADMIN
    target.cinema_scoped = cinemas is not None
    db.execute(sa.delete(CinemaOperator).where(CinemaOperator.user_id == target.id))
    for name in cinemas or []:
        db.add(CinemaOperator(user_id=target.id, cinema_name=name))
    record(db, actor, "operator.granted", "user", target.id, email=target.email, before=before,
           owner=cinemas is None, cinemas=cinemas or [])
    db.commit()
    return _out(target, cinemas or [])

@router.delete("/admin/operators/{user_id}", status_code=204)
def revoke_operator(user_id: int, db: Session = Depends(get_db), actor: User = owner):
    """Turn an operator back into an ordinary customer and end their sessions."""
    _begin(db, actor)
    target = db.scalar(sa.select(User).where(User.id == user_id, User.role == Role.ADMIN).with_for_update())
    if not target:
        raise HTTPException(404, "Operator not found")
    if target.id == actor.id:
        raise HTTPException(409, "You cannot remove your own operator role; ask another owner")
    target.role = Role.CUSTOMER
    target.cinema_scoped = False
    db.execute(sa.delete(CinemaOperator).where(CinemaOperator.user_id == target.id))
    target.token_version = (target.token_version or 0) + 1          # signs them out everywhere
    sessions.revoke_user_sessions(db, target.id)
    record(db, actor, "operator.revoked", "user", target.id, email=target.email)
    db.commit()
