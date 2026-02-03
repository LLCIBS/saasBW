# -*- coding: utf-8 -*-
"""
Возвращает пути к шаблонам для отраслевых профилей.
При добавлении нового профиля создайте папку с файлами:
  prompts.yaml, additional_vocab.yaml, script_prompt_8.yaml
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDUSTRY_ROOT = Path(__file__).resolve().parent


def get_template_path(profile: str, filename: str) -> Path | None:
    """
    Возвращает путь к файлу шаблона для данного профиля.
    Для autoservice использует корневые файлы проекта (legacy).
    Для остальных — папку industry_profiles/<profile>/.
    """
    profile = (profile or "autoservice").lower().strip()
    if profile not in ("autoservice", "restaurant", "dental", "retail", "medical", "universal"):
        profile = "universal"

    if profile == "autoservice":
        # Автосервис — используем корневые файлы проекта
        root_path = PROJECT_ROOT / filename
        if root_path.exists():
            return root_path
        # Fallback на industry_profiles/autoservice/ если есть
        alt = INDUSTRY_ROOT / "autoservice" / filename
        return alt if alt.exists() else root_path

    template_path = INDUSTRY_ROOT / profile / filename
    if template_path.exists():
        return template_path
    # Fallback на universal
    if profile != "universal":
        fallback = INDUSTRY_ROOT / "universal" / filename
        if fallback.exists():
            return fallback
    return template_path


def get_all_template_paths(profile: str) -> dict[str, Path | None]:
    """Возвращает словарь {ключ: путь} для prompts, vocabulary, script_prompt."""
    return {
        "prompts_file": get_template_path(profile, "prompts.yaml"),
        "additional_vocab_file": get_template_path(profile, "additional_vocab.yaml"),
        "script_prompt_file": get_template_path(profile, "script_prompt_8.yaml"),
    }
