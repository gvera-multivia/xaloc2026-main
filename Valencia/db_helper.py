from sqlalchemy import create_engine, text
import pandas as pd
import os
from urllib.parse import quote_plus


class DBHelper:
    # Valores por defecto para tu proyecto
    DEFAULT_SERVER = "BD-SERVER"
    DEFAULT_DATABASE = "MULTIVIA"
    DEFAULT_USERNAME = os.getenv("DB_USERNAME")
    DEFAULT_PASSWORD = os.getenv("DB_PASSWORD")

    def __init__(
        self,
        server=None,
        database=None,
        username=None,
        password=None,
        driver="ODBC Driver 17 for SQL Server",
    ):
        """
        Inicializa el helper con los datos de conexión.
        Si no se pasan valores, usa los por defecto.
        """
        self.server = server or self.DEFAULT_SERVER
        self.database = database or self.DEFAULT_DATABASE
        self.username = username or self.DEFAULT_USERNAME
        self.password = password or self.DEFAULT_PASSWORD
        self.driver = driver
        self.engine = self._create_engine()

    def _create_engine(self):
        params = quote_plus(
            f"DRIVER={{{self.driver}}};"
            f"SERVER={self.server};DATABASE={self.database};UID={self.username};PWD={self.password};Encrypt=yes;TrustServerCertificate=yes"
        )
        return create_engine(f"mssql+pyodbc:///?odbc_connect={params}")

    def run_query(self, query, params=None):
        with self.engine.connect() as conn:
            return pd.read_sql(text(query), conn, params=params)

    def execute_sql(self, query, params=None):
        """Execute a statement returning the rowcount affected.

        This replaces the previous implementation that returned None, which
        broke callers (e.g. revoke_cert checked the return value)."""
        with self.engine.begin() as conn:
            result = conn.execute(text(query), params or {})
            # SQLAlchemy may return a Result with rowcount attribute
            try:
                return result.rowcount
            except AttributeError:
                return None
