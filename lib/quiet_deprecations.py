"""Silence deprecation noise from third-party dependencies we do not control.

Two warnings show up on every import of the app stack:

* ``literalai`` (pulled in by chainlit) -> ``traceloop-sdk``, which still uses
  class-based Pydantic ``Config``.
* ``fastmcp`` 2.x's JWT auth provider imports the deprecated ``authlib.jose``
  module.

Neither is fixable from this codebase, and both are subclasses of
``DeprecationWarning``, so filtering by exact category keeps every other warning
- including anything our own code raises - visible.
"""

import warnings


def suppress_third_party_deprecations() -> list[str]:
    """Register the filters and return the categories that were suppressed."""
    suppressed = []
    for module_name, class_name in (
        ("pydantic", "PydanticDeprecatedSince20"),
        ("authlib.deprecate", "AuthlibDeprecationWarning"),
    ):
        try:
            module = __import__(module_name, fromlist=[class_name])
            category = getattr(module, class_name)
        except (ImportError, AttributeError):
            continue
        warnings.filterwarnings("ignore", category=category)
        suppressed.append(f"{module_name}.{class_name}")
    return suppressed
