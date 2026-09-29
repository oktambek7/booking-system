import os
from sqlalchemy import select
from .database import Base, engine, SessionLocal
from .models import Role, User
from .security import hash_password

def main():
    email = os.environ["ADMIN_EMAIL"].strip().lower()
    password = os.environ["ADMIN_PASSWORD"]
    if len(password) < 12:
        raise SystemExit("ADMIN_PASSWORD must be at least 12 characters")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user:
            print("Admin account already exists")
            return
        nickname = email.split("@", 1)[0][:32].lower()
        if db.scalar(select(User).where(User.nickname == nickname)):
            nickname = f"admin-{email.split('@', 1)[0][:24].lower()}"
        db.add(User(email=email, name=nickname, nickname=nickname,
                    password_hash=hash_password(password), role=Role.ADMIN))
        db.commit()
        print("Admin account created")

if __name__ == "__main__":
    main()
