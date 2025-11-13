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
        daemon=True,
    )
    svc_process.start()

    def _shutdown_service_manager():
        if svc_process.is_alive():
            svc_process.terminate()
            try:
                svc_process.join(10)
            except Exception:
                pass

    def _signal_handler(signum, frame):
        _shutdown_service_manager()
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        run_web()
    finally:
        _shutdown_service_manager()


if __name__ == '__main__':
    main()
