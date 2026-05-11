from django.db import migrations


STANDARD_PROVIDERS = [
    {
        "code": "email",
        "name": "Email Ingestion",
        "provider_type": "email",
        "description": "Foundation for future inbound email document ingestion.",
    },
    {
        "code": "1c",
        "name": "1C",
        "provider_type": "1c",
        "description": "Foundation for future 1C import/export integration.",
    },
    {
        "code": "google-drive",
        "name": "Google Drive",
        "provider_type": "google_drive",
        "description": "Foundation for future Google Drive integration.",
    },
    {
        "code": "onedrive",
        "name": "OneDrive",
        "provider_type": "onedrive",
        "description": "Foundation for future OneDrive integration.",
    },
    {
        "code": "sharepoint",
        "name": "SharePoint",
        "provider_type": "sharepoint",
        "description": "Foundation for future SharePoint integration.",
    },
    {
        "code": "external-api",
        "name": "External API",
        "provider_type": "external_api",
        "description": "Foundation for future API-based external systems.",
    },
    {
        "code": "erp",
        "name": "ERP",
        "provider_type": "other",
        "description": "Foundation for future ERP integration.",
    },
]


def seed_standard_providers(apps, schema_editor):
    IntegrationProvider = apps.get_model("dms", "IntegrationProvider")
    for provider_data in STANDARD_PROVIDERS:
        IntegrationProvider.objects.update_or_create(
            code=provider_data["code"],
            defaults={
                "name": provider_data["name"],
                "provider_type": provider_data["provider_type"],
                "description": provider_data["description"],
                "is_active": True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("dms", "0029_integrationprovider_alter_auditevent_event_type_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_standard_providers, migrations.RunPython.noop),
    ]
