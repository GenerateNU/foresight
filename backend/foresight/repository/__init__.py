"""Repository layer.

Encapsulates all database access. Repositories translate between ORM models
(`database.models`) and the rest of the application, so services and routes
never touch SQLAlchemy sessions directly.

One module per model file (`database/models/X.py` <-> `repository/X.py`), plus
shared helpers: `upsert.py` and `pagination.py`.
"""
