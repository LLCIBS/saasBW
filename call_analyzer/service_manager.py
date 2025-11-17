import json
import logging
import os
import signal
import subprocess
import sys
import time
import hashlib
from pathlib import Path

from sqlalchemy import create_engine, text
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
    sql = text("""
        SELECT u.id, u.username, u.is_active, us.data
        FROM users u
        LEFT JOIN user_settings us ON us.user_id = u.id
        WHERE u.is_active = TRUE
    """)
    profiles = []
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql).fetchall()
    except SQLAlchemyError as exc:
        LOGGER.error("Ошибка загрузки настроек пользователей: %s", exc)
        return profiles

    for row in rows:
        config_data = _normalize_settings(row.data)
        if isinstance(config_data, dict) and 'config' in config_data:
            config_data = config_data['config'] or {}
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
    
    # Запускаем FTP синхронизации для всех активных подключений
    try:
        from call_analyzer.ftp_sync_manager import start_all_active_ftp_syncs
        start_all_active_ftp_syncs()
    except Exception as e:
        LOGGER.warning(f"Не удалось запустить FTP синхронизации: {e}")
    
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
