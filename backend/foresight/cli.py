"""Operator commands, run through `just` (see the justfile).

For jobs that can't wait for the app to offer them. Like `worker.run_job`, a
command opens its own session and commits, once, when it succeeds; everything it
does goes through `services/`. A `DomainError` is printed and exits 1, with
nothing committed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from foresight.database.session import async_session_factory, engine
from foresight.services.domain import user as user_service
from foresight.services.errors import DomainError


async def link_user(email: str, hotel_id: int) -> None:
    async with async_session_factory() as session:
        user = await user_service.get_user_by_email(session, email)
        linked = await user_service.link_user_to_hotel(
            session, user_id=user.id, hotel_id=hotel_id
        )
        await session.commit()
    if linked:
        print(f"Linked {user.email} to hotel {hotel_id}")
    else:
        print(f"{user.email} is already linked to hotel {hotel_id}")


async def _run(args: argparse.Namespace) -> None:
    try:
        if args.command == "link-user":
            await link_user(args.email, args.hotel_id)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="foresight.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    link = commands.add_parser("link-user", help="Link a user to a hotel by email")
    link.add_argument("email", help="The user's email, as Google reports it")
    link.add_argument("hotel_id", type=int, help="The hotel's id")

    args = parser.parse_args(argv)
    try:
        asyncio.run(_run(args))
    except DomainError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
