# call_analyzer/reports/__init__.py

from .week_full import run_week_full
from .rr_3 import run_rr_3
from .skolko_52 import run_skolko_52

# Можно также объявить общий словарь/реестр для удобства
REPORT_FUNCTIONS = {
    "week_full": run_week_full,
    "rr_3": run_rr_3,
    "skolko_52": run_skolko_52
}
