# DermaStyle AI

One shopping plan for your skin and your style. A goal-driven shopping agent built on two YouCam APIs:
**AI Skin Analysis** (`/s2s/v2.0/task/skin-analysis`) and **AI Clothes Virtual Try-On v4** (`/s2s/v2.0/task/cloth-v4`).

Built for the YouCam API Skin AI & eCommerce VTO Hackathon (Devpost, closes Nov 2, 2026).

## What it does

1. **Discover**: parses a free-text goal ("wedding, under $150, fragrance-free, elegant") into an editable profile.
2. **Skin Insights**: with explicit consent, runs YouCam Skin Analysis (SD concerns) and shows only the scores the API returned.
3. **Beauty Planner**: ranks catalog products against the weakest measured concerns. Every reason carries an evidence tag: `measured`, `verified`, `catalog`, `inferred`, `unknown`.
4. **Virtual Closet**: runs YouCam Clothes Try-On v4 on the shopper's full-body photo and a garment image.
5. **My Plan**: budget-aware bundles (best match, lowest total, over-budget alternatives) with exact totals.

## Design rules

- The YouCam key lives only on the backend. The browser talks to Next.js, which proxies `/api/*`.
- "Fragrance-free" requires an ingredient list with no fragrance terms. **No list means unknown, and the product is excluded**, never assumed clean.
- No medical claims; try-on results always carry a "visual preview only" note.
- Photos are validated (type, size, dimensions), EXIF-normalized (GPS stripped), sent to YouCam, and **never written to disk**. `DELETE /api/sessions/{id}/data` drops everything derived from them.
- Ranking, budgeting and parsing are deterministic code, not an LLM, so nothing can be invented. An LLM parser/explainer can implement `parse_goal` later.

## YouCam integration (`backend/app/youcam/`)

| Step | Call |
|---|---|
| Register file | `POST /s2s/v2.0/file` -> `file_id` + pre-signed PUT request |
| Upload bytes | `PUT <pre-signed url>` with the returned headers (no auth header) |
| Create task | `POST /s2s/v2.0/task/{skin-analysis \| cloth-v4}` -> `task_id` |
| Poll | `GET /s2s/v2.0/task/{feature}/{task_id}` until `task_status` is `success` or `error` |

Retries with jittered backoff on 429/5xx/network errors; credit and validation errors fail fast and map to shopper-readable messages. Polling backs off up to 10 s with a deadline. Docs: <https://docs.perfectcorp.com/reference/ai_skin_analysis>, <https://docs.perfectcorp.com/reference/ai_clothes/v4.0>.

## Run

```bash
cp .env.example .env        # add YOUCAM_API_KEY
# backend
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
uvicorn app.main:app --reload
# frontend (new terminal)
cd frontend && npm install && npm run dev      # http://localhost:3000
# or everything
docker compose up --build
```

Tests: `cd backend && python -m pytest` (29 tests; YouCam is mocked with `respx`).

## Honest status

- **Verified**: backend logic and the full API journey against *mocked* YouCam responses; frontend typechecks and builds.
- **Not yet verified**: live calls with a real API key. Do one real skin and one real try-on run before recording the demo, and compare the response shapes to `parse_skin_results` / `parse_tryon_results`.
- **Sample data**: `backend/data/catalog.json` is fictional. Replace it with real, human-checked products (`provenance.verified: true`) and give garments public `image_url`s. Until then, the UI shows a "sample data" banner.
- Sessions are in memory (see `SessionStore`); swap for PostgreSQL if you need persistence. No auth or payments yet.
- The skin-analysis result schema was taken from the docs' `format: json` example; `skin_age` and overall score are only shown if the API returns them.

## Layout

```
backend/app/youcam/    API client, skin + try-on wrappers, typed errors
backend/app/agent/     goal parser, recommender, budget optimizer, session state machine
backend/app/catalog/   models, ingredient analysis, repository
backend/app/media/     image validation
backend/app/api/       FastAPI routes
frontend/app/          five-step UI (Next.js, TypeScript)
```
# dermastyle-ai
