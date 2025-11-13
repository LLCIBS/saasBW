#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
����?����' �?��?�?���Ő�� �?���?�?�<�: ��� JSON �"�����>�?�? �? �+�����? �?���?�?�<�:
"""

import sys
import os
from pathlib import Path

# �"�?�+���?�>�?��? ��?�?��?�? ���?�?���'�� �? ���?�'�?
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from flask import Flask
from config.settings import get_config
from database.models import db
from database.migrations import run_migrations
from dotenv import load_dotenv

# �-���?�?�?�?����? ����?��?��?�?�<�� �?��?�?�?����?��?
load_dotenv()

app = Flask(__name__)
app.config.from_object(get_config())

# �?�?��Ő���>�����?�?��? �?���?�?��?��?��?
db.init_app(app)

default_tenant_id = int(os.getenv('DEFAULT_TENANT_USER_ID', '1'))

with app.app_context():
    print("�?���ؐ��>? �?��?�?���Ő�� �?���?�?�<�: ��� JSON �? �+�����? �?���?�?�<�:...")
    count = run_migrations(project_root, db.session, default_tenant_id)
    print(f"\n�?� �?��?�?���Ő�? �����?��?�?��?��: {count} ��������?��� �?��?�?��?�?�?���?�?")
