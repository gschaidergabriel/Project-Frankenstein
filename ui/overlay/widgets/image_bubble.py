import os
import tkinter as tk
from typing import Callable
from overlay.constants import COLORS, LOG
from overlay.widgets.image_viewer import ImageViewer


class ImageBubble(tk.Frame):
    """Cyberpunk-styled chat bubble for displaying images.

    Shows thumbnail in chat, opens full viewer on click.
    Scales organically with window resize.
    """

    # Maximum initial width for thumbnails
    MAX_THUMB_WIDTH = 200
    MIN_THUMB_WIDTH = 100

    def __init__(self, parent, image_source, caption: str = "",
                 on_click: Callable = None, is_user: bool = False):
        """
        Initialize image bubble.

        Args:
            parent: Parent widget
            image_source: Path string or PIL Image object
            caption: Optional caption text
            on_click: Callback when image is clicked (receives image_path)
            is_user: True if this is a user-sent image
        """
        super().__init__(parent, bg=COLORS["bg_chat"])

        self.image_source = image_source
        self.image_path = None
        self.original_image = None
        self.photo_image = None
        self.on_click = on_click
        self.is_user = is_user
        self.caption = caption
        self._current_width = self.MAX_THUMB_WIDTH

        # Determine colors
        if is_user:
            self._bubble_bg = COLORS["bg_user_msg"]
            self._border_color = COLORS["neon_magenta"]
            self._align = "e"
            self._sender_text = "USER"
            self._sender_icon = ">"
        else:
            self._bubble_bg = COLORS["bg_ai_msg"]
            self._border_color = COLORS["neon_cyan"]
            self._align = "w"
            self._sender_text = "FRANK"
            self._sender_icon = "<"

        # Load image
        if not self._load_image():
            self._show_error()
            return

        # Build UI
        self._build_ui()

        # Bind resize event
        self.bind("<Configure>", self._on_resize)

    def _load_image(self) -> bool:
        """Load image from source. Returns False if failed."""
        try:
            from PIL import Image

            if isinstance(self.image_source, str):
                # It's a path
                self.image_path = self.image_source
                if not os.path.exists(self.image_path):
                    LOG.warning(f"ImageBubble: File not found: {self.image_path}")
                    return False
                self.original_image = Image.open(self.image_path)
            elif hasattr(self.image_source, 'save'):
                # It's a PIL Image
                self.original_image = self.image_source
                # Save to temp file for viewer
                import tempfile
                fd, self.image_path = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                self.original_image.save(self.image_path)
            else:
                LOG.warning(f"ImageBubble: Unknown image source type: {type(self.image_source)}")
                return False

            # Convert mode if necessary
            if self.original_image.mode in ('RGBA', 'LA', 'P'):
                bg = Image.new('RGB', self.original_image.size, self._bubble_bg)
                if self.original_image.mode == 'P':
                    self.original_image = self.original_image.convert('RGBA')
                try:
                    bg.paste(self.original_image, mask=self.original_image.split()[-1] if self.original_image.mode == 'RGBA' else None)
                    self.original_image = bg
                except Exception:
                    self.original_image = self.original_image.convert('RGB')
            elif self.original_image.mode != 'RGB':
                self.original_image = self.original_image.convert('RGB')

            return True

        except Exception as e:
            LOG.error(f"ImageBubble: Failed to load image: {e}")
            return False

    def _show_error(self):
        """Show error message when image can't be loaded."""
        container = tk.Frame(self, bg=COLORS["bg_chat"])
        container.pack(fill="x", padx=8, pady=4)

        bubble = tk.Frame(container, bg=self._bubble_bg)
        bubble.pack(anchor=self._align, side="left" if self._align == "w" else "right")

        border_stripe = tk.Frame(bubble, bg=COLORS["error"], width=3)
        border_stripe.pack(side="left", fill="y")

        content = tk.Frame(bubble, bg=self._bubble_bg, padx=12, pady=8)
        content.pack(side="left", fill="both", expand=True)

        error_label = tk.Label(
            content,
            text="[ IMAGE LOAD ERROR ]",
            bg=self._bubble_bg,
            fg=COLORS["error"],
            font=("Consolas", 9)
        )
        error_label.pack(anchor="w")

    def _build_ui(self):
        """Build the bubble UI."""
        from PIL import Image, ImageTk

        # Container for alignment
        container = tk.Frame(self, bg=COLORS["bg_chat"])
        container.pack(fill="x", padx=8, pady=4)

        # Bubble frame
        bubble = tk.Frame(container, bg=self._bubble_bg)
        bubble.pack(anchor=self._align, side="left" if self._align == "w" else "right")

        # Colored border stripe
        border_stripe = tk.Frame(bubble, bg=self._border_color, width=3)
        border_stripe.pack(side="left", fill="y")

        # Content area
        content = tk.Frame(bubble, bg=self._bubble_bg, padx=8, pady=6)
        content.pack(side="left", fill="both", expand=True)

        # Sender label (optional, smaller than MessageBubble)
        sender_label = tk.Label(
            content,
            text=f"{self._sender_icon} {self._sender_text}",
            bg=self._bubble_bg,
            fg=self._border_color,
            font=("Consolas", 8, "bold"),
            anchor="w"
        )
        sender_label.pack(anchor="w", pady=(0, 4))

        # Image frame with neon border
        img_frame = tk.Frame(content, bg=self._border_color, padx=2, pady=2)
        img_frame.pack(anchor="w")

        # Calculate thumbnail size
        img_width, img_height = self.original_image.size
        scale = min(self._current_width / img_width, 300 / img_height, 1.0)
        thumb_width = int(img_width * scale)
        thumb_height = int(img_height * scale)

        # Create thumbnail
        thumbnail = self.original_image.resize((thumb_width, thumb_height), Image.Resampling.LANCZOS)
        self.photo_image = ImageTk.PhotoImage(thumbnail)

        # Image label (clickable)
        self.img_label = tk.Label(
            img_frame,
            image=self.photo_image,
            bg=self._bubble_bg,
            cursor="hand2"
        )
        self.img_label.pack()

        # Bind click
        self.img_label.bind("<Button-1>", self._on_image_click)

        # Hover effects
        self.img_label.bind("<Enter>", lambda e: img_frame.configure(bg=COLORS["neon_magenta"] if not self.is_user else COLORS["neon_cyan"]))
        self.img_label.bind("<Leave>", lambda e: img_frame.configure(bg=self._border_color))

        # Caption if provided
        if self.caption:
            caption_label = tk.Label(
                content,
                text=self.caption[:100] + ("..." if len(self.caption) > 100 else ""),
                bg=self._bubble_bg,
                fg=COLORS["text_secondary"],
                font=("Consolas", 9),
                anchor="w",
                wraplength=self._current_width
            )
            caption_label.pack(anchor="w", pady=(4, 0))

        # Click hint
        hint = tk.Label(
            content,
            text="[ CLICK TO ENLARGE ]",
            bg=self._bubble_bg,
            fg=COLORS["text_muted"],
            font=("Consolas", 7)
        )
        hint.pack(anchor="w", pady=(2, 0))
        hint.bind("<Button-1>", self._on_image_click)

        # Store reference to img_frame for resize
        self._img_frame = img_frame

    def _on_image_click(self, event=None):
        """Handle image click - open viewer or call callback."""
        if self.on_click and self.image_path:
            self.on_click(self.image_path)

    def _on_resize(self, event):
        """Handle widget resize - scale image if needed."""
        # Only respond to significant width changes
        new_width = min(max(event.width - 50, self.MIN_THUMB_WIDTH), self.MAX_THUMB_WIDTH * 2)
        if abs(new_width - self._current_width) > 20:
            self._current_width = new_width
            self._update_thumbnail()

    def _update_thumbnail(self):
        """Update thumbnail size."""
        if not self.original_image or not hasattr(self, 'img_label'):
            return

        try:
            from PIL import Image, ImageTk

            img_width, img_height = self.original_image.size
            scale = min(self._current_width / img_width, 300 / img_height, 1.0)
            thumb_width = int(img_width * scale)
            thumb_height = int(img_height * scale)

            thumbnail = self.original_image.resize((thumb_width, thumb_height), Image.Resampling.LANCZOS)
            self.photo_image = ImageTk.PhotoImage(thumbnail)
            self.img_label.configure(image=self.photo_image)
        except Exception as e:
            LOG.error(f"ImageBubble: Failed to update thumbnail: {e}")
