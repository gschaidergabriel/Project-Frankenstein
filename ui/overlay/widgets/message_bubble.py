import re
import tkinter as tk
import webbrowser
from overlay.constants import COLORS, URL_REGEX, LOG
from overlay.widgets.action_button import ActionButton


# ── Markdown Parsing ─────────────────────────────────────────────

_CODE_BLOCK_RE = re.compile(r"```(?:\w*)\n?(.*?)```", re.DOTALL)
_CODE_INLINE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")


def _parse_markdown_segments(text: str, skip_markdown: bool = False):
    """Parse markdown into [(text, [tags]), ...] segments.

    Phases:
      1. Extract fenced code blocks (``` ... ```)
      2. Line-level: headings (#), bullets (- / *), blockquotes (>)
      3. Inline: `code`, **bold**, *italic*
    Returns flat list of (fragment, tag_list) tuples.
    """
    if skip_markdown:
        return [(text, ["normal"])]

    segments = []

    # ── Phase 1: extract code blocks ──
    parts = []
    last = 0
    for m in _CODE_BLOCK_RE.finditer(text):
        if m.start() > last:
            parts.append(("text", text[last:m.start()]))
        code = m.group(1).rstrip("\n")
        parts.append(("code_block", code))
        last = m.end()
    if last < len(text):
        parts.append(("text", text[last:]))
    if not parts:
        parts = [("text", text)]

    for kind, content in parts:
        if kind == "code_block":
            segments.append(("\n" + content + "\n", ["code_block"]))
            continue

        # ── Phase 2: line-level parsing ──
        lines = content.split("\n")
        for i, line in enumerate(lines):
            stripped = line.lstrip()

            # Headings
            if stripped.startswith("### "):
                _inline_parse(segments, stripped[4:], ["heading3"])
            elif stripped.startswith("## "):
                _inline_parse(segments, stripped[3:], ["heading2"])
            elif stripped.startswith("# "):
                _inline_parse(segments, stripped[2:], ["heading"])
            # Bullets (- item or * item, but not ** bold)
            elif re.match(r"^[-] ", stripped) or re.match(r"^\* (?!\*)", stripped):
                segments.append(("  \u2022 ", ["bullet"]))
                _inline_parse(segments, stripped[2:], ["bullet"])
            # Blockquotes
            elif stripped.startswith("> "):
                _inline_parse(segments, stripped[2:], ["blockquote"])
            else:
                _inline_parse(segments, line, [])

            # Add newline between lines (not after last)
            if i < len(lines) - 1:
                segments.append(("\n", []))

    return segments


def _inline_parse(segments, text, base_tags):
    """Phase 3: parse inline markdown (`code`, **bold**, *italic*) within a text fragment."""
    # Step 1: extract inline code first (protects inner content)
    parts = []
    last = 0
    for m in _CODE_INLINE_RE.finditer(text):
        if m.start() > last:
            parts.append(("text", text[last:m.start()]))
        parts.append(("code_inline", m.group(1)))
        last = m.end()
    if last < len(text):
        parts.append(("text", text[last:]))
    if not parts:
        parts = [("text", text)]

    for kind, content in parts:
        if kind == "code_inline":
            segments.append((content, base_tags + ["code_inline"]))
            continue

        # Step 2: bold (**...**)
        bold_parts = []
        blst = 0
        for m in _BOLD_RE.finditer(content):
            if m.start() > blst:
                bold_parts.append(("text", content[blst:m.start()]))
            bold_parts.append(("bold", m.group(1)))
            blst = m.end()
        if blst < len(content):
            bold_parts.append(("text", content[blst:]))
        if not bold_parts:
            bold_parts = [("text", content)]

        for bkind, bcontent in bold_parts:
            if bkind == "bold":
                # Check for italic inside bold
                _italic_parse(segments, bcontent, base_tags + ["bold"])
                continue

            # Step 3: italic (*...*)
            _italic_parse(segments, bcontent, base_tags)


def _italic_parse(segments, text, base_tags):
    """Parse *italic* within text and append segments."""
    last = 0
    for m in _ITALIC_RE.finditer(text):
        if m.start() > last:
            tags = base_tags + ["normal"] if not base_tags else base_tags
            segments.append((text[last:m.start()], tags or ["normal"]))
        segments.append((m.group(1), base_tags + ["italic"]))
        last = m.end()
    if last < len(text):
        tags = base_tags + ["normal"] if not base_tags else base_tags
        segments.append((text[last:], tags or ["normal"]))
    elif last == 0:
        tags = base_tags + ["normal"] if not base_tags else base_tags
        segments.append((text, tags or ["normal"]))


# ── MessageBubble Widget ─────────────────────────────────────────

class MessageBubble(tk.Frame):
    """Cyberpunk-styled chat message with selectable text and markdown rendering."""

    def __init__(self, parent, sender: str, message: str, is_user: bool = False,
                 is_system: bool = False, on_link_click=None,
                 on_retry=None, on_speak=None, on_do_this=None):
        super().__init__(parent, bg=COLORS["bg_chat"])

        self.on_link_click = on_link_click
        self.on_retry = on_retry
        self.on_speak = on_speak
        self.on_do_this = on_do_this
        self.message = message
        self._is_user = is_user

        # Determine colors and styling (cyberpunk theme)
        if is_system:
            bubble_bg = COLORS["bg_system"]
            text_color = COLORS["text_system"]
            border_color = COLORS["text_muted"]
            align = "w"
            sender_color = COLORS["text_muted"]
            sender_text = sender
            sender_icon = "\u25c6"
        elif is_user:
            bubble_bg = COLORS["bg_user_msg"]
            text_color = COLORS["text_user"]
            border_color = COLORS["neon_magenta"]
            align = "e"
            sender_color = COLORS["neon_magenta"]
            sender_text = "USER"
            sender_icon = "\u25b6"
        else:
            bubble_bg = COLORS["bg_ai_msg"]
            text_color = COLORS["text_ai"]
            border_color = COLORS["neon_cyan"]
            align = "w"
            sender_color = COLORS["neon_cyan"]
            sender_text = "FRANK"
            sender_icon = "\u25c0"

        # Container for alignment
        container = tk.Frame(self, bg=COLORS["bg_chat"])
        container.pack(fill="x", padx=8, pady=4)

        # Cyberpunk bubble: sharp edges with colored left border
        bubble = tk.Frame(container, bg=bubble_bg, padx=0, pady=0)
        bubble.pack(anchor=align, side="left" if align == "w" else "right", fill="x", expand=True)

        # Left border indicator (colored stripe)
        border_stripe = tk.Frame(bubble, bg=border_color, width=3)
        border_stripe.pack(side="left", fill="y")

        # Content area
        content = tk.Frame(bubble, bg=bubble_bg, padx=12, pady=8)
        content.pack(side="left", fill="both", expand=True)

        # Sender label with cyberpunk styling (monospace, uppercase)
        sender_label = tk.Label(
            content,
            text=f"{sender_icon} {sender_text}",
            bg=bubble_bg,
            fg=sender_color,
            font=("Consolas", 9, "bold"),
            anchor="w"
        )
        sender_label.pack(anchor="w", pady=(0, 4))

        # Message text - SELECTABLE with right-click copy + markdown rendering
        self._create_message_text(content, message, text_color, bubble_bg, border_color)

        # Action bar for Frank messages (not user, not system)
        if not is_user and not is_system:
            self._build_action_bar(content, bubble_bg)

    def _build_action_bar(self, parent, bg_color):
        """Add Copy / Retry / Speak / Do This action buttons below Frank's message."""
        bar = tk.Frame(parent, bg=bg_color)
        bar.pack(anchor="w", fill="x", pady=(4, 0))

        ActionButton(bar, "COPY", self._copy_all_message, icon="\u2398").pack(side="left", padx=(0, 2))

        if self.on_retry:
            ActionButton(bar, "RETRY", self.on_retry, icon="\u21bb").pack(side="left", padx=(0, 2))

        if self.on_speak:
            ActionButton(bar, "SPEAK", self.on_speak, icon="\u266a").pack(side="left", padx=(0, 2))

        if self.on_do_this:
            ActionButton(bar, "DO THIS", self.on_do_this, icon="\u25b6").pack(side="left", padx=(0, 2))

    def _copy_all_message(self):
        """Copy entire message to clipboard."""
        try:
            self.clipboard_clear()
            self.clipboard_append(self.message)
        except Exception:
            pass

    def _create_message_text(self, parent, message: str, text_color: str, bg_color: str, accent_color: str = None):
        """Create SELECTABLE message text with markdown rendering, clickable links, and copy support."""
        # Char-based initial estimate (works before widget is packed/laid out)
        num_lines = max(1, len(message) // 32 + message.count('\n') + 1)

        text_widget = tk.Text(
            parent,
            bg=bg_color,
            fg=text_color,
            font=("Consolas", 10),
            wrap="word",
            relief="flat",
            cursor="xterm",
            padx=0,
            pady=0,
            height=num_lines,
            borderwidth=0,
            highlightthickness=0,
            selectbackground=accent_color or COLORS["accent"],
            selectforeground=COLORS["bg_main"],
        )
        text_widget.pack(anchor="w", fill="both", expand=True)

        # ── Configure tags (base + markdown) ──
        text_widget.tag_configure("normal", foreground=text_color)
        text_widget.tag_configure("link", foreground=COLORS["link"], underline=True)
        # Markdown tags
        text_widget.tag_configure("bold", foreground=text_color, font=("Consolas", 10, "bold"))
        text_widget.tag_configure("italic", foreground="#b0b0c0", font=("Consolas", 10, "italic"))
        text_widget.tag_configure("code_inline",
                                  foreground=COLORS["neon_yellow"],
                                  background="#1a1a25",
                                  font=("Consolas", 10))
        text_widget.tag_configure("code_block",
                                  foreground=COLORS["neon_yellow"],
                                  background="#12121a",
                                  font=("Consolas", 9),
                                  lmargin1=20, lmargin2=20, rmargin=10,
                                  spacing1=4, spacing3=4)
        text_widget.tag_configure("heading",
                                  foreground=COLORS["neon_cyan"],
                                  font=("Consolas", 12, "bold"),
                                  spacing1=4, spacing3=2)
        text_widget.tag_configure("heading2",
                                  foreground=COLORS["neon_cyan"],
                                  font=("Consolas", 11, "bold"),
                                  spacing1=3, spacing3=2)
        text_widget.tag_configure("heading3",
                                  foreground=COLORS["neon_cyan"],
                                  font=("Consolas", 10, "bold"),
                                  spacing1=2, spacing3=1)
        text_widget.tag_configure("bullet",
                                  foreground=text_color,
                                  lmargin1=16, lmargin2=24)
        text_widget.tag_configure("blockquote",
                                  foreground=COLORS["text_muted"],
                                  background="#0f0f18",
                                  lmargin1=16, lmargin2=16)

        # ── Parse markdown and insert segments ──
        segments = _parse_markdown_segments(message, skip_markdown=self._is_user)
        link_count = 0

        for seg_text, seg_tags in segments:
            is_code = "code_block" in seg_tags or "code_inline" in seg_tags

            # URLs inside code should NOT be linkified
            if not is_code and URL_REGEX.search(seg_text):
                link_count = self._insert_with_urls(
                    text_widget, seg_text, seg_tags, link_count)
            else:
                tags = tuple(seg_tags) if seg_tags else ("normal",)
                text_widget.insert("end", seg_text, tags)

        # ── Height management ──
        text_widget.configure(height=num_lines)

        def _remeasure_height():
            try:
                dl = text_widget.count("1.0", "end", "displaylines")
                if dl:
                    h = dl[0] if isinstance(dl, tuple) else dl
                    h = max(1, h)
                    if h != num_lines:
                        text_widget.configure(height=h)
            except (tk.TclError, Exception):
                pass
        text_widget.after(50, _remeasure_height)

        # IMPORTANT: Keep text selectable but not editable
        text_widget.configure(state="disabled")

        # Re-enable selection in disabled state
        text_widget.bind("<Button-1>", lambda e: self._enable_selection(text_widget))
        text_widget.bind("<B1-Motion>", lambda e: self._continue_selection(text_widget, e))
        text_widget.bind("<ButtonRelease-1>", lambda e: None)

        # Copy with Ctrl+C
        text_widget.bind("<Control-c>", lambda e: self._copy_selection(text_widget))
        text_widget.bind("<Control-C>", lambda e: self._copy_selection(text_widget))

        # Right-click context menu
        text_widget.bind("<Button-3>", lambda e: self._show_context_menu(text_widget, e))

        # Store reference
        self._text_widget = text_widget

    def _insert_with_urls(self, text_widget, text: str, base_tags: list, link_count: int) -> int:
        """Insert text with URL detection, applying base_tags to non-URL parts."""
        last_end = 0
        for match in URL_REGEX.finditer(text):
            # Text before URL
            if match.start() > last_end:
                tags = tuple(base_tags) if base_tags else ("normal",)
                text_widget.insert("end", text[last_end:match.start()], tags)

            # URL with link tag
            url = match.group(1)
            link_tag = f"link_{link_count}"
            text_widget.tag_configure(link_tag, foreground=COLORS["link"], underline=True)
            text_widget.insert("end", url, (link_tag,))

            text_widget.tag_bind(link_tag, "<Button-1>", lambda e, u=url: self._handle_link_click(u))
            text_widget.tag_bind(link_tag, "<Enter>", lambda e, t=link_tag: self._link_enter(text_widget, t))
            text_widget.tag_bind(link_tag, "<Leave>", lambda e, t=link_tag: self._link_leave(text_widget, t))

            last_end = match.end()
            link_count += 1

        # Remaining text after last URL
        if last_end < len(text):
            tags = tuple(base_tags) if base_tags else ("normal",)
            text_widget.insert("end", text[last_end:], tags)

        return link_count

    # ── Selection helpers ──

    def _enable_selection(self, widget):
        widget.configure(state="normal")
        widget.focus_set()
        widget.after(100, lambda: self._check_selection_state(widget))

    def _continue_selection(self, widget, event):
        widget.configure(state="normal")

    def _check_selection_state(self, widget):
        try:
            if widget.tag_ranges("sel"):
                widget.after(100, lambda: self._check_selection_state(widget))
            else:
                widget.configure(state="disabled")
        except tk.TclError:
            try:
                widget.configure(state="disabled")
            except tk.TclError:
                pass
        except Exception as e:
            LOG.debug(f"Selection state check error: {e}")
            try:
                widget.configure(state="disabled")
            except tk.TclError:
                pass

    def _copy_selection(self, widget):
        try:
            widget.configure(state="normal")
            selected = widget.get("sel.first", "sel.last")
            if selected:
                widget.clipboard_clear()
                widget.clipboard_append(selected)
            widget.configure(state="disabled")
        except tk.TclError:
            pass
        return "break"

    def _show_context_menu(self, widget, event):
        menu = tk.Menu(widget, tearoff=0,
                      bg=COLORS["bg_elevated"],
                      fg=COLORS["text_primary"],
                      activebackground=COLORS["accent"],
                      activeforeground=COLORS["bg_main"],
                      font=("Consolas", 10))

        has_selection = False
        try:
            widget.get("sel.first", "sel.last")
            has_selection = True
        except tk.TclError:
            pass

        if has_selection:
            menu.add_command(label="\u25b8 COPY SELECTION", command=lambda: self._copy_selection(widget))
        menu.add_command(label="\u25b8 COPY ALL", command=lambda: self._copy_all(widget))

        menu.tk_popup(event.x_root, event.y_root)

    def _copy_all(self, widget):
        widget.configure(state="normal")
        all_text = widget.get("1.0", "end-1c")
        widget.clipboard_clear()
        widget.clipboard_append(all_text)
        widget.configure(state="disabled")

    def _link_enter(self, widget, tag):
        widget.tag_configure(tag, foreground=COLORS["link_hover"])
        widget.configure(cursor="hand2")

    def _link_leave(self, widget, tag):
        widget.tag_configure(tag, foreground=COLORS["link"])
        widget.configure(cursor="arrow")

    def _handle_link_click(self, url):
        if self.on_link_click:
            self.on_link_click(url)
        else:
            webbrowser.open(url)
