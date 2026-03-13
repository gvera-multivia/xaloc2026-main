"""
Utilidades para conexión a SQL Server.

Centraliza la construcción del connection string para evitar duplicación.
"""

import os
import platform
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

    driver = os.getenv("SQLSERVER_DRIVER")
    if not (driver or "").strip():
        # En Linux de contenedor solemos usar FreeTDS; en Windows, ODBC Driver 17.
        if platform.system().lower() == "windows":
            driver = "{ODBC Driver 17 for SQL Server}"
        else:
            driver = "FreeTDS"
    server = os.getenv("SQLSERVER_SERVER")
    port = (os.getenv("SQLSERVER_PORT") or "1433").strip() or "1433"
    tds_version = (os.getenv("SQLSERVER_TDS_VERSION") or "7.4").strip() or "7.4"
    login_timeout = (os.getenv("SQLSERVER_LOGIN_TIMEOUT") or "10").strip() or "10"
    database = os.getenv("SQLSERVER_DATABASE")
    username = os.getenv("SQLSERVER_USERNAME")
    password = os.getenv("SQLSERVER_PASSWORD")

    if os.getenv("SQLSERVER_TRUSTED_CONNECTION") == "1":
        if str(driver).strip().lower() == "freetds":
            return (
                f"DRIVER={driver};SERVER={server};PORT={port};TDS_Version={tds_version};"
                f"DATABASE={database};Trusted_Connection=yes;LoginTimeout={login_timeout}"
            )
        return (
            f"DRIVER={driver};SERVER={server};DATABASE={database};"
            f"Trusted_Connection=yes;LoginTimeout={login_timeout}"
        )

    if str(driver).strip().lower() == "freetds":
        return (
            f"DRIVER={driver};SERVER={server};PORT={port};TDS_Version={tds_version};"
            f"DATABASE={database};UID={username};PWD={password};"
            f"ClientCharset=UTF-8;LoginTimeout={login_timeout}"
        )

    return (
        f"DRIVER={driver};SERVER={server};DATABASE={database};UID={username};PWD={password};"
        f"LoginTimeout={login_timeout}"
    )
