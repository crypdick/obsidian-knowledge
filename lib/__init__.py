"""obsidian-knowledge shared library package.

beartype is activated here, at the top of the package's root __init__, before any
submodule import. beartype_this_package() installs an import hook that wraps every
function in lib.* with runtime type checks -- no per-function decorators needed.
See skills/strictify beartype-setup.md for the rationale behind each option.
"""

import warnings

from beartype import BeartypeConf
from beartype.claw import beartype_this_package
from beartype.roar import BeartypeClawDecorWarning

# Functions beartype cannot instrument (complex decorators) degrade to a warning
# instead of failing the import; silence those. claw_is_pep526=False checks only
# function signatures, not annotated variable assignments -- required so beartype
# does not conflict with pydantic's annotation-driven field definitions.
warnings.filterwarnings("ignore", category=BeartypeClawDecorWarning)

beartype_this_package(
    conf=BeartypeConf(
        claw_is_pep526=False,
        warning_cls_on_decorator_exception=BeartypeClawDecorWarning,
    )
)
