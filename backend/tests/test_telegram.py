"""Telegram notifications: linking, the webhook's authentication, the bot's replies, and delivery next to e-mail."""
import unittest
import uuid
from datetime import timedelta
from unittest import mock

from app import telegram, telegram_setup
from app.config import Settings, settings
from app.mail import EmailDeliveryError
from app.notifications import deliver_due_notifications, deliver_due_saved_movie_notifications, deliver_due_waitlist_notifications
from tests.support import ApiTestCase, NotificationTestCase, make_hall, make_screening, make_user, scalar, sql

SECRET = "s" * 24
BOT = "ParDaTestBot"

class TelegramCase(ApiTestCase):
    def setUp(self):
        self.calls: list[tuple[str, dict]] = []
        self.failure: Exception | None = None
        def fake_api(method, payload):
            if self.failure:
                raise self.failure
            self.calls.append((method, payload))
            return {"ok": True}
        patcher = mock.patch("app.telegram._api", side_effect=fake_api)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._saved = (settings.telegram_bot_token, settings.telegram_bot_username, settings.telegram_webhook_secret)
        settings.telegram_bot_token, settings.telegram_bot_username, settings.telegram_webhook_secret = "123456:test-token", BOT, SECRET
        self.addCleanup(lambda: setattr_all(self._saved))

    def messages(self, chat_id=None):
        return [p["text"] for m, p in self.calls if m == "sendMessage" and (chat_id is None or p["chat_id"] == chat_id)]

    def start_link(self, shop):
        resp = self.client.post("/api/telegram/link", headers=shop.headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["url"].split("start=")[1]

    def webhook(self, text, chat_id, *, secret=SECRET, chat_type="private"):
        headers = {} if secret is None else {"X-Telegram-Bot-Api-Secret-Token": secret}
        update = {"update_id": 1, "message": {"text": text, "chat": {"id": chat_id, "type": chat_type}}}
        return self.client.post("/api/telegram/webhook", json=update, headers=headers)

    def linked(self, user_id):
        return scalar("SELECT chat_id FROM telegram_links WHERE user_id = :u", u=user_id)

def setattr_all(values):
    settings.telegram_bot_token, settings.telegram_bot_username, settings.telegram_webhook_secret = values

def new_chat_id() -> int:
    return 7_000_000_000 + uuid.uuid4().int % 1_000_000_000

class LinkingTests(TelegramCase):
    def test_the_whole_linking_flow(self):
        shop, chat = self.shop(), new_chat_id()
        self.assertEqual(self.client.get("/api/telegram", headers=shop.headers).json(), {"configured": True, "bot_username": BOT, "linked": False})
        link = self.client.post("/api/telegram/link", headers=shop.headers).json()
        self.assertTrue(link["url"].startswith(f"https://t.me/{BOT}?start="))
        token = link["url"].split("start=")[1]
        self.assertEqual(self.webhook(f"/start {token}", chat).status_code, 200)
        self.assertEqual(self.linked(shop.user["id"]), chat)
        self.assertIn("Connected", self.messages(chat)[-1])
        self.assertTrue(self.client.get("/api/telegram", headers=shop.headers).json()["linked"])

    def test_only_a_hash_of_the_token_is_stored(self):
        shop = self.shop()
        token = self.start_link(shop)
        self.assertEqual(scalar("SELECT count(*) FROM telegram_link_tokens WHERE token_hash = :t", t=token), 0)
        self.assertEqual(len(scalar("SELECT token_hash FROM telegram_link_tokens WHERE user_id = :u", u=shop.user["id"])), 64)

    def test_a_token_works_once(self):
        shop, chat, other_chat = self.shop(), new_chat_id(), new_chat_id()
        token = self.start_link(shop)
        self.webhook(f"/start {token}", chat)
        self.webhook(f"/start {token}", other_chat)
        self.assertIn("expired or was already used", self.messages(other_chat)[-1])
        self.assertEqual(self.linked(shop.user["id"]), chat)

    def test_expired_and_made_up_tokens_are_refused(self):
        shop, chat = self.shop(), new_chat_id()
        token = self.start_link(shop)
        sql("UPDATE telegram_link_tokens SET expires_at = now() - interval '1 minute' WHERE user_id = :u", u=shop.user["id"])
        self.webhook(f"/start {token}", chat)
        self.webhook("/start not-a-real-token", chat)
        self.assertEqual([m for m in self.messages(chat) if "expired or was already used" in m].__len__(), 2)
        self.assertIsNone(self.linked(shop.user["id"]))

    def test_a_chat_cannot_be_taken_over_by_a_second_account(self):
        first, second, chat = self.shop(), self.shop(), new_chat_id()
        self.webhook(f"/start {self.start_link(first)}", chat)
        self.webhook(f"/start {self.start_link(second)}", chat)
        self.assertIn("already connected to another", self.messages(chat)[-1])
        self.assertEqual(self.linked(first.user["id"]), chat)
        self.assertIsNone(self.linked(second.user["id"]))

    def test_linking_again_moves_the_account_to_the_new_chat(self):
        shop, old_chat, new_chat = self.shop(), new_chat_id(), new_chat_id()
        self.webhook(f"/start {self.start_link(shop)}", old_chat)
        self.webhook(f"/start {self.start_link(shop)}", new_chat)
        self.assertEqual(self.linked(shop.user["id"]), new_chat)

    def test_stop_and_unlink_remove_the_link(self):
        shop, chat = self.shop(), new_chat_id()
        self.webhook(f"/start {self.start_link(shop)}", chat)
        self.webhook("/stop", chat)
        self.assertIsNone(self.linked(shop.user["id"]))
        self.assertIn("stopped", self.messages(chat)[-1])
        self.webhook(f"/start {self.start_link(shop)}", chat)
        self.assertEqual(self.client.delete("/api/telegram/link", headers=shop.headers).status_code, 204)
        self.assertIsNone(self.linked(shop.user["id"]))
        self.webhook("/stop", chat)
        self.assertIn("not connected", self.messages(chat)[-1])

    def test_other_messages_get_help_or_nothing(self):
        chat = new_chat_id()
        self.webhook("/start", chat)
        self.webhook("/help", chat)
        self.assertEqual(len(self.messages(chat)), 2)
        self.assertTrue(all("Phantora Cinema notifications" in m for m in self.messages(chat)))
        before = len(self.calls)
        self.webhook("hello there", chat)                                              # not a command
        self.webhook("/start x", chat, chat_type="group")                               # not a private chat
        self.assertEqual(len(self.calls), before)

    def test_link_requests_are_limited_per_customer(self):
        shop = self.shop()
        codes = [self.client.post("/api/telegram/link", headers=shop.headers).status_code for _ in range(12)]
        self.assertEqual(codes, [200] * 10 + [429] * 2)

    def test_old_tokens_are_capped(self):
        shop = self.shop()
        for _ in range(7):
            self.start_link(shop)
        self.assertLessEqual(scalar("SELECT count(*) FROM telegram_link_tokens WHERE user_id = :u", u=shop.user["id"]), 5)

class WebhookSecurityTests(TelegramCase):
    def test_requests_without_the_registered_secret_are_refused(self):
        shop, chat = self.shop(), new_chat_id()
        token = self.start_link(shop)
        for secret in (None, "", "wrong", SECRET + "x", SECRET[:-1]):
            with self.subTest(secret=secret):
                self.assertEqual(self.webhook(f"/start {token}", chat, secret=secret).status_code, 403)
        self.assertIsNone(self.linked(shop.user["id"]))
        self.assertEqual(self.messages(chat), [])

    def test_the_webhook_does_not_exist_when_telegram_is_not_configured(self):
        settings.telegram_bot_token = ""
        self.assertEqual(self.webhook("/help", new_chat_id()).status_code, 404)

    def test_an_empty_configured_secret_never_matches(self):
        settings.telegram_webhook_secret = ""
        self.assertEqual(self.webhook("/help", new_chat_id(), secret="").status_code, 403)

    def test_linking_is_unavailable_without_configuration(self):
        settings.telegram_bot_token = ""
        shop = self.shop()
        self.assertFalse(self.client.get("/api/telegram", headers=shop.headers).json()["configured"])
        self.assertEqual(self.client.post("/api/telegram/link", headers=shop.headers).status_code, 503)

    def test_the_customer_endpoints_need_a_signed_in_account(self):
        for method, path in (("get", "/api/telegram"), ("post", "/api/telegram/link"), ("delete", "/api/telegram/link")):
            self.assertIn(getattr(self.client, method)(path).status_code, (401, 403), path)

class DeliveryTests(NotificationTestCase, TelegramCase):
    def setUp(self):
        NotificationTestCase.setUp(self)
        TelegramCase.setUp(self)

    def linked_ticket(self):
        (ticket,) = self.tickets(1)
        owner = scalar("SELECT customer_id FROM bookings WHERE ticket_code = :t", t=ticket)
        chat = new_chat_id()
        sql("INSERT INTO telegram_links (user_id, chat_id) VALUES (:u, :c)", u=owner, c=chat)
        return ticket, owner, chat

    def test_a_confirmation_goes_to_telegram_as_well_as_email(self):
        ticket, owner, chat = self.linked_ticket()
        with mock.patch("app.notifications.send_booking_confirmation_email") as email:
            self.assertEqual(deliver_due_notifications(), 1)
        email.assert_called_once()
        (message,) = self.messages(chat)
        self.assertIn("your ticket is confirmed", message)
        self.assertIn(ticket, message)
        self.assertTrue(self.notice(ticket)[0])

    def test_customers_without_a_link_get_no_telegram_message(self):
        (ticket,) = self.tickets(1)
        with mock.patch("app.notifications.send_booking_confirmation_email"):
            deliver_due_notifications()
        self.assertEqual(self.calls, [])
        self.assertTrue(self.notice(ticket)[0])

    def test_nothing_is_sent_while_the_email_is_failing_and_retrying(self):
        ticket, _, chat = self.linked_ticket()
        with mock.patch("app.notifications.send_booking_confirmation_email", side_effect=EmailDeliveryError("down")):
            deliver_due_notifications()
        self.assertEqual(self.messages(chat), [], "Telegram must wait for the e-mail so the customer is not messaged twice")
        self.assertFalse(self.notice(ticket)[0])

    def test_a_telegram_outage_never_stops_the_email_notification(self):
        ticket, owner, chat = self.linked_ticket()
        self.failure = telegram.TelegramError(502, "Bad Gateway")
        with mock.patch("app.notifications.send_booking_confirmation_email"):
            self.assertEqual(deliver_due_notifications(), 1)
        self.assertTrue(self.notice(ticket)[0])
        self.assertEqual(self.linked(owner), chat, "a temporary outage must not unlink the customer")

    def test_a_chat_that_blocked_the_bot_is_unlinked(self):
        ticket, owner, chat = self.linked_ticket()
        self.failure = telegram.TelegramError(403, "Forbidden: bot was blocked by the user")
        with mock.patch("app.notifications.send_booking_confirmation_email"):
            deliver_due_notifications()
        self.assertIsNone(self.linked(owner))
        self.assertTrue(self.notice(ticket)[0])

    def test_nothing_is_sent_when_telegram_is_switched_off(self):
        ticket, owner, chat = self.linked_ticket()
        settings.telegram_bot_token = ""
        with mock.patch("app.notifications.send_booking_confirmation_email"):
            deliver_due_notifications()
        self.assertEqual(self.calls, [])

    def test_waitlist_and_saved_film_alerts_are_delivered_too(self):
        hall = make_hall()
        screening = make_screening(hall)
        user = make_user()
        chat = new_chat_id()
        sql("INSERT INTO telegram_links (user_id, chat_id) VALUES (:u, :c)", u=user["id"], c=chat)
        entry = sql("INSERT INTO screening_waitlist (screening_id, user_id, seat_count, status) VALUES (:s, :u, 2, 'notified') RETURNING id",
                    s=screening, u=user["id"])[0][0]
        sql("INSERT INTO waitlist_notifications (waitlist_entry_id, due_at, attempts) VALUES (:e, now() - interval '1 minute', 0)", e=entry)
        with mock.patch("app.notifications.send_waitlist_available_email"):
            self.assertGreaterEqual(deliver_due_waitlist_notifications(), 1)
        self.assertTrue(any("seats are available again" in m for m in self.messages(chat)))
        movie_id = scalar("SELECT movie_id FROM screenings WHERE id = :s", s=screening)
        watch = sql("INSERT INTO movie_watchlists (user_id, movie_id) VALUES (:u, :m) RETURNING id", u=user["id"], m=movie_id)[0][0]
        sql("INSERT INTO movie_watchlist_notifications (watchlist_id, screening_id, due_at, attempts) VALUES (:w, :s, now() - interval '1 minute', 0)", w=watch, s=screening)
        with mock.patch("app.notifications.send_saved_movie_showtime_email"):
            self.assertGreaterEqual(deliver_due_saved_movie_notifications(), 1)
        self.assertTrue(any("now has a showtime" in m for m in self.messages(chat)))

    def test_a_refund_message_states_the_amount(self):
        shop = self.shop()
        hall = make_hall()
        screening = make_screening(hall, starts_in=timedelta(hours=30), surcharge=0)
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        shop.pay(booking["id"])
        chat = new_chat_id()
        sql("INSERT INTO telegram_links (user_id, chat_id) VALUES (:u, :c)", u=shop.user["id"], c=chat)
        shop.set_status(booking["id"], "cancelled")
        sql("UPDATE booking_notifications SET due_at = now() - interval '1 minute' WHERE booking_id = :b AND event_type = 'refund'", b=booking["id"])
        with mock.patch("app.notifications.send_refund_email"), mock.patch("app.notifications.send_booking_confirmation_email"), \
                mock.patch("app.notifications.send_screening_reminder_email"):
            deliver_due_notifications()
        self.assertTrue(any("100% was refunded" in m and "30,000" in m for m in self.messages(chat)), self.messages(chat))

class SetupTests(unittest.TestCase):
    def test_registering_the_webhook_sends_the_secret_and_limits_updates(self):
        saved = (settings.telegram_bot_token, settings.telegram_webhook_secret)
        settings.telegram_bot_token, settings.telegram_webhook_secret = "1:t", SECRET
        try:
            with mock.patch("app.telegram._api", return_value={"ok": True}) as api:
                telegram.register_webhook("https://api.example.com/api/telegram/webhook")
        finally:
            settings.telegram_bot_token, settings.telegram_webhook_secret = saved
        method, payload = api.call_args.args
        self.assertEqual((method, payload["secret_token"], payload["allowed_updates"]), ("setWebhook", SECRET, ["message"]))

    def test_the_setup_command_refuses_unsafe_or_missing_input(self):
        saved = (settings.telegram_bot_token, settings.telegram_webhook_secret)
        try:
            settings.telegram_bot_token, settings.telegram_webhook_secret = "", ""
            self.assertEqual(telegram_setup.main(["https://x.example/api/telegram/webhook"]), 2)
            settings.telegram_bot_token, settings.telegram_webhook_secret = "1:t", "short"
            self.assertEqual(telegram_setup.main(["https://x.example/api/telegram/webhook"]), 2)
            settings.telegram_webhook_secret = SECRET
            self.assertEqual(telegram_setup.main(["http://insecure.example/hook"]), 2)
            self.assertEqual(telegram_setup.main([]), 2)
        finally:
            settings.telegram_bot_token, settings.telegram_webhook_secret = saved

    def test_production_refuses_a_bot_without_a_webhook_secret(self):
        problems = Settings(_env_file=None, app_environment="production", jwt_secret="j" * 40, otp_secret="o" * 40, email_mode="brevo",
                            cors_origins="https://x.example", database_url="postgresql+psycopg://u:p@h/db",
                            telegram_bot_token="1:t", telegram_bot_username="Bot", telegram_webhook_secret="short").production_problems()
        self.assertTrue(any("TELEGRAM_WEBHOOK_SECRET" in p for p in problems))

if __name__ == "__main__":
    unittest.main()
