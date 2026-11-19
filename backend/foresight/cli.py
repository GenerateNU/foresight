"""Operator commands, run through `just` (see the justfile).

For jobs that can't wait for the app to offer them. Like `worker.run_job`, a
command opens its own session and commits, once, when it succeeds; everything it
does goes through `services/`. A `DomainError` is printed and exits 1, with
nothing committed. `alignment`, `backtest` and `tuning-backtest` only read, so
they never commit.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import date, datetime
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING

from foresight.database.session import async_session_factory, engine
from foresight.services.domain import alignment as alignment_service
from foresight.services.domain import backtest as backtest_service
from foresight.services.domain import user as user_service
from foresight.services.errors import DomainError, InvalidRequestError
from foresight.services.ml.features import FEATURES, INPUT_GROUPS

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


async def alignment(hotel_id: int) -> None:
    async with async_session_factory() as session:
        weeks = await alignment_service.get_alignment(session, hotel_id)
    if not weeks:
        print("No manager rates with a recommendation to compare yet")
        return
    print(f"{'week':<12}{'rates':>6}{'mean gap':>10}{'mean |gap|':>12}")
    for w in weeks:
        print(f"{w.week!s:<12}{w.nights:>6}{w.mean_gap:>10}{w.mean_abs_gap:>12}")


async def backtest(
    hotel_id: int,
    test_days: int,
    out: Path,
    baselines: bool,
    inputs: list[str],
    event_days: int | None,
    start: date | None,
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


async def tuning_backtest(
    hotel_id: int,
    test_days: int,
    sizes: list[int],
    start: date | None,
    out: Path,
    rule: backtest_service.ManagerRule | None = None,
    manager_share: float = 1.0,
) -> None:
    async with async_session_factory() as session:
        result = await backtest_service.run_tuning_backtest(
            session,
            hotel_id,
            test_days=test_days,
            sizes=sizes,
            start=start,
            rule=rule,
            manager_share=manager_share,
        )
    base_mae = result.base["mae"]
    assert base_mae is not None
    manager = (
        f"synthetic, {result.rule} on the base" if result.rule else "recorded rates"
    )
    print(result.hotel_name)
    print(f"  Manager          {manager}, prices {result.manager_share:.0%} of days")
    print(f"  Base trained on  {result.train_start} to {result.cutoff}")
    print(
        f"  Scored on        {result.eval_start} to {result.eval_end} "
        f"({result.eval_nights} nights)"
    )
    print(f"  Base model MAE   €{base_mae:.2f}")
    print()
    print(_tuning_table(result.rows, synthetic=result.rule is not None))

    tuned = [r for r in result.rows if not r.skipped]
    path = out / f"tuning-hotel-{hotel_id}-{datetime.now():%Y-%m-%d-%H%M%S}.png"
    _save_tuning_plot(
        result.nights.loc[result.nights["scored"]],
        [r.feedback_days for r in tuned],
        path,
        actual_label=f"Manager ({result.rule})" if result.rule else "Actual",
        title=(
            f"Tune-up backtest: {result.hotel_name}, scored nights "
            f"{result.eval_start:%-d %b} – {result.eval_end:%-d %b %Y}"
        ),
        subtitle="  ·  ".join(
            [f"MAE: base {_euro(base_mae)}"]
            + [f"{r.feedback_days}d {_euro(r.with_untouched['mae'])}" for r in tuned]
        ),
    )
    print(f"Plot saved to {path}")


def _tuning_table(
    rows: list[backtest_service.TuningRow], *, synthetic: bool = False
) -> str:
    """Each feedback size's MAE and skill, without and with untouched nights.

    With a synthetic manager, also how much of their habit was learned.
    """
    lines = [
        f"{'Feedback':<10}{'Nights':>7}{'Untouched':>10}"
        f"{'MAE mgr-only':>14}{'Skill':>7}{'MAE +untouched':>16}{'Skill':>7}"
        f"{'Mean corr.':>12}" + (f"{'Learned':>9}{'Drift':>10}" if synthetic else "")
    ]
    for r in rows:
        label = f"{r.feedback_days} days"
        if r.skipped:
            lines.append(
                f"{label:<10}{r.feedback_nights:>7}{r.untouched_nights:>10}"
                f"  skipped: {r.skipped}"
            )
            continue
        corr = r.mean_correction or 0.0
        lines.append(
            f"{label:<10}{r.feedback_nights:>7}{r.untouched_nights:>10}"
            f"{_euro(r.manager_only['mae']):>14}{_pct(r.skill_manager_only):>7}"
            f"{_euro(r.with_untouched['mae']):>16}{_pct(r.skill_with_untouched):>7}"
            f"{_signed_euro(corr):>12}"
            + (
                f"{_share(r.recovery):>9}{_signed_euro(r.drift):>10}"
                if synthetic
                else ""
            )
        )
    lines.append(
        "Skill > 0 means the tune-up beats the base. '+untouched' is what ships "
        "(decision 0072)."
    )
    if synthetic:
        lines.append(
            "Learned: share of the manager's habit the shipped tune-up adds on the "
            "nights it applies to (100% is all of it). Drift: mean change on the "
            "other nights (€0 is right). Decision 0074."
        )
    lines.append("")
    lines.append(f"{'Feedback':<10}{'Feedback nights':<26}Untouched nights")
    for r in rows:
        untouched = _date_range(r.untouched_dates) if r.untouched_dates else "none"
        lines.append(
            f"{f'{r.feedback_days} days':<10}{_date_range(r.feedback_dates):<26}"
            f"{untouched}"
        )
    return "\n".join(lines)


def _signed_euro(value: float | None) -> str:
    if value is None:
        return "n/a"
    return ("+" if value >= 0 else "−") + "€" + format(abs(value), ".2f")


def _share(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _date_range(dates: tuple[date, date]) -> str:
    return f"{dates[0]} to {dates[1]}"


# Tune-up sizes, fewest days of feedback first: four distinct hues, which
# pass the palette validator on every pair (the lines cross everywhere). Each
# size also gets its own marker, so colour is never the only cue.
_TUNED_COLORS = ["#2a78d6", "#eda100", "#1baf7a", "#e34948"]
_TUNED_MARKERS = ["s", "^", "D", "v"]
# More sizes than that: one hue, light to dark (an ordinal ramp), no markers.
_TUNED_RAMP = ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]


def _save_tuning_plot(
    nights: pd.DataFrame,
    sizes: list[int],
    path: Path,
    *,
    title: str,
    subtitle: str,
    actual_label: str = "Actual",
) -> None:
    """Actual, base and each shipped tune-up's rate per scored night, as a PNG.

    One panel per room type, so room types are never averaged together.
    Nights sit side by side, with a divider and a break in the lines where
    nights are missing, so a gap in the data isn't drawn as a trend or as
    empty space.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    if len(sizes) <= len(_TUNED_COLORS):
        styles = [
            {"color": c, "marker": m, "markersize": 5, "markeredgecolor": "white",
             "markeredgewidth": 0.8}
            for c, m in zip(_TUNED_COLORS, _TUNED_MARKERS, strict=False)
        ]  # fmt: skip
    else:  # spread the ramp; never repeat or cycle a colour
        cmap = matplotlib.colors.LinearSegmentedColormap.from_list("t", _TUNED_RAMP)
        styles = [{"color": c} for c in cmap(np.linspace(0, 1, len(sizes)))]
    # Drawn in this order: tune-ups, then base on top (it sits almost under
    # them), then actual.
    series = [
        (f"tuned_{n}", {**style, "linewidth": 1.8, "label": f"Tuned, {n} days"})
        for n, style in zip(sizes, styles, strict=False)
    ]
    series.append(
        ("base", {"color": "#52514e", "linestyle": (0, (3, 2)), "linewidth": 1.5,
                  "label": "Base (untuned)"})
    )  # fmt: skip
    series.append(
        ("actual", {"color": "#0b0b0b", "linewidth": 2, "marker": "o",
                    "markersize": 5, "markeredgecolor": "white",
                    "markeredgewidth": 1, "label": actual_label, "zorder": 3})
    )  # fmt: skip

    room_types = list(dict.fromkeys(nights["room_type"]))
    fig, axes = plt.subplots(
        len(room_types), 1, figsize=(11, 4.5 * len(room_types)), squeeze=False
    )
    for ax, room in zip(axes[:, 0], room_types, strict=True):
        rows = nights.loc[nights["room_type"] == room].sort_values("stay_date")
        dates = list(rows["stay_date"])
        breaks = _gap_axis(ax, dates)
        x = np.insert(np.arange(len(dates), dtype=float), breaks, np.nan)
        for column, style in series:
            y = np.insert(rows[column].to_numpy(dtype=float), breaks, np.nan)
            ax.plot(x, y, **style)
        if len(room_types) > 1:
            ax.set_title(room, loc="left", fontsize=10, color="#52514e")
        ax.set_ylabel("Rate (€)")
        ax.grid(axis="y", color="#e5e5e5", linewidth=0.8)
        ax.spines[["top", "right"]].set_visible(False)

    top_ax = axes[0, 0]
    top_ax.set_title(title, loc="left", pad=24)
    top_ax.text(
        0, 1.02, subtitle, transform=top_ax.transAxes, fontsize=9,
        color="#52514e", va="bottom",
    )  # fmt: skip
    bottom, top = top_ax.get_ylim()
    top_ax.set_ylim(bottom, top + 0.25 * (top - bottom))  # room for the legend
    top_ax.legend(frameon=False, loc="upper left", ncols=3, fontsize=9)
    axes[-1, 0].set_xlabel("Scored night (dotted lines: nights missing from the data)")
    fig.tight_layout()

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _gap_axis(ax, dates: list[date]):
    """Sets up an x axis of nights side by side, one position per night.

    Draws a dotted divider wherever nights are missing, labels the first
    night, the first after each gap and every third night, and returns the
    break positions: insert NaN there (`np.insert`) so lines stop at a gap.
    """
    import numpy as np

    # A gap starts at every night more than a day after the one before.
    gap = np.array([False] + [(b - a).days > 1 for a, b in pairwise(dates)])
    breaks = np.flatnonzero(gap)
    for b in breaks:
        ax.axvline(b - 0.5, color="#c3c2b7", linewidth=1, linestyle=":")
    ticks = [i for i in range(len(dates)) if i == 0 or gap[i] or i % 3 == 0]
    ax.set_xticks(ticks, [f"{dates[i]:%-d %b}" for i in ticks], fontsize=9)
    ax.set_xlim(-0.5, len(dates) - 0.5)
    return breaks


def _euro(value: float | None) -> str:
    return "n/a" if value is None else f"€{value:.2f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.0%}"


def _parse_manager_rule(text: str) -> backtest_service.ManagerRule:
    """`--manager-rule`: nights, then a signed percent, e.g. weekend+15%.

    Raises argparse.ArgumentTypeError for anything else.
    """
    match = re.fullmatch(r"([a-z]+)([+-]\d+(?:\.\d+)?)%?", text.strip().lower())
    if match is None:
        raise argparse.ArgumentTypeError(
            f"expected nights and a percent, e.g. weekend+15%; got {text!r}"
        )
    try:
        return backtest_service.ManagerRule(match.group(1), float(match.group(2)) / 100)
    except InvalidRequestError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _parse_sizes(text: str) -> list[int]:
    """`--sizes`: comma-separated positive day counts, e.g. 5,10,20,30.

    Raises argparse.ArgumentTypeError for anything else.
    """
    try:
        sizes = [int(n) for n in text.split(",") if n.strip()]
    except ValueError:
        sizes = []
    if not sizes or min(sizes) < 1:
        raise argparse.ArgumentTypeError(
            f"expected positive whole days, e.g. 5,10,20,30; got {text!r}"
        )
    return sorted(set(sizes))


def _describe_inputs(inputs: list[str]) -> str:
    """Inputs named by group where a whole group is in, e.g. "calendar, event_count"."""
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
    """`--inputs`: comma-separated group names and/or features, in FEATURES
    order.

    Raises argparse.ArgumentTypeError for an unknown name.
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
    import numpy as np

    interval = f"{1 - backtest_service.ALPHA:.0%}"
    nights = nights.sort_values("stay_date").reset_index(drop=True)
    missed = (nights["actual"] < nights["low"]) | (nights["actual"] > nights["high"])

    fig, ax = plt.subplots(figsize=(11, 4.5))
    # Nights side by side, with a break and a dotted divider where nights are
    # missing, so a gap in the data isn't drawn as a trend.
    breaks = _gap_axis(ax, list(nights["stay_date"]))
    x = np.insert(np.arange(len(nights), dtype=float), breaks, np.nan)

    def line(column: str) -> np.ndarray:
        return np.insert(nights[column].to_numpy(dtype=float), breaks, np.nan)

    ax.fill_between(
        x,
        line("low"),
        line("high"),
        color="#eb6834",
        alpha=0.15,
        linewidth=0,
        label=f"{interval} interval",
    )
    ax.plot(
        x,
        line("actual"),
        color="#2a78d6",
        linewidth=2,
        label="Actual",
    )
    ax.plot(
        x,
        line("predicted"),
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
                x,
                line(name),
                color="#888888",
                linestyle=style,
                linewidth=1.2,
                label=label,
            )
    # The nights the interval missed: the ones that pull coverage down.
    ax.scatter(
        nights.index[missed],
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
    ax.set_xlabel("Test night (dotted lines: nights missing from the data)")
    fig.tight_layout()

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


async def _run(args: argparse.Namespace) -> None:
    try:
        if args.command == "link-user":
            await link_user(args.email, args.hotel_id)
        elif args.command == "alignment":
            await alignment(args.hotel_id)
        elif args.command == "backtest":
            await backtest(
                args.hotel_id,
                args.test_days,
                args.out,
                args.baselines,
                args.inputs,
                args.event_days,
                args.start,
            )
        elif args.command == "tuning-backtest":
            await tuning_backtest(
                args.hotel_id,
                args.test_days,
                args.sizes,
                args.start,
                args.out,
                args.manager_rule,
                args.manager_share,
            )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="foresight.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    link = commands.add_parser("link-user", help="Link a user to a hotel by email")
    link.add_argument("email", help="The user's email, as Google reports it")
    link.add_argument("hotel_id", type=int, help="The hotel's id")

    al = commands.add_parser(
        "alignment", help="Show how far the model is from the manager's rates, by week"
    )
    al.add_argument("hotel_id", type=int, help="The hotel's id")

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
        default=list(FEATURES),
        metavar="NAMES",
        help=(
            "Comma-separated inputs to train on: groups "
            f"({', '.join(INPUT_GROUPS)}) and/or single features, e.g. "
            "calendar,event_count. Default: all, like the served model"
        ),
    )
    bt.add_argument(
        "--out", type=Path, default=Path("backtest-out"), help="Folder for the plot"
    )

    tb = commands.add_parser(
        "tuning-backtest",
        help="Score the tune-up against the base model, by days of manager feedback",
    )
    tb.add_argument("hotel_id", type=int, help="The hotel's id")
    tb.add_argument(
        "--test-days",
        type=int,
        default=60,
        help=(
            "Newest priced days held out from the base: the first max(--sizes) "
            "are feedback, the rest are scored. Default: 60"
        ),
    )
    tb.add_argument(
        "--sizes",
        type=_parse_sizes,
        default=list(backtest_service.TUNING_SIZES),
        metavar="DAYS",
        help="Comma-separated days of manager feedback to try. Default: 5,10,20,30",
    )
    tb.add_argument("--start", type=date.fromisoformat, help="Leave out earlier nights")
    tb.add_argument(
        "--manager-rule",
        type=_parse_manager_rule,
        default=None,
        metavar="RULE",
        help=(
            "A synthetic manager with a habit the base lacks, e.g. weekend+15%%, "
            "events+20%%, all-10%%. Nights: "
            f"{', '.join(backtest_service.RULE_NIGHTS)}. "
            "Their rate is the base's with the rule applied. Default: none, the "
            "recorded rate is the manager's"
        ),
    )
    tb.add_argument(
        "--manager-share",
        type=float,
        default=1.0,
        metavar="SHARE",
        help=(
            "Share of feedback days the manager prices, e.g. 0.3; the rest are "
            "learned as 'no change'. Default: 1, every day"
        ),
    )
    tb.add_argument(
        "--out",
        type=Path,
        default=Path("backtest-out"),
        help="Folder for the plot",
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
