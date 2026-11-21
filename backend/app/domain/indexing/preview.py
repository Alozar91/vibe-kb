"""Генерация превью (ПРС-2): pdf — сам файл; офисные — converter-сервис (Этап 3); остальное — skip.

Модуль вызывается шагом preview пайплайна (ЧНК-1); отсутствие превью — не сбой:
job завершается done, preview_key остаётся NULL (preview_ready=false в карточке версии).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.materials import File


def generate_preview(session: Session, file_row: File) -> str:
    """Поставить превью для файла; возвращает 'done' (превью готово) или 'skipped'.

    - PDF (по mime или расширению): превью = сам файл (S3-ключ переиспользуется).
    - Офисные (docx/xlsx/pptx/odt...): нужен converter-сервис — TODO(ПРС-2, Этап 3).
    - Остальное (txt/md/изображения без рендера): превью не предусмотрено.
    """

    filename = (file_row.original_filename or "").lower()
    is_pdf = file_row.mime == "application/pdf" or filename.endswith(".pdf")
    if is_pdf:
        file_row.preview_key = file_row.storage_key
        return "done"

    office_suffixes = (".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt", ".odt", ".ods", ".odp")
    if filename.endswith(office_suffixes):
        # converter-сервис появится в Этапе 3; сейчас превью недоступно — не сбой
        return "skipped"

    return "skipped"
