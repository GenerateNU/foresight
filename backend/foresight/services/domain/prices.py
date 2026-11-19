"""VAT at the edges: the model is nett, the manager sees and types listed prices.

A version trained on booked rooms predicts `adr_nett`, the rate before VAT
(decision 0056). Managers think in the price they list, which includes VAT, so
every price the API returns from such a version has VAT added, and every rate a
manager sends is taken back to nett before it's compared, stored or trained on
(decision 0076). Inside, everything stays nett.

A version trained on nights predicts ARR, which is neither nett nor gross, so
its prices go out and come in as they are.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

from foresight.services.ml.features import LEAD

if TYPE_CHECKING:
    from foresight.database.models.city import City

# Accommodation VAT by country (ISO-3166 alpha-2). A fact of the country, not a
# deployment setting. Ireland's rate for hotel stays (0076).
VAT_RATES = {"IE": Decimal("0.135")}
# Ireland only for now, like the holidays (0067): a city without a country
# code, or with one not listed here, gets Ireland's rate.
_DEFAULT_COUNTRY = "IE"

NETT = "nett"  # a booked-room version's rate, before VAT
ARR = "arr"  # a night-trained version's rate, as recorded
_CENT = Decimal("0.01")


def basis_of(inputs: dict[str, Any] | None) -> str:
    """NETT for a recommendation from a version trained on booked rooms, which
    always reads days ahead; ARR otherwise, older snapshots included."""
    features = (inputs or {}).get("features", {})
    return NETT if features.get(LEAD) is not None else ARR


def vat_factor(city: City, basis: str) -> Decimal:
    """What a rate on `basis` is multiplied by to list it: 1 + VAT for NETT,
    1 for ARR."""
    if basis != NETT:
        return Decimal(1)
    return 1 + VAT_RATES.get(city.country or _DEFAULT_COUNTRY, VAT_RATES["IE"])


def to_listed(rate: Decimal, factor: Decimal) -> Decimal:
    """A stored rate as the manager sees it, to the cent."""
    return (rate * factor).quantize(_CENT, rounding=ROUND_HALF_UP)


def to_stored(listed: Decimal, factor: Decimal) -> Decimal:
    """A rate the manager typed, as it's stored and trained on, to the cent.

    Listing a stored rate and taking it back gives the same cents: rounding to
    list moves it by at most half a cent, and dividing by the factor shrinks
    that.
    """
    return (listed / factor).quantize(_CENT, rounding=ROUND_HALF_UP)
