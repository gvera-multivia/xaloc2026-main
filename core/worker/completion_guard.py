from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

import pyodbc

from core.sqlserver_utils import build_sqlserver_connection_string


@dataclass(frozen=True)
class ResourceCompletionStatus:
    resource_id: int
    found: bool
    completed: bool
    estado: Any = None
    completed_at: Any = None


class SQLServerCompletionGuard:
    """Revalida el estado de un recurso antes de ejecutar un job reservado."""

    QUERY = """
        SELECT TOP (1) Estado, FUsuarioCompletado
        FROM Recursos.RecursosExp
        WHERE idRecurso = ?
    """

    def __init__(
        self,
        *,
        conn_str: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        connect: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._conn_str = conn_str or build_sqlserver_connection_string()
        self._logger = logger or logging.getLogger("worker.completion_guard")
        self._connect = connect or pyodbc.connect
        self._connection: Any = None

    def _get_connection(self) -> Any:
        if self._connection is None:
            self._connection = self._connect(self._conn_str, autocommit=True)
        return self._connection

    def _discard_connection(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    @staticmethod
    def _estado_is_completed(estado: Any) -> bool:
        try:
            return int(estado) == 2
        except (TypeError, ValueError):
            return False

    def check(self, resource_id: int) -> Optional[ResourceCompletionStatus]:
        """
        Devuelve ``None`` si no puede consultarse SQL Server.

        El llamador debe interpretar ``None`` de forma conservadora y ejecutar el
        trabajo; un fallo de infraestructura nunca debe descartar un recurso.
        """
        rid = int(resource_id)
        cursor = None
        try:
            cursor = self._get_connection().cursor()
            cursor.execute(self.QUERY, (rid,))
            row = cursor.fetchone()
            if row is None:
                return ResourceCompletionStatus(
                    resource_id=rid,
                    found=False,
                    completed=False,
                )

            estado, completed_at = row[0], row[1]
            # FUsuarioCompletado puede conservar una fecha historica cuando XVIA
            # reabre un recurso (Estado=0). Estado es la fuente de verdad; la fecha
            # solo se devuelve para trazabilidad del descarte.
            return ResourceCompletionStatus(
                resource_id=rid,
                found=True,
                completed=self._estado_is_completed(estado),
                estado=estado,
                completed_at=completed_at,
            )
        except Exception as exc:
            self._logger.warning(
                "No se pudo revalidar en SQL Server el recurso %s; se procesara para no perder trabajo: %s",
                rid,
                exc,
            )
            self._discard_connection()
            return None
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass

    def close(self) -> None:
        self._discard_connection()
