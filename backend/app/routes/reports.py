from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from .. import ratelimit, reports
from ..audit import record
from ..database import get_db
from ..models import Role, User
from ..operators import scope_of
from ..security import require_roles

router = APIRouter()
admin = Depends(require_roles(Role.ADMIN))

def _stream(kind: str, generator, start: date, end: date, db: Session, actor: User) -> StreamingResponse:
    ratelimit.hit("report-export", str(actor.id), 30, 3600)
    scope = scope_of(db, actor)
    record(db, actor, "report.exported", "report", kind, start=start.isoformat(), end=end.isoformat(),
           cinemas=None if scope is None else sorted(scope))
    db.commit()
    return StreamingResponse(generator(start, end, scope), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="phantora-{kind}-{start.isoformat()}_{end.isoformat()}.csv"', "Cache-Control": "no-store"})

def _checked(start: date, end: date) -> None:
    try:
        reports.validate_range(start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

@router.get("/admin/reports/bookings.csv")
def bookings_report(start: date = Query(alias="from"), end: date = Query(alias="to"), db: Session = Depends(get_db), actor: User = admin):
    """Every booking whose screening starts between the two dates (inclusive, business time zone)."""
    _checked(start, end)
    return _stream("bookings", reports.bookings_csv, start, end, db, actor)

@router.get("/admin/reports/revenue.csv")
def revenue_report(start: date = Query(alias="from"), end: date = Query(alias="to"), db: Session = Depends(get_db), actor: User = admin):
    """Money paid, refunded and kept per screening day, hall and film."""
    _checked(start, end)
    return _stream("revenue", reports.revenue_csv, start, end, db, actor)
