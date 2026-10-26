# Deploy PubEcon

Recommended topology: one public hostname, Caddy terminating TLS, the React
build served as static files, and `/api/*` proxied to the FastAPI container.
The SQLite database is mounted read-only and is never exposed directly.

```text
Internet :443
   |
   v
 Caddy  ---> /srv/pubecon/web (React build)
   |
   +-------> /api/* ---> FastAPI :8000 ---> /data/top5.db (read-only)
```

## What the server needs

- Ubuntu 22.04 or 24.04 LTS, x86_64 or arm64
- 2 vCPU, 2 GB RAM minimum; 4 GB recommended
- 20 GB free disk (database is about 549 MB; Docker images and logs need room)
- Ports 22, 80, and 443 reachable
- Docker Engine with the Compose plugin
- A domain whose DNS you control

## 1. Buy the domain and point DNS

Buy a domain (Porkbun, Cloudflare Registrar, and Namecheap are reasonable
registrars). Suggested names: `pubecon.org`, `pubecon.io`, or `pubecon.dev`.
Availability is not guaranteed.

Create DNS records at the registrar:

| Type | Name | Value |
|---|---|---|
| A | `@` | your server's public IPv4 address |
| A | `www` | your server's public IPv4 address |

If the DNS provider is Cloudflare, set both records to **DNS only** (grey cloud)
for the first certificate issuance. After Caddy has a certificate, you can turn
on the proxy if you want Cloudflare in front. Do not use "Flexible" SSL.

## 2. Prepare the server

Run these as a sudo-capable user, replacing the IP and username as needed.

```bash
ssh root@YOUR_SERVER_IP
adduser deploy
usermod -aG sudo deploy
# Add your SSH public key to /home/deploy/.ssh/authorized_keys, then log in as deploy.
```

On the server as `deploy`:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl ufw

# Docker Engine + Compose plugin
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy
newgrp docker

sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Log out and back in so the `docker` group applies.

## 3. Put the code and database on the server

```bash
sudo mkdir -p /srv/pubecon
sudo chown deploy:deploy /srv/pubecon
git clone https://github.com/leafDancer/PubEcon.git /srv/pubecon
cd /srv/pubecon
cp .env.example .env
```

Edit `.env`:

```text
DOMAIN=your-domain.example
ACME_EMAIL=you@example.com
```

The ACME email receives certificate-expiry notices. Use an address you monitor.

Get the database. Once the v1.0.0 release asset is published:

```bash
mkdir -p data/curated
curl -L --fail \
  -o data/curated/top5.db \
  https://github.com/leafDancer/PubEcon/releases/download/v1.0.0/top5.db
sha256sum data/curated/top5.db
```

The expected SHA-256 is in `data/reports/release_manifest.md`. Until the asset
is uploaded, copy it from the laptop:

```powershell
scp D:\Research\econ-pub-database\data\curated\top5.db deploy@YOUR_SERVER_IP:/srv/pubecon/data/curated/top5.db
```

Make sure the container user can read it:

```bash
chmod 644 data/curated/top5.db
```

## 4. Start the stack

```bash
cd /srv/pubecon
docker compose up -d --build
docker compose ps
docker compose logs -f caddy
```

Caddy obtains a certificate automatically. Check:

```bash
curl -I https://your-domain.example/api/health
curl https://your-domain.example/api/health
```

Then open `https://your-domain.example/`.

## 5. Update a deployment

Code-only update:

```bash
cd /srv/pubecon
git pull
docker compose up -d --build
```

Database update: replace `data/curated/top5.db`, verify its checksum, then:

```bash
docker compose restart api
```

Keep the previous database and release manifest until the new one has been
checked. The API opens SQLite in read-only mode; the mount must stay `:ro`.

## 6. Operate it

- **TLS:** Caddy renews certificates automatically. Keep ports 80/443 open.
- **Logs:** `docker compose logs --tail=200 api`, `docker compose logs --tail=200 caddy`.
- **Health:** `curl https://your-domain.example/api/health`.
- **Backups:** keep the release asset and raw source cache off the server; the
  database is reproducible only with its exact release artifact.
- **Firewall:** only 22, 80, and 443 are public. Port 8000 is internal.
- **Workers:** the API runs two Uvicorn workers. On a 2 GB server, watch memory;
  reduce to one worker if needed.

## If the frontend and API use different hostnames

Build the frontend with `VITE_API_BASE=https://api.your-domain.example/api`, set
`PUBECON_CORS_ORIGINS=https://your-domain.example`, and proxy only the API on the
API hostname. The single-hostname setup above is simpler and recommended.

## What to send back for the concrete commands

1. Server OS and version (`lsb_release -a`)
2. Public IP and SSH username/port
3. Domain name you bought
4. RAM and disk size
5. Whether the server already runs Nginx/Apache or another service on 80/443
6. Whether Cloudflare is in front of the domain
