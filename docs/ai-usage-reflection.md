# AI Usage Reflection

---

## 1. What did you use AI for across the four sections?

**System Design**
- Refining README prose — converting rough notes into clean, concise sentences.
- Checking that stated trade-offs were consistent with the actual implementation (e.g. confirming the partial-index rationale matched the migration file).

**API Implementation**
- Debugging environment mismatches between the local `.env` setup and the GitHub Actions service container (e.g. port differences that caused CI test failures that never appeared locally).
- Generating boilerplate Pydantic schema and SQLAlchemy column definitions after the shape was decided, to avoid typing errors in repetitive code.
- Suggesting the `populate_existing=True` execution option on `RETURNING` queries after an SQLAlchemy session-cache stale-read bug was observed.

**Testing**
- Drafting edge-case test matrix entries (e.g. naive datetime inputs, slot-on-boundary vs off-boundary) after describing the validation rules in plain English.
- Identifying missed parametrize combinations in the RBAC matrix once the role-permission table was specified.
- Writing the concurrency test scaffolding (`asyncio.gather`, response count assertions) once the race scenarios were described.

**Documentation**
- Polishing the final README sections (running locally, CI/CD note) for clarity and brevity.
- Formatting the requirements compliance report.

---

## 2. One example where an AI suggestion improved the work

**The situation:** The RBAC matrix test initially called `GET /ready` without overriding the `get_engine` FastAPI dependency. In tests, the lifespan context manager doesn't run under `ASGITransport`, so `app.state.engine` was `None` and the endpoint returned `503` instead of `200`.

**The prompt that led to the fix:**

> "I have a FastAPI endpoint `GET /ready` that injects `get_engine` as a dependency. In my test suite using `ASGITransport`, the lifespan never runs so `request.app.state.engine` is `None` and the endpoint returns 503.
>
> Do not write any code. Do not ask clarifying questions. Think through the correct fix and explain your reasoning. Also explain why testing this endpoint in the same way as the rest of the API suite matters — what real bug would go undetected if we skipped it or marked it xfail."

**Why this prompt works:**
- *No code* forces explanation-first thinking; the reasoning is reviewable before any implementation.
- *No clarifying questions* keeps the exchange tight — the context is already complete.
- *Justify why to test it* surfaces the real value: without testing `/ready` under the same fixture as every other endpoint, an accidental dependency override that breaks readiness checks would go undetected in CI but fail in production.

**The improvement:** AI correctly identified that `application.dependency_overrides[get_engine] = lambda: fresh_db` was the right fix and explained *why* the lifespan gap exists. That explanation confirmed the diagnosis before a single line changed.

---

## 3. One example where AI output was wrong or incomplete

**The situation:** When asked to help with the concurrent cancel-and-reschedule test, the AI generated an assertion:

```python
assert sorted(statuses) == [200, 409]
```

with the explanation that exactly one operation would always win and the other would always see a locked/changed row and return 409.

**Why it was wrong:** That's true when cancel commits first (reschedule wakes, sees `status='cancelled'`, returns 409). But if reschedule commits first, it moves `start_at` and commits. Cancel then wakes, sees the appointment is still `booked` (just at a new slot), and cancels it successfully — both return 200. The final state is still consistent (cancelled), but the assertion fails.

**How it was caught:** Running the test suite multiple times. The assertion failed on roughly one in three runs depending on which coroutine the event loop scheduled first. The fix was to assert `statuses in ([200, 409], [200, 200])` and verify the final DB row state in both branches, which is what the test now does.

**Lesson:** AI reasoned about one interleaving of a concurrent operation and presented it as the only interleaving. Race conditions require exhaustive interleaving analysis, not just the most obvious path.

---

## 4. Two decisions made without AI

**Decision 1 — Keycloak with realm-as-code and RBAC permission roles**

Chose Keycloak over embedding JWT signing in the app, and modelled the authorisation as base roles (`patient`, `doctor`, `admin`) plus granular permission roles (`book_for_patient`, `manage_any`, `view_any`) rather than a flat role list.

*Why trusted own judgment:* This came from prior experience with systems where "admin" became a catch-all that was hard to audit and impossible to restrict incrementally. Realm-as-code (`realm-clinic.json`) means no manual Keycloak UI changes in production — configuration drift has burned me before. The permission-role model gives clinic admins least-privilege access by default, which is the correct security posture regardless of scale.

**Decision 2 — FastAPI over Django REST Framework or Go**

Chose FastAPI with asyncpg and SQLAlchemy 2 async.

*Why trusted own judgment:* Django REST Framework's ORM is synchronous; forcing async on top of it (via `sync_to_async`) adds complexity without benefit for a heavily I/O-bound service. Go would have been faster at runtime but significantly slower to iterate on — the project needed working, testable, maintainable code on a short timeline, not maximum throughput. FastAPI's native async, Pydantic v2 validation, and automatic OpenAPI generation matched the actual constraints. The choice wasn't performance-first; it was correctness-and-maintainability-first.

