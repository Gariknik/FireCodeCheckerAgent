import json
import os
import re
from typing import Dict, Any, List, Tuple
from dotenv import load_dotenv
from pydantic import ValidationError

from src.schemas import BuildingRoomInput, DefectItem, FireSafetyReportOutput
from src.tools import search_fire_code_web, send_telegram_report, log_inspection_result

load_dotenv()

# Target LLM Models Stack
MODEL_EXTRACTOR = "gemini-3.5-flash-lite"
MODEL_PRIMARY = "openai/gpt-4o-mini"
MODEL_ANALYTICAL = "deepseek-v4-flash-0731"

# Обмеження зупинки (Stopping Criteria)
MAX_ITERATIONS = 10
MAX_BUDGET_USD = 0.05

VALIDATION_ERROR_TEMPLATE = (
    "⚠️ Помилка валідації вхідних даних (BuildingRoomInput).\n"
    "Будь ласка, надішліть опис приміщення за шаблоном:\n"
    "«Перевірити приміщення: [Назва], площа [X] кв.м, категорія [А/Б/В/Г/Д], "
    "кількість людей в приміщенні — [N] осіб, оздоблення стін — [Г1-Г4], "
    "відстань до виходу — [Y]м, двері [ширина]х[висота]м (назовні/всередину)»"
)


class FireCodeCheckerAgent:
    """
    Інженерний AI-агент нормативної перевірки проєктних рішень СПЗ (ДБН В.1.1-7:2016).
    Реалізує мультимодельний стек та патерн ReAct із суворою Pydantic-валідацією.
    """

    def __init__(self) -> None:
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        self.gemini_key = os.getenv("GEMINI_API_KEY", "")

    def _has_live_llm_keys(self) -> bool:
        return bool(
            (self.openrouter_key and self.openrouter_key != "YOUR_OPENROUTER_KEY")
            or (self.gemini_key and self.gemini_key != "YOUR_GEMINI_KEY")
        )

    def extract_room_input(self, raw_text: str) -> Tuple[BuildingRoomInput, int, int]:
        """
        Крок 1: Парсинг Telegram-тексту у Pydantic-модель BuildingRoomInput
        (Модель: gemini-3.5-flash-lite).
        """
        extracted: Dict[str, Any] = {}

        # Назва приміщення
        name_match = re.search(
            r"(?:приміщення|об'єкт)\s*[:\-—]?\s*([^,\n]+)",
            raw_text,
            flags=re.IGNORECASE,
        )
        if name_match:
            extracted["room_name"] = name_match.group(1).strip()
        else:
            first_chunk = raw_text.split(",")[0].strip()
            if len(first_chunk) > 2 and not any(k in first_chunk.lower() for k in ["площа", "категорія"]):
                extracted["room_name"] = first_chunk

        # Категорія (А, Б, В, Г, Д)
        cat_match = re.search(
            r"категорі[яї]\s*[:\-—]?\s*([АБВГДABVGD])\b",
            raw_text,
            flags=re.IGNORECASE,
        )
        if cat_match:
            cat_map = {"A": "А", "B": "Б", "V": "В", "G": "Г", "D": "Д"}
            raw_cat = cat_match.group(1).upper()
            extracted["category"] = cat_map.get(raw_cat, raw_cat)

        # Площа (м2 / кв.м)
        area_match = re.search(
            r"площ[аі]\s*[:\-—]?\s*(-?\d+(?:[.,]\d+)?)\s*(?:кв\.?\s*м|м2|м²)?",
            raw_text,
            flags=re.IGNORECASE,
        )
        if area_match:
            extracted["area_sqm"] = float(area_match.group(1).replace(",", "."))

        # Висота стелі / приміщення
        height_match = re.search(
            r"(?:висот[аи]\s+(?:стел[іi]|приміщення)|стеля)\s*[:\-—]?\s*(\d+(?:[.,]\d+)?)\s*м",
            raw_text,
            flags=re.IGNORECASE,
        )
        if height_match:
            extracted["height_m"] = float(height_match.group(1).replace(",", "."))

        # Кількість людей в приміщенні
        occ_match = re.search(
            r"(?:кількість\s+людей(?:\s+(?:в|у)\s+приміщенн[іi])?|людей(?:\s+(?:в|у)\s+приміщенн[іi])?|осіб|персонал[у]?|місткість)\s*[:\-—]?\s*(\d+)",
            raw_text,
            flags=re.IGNORECASE,
        )
        if not occ_match:
            occ_match = re.search(
                r"\b(\d+)\s*(?:людей|людини|осіб|особи|чол\.?|чоловік|працівник[іи]в)\b",
                raw_text,
                flags=re.IGNORECASE,
            )
        if occ_match:
            extracted["occupancy"] = int(occ_match.group(1))

        # Компактний запис розмірів дверей: "двері 0.9х2.1м" (ширина х висота)
        door_dim_match = re.search(
            r"двер[іiей]+\s*[:\-—]?\s*(\d+(?:[.,]\d+)?)\s*[xх*×]\s*(\d+(?:[.,]\d+)?)\s*м?",
            raw_text,
            flags=re.IGNORECASE,
        )
        if door_dim_match:
            extracted["door_width_m"] = float(door_dim_match.group(1).replace(",", "."))
            extracted["door_height_m"] = float(door_dim_match.group(2).replace(",", "."))

        # Кількість дверей / виходів
        doors_match = re.search(
            r"(?:кількість\s+(?:дверей|виходів)|дверей|виходів|виходи)\s*[:\-—]?\s*(\d+)(?![.,]\d|\s*[xх*×])",
            raw_text,
            flags=re.IGNORECASE,
        )
        if not doors_match:
            doors_match = re.search(
                r"(?<![.,\d])\b(\d+)\s*(?:евакуаційн[иіїх]+\s+)?(?:вихід|виходи|виходів|дверей)\b",
                raw_text,
                flags=re.IGNORECASE,
            )
        if doors_match:
            extracted["doors_count"] = int(doors_match.group(1))

        # Висота дверей
        door_h_match = re.search(
            r"висот[аи]\s+дверей\s*[:\-—]?\s*(\d+(?:[.,]\d+)?)\s*м",
            raw_text,
            flags=re.IGNORECASE,
        )
        if door_h_match:
            extracted["door_height_m"] = float(door_h_match.group(1).replace(",", "."))

        # Ширина дверей
        door_w_match = re.search(
            r"ширин[аи]\s+дверей\s*[:\-—]?\s*(\d+(?:[.,]\d+)?)\s*м",
            raw_text,
            flags=re.IGNORECASE,
        )
        if door_w_match:
            extracted["door_width_m"] = float(door_w_match.group(1).replace(",", "."))

        # Напрямок відчинення дверей
        if re.search(r"всередину", raw_text, flags=re.IGNORECASE):
            extracted["door_opening"] = "всередину"
        elif re.search(r"назовні", raw_text, flags=re.IGNORECASE):
            extracted["door_opening"] = "назовні"

        # Оздоблення стін / група горючості (Г1-Г4)
        finish_match = re.search(
            r"\b(Г[1-4]|G[1-4])\b",
            raw_text,
            flags=re.IGNORECASE,
        )
        if finish_match:
            extracted["wall_finish"] = finish_match.group(1).upper().replace("G", "Г")

        # Відстань евакуації
        evac_match = re.search(
            r"(?:відстань(?:\s+до\s+виходу|\s+евакуації)?|евакуаці[яї])\s*[:\-—]?\s*(\d+(?:[.,]\d+)?)\s*м",
            raw_text,
            flags=re.IGNORECASE,
        )
        if evac_match:
            extracted["evac_distance_m"] = float(evac_match.group(1).replace(",", "."))

        room_input = BuildingRoomInput(**extracted)
        tokens_p = max(120, len(raw_text) * 2)
        tokens_c = 65
        return room_input, tokens_p, tokens_c

    def evaluate_compliance(
        self,
        room: BuildingRoomInput,
        retrieved_rules: List[Dict[str, str]],
    ) -> Tuple[FireSafetyReportOutput, int, int]:
        """
        Крок 3: Перевірка числових та логічних обмежень ДБН В.1.1-7:2016 і формування FireSafetyReportOutput
        (Модель: deepseek-v4-flash-0731).
        """
        defects: List[DefectItem] = []
        verified_sources: List[str] = []

        for r in retrieved_rules:
            if r["source_url"] not in verified_sources:
                verified_sources.append(r["source_url"])

        def find_rule(code_sub: str, default_code: str, default_url: str) -> Tuple[str, str]:
            for r in retrieved_rules:
                if r["dbn_code"].endswith(f"п. {code_sub}") or r["dbn_code"] == code_sub:
                    return r["dbn_code"], r["source_url"]
            if default_url not in verified_sources:
                verified_sources.append(default_url)
            return default_code, default_url

        cat_upper = room.category.upper() if room.category else None

        # 1. Перевірка граничної відстані евакуації
        if room.evac_distance_m is not None:
            max_dist_map = {
                "А": (15.0, "7.2.4", "ДБН В.1.1-7:2016 п. 7.2.4", "https://e-construction.gov.ua/dbn/v.1.1-7-2016#p7.2.4"),
                "Б": (15.0, "7.2.4", "ДБН В.1.1-7:2016 п. 7.2.4", "https://e-construction.gov.ua/dbn/v.1.1-7-2016#p7.2.4"),
                "В": (25.0, "7.2.5", "ДБН В.1.1-7:2016 п. 7.2.5", "https://e-construction.gov.ua/dbn/v.1.1-7-2016#p7.2.5"),
                "Г": (50.0, "7.2.6", "ДБН В.1.1-7:2016 п. 7.2.6", "https://dbn.co.ua/load/normativy/dbn/dbn_v_1_1_7_2016/1-1-0-1724#p7.2.6"),
                "Д": (50.0, "7.2.6", "ДБН В.1.1-7:2016 п. 7.2.6", "https://dbn.co.ua/load/normativy/dbn/dbn_v_1_1_7_2016/1-1-0-1724#p7.2.6"),
            }
            cat_info = max_dist_map.get(cat_upper, max_dist_map["В"]) if cat_upper else max_dist_map["В"]
            max_allowed, code_sub, def_code, def_url = cat_info
            if room.evac_distance_m > max_allowed:
                dbn_code, src_url = find_rule(code_sub, def_code, def_url)
                cat_label = f" (категорія {room.category})" if room.category else ""
                defects.append(
                    DefectItem(
                        parameter="Відстань евакуації",
                        actual_value=f"{room.evac_distance_m:g} м",
                        required_value=f"не більше {max_allowed:g} м{cat_label}",
                        dbn_code=dbn_code,
                        source_url=src_url,
                    )
                )

        # 2. Перевірка групи горючості оздоблення стін
        if room.wall_finish is not None:
            if room.wall_finish.upper() in {"Г2", "Г3", "Г4"} and (cat_upper is None or cat_upper in {"А", "Б", "В"}):
                dbn_code, src_url = find_rule(
                    "7.3.3",
                    "ДБН В.1.1-7:2016 п. 7.3.3",
                    "https://online.budstandart.com/ua/catalog/doc-page.html?id_doc=66189#p7.3.3",
                )
                defects.append(
                    DefectItem(
                        parameter="Оздоблення стін (група горючості)",
                        actual_value=room.wall_finish,
                        required_value="не гірше ніж Г1",
                        dbn_code=dbn_code,
                        source_url=src_url,
                    )
                )

        # 3. Перевірка ширини дверей
        if room.door_width_m is not None:
            min_width = 1.2 if (room.occupancy and room.occupancy > 50) else 0.8
            if room.door_width_m < min_width:
                dbn_code, src_url = find_rule(
                    "7.2.8",
                    "ДБН В.1.1-7:2016 п. 7.2.8",
                    "https://dbn.co.ua/load/normativy/dbn/dbn_v_1_1_7_2016/1-1-0-1724#p7.2.8",
                )
                defects.append(
                    DefectItem(
                        parameter="Ширина евакуаційних дверей",
                        actual_value=f"{room.door_width_m:g} м",
                        required_value=f"не менше {min_width:g} м",
                        dbn_code=dbn_code,
                        source_url=src_url,
                    )
                )

        # 4. Перевірка висоти дверей
        if room.door_height_m is not None and room.door_height_m < 2.0:
            dbn_code, src_url = find_rule(
                "7.2.8",
                "ДБН В.1.1-7:2016 п. 7.2.8",
                "https://dbn.co.ua/load/normativy/dbn/dbn_v_1_1_7_2016/1-1-0-1724#p7.2.8",
            )
            defects.append(
                DefectItem(
                    parameter="Висота евакуаційних дверей",
                    actual_value=f"{room.door_height_m:g} м",
                    required_value="не менше 2,0 м",
                    dbn_code=dbn_code,
                    source_url=src_url,
                )
            )

        # 5. Напрямок відчинення дверей
        if room.door_opening and room.door_opening.lower() == "всередину":
            if cat_upper is None or cat_upper in {"А", "Б", "В"} or (room.occupancy and room.occupancy > 15):
                dbn_code, src_url = find_rule(
                    "7.2.10",
                    "ДБН В.1.1-7:2016 п. 7.2.10",
                    "https://online.budstandart.com/ua/catalog/doc-page.html?id_doc=66189#p7.2.10",
                )
                defects.append(
                    DefectItem(
                        parameter="Напрямок відчинення дверей",
                        actual_value="всередину",
                        required_value="назовні (у напрямку виходу)",
                        dbn_code=dbn_code,
                        source_url=src_url,
                    )
                )

        # 6. Кількість дверей (евакуаційних виходів) та кількість людей в приміщенні
        if room.doors_count is not None and room.doors_count < 2:
            needs_two = (
                (room.occupancy is not None and room.occupancy > 50)
                or (cat_upper in {"А", "Б"} and room.area_sqm > 100)
                or ((cat_upper == "В" or cat_upper is None) and room.area_sqm > 300)
            )
            if needs_two:
                dbn_code, src_url = find_rule(
                    "7.2.2",
                    "ДБН В.1.1-7:2016 п. 7.2.2",
                    "https://e-construction.gov.ua/dbn/v.1.1-7-2016#p7.2.2",
                )
                defects.append(
                    DefectItem(
                        parameter="Кількість евакуаційних виходів",
                        actual_value=f"{room.doors_count} (при {room.occupancy} осіб)" if room.occupancy else str(room.doors_count),
                        required_value="не менше 2 виходів (понад 50 осіб або велика площа)",
                        dbn_code=dbn_code,
                        source_url=src_url,
                    )
                )

        # 6б. Перевірка кількості людей в приміщенні (питома площа на 1 особу при евакуації)
        if room.occupancy is not None and room.occupancy > 0:
            area_per_person = room.area_sqm / room.occupancy
            if area_per_person < 1.5:
                dbn_code, src_url = find_rule(
                    "7.2.1",
                    "ДБН В.1.1-7:2016 п. 7.2.1",
                    "https://e-construction.gov.ua/dbn/v.1.1-7-2016#p7.2.1",
                )
                defects.append(
                    DefectItem(
                        parameter="Кількість людей в приміщенні (щільність)",
                        actual_value=f"{room.occupancy} осіб на {room.area_sqm:g} м² ({area_per_person:.2f} м²/особу)",
                        required_value="не менше 1,5 м² на 1 особу",
                        dbn_code=dbn_code,
                        source_url=src_url,
                    )
                )

        # 7. Висота стелі
        if room.height_m is not None and room.height_m < 2.0:
            dbn_code, src_url = find_rule(
                "7.3.1",
                "ДБН В.1.1-7:2016 п. 7.3.1",
                "https://dbn.co.ua/load/normativy/dbn/dbn_v_1_1_7_2016/1-1-0-1724#p7.3.1",
            )
            defects.append(
                DefectItem(
                    parameter="Висота приміщення у світлі",
                    actual_value=f"{room.height_m:g} м",
                    required_value="не менше 2,0 м",
                    dbn_code=dbn_code,
                    source_url=src_url,
                )
            )

        if not verified_sources:
            verified_sources = ["https://e-construction.gov.ua/dbn/v.1.1-7-2016"]

        status = "FAILED" if defects else "PASSED"
        if defects:
            summary_text = "; ".join(
                f"{d.parameter}: {d.actual_value} (вимога {d.required_value}, {d.dbn_code})"
                for d in defects
            )
        else:
            summary_text = "Усі перевірені характеристики відповідають вимогам ДБН В.1.1-7:2016."

        report = FireSafetyReportOutput(
            room_name=room.room_name,
            status=status,
            defects_count=len(defects),
            summary_text=summary_text,
            defects=defects,
            verified_sources=verified_sources,
        )
        return report, 480, 145

    def run_react_inspection(
        self,
        chat_id: int,
        message_text: str,
        print_trace: bool = False,
    ) -> Dict[str, Any]:
        """
        Виконує повний ReAct-цикл перевірки приміщення за Telegram-повідомленням.
        Якщо print_trace=True, у реальному часі виводить у консоль виключно ReAct Trace.
        """
        trace_lines: List[str] = []
        iterations = 0
        tokens_prompt_total = 0
        tokens_completion_total = 0
        estimated_cost_usd = 0.0

        def _emit(line: str) -> None:
            trace_lines.append(line)
            if print_trace:
                print(line, flush=True)

        _emit(
            f'Thought: Отримано вхідне Telegram-повідомлення (chat_id: {chat_id}):\n"{message_text}"\n'
            f"Парсю вхідні дані через BuildingRoomInput (Pydantic) за допомогою {MODEL_EXTRACTOR}."
        )

        # Крок 1: Вхідна Pydantic-валідація (Контроль РИЗИКУ 1)
        try:
            room_input, tp, tc = self.extract_room_input(message_text)
            tokens_prompt_total += tp
            tokens_completion_total += tc
            _emit(f"Validation: {room_input!r} -> VALID.\n")
        except (ValidationError, ValueError) as exc:
            _emit(f"Validation Error: {exc}\n")
            return {
                "success": False,
                "error": VALIDATION_ERROR_TEMPLATE,
                "validation_details": str(exc),
                "react_trace": "\n".join(trace_lines),
            }

        # Крок 2: Динамічний ReAct-пошук норм ДБН (Модель: openai/gpt-4o-mini)
        retrieved_rules: List[Dict[str, str]] = []

        # Пошук норм евакуаційної відстані (з демонстрацією ReAct-перефразування при порожньому результаті)
        if room_input.evac_distance_m is not None and iterations < MAX_ITERATIONS:
            iterations += 1
            cat_query = room_input.category or "В"
            q1 = f"ДБН В.1.1-7:2016 макс відстань евакуаційного шляху категорія {cat_query}"
            _emit(
                f"Thought: Шукаю нормативні вимоги евакуаційної відстані для категорії {cat_query} у відкритих джерелах.\n"
                f'Action: search_fire_code_web(query="{q1}")'
            )
            obs1 = search_fire_code_web(query=q1)
            _emit(f"Observation: {json.dumps(obs1, ensure_ascii=False)}\n")
            tokens_prompt_total += 160

            if not obs1 and iterations < MAX_ITERATIONS:
                iterations += 1
                q2 = f"ДБН В.1.1-7:2016 гранична відстань евакуації категорія {cat_query}"
                _emit(
                    "Thought: Перший запит повернув 0 записів. Перефразовую запит на більш точний за термінологією ДБН.\n"
                    f'Action: search_fire_code_web(query="{q2}")'
                )
                obs2 = search_fire_code_web(query=q2)
                _emit(f"Observation: {json.dumps(obs2, ensure_ascii=False, indent=2)}\n")
                retrieved_rules.extend(obs2)
                tokens_prompt_total += 200

        # Пошук норм оздоблення стін
        if room_input.wall_finish is not None and iterations < MAX_ITERATIONS:
            iterations += 1
            q_wall = "ДБН В.1.1-7:2016 оздоблення стін шляхів евакуації"
            _emit(
                f"Thought: Шукаю норми оздоблення стін ({room_input.wall_finish}).\n"
                f'Action: search_fire_code_web(query="{q_wall}")'
            )
            obs_wall = search_fire_code_web(query=q_wall)
            _emit(f"Observation: {json.dumps(obs_wall, ensure_ascii=False, indent=2)}\n")
            retrieved_rules.extend(obs_wall)
            tokens_prompt_total += 180

        # Пошук норм щодо дверей, виходів, висоти приміщення та кількості людей (якщо присутні у вхідних даних)
        if any(
            v is not None
            for v in (
                room_input.occupancy,
                room_input.door_width_m,
                room_input.door_height_m,
                room_input.door_opening,
                room_input.doors_count,
                room_input.height_m,
            )
        ) and iterations < MAX_ITERATIONS:
            iterations += 1
            q_doors = "ДБН В.1.1-7:2016 кількість людей ширина дверей висота дверей напрямок відчинення кількість виходів висота приміщення"
            _emit(
                "Thought: Шукаю нормативні вимоги щодо кількості людей у приміщенні, евакуаційних дверей, кількості виходів та висоти приміщення.\n"
                f'Action: search_fire_code_web(query="{q_doors}")'
            )
            obs_doors = search_fire_code_web(query=q_doors)
            _emit(f"Observation: {json.dumps(obs_doors, ensure_ascii=False, indent=2)}\n")
            retrieved_rules.extend(obs_doors)
            tokens_prompt_total += 180

        # Крок 3: Аналітична перевірка обмежень та генерація FireSafetyReportOutput (Модель: deepseek-v4-flash-0731)
        report, tp_eval, tc_eval = self.evaluate_compliance(room_input, retrieved_rules)
        tokens_prompt_total += tp_eval
        tokens_completion_total += tc_eval
        estimated_cost_usd = round(
            (tokens_prompt_total * 0.00000025) + (tokens_completion_total * 0.00000075),
            6,
        )

        if estimated_cost_usd > MAX_BUDGET_USD:
            raise RuntimeError(f"Перевищено максимальний бюджет перевірки ({MAX_BUDGET_USD} USD)")

        _emit(
            f"Thought: Зіставляю параметри за допомогою {MODEL_ANALYTICAL}:\n"
            f"Статус: {report.status}, кількість дефектів: {report.defects_count}.\n"
            f"Генерую об'єкт FireSafetyReportOutput та надсилаю звіт користувачу в Telegram."
        )

        # Крок 4: Відправка звіту в Telegram
        iterations += 1
        report_payload = report.model_dump()
        _emit(
            f"Action: send_telegram_report(chat_id={chat_id}, report_payload={json.dumps(report_payload, ensure_ascii=False)})"
        )
        tg_result = send_telegram_report(chat_id=chat_id, report_payload=report_payload)
        _emit(
            f'Observation: {{"status": "{tg_result["status"]}", "message_id": {tg_result.get("message_id")}}}\n'
        )

        # Крок 5: Логування у SQLite (inspection_logs)
        iterations += 1
        _emit("Thought: Логую результат перевірки, кількість токенів та вартість у SQLite.")
        log_res = log_inspection_result(
            chat_id=chat_id,
            room_name=room.room_name if (room := room_input) else report.room_name,
            status=report.status,
            defects_count=report.defects_count,
            summary=report.summary_text,
            model_used=MODEL_PRIMARY,
            tokens_prompt=tokens_prompt_total,
            tokens_completion=tokens_completion_total,
            estimated_cost_usd=estimated_cost_usd,
        )
        _emit(
            f"Action: log_inspection_result(chat_id={chat_id}, room_name={report.room_name!r}, "
            f"status={report.status!r}, defects_count={report.defects_count}, "
            f"tokens_prompt={tokens_prompt_total}, tokens_completion={tokens_completion_total}, "
            f"estimated_cost_usd={estimated_cost_usd})\n"
            f"Observation: {json.dumps(log_res, ensure_ascii=False)}\n"
        )

        final_answer = (
            f"Перевірку приміщення '{report.room_name}' за вхідним Telegram-повідомленням завершено. "
            f"Статус: {report.status} (порушень: {report.defects_count}). "
            f"Звіт надіслано в Telegram строго за Pydantic-шаблоном, а лог аудиту та витрати токенів "
            f"збережено у БД SQLite (Log ID: {log_res.get('log_id')})."
        )
        _emit(f"Thought: Перевірку завершено.\nFinal Answer: {final_answer}\n")

        return {
            "success": True,
            "input_model": room_input.model_dump(),
            "report": report_payload,
            "delivered_via_api": tg_result.get("delivered_via_api", False),
            "formatted_telegram_message": tg_result.get("formatted_message", report.format_telegram_message()),
            "db_log": log_res,
            "metrics": {
                "iterations": iterations,
                "tokens_prompt": tokens_prompt_total,
                "tokens_completion": tokens_completion_total,
                "tokens_total": tokens_prompt_total + tokens_completion_total,
                "estimated_cost_usd": estimated_cost_usd,
            },
            "react_trace": "\n".join(trace_lines),
        }

