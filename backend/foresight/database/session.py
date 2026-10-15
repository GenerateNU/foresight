from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from foresight.config import settings

engine = create_async_engine(
    settings.async_database_url,
    echo=settings.debug,
    # Neon computes scale to zero and drop idle connections; validate before use.
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """One transaction per request: commits on success, rolls back on error.

    Repositories never commit. Depend on this with `scope="function"` so the
    commit runs before the response is sent and a failed commit returns a 500.
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()
