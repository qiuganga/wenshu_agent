from typing import TypeVar

from typing_extensions import reveal_type


class Dog:
    pass


class Cat:
    pass


p = Dog
reveal_type(p)
reveal_type(Cat)


def create_dog(cls: type[Dog]) -> Dog:
    return cls()


def create_cat(cls: type[Cat]) -> Cat:
    return cls()


dog = create_dog(Dog)

T = TypeVar("T")


def create_animal(cls: type[T]) -> T:
    return cls()


animal = create_animal(Dog)
c = create_animal(Cat)
