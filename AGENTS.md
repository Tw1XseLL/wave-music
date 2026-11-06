# WAVE Music — agent team

Roles: Frontend (Liquid Glass, accessibility, responsive UI); Backend (API, SQLite, auth); Telegram (bot, WebApp initData); QA (tests, security, regression); DevOps (Railway, GitHub, observability).

Workflow: each change starts from an issue; one owner per change; use a feature branch and PR; require tests and code review before merge; deploy API then frontend; verify Railway health, HTTP errors and user-visible behavior. Never commit tokens, initData, or personal user data. Never bypass Telegram signature validation. Roll back on failed health checks. Production deploys are coordinated by DevOps.

Immediate blocker: `GET /api/library` returns 401, diagnostic `AUTH_ERROR: signature mismatch`. Check the actual API bot identity and match it with @WaveMusicAppBot, confirm Railway BOT_TOKEN service reference, then retest Telegram Mini App. Keep database volume and other projects untouched.
