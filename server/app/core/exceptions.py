"""Исключения предметной области, в HTTP-ответы их переводит main.py."""


class HostNotFoundError(Exception):
    """Хост с таким id не найден."""


class NoSnapshotError(Exception):
    """У хоста ещё нет ни одного снимка, эталон принять не из чего."""
