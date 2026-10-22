"""SQLAlchemy models. Import every model module here so Alembic autogenerate sees it."""

from app.models.catalog import Course, Department, Professor, Section, SectionProfessor, Term

__all__ = ["Course", "Department", "Professor", "Section", "SectionProfessor", "Term"]
