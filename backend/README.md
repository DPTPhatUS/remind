# Remind backend

See the [root README](../README.md) for setup and limitations.

The `remind` Python package owns local SQLite memory, YuNet/SFace identity,
Light-ASD speaker evidence, durable conversation jobs, and the FastAPI routes.
Use `uv sync --extra speaker` and include `--extra speaker` in runtime commands
so uv retains the optional PyTorch dependency. OpenCV and speaker inference use
separate executors. The live frame queue keeps only the newest waiting frame.

Runtime data and downloaded weights live under `.local/`, excluded from git.
The installed package includes the model manifest and license notices.
Configuration is in `.env`; see [.env.example](.env.example).

No schema or API compatibility with the old application is provided. Existing
legacy database data is left untouched. The current fresh schema is created on
startup. Future schema changes will require a migration or a new dedicated file.

[API contract](docs/API.md) · [Benchmark strategy](../docs/testing/realtime-memory-evaluation.md)
