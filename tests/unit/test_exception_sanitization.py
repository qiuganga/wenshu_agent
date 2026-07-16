from app.core.exceptions import AppException, SQLExecutionError, sanitize_exception


def test_known_app_exception_passes_through():
    exc = SQLExecutionError("safe message")
    assert sanitize_exception(exc) is exc


def test_unknown_exception_is_sanitized():
    exc = sanitize_exception(RuntimeError("mysql://root:password@127.0.0.1/db"))
    assert isinstance(exc, AppException)
    assert exc.code == "INTERNAL_ERROR"
    assert "password" not in exc.message.lower()
    assert exc.details is None
