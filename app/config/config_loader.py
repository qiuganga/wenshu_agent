from pathlib import Path
from typing import TypeVar, cast, overload

from omegaconf import OmegaConf

T = TypeVar("T")


@overload
def load_config(arg1: type[T], arg2: str | Path) -> T: ...


@overload
def load_config(arg1: str | Path, arg2: type[T]) -> T: ...


def load_config(arg1: type[T] | str | Path, arg2: type[T] | str | Path) -> T:
    if isinstance(arg1, str | Path):
        config_file = Path(arg1)
        schema_cls = cast(type[T], arg2)
    else:
        schema_cls = arg1
        config_file = Path(cast(str | Path, arg2))

    schema = OmegaConf.structured(schema_cls)
    if config_file.exists():
        content = OmegaConf.load(config_file)
        conf = OmegaConf.merge(schema, content)
    else:
        conf = schema
    OmegaConf.resolve(conf)
    return cast(T, OmegaConf.to_object(conf))
