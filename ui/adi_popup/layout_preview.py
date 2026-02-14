#!/usr/bin/env python3
"""
ADI Layout Preview Generator - ASCII art visualization.

Creates proportionally scaled ASCII art representations of
the desktop layout for visual preview in the ADI popup.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class PreviewConfig:
    """Configuration for preview generation."""
    width: int = 52       # Preview width in characters
    height: int = 20      # Preview height in lines
    show_dimensions: bool = True
    show_labels: bool = True


def generate_preview(
    monitor_width: int,
    monitor_height: int,
    frank_layout: Dict[str, Any],
    app_zone: Optional[Dict[str, Any]] = None,
    config: Optional[PreviewConfig] = None
) -> str:
    """
    Generate ASCII art preview of the layout.

    Args:
        monitor_width: Monitor width in pixels
        monitor_height: Monitor height in pixels
        frank_layout: Dict with x, y, width, height, font_size
        app_zone: Optional dict with x, y, width, height
        config: Preview configuration

    Returns:
        ASCII art string representing the layout
    """
    if config is None:
        config = PreviewConfig()

    # Calculate scale factors
    # Leave room for border (2 chars each side) and margins
    inner_width = config.width - 4
    inner_height = config.height - 4

    scale_x = inner_width / monitor_width
    scale_y = inner_height / monitor_height

    # Use uniform scale to maintain aspect ratio
    scale = min(scale_x, scale_y)

    # Scaled dimensions
    scaled_monitor_w = int(monitor_width * scale)
    scaled_monitor_h = int(monitor_height * scale)

    # Center the preview
    offset_x = (inner_width - scaled_monitor_w) // 2 + 2
    offset_y = (inner_height - scaled_monitor_h) // 2 + 2

    # Create grid
    grid = [[' ' for _ in range(config.width)] for _ in range(config.height)]

    # Draw monitor border
    _draw_box(
        grid,
        offset_x, offset_y,
        scaled_monitor_w, scaled_monitor_h,
        double_line=True
    )

    # Draw Frank window
    frank_x = int(frank_layout.get('x', 10) * scale) + offset_x
    frank_y = int(frank_layout.get('y', 38) * scale) + offset_y
    frank_w = max(8, int(frank_layout.get('width', 420) * scale))
    frank_h = max(4, int(frank_layout.get('height', 720) * scale))

    # Clamp to monitor bounds
    frank_w = min(frank_w, scaled_monitor_w - 4)
    frank_h = min(frank_h, scaled_monitor_h - 4)

    _draw_box(grid, frank_x + 1, frank_y + 1, frank_w, frank_h)

    # Add Frank label
    if config.show_labels and frank_w >= 8 and frank_h >= 4:
        _draw_text(grid, frank_x + 2, frank_y + 2, "FRANK")
        # Add dimensions
        size_str = f"{frank_layout.get('width', 420)}x{frank_layout.get('height', 720)}"
        if len(size_str) <= frank_w - 2:
            _draw_text(grid, frank_x + 2, frank_y + 3, size_str)
        # Add font size
        font_str = f"F:{frank_layout.get('font_size', 14)}"
        if frank_h >= 5 and len(font_str) <= frank_w - 2:
            _draw_text(grid, frank_x + 2, frank_y + 4, font_str)

    # Draw App Zone if provided
    if app_zone:
        app_x = int(app_zone.get('x', 440) * scale) + offset_x
        app_y = int(app_zone.get('y', 0) * scale) + offset_y
        app_w = max(10, int(app_zone.get('width', 1000) * scale))
        app_h = max(4, int(app_zone.get('height', 800) * scale))

        # Clamp to monitor bounds
        app_w = min(app_w, scaled_monitor_w - (app_x - offset_x) - 2)
        app_h = min(app_h, scaled_monitor_h - 2)

        if app_w > 4 and app_h > 2:
            _draw_box(grid, app_x + 1, app_y + 1, app_w, app_h)

            # Add App Zone label
            if config.show_labels and app_w >= 12 and app_h >= 4:
                _draw_text(grid, app_x + 2, app_y + 2, "APP ZONE")
                size_str = f"{app_zone.get('width', 1000)}x{app_zone.get('height', 800)}"
                if len(size_str) <= app_w - 2:
                    _draw_text(grid, app_x + 2, app_y + 3, size_str)

    # Convert grid to string
    lines = [''.join(row) for row in grid]

    # Add monitor info below
    if config.show_dimensions:
        info_line = f"{monitor_width} x {monitor_height}"
        padding = (config.width - len(info_line)) // 2
        lines.append(' ' * padding + info_line)

    return '\n'.join(lines)


def _draw_box(
    grid: list,
    x: int, y: int,
    width: int, height: int,
    double_line: bool = False
):
    """Draw a box on the grid, handling overlapping corners properly."""
    if double_line:
        h_line = '═'
        v_line = '║'
        tl = '╔'
        tr = '╗'
        bl = '╚'
        br = '╝'
    else:
        h_line = '─'
        v_line = '│'
        tl = '┌'
        tr = '┐'
        bl = '└'
        br = '┘'

    # Characters that should not be overwritten by new corners
    corner_chars = {'┌', '┐', '└', '┘', '╔', '╗', '╚', '╝', '├', '┤', '┬', '┴', '┼'}

    max_y = len(grid)
    max_x = len(grid[0]) if grid else 0

    # Clamp coordinates
    x = max(0, x)
    y = max(0, y)
    width = min(width, max_x - x)
    height = min(height, max_y - y)

    if width < 2 or height < 2:
        return

    def safe_set(row: int, col: int, char: str, is_corner: bool = False):
        """Set a character, respecting existing corners to prevent overlap glitch."""
        if 0 <= row < max_y and 0 <= col < max_x:
            existing = grid[row][col]
            if is_corner and existing in corner_chars:
                return  # Don't overwrite existing corners
            grid[row][col] = char

    # Top line
    safe_set(y, x, tl, is_corner=True)
    for i in range(1, width - 1):
        safe_set(y, x + i, h_line)
    safe_set(y, x + width - 1, tr, is_corner=True)

    # Side lines
    for j in range(1, height - 1):
        safe_set(y + j, x, v_line)
        safe_set(y + j, x + width - 1, v_line)

    # Bottom line
    safe_set(y + height - 1, x, bl, is_corner=True)
    for i in range(1, width - 1):
        safe_set(y + height - 1, x + i, h_line)
    safe_set(y + height - 1, x + width - 1, br, is_corner=True)


def _draw_text(grid: list, x: int, y: int, text: str):
    """Draw text on the grid."""
    max_y = len(grid)
    max_x = len(grid[0]) if grid else 0

    if y < 0 or y >= max_y:
        return

    for i, char in enumerate(text):
        if 0 <= x + i < max_x:
            grid[y][x + i] = char


def generate_comparison_preview(
    monitor_width: int,
    monitor_height: int,
    old_layout: Dict[str, Any],
    new_layout: Dict[str, Any],
) -> str:
    """
    Generate side-by-side comparison of two layouts.

    Args:
        monitor_width: Monitor width in pixels
        monitor_height: Monitor height in pixels
        old_layout: Previous frank_layout dict
        new_layout: New frank_layout dict

    Returns:
        ASCII art string showing both layouts
    """
    # Bug fix: Increased size from 25x12 to 32x14 for better visibility of differences
    config = PreviewConfig(width=32, height=14, show_dimensions=False)

    old_preview = generate_preview(
        monitor_width, monitor_height,
        old_layout, None, config
    )
    new_preview = generate_preview(
        monitor_width, monitor_height,
        new_layout, None, config
    )

    old_lines = old_preview.split('\n')
    new_lines = new_preview.split('\n')

    # Pad to same length
    max_lines = max(len(old_lines), len(new_lines))
    old_lines.extend([''] * (max_lines - len(old_lines)))
    new_lines.extend([''] * (max_lines - len(new_lines)))

    # Combine with arrow
    result = []
    result.append("       VORHER                             NACHHER")
    result.append("")

    for i, (old, new) in enumerate(zip(old_lines, new_lines)):
        arrow = " → " if i == max_lines // 2 else "   "
        result.append(f"{old:<32}{arrow}{new}")

    return '\n'.join(result)


# Quick test
if __name__ == "__main__":
    # Test with the mini HDMI monitor
    print("=== Layout Preview Test ===\n")

    # Small monitor (1024x600)
    frank_layout = {
        'x': 10,
        'y': 38,
        'width': 360,
        'height': 510,
        'font_size': 12,
    }

    app_zone = {
        'x': 380,
        'y': 0,
        'width': 634,
        'height': 552,
    }

    print("Small Monitor (1024x600):")
    print(generate_preview(1024, 600, frank_layout, app_zone))
    print()

    # Full HD monitor
    print("\nFull HD Monitor (1920x1080):")
    frank_layout_hd = {
        'x': 10,
        'y': 38,
        'width': 420,
        'height': 720,
        'font_size': 14,
    }
    app_zone_hd = {
        'x': 440,
        'y': 0,
        'width': 1470,
        'height': 1040,
    }
    print(generate_preview(1920, 1080, frank_layout_hd, app_zone_hd))

    # Comparison test
    print("\n=== Comparison Preview ===\n")
    old = {'x': 10, 'y': 38, 'width': 360, 'height': 510, 'font_size': 12}
    new = {'x': 10, 'y': 38, 'width': 400, 'height': 550, 'font_size': 14}
    print(generate_comparison_preview(1024, 600, old, new))
