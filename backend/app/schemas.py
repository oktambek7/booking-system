from datetime import date, datetime
from enum import Enum
from typing import Literal
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from .models import BookingStatus

class UserCreate(BaseModel):
    nickname: str = Field(min_length=2, max_length=40, pattern=r"^[\w.-]+$")
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)

class EmailCodeVerify(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{4}$")

class EmailResend(BaseModel):
    email: EmailStr

class PasswordResetRequest(BaseModel):
    email: EmailStr

class PasswordResetConfirm(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{4}$")
    password: str = Field(min_length=10, max_length=128)

class EmailChallengeOut(BaseModel):
    email: EmailStr
    expires_at: datetime
    resend_available_at: datetime | None = None
    demo_mode: bool
    demo_code: str | None = None

class Login(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class MovieIn(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    synopsis: str = Field(default="", max_length=5000)
    duration_minutes: int | None = Field(default=None, gt=0, le=360)
    genre: str = Field(default="Drama", max_length=100)
    age_rating: str = Field(default="13+", max_length=12)
    language: str = Field(default="O‘zbekcha", max_length=60)
    poster_url: str = Field(default="", max_length=800)

class MovieOut(MovieIn):
    id: int
    active: bool
    backdrop_url: str = ""
    tmdb_id: int | None = None
    release_date: date | None = None
    vote_average: Decimal | None = None
    cast_names: list[str] = Field(default_factory=list)
    trailer_key: str | None = None
    catalog_status: str = "now_playing"
    model_config = ConfigDict(from_attributes=True)

class AuditoriumIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    cinema_name: str = Field(min_length=1, max_length=140)
    city: str = Field(default="Tashkent", max_length=100)
    address: str = Field(default="", max_length=300)
    timezone: str = "Asia/Tashkent"
    formats: list[Literal["2D", "3D", "IMAX"]] = Field(default_factory=lambda: ["2D"], min_length=1, max_length=3)
    hall_type: Literal["standard", "vip"] = "standard"
    row_count: int = Field(ge=1, le=26)
    seats_per_row: int = Field(ge=1, le=30)

class AuditoriumUpdate(BaseModel):
    address: str | None = Field(default=None, max_length=300)
    latitude: Decimal | None = Field(default=None, ge=Decimal("-90"), le=Decimal("90"))
    longitude: Decimal | None = Field(default=None, ge=Decimal("-180"), le=Decimal("180"))
    hall_type: Literal["standard", "vip"] | None = None
    active: bool | None = None
    formats: list[Literal["2D", "3D", "IMAX"]] | None = None

class AuditoriumOut(BaseModel):
    id: int
    name: str
    cinema_name: str
    city: str
    address: str
    timezone: str
    formats: list[str] = Field(default_factory=lambda: ["2D"])
    hall_type: Literal["standard", "vip"] = "standard"
    active: bool = True
    seat_count: int
    source_name: str | None = None
    external_cinema_id: int | None = None
    external_hall_id: int | None = None
    source_url: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    last_synced_at: datetime | None = None

class NearbyAuditoriumOut(AuditoriumOut):
    distance_km: float

class ScreeningIn(BaseModel):
    movie_id: int
    auditorium_id: int
    starts_at: datetime
    base_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    premium_surcharge: Decimal = Field(default=0, ge=0, max_digits=12, decimal_places=2)
    format_type: str = Field(default="2D", pattern=r"^(2D|3D|IMAX)$")


class ScreeningOut(BaseModel):
    id: int
    movie_id: int
    auditorium_id: int
    starts_at: datetime
    ends_at: datetime
    base_price: Decimal
    premium_surcharge: Decimal
    format_type: str
    movie_title: str
    duration_minutes: int | None
    cinema_name: str
    auditorium_name: str
    hall_type: Literal["standard", "vip"] = "standard"
    city: str
    timezone: str
    available_seats: int

class SeatOut(BaseModel):
    id: int
    row_label: str
    seat_number: int
    seat_type: str
    price: Decimal
    available: bool

class ScreeningSeatsOut(BaseModel):
    screening: ScreeningOut
    seats: list[SeatOut]

class BookingIn(BaseModel):
    screening_id: int
    seat_ids: list[int] = Field(min_length=1, max_length=8)

class BookingOut(BaseModel):
    id: int
    customer_id: int
    screening_id: int
    status: BookingStatus
    seat_count: int
    total_price: Decimal
    hold_expires_at: datetime | None
    created_at: datetime
    ends_at: datetime
    ticket_code: str | None = None
    checked_in_at: datetime | None = None
    movie_title: str
    starts_at: datetime
    cinema_name: str
    auditorium_name: str
    seats: list[str]

class BookingStatusIn(BaseModel):
    status: BookingStatus

class TicketCheckInIn(BaseModel):
    ticket_code: str = Field(min_length=6, max_length=16, pattern=r"^[A-Za-z0-9-]+$")

class TicketCheckInOut(BaseModel):
    booking: BookingOut
    checked_in_at: datetime

class OperatorMetricsOut(BaseModel):
    date: date
    screenings: int
    upcoming_screenings: int
    bookings: int
    confirmed_bookings: int
    pending_bookings: int
    seats_sold: int
    seats_available: int
    confirmed_revenue: Decimal

class OperatorScreeningOut(ScreeningOut):
    booking_count: int
    seats_sold: int
    confirmed_revenue: Decimal

class OperatorBookingOut(BookingOut):
    customer_nickname: str
    customer_email: EmailStr

class OperatorDashboardOut(BaseModel):
    metrics: OperatorMetricsOut
    screenings: list[OperatorScreeningOut]
    bookings: list[OperatorBookingOut]

class PaymentMethod(str, Enum):
    UZCARD = "uzcard"
    HUMO = "humo"
    VISA = "visa"
    MASTERCARD = "mastercard"

class PaymentStartIn(BaseModel):
    method: PaymentMethod
    booking_id: int
    card_number: str = Field(min_length=12, max_length=24)
    cardholder_name: str = Field(min_length=2, max_length=80)
    expiry_date: str = Field(pattern=r"^\d{2}\s*/\s*\d{2}$")
    cvv: str | None = Field(default=None, max_length=4)

class PaymentStartOut(BaseModel):
    payment_id: int
    reference: str
    method: PaymentMethod
    card_last4: str
    email_masked: str
    amount: Decimal
    expires_at: datetime
    resend_available_at: datetime | None = None
    demo_mode: bool

class OtpVerifyIn(BaseModel):
    code: str = Field(pattern=r"^\d{4}$")

class PaymentVerifyOut(BaseModel):
    payment_id: int
    reference: str
    status: str
    booking: BookingOut

class CatalogSyncOut(BaseModel):
    imported_now_playing: int
    imported_upcoming: int

class CinemaDirectorySyncOut(BaseModel):
    cinemas: int
    halls: int
    active_showtimes: int
    skipped: int
    upstream_failures: int
    synced_at: datetime

class MovieDetailsOut(MovieOut):
    trailer_url: str | None = None
