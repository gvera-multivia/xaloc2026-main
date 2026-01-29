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
    - SQLSERVER_HOST
    - SQLSERVER_DATABASE
    - SQLSERVER_USER
    - SQLSERVER_PASSWORD
    
    Returns:
        Connection string para pyodbc
    """
    host = os.getenv("SQLSERVER_HOST", "localhost")
    database = os.getenv("SQLSERVER_DATABASE")
    user = os.getenv("SQLSERVER_USER")
    password = os.getenv("SQLSERVER_PASSWORD")
    
    if not all([database, user, password]):
        raise ValueError("Faltan variables de entorno para SQL Server (DATABASE, USER, PASSWORD)")
    
    return (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={host};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        f"TrustServerCertificate=yes;"
    )
