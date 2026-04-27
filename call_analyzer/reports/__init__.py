# call_analyzer/reports/__init__.py

from .week_full import run_week_full

# Можно также объявить общий словарь/реестр для удобства
REPORT_FUNCTIONS = {
    "week_full": run_week_full,
}
