from sqlalchemy.exc import DBAPIError

from app.repositories.appointments import is_deadlock


class FakeDriverError(Exception):
    def __init__(self, sqlstate: str | None) -> None:
        super().__init__("driver error")
        self.sqlstate = sqlstate


def wrap(orig: BaseException) -> DBAPIError:
    return DBAPIError("UPDATE appointments SET start_at = :s", {}, orig)


def test_deadlock_code_on_the_driver_error() -> None:
    assert is_deadlock(wrap(FakeDriverError("40P01")))


def test_deadlock_code_on_the_wrapped_cause() -> None:
    adapter = Exception("adapter")
    adapter.__cause__ = FakeDriverError("40P01")
    assert is_deadlock(wrap(adapter))


def test_another_sqlstate_is_not_a_deadlock() -> None:
    assert not is_deadlock(wrap(FakeDriverError("23505")))


def test_an_error_without_a_sqlstate_is_not_a_deadlock() -> None:
    assert not is_deadlock(wrap(Exception("no code")))
