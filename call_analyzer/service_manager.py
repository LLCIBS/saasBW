import json
import logging
import os
import signal
import subprocess
import sys
import time
import hashlib
from pathlib import Path

from sqlalchemy import create_engine, text, bindparam
from sqlalchemy.exc import SQLAlchemyError

from config.settings import get_config
import call_analyzer.config as legacy_config
from common.user_settings import build_runtime_config, default_config_template


LOGGER = logging.getLogger("multi_user_service")
PROFILE_DIR = Path("runtime_configs")
PROFILE_DIR.mkdir(parents=True, exist_ok=True)
RELOAD_PATTERN = "reload_*.flag"


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )


def get_engine():
    uri = get_config().SQLALCHEMY_DATABASE_URI
    return create_engine(uri)


def _normalize_settings(raw_data):
    if not raw_data:
        return default_config_template()
    if isinstance(raw_data, str):
        try:
            return json.loads(raw_data)
        except json.JSONDecodeError:
            LOGGER.warning("Не удалось разобрать JSON настроек пользователя, используется шаблон по умолчанию")
            return default_config_template()
    return raw_data


def load_active_profiles(engine):
    profiles = []
    try:
        with engine.connect() as conn:
            users = conn.execute(text("SELECT id, username FROM users WHERE is_active = TRUE")).fetchall()
            if not users:
                return profiles
            user_ids = [row.id for row in users]

            def fetch(sql_text):
                stmt = text(sql_text).bindparams(bindparam("ids", expanding=True))
                return conn.execute(stmt, {"ids": user_ids}).fetchall()

            configs = fetch("""
                SELECT user_id, source_type, prompts_file, base_records_path, ftp_connection_id,
                       script_prompt_file, additional_vocab_file,
                       thebai_api_key, telegram_bot_token, speechmatics_api_key,
                       alert_chat_id, tg_channel_nizh, tg_channel_other,
                       tbank_stereo_enabled, use_additional_vocab, auto_detect_operator_name,
                       allowed_stations, nizh_station_codes, legal_entity_keywords
                FROM user_config
                WHERE user_id IN :ids
            """)
            config_map = {r.user_id: r for r in configs}

            station_rows = fetch("SELECT user_id, code, name FROM user_stations WHERE user_id IN :ids")
            station_map = {}
            for r in station_rows:
                station_map.setdefault(r.user_id, {})[r.code] = r.name

            mapping_rows = fetch("""
                SELECT user_id, main_station_code, sub_station_code
                FROM user_station_mappings
                WHERE user_id IN :ids
            """)
            mapping_map = {}
            for r in mapping_rows:
                mapping_map.setdefault(r.user_id, {}).setdefault(r.main_station_code, []).append(r.sub_station_code)

            chat_rows = fetch("""
                SELECT user_id, station_code, chat_id
                FROM user_station_chat_ids
                WHERE user_id IN :ids
            """)
            chat_map = {}
            for r in chat_rows:
                chat_map.setdefault(r.user_id, {}).setdefault(r.station_code, []).append(r.chat_id)

            employee_rows = fetch("""
                SELECT user_id, extension, employee
                FROM user_employee_extensions
                WHERE user_id IN :ids
            """)
            employee_map = {}
            for r in employee_rows:
                employee_map.setdefault(r.user_id, {})[r.extension] = r.employee

    except SQLAlchemyError as exc:
        LOGGER.error("Ошибка загрузки настроек пользователей: %s", exc)
        return profiles

    for row in users:
        cfg_row = config_map.get(row.id)
        config_data = default_config_template()

        if cfg_row:
            paths = config_data.get('paths') or {}
            paths.update({
                'source_type': cfg_row.source_type,
                'prompts_file': cfg_row.prompts_file,
                'base_records_path': cfg_row.base_records_path,
                'ftp_connection_id': cfg_row.ftp_connection_id,
                'script_prompt_file': cfg_row.script_prompt_file,
                'additional_vocab_file': cfg_row.additional_vocab_file,
            })
            config_data['paths'] = paths

            config_data['api_keys'] = {
                'speechmatics_api_key': cfg_row.speechmatics_api_key or '',
                'thebai_api_key': cfg_row.thebai_api_key or '',
                'thebai_url': config_data['api_keys'].get('thebai_url', 'https://api.deepseek.com/v1/chat/completions'),
                'thebai_model': config_data['api_keys'].get('thebai_model', 'deepseek-reasoner'),
                'telegram_bot_token': cfg_row.telegram_bot_token or '',
            }

            config_data['telegram'] = {
                'alert_chat_id': cfg_row.alert_chat_id or '',
                'tg_channel_nizh': cfg_row.tg_channel_nizh or '',
                'tg_channel_other': cfg_row.tg_channel_other or '',
            }

            config_data['transcription'] = {
                'tbank_stereo_enabled': bool(cfg_row.tbank_stereo_enabled),
                'use_additional_vocab': bool(cfg_row.use_additional_vocab),
                'auto_detect_operator_name': bool(cfg_row.auto_detect_operator_name),
            }

            config_data['allowed_stations'] = cfg_row.allowed_stations or []
            config_data['nizh_station_codes'] = cfg_row.nizh_station_codes or []
            config_data['legal_entity_keywords'] = cfg_row.legal_entity_keywords or []

        config_data['stations'] = station_map.get(row.id, {})
        config_data['station_mapping'] = mapping_map.get(row.id, {})
        config_data['station_chat_ids'] = chat_map.get(row.id, {})
        config_data['employee_by_extension'] = employee_map.get(row.id, {})

        runtime, _, _ = build_runtime_config(legacy_config, config_data, user_id=row.id)
        profiles.append({
            'user_id': row.id,
            'username': row.username or f'user-{row.id}',
            'runtime': runtime
        })
    return profiles


def _runtime_hash(runtime):
    sanitized = {k: runtime.get(k) for k in runtime if k != 'config_data'}
    payload = json.dumps(sanitized, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _write_profile_file(user_id, runtime):
    runtime_copy = json.loads(json.dumps(runtime, ensure_ascii=False))
    # Глобальный ключ модели общий, не передаём его в профиль
    runtime_copy.get('api_keys', {}).pop('thebai_api_key', None)
    profile_path = PROFILE_DIR / f'user_{user_id}.json'
    
    # Убеждаемся, что директория существует и имеет правильные права
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Устанавливаем права доступа для записи (на случай если запущено от root)
    try:
        import os
        import stat
        # Устанавливаем права 755 на директорию и 644 на файл
        os.chmod(PROFILE_DIR, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    except Exception as e:
        LOGGER.warning(f"Не удалось установить права на {PROFILE_DIR}: {e}")
    
    try:
        with profile_path.open('w', encoding='utf-8') as f:
            json.dump(runtime_copy, f, ensure_ascii=False, indent=2)
        # Устанавливаем права на файл после записи
        try:
            os.chmod(profile_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
        except Exception:
            pass  # Игнорируем ошибки установки прав на файл
    except PermissionError as e:
        LOGGER.error(f"Ошибка доступа при записи профиля {profile_path}: {e}")
        # Пытаемся исправить права и повторить (только на Linux/Unix)
        try:
            import platform
            if platform.system() != 'Windows':
                # Получаем текущего пользователя процесса
                current_user = os.getenv('SUDO_USER') or os.getenv('USER') or 'callanalyzer'
                # Пытаемся изменить владельца (требует sudo, только на Unix)
                try:
                    import pwd
                    uid = pwd.getpwnam(current_user).pw_uid
                    os.chown(PROFILE_DIR, uid, -1)
                    if profile_path.exists():
                        os.chown(profile_path, uid, -1)
                except (KeyError, PermissionError, ImportError):
                    pass  # Не удалось изменить владельца или pwd недоступен
        except Exception:
            pass
        raise
    return profile_path


def request_reload(user_id: int):
    """Создаёт флаг перезапуска воркера конкретного пользователя."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    flag = PROFILE_DIR / f"reload_{user_id}.flag"
    try:
        flag.touch()
    except OSError:
        with flag.open('w', encoding='utf-8') as f:
            f.write(str(time.time()))


def _collect_reload_requests():
    """Возвращает множество user_id, для которых требуется перезапуск."""
    pending = set()
    for flag in PROFILE_DIR.glob(RELOAD_PATTERN):
        name = flag.stem  # reload_<id>
        try:
            _, user_part = name.split('_', 1)
            pending.add(int(user_part))
        except (ValueError, IndexError):
            pass
        finally:
            try:
                flag.unlink()
            except OSError:
                pass
    return pending


def start_worker(profile, profile_hash):
    runtime = profile['runtime']
    base_path = (runtime.get('paths') or {}).get('base_records_path')
    if not base_path:
        LOGGER.warning("Профиль %s (%s) не имеет пути к звонкам, процесс не запущен",
                       profile['username'], profile['user_id'])
        return None
    Path(base_path).mkdir(parents=True, exist_ok=True)

    profile_path = _write_profile_file(profile['user_id'], runtime)
    env = os.environ.copy()
    env['CALL_ANALYZER_PROFILE_PATH'] = str(profile_path)
    env['CALL_ANALYZER_USER_ID'] = str(profile['user_id'])
    env['CALL_ANALYZER_USERNAME'] = profile['username']

    proc = subprocess.Popen(
        [sys.executable, '-m', 'call_analyzer.main'],
        env=env
    )
    LOGGER.info("Запущен процесс для профиля %s (PID=%s)", profile['username'], proc.pid)
    return {
        'proc': proc,
        'hash': profile_hash,
        'profile_path': profile_path
    }


def stop_worker(info):
    proc = info.get('proc')
    if not proc:
        return
    if proc.poll() is None:
        LOGGER.info("Останавливаем процесс PID=%s", proc.pid)
        try:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:
            proc.kill()
    if info.get('profile_path') and info['profile_path'].exists():
        try:
            info['profile_path'].unlink()
        except OSError:
            pass


def main():
    setup_logging()
    engine = get_engine()
    processes = {}

    try:
        while True:
            profiles = load_active_profiles(engine)
            forced_reload = _collect_reload_requests()
            active_ids = set()
            for profile in profiles:
                runtime = profile['runtime']
                base_path = (runtime.get('paths') or {}).get('base_records_path')
                if not base_path:
                    LOGGER.warning("Профиль %s (%s) не настроен: путь к звонкам пуст",
                                   profile['username'], profile['user_id'])
                    continue
                active_ids.add(profile['user_id'])
                profile_hash = _runtime_hash(runtime)
                current = processes.get(profile['user_id'])
                if current:
                    if profile['user_id'] in forced_reload:
                        LOGGER.info("Получен запрос на перезапуск профиля %s", profile['username'])
                        stop_worker(current)
                        processes[profile['user_id']] = start_worker(profile, profile_hash)
                    elif current['hash'] != profile_hash:
                        LOGGER.info("Конфигурация профиля %s изменилась, перезапускаем процесс", profile['username'])
                        stop_worker(current)
                        processes[profile['user_id']] = start_worker(profile, profile_hash)
                    elif current['proc'].poll() is not None:
                        LOGGER.warning("Процесс профиля %s завершился, перезапуск", profile['username'])
                        processes[profile['user_id']] = start_worker(profile, profile_hash)
                else:
                    processes[profile['user_id']] = start_worker(profile, profile_hash)

            for user_id in list(processes.keys()):
                if user_id not in active_ids:
                    LOGGER.info("Профиль %s отключён, останавливаем процесс", user_id)
                    stop_worker(processes.pop(user_id))

            time.sleep(60)
    except KeyboardInterrupt:
        LOGGER.info("Остановка multi-user сервиса (Ctrl+C)")
    finally:
        for info in processes.values():
            stop_worker(info)


if __name__ == '__main__':
    main()