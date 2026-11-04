"""Operator commands, run through `just` (see the justfile).

For jobs that can't wait for the app to offer them. Like `worker.run_job`, a
command opens its own session and commits, once, when it succeeds; everything it
does goes through `services/`. A `DomainError` is printed and exits 1, with
nothing committed. `backtest` only reads, so it never commits.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from foresight.database.session import async_session_factory, engine
from foresight.services.domain import backtest as backtest_service
from foresight.services.domain import user as user_service
from foresight.services.errors import DomainError
from foresight.services.ml.features import (
    BACKTEST_INPUTS,
    BOOKING_LEAD_DAYS,
    FEATURES,
    INPUT_GROUPS,
)

if TYPE_CHECKING:
    import pandas as pd


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


async def backtest(
    hotel_id: int,
    test_days: int,
    out: Path,
    baselines: bool,
    inputs: list[str],
    event_days: int | None,
    start: date | None,
    lead_days: int,
) -> None:
    async with async_session_factory() as session:
        result = await backtest_service.run_backtest(
            session,
            hotel_id,
            test_days=test_days,
            baselines=baselines,
            inputs=inputs,
            event_days=event_days,
            start=start,
            lead_days=lead_days,
        )
    nights = result.nights
    first, last = nights["stay_date"].min(), nights["stay_date"].max()
    described = _describe_inputs(result.inputs)
    if result.event_days is not None:
        described += f"; {result.event_days} days of event history"
    print(f"{len(nights)} test nights, {first} to {last}; inputs: {described}")
    scores = _format_metrics(result.metrics)
    for name, value in scores:
        print(f"{name:<13} {value}")
    if result.baselines:
        print()
        print(_baseline_table(result.baselines, len(nights)))

    path = out / f"hotel-{hotel_id}-{datetime.now():%Y-%m-%d-%H%M%S}.png"
    _save_plot(
        nights,
        path,
        title=(
            f"Backtest: {result.hotel_name}, actual vs predicted rate, "
            f"{first:%-d %b} – {last:%-d %b %Y} ({described})"
        ),
        subtitle="  ·  ".join(f"{name} {value}" for name, value in scores),
    )
    print(f"Plot saved to {path}")


def _describe_inputs(inputs: list[str]) -> str:
    """Inputs named by group where a whole group is in, e.g. "calendar, precip_mm"."""
    if inputs == FEATURES:
        return "all inputs"
    chosen, parts = set(inputs), []
    for group, columns in INPUT_GROUPS.items():
        if set(columns) <= chosen:
            parts.append(group)
        else:
            parts.extend(c for c in columns if c in chosen)
    return ", ".join(parts)


def _parse_inputs(text: str) -> list[str]:
    """`--inputs`: comma-separated group names and/or features, in BACKTEST_INPUTS
    order.

    Raises argparse.ArgumentTypeError for an unknown name.
    """
    names = [n.strip() for n in text.split(",") if n.strip()]
    unknown = [n for n in names if n not in INPUT_GROUPS and n not in BACKTEST_INPUTS]
    if unknown or not names:
        raise argparse.ArgumentTypeError(
            f"unknown input {', '.join(unknown) or '(none given)'}; choose from "
            f"groups {', '.join(INPUT_GROUPS)} or features "
            f"{', '.join(BACKTEST_INPUTS)}"
        )
    expanded = [c for n in names for c in INPUT_GROUPS.get(n, [n])]
    return backtest_service.in_feature_order(expanded)


def _format_metrics(metrics: dict[str, float | None]) -> list[tuple[str, str]]:
    """The backtest's scores as (label, value) pairs, for the terminal and plot."""
    coverage = metrics["coverage"]
    bias = metrics["bias"]
    assert bias is not None  # always scored; only coverage can be missing
    interval = f"{1 - backtest_service.ALPHA:.0%}"
    return [
        ("MAE", f"€{metrics['mae']:.2f}"),
        ("RMSE", f"€{metrics['rmse']:.2f}"),
        ("Bias", f"{'+' if bias >= 0 else '−'}€{abs(bias):.2f}"),
        ("MAPE", f"{metrics['mape']:.1%}"),
        ("R²", f"{metrics['r2']:.3f}"),
        (
            f"{interval} coverage",
            "n/a" if coverage is None else f"{coverage:.0%}",
        ),
    ]


def _baseline_table(
    scores: dict[str, backtest_service.BaselineScore], total: int
) -> str:
    """The model's MAE next to each baseline's, on the nights the baseline covers."""
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


def _save_plot(nights: pd.DataFrame, path: Path, *, title: str, subtitle: str) -> None:
    """Actual vs predicted rate per night, as a PNG, with the scores under the title."""
    # Imported here so only this command needs matplotlib, not the API.
    import matplotlib

    matplotlib.use("Agg")  # write files; no window
    import matplotlib.pyplot as plt

    interval = f"{1 - backtest_service.ALPHA:.0%}"
    missed = (nights["actual"] < nights["low"]) | (nights["actual"] > nights["high"])

    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.fill_between(
        nights["stay_date"],
        nights["low"],
        nights["high"],
        color="#eb6834",
        alpha=0.15,
        linewidth=0,
        label=f"{interval} interval",
    )
    ax.plot(
        nights["stay_date"],
        nights["actual"],
        color="#2a78d6",
        linewidth=2,
        label="Actual",
    )
    ax.plot(
        nights["stay_date"],
        nights["predicted"],
        color="#eb6834",
        linewidth=2,
        label="Predicted",
    )
    # Baselines:
    for (name, label), style in zip(
        backtest_service.BASELINES.items(), ["--", ":"], strict=True
    ):
        if name in nights and nights[name].notna().any():
            ax.plot(
                nights["stay_date"],
                nights[name],
                color="#888888",
                linestyle=style,
                linewidth=1.2,
                label=label,
            )
    # The nights the interval missed: the ones that pull coverage down.
    ax.scatter(
        nights.loc[missed, "stay_date"],
        nights.loc[missed, "actual"],
        s=40,
        color="#2a78d6",
        edgecolors="white",
        linewidths=1.5,
        zorder=3,
        label=f"Outside interval ({int(missed.sum())})",
    )
    ax.set_title(title, loc="left", pad=24)
    ax.text(
        0,
        1.02,
        subtitle,
        transform=ax.transAxes,
        fontsize=9,
        color="#555555",
        va="bottom",
    )
    ax.set_ylabel("Rate (€)")
    ax.grid(axis="y", color="#e5e5e5", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    bottom, top = ax.get_ylim()
    ax.set_ylim(bottom, top + 0.25 * (top - bottom))  # room for the legend
    ax.legend(frameon=False, loc="upper left", ncols=4)
    fig.autofmt_xdate()
    fig.tight_layout()

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


async def _run(args: argparse.Namespace) -> None:
    try:
        if args.command == "link-user":
            await link_user(args.email, args.hotel_id)
        elif args.command == "backtest":
            await backtest(
                args.hotel_id,
                args.test_days,
                args.out,
                args.baselines,
                args.inputs,
                args.event_days,
                args.start,
                args.lead_days,
            )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
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
        help="Leave out earlier nights; needed with the bookings inputs, e.g. "
        "the first night the booking export fully covers",
    )
    bt.add_argument(
        "--lead-days",
        type=int,
        default=BOOKING_LEAD_DAYS,
        help="How many days before each night to read the bookings inputs",
    )
    bt.add_argument(
        "--inputs",
        type=_parse_inputs,
        default=list(FEATURES),
        metavar="NAMES",
        help=(
            "Comma-separated inputs to train on: groups "
            f"({', '.join(INPUT_GROUPS)}) and/or single features, e.g. "
            "calendar,temp_max_c. Default: all, like the served model"
        ),
    )
    bt.add_argument(
        "--out", type=Path, default=Path("backtest-out"), help="Folder for the plot"
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
