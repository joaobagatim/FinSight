"""Searches must not place private descriptions into HTTP access logs."""

import logging

from app.core.access_logging import QueryFreeAccessLog, install_access_log_privacy


def test_access_log_keeps_status_and_path_but_never_query_text():
    privacy = QueryFreeAccessLog()
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1",
            "GET",
            "/api/v1/transactions?q=synthetic-private-marker&offset=50",
            "1.1",
            200,
        ),
        None,
    )
    assert privacy.filter(record)
    assert record.getMessage() == '127.0.0.1 - "GET /api/v1/transactions HTTP/1.1" 200'
    unexpected = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, "synthetic-private-marker", (), None
    )
    assert not privacy.filter(unexpected)
    logger = logging.getLogger("uvicorn.access")
    previous = list(logger.filters)
    try:
        install_access_log_privacy()
        install_access_log_privacy()
        assert sum(isinstance(item, QueryFreeAccessLog) for item in logger.filters) == 1
    finally:
        logger.filters[:] = previous
