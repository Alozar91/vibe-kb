"""Доменные исключения и их маппинг в problem+json (api-spec §1, code-standards §2.2)."""

from typing import Any


class DomainError(Exception):
    """Базовое доменное исключение: service.py бросает, common/errors.py маппит."""

    status_code = 400
    error_type = "domain-error"
    title = "Ошибка домена"

    def __init__(self, detail: str = "", extra: dict[str, Any] | None = None) -> None:
        self.detail = detail or self.title
        self.extra = extra or {}
        super().__init__(self.detail)


class PermissionDenied(DomainError):
    """Нет прав на операцию (ПРВ)."""

    status_code = 403
    error_type = "permission-denied"
    title = "Доступ запрещён"


class NotFound(DomainError):
    """Объект не существует или не виден (ПРВ-2)."""

    status_code = 404
    error_type = "not-found"
    title = "Не найдено"


class NameConflict(DomainError):
    """Дубликат имени группы/материала в рамках родителя (ГРП-2, МАТ-4)."""

    status_code = 409
    error_type = "name-conflict"
    title = "Имя уже занято"


class StatusTransitionError(DomainError):
    """Недопустимый переход статуса (СТАТ-2)."""

    status_code = 409
    error_type = "status-transition"
    title = "Недопустимый переход статуса"


class NothingChanged(DomainError):
    """Правка без изменений — версия не создаётся (ВЕРС-2)."""

    status_code = 422
    error_type = "nothing-changed"
    title = "Ничего не изменилось"


class FileNotScanned(DomainError):
    """Файл ещё не прошёл антивирус-скан (НФТ-4)."""

    status_code = 423
    error_type = "file-not-scanned"
    title = "Проверка на вирусы не завершена"


class UploadTooLarge(DomainError):
    """Файл больше лимита (НФТ-5)."""

    status_code = 413
    error_type = "upload-too-large"
    title = "Файл слишком большой"


class CycleError(DomainError):
    """Цикл в дереве групп (ГРП-1)."""

    status_code = 409
    error_type = "cycle"
    title = "Недопустимое перемещение: цикл в дереве"
