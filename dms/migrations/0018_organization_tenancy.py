from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import dms.models


def attach_existing_data_to_default_organization(apps, schema_editor):
    Organization = apps.get_model("dms", "Organization")
    OrganizationMember = apps.get_model("dms", "OrganizationMember")
    Department = apps.get_model("dms", "Department")
    Folder = apps.get_model("dms", "Folder")
    Document = apps.get_model("dms", "Document")
    DocumentType = apps.get_model("dms", "DocumentType")
    User = apps.get_model("dms", "User")

    organization, _ = Organization.objects.get_or_create(
        slug=dms.models.DEFAULT_ORGANIZATION_SLUG,
        defaults={
            "name": dms.models.DEFAULT_ORGANIZATION_NAME,
            "is_active": True,
        },
    )

    Department.objects.filter(organization__isnull=True).update(
        organization=organization,
    )
    DocumentType.objects.filter(organization__isnull=True).update(
        organization=organization,
    )

    for folder in Folder.objects.select_related("department").filter(organization__isnull=True):
        folder.organization_id = (
            folder.department.organization_id
            if folder.department_id
            else organization.id
        )
        folder.save(update_fields=["organization"])

    for document in Document.objects.select_related("department").filter(organization__isnull=True):
        document.organization_id = (
            document.department.organization_id
            if document.department_id
            else organization.id
        )
        document.save(update_fields=["organization"])

    for user in User.objects.select_related("department").all():
        user_organization_id = (
            user.department.organization_id
            if user.department_id
            else organization.id
        )
        member_role = "ADMIN" if user.role == "ADMIN" or user.is_staff or user.is_superuser else "MEMBER"
        OrganizationMember.objects.get_or_create(
            organization_id=user_organization_id,
            user_id=user.id,
            defaults={
                "role": member_role,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("dms", "0017_archive_cleanup"),
    ]

    operations = [
        migrations.CreateModel(
            name="Organization",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255, verbose_name="Название организации")),
                ("slug", models.SlugField(max_length=80, unique=True, verbose_name="Slug")),
                ("is_active", models.BooleanField(default=True, verbose_name="Активна")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")),
            ],
            options={
                "verbose_name": "Организация",
                "verbose_name_plural": "Организации",
                "ordering": ["name"],
            },
        ),
        migrations.AddField(
            model_name="department",
            name="organization",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="departments",
                to="dms.organization",
                verbose_name="Организация",
            ),
        ),
        migrations.AddField(
            model_name="documenttype",
            name="organization",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="document_types",
                to="dms.organization",
                verbose_name="Организация",
            ),
        ),
        migrations.AddField(
            model_name="folder",
            name="organization",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="folders",
                to="dms.organization",
                verbose_name="Организация",
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="organization",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="documents",
                to="dms.organization",
                verbose_name="Организация",
            ),
        ),
        migrations.CreateModel(
            name="OrganizationMember",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "role",
                    models.CharField(
                        choices=[("OWNER", "Владелец"), ("ADMIN", "Администратор"), ("MEMBER", "Участник")],
                        default="MEMBER",
                        max_length=20,
                        verbose_name="Роль в организации",
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="Активен")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="members",
                        to="dms.organization",
                        verbose_name="Организация",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="organization_memberships",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Участник организации",
                "verbose_name_plural": "Участники организаций",
            },
        ),
        migrations.AlterField(
            model_name="department",
            name="name",
            field=models.CharField(max_length=255, verbose_name="Название отдела"),
        ),
        migrations.AlterField(
            model_name="documenttype",
            name="name",
            field=models.CharField(max_length=100, verbose_name="Тип документа"),
        ),
        migrations.RunPython(
            attach_existing_data_to_default_organization,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="department",
            name="organization",
            field=models.ForeignKey(
                default=dms.models.get_default_organization_id,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="departments",
                to="dms.organization",
                verbose_name="Организация",
            ),
        ),
        migrations.AlterField(
            model_name="documenttype",
            name="organization",
            field=models.ForeignKey(
                default=dms.models.get_default_organization_id,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="document_types",
                to="dms.organization",
                verbose_name="Организация",
            ),
        ),
        migrations.AlterField(
            model_name="folder",
            name="organization",
            field=models.ForeignKey(
                default=dms.models.get_default_organization_id,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="folders",
                to="dms.organization",
                verbose_name="Организация",
            ),
        ),
        migrations.AlterField(
            model_name="document",
            name="organization",
            field=models.ForeignKey(
                default=dms.models.get_default_organization_id,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="documents",
                to="dms.organization",
                verbose_name="Организация",
            ),
        ),
        migrations.AddConstraint(
            model_name="department",
            constraint=models.UniqueConstraint(
                fields=("organization", "name"),
                name="unique_department_name_per_organization",
            ),
        ),
        migrations.AddConstraint(
            model_name="documenttype",
            constraint=models.UniqueConstraint(
                fields=("organization", "name"),
                name="unique_document_type_name_per_organization",
            ),
        ),
        migrations.AddConstraint(
            model_name="organizationmember",
            constraint=models.UniqueConstraint(
                fields=("organization", "user"),
                name="unique_organization_member",
            ),
        ),
        migrations.AddIndex(
            model_name="organizationmember",
            index=models.Index(fields=["user", "is_active"], name="dms_organiz_user_id_5bcd6b_idx"),
        ),
        migrations.AddIndex(
            model_name="organizationmember",
            index=models.Index(fields=["organization", "is_active"], name="dms_organiz_organiz_179b71_idx"),
        ),
        migrations.AddIndex(
            model_name="document",
            index=models.Index(fields=["organization", "-doc_date"], name="dms_documen_organiz_78c5e0_idx"),
        ),
    ]
