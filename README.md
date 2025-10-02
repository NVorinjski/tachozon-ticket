📖 README – Ticket-System Deployment & Betrieb
🚀 Überblick

Dieses Repository enthält die Ticketing-App (Django + Celery/Huey + Postgres + Docker), die für mehrere Unternehmen parallel betrieben werden kann.
Jede Instanz läuft in einem eigenen Verzeichnis mit eigener Konfiguration, Datenbank und Branding.

Beispiele:

ticket.tachozon.com → Instanz A (Tachozon)

it-teleticket.tachozon.com → Instanz B (IT-Telematics)

📦 Architektur

Django (Gunicorn): Ticketing-Backend & Frontend (AdminLTE)

Postgres: separate Datenbank pro Instanz

Huey: Hintergrund-Jobs (z. B. Mail-Import, Erinnerungen)

Background-Tasks: Task Worker

Nginx (im Container): Statisches Serving, Proxy aus Docker heraus

System-Nginx (auf dem Host): Reverse Proxy mit SSL (Let’s Encrypt)

Docker Compose: Orchestrierung pro Instanz

📂 Verzeichnisstruktur
/var/www/
 ├── tachozon-ticket/         # Instanz A (ticket.tachozon.com)
 └── it-teleticket.tachozon.com/  # Instanz B (it-teleticket.tachozon.com)


Jede Instanz enthält:

docker-compose.yml

.env (Konfiguration, Secrets, Mail-Setup)

nginx/ (Container-Nginx Config)

Repo-Code (geclont aus GitHub)

⚙️ Setup einer neuen Instanz

Repo klonen

cd /var/www
git clone https://github.com/<dein-repo>.git it-teleticket.tachozon.com
cd it-teleticket.tachozon.com


.env erstellen
Kopiere aus bestehender Instanz und anpassen:

# Datenbank
POSTGRES_DB=it_teleticket
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<pw>
POSTGRES_HOST=db
POSTGRES_PORT=5432

# Django
SECRET_KEY=...
ALLOWED_HOSTS=it-teleticket.tachozon.com

# Branding
PROJECT_NAME="IT-Telematics Ticket"
LOGO_URL="/static/assets/img/it_telematics_logo.png"

# Mail-Einstellungen
MAIL_USER=support@it-telematics.de
MAIL_AUTH_USER=service@it-telematics.de   # falls Shared Mailbox
OAUTH_TENANT_ID=...
OAUTH_CLIENT_ID=...
OAUTH_CLIENT_SECRET=...
OAUTH_REFRESH_TOKEN=...


Docker Compose starten

docker compose up -d --build


Superuser anlegen

docker compose exec web python manage.py createsuperuser

🔑 Auth & Mails (Microsoft Entra ID)
App-Registrierung in Azure AD

App registrieren → CLIENT_ID, TENANT_ID notieren.

Secret anlegen (optional, für Confidential Client).

API-Permissions:

IMAP.AccessAsUser.All

offline_access
(Admin Consent erteilen)

Token-Flow

Einmalig mit msal einen Refresh-Token generieren:

result = app.acquire_token_interactive([
    "offline_access",
    "https://outlook.office.com/IMAP.AccessAsUser.All"
])
print(result["refresh_token"])


OAUTH_REFRESH_TOKEN in .env speichern.

Shared Mailbox beachten

MAIL_USER = Shared-Adresse (support@it-telematics.de)

MAIL_AUTH_USER = Lizenzierter Benutzer mit FullAccess

Token muss zu MAIL_AUTH_USER gehören, aber im IMAP-Authstring wird MAIL_USER gesetzt.

✉️ Mail-Import Workflow

Huey/Background-Tasks holen regelmäßig neue Mails via IMAP + OAuth2.

Mail wird als Ticket gespeichert:

subject → Ticket-Titel

Body → note (HTML oder Text, normalisiert)

Attachments → als Attachment-Model gespeichert

ProblemSource wird automatisch mit email markiert.

📝 Notes-Rendering

E-Mails: werden beim Import normalisiert (HTML → Text, Absätze/Listen bleiben erhalten).

In-App Notes: werden ohne Tags gespeichert und erst in Templates mit render_note gefiltert.

Template-Tags:

{{ ticket.note|render_note }} → komplette Note anzeigen

{{ ticket.note|render_note_preview:100 }} → Vorschau mit Truncation

🎨 Branding (pro Instanz)

Variablen in .env:

PROJECT_NAME (z. B. „Tachozon Ticket“ oder „IT-Telematics Ticket“)

LOGO_URL (Pfad zu Logo-Datei im static)

Templates nutzen Variablen statt hartem Text:

<h1><b>{{ PROJECT_NAME }}</b></h1>
<img src="{{ LOGO_URL }}" width="40">


So bleibt der Master-Branch gleich, nur .env + statische Assets pro Instanz ändern sich.

🔒 SSL & Reverse Proxy

System-Nginx unter /etc/nginx/sites-enabled/
Beispiel it-teleticket.tachozon.com.conf:

server {
    listen 80;
    server_name it-teleticket.tachozon.com;
    location /.well-known/acme-challenge/ { root /var/www/letsencrypt; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl http2;
    server_name it-teleticket.tachozon.com;

    ssl_certificate     /etc/letsencrypt/live/it-teleticket.tachozon.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/it-teleticket.tachozon.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:1338;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}


Zertifikat anlegen:

sudo certbot --nginx -d it-teleticket.tachozon.com

🔧 Nützliche Befehle

Logs live:

docker compose logs -f web
docker compose logs -f background_tasks
docker compose logs -f huey


Migrationen nachziehen:

docker compose run --rm web python manage.py migrate


Collectstatic manuell:

docker compose run --rm web python manage.py collectstatic --noinput


Ticket-Superuser anlegen:

docker compose exec web python manage.py createsuperuser

✅ Betrieb & Wartung

Mehrere Instanzen = mehrere Verzeichnisse mit eigenem docker compose.

Updates:

git pull
docker compose build
docker compose up -d


Fehleranalyse:

System-Nginx → /var/log/nginx/error.log

Container → docker compose logs -f

Django-Debug → .env mit DEBUG=1