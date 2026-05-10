from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify

from dms.models import Department

User = get_user_model()

DEFAULT_PASSWORD = "ChangeMe123!"


class Command(BaseCommand):
    help = "Create one responsible user for each Department"

    @transaction.atomic
    def handle(self, *args, **options):
        created = 0

        for dept in Department.objects.all().order_by("tree_id", "lft"):
            username = self.build_username(dept)

            if User.objects.filter(username=username).exists():
                continue

            user = User(
                username=username,
                first_name="Ответственный",
                last_name=dept.name[:150],
                role=User.Role.EMPLOYEE,
                department=dept,
                position="Ответственный за документооборот",
                is_active=True,
            )
            user.set_password(DEFAULT_PASSWORD)
            user.save()

            created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"✅ Создано пользователей: {created}\n"
                f"🔑 Временный пароль для всех: {DEFAULT_PASSWORD}"
            )
        )

    def build_username(self, dept: Department) -> str:
        """
        Формирует уникальный логин из пути отдела
        """
        parts = [slugify(a.name) for a in dept.get_ancestors(include_self=True)]
        base = "_".join(parts)[:140]

        username = base
        i = 1
        while User.objects.filter(username=username).exists():
            username = f"{base}_{i}"
            i += 1

        return username
