"""Repository layer.

Encapsulates all database access. Repositories translate between ORM models
(`database.models`) and the rest of the application, so services and routes
never touch SQLAlchemy sessions directly.
"""
