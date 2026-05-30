# Deploy RiskRadar with Docker on Render (one URL, free tier)

One Docker image runs **FastAPI + Next.js + nginx** on the port Render assigns (`$PORT`).

---

## Architecture

```
Internet → Render ($PORT) → nginx
                              ├─ /claims, /predict, … → FastAPI :8000
                              └─ /*                     → Next.js :3000
```

The UI calls `/claims` on the **same hostname** (no separate API URL needed).

---

## Part A — Test locally (recommended)

From `C:\Users\202121\Desktop\riskradar`:

```powershell
docker build -t riskradar .
docker run -p 10000:10000 -e PORT=10000 --env-file .env riskradar
```

Open:

- App: http://localhost:10000  
- API health: http://localhost:10000/health  
- API docs: http://localhost:10000/docs  

First build can take **10–20 minutes** (installs Python + Node + npm build).

---

## Part B — Push to GitHub

```powershell
cd C:\Users\202121\Desktop\riskradar
git init
git add .
git commit -m "Docker deploy: frontend + backend"
git branch -M main
git remote add origin https://github.com/YOUR_USER/riskradar.git
git push -u origin main
```

**Must be committed:** `data/`, `models/`, `api/`, `frontend/`, `Dockerfile`, `docker/`, `requirements-docker.txt`

**Do not commit:** `.env` (set secrets in Render dashboard)

---

## Part C — Render Web Service (Docker, not Blueprint)

1. [dashboard.render.com](https://dashboard.render.com) → **New +** → **Web Service**
2. Connect your **riskradar** GitHub repo
3. Settings:

| Field | Value |
|-------|--------|
| **Name** | `riskradar` |
| **Region** | closest to you |
| **Branch** | `main` |
| **Runtime** | **Docker** |
| **Dockerfile Path** | `Dockerfile` |
| **Instance Type** | **Free** (if available) |

4. **Environment Variables** (optional but recommended):

| Key | Example |
|-----|---------|
| `GEMINI_API_KEY` | your key |
| `GROQ_API_KEY` | your key |
| `KANOON_API_KEY` | optional |
| `COURTLISTENER_API_KEY` | optional |

You do **not** need `NEXT_PUBLIC_API_BASE_URL` for this setup.

5. Click **Create Web Service**
6. Wait for build + deploy (often 15–25 min first time)

7. Open your service URL: `https://riskradar-xxxx.onrender.com`

---

## Part D — Verify production

```text
https://YOUR-SERVICE.onrender.com/health
https://YOUR-SERVICE.onrender.com/claims
https://YOUR-SERVICE.onrender.com/
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Build runs out of memory | Use **Starter** instance ($7) for build, or build image in GitHub Actions and push to Docker Hub |
| `structured_rows: 0` | `data/` not in git — commit and push |
| UI loads, API 404 | Check nginx paths; hit `/health` directly |
| Cold start 30–60s | Normal on free tier — wake service before demo |
| Old `DockerFile` name | Render uses **`Dockerfile`** (lowercase f) — use the new file in repo root |

---

## Optional: two separate Docker services

If one image is too heavy for free tier, run **two** Web Services from the same repo:

1. **API only** — use the old `DockerFile` / slim Python image on port `$PORT`
2. **Frontend** — official Node image, `rootDir: frontend`, set `NEXT_PUBLIC_API_BASE_URL` to API URL

The single-container approach above is simpler for demos (one link for judges).
