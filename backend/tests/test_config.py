import unittest

from app.config import Settings

SAFE = dict(
    app_environment="production",
    jwt_secret="j" * 40,
    otp_secret="o" * 40,
    email_mode="brevo",
    cors_origins="https://parda-booking.vercel.app",
    database_url="postgresql+psycopg://parda:s3cret@db.internal:5432/parda",
)

def make(**overrides) -> Settings:
    return Settings(_env_file=None, **{**SAFE, **overrides})

class ProductionConfigTests(unittest.TestCase):
    def test_safe_configuration_passes(self):
        self.assertEqual(make().production_problems(), [])
        make().assert_production_ready()

    def test_default_and_short_jwt_secret_rejected(self):
        for secret in ("change-me-before-deploying-this-app", "short", "replace-with-" + "x" * 40):
            with self.subTest(secret=secret):
                self.assertTrue(any("JWT_SECRET" in p for p in make(jwt_secret=secret).production_problems()))

    def test_otp_secret_required_and_distinct(self):
        self.assertTrue(any("OTP_SECRET" in p for p in make(otp_secret="").production_problems()))
        self.assertTrue(any("differ" in p for p in make(otp_secret="j" * 40).production_problems()))

    def test_mock_email_rejected(self):
        self.assertTrue(any("EMAIL_MODE" in p for p in make(email_mode="mock").production_problems()))
        self.assertTrue(any("EMAIL_MODE" in p for p in make(email_mode="nonsense").production_problems()))

    def test_wildcard_or_empty_cors_rejected(self):
        for origins in ("*", "", "https://a.example,*"):
            with self.subTest(origins=origins):
                self.assertTrue(any("CORS_ORIGINS" in p for p in make(cors_origins=origins).production_problems()))

    def test_default_database_credentials_rejected(self):
        bad = "postgresql+psycopg://booking:booking@localhost:5432/booking"
        self.assertTrue(any("DATABASE_URL" in p for p in make(database_url=bad).production_problems()))

    def test_unsafe_production_refuses_to_start(self):
        with self.assertRaises(RuntimeError) as ctx:
            make(jwt_secret="short", email_mode="mock").assert_production_ready()
        self.assertIn("JWT_SECRET", str(ctx.exception))
        self.assertIn("EMAIL_MODE", str(ctx.exception))

    def test_development_is_never_blocked(self):
        make(app_environment="development", jwt_secret="x", email_mode="mock").assert_production_ready()

if __name__ == "__main__":
    unittest.main()
