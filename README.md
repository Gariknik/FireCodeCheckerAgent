# FireCodeCheckerAgent 🔥

Інженерний AI-агент та Telegram-бот для автоматизованого нормативного аудиту приміщень за **ДБН В.1.1-7:2016 «Пожежна безпека об'єктів будівництва»** з використанням патерну **ReAct**, суворої валідації **Pydantic** та логуванням токенів/витрат у **SQLite**.

---

## 📁 Структура проєкту

```text
FireCodeCheckerAgent/
├── src/                        # Основний вихідний код агента
│   ├── __init__.py
│   ├── schemas.py              # Pydantic-схеми (BuildingRoomInput, DefectItem, FireSafetyReportOutput)
│   ├── database.py             # Робота з БД SQLite (inspection_logs) та консольне форматування логів
│   ├── tools.py                # Інструменти агента (search_fire_code_web, send_telegram_report, log_inspection_result)
│   ├── agent.py                # Клас FireCodeCheckerAgent (парсинг, ReAct-цикл, перевірка норм ДБН)
│   └── bot.py                  # Telegram-бот (команди /start, /logs та обробка повідомлень)
├── tests/                      # Автоматизовані Unit-тести
│   ├── __init__.py
│   └── test_agent.py           # Повне покриття функціоналу (8 тестових наборів)
├── docs/                       # Проєктна документація та системний промпт
│   ├── Antigravity_System_Prompt.md
│   └── HW4_AI_Agent_Architecture.md
├── main.py                     # Єдина точка входу (CLI демо, перегляд логів з БД, запуск бота)
├── requirements.txt            # Залежності Python
├── .env.example                # Шаблон змінних середовища
└── .gitignore                  # Захист секретів (.env, .venv, *.db)
```

---

## 🚀 Швидкий старт та команди CLI

### 1. Запуск Telegram-бота
```powershell
.\.venv\Scripts\python.exe main.py --bot
```

### 2. Отримання логів із бази даних SQLite у консоль
Вивести таблицю останніх перевірок і загальну статистику токенів/витрат:
```powershell
.\.venv\Scripts\python.exe main.py --logs
```

Додаткові фільтри для перегляду логів у консолі:
```powershell
# Вивести останні 5 записів
.\.venv\Scripts\python.exe main.py --logs --limit 5

# Вивести лише перевірки з порушеннями (FAILED) або успішні (PASSED)
.\.venv\Scripts\python.exe main.py --logs --status FAILED

# Вивести логи конкретного користувача за його Telegram chat_id
.\.venv\Scripts\python.exe main.py --logs --chat-id 484076222

# Вивести логи та статистику у форматі JSON
.\.venv\Scripts\python.exe main.py --logs --json
```

### 3. Запуск демонстраційних ReAct-сценаріїв (6 сценаріїв)
```powershell
.\.venv\Scripts\python.exe main.py
```

### 4. Запуск Unit-тестів
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
