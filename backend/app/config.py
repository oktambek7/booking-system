from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://booking:booking@localhost:5432/booking"
    jwt_secret: str = "change-me-before-deploying-this-app"
    jwt_expire_minutes: int = 1440
    business_timezone: str = "Asia/Tashkent"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    tmdb_read_token: str = ""
    tmdb_region: str = "UZ"
    tmdb_max_pages: int = 5
    tmdb_sync_interval_hours: int = 24
    sms_mode: str = "mock"
    sms_api_url: str = "https://notify.eskiz.uz/api"
    sms_email: str = ""
    sms_password: str = ""
    sms_sender: str = "4546"
    email_mode: str = "mock"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    resend_api_key: str = ""
    resend_from: str = ""
    brevo_api_key: str = ""
    brevo_from: str = ""
    otp_secret: str = ""
    app_environment: str = "development"
    admin_email: str = ""
    admin_password: str = ""
    admin_nickname: str = "admin"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
