"""
Пакет модуля классификации звонков.

Каталог содержит:
- classification_engine.py — основной движок классификации и выгрузки отчётов
- classification_rules.py — менеджер правил и системных промптов
- training_examples.py — менеджер обучающих примеров и метрик
- self_learning_system.py — подсистема самообучения и автогенерации правил
- web_app.py и вспомогательные скрипты — отдельный веб-интерфейс (опционален при интеграции в BW)

При интеграции в проект BW модуль импортируется как обычный пакет:
    from classification_engine import CallClassificationEngine
или
    from classification_rules import ClassificationRulesManager
в зависимости от точки подключения.
"""

