"""
Совмещённая конфигурация:
- `config.settings` — новые настройки Flask/БД.
- `call_analyzer/config.py` — legacy-конфиг, который ждут сервисы анализа.
"""

from pathlib import Path
import importlib.util
import sys

from .settings import get_config

__all__ = ['get_config']

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LEGACY_CONFIG_PATH = _PROJECT_ROOT / 'call_analyzer' / 'config.py'
_LEGACY_MODULE_NAME = '_legacy_call_analyzer_config'
_legacy_module = None


def _load_legacy():
    """Ленивая загрузка call_analyzer/config.py."""
    global _legacy_module
    if _legacy_module is not None:
        return _legacy_module

    if not _LEGACY_CONFIG_PATH.exists():
        _legacy_module = None
        return None

    spec = importlib.util.spec_from_file_location(
        _LEGACY_MODULE_NAME,
        str(_LEGACY_CONFIG_PATH)
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[_LEGACY_MODULE_NAME] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    _legacy_module = module

    for attr in dir(module):
        if attr.startswith('__'):
            continue
        globals().setdefault(attr, getattr(module, attr))

    return _legacy_module


def reload_legacy_config():
    """Принудительная перезагрузка legacy-конфига."""
    global _legacy_module
    _legacy_module = None
    return _load_legacy()


def __getattr__(name):
    legacy = _load_legacy()
    if legacy and hasattr(legacy, name):
        value = getattr(legacy, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'config' has no attribute '{name}'")


_load_legacy()
