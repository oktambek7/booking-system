import enum
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, JSON,
                        Integer, Numeric, String, Text, UniqueConstraint, func, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

class Role(str, enum.Enum):
    CUSTOMER = "customer"
    ADMIN = "admin"

class BookingStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    nickname: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.CUSTOMER)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Movie(Base):
    __tablename__ = "movies"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(180), index=True)
    synopsis: Mapped[str] = mapped_column(Text, default="")
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    genre: Mapped[str] = mapped_column(String(100), default="Drama")
    age_rating: Mapped[str] = mapped_column(String(12), default="13+")
    language: Mapped[str] = mapped_column(String(60), default="O‘zbekcha")
    poster_url: Mapped[str] = mapped_column(String(800), default="")
    backdrop_url: Mapped[str] = mapped_column(String(800), default="")
    tmdb_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    release_date: Mapped[date | None] = mapped_column(Date)
    vote_average: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    cast_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    trailer_key: Mapped[str | None] = mapped_column(String(100))
    catalog_status: Mapped[str] = mapped_column(String(20), default="now_playing")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("duration_minutes IS NULL OR duration_minutes > 0", name="ck_movie_duration_positive"),)

class Auditorium(Base):
    __tablename__ = "auditoriums"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    cinema_name: Mapped[str] = mapped_column(String(140), default="Kino")
    city: Mapped[str] = mapped_column(String(100), default="Tashkent")
    address: Mapped[str] = mapped_column(String(300), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Tashkent")
    formats: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["2D"])
    hall_type: Mapped[str] = mapped_column(String(12), default="standard")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    seats: Mapped[list["Seat"]] = relationship(back_populates="auditorium", cascade="all, delete-orphan")

class Seat(Base):
    __tablename__ = "seats"
    id: Mapped[int] = mapped_column(primary_key=True)
    auditorium_id: Mapped[int] = mapped_column(ForeignKey("auditoriums.id", ondelete="CASCADE"), index=True)
    row_label: Mapped[str] = mapped_column(String(5))
    seat_number: Mapped[int] = mapped_column(Integer)
    seat_type: Mapped[str] = mapped_column(String(20), default="standard")
    __table_args__ = (UniqueConstraint("auditorium_id", "row_label", "seat_number", name="uq_auditorium_seat"),
                      CheckConstraint("seat_number > 0", name="ck_seat_number_positive"))
    auditorium: Mapped[Auditorium] = relationship(back_populates="seats")

class Screening(Base):
    __tablename__ = "screenings"
    id: Mapped[int] = mapped_column(primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id"), index=True)
    auditorium_id: Mapped[int] = mapped_column(ForeignKey("auditoriums.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    base_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    premium_surcharge: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    format_type: Mapped[str] = mapped_column(String(8), default="2D")
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    movie: Mapped[Movie] = relationship()
    auditorium: Mapped[Auditorium] = relationship()
    __table_args__ = (CheckConstraint("starts_at < ends_at", name="ck_screening_time_range"),
                      CheckConstraint("base_price >= 0 AND premium_surcharge >= 0", name="ck_screening_price_nonnegative"))

class CatalogScreeningLink(Base):
    """One owned seat map for one source repertory item.

    The public schedule id is unique.  This lets concurrent visitors select
    the same time without producing two independent Parda seat inventories.
    """
    __tablename__ = "catalog_screening_links"
    source_repertory_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    screening_id: Mapped[int] = mapped_column(ForeignKey("screenings.id", ondelete="CASCADE"), unique=True, index=True)
    source_name: Mapped[str] = mapped_column(String(40), default="cinematica")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    screening: Mapped["Screening"] = relationship()

class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    screening_id: Mapped[int] = mapped_column(ForeignKey("screenings.id"), index=True)
    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus), default=BookingStatus.PENDING, index=True)
    seat_count: Mapped[int] = mapped_column(Integer)
    total_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archived_by_customer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    customer: Mapped[User] = relationship()
    screening: Mapped[Screening] = relationship()
    seat_assignments: Mapped[list["BookingSeat"]] = relationship(back_populates="booking", cascade="all, delete-orphan")

class BookingSeat(Base):
    __tablename__ = "booking_seats"
    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True)
    screening_id: Mapped[int] = mapped_column(ForeignKey("screenings.id"), index=True)
    seat_id: Mapped[int] = mapped_column(ForeignKey("seats.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    booking: Mapped[Booking] = relationship(back_populates="seat_assignments")
    seat: Mapped[Seat] = relationship()
    __table_args__ = (Index("uq_active_screening_seat", "screening_id", "seat_id", unique=True,
                            postgresql_where=text("active IS TRUE")),)

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True)
    reference: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    method: Mapped[str] = mapped_column(String(20))
    # A card's final four digits are sufficient for a receipt. Full PANs and
    # CVVs must never enter this model or the database.
    card_last4: Mapped[str] = mapped_column(String(4))
    # Kept nullable only for compatibility with the retired SMS migration.
    # New payment code never reads or writes it.
    legacy_phone_last4: Mapped[str | None] = mapped_column("phone_last4", String(4), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(24), default="awaiting_verification")
    provider: Mapped[str] = mapped_column(String(24), default="mock")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    booking: Mapped[Booking] = relationship()
    __table_args__ = (Index("uq_open_payment_per_booking", "booking_id", unique=True,
                            postgresql_where=text("status = 'awaiting_verification'")),)

class OtpChallenge(Base):
    __tablename__ = "otp_challenges"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    phone: Mapped[str] = mapped_column(String(20))
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class EmailOtpChallenge(Base):
    __tablename__ = "email_otp_challenges"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class PaymentEmailChallenge(Base):
    __tablename__ = "payment_email_challenges"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
