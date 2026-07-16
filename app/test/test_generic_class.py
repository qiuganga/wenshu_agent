from typing import TypeVar, Generic

T = TypeVar("T")


class Box(Generic[T]):
    def __init__(self, value: T):
        self.value = value

    def get_value(self) -> T:
        return self.value


box_int = Box[int](1)
box_str = Box[str]("1")
