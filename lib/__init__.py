"""Shared library with runtime checks on subsequently imported submodules."""

from beartype import BeartypeConf
from beartype.claw import beartype_this_package

# Check function signatures; leave annotation-driven model fields to Pydantic.
# Keep decoration warnings visible so unchecked callables cannot fail silently.
beartype_this_package(conf=BeartypeConf(claw_is_pep526=False))
