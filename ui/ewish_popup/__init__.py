#!/usr/bin/env python3
"""
E-WISH Popup Package
Cyberpunk-styled popup for Frank's autonomous wishes.
"""

from .main_window import (
    EWishPopupWindow,
    EWishPopupApp,
    show_wish_popup,
)

__all__ = [
    "EWishPopupWindow",
    "EWishPopupApp",
    "show_wish_popup",
]

__version__ = "1.0.0"
