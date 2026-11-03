import logging


class _Logger:
    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def _log(self, level: int, event: str, exc_info: bool = False, **fields) -> None:
        if fields:
            self._logger.log(level, "%s %s", event, fields, exc_info=exc_info)
            return
        self._logger.log(level, event, exc_info=exc_info)

    def debug(self, event: str, **fields) -> None:
        self._log(logging.DEBUG, event, **fields)

    def info(self, event: str, **fields) -> None:
        self._log(logging.INFO, event, **fields)

    def warning(self, event: str, **fields) -> None:
        self._log(logging.WARNING, event, **fields)

    def error(self, event: str, exc_info: bool = False, **fields) -> None:
        self._log(logging.ERROR, event, exc_info=exc_info, **fields)


def get_logger(name: str) -> _Logger:
    return _Logger(name)
