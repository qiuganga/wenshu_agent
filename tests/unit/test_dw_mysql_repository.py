import asyncio

import pytest

from app.repository.mysql.dw_mysql_repository import DWMySQLRepository


class FakeMappings:
    def __init__(self, rows):
        self.rows = rows

    def fetchmany(self, size):
        return self.rows[:size]


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return FakeMappings(self._rows)


class FakeSession:
    def __init__(self, rows=None, fail=False):
        self.rows = rows or []
        self.fail = fail
        self.rollback_calls = 0
        self.executed = []

    async def execute(self, stmt):
        statement = str(stmt)
        self.executed.append(statement)
        if statement.lower().startswith("select"):
            if self.fail:
                raise RuntimeError("database host 127.0.0.1 password secret")
            return FakeResult(self.rows)
        return FakeResult([])

    async def rollback(self):
        self.rollback_calls += 1

    def in_transaction(self):
        return True


@pytest.mark.asyncio
async def test_execute_fetches_max_rows_plus_one_and_truncates():
    session = FakeSession(rows=[{"id": 1}, {"id": 2}, {"id": 3}])
    result = await DWMySQLRepository(session).execute_sql("select id from t", max_rows=2, timeout_seconds=1)
    assert result.rows == [{"id": 1}, {"id": 2}]
    assert result.row_count == 2
    assert result.truncated is True
    assert session.rollback_calls >= 1
    assert any("MAX_EXECUTION_TIME" in item for item in session.executed)
    assert any("READ ONLY" in item for item in session.executed)


@pytest.mark.asyncio
async def test_execute_rolls_back_on_error():
    session = FakeSession(fail=True)
    with pytest.raises(RuntimeError):
        await DWMySQLRepository(session).execute_sql("select id from t", max_rows=2, timeout_seconds=1)
    assert session.rollback_calls >= 1


@pytest.mark.asyncio
async def test_execute_rolls_back_on_cancel():
    class CancelSession(FakeSession):
        async def execute(self, stmt):
            statement = str(stmt)
            self.executed.append(statement)
            if statement.lower().startswith("select"):
                raise asyncio.CancelledError
            return FakeResult([])

    session = CancelSession()
    with pytest.raises(asyncio.CancelledError):
        await DWMySQLRepository(session).execute_sql("select id from t", max_rows=2, timeout_seconds=1)
    assert session.rollback_calls >= 1
