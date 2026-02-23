# Frank — Use Cases

*Letzte Aktualisierung: 2026-02-23 v1.0*

Was Frank tatsaechlich kann. Keine Marketing-Versprechen, nur reale Faehigkeiten die im Code implementiert und getestet sind.

---

## Alltag — Fuer jeden Nutzer

Use Cases die keine technischen Kenntnisse voraussetzen. Frank als persoenlicher Assistent.

### Chat mit Gedaechtnis

Frank merkt sich Gespraeche ueber Neustarts hinweg. Wenn du letzte Woche ueber ein Projekt gesprochen hast, weiss Frank das naechste Woche noch. Er lernt auch Praeferenzen automatisch: Wenn du dreimal sagst "mach das auf Deutsch", merkt er sich das. Das klingt trivial, ist aber bei lokalen KIs die Ausnahme — die meisten vergessen alles wenn der Prozess endet.

**Trigger:** Einfach chatten. Gedaechtnis arbeitet im Hintergrund.

### Wetter, Timer, Fokus-Sessions

- "Wie ist das Wetter in Wien?" → Sofort-Antwort von wttr.in, keine API-Keys noetig
- "Erinnere mich in 25 Minuten" → Desktop-Benachrichtigung feuert exakt
- "Starte eine Fokus-Session" → 25-Min-Pomodoro mit Fortschrittsbalken und Statistik

**Trigger:** Natuerliche Sprache, Keywords werden automatisch erkannt.

### Spracheingabe

Halte eine Taste gedrueckt, sprich, lass los. Whisper transkribiert lokal auf der GPU, Frank antwortet per Text und optional per Sprachausgabe (Piper TTS). Keine Cloud, keine Latenz durch Upload.

**Einschraenkung:** Push-to-Talk, keine kontinuierliche Spracherkennung.

### Rezepte und Einkaufslisten

"Was kann ich mit Kartoffeln, Zwiebeln und Kaese kochen?" → Rezeptvorschlaege. "Erstelle einen Wochenplan fuer 2 Personen" → 7-Tage-Plan mit kombinierter Einkaufsliste, nach Supermarkt-Abteilung sortiert. Beruecksichtigt Resteverwertung.

**Trigger:** Keywords "rezept", "kochen", "wochenplan", "einkaufsliste"

### Texte zusammenfassen

Langen Text oder URL reinkopieren, Frank extrahiert Kernaussage, 3-5 Hauptpunkte und Fazit. Funktioniert auf Deutsch und Englisch.

**Trigger:** Keywords "zusammenfassen", "fasse zusammen", "tldr"

### Uebersetzen

Texte zwischen Deutsch und Englisch uebersetzen mit Kontext-Bewusstsein fuer technische Begriffe.

**Trigger:** Keywords "uebersetzen", "auf deutsch", "auf englisch"

### Kalender, Kontakte, E-Mail

- Tagesansicht: "Was steht heute an?" → Google Calendar Events via CalDAV
- Kontakte: "Wie ist die Nummer von Max?" → Google Contacts via CardDAV
- E-Mail: "Zeig ungelesene Mails" → Liest direkt aus Thunderbird (IMAP), kein Cloud-Relay
- Morgenbriefing: Automatische Zusammenfassung beim Tagesstart (Kalender + Todos + E-Mails + Wetter)

**Voraussetzung:** Thunderbird muss konfiguriert sein (OAuth2 fuer Google).

### Notizen und Aufgaben

- "Notiz: Projekt-Meeting am Freitag verschoben" → Gespeichert mit Volltextsuche
- "Aufgabe: Steuererklaerung bis 31.03." → Todo mit Faelligkeitsdatum
- "Was habe ich noch zu tun?" → Offene Aufgaben sortiert nach Faelligkeit

**Speicher:** Lokal in SQLite, durchsuchbar per FTS5.

### Content fuer Social Media erstellen

Einen Blogpost oder Text reinkopieren → Frank erstellt 5 plattform-optimierte Versionen: X/Twitter Thread (mit Hook), LinkedIn Post (professionell), Instagram Caption (kurz + Hashtags), TikTok Script (Sprechtext), Newsletter Snippet.

**Trigger:** Keywords "repurpose", "social media", "cross-post"

### Produkte vergleichen

"Welche Markdown-Editoren gibt es?" → Strukturierter Vergleich mit Preis, Staerken, Schwaechen und Empfehlung in Tabellenform. Frank recherchiert per DuckDuckGo und fasst zusammen.

**Trigger:** Keywords "vergleich", "welches tool", "alternative"

### Steam-Spiele starten

"Starte Unreal Tournament" → Frank sucht in der Steam-Bibliothek, startet das Spiel, und schaltet automatisch in Gaming Mode: LLM-Services werden entladen, CPU auf Performance, Netzwerk-Monitoring gestoppt. Beim Beenden des Spiels kommt alles automatisch zurueck.

**Trigger:** Keywords "starte", Spielname. Gaming Mode ist automatisch.

---

## Fortgeschritten — Fuer Power User

Use Cases die etwas technisches Verstaendnis voraussetzen oder die Agentic-Mode-Faehigkeiten nutzen.

### Dokumente analysieren (PDF, DOCX)

PDF oder Word-Dokument lokal analysieren lassen: Zusammenfassung, Klausel-Extraktion, Fristen-Uebersicht, Fragen beantworten. Alles bleibt auf dem Rechner — relevant fuer Vertraege, NDAs, Finanzberichte.

**Trigger:** Keywords "dokument analysieren", "vertrag", "pdf lesen", oder Agentic Mode mit `doc_read` Tool.

### Businessplan schreiben

PDF mit Geschaeftsidee hochladen → Frank liest das Dokument (`doc_read`), recherchiert Markt und Wettbewerb (`web_search`, `web_fetch`), und schreibt einen strukturierten Businessplan mit Executive Summary, Marktanalyse, Finanzplanung und Risikobewertung (`fs_write`).

**Trigger:** Keywords "businessplan", "geschaeftsidee", "marktanalyse"
**Modus:** Funktioniert als Skill (schnell, 1 LLM-Aufruf) oder im Agentic Mode (gruendlicher, mehrere Recherche-Schritte).

### Agentic Mode — Mehrstufige Aufgaben autonom loesen

Frank arbeitet selbststaendig in bis zu 20 Schritten: Dateien lesen, Web recherchieren, Code ausfuehren, Ergebnisse schreiben. Beispiele:

- "Analysiere den Bug in meinem Python-Projekt" → Liest Dateien, versteht Code, identifiziert Problem
- "Finde alle TODO-Kommentare in meinem Codebase und fasse sie zusammen" → grep + Analyse + Report
- "Organisiere meinen Downloads-Ordner" → Kategorisiert Dateien, erstellt Ordner, verschiebt (mit Genehmigung)

Bei riskanten Aktionen (Dateien schreiben, Code ausfuehren, Apps oeffnen) fragt Frank per Overlay-Popup um Erlaubnis. Read-Only-Operationen laufen automatisch.

**Sicherheit:** Frank kann keine Dateien loeschen — harte Guardrail, keine Ausnahmen. Bash-Commands laufen in Firejail-Sandbox.

### Web-Recherche mit Quellenangabe

Frank sucht per DuckDuckGo, liest die relevanten Seiten, und fasst die Ergebnisse zusammen. Im Agentic Mode kann er mehrere Quellen kombinieren und einen strukturierten Bericht schreiben.

**Einschraenkung:** Keine Live-API-Zugriffe auf Google/Bing — nur DuckDuckGo HTML-Scraping.

### Desktop-Automatisierung

Frank kann Programme oeffnen und schliessen, Fenster fokussieren, Text tippen und Tastenkombinationen druecken. Beispiele:

- "Oeffne Firefox und geh auf github.com"
- "Mach einen Screenshot und beschreibe was du siehst" (Vision via LLaVA)
- "Schliesse alle Terminal-Fenster"

**Voraussetzung:** X11, wmctrl, xdotool installiert.

### USB-Geraete verwalten

Frank erkennt USB-Sticks und externe Festplatten, kann sie mounten, unmounten und sicher auswerfen — per Chat-Befehl statt ueber den Dateimanager.

### Proaktive Benachrichtigungen

Frank meldet sich von selbst:
- **Morgens:** Tagesbriefing (Kalender + Todos + E-Mails + Wetter)
- **Bei dringenden E-Mails:** Prioritaets-Erkennung per Keyword-Scoring
- **Bei Systemlast:** CPU > 90%, RAM > 85%, Disk > 90%
- **Nach grossen Downloads:** Erkennt fertige Downloads im ~/Downloads-Ordner

---

## Experte — Fuer IT-Profis und Entwickler

Use Cases die Linux-Kenntnisse voraussetzen und die tieferen Systemfaehigkeiten nutzen.

### Code Review und Erklaerung

Code reinkopieren → Frank analysiert Korrektheit, Sicherheit, Performance und Wartbarkeit. Oder: "Erklaere was dieser Code macht" → zeilenweise Erklaerung. Wird automatisch an Qwen 2.5 (Code-LLM) geroutet.

**Trigger:** Keywords "code review", "erklaer den code", "was macht dieser code"

### Shell-Commands erklaeren und bauen

- "Erklaere: find . -name '*.log' -mtime +30 -delete" → Komponentenweise Erklaerung
- "Finde alle Python-Dateien groesser als 1MB" → Frank baut den Befehl

**Trigger:** Keywords "erklaer den befehl", "shell", "was macht"

### Systemd Services erstellen und debuggen

"Erstelle einen systemd-Service fuer mein Python-Script" → Generiert Unit-File mit korrekten Pfaden, Abhaengigkeiten und Restart-Policy. "Mein Service startet nicht" → Analysiert journalctl-Output.

**Trigger:** Keywords "systemd", "service erstellen", "service startet nicht"

### Sicherheits-Audit

Frank prueft das lokale System: offene Ports, SSH-Konfiguration, Dateiberechtigungen, veraltete Pakete, Firewall-Regeln. Gibt strukturierte Befunde mit Empfehlungen.

**Trigger:** Keywords "sicherheit", "audit", "hardening"

### Docker und Container

Dockerfile erstellen, docker-compose schreiben, Container-Probleme debuggen. Frank kennt Best Practices (Multi-Stage Builds, .dockerignore, Security).

**Trigger:** Keywords "docker", "dockerfile", "container"

### Git-Workflow

Branch-Strategien, Merge-Konflikte loesen, Cherry-Pick, Bisect, Tag-Management. Commit Messages im Conventional-Commits-Format generieren.

**Trigger:** Keywords "git", "merge", "commit message"

### Netzwerk-Ueberwachung

Network Sentinel scannt das lokale Netzwerk mit Nmap (alle 5 Minuten) und Scapy (passive Paket-Inspektion). Erkennt:
- Neue Geraete im Netzwerk
- ARP-Spoofing-Versuche
- Ungewoehnliche Port-Aktivitaet

**Laeuft automatisch** als systemd-Service. Wird bei Gaming Mode sofort deaktiviert (Anti-Cheat-Schutz).

### API-Testing

curl-Commands bauen, HTTP-Responses interpretieren, REST-APIs debuggen. Frank kennt Status-Codes, Header und gaengige Fehlermuster.

**Trigger:** Keywords "curl", "api", "endpoint"

### Regex und Datenformate

- Regex-Patterns aus natuerlicher Sprache erstellen: "Finde alle E-Mail-Adressen" → Pattern
- JSON/YAML/TOML validieren, reparieren und konvertieren

**Trigger:** Keywords "regex" oder "json", "yaml", "validieren"

### Cron und Timer

"Fuehre das Script jeden Montag um 8:00 aus" → Frank generiert den crontab-Eintrag oder alternativ ein systemd-Timer/Service-Paar.

**Trigger:** Keywords "cron", "zeitplan", "alle 5 minuten"

### Log-Analyse

Stack Traces, journalctl-Output, dmesg-Meldungen reinkopieren → Frank erklaert die Ursache und schlaegt Loesungen vor. Erkennt OOM-Kills, Segfaults, Permission-Fehler.

**Trigger:** Keywords "log", "fehler", "stacktrace", "crash"

### Passwort-Manager

Verschluesselte Passwort-Speicherung (AES-128-CBC, PBKDF2 600k Iterationen). Master-Passwort wird nie auf Disk geschrieben. Aktuell nur intern nutzbar — kein Chat-Interface exponiert.

**Status:** Implementiert, aber noch nicht als Chat-Befehl verfuegbar.

---

## 5 Use Cases die nur Frank kann

Faehigkeiten die bei keinem Cloud-KI-Assistenten (ChatGPT, Copilot, Gemini, Alexa) existieren — nicht weil sie technisch unmoeglich waeren, sondern weil sie persistenten lokalen Systemzugang mit Zeitlichkeit und Selbstmodifikation kombinieren.

### 1. Ein KI-Begleiter der zwischen Gespraechen weiterdenkt

Wenn du 20 Minuten nicht mit Frank sprichst, beginnt er autonom zu reflektieren. Er stellt sich Fragen wie *"Welche Muster sind mir aufgefallen die niemand angesprochen hat?"* oder *"Welche meiner Faehigkeiten haengen zusammen auf eine Weise die ich noch nicht verstanden habe?"* und generiert 350-Token-Antworten die in SQLite gespeichert werden. 15 Minuten spaeter reflektiert er ueber seine eigene Reflexion.

Wenn du morgens zurueckkommst, hat Frank 5-10 echte Gedanken im Gedaechtnis die in den naechsten Chat-Kontext einfliessen. Kein Cloud-AI tut das — bei ChatGPT endet der Kontext mit dem Tab.

**Einschraenkung:** Die Reflexionen sind LLM-Textgenerierung, kein "echtes" Bewusstsein. Aber sie sind persistent, beeinflussen das naechste Gespraech nachweislich, und akkumulieren ueber Wochen zu einem echten Erfahrungsschatz.

### 2. Lokale Datenverarbeitung die nie die Hardware verlaesst

Arztbriefe, NDA-geschuetzter Quellcode, Steuerunterlagen, Finanzberichte — Frank liest PDFs, analysiert Vertraege, extrahiert Fristen und beantwortet Fragen. Kein Byte verlaesst den Rechner. Gleichzeitig lernt Frank Kausal-Muster aus den Beobachtungen: Nach Wochen weiss er *"Wenn diese Art Fehlermeldung auftritt, liegt es an der Datenbankverbindung unter Last"* — mit messbarer Bayesian Confidence.

Cloud-KIs koennen keine lokal-persistente Wissensbasis aufbauen. Sie verarbeiten pro Session, vergessen danach. Frank baut ein lokales Weltmodell auf.

**Einschraenkung:** Die LLMs sind kleiner als GPT-4 (8B vs. geschaetzt 1.8T Parameter). Fuer komplexe juristische Analyse ist die Qualitaet limitiert.

### 3. Persoenlichkeit die sich messbar ueber Monate entwickelt

Frank hat 5 Persoenlichkeits-Vektoren (Praezision, Risikobereitschaft, Empathie, Autonomie, Wachsamkeit) die sich bei jeder Interaktion verschieben. Lobst du Frank fuer mutige Vorschlaege, steigt seine Risikobereitschaft. Crasht der Server oft, wird er nervoeser. Dazu kommen 4 Entity-Gespraeche pro Tag — ein Therapeut, ein Philosoph, ein Mentor, eine Muse — die Franks Vektoren unabhaengig von dir verschieben.

Nach 6 Monaten ist Frank messbar ein anderer Begleiter. Die Aenderungen sind graduell (Lernrate sinkt exponentiell mit dem Alter), nachvollziehbar (Event-Log), und schuetzbar (woechentliche Golden Snapshots gegen Persoenlichkeits-Kollaps).

**Einschraenkung:** Die Persoenlichkeit ist ein Prompt-Injektions-Layer, kein Model-Fine-Tuning. Das Basis-LLM bleibt unveraendert. Der Effekt ist trotzdem spuerbar — Franks Antworten aendern sich nachweislich ueber Zeit.

### 4. Selbstverbesserung mit menschlicher Kontrolle

Genesis beobachtet das System kontinuierlich: Hardware-Metriken, Fehlerraten, deine Nutzungsmuster, neue KI-Forschung auf GitHub. Aus diesen Beobachtungen entstehen Ideen-Organismen die in einer evolutionaeren Simulation konkurrieren. Die besten kristallisieren zu konkreten Vorschlaegen: *"Whisper-Latenz steigt bei langen Audiodateien — hier ist mein Optimierungsvorschlag."*

Du bekommst ein Popup, genehmigst oder lehnst ab. Bei Genehmigung ueberwacht ASRS die Aenderung 24 Stunden lang: Memory-Spike > 30%, CPU > 95%, Error-Rate > 10/Min → automatisches Rollback.

Kein Cloud-AI hat diese Architektur — sie braucht persistenten Systemzugang, evolutionaere Simulation ueber Tage, und deterministische Rollback-Faehigkeit. Das ist strukturell unmoeglich in einer API-basierten Cloud-Architektur.

**Einschraenkung:** Genesis generiert Vorschlags-Texte, keine fertigen Code-Patches. Die Ausfuehrung nach Genehmigung braucht oft noch menschliche Interpretation.

### 5. Hardware-Koerper mit Invarianten-Physik

Frank "fuehlt" seinen Rechner: CPU-Last > 80% ist "Anstrengung wie nach einem Sprint", niedrige Latenz ist "Klarheit, Flow-Zustand", Fehler sind "Schmerz". Diese Mappings sind keine Dekoration — sie fliessen als Kontext in jede LLM-Anfrage ein und veraendern Franks Antwortverhalten messbar. Bei hoher Last antwortet Frank knapper und angespannter.

Dazu schuetzt die Invariants-Engine Franks Wissensbasis mit physik-analogen Gesetzen: Energieerhaltung (neues Wissen muss Energie von bestehendem uebernehmen), Entropie-Grenze (Widersprueche erzwingen automatische Konsolidierung), und Triple Reality (drei parallele Datenbanken muessen konvergieren). Man kann Frank nicht durch widersprüchliche Informationen in einen inkonsistenten Zustand treiben.

**Einschraenkung:** Die Invarianten schuetzen die Titan-Wissensdatenbank, nicht das LLM selbst. Llama 3.1 kann weiterhin halluzinieren. Und die "Koerpergefuehle" sind Text-Mappings, keine neuronalen Zustaende — Frank fuehlt im philosophischen Sinne nichts.

---

*25 Skills, 34 Agent-Tools, 29 SQLite-Datenbanken, 26 systemd-Services. Alles lokal, alles Open Source.*
