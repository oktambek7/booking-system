from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from .models import BookingStatus

class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)

class Login(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    duration_minutes: int = Field(gt=0, le=480)
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)

class ServiceOut(ServiceIn):
    id: int
    active: bool
    model_config = ConfigDict(from_attributes=True)

class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    bio: str = Field(default="", max_length=2000)
    service_ids: list[int] = Field(default_factory=list)

class ProviderOut(BaseModel):
    id: int
    name: str
    bio: str
    active: bool
    service_ids: list[int]

class AvailabilityIn(BaseModel):
    weekday: int = Field(ge=0, le=6)
    starts_at: time
    ends_at: time
    timezone: str = "Asia/Tashkent"

class SlotOut(BaseModel):
    starts_at: datetime
    ends_at: datetime

class BookingIn(BaseModel):
    service_id: int
    provider_id: int
    starts_at: datetime

class BookingOut(BaseModel):
    id: int
    service_id: int
    provider_id: int
    starts_at: datetime
    ends_at: datetime
    status: BookingStatus
    price_at_booking: Decimal
    model_config = ConfigDict(from_attributes=True)

class StatusIn(BaseModel):
    status: BookingStatus
