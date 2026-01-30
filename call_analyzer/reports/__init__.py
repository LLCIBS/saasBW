# call_analyzer/reports/__init__.py

from .week_full import run_week_full
from .rr_3 import run_rr_3
from .rr_bad import run_rr_bad

# Можно также объявить общий словарь/реестр для удобства
REPORT_FUNCTIONS = {
    "week_full": run_week_full,
    "rr_3": run_rr_3,
    "rr_bad": run_rr_bad
}
