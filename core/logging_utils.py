import logging
import json
import datetime

class JSONFormatter(logging.Formatter):
    """
    Formateador de logs que emite JSON por línea.
    Útil para ingesta por sistemas de monitoreo (ELK, Datadog, etc.).
    """
    def format(self, record):
        log_record = {
            "timestamp": datetime.datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno
        }
        
        # Añadir excepciones si existen
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
            
        # Añadir campos extra si se pasaron
        if hasattr(record, "extra_fields"):
            log_record.update(record.extra_fields)
            
        return json.dumps(log_record, ensure_ascii=False)
