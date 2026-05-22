from __future__ import annotations

from django import template
from django.utils.translation import get_language


register = template.Library()


UI_TEXT = {
    "ru": {
        "brand_title": "ИИ-архив документов",
        "brand_subtitle": "Электронный архив с умным поиском и карточкой документа",
        "folders": "Папки",
        "create_user": "Регистрация пользователя",
        "users": "Пользователи",
        "administration": "Администрирование",
        "analytics": "Аналитика и наблюдаемость",
        "billing": "Тарифы и лимиты",
        "costs": "Стоимость обработки",
        "security": "Безопасность",
        "usage": "Использование и вебхуки",
        "notifications": "Уведомления",
        "logout": "Выйти",
        "theme_light": "Светлая тема",
        "theme_dark": "Тёмная тема",
        "language": "Язык",
        "login_page_title": "Вход — DMS",
        "login_title": "Система документооборота",
        "login_subtitle": "Южно-Казахстанский университет имени М. Ауэзова",
        "login_card_title": "Вход в систему",
        "login_card_subtitle": "Войдите, используя учетные данные",
        "username_label": "Email / Логин",
        "password_label": "Пароль",
        "forgot": "Забыли?",
        "sign_in": "Войти в систему",
        "staff_only": "Система предназначена для сотрудников университета",
        "forgot_title": "Восстановление доступа",
        "forgot_subtitle": "Самостоятельное восстановление недоступно",
        "forgot_text": "Обратитесь в IT отдел в XXX кабинет Х корпуса.",
        "understood": "Понятно",
        "close": "Закрыть",
    },
    "kk": {
        "brand_title": "Құжаттардың AI-архиві",
        "brand_subtitle": "Ақылды іздеу және құжат карточкасы бар электрондық архив",
        "folders": "Бумалар",
        "create_user": "Пайдаланушыны тіркеу",
        "users": "Пайдаланушылар",
        "administration": "Әкімшілендіру",
        "analytics": "Аналитика және бақылау",
        "billing": "Тарифтер мен лимиттер",
        "costs": "Өңдеу құны",
        "security": "Қауіпсіздік",
        "usage": "Пайдалану және вебхуктар",
        "notifications": "Хабарламалар",
        "logout": "Шығу",
        "theme_light": "Жарық тема",
        "theme_dark": "Қараңғы тема",
        "language": "Тіл",
        "login_page_title": "Кіру — DMS",
        "login_title": "Құжат айналымы жүйесі",
        "login_subtitle": "М. Әуезов атындағы Оңтүстік Қазақстан университеті",
        "login_card_title": "Жүйеге кіру",
        "login_card_subtitle": "Тіркелгі деректерін пайдаланып кіріңіз",
        "username_label": "Email / Логин",
        "password_label": "Құпиясөз",
        "forgot": "Ұмыттыңыз ба?",
        "sign_in": "Жүйеге кіру",
        "staff_only": "Жүйе университет қызметкерлеріне арналған",
        "forgot_title": "Қолжетімділікті қалпына келтіру",
        "forgot_subtitle": "Өздігінен қалпына келтіру қолжетімсіз",
        "forgot_text": "IT бөліміне, XXX кабинетке, Х корпусына хабарласыңыз.",
        "understood": "Түсінікті",
        "close": "Жабу",
    },
    "en": {
        "brand_title": "AI Document Archive",
        "brand_subtitle": "Electronic archive with smart search and document cards",
        "folders": "Folders",
        "create_user": "Register user",
        "users": "Users",
        "administration": "Administration",
        "analytics": "Analytics and observability",
        "billing": "Plans and limits",
        "costs": "Processing cost",
        "security": "Security",
        "usage": "Usage and webhooks",
        "notifications": "Notifications",
        "logout": "Sign out",
        "theme_light": "Light theme",
        "theme_dark": "Dark theme",
        "language": "Language",
        "login_page_title": "Sign in — DMS",
        "login_title": "Document Management System",
        "login_subtitle": "M. Auezov South Kazakhstan University",
        "login_card_title": "Sign in",
        "login_card_subtitle": "Use your account credentials",
        "username_label": "Email / Login",
        "password_label": "Password",
        "forgot": "Forgot?",
        "sign_in": "Sign in",
        "staff_only": "The system is intended for university staff",
        "forgot_title": "Access recovery",
        "forgot_subtitle": "Self-service recovery is not available",
        "forgot_text": "Contact the IT department in room XXX, building X.",
        "understood": "Got it",
        "close": "Close",
    },
}


def _active_language() -> str:
    language = (get_language() or "ru").split("-")[0].lower()
    return language if language in UI_TEXT else "ru"


@register.simple_tag
def ui_text(key: str) -> str:
    language = _active_language()
    return UI_TEXT[language].get(key) or UI_TEXT["ru"].get(key) or key
