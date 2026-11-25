import argparse
import asyncio
import sys
from datetime import date

import pandas as pd

from foresight.database.session import async_session_factory, engine
from foresight.services.errors import DomainError
from foresight.services.ml.features import FEATURES, INPUT_GROUPS, LEAD
from foresight.services.pricing import backtest as backtest_service
from foresight.services.users import user as user_service


async def link_user(email: str, hotel_id: int) -> None:
    """Links a user to a hotel by email, and commits.

    Operator commands run through `just`. Like `worker.run_job`, each opens its
    own session and commits once, when it succeeds; a `DomainError` is printed
    and exits 1 with nothing committed.

    Args:
        email (str): The user's email, as Google reports it.
        hotel_id (int): The hotel.

    Raises:
        NotFoundError: Unknown user or hotel.
        ConflictError: Several users share the email.
    """
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


async def backtest(
    hotel_id: int,
    test_days: int,
    baselines: bool,
    inputs: list[str] | None,
    event_days: int | None,
    start: date | None,
) -> None:
    """Scores the model on the hotel's newest nights and prints the result.

    Only reads, so it never commits. The session closes before the fit: a long
    fit would outlast the connection.

    Args:
        hotel_id (int): The hotel.
        test_days (int): Recent nights to predict.
        baselines (bool): Also score the baselines.
        inputs (list[str] | None): The features to train on; None for all.
        event_days (int | None): Event history to keep; None for all.
        start (date | None): Leave out earlier nights.

    Raises:
        NotFoundError: The hotel doesn't exist.
        InvalidRequestError: No nights on one side of the cutoff.
    """
    async with async_session_factory() as session:
        split = await backtest_service.load_backtest(
            session, hotel_id, test_days=test_days, start=start
        )
    result = await backtest_service.run_backtest(
        split, baselines=baselines, inputs=inputs, event_days=event_days
    )
    rows = result.rows
    first, last = rows["stay_date"].min(), rows["stay_date"].max()
    n_nights = rows["stay_date"].nunique()
    described = _describe_inputs(result.inputs)
    if result.event_days is not None:
        described += f"; {result.event_days} days of event history"
    print(
        f"{len(rows)} booked rooms over {n_nights} nights, {first} to {last}; "
        f"inputs: {described}"
    )
    scores = _format_metrics(result.metrics)
    for name, value in scores:
        print(f"{name:<13} {value}")
    print()
    print(_lead_table(rows))
    if result.baselines:
        print()
        print(_baseline_table(result.baselines, len(rows)))


_LEAD_BUCKETS = [("0-7", 0, 7), ("8-30", 8, 30), ("31-90", 31, 90), ("91+", 91, None)]


def _lead_table(rows: pd.DataFrame) -> str:
    """Breaks the model's MAE on booked rooms down by days booked ahead.

    Args:
        rows (pd.DataFrame): The test rows.

    Returns:
        str: The table, one line per bucket in `_LEAD_BUCKETS`.
    """
    lines = [f"{'Days ahead':<11} {'Rooms':>6} {'MAE':>9}"]
    error = (rows["actual"] - rows["predicted"]).abs()
    for label, low, high in _LEAD_BUCKETS:
        inside = rows[LEAD] >= low
        if high is not None:
            inside &= rows[LEAD] <= high
        if inside.any():
            mae = error[inside].mean()
            lines.append(f"{label:<11} {int(inside.sum()):>6} €{mae:>7.2f}")
    return "\n".join(lines)


def _describe_inputs(inputs: list[str]) -> str:
    """Names inputs by group where a whole group is in, e.g. "calendar, event_count".

    Args:
        inputs (list[str]): The inputs.

    Returns:
        str: Their description.
    """
    chosen, parts = set(inputs), []
    for group, columns in INPUT_GROUPS.items():
        if set(columns) <= chosen:
            parts.append(group)
        else:
            parts.extend(c for c in columns if c in chosen)
    return ", ".join(parts)


def _parse_inputs(text: str) -> list[str]:
    """Reads `--inputs`: comma-separated group names and features.

    Args:
        text (str): The argument.

    Returns:
        list[str]: The features, in FEATURES order.

    Raises:
        argparse.ArgumentTypeError: A name is unknown, or none is given.
    """
    names = [n.strip() for n in text.split(",") if n.strip()]
    unknown = [n for n in names if n not in INPUT_GROUPS and n not in FEATURES]
    if unknown or not names:
        raise argparse.ArgumentTypeError(
            f"unknown input {', '.join(unknown) or '(none given)'}; choose from "
            f"groups {', '.join(INPUT_GROUPS)} or features "
            f"{', '.join(FEATURES)}"
        )
    expanded = [c for n in names for c in INPUT_GROUPS.get(n, [n])]
    return backtest_service.in_feature_order(expanded)


def _format_metrics(metrics: dict[str, float]) -> list[tuple[str, str]]:
    """Formats the backtest's scores for the terminal.

    Args:
        metrics (dict[str, float]): mae, rmse, bias, mape and r2.

    Returns:
        list[tuple[str, str]]: Label and value pairs.
    """
    bias = metrics["bias"]
    return [
        ("MAE", f"€{metrics['mae']:.2f}"),
        ("RMSE", f"€{metrics['rmse']:.2f}"),
        ("Bias", f"{'+' if bias >= 0 else '−'}€{abs(bias):.2f}"),
        ("MAPE", f"{metrics['mape']:.1%}"),
        ("R²", f"{metrics['r2']:.3f}"),
    ]


def _baseline_table(
    scores: dict[str, backtest_service.BaselineScore], total: int
) -> str:
    """Puts the model's MAE next to each baseline's, on the nights it covers.

    Args:
        scores (dict[str, backtest_service.BaselineScore]): Each baseline's
            scores.
        total (int): Test rows in all.

    Returns:
        str: The table.
    """
    lines = [
        f"{'Compared with':<28} {'Nights':>9} {'Baseline MAE':>13} "
        f"{'Model MAE':>10} {'Skill':>7}"
    ]
    for name, label in backtest_service.BASELINES.items():
        b = scores[name]
        if b.nights == 0:
            lines.append(f"{label:<28} {'0/' + str(total):>9}   no history")
            continue
        skill = "n/a" if b.skill is None else f"{b.skill:+.0%}"
        lines.append(
            f"{label:<28} {f'{b.nights}/{total}':>9} "
            f"{'€' + format(b.metrics['mae'], '.2f'):>13} "
            f"{'€' + format(b.model_mae, '.2f'):>10} {skill:>7}"
        )
    lines.append("Skill > 0 means the model beats the baseline.")
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> None:
    """Runs a command, then closes the database engine.

    Args:
        args (argparse.Namespace): The parsed command line.
    """
    try:
        if args.command == "link-user":
            await link_user(args.email, args.hotel_id)
        elif args.command == "backtest":
            await backtest(
                args.hotel_id,
                args.test_days,
                args.baselines,
                args.inputs,
                args.event_days,
                args.start,
            )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    """Parses the command line and runs the command.

    Args:
        argv (list[str] | None): The arguments; None for `sys.argv`.

    Returns:
        int: The exit code: 0, or 1 after a DomainError.
    """
    parser = argparse.ArgumentParser(prog="foresight.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    link = commands.add_parser("link-user", help="Link a user to a hotel by email")
    link.add_argument("email", help="The user's email, as Google reports it")
    link.add_argument("hotel_id", type=int, help="The hotel's id")

    bt = commands.add_parser("backtest", help="Score the model on its newest nights")
    bt.add_argument("hotel_id", type=int, help="The hotel's id")
    bt.add_argument(
        "--test-days", type=int, default=90, help="How many recent nights to predict"
    )
    bt.add_argument(
        "--event-days",
        type=int,
        default=None,
        help=(
            "Train on only this many days of event history before the cutoff, "
            "e.g. 30. Other inputs keep all their history. Default: all"
        ),
    )
    bt.add_argument(
        "--baselines",
        action="store_true",
        help="Also score simple baselines the model should beat",
    )
    bt.add_argument(
        "--start",
        type=date.fromisoformat,
        help="Leave out earlier nights",
    )
    bt.add_argument(
        "--inputs",
        type=_parse_inputs,
        metavar="NAMES",
        help=(
            "Comma-separated inputs to train on: groups "
            f"({', '.join(INPUT_GROUPS)}) and/or single features, e.g. "
            "calendar,event_count. Default: every input the hotel's training "
            "data has, like the served model"
        ),
    )

    args = parser.parse_args(argv)
    try:
        asyncio.run(_run(args))
    except DomainError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
