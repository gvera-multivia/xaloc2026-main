"""
Utilidades para conexión a SQL Server.

Centraliza la construcción del connection string para evitar duplicación.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def build_sqlserver_connection_string() -> str:
    """
    Construye el connection string para SQL Server.
    Prioridad: variable de entorno completa > variables separadas.
    """
    direct = os.getenv("SQLSERVER_CONNECTION_STRING")
    if direct:
        return direct

    driver = os.getenv("SQLSERVER_DRIVER", "{ODBC Driver 17 for SQL Server}")
    server = os.getenv("SQLSERVER_SERVER")
    database = os.getenv("SQLSERVER_DATABASE")
    username = os.getenv("SQLSERVER_USERNAME")
    password = os.getenv("SQLSERVER_PASSWORD")
    
    if os.getenv("SQLSERVER_TRUSTED_CONNECTION") == "1":
        return f"DRIVER={driver};SERVER={server};DATABASE={database};Trusted_Connection=yes"
    
    return f"DRIVER={driver};SERVER={server};DATABASE={database};UID={username};PWD={password}"
