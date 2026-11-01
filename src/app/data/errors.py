"""Typed failure for every reader: a header, unit or format that differs from what the data promised."""


class SourceError(RuntimeError):
    pass
