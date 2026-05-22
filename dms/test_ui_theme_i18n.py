from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(ALLOWED_HOSTS=["testserver", "127.0.0.1", "localhost"])
class ThemeAndLanguageUiTests(TestCase):
    def test_login_page_renders_theme_and_language_controls(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "docflow-theme")
        self.assertContains(response, reverse("set_language"))
        self.assertContains(response, "name=\"language\"")

    def test_authenticated_shell_uses_selected_language_labels(self):
        user = get_user_model().objects.create_user(
            username="theme-admin",
            password="pass",
            role="ADMIN",
        )
        self.client.force_login(user)
        self.client.cookies.load({"django_language": "en"})

        response = self.client.get(reverse("dms:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AI Document Archive")
        self.assertContains(response, "Folders")
        self.assertContains(response, "Administration")
        self.assertContains(response, "Sign out")
