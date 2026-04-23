"""
Слой доступа к данным классификации в PostgreSQL (SQLAlchemy).

Публичный контракт — классы-менеджеры и self-learning; этот модуль
централизует импорты для внешнего кода, которому удобнее зависеть от
«слоёвого» входа, а не от внутренних путей файлов.
"""

from __future__ import annotations

from classification_module.classification_rules import ClassificationRulesManager
from classification_module.self_learning_system import (
    IntegratedLearningSystem,
    SelfLearningSystem,
)
from classification_module.training_examples import TrainingExamplesManager

__all__ = [
    "ClassificationRulesManager",
    "TrainingExamplesManager",
    "SelfLearningSystem",
    "IntegratedLearningSystem",
]
