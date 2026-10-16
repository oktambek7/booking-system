import logging
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from .. import privacy, ratelimit, sessions
from ..database import get_db
from ..mail import send_account_deleted_email
from ..models import User
from ..security import current_user, verify_password

logger = logging.getLogger("parda.privacy")
router = APIRouter()

class AccountDeleteIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    confirm: bool

@router.get("/account/export")
def export_my_data(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Everything held about the signed-in customer, as a JSON download. Secrets and other people's data are never included."""
    ratelimit.hit("account-export", str(user.id), 5, 3600)
    return JSONResponse(privacy.export_account(db, user), headers={
        "Content-Disposition": f'attachment; filename="phantora-data-{date.today().isoformat()}.json"', "Cache-Control": "no-store"})

@router.delete("/account", status_code=204)
def delete_my_account(data: AccountDeleteIn, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Close the account: personal data is erased, paid-ticket records are kept anonymously. Needs the password again."""
    if not data.confirm:
        raise HTTPException(422, "Confirm that you want to delete your account")
    ratelimit.hit("account-delete", str(user.id), 5, 3600)
    try:
        former_email = privacy.delete_account(db, user, verify_password(data.password, user.password_hash))
    except PermissionError:
        raise HTTPException(403, "Password is incorrect") from None
    except privacy.DeletionBlocked as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    sessions.clear_cookie(response)
    try:
        send_account_deleted_email(former_email)
    except Exception:
        logger.warning("Account deleted but the confirmation e-mail could not be sent", exc_info=True)
