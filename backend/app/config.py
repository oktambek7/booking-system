from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "change-me-before-deploying-this-app"
MIN_SECRET_LENGTH = 32
EMAIL_MODES = {"mock", "smtp", "resend", "brevo"}

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://booking:booking@localhost:5432/booking"
    jwt_secret: str = DEFAULT_JWT_SECRET
    # Access tokens are short-lived; the browser renews them silently with its refresh cookie.
    jwt_expire_minutes: int = 15
    # Browser sessions: the refresh token lives in an httpOnly cookie and rotates on every use.
    # A rotated token replayed after the grace period revokes the whole sign-in (it was copied).
    refresh_token_days: int = 30
    refresh_family_max_days: int = 90
    refresh_reuse_grace_seconds: int = 10
    business_timezone: str = "Asia/Tashkent"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    tmdb_read_token: str = ""
    tmdb_region: str = "UZ"
    tmdb_max_pages: int = 5
    tmdb_sync_interval_hours: int = 24
    # The external cinema catalogue is discovery data.  Keep it in the
    # production database so a Render restart does not make customers wait on
    # the upstream service again.
    cinematica_cache_fresh_seconds: int = 600
    cinematica_cache_stale_seconds: int = 86400
    cinematica_refresh_interval_seconds: int = 600
    # Seat-hoarding limits: unpaid holds one customer may have at once, and how many seats of
    # one screening they may hold unpaid. Paid tickets are not counted.
    max_pending_holds_per_user: int = 3
    # Cancellation policy for paid tickets: share of the price returned to a customer who cancels this many
    # hours before the screening starts (operators always refund in full).
    refund_full_hours: int = 24
    # Live seat-map updates (Server-Sent Events fed by PostgreSQL NOTIFY).
    live_updates_enabled: bool = True
    live_heartbeat_seconds: float = 20.0
    live_max_streams: int = 2000
    live_max_streams_per_ip: int = 10
    refund_partial_hours: int = 2
    refund_partial_percent: int = 50
    max_pending_seats_per_screening: int = 8
    notification_poll_seconds: int = 60
    notification_retry_minutes: int = 10
    # After this many failed deliveries a notification is abandoned instead of retried forever.
    notification_max_attempts: int = 8
    sms_mode: str = "mock"
    sms_api_url: str = "https://notify.eskiz.uz/api"
    sms_email: str = ""
    sms_password: str = ""
    sms_sender: str = "4546"
    email_mode: str = "mock"
    # Telegram notifications are off until a bot token is set. The webhook secret must be registered with
    # Telegram too (python -m app.telegram_setup); bot_username is the bot's handle without the @.
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    telegram_webhook_secret: str = ""
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
    log_level: str = "INFO"
    # "json" for log search in production, "text" for a terminal. Empty = json in production, text otherwise.
    log_format: str = ""
    rate_limit_enabled: bool = True
    # Scheduled catalogue refreshes and notification delivery. Tests turn this off; a
    # dedicated worker deployment can turn it off on web instances.
    run_background_jobs: bool = True
    # Apply pending Alembic migrations when the API starts. Turn off once migrations run as a
    # separate release step (`python -m app.migrate`); the API then refuses to start on an old schema.
    auto_migrate: bool = True
    # Header carrying the real caller address behind a proxy (Render: cf-connecting-ip).
    # Empty means use the socket peer; never trust a header the proxy does not overwrite.
    client_ip_header: str = ""
    admin_email: str = ""
    admin_password: str = ""
    admin_nickname: str = "admin"
    # One-time, operator-controlled bootstrap for a pre-existing user. Keep
    # this empty in normal operation and remove it after a successful grant.
    operator_bootstrap_nickname: str = ""
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def is_production(self) -> bool:
        return self.app_environment.strip().lower() == "production"

    def production_problems(self) -> list[str]:
        """Return every unsafe setting for a production deploy (empty when safe)."""
        problems: list[str] = []
        if self.jwt_secret == DEFAULT_JWT_SECRET or len(self.jwt_secret) < MIN_SECRET_LENGTH                 or self.jwt_secret.startswith(("replace-with", "local-development")):
            problems.append(f"JWT_SECRET must be a unique random value of at least {MIN_SECRET_LENGTH} characters")
        if len(self.otp_secret) < MIN_SECRET_LENGTH or self.otp_secret.startswith("replace-with"):
            problems.append(f"OTP_SECRET must be a unique random value of at least {MIN_SECRET_LENGTH} characters")
        elif self.otp_secret == self.jwt_secret:
            problems.append("OTP_SECRET must differ from JWT_SECRET")
        email_mode = self.email_mode.strip().lower()
        if email_mode not in EMAIL_MODES or email_mode == "mock":
            problems.append("EMAIL_MODE must be smtp, resend or brevo (mock is development-only)")
        origins = [x.strip() for x in self.cors_origins.split(",") if x.strip()]
        if not origins or "*" in origins:
            problems.append("CORS_ORIGINS must list the exact frontend origin(s), not '*' or empty")
        if self.telegram_bot_token and (len(self.telegram_webhook_secret) < 16 or not self.telegram_bot_username):
            problems.append("TELEGRAM_BOT_TOKEN needs TELEGRAM_BOT_USERNAME and a TELEGRAM_WEBHOOK_SECRET of at least 16 characters")
        if "booking:booking@" in self.database_url:
            problems.append("DATABASE_URL still uses the default development credentials")
        return problems

    def assert_production_ready(self) -> None:
        if not self.is_production:
            return
        problems = self.production_problems()
        if problems:
            raise RuntimeError("Unsafe production configuration:\n - " + "\n - ".join(problems))

settings = Settings()
