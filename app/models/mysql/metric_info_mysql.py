from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.mysql.base import Base


class MetricInfoMySQL(Base):
    __tablename__ = "metric_info"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="metric id")
    name: Mapped[str] = mapped_column(String(128), comment="metric name")
    description: Mapped[str] = mapped_column(Text, comment="metric description")
    relevant_columns: Mapped[list[str]] = mapped_column(JSON, comment="related columns")
    alias: Mapped[list[str]] = mapped_column(JSON, comment="metric aliases")
