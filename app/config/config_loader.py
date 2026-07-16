from pathlib import Path
from typing import Type, TypeVar

from omegaconf import OmegaConf

T = TypeVar("T")


def load_config(arg1, arg2) -> T:
    if isinstance(arg1, (str, Path)):
        config_file = Path(arg1)
        schema_cls: Type[T] = arg2
    else:
        schema_cls: Type[T] = arg1
        config_file = Path(arg2)

    schema = OmegaConf.structured(schema_cls)
    content = OmegaConf.load(config_file)
    conf = OmegaConf.merge(schema, content)
    return OmegaConf.to_object(conf)
