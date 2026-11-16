"""SQLAlchemy models. Import every model module here so Alembic autogenerate sees it."""

from app.models.catalog import Course, Department, Professor, Section, SectionProfessor, Term
from app.models.review import Review, ReviewTarget

__all__ = [
    "Course",
    "Department",
    "Professor",
    "Review",
    "ReviewTarget",
    "Section",
    "SectionProfessor",
    "Term",
]
