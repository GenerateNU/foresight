import logging
import pandas as pd
from sqlalchemy import create_engine

class HotelDataParser:
    """
    Parser for client hotel data used in the Foresight pipeline.

    Purpose:
        - Load raw hotel data from a client file
        - Clean and standardize the data
        - Transform it into Foresight's expected schema
        - Validate the final output
        - Save the processed data to the local database

    Expected flow:
        1. load_data()
        2. clean_data()
        3. transform_data()
        4. validate_data()
        5. save_to_db()

    Main usage:
        parser = HotelDataParser(input_path, schema, db_url)
        parser.run()

    Attributes:
        input_path: Path to the client input file
        schema: Expected Foresight schema
        db_url: Database connection information
        raw_data: Original loaded client data
        cleaned_data: Cleaned version of the client data
        transformed_data: Data transformed into Foresight's expected schema
        column_mapping: Mapping of client column names to Foresight column names
    """

    def __init__(self, input_path, schema=None, db_url=None, column_mapping=None):
        """
        Initialize the hotel data parser.

        Args:
            input_path: Path to the client hotel data file.
            schema: Expected Foresight schema.
            db_url: Database connection information.
            column_mapping: Optional mapping of client column names
            to Foresight column names.
        """

        # Stores anything needed throughout the pipeline
        self.input_path = input_path
        self.schema = schema
        self.db_url = db_url

        # Stores data at different stages of processing
        self.raw_data = None
        self.cleaned_data = None
        self.transformed_data = None
        self.column_mapping = column_mapping or {}


        # Set up logging for parser runs
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s"
        )

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

        This method performs only safe, client-independent cleaning.
        Additional client-specific cleaning should be added after
        testing against the real data.

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
        string_columns = self.cleaned_data.select_dtypes(
            include="object"
        ).columns

        for column in string_columns:
            self.cleaned_data[column] = self.cleaned_data[column].str.strip()

        # TODO:
        # Add client-specific cleaning after testing against real data.

        self.logger.info("Data cleaning completed.")

        return self.cleaned_data

    def transform_data(self):
        """
        Transform cleaned client data into Foresight's expected schema.

        Client-specific column mappings can be passed into the parser
        through column_mapping.

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
        if self.column_mapping:
            self.transformed_data = self.transformed_data.rename(
                columns=self.column_mapping
            )

        # TODO:
        # Add client-specific transformations here once the real data
        # can be safely tested, such as:
        # - calculated fields
        # - date standardization
        # - currency conversion
        # - percentage conversion
        # - custom null handling


        self.logger.info("Data transformation completed.")

        return self.transformed_data
    
    def validate_data(self):
        """
        Validate the transformed hotel data.

        If a schema is provided, checks that required columns exist
        and that they do not contain missing values.

        Additional validation rules should be added once the real data
        and final schema requirements are confirmed.

        Returns:
            bool: True if validation passes.

        Raises:
            ValueError: If validation fails.
        """

        if self.transformed_data is None:
            raise ValueError("Data must be transformed before validation.")

        self.logger.info("Validating hotel data...")

        if self.schema is not None:
            missing_columns = [
                column
                for column in self.schema
                if column not in self.transformed_data.columns
            ]

            if missing_columns:
                self.logger.error(
                    f"Missing required columns: {missing_columns}"
                )
                raise ValueError(
                    f"Missing required columns: {missing_columns}"
                )

            # Check required columns for missing values
            null_counts = self.transformed_data[self.schema].isnull().sum()
            columns_with_nulls = null_counts[null_counts > 0]

            if not columns_with_nulls.empty:
                self.logger.error(
                    f"Missing values found: {columns_with_nulls.to_dict()}"
                )
                raise ValueError(
                    f"Missing values found: {columns_with_nulls.to_dict()}"
                )

        self.logger.info("Validation passed.")

        return True
    
    def save_to_db(self, table_name="hotel_data"):
        """
        Save the transformed hotel data to the local database.

        Data is only saved after validation has passed.

        Args:
            table_name: Name of the database table where hotel data will be stored.

        Raises:
            ValueError: If transformed data does not exist or no database URL is provided.
            Exception: If the database insert fails.
        """

        if self.transformed_data is None:
            raise ValueError("Data must be transformed before saving.")

        if self.db_url is None:
            raise ValueError("Database URL is required to save data.")

        self.logger.info("Saving hotel data to database...")

        try:
            # TODO:
            # This currently creates a new SQLAlchemy engine and writes directly
            # to a table using pandas.to_sql().
            # Before finalizing the parser, check the existing Foresight database
            # setup and models to see if we should reuse the project's existing
            # database session/connection instead.
            # Also confirm the correct table name and insertion method.

            # Create a connection to the database
            engine = create_engine(self.db_url)

            # Insert the transformed data into the database
            self.transformed_data.to_sql(
                name=table_name,
                con=engine,
                if_exists="append",
                index=False
            )

            self.logger.info(
                f"{len(self.transformed_data)} rows inserted into {table_name}."
            )

        except Exception as e:
            # Log the error and allow the pipeline to fail
            self.logger.error(f"Failed to save data to database: {e}")
            raise

    def run(self):
        """
        Run the full hotel data parsing pipeline.

        Executes each stage of the parser in order:
            1. Load the raw client data
            2. Clean the data
            3. Transform it into Foresight's schema
            4. Validate the transformed data
            5. Save the final data to the database

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
            self.save_to_db()

            self.logger.info("Hotel data parser completed successfully.")

            return self.transformed_data

        except Exception as e:
            # Log the failure and re-raise it so a scheduler can detect the failed job
            self.logger.error(f"Hotel data parser failed: {e}")
            raise