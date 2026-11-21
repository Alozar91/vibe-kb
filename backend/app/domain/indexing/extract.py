"""Извлечение текста (ЧНК-7) и генерация PDF-превью (ПРС-2).

MVP: pdf (pypdf), txt/csv/md (прямо), docx (zip+xml); html/svg — только через PDF-превью
(XSS-правило, концепция §9). Превью — через converter-сервис (LibreOffice), недоступен локально → заглушка.
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree


def _sniff_mime(content: bytes, filename: str) -> str:
    """Детекция mime по содержимому (ЧНК-7), не по расширению."""

    if content.startswith(b"%PDF"):
        return "application/pdf"
    if content.startswith(b"PK\x03\x04"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if content.startswith(b"\xd0\xcf\x11\xe0"):
        return "application/msword"
    if content.startswith((b"\x89PNG", b"\xff\xd8\xff")):
        return "image/png" if content.startswith(b"\x89PNG") else "image/jpeg"
    head = content[:1000].lstrip()
    if head.startswith(b"<svg") or head.startswith(b"<!DOCTYPE html") or head.startswith(b"<html"):
        return "image/svg+xml" if head.startswith(b"<svg") else "text/html"
    return "text/plain"


def _extract_pdf(content: bytes) -> str:
    """PDF → текст через pypdf (зависимость добавлена в pyproject)."""

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        # pypdf недоступен: не падаем — файл останется unsupported
        raise RuntimeError("pypdf не установлен") from None


def _extract_docx(content: bytes) -> str:
    """DOCX → текст: word/document.xml из zip; namespace-aware."""

    with zipfile.ZipFile(io.BytesIO(content)) as z:
        xml = z.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    paras = []
    for p in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        texts = [t.text or "" for t in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")]
        if texts:
            paras.append("".join(texts))
    return "\n".join(paras)


def extract_text(content: bytes, filename: str) -> tuple[str, str]:
    """Файл → (текст, детектированный mime). ЧНК-7: неподдерживаемые → RuntimeError → 'failed'."""

    mime = _sniff_mime(content, filename)
    if mime == "application/pdf":
        return _extract_pdf(content), mime
    if mime.endswith("wordprocessingml.document"):
        return _extract_docx(content), mime
    if mime == "text/plain":
        return content.decode("utf-8", errors="replace"), mime
    # изображения/архивы/прочее: текст не извлекается (ПРС-2: превью-правила)
    raise RuntimeError(f"Извлечение текста не поддерживается для {mime}")


def generate_preview(session, file_row) -> None:
    """PDF-превью (ПРС-2): pdf → сам объект; офисные → converter (HTTP); иначе — без превью.

    MVP-заглушка: converter-сервис недоступен в dev без LibreOffice — preview_key остаётся NULL,
    API вернёт 202 pending (api-spec §4). Этап 3: подключение реального converter.
    """

    from app.common.config import get_settings

    if file_row.mime == "application/pdf":
        # превью = сам файл (предпросмотр первого старницы делает фронт pdf.js)
        file_row.preview_key = file_row.storage_key
        return
    # TODO(ПРС-2, Этап 3): POST /convert на converter-сервис (soffice --convert-to pdf)
    if not get_settings().debug:
        raise RuntimeError("Converter недоступен: превью для офисных форматов не готово")
