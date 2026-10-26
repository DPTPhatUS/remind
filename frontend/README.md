# Remind web app

React/Vite camera UI for one patient's local memory store. See the
[root README](../README.md) for the complete launch sequence.

```bash
npm ci
npm run dev -- --host 127.0.0.1
```

Vite proxies `/api` HTTP and WebSocket traffic to `http://127.0.0.1:8000`.
Use localhost or HTTPS for camera access. Start/Stop owns capture explicitly.
The preview is direct camera video; fresh backend face results produce overlays.
Voice setup lets a helper save the user reference. People provides categorized
facts, evidence, temporal history, optional corrections and forgetting. Live
reminders show up to three established highlights and the previous encounter.

```bash
npm test
npm run build
npm run lint
```

[Backend contract](../backend/docs/API.md). Browser tests use Playwright with a
synthetic camera fixture and a separate test database; see
[benchmark instructions](../benchmarks/README.md).
