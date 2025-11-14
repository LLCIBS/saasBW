# call_analyzer/ftp_sync.py
"""
Модуль для синхронизации файлов с FTP/SFTP серверов
"""

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple, Union, Any
import ftplib
# Попытка импорта paramiko с явным указанием пути к site-packages
import sys
import os

HAS_PARAMIKO = False
paramiko = None

# Пытаемся найти paramiko в разных возможных местах
possible_paths = [
    # Текущий venv проекта
    Path(__file__).parent.parent.parent / 'venv' / 'Lib' / 'site-packages',
    # Глобальный venv пользователя (если venv проекта - это ссылка)
    Path.home() / 'venv' / 'Lib' / 'site-packages',
    # Системный site-packages
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

# Если не нашли через пути, пробуем обычный импорт
if not HAS_PARAMIKO:
    try:
        import paramiko
        HAS_PARAMIKO = True
    except ImportError as e:
        import logging
        logger_temp = logging.getLogger(__name__)
        logger_temp.warning(f"paramiko не установлен. SFTP функции будут недоступны. Ошибка: {e}")
        logger_temp.warning(f"Python executable: {sys.executable}")
        logger_temp.warning(f"Python path: {sys.path}")
        logger_temp.warning(f"Проверенные пути: {[str(p) for p in possible_paths]}")
from io import BytesIO

logger = logging.getLogger(__name__)


class FtpSyncError(Exception):
    """Исключение для ошибок FTP синхронизации"""
    pass


class FtpSync:
    """Класс для синхронизации файлов с FTP/SFTP сервера"""
    
    def __init__(self, host: str, port: int, username: str, password: str, 
                 remote_path: str = '/', protocol: str = 'ftp'):
        """
        Инициализация FTP подключения
        
        Args:
            host: Адрес FTP сервера
            port: Порт (21 для FTP, 22 для SFTP)
            username: Имя пользователя
            password: Пароль
            remote_path: Удаленная папка для синхронизации
            protocol: Протокол ('ftp' или 'sftp')
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.remote_path = remote_path.rstrip('/')
        self.protocol = protocol.lower()
        
        if self.protocol not in ('ftp', 'sftp'):
            raise ValueError(f"Неподдерживаемый протокол: {protocol}. Используйте 'ftp' или 'sftp'")
    
    def _get_ftp_connection(self) -> ftplib.FTP:
        """Создает и возвращает FTP подключение"""
        try:
            ftp = ftplib.FTP()
            ftp.connect(self.host, self.port, timeout=30)
            ftp.login(self.username, self.password)
            ftp.set_pasv(True)  # Пассивный режим для работы за NAT
            return ftp
        except Exception as e:
            raise FtpSyncError(f"Ошибка подключения к FTP: {e}")
    
    def _get_sftp_connection(self) -> Tuple[Any, Any]:
        """Создает и возвращает SFTP подключение"""
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
    
    def list_files(self, path: Optional[str] = None) -> List[dict]:
        """
        Получает список файлов на удаленном сервере
        
        Args:
            path: Путь на удаленном сервере (если None, используется self.remote_path)
            
        Returns:
            Список словарей с информацией о файлах: [{'name': str, 'size': int, 'mtime': datetime}, ...]
        """
        remote_dir = path or self.remote_path
        
        if self.protocol == 'ftp':
            return self._list_files_ftp(remote_dir)
        else:
            return self._list_files_sftp(remote_dir)
    
    def _list_files_ftp(self, remote_dir: str) -> List[dict]:
        """Получает список файлов через FTP"""
        files = []
        ftp = None
        try:
            ftp = self._get_ftp_connection()
            ftp.cwd(remote_dir)
            
            # Получаем список файлов с детальной информацией
            ftp.retrlines('LIST', lambda line: files.append(self._parse_ftp_list_line(line)))
            
            # Фильтруем только файлы (не директории)
            files = [f for f in files if f and f.get('type') == 'file']
            
        except Exception as e:
            logger.error(f"Ошибка получения списка файлов через FTP: {e}")
            raise FtpSyncError(f"Ошибка получения списка файлов: {e}")
        finally:
            if ftp:
                try:
                    ftp.quit()
                except:
                    ftp.close()
        
        return files
    
    def _parse_ftp_list_line(self, line: str) -> Optional[dict]:
        """Парсит строку из FTP LIST команды"""
        try:
            parts = line.split()
            if len(parts) < 9:
                return None
            
            # Формат: -rw-r--r-- 1 user group size month day time filename
            file_type = parts[0][0]  # '-' для файла, 'd' для директории
            size = int(parts[4])
            filename = ' '.join(parts[8:])
            
            # Пытаемся получить время модификации
            try:
                # Простой парсинг даты (может не работать для всех форматов)
                month_map = {
                    'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                    'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
                }
                month = month_map.get(parts[5], datetime.now().month)
                day = int(parts[6])
                year = datetime.now().year
                mtime = datetime(year, month, day)
            except:
                mtime = datetime.now()
            
            return {
                'name': filename,
                'size': size,
                'mtime': mtime,
                'type': 'file' if file_type == '-' else 'directory'
            }
        except Exception as e:
            logger.debug(f"Ошибка парсинга строки FTP LIST: {line}, {e}")
            return None
    
    def _list_files_sftp(self, remote_dir: str) -> List[dict]:
        """Получает список файлов через SFTP"""
        files = []
        ssh = None
        sftp = None
        try:
            ssh, sftp = self._get_sftp_connection()
            
            try:
                sftp.chdir(remote_dir)
            except:
                # Если директория не существует, возвращаем пустой список
                return []
            
            for item in sftp.listdir_attr(remote_dir):
                if not item.st_mode or not (item.st_mode & 0o100000):  # Проверка что это файл
                    continue
                
                files.append({
                    'name': item.filename,
                    'size': item.st_size,
                    'mtime': datetime.fromtimestamp(item.st_mtime),
                    'type': 'file'
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
        """
        Скачивает файл с удаленного сервера
        
        Args:
            remote_filename: Имя файла на удаленном сервере
            local_path: Локальный путь для сохранения файла
            
        Returns:
            True если файл успешно скачан
        """
        remote_file_path = f"{self.remote_path}/{remote_filename}".replace('//', '/')
        
        if self.protocol == 'ftp':
            return self._download_file_ftp(remote_file_path, local_path)
        else:
            return self._download_file_sftp(remote_file_path, local_path)
    
    def _download_file_ftp(self, remote_path: str, local_path: Path) -> bool:
        """Скачивает файл через FTP"""
        ftp = None
        try:
            ftp = self._get_ftp_connection()
            
            # Создаем директорию если не существует
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Скачиваем файл
            with open(local_path, 'wb') as f:
                ftp.retrbinary(f'RETR {remote_path}', f.write)
            
            logger.info(f"Файл скачан: {remote_path} -> {local_path}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка скачивания файла через FTP: {e}")
            # Удаляем частично скачанный файл
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
        """Скачивает файл через SFTP"""
        ssh = None
        sftp = None
        try:
            ssh, sftp = self._get_sftp_connection()
            
            # Создаем директорию если не существует
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Скачиваем файл
            sftp.get(remote_path, str(local_path))
            
            logger.info(f"Файл скачан: {remote_path} -> {local_path}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка скачивания файла через SFTP: {e}")
            # Удаляем частично скачанный файл
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
        """
        Тестирует подключение к FTP/SFTP серверу
        
        Returns:
            (success: bool, message: str)
        """
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

