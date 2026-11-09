import uuid
from pathlib import Path
from fastapi import HTTPException, UploadFile


async def save_upload(file: UploadFile, folder: Path, max_bytes: int):
    name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    suffix = Path(name).suffix.lower()
    if suffix not in {".docx", ".xlsx", ".pdf"}:
        await file.close()
        raise HTTPException(400, "Разрешены только DOCX, XLSX и PDF.")
    if len(name) > 255:
        await file.close()
        raise HTTPException(400, "Имя файла слишком длинное.")
    stored = uuid.uuid4().hex + suffix
    target = folder / stored
    size = 0
    try:
        with target.open("xb") as output:
            while chunk := await file.read(64 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, "Превышен допустимый размер файла.")
                output.write(chunk)
        if not size:
            raise HTTPException(400, "Пустой файл не принят.")
        return name, stored, size
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
