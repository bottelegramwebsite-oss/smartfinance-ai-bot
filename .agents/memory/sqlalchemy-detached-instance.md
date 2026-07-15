---
name: SQLAlchemy detached-instance trap
description: Returning ORM objects from a scoped session context manager without expire_on_commit=False raises DetachedInstanceError on later attribute access.
---

If a helper does:
```python
with get_db_session() as session:
    obj = session.query(Model)...
    return obj
```
and the session factory uses SQLAlchemy's default `expire_on_commit=True`, then after the context manager commits and closes the session, any attribute access on `obj` (e.g. `obj.some_field`) raises `DetachedInstanceError` — even though the call site looks fine and works for callers who never read attributes off the returned object.

**Why:** commit expires all loaded attributes so the next read re-fetches fresh data from the DB. That re-fetch needs an open session; once the `with` block's context manager closes the session, there's nothing to fetch from.

**How to apply:** when a project's data-access pattern returns ORM objects out of a `with session:` block for the caller to read afterward, set `expire_on_commit=False` on the `sessionmaker`. Remove any redundant manual `session.commit(); session.refresh(obj)` calls inside the block — they're unnecessary once the context manager itself commits, and calling commit twice while relying on refresh afterward is what triggers the trap. This bug can lie completely dormant if no caller happens to read attributes off the returned object — don't assume "no error today" means it's safe to keep returning detached objects.
