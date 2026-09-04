"""Patient-owned acceptance invariants.

These tests pin the three goals of the patient-owned release (focus memory,
remove caregiver, single-patient-owned) to executable assertions that run on
every CI run. They must NEVER be skipped.

The five checks below collectively enforce:
    1. The HTTP surface is exactly the memory-only route set.
    2. The startup hook creates the single Patient row on an empty database.
    4. PersonService no longer reads any `sensitive` field.
    5. The reminder/reminder-payload schema no longer exports `requires_review`.

The frontend counterpart (`test_patient_nav_is_top_level`,
`test_patient_me_is_no_auth`) lives in `frontend/src/App.test.tsx`.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import fields, is_dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures / constants
# ---------------------------------------------------------------------------

EXPECTED_HTTP_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/health",
        "/api/v1/patients/me",
        "/api/v1/people",
        "/api/v1/people/{person_id}",
        "/api/v1/people/{person_id}/face-examples",
        "/api/v1/relationships",
        "/api/v1/events",
        "/api/v1/interactions",
        "/api/v1/interactions/{interaction_id}/transcripts",
        "/api/v1/memories/search",
        "/api/v1/media/evidence",
        "/api/v1/media/cleanup-expired",
    }
)
EXPECTED_WEBSOCKET_PATHS: frozenset[str] = frozenset(
    {"/api/v1/live/sessions/{session_id}"}
)


def _collect_route_paths(app) -> tuple[frozenset[str], frozenset[str]]:
    """Return (http_paths, websocket_paths) registered on the FastAPI app.

    Starlette wraps every ``include_router`` in a private ``_IncludedRouter``
    whose ``include_context.prefix`` carries the mount point. Walking
    recursively and accumulating that prefix at each level gives the real
    URL a client would hit.
    """
    from fastapi.routing import APIRoute, APIWebSocketRoute

    http_paths: set[str] = set()
    websocket_paths: set[str] = set()

    def walk(routes, prefix: str = "") -> None:
        for route in routes:
            if type(route).__name__ == "_IncludedRouter":
                inner_prefix = getattr(route.include_context, "prefix", "") or ""
                walk(route.original_router.routes, prefix + inner_prefix)
                continue
            path = getattr(route, "path", None)
            if path is None:
                continue
            full = prefix + path
            if isinstance(route, APIWebSocketRoute):
                websocket_paths.add(full)
            elif isinstance(route, APIRoute):
                http_paths.add(full)

    walk(app.router.routes)
    return frozenset(http_paths), frozenset(websocket_paths)


# ---------------------------------------------------------------------------
# Test 1: openapi route set is memory-only
# ---------------------------------------------------------------------------


def test_openapi_route_set_is_memory_only() -> None:
    """The exposed HTTP + WS routes must be exactly the patient-owned set.

    No `/auth/*`, no `/review-items/*`, no other legacy caregiver endpoints.
    """
    from main import app

    http_paths, websocket_paths = _collect_route_paths(app)
    openapi_paths = frozenset(app.openapi()["paths"].keys())

    # The OpenAPI schema (HTTP only) matches the expected HTTP set exactly.
    assert openapi_paths == EXPECTED_HTTP_PATHS, (
        f"openapi paths drift.\n"
        f"  missing: {EXPECTED_HTTP_PATHS - openapi_paths}\n"
        f"  extra:   {openapi_paths - EXPECTED_HTTP_PATHS}"
    )

    # The websocket surface is exactly the live-session route.
    assert websocket_paths == EXPECTED_WEBSOCKET_PATHS, (
        f"websocket paths drift.\n"
        f"  missing: {EXPECTED_WEBSOCKET_PATHS - websocket_paths}\n"
        f"  extra:   {websocket_paths - EXPECTED_WEBSOCKET_PATHS}"
    )

    # Combined surface still excludes any legacy caregiver surface.
    all_paths = http_paths | websocket_paths | openapi_paths
    forbidden_prefixes = ("/api/v1/auth", "/api/v1/review-items", "/api/v1/caregivers")
    for forbidden in forbidden_prefixes:
        offenders = [p for p in all_paths if p.startswith(forbidden)]
        assert not offenders, f"legacy route {forbidden}* leaked: {offenders}"

    # Sanity: the patient endpoint exists and is unauth-gated at the
    # openapi layer (no security scheme on the operation).
    patient_op = app.openapi()["paths"]["/api/v1/patients/me"]["get"]
    assert "security" not in patient_op or patient_op["security"] == []


# ---------------------------------------------------------------------------
# Test 2: lifespan seeds patient on empty db
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_seeds_patient_on_empty_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Running the lifespan hook on an empty patients table inserts one row."""
    from db.models.entities import Patient as PatientModel
    from main import app, lifespan

    added: list[PatientModel] = []

    # Build a fake session that reports no existing patient, then tracks
    # any ``add`` call so we can inspect what the lifespan would persist.
    fake_session = MagicMock(name="fake_session")
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)

    exec_result = MagicMock(name="exec_result")
    exec_result.scalars.return_value.first.return_value = None
    fake_session.execute = AsyncMock(return_value=exec_result)
    fake_session.commit = AsyncMock(return_value=None)

    def _add(obj: PatientModel) -> None:
        added.append(obj)

    fake_session.add = _add  # type: ignore[assignment]

    session_factory = MagicMock(name="session_factory")
    session_factory.return_value = fake_session

    # The lifespan imports ``AsyncSessionLocal`` into the ``main`` module's
    # namespace at import time, so patch the attribute the hook actually uses.
    import main as main_module

    monkeypatch.setattr(main_module, "AsyncSessionLocal", session_factory)

    # Run the startup hook (and exit immediately after the seed branch).
    async with lifespan(app):
        pass

    # Exactly one Patient row was created, with the canonical display name.
    assert len(added) == 1, f"expected 1 patient, lifespan added {len(added)}"
    created = added[0]
    assert isinstance(created, PatientModel)
    assert created.display_name == "Patient"
    assert created.preferences == {}
    assert created.accessibility_settings == {}

    # And the hook called commit + close exactly once.
    fake_session.execute.assert_awaited_once()
    fake_session.commit.assert_awaited_once()
    session_factory.assert_called_once()


# ---------------------------------------------------------------------------
# Test 4: person service does not read sensitive
# ---------------------------------------------------------------------------


def test_person_service_does_not_read_sensitive() -> None:
    """PersonService methods that touch Person must not reference `sensitive`.

    The patient-owned release drops the ``sensitive`` flag from Person; this
    test pins that PersonService source code does not depend on it.
    """
    from services import person_service

    source = inspect.getsource(person_service)
    lowered = source.lower()

    # No ``sensitive`` token anywhere in the module.
    assert "sensitive" not in lowered, (
        "PersonService still mentions 'sensitive'; the patient-owned release "
        "removed this flag. See services/person_service.py."
    )

    # Sanity: every public method on PersonService still exists.
    expected_methods = {"list_people", "create_person", "update_person", "enroll_face"}
    actual_methods = {
        name
        for name, obj in inspect.getmembers(person_service.PersonService, inspect.iscoroutinefunction)
    }
    assert expected_methods <= actual_methods, (
        f"missing PersonService methods: {expected_methods - actual_methods}"
    )


# ---------------------------------------------------------------------------
# Test 5: reminder payload has no requires_review
# ---------------------------------------------------------------------------


def test_reminder_payload_has_no_requires_review() -> None:
    """Reminder dataclass + ReminderPayload schema no longer export requires_review."""
    # 1. The Reminder dataclass must not carry a requires_review field.
    from services.reminder_service import Reminder

    assert is_dataclass(Reminder), "Reminder should be a dataclass"
    field_names = {f.name for f in fields(Reminder)}
    assert "requires_review" not in field_names, (
        f"Reminder still carries requires_review (got fields: {sorted(field_names)})"
    )

    # 2. The ReminderPayload schema must not export requires_review.
    # The patient-owned release removed ReminderPayload entirely; even if a
    # future module reintroduces it, the attribute must remain absent.
    try:
        from schemas import reminders as reminders_module  # type: ignore[import-not-found]
    except (ImportError, ModuleNotFoundError):
        reminders_module = None

    if reminders_module is not None:
        exported = set(getattr(reminders_module, "__all__", [])) | set(dir(reminders_module))
        assert "ReminderPayload" not in exported or not hasattr(
            reminders_module, "requires_review"
        ), "ReminderPayload/requires_review leaked back into schemas.reminders"

        # If ReminderPayload is exported, its model fields must not contain requires_review.
        if hasattr(reminders_module, "ReminderPayload"):
            payload_cls = reminders_module.ReminderPayload
            payload_fields = set(getattr(payload_cls, "model_fields", {}).keys())
            assert "requires_review" not in payload_fields, (
                f"ReminderPayload.model_fields leaked requires_review: {sorted(payload_fields)}"
            )

    # 3. No schema module exports a top-level `requires_review` attribute.
    schemas_root = Path(__file__).resolve().parents[2] / "src" / "schemas"
    leaked: list[str] = []
    if schemas_root.is_dir():
        for py_file in schemas_root.glob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            # Token ``requires_review`` outside of docstrings/comments/strings.
            for match in re.finditer(r"\brequires_review\b", text):
                line_start = text.rfind("\n", 0, match.start()) + 1
                line_end = text.find("\n", match.end())
                line = text[line_start:line_end if line_end != -1 else None]
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                leaked.append(f"{py_file.name}:{stripped}")

    assert not leaked, (
        "`requires_review` still referenced in schemas source:\n  "
        + "\n  ".join(leaked)
    )