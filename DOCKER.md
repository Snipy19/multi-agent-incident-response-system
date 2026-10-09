# Docker development

The project can run locally in a reproducible container. Docker does not copy
`.env`, OAuth credentials, runtime reports, or the local SQLite database into
the image.

## Prerequisites

Install Docker Desktop, then confirm:

```powershell
docker --version
docker compose version
```

## Start the service

Ensure `.env` contains the required local credentials, then run:

```powershell
docker compose up --build
```

Open the website at:

```text
http://127.0.0.1:8000/ui/login.html
```

The API health check is available at:

```text
http://127.0.0.1:8000/
```

## Stop the service

```powershell
docker compose down
```

The current Compose file mounts `./db` for local SQLite persistence. During
AWS deployment, remove that mount and configure the application to use the RDS
PostgreSQL connection string instead.
