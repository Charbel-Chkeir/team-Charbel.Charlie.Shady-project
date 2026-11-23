"""
Security tests -- one or more per Week 11 (OWASP) item:
headers & CSP, rate limiting, account enumeration, security logging,
cookie flags, debug off, secrets, running behind Render's proxy.

Run from the project root:   python3 -m unittest -v
"""
import logging
import os
import re
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["OPENTRIPMAP_API_KEY"] = "test-key"

import api_client                                   # noqa: E402
import app as app_module                            # noqa: E402
from app import app, limiter                        # noqa: E402
from tests.test_routes import fake_api              # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent


def csrf(client, page="/login"):
    html = client.get(page).get_data(as_text=True)
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


class SecurityTests(unittest.TestCase):

    def setUp(self):
        api_client.clear_cache()
        patcher = mock.patch("api_client.requests.get", side_effect=fake_api)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = app.test_client()
        limiter.enabled = True          # ON for these tests...
        limiter.reset()                 # ...starting from zero
        self.addCleanup(setattr, limiter, "enabled", False)

    def show_logs(self):
        """Other test files silence logging; the two logging tests need it on."""
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, logging.CRITICAL)

    def signup(self, client, email=None, password="abc12345"):
        email = email or f"{uuid.uuid4().hex[:8]}@test.com"
        r = client.post("/signup", data={"email": email, "password": password, "confirm": password,
                                         "csrf_token": csrf(client, "/signup")})
        return email, r

    def login(self, client, email, password):
        return client.post("/login", data={"email": email, "password": password,
                                           "csrf_token": csrf(client)})

    # ---------- A02 / A05: security headers ----------
    def test_security_headers(self):
        r = self.client.get("/")
        csp = r.headers["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertIn("Referrer-Policy", r.headers)
        self.assertNotIn("Strict-Transport-Security", r.headers)   # only on Render (HTTPS)
        # headers are on error pages too
        self.assertIn("Content-Security-Policy", self.client.get("/nope").headers)

    # ---------- A07: brute force ----------
    def test_login_rate_limit(self):
        email, _ = self.signup(app.test_client())
        limiter.reset()
        attacker = app.test_client()
        for attempt in range(5):
            self.assertEqual(self.login(attacker, email, f"wrong{attempt}x").status_code, 401)
        r = self.login(attacker, email, "abc12345")                 # 6th try, even the right one
        self.assertEqual(r.status_code, 429)
        self.assertIn("Too many requests", r.get_data(as_text=True))
        self.assertEqual(attacker.get("/login").status_code, 200)   # only POST is limited

    def test_signup_rate_limit(self):
        # a new browser for each sign-up, but all from the same IP (what the limit counts)
        codes = [self.signup(app.test_client())[1].status_code for _ in range(11)]
        self.assertEqual(codes[:10], [302] * 10)
        self.assertEqual(codes[10], 429)

    def test_search_rate_limit(self):
        codes = [self.client.get("/search?city=Beirut").status_code for _ in range(31)]
        self.assertEqual(codes[:30], [200] * 30)
        self.assertEqual(codes[30], 429)

    # ---------- A07: account enumeration ----------
    def test_unknown_email_still_checks_a_password(self):
        """Same work (one hash check) whether or not the email exists -> same timing."""
        with mock.patch.object(app_module, "check_password_hash",
                               wraps=app_module.check_password_hash) as spy:
            r = self.login(self.client, "nobody-here@test.com", "whatever1")
        self.assertEqual(r.status_code, 401)
        spy.assert_called_once()
        self.assertEqual(spy.call_args.args[0], app_module.DUMMY_HASH)

    def test_same_message_for_unknown_email_and_wrong_password(self):
        email, _ = self.signup(app.test_client())
        a = self.login(app.test_client(), email, "wrongpass1").get_data(as_text=True)
        b = self.login(app.test_client(), "nobody@test.com", "wrongpass1").get_data(as_text=True)
        self.assertIn("Email or password is incorrect.", a)
        self.assertIn("Email or password is incorrect.", b)

    # ---------- A01: open redirect ----------
    def test_open_redirect_blocked(self):
        email, _ = self.signup(app.test_client())
        for evil in ["https://evil.com", "//evil.com", "javascript:alert(1)"]:
            client = app.test_client()
            r = client.post("/login", data={"email": email, "password": "abc12345", "next": evil,
                                            "csrf_token": csrf(client)})
            self.assertEqual(r.status_code, 302, evil)
            self.assertEqual(r.location, "/", evil)             # sent home, not to evil.com
        client = app.test_client()
        r = client.post("/login", data={"email": email, "password": "abc12345", "next": "/trips",
                                        "csrf_token": csrf(client)})
        self.assertEqual(r.location, "/trips")                  # local paths still work

    # ---------- A09: logging (and never the password) ----------
    def test_failed_login_is_logged_without_password(self):
        self.show_logs()
        with self.assertLogs(app.logger, level="WARNING") as logs:
            self.login(self.client, "victim@test.com", "Secret123guess")
        text = "\n".join(logs.output)
        self.assertIn("Failed login for victim@test.com", text)
        self.assertNotIn("Secret123guess", text)

    def test_access_denied_is_logged(self):
        alice = app.test_client()
        self.signup(alice)
        alice.post("/trips/new", data={"title": "Mine", "destination": "Beirut",
                                       "start_date": "2030-01-01", "end_date": "2030-01-02",
                                       "csrf_token": csrf(alice, "/trips/new")})
        trip_url = "/trips/" + re.search(r"/trips/(\d+)", alice.get("/trips").get_data(as_text=True)).group(1)
        bob = app.test_client()
        self.signup(bob)
        self.show_logs()
        with self.assertLogs(app.logger, level="WARNING") as logs:
            self.assertEqual(bob.get(trip_url).status_code, 403)
        self.assertIn("403 access denied", "\n".join(logs.output))

    # ---------- A02: cookies, debug ----------
    def test_session_cookie_flags(self):
        _, r = self.signup(app.test_client())
        cookie = r.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)

    def test_debug_is_off(self):
        self.assertFalse(app.debug)

    def test_no_secrets_in_the_code(self):
        """Keys only come from the environment, never written in a .py file."""
        for file in PROJECT.glob("*.py"):
            text = file.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"apikey\s*=\s*['\"][0-9a-f]{20,}", file.name)
            self.assertNotRegex(text, r"postgres(ql)?://\w+:\w+@", file.name)

    # ---------- configuration on Render (separate Python process) ----------
    def run_app_with(self, env, code):
        full_env = {k: v for k, v in os.environ.items() if k not in ("SECRET_KEY", "RENDER")}
        full_env.update({"DATABASE_URL": "sqlite://"}, **env)
        return subprocess.run([sys.executable, "-c", code], cwd=PROJECT, env=full_env,
                              capture_output=True, text=True, timeout=60)

    def test_render_refuses_to_start_without_secret_key(self):
        r = self.run_app_with({"RENDER": "true"}, "import app")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("SECRET_KEY", r.stderr)

    def test_render_mode_proxy_hsts_and_secure_cookie(self):
        code = ("from app import app\n"
                "c = app.test_client()\n"
                "r = c.get('/', headers={'X-Forwarded-For': '203.0.113.7', 'X-Forwarded-Proto': 'https'})\n"
                "print(type(app.wsgi_app).__name__, app.config['SESSION_COOKIE_SECURE'],\n"
                "      'Strict-Transport-Security' in r.headers)\n")
        r = self.run_app_with({"RENDER": "true", "SECRET_KEY": "x" * 32}, code)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), ["ProxyFix", "True", "True"])


if __name__ == "__main__":
    unittest.main()
