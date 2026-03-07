# concert-monitor

## Bachtrack-Monitor

Das Script `monitor.py` überwacht die Bachtrack-Seite für Sibelius-Events in NRW.  
Neue Events werden an einen Discord-Webhook gesendet.

Benötigte Umgebungsvariable:

- `DISCORD_WEBHOOK` – URL des Discord-Webhooks

## Gmail-Monitor („Ananas“ im Betreff)

Zusätzlich prüft dasselbe Script dein Gmail-Postfach per IMAP.  
Für jede **ungelesene** E-Mail in `INBOX`, deren Betreff das Keyword (Standard: `"Ananas"`) enthält, wird ebenfalls eine Nachricht an denselben Discord-Webhook gesendet.  
Die betroffenen Mails werden dabei als **gelesen** markiert, damit nicht bei jedem Lauf erneut eine Nachricht gesendet wird.

Benötigte Umgebungsvariablen:

- `GMAIL_USER` – deine Gmail-Adresse (z. B. `dein.name@gmail.com`)
- `GMAIL_PASSWORD` – App-Passwort für Gmail (nicht dein normales Login-Passwort)
- `GMAIL_SUBJECT_KEYWORD` – optional, Standard ist `"Ananas"`

### Gmail App-Passwort einrichten (empfohlen)

1. In deinem Google-Account 2FA aktivieren (falls noch nicht geschehen).  
2. Unter „Sicherheit“ → „App-Passwörter“ ein neues App-Passwort für „Mail“ erstellen.  
3. Das generierte 16-stellige Passwort als `GMAIL_PASSWORD` verwenden.

### Ausführung

Das Script kann z. B. periodisch per Task Scheduler (Windows) aufgerufen werden:

```bash
python monitor.py
```

Bei jedem Lauf:

- werden neue Bachtrack-Events erkannt und an Discord gemeldet
- werden neue passende Gmail-Mails erkannt und an Discord gemeldet