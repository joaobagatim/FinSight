"""Keep query strings, including financial search text, out of Uvicorn access logs."""

import logging


class QueryFreeAccessLog(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Unknown formats are suppressed rather than risking unredacted financial text.
        if (
            record.msg != '%s - "%s %s HTTP/%s" %d'
            or not isinstance(record.args, tuple)
            or len(record.args) != 5
            or not isinstance(record.args[2], str)
        ):
            return False
        client, method, target, version, status = record.args
        record.args = (client, method, target.partition("?")[0], version, status)
        return True


def install_access_log_privacy() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, QueryFreeAccessLog) for item in logger.filters):
        logger.addFilter(QueryFreeAccessLog())
