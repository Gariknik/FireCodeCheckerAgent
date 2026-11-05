from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class BuildingRoomInput(BaseModel):
    room_name: str = Field(min_length=1, description="Назва приміщення або об'єкта")
    category: Optional[str] = Field(default=None, description="Категорія вибухопожежної небезпеки (А, Б, В, Г, Д)")
    area_sqm: float = Field(gt=0, description="Площа приміщення в м²")
    height_m: Optional[float] = Field(default=None, gt=0, description="Висота стелі в м")
    occupancy: Optional[int] = Field(default=None, ge=0, description="Кількість людей в приміщенні")
    doors_count: Optional[int] = Field(default=None, ge=0, description="Кількість дверей")
    door_height_m: Optional[float] = Field(default=None, gt=0, description="Висота дверей у м")
    door_width_m: Optional[float] = Field(default=None, gt=0, description="Ширина дверей у м")
    door_opening: Optional[str] = Field(default=None, description="Напрямок відчинення дверей (назовні/всередину)")
    wall_finish: Optional[str] = Field(default=None, description="Матеріал оздоблення стін або група горючості (Г1-Г4)")
    evac_distance_m: Optional[float] = Field(default=None, ge=0, description="Фактична відстань евакуації в м")

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cat_map = {"A": "А", "B": "Б", "V": "В", "G": "Г", "D": "Д"}
        cleaned = cat_map.get(v.strip().upper(), v.strip().upper())
        if cleaned not in {"А", "Б", "В", "Г", "Д"}:
            raise ValueError("Категорія має бути однією з: А, Б, В, Г, Д")
        return cleaned


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

    def format_telegram_message(self) -> str:
        """Формує повідомлення для Telegram строго за шаблонами System Prompt."""
        def _safe_md_source(url: str) -> str:
            # Екрануємо символ '_' у відкритому тексті URL, щоб Telegram Markdown не вважав його курсивом
            return url.replace("_", r"\_")

        if self.status == "PASSED":
            sources_list = [_safe_md_source(s) for s in self.verified_sources]
            sources_str = ", ".join(sources_list) if sources_list else "e-construction.gov.ua"
            return (
                f"🟢 РЕЗУЛЬТАТ НОРМАТИВНОГО АУДИТУ ДБН В.1.1-7:2016\n"
                f"Приміщення: {self.room_name}\n"
                f"Статус: ВІДПОВІДАЄ НОРМАМ\n\n"
                f"ℹ️ Усі перевірені характеристики відповідають вимогам ДБН В.1.1-7:2016.\n\n"
                f"🔗 Джерело: {sources_str}"
            )
        else:
            defects_lines = []
            for idx, d in enumerate(self.defects, start=1):
                defects_lines.append(
                    f"{idx}. {d.parameter}: Фактично {d.actual_value} (Вимога: {d.required_value}).\n"
                    f"   Посилання: [{d.dbn_code}]({d.source_url})"
                )
            defects_block = "\n".join(defects_lines)
            sources_block = "\n".join(f"- {_safe_md_source(src)}" for src in self.verified_sources)
            return (
                f"🔴 РЕЗУЛЬТАТ НОРМАТИВНОГО АУДИТУ ДБН В.1.1-7:2016\n"
                f"Приміщення: {self.room_name}\n"
                f"Статус: ВИЯВЛЕНО ВІДХИЛЕННЯ ({self.defects_count})\n\n"
                f"❌ Перелік порушень:\n"
                f"{defects_block}\n\n"
                f"🔗 Перевірені джерела:\n"
                f"{sources_block}"
            )

