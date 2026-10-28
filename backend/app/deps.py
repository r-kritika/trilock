from fastapi import Request, UploadFile
from sqlalchemy.orm import Session

from .errors import ApiError


def get_db(request: Request):
    db: Session = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


async def read_upload(f: UploadFile | None, limit: int) -> bytes | None:
    """Read an upload with a hard size cap. Empty / missing -> None."""
    if f is None or not f.filename:
        return None
    data = await f.read(limit + 1)
    if len(data) > limit:
        raise ApiError(413, "file_too_large", f"'{f.filename}' exceeds the {limit // (1024 * 1024)} MB upload limit.")
    return data
