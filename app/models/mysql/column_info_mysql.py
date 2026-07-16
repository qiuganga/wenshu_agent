from typing import Any

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.mysql.base import Base


class ColumnInfoMySQL(Base):
    __tablename__ = "column_info"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="column id")
    name: Mapped[str] = mapped_column(String(128), comment="column name")
    type: Mapped[str] = mapped_column(String(64), comment="data type")
    role: Mapped[str] = mapped_column(String(32), comment="primary_key, foreign_key, measure, dimension")
    examples: Mapped[list[Any]] = mapped_column(JSON, comment="sample values")
    description: Mapped[str] = mapped_column(Text, comment="column description")
    alias: Mapped[list[str]] = mapped_column(JSON, comment="column aliases")
    table_id: Mapped[str] = mapped_column(String(64), comment="owner table id")
