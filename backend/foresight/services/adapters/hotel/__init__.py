"""Hotel CSV exports from the PMS (Guestline Rezlynx), one adapter per report:

- `actual_forecast`: Actual & Forecast, one row per night
- `reservations`: Daily New Reservations, one row per room booked
- `cancellations`: Cancellations, one row per room cancelled

`common` holds the shared row-by-row reading. Adapters never touch the
database; `services/ingest/` saves what they return.
"""
