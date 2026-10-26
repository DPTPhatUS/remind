# Remind web app

React/Vite camera UI for one patient's local memory store. See the
[root README](../README.md) for the complete launch sequence.

```bash
npm ci
npm run dev -- --host 127.0.0.1
```

Vite proxies `/api` HTTP and WebSocket traffic to `http://127.0.0.1:8000`.
Set `REMIND_API_URL` to use a different local backend.
Use localhost or HTTPS for camera access. Start/Stop owns capture explicitly.
The preview is direct camera video; fresh backend face results produce overlays.
Voice setup lets a helper save the user reference. People provides categorized
facts, evidence, temporal history, optional corrections and forgetting. Live
reminders show up to three established highlights and the previous encounter.

```bash
npm test
npm run build
npm run lint
npm run test:e2e
```

[Backend contract](../backend/docs/API.md). Playwright starts isolated local
servers and uses a separate test database. For camera fixtures and setup, see
[benchmark instructions](../benchmarks/README.md).
