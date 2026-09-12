"""Shared Nexacro/DOM JavaScript snippets, re-exported for this package.

JS_IS_VISIBLE and JS_SET_VALUE are canonically defined in
`browser.interaction` - they are generic DOM predicates, not actually
Nexacro-specific (they started life shared with N-ERP's SAP screens in
cdp_common.py), and browser/ must not depend on nexacro/ (see that
module's docstring for the import-cycle this direction avoids). This
module exists so code inside `nexacro/` can write `from .js_snippets
import JS_IS_VISIBLE` without reaching two packages up, and so a reader
of this package doesn't have to already know they live in `browser/`.
"""
from ..browser.interaction import JS_IS_VISIBLE, JS_SET_VALUE

__all__ = ["JS_IS_VISIBLE", "JS_SET_VALUE"]
