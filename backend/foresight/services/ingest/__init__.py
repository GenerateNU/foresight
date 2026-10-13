"""External data adapters: fetch from a third-party API and normalize.

Adapters never touch the database. Domain services (`services/event.py`,
`services/weather.py`, `services/flight.py`) call them and persist the result
through the repository layer.
"""
