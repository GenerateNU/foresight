"""Client hotel exports: parse a nightly CSV into `daily_performance` rows.

Never touches the database; `services/ingest/performance.py` saves the rows.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import pandas as pd

# The client draws no distinction between rooms. They price one standard room
# and apply their own multipliers downstream, so every night hangs off a single
# room type rather than the schema's per-type breakdown.
ROOM_TYPE = "Standard"

# What a malformed file raises while parsing.
PARSE_ERRORS = (ValueError, KeyError, pd.errors.ParserError)


class HotelDataParser:
    """
    Parser for client hotel data used in the Foresight pipeline.

    Purpose:
        - Load raw hotel data from a client file
        - Clean and standardize the data
        - Transform it into Foresight's expected schema
        - Validate the final output

    Expected flow:
        1. load_data()
        2. clean_data()
        3. transform_data()
        4. validate_data()

    The parser never touches the database; `services/ingest/performance.py`
    saves what it returns.

    Main usage:
        parser = HotelDataParser(file)
        parser.run()

    Attributes:
        input_path: Path to the client input file
        schema: Expected Foresight schema (required output columns)
        raw_data: Original loaded client data
        cleaned_data: Cleaned version of the client data
        transformed_data: Data transformed into Foresight's expected schema
        column_mapping: Mapping of client column names to Foresight column names
    """

    # Column mapping for this client's export format, confirmed against the
    # sample files: InStock is the hotel's total room count (Occ == Total /
    # InStock * 100), Total is rooms sold, Accomm is accommodation-only
    # revenue. Everything else in the export (DayOfWeek, Blocks, the
    # cumulative columns, Yield, Waitlist, ...) has no home in the schema yet.
    DEFAULT_COLUMN_MAPPING = {
        "Date": "stay_date",
        "InStock": "rooms_available",
        "Total": "rooms_sold",
        "Accomm": "room_revenue",
    }

    DEFAULT_SCHEMA = ["stay_date", "rooms_available", "rooms_sold", "room_revenue"]

    def __init__(self, input_path, schema=None, column_mapping=None):
        """
        Initialize the hotel data parser.

        Args:
            input_path: Path to, or file-like object of, a client export.
            schema: Optional list of required output columns.
            column_mapping: Optional mapping of client column names
            to Foresight column names.
        """

        self.input_path = input_path
        self.schema = schema or self.DEFAULT_SCHEMA
        self.column_mapping = column_mapping or self.DEFAULT_COLUMN_MAPPING

        # Stores data at different stages of processing
        self.raw_data: pd.DataFrame | None = None
        self.cleaned_data: pd.DataFrame | None = None
        self.transformed_data: pd.DataFrame | None = None

        self.logger = logging.getLogger(__name__)

    def load_data(self):
        """
        Load the client hotel data from the input file.

        The raw file is stored in self.raw_data so the original
        data can be kept separate from later cleaning and transformation steps.

        Returns:
            pandas.DataFrame: The raw hotel data.

        Raises:
            Exception: If the file cannot be loaded.
        """

        # Log the start of the file loading process
        self.logger.info("Loading hotel data...")

        try:
            # Read the client file and store the original data
            self.raw_data = pd.read_csv(self.input_path)

            # Log basic information about the loaded file
            self.logger.info(f"File loaded: {self.input_path}")
            self.logger.info(f"Rows: {self.raw_data.shape[0]}")
            self.logger.info(f"Columns: {self.raw_data.shape[1]}")

            return self.raw_data

        except Exception as e:
            # Log the error and raise it again so the pipeline is marked as failed
            self.logger.error(f"Failed to load file: {e}")
            raise

    def clean_data(self):
        """
        Clean the raw client hotel data using general cleaning rules.

        Returns:
            pandas.DataFrame: Cleaned hotel data.

        Raises:
            ValueError: If data has not been loaded first.
        """

        if self.raw_data is None:
            raise ValueError("Data must be loaded before cleaning.")

        self.logger.info("Cleaning hotel data...")

        self.cleaned_data = self.raw_data.copy()

        # Remove extra spaces from column names
        self.cleaned_data.columns = self.cleaned_data.columns.str.strip()

        # Remove duplicate rows
        self.cleaned_data = self.cleaned_data.drop_duplicates()

        # Remove extra spaces from text values
        string_columns = self.cleaned_data.select_dtypes(include="object").columns

        for column in string_columns:
            self.cleaned_data[column] = self.cleaned_data[column].str.strip()

        # Client export has no $ or % symbols today
        numeric_columns = [
            "Avail",
            "Total",
            "Occ",
            "Accomm",
            "InStock",
            "ARR",
            "APR",
        ]
        for column in numeric_columns:
            if column in self.cleaned_data.columns:
                self.cleaned_data[column] = (
                    self.cleaned_data[column]
                    .astype(str)
                    .str.replace(r"[$,%]", "", regex=True)
                )
                self.cleaned_data[column] = pd.to_numeric(
                    self.cleaned_data[column], errors="coerce"
                )

        # Parse the date column (client format is DD/MM/YYYY HH:MM)
        parsed_dates = pd.to_datetime(
            self.cleaned_data["Date"], format="%d/%m/%Y %H:%M", errors="coerce"
        ).dt.date
        unparseable = parsed_dates.isna().sum()
        if unparseable:
            self.logger.warning(
                f"Dropping {unparseable} row(s) with an unparseable Date."
            )
        self.cleaned_data["Date"] = parsed_dates
        self.cleaned_data = self.cleaned_data.dropna(subset=["Date"])

        # Recomputed occupancy should match the client's own
        # Occ column.
        recomputed_occ = self.cleaned_data["Total"] / self.cleaned_data["InStock"] * 100
        occ_diff = (recomputed_occ - self.cleaned_data["Occ"]).abs()
        mismatches = (occ_diff > 0.5).sum()
        if mismatches:
            self.logger.warning(
                f"{mismatches} row(s) where Total/InStock*100 does not match "
                "the client's Occ column."
            )

        self.logger.info("Data cleaning completed.")

        return self.cleaned_data

    def transform_data(self):
        """
        Transform cleaned client data into Foresight's expected schema.

        Returns:
            pandas.DataFrame: Transformed hotel data.

        Raises:
            ValueError: If data has not been cleaned first.
        """

        if self.cleaned_data is None:
            raise ValueError("Data must be cleaned before transformation.")

        self.logger.info("Transforming hotel data...")

        # Create a copy so cleaned data remains unchanged
        self.transformed_data = self.cleaned_data.copy()

        # Rename client columns using the provided mapping
        self.transformed_data = self.transformed_data.rename(
            columns=self.column_mapping
        )

        # Keep only the columns the schema cares about.
        self.transformed_data = self.transformed_data[self.schema].copy()

        self.logger.info("Data transformation completed.")

        return self.transformed_data

    def validate_data(self):
        """
        Validate the transformed hotel data.

        Checks that required columns exist, contain no missing values,
        contain no duplicate stay dates, and that the numbers are internally
        consistent (no negative revenue, sold rooms can't exceed inventory).

        Returns:
            bool: True if validation passes.

        Raises:
            ValueError: If validation fails.
        """

        if self.transformed_data is None:
            raise ValueError("Data must be transformed before validation.")

        self.logger.info("Validating hotel data...")

        data = self.transformed_data

        missing_columns = [
            column for column in self.schema if column not in data.columns
        ]
        if missing_columns:
            raise ValueError(f"Missing required columns: {missing_columns}")

        null_counts = data[self.schema].isnull().sum()
        columns_with_nulls = null_counts[null_counts > 0]
        if not columns_with_nulls.empty:
            raise ValueError(f"Missing values found: {columns_with_nulls.to_dict()}")

        duplicate_dates = data["stay_date"].duplicated().sum()
        if duplicate_dates:
            raise ValueError(f"Found {duplicate_dates} duplicate stay_date row(s).")

        if (data["rooms_sold"] > data["rooms_available"]).any():
            raise ValueError("rooms_sold exceeds rooms_available in one or more rows.")

        if (data["room_revenue"] < 0).any():
            raise ValueError("Negative room_revenue found.")

        self.logger.info("Validation passed.")

        return True

    def total_rooms(self):
        """The hotel's inventory, which the client reports per night as InStock."""
        if self.transformed_data is None:
            raise ValueError("Data must be transformed before reading inventory.")

        return int(self.transformed_data["rooms_available"].astype(int).max())

    def rows(self, room_type_id):
        """Transformed nights as `daily_performance` rows.

        One client row is one night for the hotel, which is one night for its
        single room type. The export has no listed price, so rate is the
        average rate paid (room revenue / rooms sold, the client's ARR) until
        listed-rate history arrives. Unsold nights have no rate.
        """
        if self.transformed_data is None:
            raise ValueError("Data must be transformed before persisting.")

        return [
            {
                "room_type_id": room_type_id,
                "stay_date": night["stay_date"],
                "rate": average_rate(night["room_revenue"], night["rooms_sold"]),
                "rooms_available": int(night["rooms_available"]),
                "rooms_sold": int(night["rooms_sold"]),
                "room_revenue": Decimal(str(night["room_revenue"])),
            }
            for night in self.transformed_data.to_dict(orient="records")
        ]

    def run(self):
        """
        Run the full hotel data parsing pipeline.

        Executes each stage of the parser in order:
            1. Load the raw client data
            2. Clean the data
            3. Transform it into Foresight's schema
            4. Validate the transformed data

        Returns:
            pandas.DataFrame: The final transformed hotel data.

        Raises:
            Exception: If any stage of the pipeline fails.
        """

        self.logger.info("Hotel data parser started.")

        try:
            self.load_data()
            self.clean_data()
            self.transform_data()
            self.validate_data()

            self.logger.info("Hotel data parser completed successfully.")

            return self.transformed_data

        except Exception as e:
            # Log the failure and re-raise it so a scheduler can detect the failed job
            self.logger.error(f"Hotel data parser failed: {e}")
            raise


def average_rate(room_revenue, rooms_sold):
    """Revenue per room sold, to the cent; None when nothing sold."""
    if not rooms_sold:
        return None
    return (Decimal(str(room_revenue)) / int(rooms_sold)).quantize(Decimal("0.01"))
