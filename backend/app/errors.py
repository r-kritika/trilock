"""One error shape for the whole API: {"error": {"code": ..., "message": ...}}."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("trilock")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        self.status, self.code, self.message, self.details = status, code, message, details


def _body(code: str, message: str, extra=None) -> dict:
    err = {"code": code, "message": message}
    if extra is not None:
        err["fields"] = extra
    return {"error": err}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, e: ApiError):
        body = _body(e.code, e.message)
        if e.details is not None:
            body["error"]["details"] = e.details
        return JSONResponse(body, status_code=e.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        return JSONResponse(_body("http_error", str(e.detail)), status_code=e.status_code)

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, e: RequestValidationError):
        fields = [{"field": ".".join(str(p) for p in err["loc"][1:]), "message": err["msg"]} for err in e.errors()]
        return JSONResponse(_body("validation_error", "The request is not valid.", fields), status_code=422)

    @app.exception_handler(SQLAlchemyError)
    async def _db(_: Request, e: SQLAlchemyError):
        log.exception("database error")
        return JSONResponse(_body("database_error", "A database error occurred."), status_code=500)

    @app.exception_handler(Exception)
    async def _any(_: Request, e: Exception):
        log.exception("unhandled error")
        return JSONResponse(_body("internal_error", "Unexpected server error."), status_code=500)
