"""
Utilidades para conexión a SQL Server.

Centraliza la construcción del connection string para evitar duplicación.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def build_sqlserver_connection_string() -> str:
    """
    Construye el connection string de SQL Server desde variables de entorno.
    
    Variables requeridas en .env:
    - SQLSERVER_SERVER
    - SQLSERVER_DATABASE
    - SQLSERVER_USERNAME
    - SQLSERVER_PASSWORD
    
    Returns:
        Connection string para pyodbc
    """
    host = os.getenv("SQLSERVER_SERVER")
    database = os.getenv("SQLSERVER_DATABASE")
    user = os.getenv("SQLSERVER_USERNAME")
    password = os.getenv("SQLSERVER_PASSWORD")
    
    if not all([host, database, user, password]):
        missing = []
        if not host: missing.append("SQLSERVER_SERVER")
        if not database: missing.append("SQLSERVER_DATABASE")
        if not user: missing.append("SQLSERVER_USERNAME")
        if not password: missing.append("SQLSERVER_PASSWORD")
        raise ValueError(f"Faltan variables de entorno para SQL Server: {', '.join(missing)}")
    
    return (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={host};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        f"TrustServerCertificate=yes;"
    )
