import asyncio

import pytest

from app.repository.mysql.dw_mysql_repository import DWMySQLRepository


class FakeMappings:
    def __init__(self, rows):
        self.rows = rows

    def fetchmany(self, size):
        return self.rows[:size]


class FakeResult:
    def __init__(self, rows=None, scalar_value=None):
        self._scalar_value = scalar_value
        self._rows = rows

    def mappings(self):
        return FakeMappings(self._rows)

    def scalar(self):
        return self._scalar_value


class FakeSession:
    def __init__(self, rows=None, fail=False):
        self.rows = rows or []
        self.fail = fail
        self.rollback_calls = 0
        self.invalidate_calls = 0
        self.executed = []

    async def execute(self, stmt):
        statement = str(stmt)
        self.executed.append(statement)
        if statement.lower().startswith("explain"):
            if self.fail:
                raise RuntimeError("database host 127.0.0.1 password secret")
            return FakeResult(scalar_value='{"query_block":{}}')
        if statement.lower().startswith("select"):
            if self.fail:
                raise RuntimeError("database host 127.0.0.1 password secret")
            return FakeResult(self.rows)
        return FakeResult([])

    async def rollback(self):
        self.rollback_calls += 1

    async def invalidate(self):
        self.invalidate_calls += 1

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
    assert session.invalidate_calls == 1


@pytest.mark.asyncio
async def test_explain_json_sets_timeout_and_rolls_back():
    session = FakeSession()
    value = await DWMySQLRepository(session).explain_json("select id from t", timeout_seconds=2)

    assert value == '{"query_block":{}}'
    assert any("MAX_EXECUTION_TIME=2000" in item for item in session.executed)
    assert any("explain format=json select id from t" in item.lower() for item in session.executed)
    assert session.rollback_calls >= 1


@pytest.mark.asyncio
async def test_explain_timeout_invalidates_session():
    class TimeoutSession(FakeSession):
        async def execute(self, stmt):
            statement = str(stmt)
            self.executed.append(statement)
            if statement.lower().startswith("explain"):
                raise TimeoutError
            return FakeResult([])

    session = TimeoutSession()
    with pytest.raises(TimeoutError):
        await DWMySQLRepository(session).explain_json("select id from t", timeout_seconds=1)

    assert session.invalidate_calls == 1


@pytest.mark.asyncio
async def test_execute_timeout_invalidates_session_and_does_not_repeat_sql():
    class TimeoutSession(FakeSession):
        async def execute(self, stmt):
            statement = str(stmt)
            self.executed.append(statement)
            if statement.lower().startswith("select"):
                raise TimeoutError
            return FakeResult([])

    session = TimeoutSession()
    with pytest.raises(TimeoutError):
        await DWMySQLRepository(session).execute_sql("select id from t", max_rows=2, timeout_seconds=1)

    assert session.invalidate_calls == 1
    assert sum(1 for statement in session.executed if statement.lower().startswith("select")) == 1
