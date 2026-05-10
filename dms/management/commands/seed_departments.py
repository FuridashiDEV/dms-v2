from django.core.management.base import BaseCommand
from django.db import transaction

from dms.models import DEFAULT_ORGANIZATION_NAME, DEFAULT_ORGANIZATION_SLUG, Department, Organization


TREE = {
    "Единственный акционер": {
        "Совет директоров": {
            "Служба внутреннего аудита": {},
            "Корпоративный секретарь": {},
            "Антикоррупционная комплаенс-служба": {},
            "Председатель Правления — Ректор": {
                "Военно-мобилизационный отдел": {},
                "Служба безопасности и правопорядка": {},
                "Военная кафедра": {},
                "Подразделение по защите гос. секретов": {},
                "Ученый совет": {},
                "Учебно-методическое объединение": {},
                "Аппарат ректора": {
                    "Административный департамент": {},
                    "Департамент административно-хозяйственной деятельности": {},
                    "Управление по работе с персоналом": {},
                    "Юридический отдел": {},
                },
                "ПРАВЛЕНИЕ": {
                    "Член Правления — Первый проректор": {
                        "Департамент стратегического развития": {},
                        "Финансовый департамент": {},
                        "Auezov University Endowment Fund": {},
                        "Центр новой климатической экономики и устойчивого развития имени Рае Квон Чунга": {},
                    },
                    "Член Правления — проректор по академическим вопросам": {
                        "Департамент по академическим вопросам": {},
                        "Департамент по студенческим вопросам": {},
                        "Образовательно-информационный центр": {},
                        "Центр профориентационной работы": {},
                        "Учебно-методический совет": {},
                        "Департамент цифровизации": {},
                        "Центр поддержки карьеры и трудоустройства": {},
                    },
                    "Член Правления — проректор по международному сотрудничеству": {
                        "Центр международного сотрудничества": {},
                        "Проектный офис по зарубежным партнерам": {},
                        "Центр Болонского процесса и академической мобильности": {},
                        "Foundation": {},
                        "Филиал НАО “ЮКУ им. М. Ауэзова” в городе Чирчик (Республика Узбекистан)": {},
                    },
                    "Член Правления — Проректор по научной работе и инновациям": {
                        "Департамент академической науки": {},
                        "Департамент науки и предпринимательства": {},
                        "Департамент научных проектов и программ": {},
                        "Департамент научных исследований": {},
                        "Департамент испытательных лабораторий": {},
                        "Диссертационные советы": {},
                        "Научные советы (НТС, НГС, СМУ)": {},
                    },
                    "Член Правления — проректор по связям с общественностью и культуре": {
                        "Департамент по культурно-массовой работе": {
                            "Дизайнерская мастерская": {},
                            "Музей": {},
                        },
                        "Центр медиа-службы": {
                            "Телестудия": {},
                            "Фотостудия": {},
                            "Газета “Университет”": {},
                        },
                    },
                    "Член Правления — проректор по социальной и воспитательной работе": {
                        "Департамент по воспитательной работе и молодёжной политике": {},
                        "Центр “Рухани жаңғыру” “Ассамблея народов Казахстана”": {},
                        "Ассоциация выпускников": {},
                        "Профсоюзный комитет": {},
                        "Совет по этике": {},
                        "Общественный совет при ректоре": {},
                        "Комиссия по обеспечению качества": {},
                    },
                },
            },
        }
    }
}


def get_default_organization() -> Organization:
    organization, _ = Organization.objects.get_or_create(
        slug=DEFAULT_ORGANIZATION_SLUG,
        defaults={
            "name": DEFAULT_ORGANIZATION_NAME,
            "is_active": True,
        },
    )
    return organization


def ensure_node(name: str, parent: Department | None, organization: Organization) -> Department:
    """
    Создаёт Department если нет. Если есть — обновляет parent (если изменился).
    """
    obj, created = Department.objects.get_or_create(
        name=name,
        organization=organization,
        defaults={"parent": parent},
    )
    if (not created) and (obj.parent_id != (parent.id if parent else None)):
        obj.parent = parent
        obj.save(update_fields=["parent"])
    return obj


def create_tree(parent: Department | None, subtree: dict, organization: Organization):
    for dept_name, children in subtree.items():
        node = ensure_node(dept_name, parent, organization)
        if isinstance(children, dict) and children:
            create_tree(node, children, organization)


class Command(BaseCommand):
    help = "Seed departments tree into DB (MPTT)"

    @transaction.atomic
    def handle(self, *args, **options):
        organization = get_default_organization()
        create_tree(None, TREE, organization)

        # пересобираем MPTT дерево (на случай изменений)
        Department.objects.rebuild()

        self.stdout.write(self.style.SUCCESS("✅ Department tree has been seeded & rebuilt"))
