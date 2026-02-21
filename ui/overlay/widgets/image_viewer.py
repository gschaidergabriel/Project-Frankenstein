import os
import tkinter as tk
from overlay.constants import COLORS, LOG


class ImageViewer(tk.Toplevel):
    """Fullscreen/popup image viewer with cyberpunk styling.

    Opens next to the overlay if there's space, otherwise on top.
    Closes on click, Escape, or closing the window.
    """

    def __init__(self, parent, image_path: str, overlay_geometry: str = None):
        super().__init__(parent)

        self.image_path = image_path
        self.original_image = None
        self.photo_image = None
        self._overlay_geometry = overlay_geometry

        # Frameless, dark window
        self.overrideredirect(True)
        self.configure(bg=COLORS["bg_deep"])
        self.attributes("-topmost", True)

        try:
            self.attributes("-alpha", 0.98)
        except Exception:
            pass

        # Load image safely
        if not self._load_image():
            self.destroy()
            return

        # Position window
        self._position_window()

        # Build UI
        self._build_ui()

        # Bindings for closing (with event stopping to prevent propagation to parent)
        self.bind("<Button-1>", self._close_viewer)
        self.bind("<Escape>", self._close_viewer)
        self.bind("<Button-3>", self._close_viewer)  # Right click also closes
        self.focus_set()

        # Grab focus to catch Escape (delayed — window must be mapped first)
        self.after(50, self._try_grab)

    def _try_grab(self):
        """Attempt grab_set after window is mapped."""
        try:
            self.grab_set()
        except tk.TclError:
            # Window not viewable yet, retry once more
            self.after(100, lambda: self.grab_set() if self.winfo_exists() else None)

    def _close_viewer(self, event=None):
        """Close the viewer and stop event propagation."""
        self.destroy()
        return "break"  # CRITICAL: Stop event from propagating to parent overlay

    def _load_image(self) -> bool:
        """Load image from path. Returns False if failed."""
        try:
            from PIL import Image, ImageTk

            if not os.path.exists(self.image_path):
                LOG.warning(f"ImageViewer: File not found: {self.image_path}")
                return False

            self.original_image = Image.open(self.image_path)
            # Convert to RGB if necessary (for PNG with transparency)
            if self.original_image.mode in ('RGBA', 'LA', 'P'):
                bg = Image.new('RGB', self.original_image.size, COLORS["bg_deep"])
                if self.original_image.mode == 'P':
                    self.original_image = self.original_image.convert('RGBA')
                bg.paste(self.original_image, mask=self.original_image.split()[-1] if self.original_image.mode == 'RGBA' else None)
                self.original_image = bg
            elif self.original_image.mode != 'RGB':
                self.original_image = self.original_image.convert('RGB')

            return True
        except Exception as e:
            LOG.error(f"ImageViewer: Failed to load image: {e}")
            return False

    def _position_window(self):
        """Position viewer next to overlay or fullscreen."""
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        img_width, img_height = self.original_image.size

        # Parse overlay geometry if available
        overlay_x, overlay_y, overlay_w = 0, 0, 0
        if self._overlay_geometry:
            try:
                # Format: "WxH+X+Y" or "WxH-X+Y" etc
                import re
                match = re.match(r'(\d+)x(\d+)([+-])(\d+)([+-])(\d+)', self._overlay_geometry)
                if match:
                    overlay_w = int(match.group(1))
                    overlay_x = int(match.group(4)) if match.group(3) == '+' else -int(match.group(4))
                    overlay_y = int(match.group(6)) if match.group(5) == '+' else -int(match.group(6))
            except Exception:
                pass

        # Calculate available space next to overlay
        space_right = screen_width - (overlay_x + overlay_w + 20)
        space_left = overlay_x - 20

        # Determine max size (leave margin)
        margin = 40

        # Check if overlay is fullscreen (takes most of screen)
        is_fullscreen = overlay_w > screen_width * 0.8

        if is_fullscreen:
            # Viewer covers entire screen
            max_width = screen_width - margin * 2
            max_height = screen_height - margin * 2
            viewer_x = margin
            viewer_y = margin
        elif space_right > 400:
            # Place to the right of overlay
            max_width = min(space_right - margin, screen_width // 2)
            max_height = screen_height - margin * 2
            viewer_x = overlay_x + overlay_w + 20
            viewer_y = margin
        elif space_left > 400:
            # Place to the left of overlay
            max_width = min(space_left - margin, screen_width // 2)
            max_height = screen_height - margin * 2
            viewer_x = margin
            viewer_y = margin
        else:
            # Place centered on screen (overlay is in middle)
            max_width = screen_width - margin * 2
            max_height = screen_height - margin * 2
            viewer_x = margin
            viewer_y = margin

        # Scale image to fit
        scale = min(max_width / img_width, max_height / img_height, 1.0)
        new_width = int(img_width * scale)
        new_height = int(img_height * scale)

        # Center within available space
        if not is_fullscreen and space_right > 400:
            viewer_x = overlay_x + overlay_w + 20 + (max_width - new_width) // 2
        elif not is_fullscreen and space_left > 400:
            viewer_x = margin + (max_width - new_width) // 2
        else:
            viewer_x = (screen_width - new_width) // 2

        viewer_y = (screen_height - new_height) // 2

        # Store dimensions for UI building
        self._display_width = new_width
        self._display_height = new_height

        # Add border space
        border = 4
        self.geometry(f"{new_width + border*2}x{new_height + border*2}+{viewer_x - border}+{viewer_y - border}")

    def _build_ui(self):
        """Build the viewer UI with cyberpunk styling."""
        from PIL import Image, ImageTk

        # Outer border (neon glow effect)
        border_frame = tk.Frame(self, bg=COLORS["neon_cyan"], padx=2, pady=2)
        border_frame.pack(fill="both", expand=True)

        # Inner container
        inner_frame = tk.Frame(border_frame, bg=COLORS["bg_deep"])
        inner_frame.pack(fill="both", expand=True)

        # Scale image
        scaled_image = self.original_image.resize(
            (self._display_width, self._display_height),
            Image.Resampling.LANCZOS
        )
        self.photo_image = ImageTk.PhotoImage(scaled_image)

        # Image label
        img_label = tk.Label(
            inner_frame,
            image=self.photo_image,
            bg=COLORS["bg_deep"],
            cursor="hand2"
        )
        img_label.pack(fill="both", expand=True)

        # Hint label at bottom
        hint = tk.Label(
            inner_frame,
            text="[ CLICK TO CLOSE ]",
            bg=COLORS["bg_deep"],
            fg=COLORS["text_muted"],
            font=("Consolas", 8)
        )
        hint.pack(side="bottom", pady=2)

        # Bind click on image
        img_label.bind("<Button-1>", lambda e: self.destroy())
