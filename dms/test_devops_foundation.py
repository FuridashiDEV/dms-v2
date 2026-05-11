from django.test import TestCase, override_settings
from django.urls import reverse


class DevOpsFoundationTests(TestCase):
    def test_health_endpoint_checks_database(self):
        response = self.client.get(reverse("health_check"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["checks"]["database"], "ok")

    @override_settings(HEALTH_CHECK_DATABASE=False, HEALTH_CHECK_QDRANT=False)
    def test_health_endpoint_can_run_without_dependency_checks(self):
        response = self.client.get(reverse("health_check"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["checks"]["application"], "ok")

    def test_health_endpoint_does_not_expose_secrets(self):
        response = self.client.get(reverse("health_check"))
        raw_payload = response.content.decode("utf-8")

        self.assertNotIn("SECRET_KEY", raw_payload)
        self.assertNotIn("POSTGRES_PASSWORD", raw_payload)
        self.assertNotIn("DJANGO_SECRET_KEY", raw_payload)
