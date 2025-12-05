#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Единая точка входа: поднимает веб-интерфейс и сервис-менеджер воркеров.
Запуск: python app.py
"""

import multiprocessing
import os
import signal
import sys
import time

from web_interface.app import app, initialize_app
from call_analyzer import service_manager


def run_web():
    initialize_app()
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = app.config.get('DEBUG', False)
    app.run(host=host, port=port, debug=debug, use_reloader=False)


def main():
    multiprocessing.freeze_support()
    try:
        multiprocessing.set_start_method('spawn')
    except RuntimeError:
        pass

    svc_process = multiprocessing.Process(
        target=service_manager.main,
        name="call_analyzer_service_manager",
        daemon=False,  # Изменено на False для корректной остановки
    )
    svc_process.start()

    def _shutdown_service_manager():
        if svc_process.is_alive():
            print("\nОстановка сервис-менеджера...")
            svc_process.terminate()
            try:
                svc_process.join(timeout=5)
                if svc_process.is_alive():
                    print("Принудительное завершение сервис-менеджера...")
                    svc_process.kill()
                    svc_process.join(timeout=2)
            except Exception as e:
                print(f"Ошибка при остановке сервис-менеджера: {e}")

    def _signal_handler(signum, frame):
        print("\nПолучен сигнал остановки...")
        _shutdown_service_manager()
        sys.exit(0)

    # Регистрируем обработчики сигналов
    if sys.platform != 'win32':
        # В Linux/Unix используем сигналы
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    # В Windows сигналы обрабатываются через KeyboardInterrupt

    try:
        run_web()
    except KeyboardInterrupt:
        print("\nПолучен KeyboardInterrupt (Ctrl+C)...")
        _shutdown_service_manager()
    finally:
        _shutdown_service_manager()


if __name__ == '__main__':
    main()
