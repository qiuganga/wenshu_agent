from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.mysql.base import Base


class TableInfoMySQL(Base):
    __tablename__ = "table_info"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="table id")
    name: Mapped[str] = mapped_column(String(128), comment="table name")
    role: Mapped[str] = mapped_column(String(32), comment="fact or dimension")
    description: Mapped[str] = mapped_column(Text, comment="table description")
