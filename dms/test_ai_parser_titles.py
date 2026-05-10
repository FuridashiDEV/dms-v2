from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase

from dms.services.ai_parser import parse_document


class AiParserTitleTests(SimpleTestCase):
    @patch("dms.services.ai_parser.ollama.chat")
    def test_parser_rewrites_raw_sentence_title_into_semantic_archive_title(self, ollama_chat_mock):
        text = (
            "RU: чЯ хочу поступить в inVision U, потому что для меня образование — это не только получение знаний, "
            "но и подготовка к реальным действиям. Мне близка идея обучения, в котором студент...\n"
            "Документ описывает мотивацию абитуриента и причины выбора университета."
        )
        ollama_chat_mock.return_value = {
            "message": {
                "content": (
                    '{"title_ru":"Я хочу поступить в inVision U, потому что для меня образование — это не только получение знаний",'
                    '"summary_ru":"Мотивационное письмо абитуриента с объяснением выбора университета.",'
                    '"doc_type":null,"date_index":null,"document_author":"","language":"RU","retention_category":"","legal_hold":false}'
                )
            }
        }

        payload = parse_document(
            text=text,
            candidate_dates=[date(2026, 5, 2)],
            allowed_doc_types=set(),
        )

        self.assertEqual(payload["title_ru"], "Мотивационное письмо для поступления в inVision U")
        self.assertEqual(payload["summary_ru"], "Мотивационное письмо абитуриента с объяснением выбора университета.")
