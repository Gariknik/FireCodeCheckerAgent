import os
import tempfile
import unittest
from unittest.mock import patch
from pydantic import ValidationError

from schemas import BuildingRoomInput, DefectItem, FireSafetyReportOutput
from tools import (
    search_fire_code_web,
    send_telegram_report,
    log_inspection_result,
    _is_whitelisted_url,
)
from agent import FireCodeCheckerAgent
from database import init_db, insert_inspection_log, fetch_recent_logs


class TestFireCodeCheckerAgent(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = FireCodeCheckerAgent()
        # Ізолюємо від реальних мережевих викликів Telegram під час unit-тестів
        self.env_patcher = patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "YOUR_BOT_TOKEN"})
        self.env_patcher.start()

    def tearDown(self) -> None:
        self.env_patcher.stop()

    # -------------------------------------------------------------------------
    # 1. Тести Pydantic-схем (schemas.py)
    # -------------------------------------------------------------------------
    def test_building_room_input_validation_and_optional_category(self) -> None:
        # Повна валідна модель з категорією
        valid = BuildingRoomInput(
            room_name="Складський комплекс",
            category="в",  # перевірка автоматичної нормалізації у верхній регістр 'В'
            area_sqm=250.0,
            height_m=3.0,
            occupancy=15,
            doors_count=2,
            door_height_m=2.1,
            door_width_m=0.9,
            door_opening="назовні",
            wall_finish="Г1",
            evac_distance_m=20.0,
        )
        self.assertEqual(valid.category, "В")
        self.assertEqual(valid.occupancy, 15)

        # Необов'язкова категорія (category=None)
        no_cat = BuildingRoomInput(room_name="Офіс 302", area_sqm=40.0, occupancy=20)
        self.assertIsNone(no_cat.category)
        self.assertEqual(no_cat.occupancy, 20)

        # Латинська літера категорії ('A' -> 'А')
        latin_cat = BuildingRoomInput(room_name="Цех", category="A", area_sqm=50.0)
        self.assertEqual(latin_cat.category, "А")

        # Некоректна площа (<= 0)
        with self.assertRaises(ValidationError):
            BuildingRoomInput(room_name="Тест", category="В", area_sqm=-10.0)

        # Некоректна категорія
        with self.assertRaises(ValidationError):
            BuildingRoomInput(room_name="Тест", category="Ж", area_sqm=50.0)

        # Від'ємна кількість людей
        with self.assertRaises(ValidationError):
            BuildingRoomInput(room_name="Тест", area_sqm=50.0, occupancy=-5)

    def test_fire_safety_report_output_formatting_and_markdown_escape(self) -> None:
        # PASSED шаблон з підкресленнями в URL
        passed_report = FireSafetyReportOutput(
            room_name="Серверна",
            status="PASSED",
            defects_count=0,
            summary_text="Норма",
            defects=[],
            verified_sources=["https://dbn.co.ua/load/dbn_v_1_1_7_2016"],
        )
        msg_passed = passed_report.format_telegram_message()
        self.assertIn("🟢 РЕЗУЛЬТАТ НОРМАТИВНОГО АУДИТУ", msg_passed)
        self.assertIn("ВІДПОВІДАЄ НОРМАМ", msg_passed)
        self.assertIn(r"dbn\_v\_1\_1\_7\_2016", msg_passed)

        # FAILED шаблон
        failed_report = FireSafetyReportOutput(
            room_name="Склад",
            status="FAILED",
            defects_count=1,
            summary_text="Порушення",
            defects=[
                DefectItem(
                    parameter="Відстань евакуації",
                    actual_value="35 м",
                    required_value="не більше 25 м",
                    dbn_code="ДБН В.1.1-7:2016 п. 7.2.5",
                    source_url="https://e-construction.gov.ua/dbn/v.1.1-7-2016#p7.2.5",
                )
            ],
            verified_sources=["https://online.budstandart.com/ua/doc?id_doc=66189"],
        )
        msg_failed = failed_report.format_telegram_message()
        self.assertIn("🔴 РЕЗУЛЬТАТ НОРМАТИВНОГО АУДИТУ", msg_failed)
        self.assertIn("[ДБН В.1.1-7:2016 п. 7.2.5](https://e-construction.gov.ua/dbn/v.1.1-7-2016#p7.2.5)", msg_failed)
        self.assertIn(r"id\_doc=66189", msg_failed)

    # -------------------------------------------------------------------------
    # 2. Тести парсера природної мови (extract_room_input у agent.py)
    # -------------------------------------------------------------------------
    def test_extract_room_input_all_parameters_and_variants(self) -> None:
        # Варіант 1: повний текст із компактним розміром дверей та кількістю людей в приміщенні
        text1 = (
            "Перевірити приміщення: Конференц-зал, площа 85,5 кв.м, "
            "кількість людей в приміщенні — 55, висота стелі 3,2м, "
            "двері 0,9х2,1м, 2 виходи, назовні, оздоблення стін — Г1, відстань до виходу — 18м"
        )
        room1, _, _ = self.agent.extract_room_input(text1)
        self.assertEqual(room1.room_name, "Конференц-зал")
        self.assertIsNone(room1.category)
        self.assertEqual(room1.area_sqm, 85.5)
        self.assertEqual(room1.occupancy, 55)
        self.assertEqual(room1.height_m, 3.2)
        self.assertEqual(room1.door_width_m, 0.9)
        self.assertEqual(room1.door_height_m, 2.1)
        self.assertEqual(room1.doors_count, 2)
        self.assertEqual(room1.door_opening, "назовні")
        self.assertEqual(room1.wall_finish, "Г1")
        self.assertEqual(room1.evac_distance_m, 18.0)

        # Варіант 2: альтернативні формулювання ("40 осіб", "виходів: 1", "всередину", "ширина дверей", "висота дверей")
        text2 = (
            "Об'єкт: Цех пакування, категорія Б, площа 150 м2, 40 осіб, "
            "виходів: 1, ширина дверей 0.75м, висота дверей 1.9м, всередину, Г2"
        )
        room2, _, _ = self.agent.extract_room_input(text2)
        self.assertEqual(room2.room_name, "Цех пакування")
        self.assertEqual(room2.category, "Б")
        self.assertEqual(room2.occupancy, 40)
        self.assertEqual(room2.doors_count, 1)
        self.assertEqual(room2.door_width_m, 0.75)
        self.assertEqual(room2.door_height_m, 1.9)
        self.assertEqual(room2.door_opening, "всередину")
        self.assertEqual(room2.wall_finish, "Г2")

    # -------------------------------------------------------------------------
    # 3. Тести інструментів та білого списку джерел (tools.py)
    # -------------------------------------------------------------------------
    def test_search_fire_code_web_whitelist_and_rephrasing(self) -> None:
        # Перевірка білого списку доменів (Контроль РИЗИКУ 2)
        self.assertTrue(_is_whitelisted_url("https://e-construction.gov.ua/dbn"))
        self.assertTrue(_is_whitelisted_url("https://online.budstandart.com/doc"))
        self.assertTrue(_is_whitelisted_url("https://dbn.co.ua/load"))
        self.assertFalse(_is_whitelisted_url("https://fake-fire-norms.com/dbn"))

        # Перший (неточний) запит повертає порожній список []
        res_empty = search_fire_code_web("ДБН В.1.1-7:2016 макс відстань евакуаційного шляху категорія В")
        self.assertEqual(res_empty, [])

        # Уточнений запит повертає п. 7.2.5 з білого списку
        res_found = search_fire_code_web("ДБН В.1.1-7:2016 гранична відстань евакуації категорія В")
        self.assertTrue(len(res_found) >= 1)
        self.assertTrue(any("7.2.5" in r["dbn_code"] for r in res_found))
        for r in res_found:
            self.assertTrue(_is_whitelisted_url(r["source_url"]))

    # -------------------------------------------------------------------------
    # 4. Тести всіх нормативних правил ДБН В.1.1-7:2016 (evaluate_compliance)
    # -------------------------------------------------------------------------
    def test_evaluate_compliance_evacuation_distances_by_category(self) -> None:
        # Категорія А (макс 15м): 20м -> FAILED (п. 7.2.4)
        r_a = BuildingRoomInput(room_name="Цех А", category="А", area_sqm=50.0, evac_distance_m=20.0)
        rep_a, _, _ = self.agent.evaluate_compliance(r_a, [])
        self.assertEqual(rep_a.status, "FAILED")
        self.assertIn("7.2.4", rep_a.defects[0].dbn_code)

        # Категорія В (макс 25м): 35м -> FAILED (п. 7.2.5)
        r_v = BuildingRoomInput(room_name="Склад В", category="В", area_sqm=100.0, evac_distance_m=35.0)
        rep_v, _, _ = self.agent.evaluate_compliance(r_v, [])
        self.assertEqual(rep_v.status, "FAILED")
        self.assertIn("7.2.5", rep_v.defects[0].dbn_code)

        # Категорія Д (макс 50м): 40м -> PASSED, 60м -> FAILED (п. 7.2.6)
        r_d_ok = BuildingRoomInput(room_name="Цех Д", category="Д", area_sqm=100.0, evac_distance_m=40.0)
        rep_d_ok, _, _ = self.agent.evaluate_compliance(r_d_ok, [])
        self.assertEqual(rep_d_ok.status, "PASSED")

        r_d_fail = BuildingRoomInput(room_name="Цех Д", category="Д", area_sqm=100.0, evac_distance_m=60.0)
        rep_d_fail, _, _ = self.agent.evaluate_compliance(r_d_fail, [])
        self.assertEqual(rep_d_fail.status, "FAILED")
        self.assertIn("7.2.6", rep_d_fail.defects[0].dbn_code)

    def test_evaluate_compliance_occupancy_doors_walls_and_height(self) -> None:
        # Комплексна перевірка усіх дефектів:
        # - щільність людей: 60 осіб на 60 м² = 1.0 м²/особу (< 1.5 м² -> п. 7.2.1)
        # - кількість виходів: 1 вихід при 60 особах (> 50 осіб -> п. 7.2.2)
        # - ширина дверей: 0.9м при 60 особах (< 1.2м для >50 осіб -> п. 7.2.8)
        # - висота дверей: 1.85м (< 2.0м -> п. 7.2.8)
        # - напрямок дверей: всередину при 60 особах (-> п. 7.2.10)
        # - висота стелі: 1.9м (< 2.0м -> п. 7.3.1)
        # - оздоблення стін: Г3 (-> п. 7.3.3)
        room = BuildingRoomInput(
            room_name="Зал засідань",
            category=None,
            area_sqm=60.0,
            height_m=1.9,
            occupancy=60,
            doors_count=1,
            door_width_m=0.9,
            door_height_m=1.85,
            door_opening="всередину",
            wall_finish="Г3",
        )
        report, _, _ = self.agent.evaluate_compliance(room, [])
        self.assertEqual(report.status, "FAILED")
        self.assertEqual(report.defects_count, 7)
        codes = {d.dbn_code for d in report.defects}
        self.assertIn("ДБН В.1.1-7:2016 п. 7.2.1", codes)
        self.assertIn("ДБН В.1.1-7:2016 п. 7.2.2", codes)
        self.assertIn("ДБН В.1.1-7:2016 п. 7.2.8", codes)
        self.assertIn("ДБН В.1.1-7:2016 п. 7.2.10", codes)
        self.assertIn("ДБН В.1.1-7:2016 п. 7.3.1", codes)
        self.assertIn("ДБН В.1.1-7:2016 п. 7.3.3", codes)

    # -------------------------------------------------------------------------
    # 5. Тести SQLite БД (database.py) та повного циклу ReAct (run_react_inspection)
    # -------------------------------------------------------------------------
    def test_sqlite_database_logging(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = os.path.join(tmpdir, "test_building.db")
            init_db(temp_db)
            res = insert_inspection_log(
                chat_id=111222,
                room_name="Тестова кімната",
                status="PASSED",
                defects_count=0,
                summary="ОК",
                model_used="openai/gpt-4o-mini",
                tokens_prompt=500,
                tokens_completion=100,
                estimated_cost_usd=0.0002,
                db_path=temp_db,
            )
            self.assertEqual(res["status"], "SUCCESS")
            self.assertEqual(res["log_id"], 1)

            logs = fetch_recent_logs(limit=5, db_path=temp_db)
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0]["tokens_total"], 600)
            self.assertEqual(logs[0]["room_name"], "Тестова кімната")

    def test_full_react_inspection_passed_failed_and_validation_error(self) -> None:
        # 1. FAILED сценарій
        msg_fail = (
            "Перевірити приміщення: Складський комплекс, площа 250 кв.м, категорія В, "
            "оздоблення стін — гіпсокартон Г1, відстань до виходу — 35м."
        )
        res_fail = self.agent.run_react_inspection(chat_id=987654321, message_text=msg_fail)
        self.assertTrue(res_fail["success"])
        self.assertEqual(res_fail["report"]["status"], "FAILED")
        self.assertEqual(res_fail["report"]["defects_count"], 1)
        self.assertEqual(res_fail["db_log"]["status"], "SUCCESS")

        # 2. PASSED сценарій без категорії з кількістю людей
        msg_pass = (
            "Перевірити приміщення: Офіс 302, площа 60 кв.м, кількість людей в приміщенні — 20 осіб, "
            "оздоблення стін — Г1, відстань до виходу — 15м, двері 0.9х2.1м, назовні."
        )
        res_pass = self.agent.run_react_inspection(chat_id=987654322, message_text=msg_pass)
        self.assertTrue(res_pass["success"])
        self.assertEqual(res_pass["report"]["status"], "PASSED")
        self.assertEqual(res_pass["report"]["defects_count"], 0)

        # 3. ValidationError сценарій (Контроль РИЗИКУ 1)
        msg_invalid = "Перевірити приміщення без площі"
        res_err = self.agent.run_react_inspection(chat_id=987654323, message_text=msg_invalid)
        self.assertFalse(res_err["success"])
        self.assertIn("Помилка валідації вхідних даних", res_err["error"])


if __name__ == "__main__":
    unittest.main()
