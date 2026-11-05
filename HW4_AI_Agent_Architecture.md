# Домашнє завдання — Заняття 4
**Тема:** Спроєктуйте архітектуру свого AI-агента  
**Сфера:** Проєктування та інженерна протипожежна експертиза  
**Назва проєкту:** AI-агент нормативної перевірки проєктних рішень СПЗ (`FireCodeCheckerAgent`)

---

## Розділ 1. Задача та 4 компоненти архітектури

**ЗАДАЧА:**  
Отримувати параметри приміщення з Telegram-повідомлення користувача, валідувати та парсити їх у сувору Pydantic-схему (`BuildingRoomInput`), шукати протипожежні вимоги ДБН В.1.1-7:2016 у відкритих будівельних ресурсах України (`e-construction.gov.ua`, `online.budstandart.com`, `dbn.co.ua`), зіставляти характеристики на відповідність нормам та генерувати підсумкову відповідь строго за вихідним Pydantic-шаблоном (`FireSafetyReportOutput`) із мітками джерел, логуванням у БД SQLite та обліком витрат токенів.

**МОДЕЛЬ:**  
Мультимодельний стек із 3 моделей через OpenRouter / Gemini API:
1. `gemini-3.5-flash-lite` — Fast Router & Entity Extraction (парсинг Telegram-тексту у Pydantic-модель `BuildingRoomInput` з мінімальною затримкою).
2. `openai/gpt-4o-mini` — Primary ReAct & Function Calling (оркестрація цільового веб-пошуку `search_fire_code_web` та викликів логування).
3. `deepseek-v4-flash-0731` — Аналітична модель (перевірка числових обмежень та логічного форматування висновків `FireSafetyReportOutput`).

**ІНСТРУМЕНТИ:**  
1. `search_fire_code_web` — цільовий веб-пошук нормативних правил ДБН В.1.1-7:2016 у білому списку відкритих ресурсів.
2. `send_telegram_report` — відправка згенерованого звіту строго за шаблоном Pydantic `FireSafetyReportOutput` у Telegram.
3. `log_inspection_result` — збереження логу перевірки, виявлених дефектів, статистики токенів (`tokens_prompt`, `tokens_completion`, `tokens_total`) та суми витрат у доларах у SQLite.

**ПАМ'ЯТЬ:**  
- **У межах одного запуску:** Валідований об'єкт `BuildingRoomInput`, витягнуті нормативні цитати, об'єкт `FireSafetyReportOutput`.
- **Між запусками:** Таблиця `inspection_logs` у базі даних SQLite (`building_project.db`).

**ПЛАНУВАННЯ:**  
По кроку (патерн ReAct з Pydantic-валідацією входу/виходу). 
1. Парсинг Telegram-повідомлення у `BuildingRoomInput`. 
2. Виклик `search_fire_code_web`. При порожньому результаті — повторний виклик із перефразованим запитом у `Thought`. 
3. Перевірка обмежень та формування `FireSafetyReportOutput`. 
4. Надсилання в Telegram та логування у SQLite.

**ЗУПИНКА:**  
- Умова завершення: Звіт згенеровано за Pydantic-схемою, доставлено в Telegram та залоговано в `inspection_logs`.
- Максимум ітерацій: 10 спроб на запуск.
- Максимальний бюджет: 0.05 долара на перевірку.

---

## Розділ 2. Картки інструментів та Pydantic-моделі

### Pydantic-схеми даних (`schemas.py`)

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class BuildingRoomInput(BaseModel):
    room_name: str = Field(description="Назва приміщення або об'єкта")
    category: Optional[str] = Field(default=None, description="Категорія вибухопожежної небезпеки (А, Б, В, Г, Д)")
    area_sqm: float = Field(gt=0, description="Площа приміщення в м²")
    height_m: Optional[float] = Field(default=None, gt=0, description="Висота стелі в м")
    occupancy: Optional[int] = Field(default=None, ge=0, description="Кількість людей")
    doors_count: Optional[int] = Field(default=None, ge=0, description="Кількість дверей")
    door_height_m: Optional[float] = Field(default=None, gt=0, description="Висота дверей у м")
    door_width_m: Optional[float] = Field(default=None, gt=0, description="Ширина дверей у м")
    door_opening: Optional[str] = Field(default=None, description="Напрямок відчинення дверей (назовні/всередину)")
    wall_finish: Optional[str] = Field(default=None, description="Матеріал або група горючості (Г1-Г4)")
    evac_distance_m: Optional[float] = Field(default=None, ge=0, description="Фактична відстань евакуації в м")

class DefectItem(BaseModel):
    parameter: str = Field(description="Параметр, у якому виявлено відхилення")
    actual_value: str = Field(description="Фактичне значення з опису приміщення")
    required_value: str = Field(description="Нормативна вимога ДБН")
    dbn_code: str = Field(description="Код пункту ДБН В.1.1-7:2016")
    source_url: str = Field(description="Посилання на відкрите джерело ДБН")

class FireSafetyReportOutput(BaseModel):
    room_name: str
    status: str = Field(pattern="^(PASSED|FAILED)$")
    defects_count: int = Field(ge=0)
    summary_text: str
    defects: List[DefectItem] = Field(default_factory=list)
    verified_sources: List[str] = Field(default_factory=list)
```

### Картки інструментів (Prompt-Cards)

#### 1. `search_fire_code_web`
- **НАЗВА:** `search_fire_code_web`
- **ЩО РОБИТЬ:** Пошук статей ДБН В.1.1-7:2016 у відкритих реєстрах (`e-construction.gov.ua`, `online.budstandart.com`, `dbn.co.ua`).
- **КОЛИ ВИКЛИКАТИ:** Для отримання офіційних нормативних обмежень та пунктів ДБН.
- **ПАРАМЕТРИ:** `query` (рядок, обов'язковий — ключовий запит пошуку).
- **ПОВЕРТАЄ:** `[{"dbn_code": str, "rule_text": str, "source_url": str}]`.
- **ЩО МОЖЕ ПІТИ НЕ ТАК:** 0 записів через занадто складний запит; мережевий таймаут.

#### 2. `send_telegram_report`
- **НАЗВА:** `send_telegram_report`
- **ЩО РОБИТЬ:** Відправляє підсумковий звіт у Telegram користувача строго за схемою `FireSafetyReportOutput`.
- **КОЛИ ВИКЛИКАТИ:** Наприкінці аналізу після формування об'єкта `FireSafetyReportOutput`.
- **ПАРАМЕТРИ:** `chat_id` (int), `report_payload` (dict відповідає `FireSafetyReportOutput`).
- **ПОВЕРТАЄ:** `{"status": "DELIVERED", "message_id": int}`.
- **ЩО МОЖЕ ПІТИ НЕ ТАК:** Користувач заблокував бота (HTTP 403); Rate limit Telegram API.

#### 3. `log_inspection_result`
- **НАЗВА:** `log_inspection_result`
- **ЩО РОБИТЬ:** Зберігає лог перевірки, токени та витрати у БД SQLite (`building_project.db`).
- **КОЛИ ВИКЛИКАТИ:** Одразу після відправки звіту в Telegram.
- **ПАРАМЕТРИ:** `chat_id` (int), `room_name` (str), `status` (str), `defects_count` (int), `summary` (str), `model_used` (str), `tokens_prompt` (int), `tokens_completion` (int), `estimated_cost_usd` (float).
- **ПОВЕРТАЄ:** `{"log_id": int, "status": "SUCCESS"}`.
- **ЩО МОЖЕ ПІТИ НЕ ТАК:** Файл БД заблокований (`database is locked`).

---

## Розділ 3. Трасування ReAct

```text
Thought: Отримано вхідне Telegram-повідомлення (chat_id: 987654321):
"Перевірити приміщення: Складський комплекс, площа 250 кв.м, категорія В, оздоблення стін — гіпсокартон Г1, відстань до виходу — 35м."
Парсю вхідні дані через BuildingRoomInput (Pydantic).
Validation: BuildingRoomInput(room_name="Складський комплекс", category="В", area_sqm=250.0, wall_finish="Г1", evac_distance_m=35.0) -> VALID.

Thought: Шукаю нормативні вимоги евакуаційної відстані для категорії В у відкритих джерелах.
Action: search_fire_code_web(query="ДБН В.1.1-7:2016 макс відстань евакуаційного шляху категорія В")
Observation: []

Thought: Перший запит повернув 0 записів. Перефразовую запит на більш точний за термінологією ДБН.
Action: search_fire_code_web(query="ДБН В.1.1-7:2016 гранична відстань евакуації категорія В")
Observation: [
  {
    "dbn_code": "ДБН В.1.1-7:2016 п. 7.2.5",
    "rule_text": "Гранична відстань від найвіддаленішої точки приміщення категорії В до евакуаційного виходу становить не більше 25 м.",
    "source_url": "e-construction.gov.ua"
  }
]

Thought: Знайдено норму п. 7.2.5 (макс. 25 м). Шукаю норми оздоблення стін Г1.
Action: search_fire_code_web(query="ДБН В.1.1-7:2016 оздоблення стін шляхів евакуації")
Observation: [
  {
    "dbn_code": "ДБН В.1.1-7:2016 п. 7.3.3",
    "rule_text": "На шляхах евакуації дозволено оздоблення матеріалами не гірше ніж Г1.",
    "source_url": "online.budstandart.com"
  }
]

Thought: Зіставляю параметри:
1. Відстань евакуації: Фактична 35м > Нормативна 25м. Порушення п. 7.2.5!
2. Оздоблення стін: Г1 відповідає вимогам п. 7.3.3.
Генерую об'єкт FireSafetyReportOutput з дефектом перевищення відстані на 10м.

Надсилаю звіт користувачу в Telegram.
Action: send_telegram_report(chat_id=987654321, report_payload={...})
Observation: {"status": "DELIVERED", "message_id": 92105}

Thought: Логую результат перевірки, кількість токенів та вартість у SQLite.
Action: log_inspection_result(
  chat_id=987654321,
  room_name="Складський комплекс",
  status="FAILED",
  defects_count=1,
  summary="Перевищення відстані евакуації на 10м (п. 7.2.5)",
  model_used="openai/gpt-4o-mini",
  tokens_prompt=840,
  tokens_completion=210,
  estimated_cost_usd=0.00035
)
Observation: {"log_id": 102, "status": "SUCCESS"}

Thought: Перевірку завершено.
Final Answer: Перевірку приміщення 'Складський комплекс' за вхідним Telegram-повідомленням завершено. Знайдено 1 порушення ДБН В.1.1-7:2016 п. 7.2.5. Звіт надіслано в Telegram строго за Pydantic-шаблоном, а лог аудиту та витрати токенів збережено у БД SQLite (Log ID: 102).
```

---

## Розділ 4. Обґрунтування вибору патерну

Обрано **динамічний патерн ReAct з Pydantic-валідацією та структурованим виводом**.

**Обґрунтування:**
1. **Суворість типів даних:** Pydantic на вході (`BuildingRoomInput`) та виході (`FireSafetyReportOutput`) виключає галюцинації у структурі відповідей.
2. **Динамічний пошук та повторні спроби:** Оскільки веб-пошук може повертати порожній результат (як на кроці 2), ReAct дозволяє скоригувати пошукові теги і виконати повторний запит.
3. **Безпечність та контроль:** Дії агента є інформаційними, а логування у SQLite забезпечує прозорий облік токенів та вартості.

---

## Розділ 5. Ризики та заходи контролю

```text
РИЗИК 1:    Помилковий парсинг Telegram-повідомлення (некоректні типи даних чи пропущені обопільні поля).
КОНТРОЛЬ:   Валідація через Pydantic-модель BuildingRoomInput. При ValidationError агент автоматично повертає користувачу сповіщення з підказкою-шаблоном.

РИЗИК 2:    Повернення сторонніх ненадійних веб-сайтів або застарілих норм.
КОНТРОЛЬ:   У search_fire_code_web діє строгий білий список доменів (e-construction.gov.ua, online.budstandart.com, dbn.co.ua) та обов'язкове посилання на джерело.

РИЗИК 3:    Блокування файлу локальної БД SQLite (database is locked).
КОНТРОЛЬ:   Параметр connection timeout=10.0 та retry loop до 3 спроб у log_inspection_result.
```

---

## Розділ 6. Інструкції з розгортання Venv, Requirements та Безпеки

### 1. Віртуальне середовище (`.venv`)
```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Файл залежностей (`requirements.txt`)
```text
pydantic>=2.5.0
python-telegram-bot>=20.7
openai>=1.12.0
google-genai>=0.1.0
python-dotenv>=1.0.0
requests>=2.31.0
sqlite-utils>=3.35
```

### 3. Конфігурація секретів (`.env` & `.gitignore`)

Файл `.env`:
```text
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN
OPENROUTER_API_KEY=YOUR_OPENROUTER_KEY
GEMINI_API_KEY=YOUR_GEMINI_KEY
DATABASE_PATH=building_project.db
```

Файл `.gitignore`:
```text
.env
.venv/
env/
__pycache__/
*.db
*.log
```
