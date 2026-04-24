from __future__ import annotations

import json
import os
import threading
import time
from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import requests
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from classification_module.classification_engine import CallClassificationEngine
from classification_module.classification_rules import ClassificationRulesManager
from classification_module.max_notify import send_excel_report_to_max
from classification_module.self_learning_system import SelfLearningSystem
from classification_module.training_examples import TrainingExamplesManager
from database.models import (
    User,
    UserConfig,
    UserClassificationMetric,
    UserClassificationSuccessStat,
    UserCorrectClassification,
    UserCorrectionHistory,
    UserStation,
    UserStationMapping,
    UserTrainingExample,
)


classification_bp = Blueprint("classification", __name__, url_prefix="/classification")

_tasks_lock = threading.Lock()
_classification_tasks: Dict[str, Dict] = {}
_schedule_task_map: Dict[str, str] = {}
_running_schedule_keys = set()
_scheduler_thread: threading.Thread | None = None
_scheduler_stop_event = threading.Event()
_scheduler_check_interval = 60


def _schedule_key(user_id: int, schedule_id: int) -> str:
    return f"{int(user_id)}:{int(schedule_id)}"


def _user_base_records_path_for(user_id: int) -> Path:
    cfg = UserConfig.query.filter_by(user_id=int(user_id)).first()
    if cfg and cfg.base_records_path:
        return Path(cfg.base_records_path)
    base_root = Path(str(current_app.config.get("BASE_RECORDS_PATH", Path.cwd())))
    return base_root / "users" / str(user_id)


def _classification_root_for(user_id: int) -> Path:
    root = _user_base_records_path_for(user_id) / "classification"
    root.mkdir(parents=True, exist_ok=True)
    (root / "uploads").mkdir(parents=True, exist_ok=True)
    return root


def _uploads_dir_for(user_id: int) -> Path:
    return _classification_root_for(user_id) / "uploads"


def _user_base_records_path() -> Path:
    return _user_base_records_path_for(int(current_user.id))


def _classification_root() -> Path:
    return _classification_root_for(int(current_user.id))


def _uploads_dir() -> Path:
    return _uploads_dir_for(int(current_user.id))


def _rules_manager() -> ClassificationRulesManager:
    return ClassificationRulesManager(
        user_id=int(current_user.id), classification_root=_classification_root()
    )


def _normalize_llm_base_url(raw_url: str) -> str:
    url = (raw_url or "").strip()
    if not url:
        return "https://api.deepseek.com/v1"
    lower_url = url.lower().rstrip("/")
    if lower_url.endswith("/chat/completions"):
        return url[: -len("/chat/completions")].rstrip("/")
    return url


def _resolve_user_llm_settings(user=None, user_id: int | None = None) -> Tuple[str, str, str]:
    """
    Берем LLM-настройки из того же runtime-конфига, что и основной пайплайн ЛК.
    Это гарантирует единый источник истины для аудио-обработки и классификации.
    """
    api_key = ""
    base_url_raw = ""
    model = ""

    actual_user = user
    if actual_user is None and user_id is not None:
        actual_user = User.query.get(int(user_id))
    if actual_user is None and hasattr(current_user, "is_authenticated") and current_user.is_authenticated:
        actual_user = current_user

    try:
        # Локальный импорт, чтобы избежать циклического импорта на этапе загрузки модуля.
        from web_interface.app import build_user_runtime_config
        runtime_cfg = build_user_runtime_config(user=actual_user)
        api_keys = runtime_cfg.get("api_keys", {}) if isinstance(runtime_cfg, dict) else {}
        api_key = str(api_keys.get("thebai_api_key", "") or "").strip()
        base_url_raw = str(api_keys.get("thebai_url", "") or "").strip()
        model = str(api_keys.get("thebai_model", "") or "").strip()
    except Exception:
        # Fallback на прежнюю логику, если runtime-конфиг недоступен.
        uid = int(getattr(actual_user, "id", 0) or 0)
        cfg = UserConfig.query.filter_by(user_id=uid).first() if uid else None
        api_key = str(getattr(cfg, "thebai_api_key", "") or "").strip()
        base_url_raw = str(getattr(cfg, "thebai_url", "") or "").strip()
        model = str(getattr(cfg, "thebai_model", "") or "").strip()

    if not api_key:
        api_key = str(current_app.config.get("THEBAI_API_KEY", "")).strip() or "local"
    if not base_url_raw:
        base_url_raw = str(current_app.config.get("THEBAI_URL", "")).strip()
    if not model:
        model = str(current_app.config.get("THEBAI_MODEL", "")).strip() or "deepseek-chat"

    return api_key, base_url_raw, model


def _scan_transcript_folders(limit: int = 100) -> List[Dict]:
    base = _user_base_records_path()
    if not base.exists():
        return []

    folders = []
    for transcript_dir in base.rglob("transcript"):
        if not transcript_dir.is_dir():
            continue
        txt_files = [p for p in transcript_dir.glob("*.txt") if p.is_file()]
        if not txt_files:
            continue

        date_label = ""
        try:
            parts = transcript_dir.parts
            if len(parts) >= 4:
                year, month, day = parts[-4], parts[-3], parts[-2]
                if year.isdigit() and month.isdigit() and day.isdigit():
                    date_label = f"{day}.{month}.{year}"
        except Exception:
            date_label = ""

        folders.append(
            {
                "name": str(transcript_dir.relative_to(base)),
                "path": str(transcript_dir),
                "files_count": len(txt_files),
                "date": date_label,
                "mtime": transcript_dir.stat().st_mtime,
            }
        )

    folders.sort(key=lambda item: item["mtime"], reverse=True)
    return folders[:limit]


def _latest_result_file() -> Path | None:
    uploads = _uploads_dir()
    files = sorted(uploads.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _load_results_df(path: Path):
    try:
        return pd.read_excel(path, sheet_name="Р”РµС‚Р°Р»СЊРЅС‹Рµ РґР°РЅРЅС‹Рµ")
    except Exception:
        return pd.read_excel(path)


def _build_dashboard_stats() -> Dict:
    latest = _latest_result_file()
    if not latest:
        return {
            "total_calls": 0,
            "target_calls": 0,
            "recorded_calls": 0,
            "latest_file": None,
        }

    df = _load_results_df(latest)
    total = len(df.index)
    group_col = "group" if "group" in df.columns else None
    target_calls = int((df[group_col] == "Р¦РµР»РµРІС‹Рµ").sum()) if group_col else 0
    result_col = "Р РµР·СѓР»СЊС‚Р°С‚" if "Р РµР·СѓР»СЊС‚Р°С‚" in df.columns else None
    recorded_calls = (
        int(df[result_col].astype(str).str.contains("BOOK", case=False).sum()) if result_col else 0
    )
    return {
        "total_calls": total,
        "target_calls": target_calls,
        "recorded_calls": recorded_calls,
        "latest_file": latest.name,
    }


def _result_group(result_code: str) -> str:
    code = str(result_code or "").strip().upper()
    if not code:
        return "Неизвестно"
    if code in {"1", "14"}:
        return "Нецелевые"
    if code in {"13", "26", "27"}:
        return "Справочные"
    if code.startswith("IN.NE") or code.startswith("OUT.NE"):
        return "Нецелевые"
    if ".INFO." in code or ".OBZ." in code:
        return "Справочные"
    return "Целевые"


def _call_type_from_row(row: Dict) -> str:
    row_type = str(row.get("Тип звонка", "") or "").strip()
    if row_type:
        return row_type
    code = str(row.get("Результат", "") or "").strip().upper()
    if code.startswith("IN."):
        return "Входящий"
    if code.startswith("OUT."):
        return "Исходящий"
    try:
        cat_num = int(code)
        if 1 <= cat_num <= 13:
            return "Входящий"
        if 14 <= cat_num <= 26:
            return "Исходящий"
    except Exception:
        pass
    return "Не определен"


def _category_name_from_row(row: Dict) -> str:
    category_name = str(row.get("Категория", "") or "").strip()
    if category_name:
        return category_name
    return str(row.get("Результат", "") or "").strip() or "Неизвестно"


def _categories_from_dataframe(df: pd.DataFrame) -> Dict[str, str]:
    if df is None or df.empty or "Результат" not in df.columns:
        return {}
    result: Dict[str, str] = {}
    for _, row in df.iterrows():
        code = str(row.get("Результат", "") or "").strip()
        if not code:
            continue
        if code not in result:
            result[code] = _category_name_from_row(row)
    return dict(sorted(result.items(), key=lambda item: item[0]))


def _all_categories_map() -> Dict[str, str]:
    """Возвращает полный каталог категорий для шаблонов правил/обучения."""
    try:
        engine, _ = _engine_for_user()
        categories = dict(getattr(engine, "NEW_CATEGORIES", {}) or {})
        if categories:
            return categories
    except Exception:
        pass
    # Fallback: категории из уже сформированных результатов, если есть.
    return _categories_from_dataframe(_load_all_results_df().fillna(""))


def _all_result_files() -> List[Path]:
    uploads = _uploads_dir()
    if not uploads.exists():
        return []
    files = [p for p in uploads.glob("*.xlsx") if p.is_file()]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def _load_all_results_df() -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for result_file in _all_result_files():
        try:
            df = _load_results_df(result_file)
            if df is None or df.empty:
                continue
            df = df.copy()
            df["Файл_источник"] = result_file.name
            frames.append(df)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _filter_df_by_date(df: pd.DataFrame, date_from: str, date_to: str) -> pd.DataFrame:
    if df.empty or "Дата" not in df.columns:
        return df
    result = df.copy()
    parsed_dates = pd.to_datetime(result["Дата"], format="%d.%m.%Y", errors="coerce")
    if date_from:
        try:
            start_date = datetime.strptime(date_from, "%Y-%m-%d")
            result = result[parsed_dates >= start_date]
            parsed_dates = pd.to_datetime(result["Дата"], format="%d.%m.%Y", errors="coerce")
        except Exception:
            pass
    if date_to:
        try:
            end_date = datetime.strptime(date_to, "%Y-%m-%d")
            result = result[parsed_dates <= end_date]
        except Exception:
            pass
    return result


def _sort_calls_df(df: pd.DataFrame, sort_column: str, sort_order: str) -> pd.DataFrame:
    if df.empty or not sort_column:
        return df
    ascending = str(sort_order).lower() != "desc"
    result = df.copy()
    try:
        if sort_column == "date":
            parsed = pd.to_datetime(result.get("Дата"), format="%d.%m.%Y", errors="coerce")
            result = result.assign(_date_sort=parsed).sort_values(
                by=["_date_sort", "Время"], ascending=ascending
            )
            return result.drop(columns=["_date_sort"], errors="ignore")
        mapping = {
            "phone": "Номер телефона",
            "station": "Станция",
            "category": "Результат",
            "group": "Целевой/Не целевой",
            "call_type": "Тип звонка",
        }
        target_col = mapping.get(sort_column)
        if target_col and target_col in result.columns:
            return result.sort_values(by=[target_col], ascending=ascending)
    except Exception:
        return df
    return df


def _read_transcription_text(file_name: str) -> str:
    if not file_name:
        return ""
    base = _user_base_records_path()
    if not base.exists():
        return ""
    matches = list(base.rglob(file_name))
    if not matches:
        return ""
    matches = sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)
    for path in matches:
        try:
            return path.read_text(encoding="utf-8").strip()
        except UnicodeDecodeError:
            try:
                return path.read_text(encoding="cp1251").strip()
            except Exception:
                continue
        except Exception:
            continue
    return ""


def _sync_filename_settings_to_rules(rules: ClassificationRulesManager, cfg: UserConfig | None):
    if not cfg:
        rules.set_setting("filename_pattern_custom_enabled", "0")
        rules.set_setting("filename_patterns_json", "[]")
        return

    patterns = list(getattr(cfg, "filename_patterns", None) or [])
    if bool(getattr(cfg, "use_custom_filename_patterns", False)) and patterns:
        first_regex = ""
        for pattern in patterns:
            regex = str((pattern or {}).get("regex") or "").strip()
            if regex:
                first_regex = regex
                break
        if first_regex:
            rules.set_setting(
                "filename_pattern_custom",
                first_regex,
                "Regex шаблон из пользовательских настроек LK",
            )
            rules.set_setting(
                "filename_pattern_custom_enabled",
                "1",
                "Включен пользовательский шаблон имени файла",
            )
            rules.set_setting(
                "filename_patterns_json",
                json.dumps(patterns, ensure_ascii=False),
                "Список пользовательских шаблонов имени файла из LK",
            )
            return

    rules.set_setting("filename_pattern_custom_enabled", "0")
    rules.set_setting("filename_patterns_json", "[]")


def _resolve_schedule_input_folder(user_id: int, schedule: Dict) -> Path | None:
    base = _user_base_records_path_for(user_id).resolve()
    input_folder_raw = str(schedule.get("input_folder", "") or "").strip()
    if not input_folder_raw:
        return None

    if input_folder_raw == "__DYNAMIC__":
        config_raw = schedule.get("schedule_config", "{}")
        cfg = {}
        try:
            cfg = json.loads(config_raw) if config_raw else {}
        except Exception:
            cfg = {}
        dynamic = cfg.get("dynamic_day", {}) if isinstance(cfg, dict) else {}
        mode = str(dynamic.get("mode", "today") or "today").strip().lower()
        offset_days = int(dynamic.get("offset_days", 0) or 0)
        run_date = datetime.now()
        if mode == "offset":
            run_date = run_date - timedelta(days=offset_days)
        return (base / run_date.strftime("%Y") / run_date.strftime("%m") / run_date.strftime("%d") / "transcript").resolve()

    path = Path(input_folder_raw)
    if not path.is_absolute():
        path = (base / path).resolve()
    else:
        path = path.resolve()
    return path


def _station_engine_kwargs_for_user(user_id: int) -> Tuple[
    Dict[str, str],
    Dict[str, List[str]],
    Dict[str, str],
    List[str],
]:
    """Станции пользователя: отображаемые имена, маппинг подстанций, имена для отчёта и порядок карточек."""
    stations_rows = (
        UserStation.query.filter_by(user_id=int(user_id))
        .order_by(UserStation.sort_order.asc(), UserStation.id.asc())
        .all()
    )
    mapping_rows = UserStationMapping.query.filter_by(user_id=int(user_id)).all()
    station_names = {
        str(row.code): str(row.name)
        for row in stations_rows
        if row.code and row.name
    }
    station_report_names: Dict[str, str] = {}
    for row in stations_rows:
        if not row.code:
            continue
        code = str(row.code).strip()
        rnv = (getattr(row, "report_name", None) or "").strip()
        nm = str(row.name or "").strip()
        station_report_names[code] = rnv or nm or code
    station_report_order = [str(row.code).strip() for row in stations_rows if row.code]

    station_mapping: Dict[str, List[str]] = {}
    for row in mapping_rows:
        main_code = str(row.main_station_code or "").strip()
        sub_code = str(row.sub_station_code or "").strip()
        if not main_code or not sub_code:
            continue
        station_mapping.setdefault(main_code, [])
        if sub_code not in station_mapping[main_code]:
            station_mapping[main_code].append(sub_code)

    return station_names, station_mapping, station_report_names, station_report_order


def _engine_for_user() -> Tuple[CallClassificationEngine, Path]:
    root = _classification_root()

    station_names, station_mapping, station_report_names, station_report_order = _station_engine_kwargs_for_user(
        current_user.id
    )

    cfg = UserConfig.query.filter_by(user_id=current_user.id).first()
    _sync_filename_settings_to_rules(
        ClassificationRulesManager(user_id=int(current_user.id), classification_root=root), cfg
    )
    llm_api_key, llm_base_url, llm_model = _resolve_user_llm_settings(user=current_user)

    engine = CallClassificationEngine(
        api_key=llm_api_key,
        base_url=llm_base_url,
        model=llm_model,
        user_id=int(current_user.id),
        classification_root=root,
        station_names=station_names,
        station_mapping=station_mapping,
        station_report_names=station_report_names,
        station_report_order=station_report_order,
    )
    return engine, root


_NOTIFY_SETTING_KEYS = (
    "telegram_enabled",
    "telegram_bot_token",
    "telegram_chat_id",
    "max_enabled",
    "max_access_token",
    "max_chat_id",
)


def _resolve_schedule_notify_telegram(
    rules_rm: ClassificationRulesManager, config_data: dict
) -> Tuple[bool, str, str]:
    """
    Приоритет: настройки страницы «Расписания» (user_classification_settings),
    иначе профиль ЛК (user_config).
    """
    te = (rules_rm.get_setting("telegram_enabled", "") or "").strip()
    tt = (rules_rm.get_setting("telegram_bot_token", "") or "").strip()
    tc = (rules_rm.get_setting("telegram_chat_id", "") or "").strip()
    if te == "1" and tt and tc:
        return True, tt, tc

    telegram = config_data.get("telegram") or {}
    api_keys = config_data.get("api_keys") or {}
    if not bool(telegram.get("notifications_enabled", True)):
        return False, "", ""
    pt = (api_keys.get("telegram_bot_token") or "").strip()
    pc = (telegram.get("reports_chat_id") or telegram.get("alert_chat_id") or "").strip()
    if pt and pc:
        return True, pt, pc
    return False, "", ""


def _resolve_schedule_notify_max(
    rules_rm: ClassificationRulesManager, config_data: dict
) -> Tuple[bool, str, str]:
    """Тот же приоритет, что и для Telegram."""
    me = (rules_rm.get_setting("max_enabled", "") or "").strip()
    mt = (rules_rm.get_setting("max_access_token", "") or "").strip()
    mc = (rules_rm.get_setting("max_chat_id", "") or "").strip()
    if me == "1" and mt and mc:
        return True, mt, mc

    max_c = config_data.get("max") or {}
    api_keys = config_data.get("api_keys") or {}
    if not bool(max_c.get("notifications_enabled", True)):
        return False, "", ""
    pt = (api_keys.get("max_access_token") or "").strip()
    pc = (max_c.get("reports_chat_id") or max_c.get("alert_chat_id") or "").strip()
    if pt and pc:
        return True, pt, pc
    return False, "", ""


def _try_send_schedule_excel_notifications(
    flask_app,
    output_path: Path,
    total_calls: int,
    user_id: int,
) -> None:
    """
    Отправка Excel после успешного прогона по расписанию.

    Сначала используются настройки из блока «Отправка Excel после расписания»
    (PostgreSQL user_classification_settings), при неполных данных — профиль ЛК.
    """
    path_str = str(output_path)
    if not os.path.isfile(path_str):
        return
    base_name = os.path.basename(path_str)
    caption = f"Запланированный отчет: {base_name} ({total_calls} звонков)"

    with flask_app.app_context():
        from web_interface.app import get_user_config_data

        user = User.query.get(int(user_id))
        if not user:
            return
        config_data = get_user_config_data(user=user)
        rules_rm = ClassificationRulesManager(
            user_id=int(user_id), classification_root=_classification_root_for(int(user_id))
        )

        send_tg, bot_token, chat_id = _resolve_schedule_notify_telegram(rules_rm, config_data)
        try:
            if send_tg and bot_token and chat_id:
                url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
                with open(path_str, "rb") as f:
                    files = {
                        "document": (
                            base_name,
                            f,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )
                    }
                    data = {"chat_id": chat_id, "caption": caption}
                    resp = requests.post(url, data=data, files=files, timeout=30)
                if resp.status_code != 200:
                    flask_app.logger.warning(
                        "Отчёт по расписанию: Telegram API %s: %s",
                        resp.status_code,
                        (resp.text or "")[:800],
                    )
        except Exception as te:
            flask_app.logger.warning("Отчёт по расписанию: не удалось отправить в Telegram: %s", te)

        send_mx, max_token, max_chat = _resolve_schedule_notify_max(rules_rm, config_data)
        try:
            if send_mx and max_token and max_chat:
                send_excel_report_to_max(max_token, max_chat, path_str, caption)
        except Exception as me:
            flask_app.logger.warning("Отчёт по расписанию: не удалось отправить в MAX: %s", me)


def _run_classification_task(
    flask_app,
    task_id,
    user_id,
    classification_root,
    uploads_dir,
    input_folder,
    output_filename,
    context_days,
    station_names,
    station_mapping,
    station_report_names,
    station_report_order,
    llm_api_key,
    llm_base_url,
    llm_model,
    schedule_id=None,
    schedule_key=None,
):
    rules = None
    schedule_rm = None
    app_ctx = flask_app.app_context()
    app_ctx.push()
    try:
        _cr = Path(classification_root)
        rules = ClassificationRulesManager(user_id=int(user_id), classification_root=_cr)
        if schedule_id is not None:
            schedule_rm = ClassificationRulesManager(user_id=int(user_id), classification_root=_cr)
        output_path = Path(uploads_dir) / output_filename

        with _tasks_lock:
            task = _classification_tasks.get(task_id)
            if not task:
                return
            task["status"] = "running"
            task["message"] = "РџРѕРґРіРѕС‚РѕРІРєР° Рє РѕР±СЂР°Р±РѕС‚РєРµ..."
            task["started_at"] = time.time()

        rules.update_classification_task(task_id, status="running")

        def progress_callback(processed, total, current_file):
            progress = int((processed / total) * 100) if total else 0
            with _tasks_lock:
                if task_id in _classification_tasks:
                    _classification_tasks[task_id].update(
                        {
                            "progress": progress,
                            "processed_files": int(processed),
                            "total_files": int(total),
                            "current_file": str(current_file or ""),
                            "message": f"РћР±СЂР°Р±РѕС‚РєР° {processed}/{total} С„Р°Р№Р»РѕРІ...",
                        }
                    )
            rules.update_classification_task(
                task_id,
                processed_files=int(processed),
                total_files=int(total),
            )

        engine = CallClassificationEngine(
            api_key=llm_api_key,
            base_url=llm_base_url,
            model=llm_model,
            user_id=int(user_id),
            classification_root=Path(classification_root),
            station_names=station_names or {},
            station_mapping=station_mapping or {},
            station_report_names=station_report_names or {},
            station_report_order=station_report_order or [],
        )
        _, _, total_calls = engine.process_folder(
            input_folder=input_folder,
            output_file=str(output_path),
            context_days=context_days,
            progress_callback=progress_callback,
        )

        with _tasks_lock:
            task = _classification_tasks.get(task_id, {})
            duration = int(time.time() - task.get("started_at", time.time()))
            _classification_tasks[task_id].update(
                {
                    "status": "completed",
                    "progress": 100,
                    "processed_files": int(total_calls),
                    "total_files": int(total_calls),
                    "message": f"Р“РѕС‚РѕРІРѕ. РћР±СЂР°Р±РѕС‚Р°РЅРѕ {total_calls} Р·РІРѕРЅРєРѕРІ.",
                    "duration": f"{duration // 60}Рј {duration % 60}СЃ",
                    "download_url": f"/classification/download/{output_filename}",
                }
            )

        rules.update_classification_task(
            task_id,
            status="completed",
            end_time=datetime.now().isoformat(),
            duration=_classification_tasks.get(task_id, {}).get("duration", ""),
            processed_files=int(total_calls),
            total_files=int(total_calls),
        )
        if schedule_rm is not None and schedule_id is not None:
            schedule_rm.update_schedule_run_stats(int(schedule_id), success=True)
            _try_send_schedule_excel_notifications(
                flask_app, output_path, int(total_calls), int(user_id)
            )
    except Exception as exc:
        with _tasks_lock:
            if task_id in _classification_tasks:
                _classification_tasks[task_id].update(
                    {
                        "status": "error",
                        "message": f"РћС€РёР±РєР°: {exc}",
                    }
                )
        if rules is not None:
            rules.update_classification_task(
                task_id,
                status="error",
                end_time=datetime.now().isoformat(),
                error_message=str(exc),
            )
        if schedule_rm is not None and schedule_id is not None:
            schedule_rm.update_schedule_run_stats(int(schedule_id), success=False)
        flask_app.logger.exception("Classification task failed: %s", task_id)
    finally:
        app_ctx.pop()
        if schedule_key:
            with _tasks_lock:
                _running_schedule_keys.discard(schedule_key)


def _enqueue_classification_task_for_user(
    user_id: int,
    username: str,
    input_path: Path,
    output_filename: str,
    context_days: int,
    *,
    schedule_id: int | None = None,
    app_obj=None,
) -> str:
    task_id = f"{int(user_id)}_{int(time.time() * 1000)}"
    cr_path = _classification_root_for(user_id)
    classification_root = str(cr_path)
    uploads_dir = str(_uploads_dir_for(user_id))

    rules = ClassificationRulesManager(user_id=int(user_id), classification_root=cr_path)
    rules.add_classification_task(
        task_id=task_id,
        input_folder=str(input_path),
        output_file=output_filename,
        context_days=context_days,
        operator_name=username,
    )

    with _tasks_lock:
        _classification_tasks[task_id] = {
            "task_id": task_id,
            "user_id": int(user_id),
            "status": "queued",
            "progress": 0,
            "processed_files": 0,
            "total_files": 0,
            "current_file": "",
            "message": "Р—Р°РґР°С‡Р° РїРѕСЃС‚Р°РІР»РµРЅР° РІ РѕС‡РµСЂРµРґСЊ",
            "download_url": None,
            "created_at": time.time(),
            "schedule_id": schedule_id,
        }

    station_names, station_mapping, station_report_names, station_report_order = _station_engine_kwargs_for_user(
        int(user_id)
    )

    cfg = UserConfig.query.filter_by(user_id=int(user_id)).first()
    _sync_filename_settings_to_rules(rules, cfg)
    user_obj = User.query.get(int(user_id))
    llm_api_key, llm_base_url, llm_model = _resolve_user_llm_settings(user=user_obj, user_id=int(user_id))

    if app_obj is None:
        app_obj = current_app._get_current_object()
    current_schedule_key = None
    if schedule_id is not None:
        current_schedule_key = _schedule_key(int(user_id), int(schedule_id))
        with _tasks_lock:
            _schedule_task_map[current_schedule_key] = task_id
            _running_schedule_keys.add(current_schedule_key)

    thread = threading.Thread(
        target=_run_classification_task,
        args=(
            app_obj,
            task_id,
            int(user_id),
            classification_root,
            uploads_dir,
            str(input_path),
            output_filename,
            context_days,
            station_names,
            station_mapping,
            station_report_names,
            station_report_order,
            llm_api_key,
            llm_base_url,
            llm_model,
            schedule_id,
            current_schedule_key,
        ),
        daemon=True,
    )
    thread.start()
    return task_id


def _enqueue_classification_task(input_path: Path, output_filename: str, context_days: int) -> str:
    app_obj = current_app._get_current_object()
    return _enqueue_classification_task_for_user(
        user_id=int(current_user.id),
        username=str(current_user.username),
        input_path=input_path,
        output_filename=output_filename,
        context_days=context_days,
        app_obj=app_obj,
    )


def _find_task_for_schedule(user_id: int, schedule_id: int) -> Dict | None:
    key = _schedule_key(user_id, schedule_id)
    with _tasks_lock:
        task_id = _schedule_task_map.get(key)
        if task_id and task_id in _classification_tasks:
            return dict(_classification_tasks[task_id])
        candidates = [
            t for t in _classification_tasks.values()
            if int(t.get("user_id", -1)) == int(user_id) and int(t.get("schedule_id") or -1) == int(schedule_id)
        ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: float(item.get("created_at") or 0), reverse=True)
    return dict(candidates[0])


def _process_due_schedules(flask_app):
    with flask_app.app_context():
        users = User.query.all()
        for user in users:
            user_id = int(user.id)
            cr = _classification_root_for(user_id)
            rm = ClassificationRulesManager(user_id=user_id, classification_root=cr)
            for schedule in rm.get_due_schedules():
                schedule_id = int(schedule["id"])
                schedule_key = _schedule_key(user_id, schedule_id)
                with _tasks_lock:
                    if schedule_key in _running_schedule_keys:
                        continue
                    _running_schedule_keys.add(schedule_key)
                try:
                    rm.update_next_run(schedule_id)
                    input_path = _resolve_schedule_input_folder(user_id, schedule)
                    base = _user_base_records_path_for(user_id).resolve()
                    if not input_path:
                        with _tasks_lock:
                            _running_schedule_keys.discard(schedule_key)
                        continue
                    if not str(input_path).startswith(str(base)):
                        with _tasks_lock:
                            _running_schedule_keys.discard(schedule_key)
                        continue
                    if not input_path.exists():
                        with _tasks_lock:
                            _running_schedule_keys.discard(schedule_key)
                        continue
                    filename = f"call_classification_results_schedule_{schedule_id}_{int(time.time())}.xlsx"
                    _enqueue_classification_task_for_user(
                        user_id=user_id,
                        username=str(user.username),
                        input_path=input_path,
                        output_filename=filename,
                        context_days=int(schedule.get("context_days", 7) or 7),
                        schedule_id=schedule_id,
                        app_obj=flask_app,
                    )
                except Exception:
                    with _tasks_lock:
                        _running_schedule_keys.discard(schedule_key)
                    flask_app.logger.exception(
                        "Failed to enqueue scheduled classification: user=%s schedule=%s",
                        user_id,
                        schedule_id,
                    )


def _classification_scheduler_loop(flask_app):
    while not _scheduler_stop_event.is_set():
        try:
            _process_due_schedules(flask_app)
        except Exception:
            with flask_app.app_context():
                flask_app.logger.exception("Classification scheduler loop error")
        _scheduler_stop_event.wait(timeout=_scheduler_check_interval)


def start_classification_scheduler(flask_app):
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _scheduler_stop_event.clear()
    _scheduler_thread = threading.Thread(
        target=_classification_scheduler_loop,
        args=(flask_app,),
        name="classification-scheduler",
        daemon=True,
    )
    _scheduler_thread.start()


@classification_bp.route("/")
@login_required
def dashboard():
    stats = _build_dashboard_stats()
    history = _rules_manager().get_classification_history(limit=10)
    return render_template(
        "classification/dashboard.html",
        active_page="classification_dashboard",
        stats=stats,
        history=history,
    )


@classification_bp.route("/classify")
@login_required
def classify_page():
    folders = _scan_transcript_folders()
    return render_template(
        "classification/classify.html",
        active_page="classification_classify",
        folders=folders,
    )


@classification_bp.route("/review")
@login_required
def review_page():
    category = request.args.get("category", "").strip()
    station = request.args.get("station", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    sort_column = request.args.get("sort", "").strip()
    sort_order = request.args.get("order", "asc").strip().lower()
    page = max(int(request.args.get("page", 1) or 1), 1)
    per_page = 30

    df = _load_all_results_df().fillna("")
    if station and "Станция" in df.columns:
        df = df[df["Станция"].astype(str) == station]
    if category and "Результат" in df.columns:
        df = df[df["Результат"].astype(str) == category]
    df = _filter_df_by_date(df, date_from, date_to)
    df = _sort_calls_df(df, sort_column, sort_order)

    total = len(df.index)
    pages = max((total + per_page - 1) // per_page, 1)
    if page > pages:
        page = pages
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page

    calls: List[Dict] = []
    if total:
        page_df = df.iloc[start_idx:end_idx].copy()
        for _, row in page_df.iterrows():
            item = row.to_dict()
            item["call_id"] = int(row.name)
            item["group"] = _result_group(item.get("Результат"))
            item["category_name"] = _category_name_from_row(item)
            item["Тип звонка"] = _call_type_from_row(item)
            calls.append(item)

    all_df = _load_all_results_df().fillna("")
    stations: List[str] = []
    if "Станция" in all_df.columns:
        stations = sorted({str(x) for x in all_df["Станция"].tolist() if str(x).strip()})
    categories = _categories_from_dataframe(all_df)

    pagination = {
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "total": total,
        "has_prev": page > 1,
        "has_next": page < pages,
    }
    return render_template(
        "classification/review.html",
        active_page="classification_review",
        calls=calls,
        latest_file=_latest_result_file().name if _latest_result_file() else None,
        stations=stations,
        categories=categories,
        pagination=pagination,
        filters={
            "station": station,
            "category": category,
            "date_from": date_from,
            "date_to": date_to,
            "sort": sort_column,
            "order": sort_order,
        },
    )


@classification_bp.route("/rules")
@login_required
def rules_page():
    rm = _rules_manager()
    return render_template(
        "classification/rules.html",
        active_page="classification_rules",
        system_prompts=rm.get_system_prompts(),
        classification_rules=rm.get_classification_rules(),
        critical_rules=rm.get_critical_rules(),
        categories=_all_categories_map(),
    )


@classification_bp.route("/schedules")
@login_required
def schedules_page():
    rm = _rules_manager()
    return render_template(
        "classification/schedules.html",
        active_page="classification_schedules",
        schedules=rm.get_schedules(active_only=False),
        folders=_scan_transcript_folders(),
    )


@classification_bp.route("/learning-analytics")
@login_required
def learning_analytics_page():
    report = {
        "learning_progress": {
            "period_days": 30,
            "current_accuracy": 0.0,
            "accuracy_improvement": 0.0,
            "total_confirmations": 0,
            "total_corrections": 0,
            "total_interactions": 0,
            "avg_confidence": 0,
        },
        "error_patterns": {"total": 0, "top_5": []},
        "success_statistics": {"by_category": {}, "top_performing": [], "needs_attention": []},
        "example_effectiveness": {"effective_count": 0, "ineffective_count": 0},
        "suggestions": {"total": 0, "all": []},
        "recommendations": [],
    }
    try:
        self_learning = SelfLearningSystem(user_id=int(current_user.id))
        generated = self_learning.generate_enhanced_learning_report() or {}
        if isinstance(generated, dict):
            report.update(generated)
    except Exception:
        current_app.logger.exception("Failed to build learning analytics report for user=%s", current_user.id)

    return render_template(
        "classification/learning_analytics.html",
        active_page="classification_learning",
        report=report,
        categories=_all_categories_map(),
    )


@classification_bp.route("/api/start", methods=["POST"])
@login_required
def api_start():
    data = request.get_json(silent=True) or {}
    input_folder = str(data.get("input_folder", "")).strip()
    output_file = str(data.get("output_file", "")).strip()
    context_days = int(data.get("context_days", 7))

    if not input_folder or not output_file:
        return jsonify({"success": False, "message": "РќРµ Р·Р°РїРѕР»РЅРµРЅС‹ РѕР±СЏР·Р°С‚РµР»СЊРЅС‹Рµ РїРѕР»СЏ"}), 400

    try:
        input_path = Path(input_folder).resolve()
    except Exception:
        return jsonify({"success": False, "message": "РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ РїСѓС‚СЊ Рє РїР°РїРєРµ"}), 400

    base = _user_base_records_path().resolve()
    if not str(input_path).startswith(str(base)) or not input_path.exists():
        return jsonify({"success": False, "message": "РџР°РїРєР° РІРЅРµ СЂР°Р±РѕС‡РµР№ РѕР±Р»Р°СЃС‚Рё РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ"}), 400

    filename = secure_filename(output_file)
    if not filename:
        return jsonify({"success": False, "message": "РќРµРєРѕСЂСЂРµРєС‚РЅРѕРµ РёРјСЏ С„Р°Р№Р»Р°"}), 400
    if not filename.lower().endswith(".xlsx"):
        filename = f"{filename}.xlsx"
    task_id = _enqueue_classification_task(
        input_path=input_path,
        output_filename=filename,
        context_days=context_days,
    )
    return jsonify({"success": True, "task_id": task_id})


@classification_bp.route("/api/status/<task_id>")
@login_required
def api_status(task_id):
    db_task = _rules_manager().get_classification_task(task_id)
    with _tasks_lock:
        task = _classification_tasks.get(task_id)
        if task and task.get("user_id") != current_user.id:
            return jsonify({"success": False, "message": "РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ РїСЂР°РІ"}), 403
        if task is None and db_task is None:
            return jsonify({"success": False, "message": "Р—Р°РґР°С‡Р° РЅРµ РЅР°Р№РґРµРЅР°"}), 404

        result = dict(task or {})
        if db_task:
            processed = int(db_task.get("processed_files") or 0)
            total = int(db_task.get("total_files") or 0)
            progress = int((processed / total) * 100) if total else result.get("progress", 0)
            result.update(
                {
                    "status": db_task.get("status") or result.get("status") or "running",
                    "processed_files": processed,
                    "total_files": total,
                    "progress": progress,
                }
            )
            if db_task.get("status") == "completed" and not result.get("download_url"):
                output_file = db_task.get("output_file")
                if output_file:
                    result["download_url"] = f"/classification/download/{output_file}"

        if (
            result.get("status") == "queued"
            and db_task
            and db_task.get("status")
        ):
            result["status"] = db_task.get("status")
            if result.get("message") == "Р—Р°РґР°С‡Р° РїРѕСЃС‚Р°РІР»РµРЅР° РІ РѕС‡РµСЂРµРґСЊ":
                result["message"] = "Р—Р°РїСѓС‰РµРЅР° РѕР±СЂР°Р±РѕС‚РєР°..."

        return jsonify({"success": True, **result})


@classification_bp.route("/download/<filename>")
@login_required
def download(filename):
    safe = secure_filename(filename)
    path = _uploads_dir() / safe
    if not path.exists():
        return jsonify({"success": False, "message": "Р¤Р°Р№Р» РЅРµ РЅР°Р№РґРµРЅ"}), 404
    return send_file(path, as_attachment=True, download_name=safe)


@classification_bp.route("/api/system-prompts", methods=["GET", "POST"])
@login_required
def api_system_prompts():
    rm = _rules_manager()
    if request.method == "GET":
        return jsonify({"success": True, "prompts": rm.get_system_prompts()})

    data = request.get_json(silent=True) or {}
    ok = rm.add_system_prompt(
        name=str(data.get("name", "")).strip(),
        content=str(data.get("content", "")).strip(),
        description=str(data.get("description", "")).strip(),
    )
    return jsonify({"success": ok})


@classification_bp.route("/api/system-prompts/<int:prompt_id>", methods=["PUT", "DELETE"])
@login_required
def api_system_prompt_detail(prompt_id):
    rm = _rules_manager()
    if request.method == "PUT":
        data = request.get_json(silent=True) or {}
        ok = rm.update_system_prompt(
            prompt_id=prompt_id,
            name=str(data.get("name", "")).strip(),
            content=str(data.get("content", "")).strip(),
            description=str(data.get("description", "")).strip(),
        )
        return jsonify({"success": ok})
    return jsonify({"success": rm.delete_system_prompt(prompt_id)})


@classification_bp.route("/api/system-prompts/<int:prompt_id>/toggle", methods=["POST"])
@login_required
def api_system_prompt_toggle(prompt_id):
    return jsonify({"success": _rules_manager().toggle_system_prompt_active(prompt_id)})


@classification_bp.route("/api/classification-rules", methods=["GET", "POST"])
@login_required
def api_classification_rules():
    rm = _rules_manager()
    if request.method == "GET":
        return jsonify({"success": True, "rules": rm.get_classification_rules()})

    data = request.get_json(silent=True) or {}
    ok = rm.add_classification_rule(
        category_id=str(data.get("category_id", "")).strip(),
        category_name=str(data.get("category_name", "")).strip(),
        rule_text=str(data.get("rule_text", "")).strip(),
        priority=int(data.get("priority", 0) or 0),
        examples=data.get("examples", ""),
        conditions=data.get("conditions", ""),
    )
    return jsonify({"success": ok})


@classification_bp.route("/api/classification-rules/<int:rule_id>", methods=["PUT", "DELETE"])
@login_required
def api_classification_rule_detail(rule_id):
    rm = _rules_manager()
    if request.method == "PUT":
        data = request.get_json(silent=True) or {}
        ok = rm.update_classification_rule(
            rule_id=rule_id,
            category_id=str(data.get("category_id", "")).strip(),
            category_name=str(data.get("category_name", "")).strip(),
            rule_text=str(data.get("rule_text", "")).strip(),
            priority=int(data.get("priority", 0) or 0),
            examples=data.get("examples", ""),
            conditions=data.get("conditions", ""),
        )
        return jsonify({"success": ok})
    return jsonify({"success": rm.delete_classification_rule(rule_id)})


@classification_bp.route("/api/classification-rules/<int:rule_id>/toggle", methods=["POST"])
@login_required
def api_classification_rule_toggle(rule_id):
    return jsonify({"success": _rules_manager().toggle_classification_rule_active(rule_id)})


@classification_bp.route("/api/critical-rules", methods=["GET", "POST"])
@login_required
def api_critical_rules():
    rm = _rules_manager()
    if request.method == "GET":
        return jsonify({"success": True, "rules": rm.get_critical_rules()})

    data = request.get_json(silent=True) or {}
    ok = rm.add_critical_rule(
        name=str(data.get("name", "")).strip(),
        rule_text=str(data.get("rule_text", "")).strip(),
        description=str(data.get("description", "")).strip(),
    )
    return jsonify({"success": ok})


@classification_bp.route("/api/critical-rules/<int:rule_id>", methods=["PUT", "DELETE"])
@login_required
def api_critical_rule_detail(rule_id):
    rm = _rules_manager()
    if request.method == "PUT":
        data = request.get_json(silent=True) or {}
        ok = rm.update_critical_rule(
            rule_id=rule_id,
            name=str(data.get("name", "")).strip(),
            rule_text=str(data.get("rule_text", "")).strip(),
            description=str(data.get("description", "")).strip(),
        )
        return jsonify({"success": ok})
    return jsonify({"success": rm.delete_critical_rule(rule_id)})


@classification_bp.route("/api/critical-rules/<int:rule_id>/toggle", methods=["POST"])
@login_required
def api_critical_rule_toggle(rule_id):
    return jsonify({"success": _rules_manager().toggle_critical_rule_active(rule_id)})


@classification_bp.route("/api/schedules", methods=["GET", "POST"])
@login_required
def api_schedules():
    rm = _rules_manager()
    if request.method == "GET":
        active_only = request.args.get("active_only", "false").lower() == "true"
        return jsonify({"success": True, "schedules": rm.get_schedules(active_only=active_only)})

    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    input_folder = str(data.get("input_folder", "")).strip()
    schedule_type = str(data.get("schedule_type", "daily")).strip()
    schedule_config = data.get("schedule_config", {})
    if isinstance(schedule_config, dict):
        schedule_config = json.dumps(schedule_config, ensure_ascii=False)
    if not name or not input_folder:
        return jsonify({"success": False, "message": "name Рё input_folder РѕР±СЏР·Р°С‚РµР»СЊРЅС‹"}), 400

    schedule_id = rm.add_schedule(
        name=name,
        description=str(data.get("description", "")).strip(),
        input_folder=input_folder,
        context_days=int(data.get("context_days", 7) or 7),
        schedule_type=schedule_type,
        schedule_config=str(schedule_config),
        created_by=current_user.username,
    )
    return jsonify({"success": True, "schedule_id": schedule_id})


@classification_bp.route("/api/schedules/<int:schedule_id>", methods=["PUT", "DELETE"])
@login_required
def api_schedule_detail(schedule_id):
    rm = _rules_manager()
    if request.method == "PUT":
        data = request.get_json(silent=True) or {}
        updates = {}
        for key in ("name", "description", "input_folder", "context_days", "schedule_type", "is_active"):
            if key in data:
                updates[key] = data[key]
        if "schedule_config" in data:
            cfg = data["schedule_config"]
            if isinstance(cfg, dict):
                cfg = json.dumps(cfg, ensure_ascii=False)
            updates["schedule_config"] = cfg
        rm.update_schedule(schedule_id, **updates)
        return jsonify({"success": True})

    rm.delete_schedule(schedule_id)
    return jsonify({"success": True})


@classification_bp.route("/api/schedules/<int:schedule_id>/run", methods=["POST"])
@login_required
def api_schedule_run(schedule_id):
    rm = _rules_manager()
    schedule = rm.get_schedule(schedule_id)
    if not schedule:
        return jsonify({"success": False, "message": "Р Р°СЃРїРёСЃР°РЅРёРµ РЅРµ РЅР°Р№РґРµРЅРѕ"}), 404
    schedule_key = _schedule_key(int(current_user.id), int(schedule_id))
    with _tasks_lock:
        if schedule_key in _running_schedule_keys:
            return jsonify({"success": False, "message": "Расписание уже выполняется"}), 409

    input_path = _resolve_schedule_input_folder(int(current_user.id), schedule)
    base = _user_base_records_path().resolve()
    if not input_path or not str(input_path).startswith(str(base)) or not input_path.exists():
        return jsonify({"success": False, "message": "РџР°РїРєР° СЂР°СЃРїРёСЃР°РЅРёСЏ РЅРµРґРѕСЃС‚СѓРїРЅР°"}), 400

    filename = f"call_classification_results_schedule_{schedule_id}_{int(time.time())}.xlsx"
    task_id = _enqueue_classification_task_for_user(
        user_id=int(current_user.id),
        username=str(current_user.username),
        input_path=input_path,
        output_filename=filename,
        context_days=int(schedule.get("context_days", 7) or 7),
        schedule_id=int(schedule_id),
        app_obj=current_app._get_current_object(),
    )
    rm.update_next_run(schedule_id)
    return jsonify({"success": True, "task_id": task_id})


@classification_bp.route("/api/learning/stats")
@login_required
def api_learning_stats():
    uid = int(current_user.id)
    stats = {
        "training_examples": UserTrainingExample.query.filter_by(user_id=uid).count(),
        "corrections": UserCorrectionHistory.query.filter_by(user_id=uid).count(),
        "correct_classifications": UserCorrectClassification.query.filter_by(user_id=uid).count(),
    }
    by_rows = (
        UserClassificationSuccessStat.query.filter_by(user_id=uid)
        .order_by(
            UserClassificationSuccessStat.success_rate.desc(),
            UserClassificationSuccessStat.total_classified.desc(),
        )
        .limit(20)
        .all()
    )
    by_category = [
        {
            "category": r.category,
            "total_classified": r.total_classified,
            "confirmed_correct": r.confirmed_correct,
            "corrections_count": r.corrections_count,
            "success_rate": r.success_rate,
        }
        for r in by_rows
    ]
    mrows = (
        UserClassificationMetric.query.filter_by(user_id=uid)
        .order_by(UserClassificationMetric.metric_date.desc())
        .limit(30)
        .all()
    )
    mrows = list(reversed(mrows))
    metrics = [
        {
            "date": r.metric_date.isoformat() if r.metric_date else None,
            "total_calls": r.total_calls,
            "correct_classifications": r.correct_classifications,
            "corrections_made": r.corrections_made,
            "accuracy_rate": r.accuracy_rate,
        }
        for r in mrows
    ]
    return jsonify({"success": True, "stats": stats, "by_category": by_category, "metrics": metrics})


def _select_filtered_df_from_request(payload: Dict | None = None) -> pd.DataFrame:
    data = payload or {}
    category = str(data.get("category", request.args.get("category", "")) or "").strip()
    station = str(data.get("station", request.args.get("station", "")) or "").strip()
    date_from = str(data.get("date_from", request.args.get("date_from", "")) or "").strip()
    date_to = str(data.get("date_to", request.args.get("date_to", "")) or "").strip()
    sort_column = str(data.get("sort", request.args.get("sort", "")) or "").strip()
    sort_order = str(data.get("order", request.args.get("order", "asc")) or "asc").strip().lower()

    df = _load_all_results_df().fillna("")
    if station and "Станция" in df.columns:
        df = df[df["Станция"].astype(str) == station]
    if category and "Результат" in df.columns:
        df = df[df["Результат"].astype(str) == category]
    df = _filter_df_by_date(df, date_from, date_to)
    df = _sort_calls_df(df, sort_column, sort_order)
    return df


def _find_row_by_call_id(call_id: int, payload: Dict | None = None) -> Dict | None:
    df = _select_filtered_df_from_request(payload)
    if df.empty or call_id < 0 or call_id >= len(df.index):
        return None
    row = df.iloc[call_id].to_dict()
    row["call_id"] = call_id
    row["group"] = _result_group(row.get("Результат"))
    row["category_name"] = _category_name_from_row(row)
    row["Тип звонка"] = _call_type_from_row(row)
    return row


@classification_bp.route("/call/<int:call_id>")
@login_required
def call_detail_page(call_id: int):
    call = _find_row_by_call_id(call_id)
    if not call:
        flash("Звонок не найден в текущей выборке", "warning")
        return redirect(url_for("classification.review_page"))

    phone_number = str(call.get("Номер телефона", "") or "")
    all_df = _load_all_results_df().fillna("")
    history = []
    if phone_number and "Номер телефона" in all_df.columns:
        client_calls = all_df[all_df["Номер телефона"].astype(str) == phone_number]
        for _, hist in client_calls.tail(15).iterrows():
            history.append(
                {
                    "date": str(hist.get("Дата", "") or ""),
                    "time": str(hist.get("Время", "") or ""),
                    "station": str(hist.get("Станция", "") or ""),
                    "category": str(hist.get("Результат", "") or ""),
                    "reasoning": str(hist.get("Обоснование", "") or "")[:220],
                    "file_source": str(hist.get("Файл_источник", "") or ""),
                }
            )

    transcription = _read_transcription_text(str(call.get("Файл", "") or ""))
    categories = _categories_from_dataframe(all_df)
    return render_template(
        "classification/call_detail.html",
        active_page="classification_review",
        call=call,
        categories=categories,
        client_history=history,
        transcription=transcription or "Транскрипция не найдена",
        filters={
            "category": request.args.get("category", ""),
            "station": request.args.get("station", ""),
            "date_from": request.args.get("date_from", ""),
            "date_to": request.args.get("date_to", ""),
            "page": request.args.get("page", "1"),
            "sort": request.args.get("sort", ""),
            "order": request.args.get("order", "asc"),
        },
    )


@classification_bp.route("/training")
@login_required
def training_page():
    manager = TrainingExamplesManager(user_id=int(current_user.id))
    page = max(int(request.args.get("page", 1) or 1), 1)
    per_page = 30
    category_filter = str(request.args.get("category", "") or "").strip()

    all_examples = manager.get_all_examples()
    if category_filter:
        filtered = [item for item in all_examples if str(item.get("correct_category", "")) == category_filter]
    else:
        filtered = all_examples

    total = len(filtered)
    pages = max((total + per_page - 1) // per_page, 1)
    if page > pages:
        page = pages
    examples_page = filtered[(page - 1) * per_page : page * per_page]
    categories = _categories_from_dataframe(_load_all_results_df().fillna(""))
    for item in examples_page:
        code = str(item.get("correct_category", "") or "")
        original_code = str(item.get("original_category", "") or "")
        item["category_name"] = categories.get(code, code)
        item["original_category_name"] = categories.get(original_code, original_code)

    pagination = {
        "page": page,
        "pages": pages,
        "total": total,
        "has_prev": page > 1,
        "has_next": page < pages,
    }
    return render_template(
        "classification/training.html",
        active_page="classification_training",
        examples=examples_page,
        categories=categories,
        category_filter=category_filter,
        pagination=pagination,
    )


@classification_bp.route("/training/add", methods=["GET", "POST"])
@login_required
def training_add_page():
    manager = TrainingExamplesManager(user_id=int(current_user.id))
    categories = _categories_from_dataframe(_load_all_results_df().fillna(""))

    if request.method == "POST":
        transcription = str(request.form.get("transcription", "") or "").strip()
        correct_category = str(request.form.get("correct_category", "") or "").strip()
        correct_reasoning = str(request.form.get("correct_reasoning", "") or "").strip()
        original_category = str(request.form.get("original_category", "") or "").strip()
        original_reasoning = str(request.form.get("original_reasoning", "") or "").strip()
        operator_comment = str(request.form.get("operator_comment", "") or "").strip()

        if not transcription or not correct_category or not correct_reasoning:
            flash("Заполните обязательные поля", "warning")
            return render_template(
                "classification/add_example.html",
                active_page="classification_training",
                categories=categories,
            )

        success = manager.add_training_example(
            transcription=transcription,
            correct_category=correct_category,
            correct_reasoning=correct_reasoning,
            original_category=original_category or None,
            original_reasoning=original_reasoning or None,
            operator_comment=operator_comment or None,
        )
        if success:
            flash("Обучающий пример сохранен", "success")
            return redirect(url_for("classification.training_page"))
        flash("Не удалось сохранить обучающий пример", "danger")

    return render_template(
        "classification/add_example.html",
        active_page="classification_training",
        categories=categories,
    )


@classification_bp.route("/training/toggle/<int:example_id>")
@login_required
def training_toggle_example(example_id: int):
    manager = TrainingExamplesManager(user_id=int(current_user.id))
    if manager.toggle_example_status(example_id):
        flash("Статус примера обновлен", "success")
    else:
        flash("Не удалось обновить статус примера", "danger")
    return redirect(url_for("classification.training_page"))


@classification_bp.route("/training/delete/<int:example_id>")
@login_required
def training_delete_example(example_id: int):
    manager = TrainingExamplesManager(user_id=int(current_user.id))
    if manager.delete_example(example_id):
        flash("Пример удален", "success")
    else:
        flash("Не удалось удалить пример", "danger")
    return redirect(url_for("classification.training_page"))


@classification_bp.route("/correct-classifications")
@login_required
def correct_classifications_page():
    categories = _categories_from_dataframe(_load_all_results_df().fillna(""))
    return render_template(
        "classification/correct_classifications.html",
        active_page="classification_learning",
        categories=categories,
    )


@classification_bp.route("/api/reclassify-call", methods=["POST"])
@login_required
def api_reclassify_call():
    data = request.get_json(silent=True) or {}
    call_id = int(data.get("call_id", -1))
    call = _find_row_by_call_id(call_id, payload=data)
    if not call:
        return jsonify({"success": False, "message": "Звонок не найден"}), 404

    transcription = _read_transcription_text(str(call.get("Файл", "") or ""))
    if not transcription:
        return jsonify({"success": False, "message": "Транскрипция не найдена"}), 400

    phone = str(call.get("Номер телефона", "") or "")
    history_context = ""
    all_df = _load_all_results_df().fillna("")
    if phone and "Номер телефона" in all_df.columns:
        client_df = all_df[all_df["Номер телефона"].astype(str) == phone]
        history_lines = []
        for _, item in client_df.tail(10).iterrows():
            file_name = str(item.get("Файл", "") or "")
            if file_name == str(call.get("Файл", "") or ""):
                continue
            history_lines.append(
                f"{item.get('Дата', '')} {item.get('Время', '')}: {item.get('Результат', '')} | {str(item.get('Обоснование', '') or '')[:150]}"
            )
        history_context = "\n".join(history_lines)

    manager = TrainingExamplesManager(user_id=int(current_user.id))
    examples = manager.get_training_examples(limit=10)
    training_context = "\n".join(
        [
            f"Категория: {item.get('category', '')}\nТранскрипция: {str(item.get('transcription', '') or '')[:220]}\nОбоснование: {str(item.get('reasoning', '') or '')[:220]}"
            for item in examples
        ]
    )

    engine, _ = _engine_for_user()
    result = engine.classify_call_with_reasoning(
        transcription=transcription,
        call_history_context=history_context,
        training_examples_context=training_context,
        call_type=_call_type_from_row(call),
    )
    if not result:
        return jsonify({"success": False, "message": "Не удалось выполнить повторную классификацию"}), 500

    new_category, new_reasoning = result
    return jsonify(
        {
            "success": True,
            "result": {
                "category_num": new_category,
                "category_name": new_category,
                "reasoning": new_reasoning,
                "main_group": _result_group(new_category),
                "old_result": {
                    "category_num": str(call.get("Результат", "") or ""),
                    "category_name": _category_name_from_row(call),
                    "reasoning": str(call.get("Обоснование", "") or ""),
                },
            },
        }
    )


@classification_bp.route("/api/save-reclassification", methods=["POST"])
@login_required
def api_save_reclassification():
    data = request.get_json(silent=True) or {}
    call_id = int(data.get("call_id", -1))
    new_category = str(data.get("new_category", "") or "").strip()
    new_reasoning = str(data.get("new_reasoning", "") or "").strip()
    auto_correction = str(data.get("auto_correction", "") or "").strip()

    if call_id < 0 or not new_category or not new_reasoning:
        return jsonify({"success": False, "message": "Некорректные входные данные"}), 400

    call = _find_row_by_call_id(call_id, payload=data)
    if not call:
        return jsonify({"success": False, "message": "Звонок не найден"}), 404

    source_file = str(call.get("Файл_источник", "") or "").strip()
    if not source_file:
        return jsonify({"success": False, "message": "Источник файла результата не определен"}), 400
    target_path = _uploads_dir() / source_file
    if not target_path.exists():
        return jsonify({"success": False, "message": "Файл результатов не найден"}), 404

    source_df = _load_results_df(target_path).fillna("")
    phone = str(call.get("Номер телефона", "") or "")
    call_date = str(call.get("Дата", "") or "")
    call_time = str(call.get("Время", "") or "")
    match_rows = source_df[
        (source_df.get("Номер телефона", "").astype(str) == phone)
        & (source_df.get("Дата", "").astype(str) == call_date)
        & (source_df.get("Время", "").astype(str) == call_time)
    ]
    if match_rows.empty:
        return jsonify({"success": False, "message": "Запись не найдена в исходном файле"}), 404

    file_index = match_rows.index[0]
    source_df.at[file_index, "Результат"] = new_category
    source_df.at[file_index, "Категория"] = new_category
    source_df.at[file_index, "Обоснование"] = new_reasoning
    source_df.at[file_index, "Целевой/Не целевой"] = _result_group(new_category)
    if auto_correction:
        source_df.at[file_index, "Автокоррекция"] = auto_correction

    engine, _ = _engine_for_user()
    if not engine.safe_save_excel(source_df.to_dict("records"), str(target_path)):
        return jsonify({"success": False, "message": "Не удалось сохранить файл (возможно открыт в Excel)"}), 409

    manager = TrainingExamplesManager(user_id=int(current_user.id))
    manager.add_correction(
        phone_number=phone,
        call_date=call_date,
        call_time=call_time,
        station=str(call.get("Станция", "") or ""),
        original_category=str(call.get("Результат", "") or ""),
        corrected_category=new_category,
        original_reasoning=str(call.get("Обоснование", "") or ""),
        corrected_reasoning=new_reasoning,
        operator_name=current_user.username,
    )

    transcription = _read_transcription_text(str(call.get("Файл", "") or ""))
    if transcription:
        manager.add_training_example(
            transcription=transcription,
            correct_category=new_category,
            correct_reasoning=new_reasoning,
            original_category=str(call.get("Результат", "") or ""),
            original_reasoning=str(call.get("Обоснование", "") or ""),
            operator_comment=f"Корректировка из ЛК: {current_user.username}",
        )

    return jsonify({"success": True, "message": "Результат переклассификации сохранен"})


@classification_bp.route("/api/mark-as-correct", methods=["POST"])
@login_required
def api_mark_as_correct():
    data = request.get_json(silent=True) or {}
    call_id = int(data.get("call_id", -1))
    confidence = int(data.get("confidence", 5) or 5)
    comment = str(data.get("comment", "") or "")
    call = _find_row_by_call_id(call_id, payload=data)
    if not call:
        return jsonify({"success": False, "message": "Звонок не найден"}), 404

    transcription = _read_transcription_text(str(call.get("Файл", "") or ""))
    if not transcription:
        return jsonify({"success": False, "message": "Транскрипция не найдена"}), 400

    self_learning = SelfLearningSystem(user_id=int(current_user.id))
    success = self_learning.mark_as_correct(
        phone_number=str(call.get("Номер телефона", "") or ""),
        call_date=str(call.get("Дата", "") or ""),
        call_time=str(call.get("Время", "") or ""),
        category=str(call.get("Результат", "") or ""),
        reasoning=str(call.get("Обоснование", "") or ""),
        transcription=transcription,
        confirmed_by=current_user.username,
        confidence_level=confidence,
        comment=comment,
    )
    if not success:
        return jsonify({"success": False, "message": "Не удалось сохранить подтверждение"}), 500
    return jsonify({"success": True, "message": "Классификация подтверждена"})


@classification_bp.route("/api/success-stats")
@login_required
def api_success_stats():
    try:
        self_learning = SelfLearningSystem(user_id=int(current_user.id))
        stats = self_learning.get_category_success_stats()
        progress = self_learning.analyze_learning_progress(days=30)
        return jsonify({"success": True, "stats": stats, "progress": progress})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@classification_bp.route("/api/correct-classifications")
@login_required
def api_correct_classifications():
    limit = max(int(request.args.get("limit", 50) or 50), 1)
    categories = _categories_from_dataframe(_load_all_results_df().fillna(""))
    recs = (
        UserCorrectClassification.query.filter_by(user_id=int(current_user.id))
        .order_by(UserCorrectClassification.confirmed_at.desc())
        .limit(limit)
        .all()
    )
    rows = []
    for r in recs:
        d = {
            "id": r.id,
            "phone_number": r.phone_number,
            "call_date": r.call_date,
            "call_time": r.call_time,
            "category": r.category,
            "reasoning": r.reasoning,
            "confirmed_by": r.confirmed_by,
            "confidence_level": r.confidence_level,
            "comment": r.comment,
            "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
        }
        code = str(d.get("category", "") or "")
        d["category_name"] = categories.get(code, code)
        rows.append(d)
    return jsonify({"success": True, "data": rows, "count": len(rows)})


@classification_bp.route("/api/export-learning-report")
@login_required
def api_export_learning_report():
    try:
        self_learning = SelfLearningSystem(user_id=int(current_user.id))
        report = self_learning.generate_enhanced_learning_report()
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            progress = report.get("learning_progress", {})
            pd.DataFrame(
                [
                    {"metric": "current_accuracy", "value": progress.get("current_accuracy", 0)},
                    {"metric": "accuracy_improvement", "value": progress.get("accuracy_improvement", 0)},
                    {"metric": "total_confirmations", "value": progress.get("total_confirmations", 0)},
                    {"metric": "total_corrections", "value": progress.get("total_corrections", 0)},
                ]
            ).to_excel(writer, sheet_name="progress", index=False)

            stats = report.get("success_statistics", {}).get("by_category", {})
            if stats:
                pd.DataFrame(
                    [
                        {
                            "category": cat,
                            "total": values.get("total", 0),
                            "confirmed_correct": values.get("confirmed_correct", 0),
                            "corrections": values.get("corrections", 0),
                            "success_rate": values.get("success_rate", 0),
                        }
                        for cat, values in stats.items()
                    ]
                ).to_excel(writer, sheet_name="by_category", index=False)
        output.seek(0)
        file_name = f"classification_learning_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=file_name,
        )
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@classification_bp.route("/api/generate-prompt-preview")
@login_required
def api_generate_prompt_preview():
    call_history = str(request.args.get("call_history", "") or "")
    training_examples = str(request.args.get("training_examples", "") or "")
    try:
        preview = _rules_manager().generate_system_prompt(
            call_history=call_history,
            training_examples=training_examples,
        )
        return jsonify({"success": True, "preview": preview})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@classification_bp.route("/api/scheduler/status")
@login_required
def api_scheduler_status():
    active_count = len(_rules_manager().get_schedules(active_only=True))
    return jsonify(
        {
            "success": True,
            "status": {
                "running": bool(_scheduler_thread and _scheduler_thread.is_alive()),
                "check_interval": _scheduler_check_interval,
                "active_schedules": active_count,
            },
        }
    )


@classification_bp.route("/api/schedules/<int:schedule_id>/status")
@login_required
def api_schedule_status(schedule_id: int):
    schedule = _rules_manager().get_schedule(schedule_id)
    if not schedule:
        return jsonify({"success": False, "message": "Расписание не найдено"}), 404
    task = _find_task_for_schedule(int(current_user.id), int(schedule_id))
    if not task:
        return jsonify(
            {
                "success": True,
                "status": "idle",
                "progress": 0,
                "message": "Расписание не выполняется",
                "last_run": schedule.get("last_run"),
            }
        )
    return jsonify(
        {
            "success": True,
            "status": task.get("status", "idle"),
            "progress": int(task.get("progress", 0) or 0),
            "message": task.get("message", ""),
            "processed_files": int(task.get("processed_files", 0) or 0),
            "total_files": int(task.get("total_files", 0) or 0),
            "current_file": task.get("current_file", ""),
            "download_url": task.get("download_url"),
            "duration": task.get("duration", ""),
        }
    )


@classification_bp.route("/api/notify-settings", methods=["GET", "PUT"])
@login_required
def api_notify_settings():
    """
    Настройки отправки отчётов после классификации (Telegram и MAX).
    Хранятся в PostgreSQL: user_classification_settings.
    """
    rules = _rules_manager()
    if request.method == "GET":
        data = {k: rules.get_setting(k, "") for k in _NOTIFY_SETTING_KEYS}
        # флаги как строки '0'/'1' для совместимости с API/фронтом
        return jsonify({"success": True, "settings": data})

    payload = request.get_json(silent=True) or {}
    for key in _NOTIFY_SETTING_KEYS:
        if key not in payload:
            continue
        val = payload[key]
        if val is None:
            val = ""
        sval = "1" if val is True else ("0" if val is False else str(val))
        if key in ("telegram_enabled", "max_enabled") and sval not in ("0", "1"):
            return jsonify({"success": False, "message": f"{key}: ожидается 0 или 1"}), 400
        if key == "max_chat_id" and str(sval).strip():
            try:
                int(str(sval).strip())
            except ValueError:
                return jsonify({"success": False, "message": "max_chat_id: укажите целое число"}), 400
        desc = None
        if key == "max_access_token":
            desc = "Токен бота MAX"
        rules.set_setting(key, sval, description=desc)

    return jsonify(
        {
            "success": True,
            "settings": {k: rules.get_setting(k, "") for k in _NOTIFY_SETTING_KEYS},
        }
    )
