import io

from django.core.management import call_command
from django.test import TestCase, override_settings


class ProductionPilotStage33Tests(TestCase):
    def test_check_pilot_readiness_passes_with_pilot_like_settings(self):
        stdout = io.StringIO()

        with override_settings(
            DEBUG=False,
            SECRET_KEY="stage33-pilot-secret-key",
            ALLOWED_HOSTS=["pilot.example.com"],
            CSRF_TRUSTED_ORIGINS=["https://pilot.example.com"],
            SESSION_COOKIE_SECURE=True,
            CSRF_COOKIE_SECURE=True,
            SECURE_SSL_REDIRECT=True,
            SECURE_HSTS_SECONDS=31536000,
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.postgresql",
                    "NAME": "dms",
                    "USER": "postgres",
                    "PASSWORD": "stage33-strong-db-password",
                    "HOST": "localhost",
                    "PORT": "5432",
                }
            },
            HEALTH_CHECK_DATABASE=True,
            AUTH_PASSWORD_VALIDATORS=[{"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"}],
        ):
            call_command("check_pilot_readiness", stdout=stdout)

        self.assertIn("Pilot readiness check passed", stdout.getvalue())

    def test_check_pilot_readiness_does_not_print_secrets(self):
        stdout = io.StringIO()
        secret = "stage33-secret-must-not-leak"
        db_password = "stage33-db-password-must-not-leak"

        with override_settings(
            DEBUG=True,
            SECRET_KEY=secret,
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.postgresql",
                    "NAME": "dms",
                    "USER": "postgres",
                    "PASSWORD": db_password,
                    "HOST": "localhost",
                    "PORT": "5432",
                }
            },
        ):
            with self.assertRaises(SystemExit):
                call_command("check_pilot_readiness", stdout=stdout)

        output = stdout.getvalue()
        self.assertIn("security.debug_enabled", output)
        self.assertNotIn(secret, output)
        self.assertNotIn(db_password, output)

    def test_check_pilot_readiness_strict_fails_on_warnings(self):
        stdout = io.StringIO()

        with override_settings(
            DEBUG=False,
            SECRET_KEY="stage33-pilot-secret-key",
            ALLOWED_HOSTS=["localhost"],
            CSRF_TRUSTED_ORIGINS=[],
            SESSION_COOKIE_SECURE=True,
            CSRF_COOKIE_SECURE=True,
            SECURE_SSL_REDIRECT=True,
            SECURE_HSTS_SECONDS=31536000,
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.postgresql",
                    "NAME": "dms",
                    "USER": "postgres",
                    "PASSWORD": "stage33-strong-db-password",
                    "HOST": "localhost",
                    "PORT": "5432",
                }
            },
            HEALTH_CHECK_DATABASE=True,
            AUTH_PASSWORD_VALIDATORS=[{"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"}],
        ):
            with self.assertRaises(SystemExit):
                call_command("check_pilot_readiness", "--strict", stdout=stdout)

        self.assertIn("pilot_hosts_local_only", stdout.getvalue())
