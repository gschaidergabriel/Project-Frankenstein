"""Contacts integration mixin – Google Contacts via CardDAV.

Worker methods run on the IO thread (via _io_q dispatch in worker_mixin).
No polling needed (contacts change infrequently).
"""
from __future__ import annotations

import json
import re

from overlay.constants import LOG, FRANK_IDENTITY
from overlay.services.core_api import _core_chat
from overlay.services.toolbox import _toolbox_call


class ContactsMixin:
    """Google Contacts integration: list, search, create, delete contacts."""

    # ── Worker methods (IO thread) ──────────────────────────────────

    def _do_contacts_list_worker(self, voice: bool = False):
        """List all contacts, formatted via LLM."""
        self._ui_call(self._show_typing)

        try:
            result = _toolbox_call("/contacts/list", {}, timeout_s=15.0)
            if not result or not result.get("ok"):
                error = (result or {}).get("error", "Contacts unreachable")
                self._ui_call(self._hide_typing)
                self._ui_call(lambda e=error: self._add_message("Frank", f"Error: {e}", is_system=True))
                return

            contacts = result.get("contacts", [])
            if not contacts:
                self._ui_call(self._hide_typing)
                reply = "You have no saved contacts."
                if voice and hasattr(self, '_voice_respond'):
                    self._ui_call(lambda r=reply: self._voice_respond(r))
                else:
                    self._ui_call(lambda r=reply: self._add_message("Frank", r))
                return

            # Format contacts for display
            lines = []
            for c in contacts:
                name = c.get("name", "?")
                phones = ", ".join(c.get("phones", []))
                emails = ", ".join(c.get("emails", []))
                info = phones or emails or "(no data)"
                lines.append(f"  {name}: {info}")

            reply = f"Your contacts ({len(contacts)}):\n" + "\n".join(lines)

            self._ui_call(self._hide_typing)
            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda e=e: self._add_message("Frank", f"Contact error: {e}", is_system=True))

    def _do_contacts_search_worker(self, query: str = "", voice: bool = False):
        """Search contacts by name/phone/email."""
        self._ui_call(self._show_typing)

        try:
            result = _toolbox_call("/contacts/search", {"query": query}, timeout_s=15.0)
            if not result or not result.get("ok"):
                error = (result or {}).get("error", "Contacts unreachable")
                self._ui_call(self._hide_typing)
                self._ui_call(lambda e=error: self._add_message("Frank", f"Error: {e}", is_system=True))
                return

            contacts = result.get("contacts", [])
            if not contacts:
                self._ui_call(self._hide_typing)
                reply = f"No contact found for '{query}'."
                if voice and hasattr(self, '_voice_respond'):
                    self._ui_call(lambda r=reply: self._voice_respond(r))
                else:
                    self._ui_call(lambda r=reply: self._add_message("Frank", r))
                return

            lines = []
            for c in contacts:
                name = c.get("name", "?")
                phones = ", ".join(c.get("phones", []))
                emails = ", ".join(c.get("emails", []))
                org = c.get("org", "")
                parts = [f"  {name}:"]
                if phones:
                    parts.append(f"Tel: {phones}")
                if emails:
                    parts.append(f"Mail: {emails}")
                if org:
                    parts.append(f"Org: {org}")
                lines.append(" ".join(parts))

            reply = f"Found ({len(contacts)}):\n" + "\n".join(lines)

            self._ui_call(self._hide_typing)
            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda e=e: self._add_message("Frank", f"Contact error: {e}", is_system=True))

    def _do_contacts_create_worker(self, user_msg: str = "", voice: bool = False):
        """Create a contact by extracting details from user message via LLM."""
        self._ui_call(self._show_typing)

        try:
            extract_prompt = (
                f"Extract the contact details from the following message.\n\n"
                f"Message: \"{user_msg}\"\n\n"
                f"Reply ONLY with a JSON object (no explanation):\n"
                f"{{\n"
                f"  \"name\": \"First and last name\",\n"
                f"  \"phone\": \"Phone number or empty\",\n"
                f"  \"email\": \"E-mail or empty\",\n"
                f"  \"org\": \"Organization or empty\"\n"
                f"}}\n\n"
                f"Rules:\n"
                f"- Phone numbers in international format (+43, +49, +1, etc.)\n"
                f"- If no country recognizable: assume Austrian number (+43)\n"
                f"- 0664... becomes +43 664...\n"
                f"- Name is required, rest optional"
            )

            try:
                res = _core_chat(extract_prompt, max_tokens=200, timeout_s=30, task="chat.fast", force="llama")
                raw = (res.get("text") or "").strip() if res.get("ok") else ""
            except Exception:
                raw = ""

            if not raw:
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message("Frank", "Could not extract contact details. Please provide name and number.", is_system=True))
                return

            # Parse JSON
            json_text = raw
            if "```" in json_text:
                m = re.search(r"```(?:json)?\s*(.*?)```", json_text, re.DOTALL)
                if m:
                    json_text = m.group(1).strip()

            try:
                details = json.loads(json_text)
            except json.JSONDecodeError:
                m = re.search(r"\{[^}]+\}", raw, re.DOTALL)
                if m:
                    try:
                        details = json.loads(m.group())
                    except json.JSONDecodeError:
                        self._ui_call(self._hide_typing)
                        self._ui_call(lambda: self._add_message("Frank", "Could not understand contact details.", is_system=True))
                        return
                else:
                    self._ui_call(self._hide_typing)
                    self._ui_call(lambda: self._add_message("Frank", "Could not understand contact details.", is_system=True))
                    return

            name = str(details.get("name", "")).strip()
            phone = str(details.get("phone", "") or "").strip()
            email = str(details.get("email", "") or "").strip()
            org = str(details.get("org", "") or "").strip()

            if not name:
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message("Frank", "No name recognized. Please provide at least a name.", is_system=True))
                return

            LOG.info(f"Contacts create: name={name}, phone={phone}, email={email}")

            result = _toolbox_call("/contacts/create", {
                "name": name,
                "phone": phone,
                "email": email,
                "org": org,
            }, timeout_s=15.0)

            self._ui_call(self._hide_typing)

            if result and result.get("ok"):
                parts = [f"Contact saved: {name}"]
                if phone:
                    parts.append(f"Tel: {phone}")
                if email:
                    parts.append(f"Mail: {email}")
                reply = "\n".join(parts)
                LOG.info(f"Contact created via chat: {name}")
            else:
                error = (result or {}).get("error", "Unknown error")
                LOG.warning(f"Contact create failed: result={result}")
                reply = f"Could not create contact: {error}"

            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda e=e: self._add_message("Frank", f"Contact creation failed: {e}", is_system=True))

    def _do_contacts_delete_worker(self, query: str = "", user_msg: str = "", voice: bool = False):
        """Delete a contact by searching for it first."""
        self._ui_call(self._show_typing)

        try:
            # List all contacts to find match
            result = _toolbox_call("/contacts/list", {}, timeout_s=15.0)
            if not result or not result.get("ok"):
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message("Frank", "Could not fetch contacts.", is_system=True))
                return

            contacts = result.get("contacts", [])
            if not contacts:
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message("Frank", "No contacts to delete.", is_system=True))
                return

            # Search for matching contact
            search = (query or user_msg).lower()
            match = None
            for c in contacts:
                name = (c.get("name") or "").lower()
                if any(word in name for word in search.split() if len(word) > 2):
                    match = c
                    break

            if not match:
                lines = [f"  {i+1}. {c['name']}" for i, c in enumerate(contacts[:8])]
                reply = "Which contact should I delete?\n" + "\n".join(lines)
                self._ui_call(self._hide_typing)
                self._ui_call(lambda r=reply: self._add_message("Frank", r))
                return

            # Delete the matched contact
            uid = match.get("uid", "")
            del_result = _toolbox_call("/contacts/delete", {"uid": uid}, timeout_s=15.0)
            self._ui_call(self._hide_typing)

            if del_result and del_result.get("ok"):
                reply = f"Contact deleted: {match.get('name', '?')}"
                LOG.info(f"Contact deleted via chat: {match.get('name')}")
            else:
                error = (del_result or {}).get("error", "Unknown error")
                reply = f"Delete failed: {error}"

            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda e=e: self._add_message("Frank", f"Delete failed: {e}", is_system=True))

    def _do_contacts_general_worker(self, user_msg: str = "", voice: bool = False):
        """Handle general contact-related queries via LLM with contacts context."""
        self._ui_call(self._show_typing)

        try:
            # Get contacts for context
            contacts_result = _toolbox_call("/contacts/list", {}, timeout_s=10.0)
            ctx = ""
            if contacts_result and contacts_result.get("ok"):
                contacts = contacts_result.get("contacts", [])
                if contacts:
                    lines = [f"- {c.get('name', '?')}" for c in contacts]
                    ctx = f"Saved contacts ({len(contacts)}):\n" + "\n".join(lines)
                else:
                    ctx = "No contacts saved."

            prompt = (
                f"[Identity: {FRANK_IDENTITY}]\n\n"
                f"You have access to the user's Google Contacts.\n"
                f"Your contact commands:\n"
                f"- 'show my contacts' → List all contacts\n"
                f"- 'find contact Mom' → Search contact\n"
                f"- 'add contact Max 0664123456' → Create contact\n"
                f"- 'delete contact Test' → Delete contact\n\n"
                f"Current status:\n{ctx}\n\n"
                f"The user says: '{user_msg}'\n\n"
                f"Answer the question or point to the relevant command. "
                f"Reply briefly and helpfully."
            )

            try:
                res = _core_chat(prompt, max_tokens=300, timeout_s=60, task="chat.fast", force="llama")
                reply = (res.get("text") or "").strip() if res.get("ok") else "Could not process your contacts request."
            except Exception:
                reply = "Could not process your contacts request."

            self._ui_call(self._hide_typing)
            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda err=e: self._add_message("Frank", f"Contacts request failed: {err}", is_system=True))
