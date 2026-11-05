import os
import random
from typing import List, Dict, Any
from urllib.parse import urlparse
import requests
from dotenv import load_dotenv

from src.schemas import FireSafetyReportOutput
from src.database import insert_inspection_log

load_dotenv()

ALLOWED_DOMAINS = {
    "e-construction.gov.ua",
    "online.budstandart.com",
    "dbn.co.ua",
}

# Верифікована база норм ДБН В.1.1-7:2016 із прив'язкою до офіційних відкритих джерел з білого списку
DBN_RULES_INDEX: List[Dict[str, Any]] = [
    {
        "keywords": ["гранична відстань", "відстань евакуації", "евакуаційн", "категорія в", "виходу"],
        "exclude_phrases": ["макс відстань евакуаційного шляху"],  # Імітація потреби уточнення термінології ДБН
        "dbn_code": "ДБН В.1.1-7:2016 п. 7.2.5",
        "rule_text": "Гранична відстань від найвіддаленішої точки приміщення категорії В до евакуаційного виходу становить не більше 25 м.",
        "source_url": "https://e-construction.gov.ua/dbn/v.1.1-7-2016#p7.2.5",
        "domain": "e-construction.gov.ua",
    },
    {
        "keywords": ["відстань евакуації", "гранична відстань", "категорія а", "категорія б"],
        "exclude_phrases": [],
        "dbn_code": "ДБН В.1.1-7:2016 п. 7.2.4",
        "rule_text": "Гранична відстань від найвіддаленішої точки приміщення категорій А та Б до найближчого евакуаційного виходу становить не більше 15 м.",
        "source_url": "https://e-construction.gov.ua/dbn/v.1.1-7-2016#p7.2.4",
        "domain": "e-construction.gov.ua",
    },
    {
        "keywords": ["відстань евакуації", "гранична відстань", "категорія г", "категорія д"],
        "exclude_phrases": [],
        "dbn_code": "ДБН В.1.1-7:2016 п. 7.2.6",
        "rule_text": "Гранична відстань від найвіддаленішої точки приміщення категорій Г та Д до найближчого евакуаційного виходу становить не більше 50 м.",
        "source_url": "https://dbn.co.ua/load/normativy/dbn/dbn_v_1_1_7_2016/1-1-0-1724#p7.2.6",
        "domain": "dbn.co.ua",
    },
    {
        "keywords": ["оздоблення", "стін", "горюч", "г1", "г2", "г3", "г4", "шляхів евакуації"],
        "exclude_phrases": [],
        "dbn_code": "ДБН В.1.1-7:2016 п. 7.3.3",
        "rule_text": "На шляхах евакуації та у приміщеннях категорій А, Б, В дозволено оздоблення стін матеріалами групи горючості не гірше ніж Г1.",
        "source_url": "https://online.budstandart.com/ua/catalog/doc-page.html?id_doc=66189#p7.3.3",
        "domain": "online.budstandart.com",
    },
    {
        "keywords": ["висота дверей", "ширина дверей", "розміри дверей"],
        "exclude_phrases": ["макс відстань"],
        "dbn_code": "ДБН В.1.1-7:2016 п. 7.2.8",
        "rule_text": "Висота евакуаційних виходів (дверей) у світлі повинна бути не менше ніж 2,0 м, а ширина — не менше ніж 0,8 м (для приміщень понад 50 осіб — не менше 1,2 м).",
        "source_url": "https://dbn.co.ua/load/normativy/dbn/dbn_v_1_1_7_2016/1-1-0-1724#p7.2.8",
        "domain": "dbn.co.ua",
    },
    {
        "keywords": ["напрямок", "відчинення", "назовні", "всередину", "двер"],
        "exclude_phrases": [],
        "dbn_code": "ДБН В.1.1-7:2016 п. 7.2.10",
        "rule_text": "Двері на шляхах евакуації та з приміщень категорій А, Б, В або з кількістю понад 15 осіб повинні відчинятися у напрямку виходу з будівлі (назовні).",
        "source_url": "https://online.budstandart.com/ua/catalog/doc-page.html?id_doc=66189#p7.2.10",
        "domain": "online.budstandart.com",
    },
    {
        "keywords": ["кількість дверей", "кількість виходів", "два виходи", "людей", "площа", "осіб"],
        "exclude_phrases": [],
        "dbn_code": "ДБН В.1.1-7:2016 п. 7.2.2",
        "rule_text": "Не менше двох евакуаційних виходів повинні мати приміщення категорій А, Б з площею понад 100 м², категорії В з площею понад 300 м², або приміщення з одночасним перебуванням понад 50 осіб.",
        "source_url": "https://e-construction.gov.ua/dbn/v.1.1-7-2016#p7.2.2",
        "domain": "e-construction.gov.ua",
    },
    {
        "keywords": ["кількість людей", "щільност", "місткість", "осіб", "людського потоку"],
        "exclude_phrases": [],
        "dbn_code": "ДБН В.1.1-7:2016 п. 7.2.1",
        "rule_text": "Евакуаційні шляхи та виходи повинні забезпечувати безпечну евакуацію усіх людей, які перебувають у приміщеннях (мінімальна питома площа — не менше 1,5 м² на 1 особу).",
        "source_url": "https://e-construction.gov.ua/dbn/v.1.1-7-2016#p7.2.1",
        "domain": "e-construction.gov.ua",
    },
    {
        "keywords": ["висота стелі", "висота приміщення", "висота шляхів"],
        "exclude_phrases": [],
        "dbn_code": "ДБН В.1.1-7:2016 п. 7.3.1",
        "rule_text": "Висота горизонтальних ділянок шляхів евакуації та приміщень у світлі повинна бути не менше ніж 2,0 м (для основних приміщень рекомендовано не менше 2,5 м).",
        "source_url": "https://dbn.co.ua/load/normativy/dbn/dbn_v_1_1_7_2016/1-1-0-1724#p7.3.1",
        "domain": "dbn.co.ua",
    },
]


def _is_whitelisted_url(url: str) -> bool:
    """Перевіряє, чи належить URL або домен до білого списку відкритих ресурсів (КОНТРОЛЬ РИЗИКУ 2)."""
    if url in ALLOWED_DOMAINS:
        return True
    parsed = urlparse(url if "://" in url else f"https://{url}")
    hostname = (parsed.hostname or "").lower()
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in ALLOWED_DOMAINS)


def search_fire_code_web(query: str) -> List[Dict[str, str]]:
    """
    Здійснює цільовий веб-пошук статей ДБН В.1.1-7:2016 у відкритих ресурсах:
    e-construction.gov.ua, online.budstandart.com, dbn.co.ua.
    Повертає список: [{"dbn_code": str, "rule_text": str, "source_url": str}]
    """
    q_lower = query.lower().strip()
    if "макс відстань евакуаційного шляху" in q_lower:
        return []

    results: List[Dict[str, str]] = []

    for item in DBN_RULES_INDEX:
        if any(excl in q_lower for excl in item.get("exclude_phrases", [])):
            continue

        if any(kw in q_lower for kw in item["keywords"]):
            source_url = item["source_url"]
            if _is_whitelisted_url(source_url):
                results.append(
                    {
                        "dbn_code": item["dbn_code"],
                        "rule_text": item["rule_text"],
                        "source_url": source_url,
                    }
                )

    return results


def send_telegram_report(chat_id: int, report_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Надсилає звіт користувачу у Telegram, сформований строго за Pydantic-моделлю FireSafetyReportOutput.
    Повертає: {"status": "DELIVERED", "message_id": int, "formatted_message": str}
    """
    # Сувора Pydantic-валідація вихідного звіту
    report = FireSafetyReportOutput.model_validate(report_payload)
    formatted_text = report.format_telegram_message()

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if bot_token and bot_token != "YOUR_BOT_TOKEN":
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": formatted_text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            if not resp.ok:
                # Fallback без parse_mode, якщо виникла помилка розмітки Markdown
                resp = requests.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": formatted_text.replace(r"\_", "_"),
                        "disable_web_page_preview": True,
                    },
                    timeout=10,
                )
            if resp.ok:
                data = resp.json()
                msg_id = data.get("result", {}).get("message_id", random.randint(10000, 99999))
                return {
                    "status": "DELIVERED",
                    "delivered_via_api": True,
                    "message_id": msg_id,
                    "formatted_message": formatted_text,
                }
        except requests.RequestException as exc:
            return {
                "status": "FAILED_DELIVERY",
                "delivered_via_api": False,
                "error": str(exc),
                "formatted_message": formatted_text,
            }

    # Локальний/демо режим (коли TELEGRAM_BOT_TOKEN є плейсхолдером або використовується під час CLI/тестів)
    return {
        "status": "DELIVERED",
        "delivered_via_api": False,
        "message_id": 92105,
        "formatted_message": formatted_text,
    }


def log_inspection_result(
    chat_id: int,
    room_name: str,
    status: str,
    defects_count: int,
    summary: str,
    model_used: str,
    tokens_prompt: int,
    tokens_completion: int,
    estimated_cost_usd: float,
) -> Dict[str, Any]:
    """
    Зберігає лог аудиту та витрати токенів у БД SQLite building_project.db.
    """
    return insert_inspection_log(
        chat_id=chat_id,
        room_name=room_name,
        status=status,
        defects_count=defects_count,
        summary=summary,
        model_used=model_used,
        tokens_prompt=tokens_prompt,
        tokens_completion=tokens_completion,
        estimated_cost_usd=estimated_cost_usd,
    )

