"""Calculator/Converter mixin – unit and currency conversion.

Worker methods run on the IO thread (via _io_q dispatch in worker_mixin).
No toolbox call needed — imports converter.py directly.
No polling needed.
"""
from __future__ import annotations

import sys

from overlay.constants import LOG

# Ensure tools/ is importable
try:
    from config.paths import TOOLS_DIR as _TOOLS_DIR
except ImportError:
    from pathlib import Path as _Path
    _TOOLS_DIR = _Path(__file__).resolve().parents[3] / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


class CalculatorMixin:
    """Unit and currency conversion via chat."""

    def _do_convert_worker(self, user_msg: str = "", value: float = 0,
                           from_unit: str = "", to_unit: str = "", voice: bool = False):
        """Perform unit or currency conversion."""
        try:
            from converter import convert, convert_units, convert_currency, _normalize_unit, _is_currency

            fu = _normalize_unit(from_unit)
            tu = _normalize_unit(to_unit)

            # Determine currency vs unit
            fu_is_cur = _is_currency(fu)
            tu_is_cur = _is_currency(tu)

            if fu_is_cur and tu_is_cur:
                self._ui_call(self._show_typing)
                result = convert_currency(value, from_unit, to_unit)
                self._ui_call(self._hide_typing)
            elif fu_is_cur or tu_is_cur:
                result = {"error": f"Cannot convert {from_unit} to {to_unit} (unit/currency mismatch)"}
            else:
                result = convert_units(value, from_unit, to_unit)

            if result.get("ok"):
                reply = result["formatted"]
                LOG.info(f"Conversion: {reply}")
            else:
                # Fallback: try high-level convert with full message
                result2 = convert(user_msg)
                if result2.get("ok"):
                    reply = result2["formatted"]
                    LOG.info(f"Conversion (fallback): {reply}")
                else:
                    reply = f"Conversion failed: {result.get('error', 'Unknown units')}"

            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            LOG.error(f"Converter error: {e}", exc_info=True)
            self._ui_call(lambda e=e: self._add_message("Frank", f"Conversion error: {e}", is_system=True))
