import re
from colorama import init, Fore, Back, Style as ColoramaStyle

# Ініціалізуємо colorama для кросплатформної підтримки кольорів у Windows PowerShell / CMD / Linux
init(autoreset=False)


class Style:
    RESET = ColoramaStyle.RESET_ALL
    BOLD = ColoramaStyle.BRIGHT
    DIM = ColoramaStyle.DIM
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # Основні кольори через colorama.Fore
    RED = Fore.LIGHTRED_EX
    GREEN = Fore.LIGHTGREEN_EX
    YELLOW = Fore.LIGHTYELLOW_EX
    BLUE = Fore.LIGHTBLUE_EX
    MAGENTA = Fore.LIGHTMAGENTA_EX
    CYAN = Fore.LIGHTCYAN_EX
    WHITE = Fore.LIGHTWHITE_EX
    GRAY = Fore.LIGHTBLACK_EX

    # Фонові бейджі через colorama.Back + Fore + Style
    BG_BLUE = Back.BLUE + Fore.LIGHTWHITE_EX + ColoramaStyle.BRIGHT
    BG_GREEN = Back.GREEN + Fore.LIGHTWHITE_EX + ColoramaStyle.BRIGHT
    BG_RED = Back.RED + Fore.LIGHTWHITE_EX + ColoramaStyle.BRIGHT
    BG_YELLOW = Back.YELLOW + Fore.BLACK + ColoramaStyle.BRIGHT
    BG_MAGENTA = Back.MAGENTA + Fore.LIGHTWHITE_EX + ColoramaStyle.BRIGHT
    BG_CYAN = Back.CYAN + Fore.BLACK + ColoramaStyle.BRIGHT


def colorize_react_block(raw_block: str) -> str:
    """
    Перетворює текстовий блок ReAct Trace (Thought / Validation / Action / Observation / Final Answer)
    у кольоровий, зручний для читання консольний вивід за допомогою бібліотеки colorama.
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
            colored_line = line
            colored_line = colored_line.replace("FAILED", f"{Style.BOLD}{Style.RED}FAILED{Style.RESET}")
            colored_line = colored_line.replace("PASSED", f"{Style.BOLD}{Style.GREEN}PASSED{Style.RESET}")
            styled_lines.append(f"{Style.GRAY}{colored_line}{Style.RESET}")

    return "\n".join(styled_lines)
