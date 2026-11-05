import os
import re
import sys

# Активуємо підтримку ANSI-кольорів у консолі Windows (PowerShell / CMD)
if os.name == "nt":
    os.system("")


class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # Основні кольори
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"

    # Фонові бейджі
    BG_BLUE = "\033[44;97;1m"
    BG_GREEN = "\033[42;97;1m"
    BG_RED = "\033[41;97;1m"
    BG_YELLOW = "\033[43;30;1m"
    BG_MAGENTA = "\033[45;97;1m"
    BG_CYAN = "\033[46;30;1m"


def colorize_react_block(raw_block: str) -> str:
    """
    Перетворює текстовий блок ReAct Trace (Thought / Validation / Action / Observation / Final Answer)
    у кольоровий, зручний для читання консольний вивід із жирними мітками та підсвіткою.
    """
    lines = raw_block.splitlines()
    styled_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            styled_lines.append("")
            continue

        # 1. Thought
        if stripped.startswith("Thought:"):
            content = stripped[len("Thought:"):].strip()
            # Підсвічуємо назви моделей
            content = re.sub(
                r"(gemini-3\.5-flash-lite|openai/gpt-4o-mini|deepseek-v4-flash-0731)",
                f"{Style.BOLD}{Style.MAGENTA}\\1{Style.RESET}{Style.CYAN}",
                content,
            )
            styled_lines.append(
                f"{Style.BOLD}{Style.CYAN}🧠 Thought:{Style.RESET} {Style.CYAN}{content}{Style.RESET}"
            )

        # 2. Validation (успішна)
        elif stripped.startswith("Validation:"):
            content = stripped[len("Validation:"):].strip()
            content = content.replace(
                "-> VALID.",
                f"{Style.BOLD}{Style.GREEN}✔ VALID{Style.RESET}",
            )
            styled_lines.append(
                f"{Style.BOLD}{Style.GREEN}✅ Validation:{Style.RESET} {Style.WHITE}{content}{Style.RESET}"
            )

        # 3. Validation Error
        elif stripped.startswith("Validation Error:"):
            content = stripped[len("Validation Error:"):].strip()
            styled_lines.append(
                f"{Style.BOLD}{Style.RED}❌ Validation Error:{Style.RESET} {Style.RED}{content}{Style.RESET}"
            )

        # 4. Action
        elif stripped.startswith("Action:"):
            content = stripped[len("Action:"):].strip()
            # Виділяємо ім'я інструменту жирним пурпуровим кольором
            content = re.sub(
                r"^([a-zA-Z0-9_]+)\(",
                f"{Style.BOLD}{Style.MAGENTA}\\1{Style.RESET}{Style.YELLOW}(",
                content,
            )
            styled_lines.append(
                f"{Style.BOLD}{Style.YELLOW}⚡ Action:{Style.RESET} {Style.YELLOW}{content}{Style.RESET}"
            )

        # 5. Observation
        elif stripped.startswith("Observation:"):
            content = stripped[len("Observation:"):].strip()
            if content == "[]":
                styled_lines.append(
                    f"{Style.BOLD}{Style.BLUE}🔎 Observation:{Style.RESET} "
                    f"{Style.BOLD}{Style.RED}[] (0 записів знайдено — потрібен повторний запит){Style.RESET}"
                )
            else:
                styled_lines.append(
                    f"{Style.BOLD}{Style.BLUE}🔎 Observation:{Style.RESET} {Style.GRAY}{content}{Style.RESET}"
                )

        # 6. Final Answer
        elif stripped.startswith("Final Answer:"):
            content = stripped[len("Final Answer:"):].strip()
            if "FAILED" in content:
                content = content.replace("FAILED", f"{Style.BG_RED} FAILED {Style.RESET}{Style.BOLD}{Style.WHITE}")
            elif "PASSED" in content:
                content = content.replace("PASSED", f"{Style.BG_GREEN} PASSED {Style.RESET}{Style.BOLD}{Style.WHITE}")

            border = f"{Style.BOLD}{Style.GREEN}{'━' * 95}{Style.RESET}"
            styled_lines.append(border)
            styled_lines.append(
                f"{Style.BOLD}{Style.GREEN}🏁 Final Answer:{Style.RESET} {Style.BOLD}{Style.WHITE}{content}{Style.RESET}"
            )
            styled_lines.append(border)

        # 7. JSON-рядки всередині Observation або цитати повідомлення
        elif stripped.startswith('"dbn_code"'):
            styled_lines.append(f"    {Style.BOLD}{Style.GREEN}{stripped}{Style.RESET}")
        elif stripped.startswith('"rule_text"'):
            styled_lines.append(f"    {Style.WHITE}{stripped}{Style.RESET}")
        elif stripped.startswith('"source_url"'):
            styled_lines.append(f"    {Style.UNDERLINE}{Style.CYAN}{stripped}{Style.RESET}")
        elif stripped.startswith('"') and stripped.endswith('"'):
            styled_lines.append(f"   {Style.ITALIC}{Style.WHITE}{stripped}{Style.RESET}")
        else:
            # Додаткова підсвітка статусів у звичайних рядках
            colored_line = line
            colored_line = colored_line.replace("FAILED", f"{Style.BOLD}{Style.RED}FAILED{Style.RESET}")
            colored_line = colored_line.replace("PASSED", f"{Style.BOLD}{Style.GREEN}PASSED{Style.RESET}")
            styled_lines.append(f"{Style.GRAY}{colored_line}{Style.RESET}")

    return "\n".join(styled_lines)
