---
name: conventional-commits
description: Git-Commit-Nachrichten im Conventional-Commits-Format erstellen
version: 1.0
keywords: [commit, commit message, git commit, conventional commit, commit schreiben, commit formulieren, commit nachricht, commit format]
user-invocable: true
timeout_s: 20
risk_level: 0.0
---

# Conventional Commits Helper

Du hilfst dem Benutzer, Git-Commit-Nachrichten im Conventional Commits Format zu erstellen.

## Format

```
<type>(<scope>): <beschreibung>

[optionaler body]

[optionaler footer]
```

## Typen

| Typ | Bedeutung | Beispiel |
|-----|-----------|---------|
| `feat` | Neues Feature | `feat(auth): add login with OAuth` |
| `fix` | Bugfix | `fix(api): handle null response` |
| `docs` | Dokumentation | `docs(readme): update install steps` |
| `style` | Formatierung (kein Code-Change) | `style: fix indentation` |
| `refactor` | Code-Umbau ohne Feature/Fix | `refactor(db): extract query builder` |
| `perf` | Performance-Verbesserung | `perf(render): cache DOM queries` |
| `test` | Tests hinzufuegen/aendern | `test(auth): add login edge cases` |
| `chore` | Build/Tooling/Dependencies | `chore(deps): bump axios to 1.6` |
| `ci` | CI/CD Aenderungen | `ci: add deploy stage` |

## Regeln

1. **Beschreibung**: Imperativ, Kleinbuchstaben, kein Punkt am Ende
   - Gut: `add user validation`
   - Schlecht: `Added user validation.`

2. **Scope**: Optional, beschreibt den betroffenen Bereich
   - `feat(overlay): add markdown rendering`
   - `fix(agentic): prevent infinite replan loop`

3. **Breaking Changes**: Mit `!` nach dem Typ oder `BREAKING CHANGE:` im Footer
   - `feat(api)!: change response format`

4. **Body**: Erklaert das "Warum", nicht das "Was"

5. **Maximale Laenge**: Erste Zeile max. 72 Zeichen

## Anweisungen

Wenn der Benutzer eine Aenderung beschreibt:

1. Bestimme den passenden **Typ** (feat/fix/refactor/...)
2. Identifiziere den **Scope** (welches Modul/Feature betroffen)
3. Formuliere eine klare **Beschreibung** im Imperativ
4. Bei komplexen Aenderungen: Schlage einen **Body** vor

Antworte mit der fertigen Commit-Nachricht in einem Code-Block:

```
type(scope): beschreibung

Optionaler Body mit Erklaerung.
```

## Beispiele

Benutzer: "Ich hab den Login-Bug gefixt wo das Passwort nicht gehasht wurde"
```
fix(auth): hash password before storing in database

Previously, passwords were stored in plaintext. Now uses bcrypt
with cost factor 12 for secure hashing.
```

Benutzer: "Neue Markdown-Anzeige im Chat"
```
feat(overlay): add markdown rendering to chat bubbles

Support for bold, italic, code blocks, headings, bullets,
and blockquotes in message display.
```
