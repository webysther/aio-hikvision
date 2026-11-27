"""Values named by a text, each with a numeric code that never changes."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Callable

_CODES: dict[type[CodedEnum], dict[str, int]] = {}
"""The code of each member of each :class:`CodedEnum`, by member name (see :func:`coded`)."""


class CodedEnum(StrEnum):
    """A value named by a text, with a numeric code given by :func:`coded`.

    The text is what the value is called (``"electric_lock"``); the code is a number a
    consumer can store or chart. A released code never changes and is never reused: a new
    value gets a new code (``tests/models/test_codes.py`` freezes them).
    """

    @property
    def code(self) -> int:
        """Return the numeric code of the value."""
        return _CODES[type(self)][self.name]

    @classmethod
    def from_code(cls, code: int) -> Self | None:
        """Return the value of a numeric code; None when no value has it."""
        return next((member for member in cls if member.code == code), None)


def coded[E: CodedEnum](**codes: int) -> Callable[[type[E]], type[E]]:
    """Give the members of a :class:`CodedEnum` their codes, by member name.

    Every member needs a code, and no two members share one::

        @coded(PRESENT=1, ABSENT=2, UNKNOWN=3)
        class Support(CodedEnum): ...
    """

    def decorate(cls: type[E]) -> type[E]:
        names = {member.name for member in cls}
        if set(codes) != names:
            msg = f"{cls.__name__}: the codes of {sorted(set(codes) ^ names)} are missing or unknown"
            raise TypeError(msg)
        if len(set(codes.values())) != len(codes):
            msg = f"{cls.__name__}: two values share a code"
            raise TypeError(msg)
        _CODES[cls] = dict(codes)
        return cls

    return decorate
