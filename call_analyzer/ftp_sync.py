# call_analyzer/ftp_sync.py
"""
Модуль для синхронизации файлов с FTP/SFTP серверов
"""

import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Optional, List, Tuple, Union, Any
import ftplib
import sys
import stat

HAS_PARAMIKO = False
paramiko = None

# Пытаемся найти paramiko в разных возможных местах
possible_paths = [
    Path(__file__).parent.parent.parent / 'venv' / 'Lib' / 'site-packages',
    Path.home() / 'venv' / 'Lib' / 'site-packages',
    Path(sys.executable).parent.parent / 'Lib' / 'site-packages',
]

for site_packages_path in possible_paths:
    if site_packages_path.exists():
        paramiko_path = site_packages_path / 'paramiko'
        if paramiko_path.exists():
            if str(site_packages_path) not in sys.path:
                sys.path.insert(0, str(site_packages_path))
            try:
                import paramiko
                HAS_PARAMIKO = True
                break
            except ImportError:
                continue

if not HAS_PARAMIKO:
    try:
        import paramiko
        HAS_PARAMIKO = True
    except ImportError as e:
        import logging
        logger_temp = logging.getLogger(__name__)
        logger_temp.warning(f"paramiko не установлен. SFTP функции будут недоступны. Ошибка: {e}")

from io import BytesIO

logger = logging.getLogger(__name__)


class FtpSyncError(Exception):
    """Исключение для ошибок FTP синхронизации"""
    pass


class FtpSync:
    """Класс для синхронизации файлов с FTP/SFTP сервера"""
    
    def __init__(self, host: str, port: int, username: str, password: str, 
                 remote_path: str = '/', protocol: str = 'ftp'):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.remote_path = remote_path.rstrip('/')
        self.protocol = protocol.lower()
        
        if self.protocol not in ('ftp', 'sftp'):
            raise ValueError(f"Неподдерживаемый протокол: {protocol}. Используйте 'ftp' или 'sftp'")
    
    def _get_ftp_connection(self) -> ftplib.FTP:
        try:
            ftp = ftplib.FTP()
            ftp.connect(self.host, self.port, timeout=30)
            ftp.login(self.username, self.password)
            ftp.set_pasv(True)
            # Принудительно ставим UTF-8, если сервер поддерживает
            try:
                ftp.encoding = "utf-8"
            except:
                pass
            return ftp
        except Exception as e:
            raise FtpSyncError(f"Ошибка подключения к FTP: {e}")
    
    def _get_sftp_connection(self) -> Tuple[Any, Any]:
        if not HAS_PARAMIKO or paramiko is None:
            raise FtpSyncError("paramiko не установлен. Установите его: pip install paramiko")
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=30
            )
            sftp = ssh.open_sftp()
            return ssh, sftp
        except Exception as e:
            raise FtpSyncError(f"Ошибка подключения к SFTP: {e}")
    
    def _normalize_remote_dir(self, remote_dir: Optional[str]) -> str:
        if remote_dir is None:
            return '/'
        remote_dir = remote_dir.strip()
        if not remote_dir:
            return '/'
        remote_dir = remote_dir.replace('\\', '/')
        remote_dir = remote_dir.rstrip('/')
        return remote_dir or '/'

    def _compose_absolute_path(self, initial_pwd: str, remote_dir: str) -> str:
        if remote_dir.startswith('/'):
            result = remote_dir
        else:
            base = PurePosixPath(initial_pwd or '/')
            result = str((base / remote_dir).as_posix())
        result = result.rstrip('/')
        return result or '/'

    def _build_remote_path(self, parent: str, child: str) -> str:
        parent = parent.rstrip('/')
        child = child.lstrip('/')
        if not parent or parent == '/':
            return f"/{child}" if child else '/'
        return f"{parent}/{child}" if child else parent

    def list_files(self, path: Optional[str] = None, recursive: bool = False) -> List[dict]:
        remote_dir = path or self.remote_path
        
        if self.protocol == 'ftp':
            return self._list_files_ftp(remote_dir, recursive=recursive)
        else:
            return self._list_files_sftp(remote_dir, recursive=recursive)

    def _list_files_ftp(self, remote_dir: str, recursive: bool = False) -> List[dict]:
        files = []
        ftp = None
        remote_dir = self._normalize_remote_dir(remote_dir)
        try:
            ftp = self._get_ftp_connection()
            initial_pwd = ftp.pwd()
            absolute_base = self._compose_absolute_path(initial_pwd, remote_dir)
            
            # Используем deque для очереди (BFS) вместо стека (DFS)
            # Это может помочь не зарываться сразу глубоко и избегать тайм-аутов
            from collections import deque
            queue = deque([(absolute_base, PurePosixPath('.'))])
            visited = set()
            
            logger.info(f"FTP LIST: Начинаем обход с {absolute_base}")

            # Ограничиваем глубину или количество папок, чтобы не зависнуть
            max_dirs = 1000
            dirs_processed = 0

            while queue:
                if dirs_processed >= max_dirs:
                    logger.warning(f"FTP LIST: Достигнут лимит сканирования папок ({max_dirs}). Останавливаем сканирование.")
                    break
                    
                current_dir, relative_prefix = queue.popleft() # BFS
                normalized_dir = current_dir.rstrip('/') or '/'
                
                if normalized_dir in visited:
                    continue
                visited.add(normalized_dir)
                dirs_processed += 1
                
                # Если путь содержит год, проверяем, не слишком ли он старый
                # Это эвристика для Asterisk /var/spool/asterisk/monitor/YYYY/MM/DD
                try:
                    parts = normalized_dir.split('/')
                    for part in parts:
                        if part.isdigit() and len(part) == 4:
                            year = int(part)
                            current_year = datetime.now().year
                            if year < current_year - 1: # Сканируем только текущий и прошлый год
                                # logger.debug(f"Пропускаем старую папку: {normalized_dir}")
                                continue
                except:
                    pass
                
                try:
                    ftp.cwd(normalized_dir)
                except Exception as e:
                    logger.error(f"Ошибка доступа к каталогу {normalized_dir}: {e}")
                    continue
                
                entries = []
                try:
                    ftp.retrlines('LIST', entries.append)
                except Exception as e:
                    logger.error(f"Ошибка получения списка файлов через FTP в {normalized_dir}: {e}")
                    # Если тайм-аут, возможно стоит переподключиться
                    if "time" in str(e).lower() or "out" in str(e).lower():
                        logger.info("Попытка переподключения к FTP...")
                        try:
                            ftp.quit()
                        except:
                            pass
                        try:
                            ftp = self._get_ftp_connection()
                            ftp.cwd(normalized_dir)
                        except Exception as reconnect_e:
                             logger.error(f"Не удалось переподключиться: {reconnect_e}")
                             break
                    continue
                
                if not entries:
                    # logger.debug(f"FTP: Пустой каталог {normalized_dir}")
                    pass

                for line in entries:
                    info = self._parse_ftp_list_line(line)
                    if not info:
                        if line.strip() and not line.startswith('total'):
                            # logger.warning(f"Не удалось распарсить строку FTP: '{line}'")
                            pass
                        continue
                        
                    name = info['name']
                    if name in ('.', '..'):
                        continue
                        
                    relative_path = str((relative_prefix / name).as_posix())
                    info['relative_path'] = relative_path or name
                    info['remote_path'] = self._build_remote_path(normalized_dir, name)
                    
                    if info.get('type') == 'file':
                        files.append(info)
                    elif recursive and info.get('type') == 'directory':
                        if info['remote_path'] not in visited:
                            queue.append((info['remote_path'], PurePosixPath(info['relative_path'])))
                            
        except Exception as e:
            logger.error(f"Ошибка получения списка файлов через FTP: {e}")
            raise FtpSyncError(f"Ошибка получения списка файлов: {e}")
        finally:
            if ftp:
                try:
                    ftp.quit()
                except:
                    ftp.close()
        return [f for f in files if f and f.get('type') == 'file']

    def _parse_ftp_list_line(self, line: str) -> Optional[dict]:
        """Парсит строку из FTP LIST команды"""
        try:
            # Попытка парсинга Unix формата
            # drwxr-xr-x 2 user group 4096 Nov 19 18:54 filename
            parts = line.split()
            if len(parts) < 9:
                # Может быть Windows формат?
                if len(parts) >= 4 and (parts[2] == '<DIR>' or parts[2].isdigit()):
                    return self._parse_windows_ftp_line(line, parts)
                return None

            # Стандартный Unix формат
            perms = parts[0]
            file_type = 'directory' if perms.startswith('d') else 'file'
            
            if perms.startswith('l'):
                pass 

            try:
                size = int(parts[4])
            except ValueError:
                size = 0

            filename = ' '.join(parts[8:])
            
            # Парсинг даты
            try:
                month_map = {
                    'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                    'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12,
                    'Янв': 1, 'Фев': 2, 'Мар': 3, 'Апр': 4, 'Май': 5, 'Июн': 6,
                    'Июл': 7, 'Авг': 8, 'Сен': 9, 'Окт': 10, 'Ноя': 11, 'Дек': 12
                }
                month_str = parts[5]
                month_str = month_str[0].upper() + month_str[1:].lower() if len(month_str) > 1 else month_str
                
                month = month_map.get(month_str, datetime.now().month)
                day = int(parts[6])
                
                time_year_part = parts[7]
                now = datetime.now()
                year = now.year
                hour = 0
                minute = 0
                
                if ':' in time_year_part:
                    hour, minute = map(int, time_year_part.split(':'))
                    if month > now.month:
                        year -= 1
                else:
                    year = int(time_year_part)
                    
                mtime = datetime(year, month, day, hour, minute)
            except Exception:
                mtime = datetime.now()

            return {
                'name': filename,
                'size': size,
                'mtime': mtime,
                'type': file_type
            }
        except Exception as e:
            return None

    def _parse_windows_ftp_line(self, line: str, parts: List[str]) -> Optional[dict]:
        """Парсинг Windows/DOS формата FTP"""
        try:
            date_str = parts[0]
            time_str = parts[1]
            is_dir = parts[2] == '<DIR>'
            
            if is_dir:
                size = 0
                filename = ' '.join(parts[3:])
            else:
                size = int(parts[2])
                filename = ' '.join(parts[3:])
            
            try:
                dt_str = f"{date_str} {time_str}"
                mtime = datetime.strptime(dt_str, "%m-%d-%y %I:%M%p")
            except:
                mtime = datetime.now()
                
            return {
                'name': filename,
                'size': size,
                'mtime': mtime,
                'type': 'directory' if is_dir else 'file'
            }
        except:
            return None

    def _list_files_sftp(self, remote_dir: str, recursive: bool = False) -> List[dict]:
        files = []
        ssh = None
        sftp = None
        remote_dir = self._normalize_remote_dir(remote_dir)
        try:
            ssh, sftp = self._get_sftp_connection()
            stack = [(remote_dir, PurePosixPath('.'))]
            visited = set()
            while stack:
                current_dir, relative_prefix = stack.pop()
                normalized_dir = current_dir.rstrip('/') or '/'
                if normalized_dir in visited:
                    continue
                visited.add(normalized_dir)
                try:
                    entries = sftp.listdir_attr(normalized_dir)
                except Exception as e:
                    logger.error(f"Ошибка получения списка файлов через SFTP в {normalized_dir}: {e}")
                    continue
                for item in entries:
                    name = item.filename
                    if name in ('.', '..'):
                        continue
                    relative_path = str((relative_prefix / name).as_posix())
                    full_remote_path = str((PurePosixPath(normalized_dir) / name).as_posix())
                    if stat.S_ISDIR(item.st_mode):
                        if recursive:
                            stack.append((full_remote_path, PurePosixPath(relative_path)))
                        continue
                    files.append({
                        'name': name,
                        'size': item.st_size,
                        'mtime': datetime.fromtimestamp(item.st_mtime),
                        'type': 'file',
                        'relative_path': relative_path or name,
                        'remote_path': full_remote_path
                    })
        except Exception as e:
            logger.error(f"Ошибка получения списка файлов через SFTP: {e}")
            raise FtpSyncError(f"Ошибка получения списка файлов: {e}")
        finally:
            if sftp:
                sftp.close()
            if ssh:
                ssh.close()
        return files

    def download_file(self, remote_filename: str, local_path: Path) -> bool:
        remote_file_path = f"{self.remote_path}/{remote_filename}".replace('//', '/')
        if remote_filename.startswith('/'):
            remote_file_path = remote_filename
            
        if self.protocol == 'ftp':
            return self._download_file_ftp(remote_file_path, local_path)
        else:
            return self._download_file_sftp(remote_file_path, local_path)

    def _download_file_ftp(self, remote_path: str, local_path: Path) -> bool:
        ftp = None
        try:
            ftp = self._get_ftp_connection()
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, 'wb') as f:
                ftp.retrbinary(f'RETR {remote_path}', f.write)
            logger.info(f"Файл скачан: {remote_path} -> {local_path}")
            return True
        except Exception as e:
            logger.error(f"Ошибка скачивания файла через FTP: {e}")
            if local_path.exists():
                try:
                    local_path.unlink()
                except:
                    pass
            return False
        finally:
            if ftp:
                try:
                    ftp.quit()
                except:
                    ftp.close()
    
    def _download_file_sftp(self, remote_path: str, local_path: Path) -> bool:
        ssh = None
        sftp = None
        try:
            ssh, sftp = self._get_sftp_connection()
            local_path.parent.mkdir(parents=True, exist_ok=True)
            sftp.get(remote_path, str(local_path))
            logger.info(f"Файл скачан: {remote_path} -> {local_path}")
            return True
        except Exception as e:
            logger.error(f"Ошибка скачивания файла через SFTP: {e}")
            if local_path.exists():
                try:
                    local_path.unlink()
                except:
                    pass
            return False
        finally:
            if sftp:
                sftp.close()
            if ssh:
                ssh.close()
    
    def test_connection(self) -> Tuple[bool, str]:
        try:
            if self.protocol == 'ftp':
                ftp = self._get_ftp_connection()
                ftp.quit()
                return True, "FTP подключение успешно"
            else:
                if not HAS_PARAMIKO or paramiko is None:
                    return False, "paramiko не установлен. Установите его: pip install paramiko"
                ssh, sftp = self._get_sftp_connection()
                sftp.close()
                ssh.close()
                return True, "SFTP подключение успешно"
        except Exception as e:
            return False, f"Ошибка подключения: {str(e)}"
