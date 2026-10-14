"""External data adapters: call a third-party API or parse a file, and return
normalized rows. Adapters never touch the database; `services/ingest/` saves
what they return.
"""
