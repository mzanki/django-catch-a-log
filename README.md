# django-catch-a-log

A small, dependency-light Django app that captures HTTP requests, application logs and model
changes, ties them together through a correlation ID, and shows them in the Django admin.

It is intended for projects that want a simple built-in observability layer without setting up
Sentry, Datadog, New Relic or a dedicated log pipeline.


## What it does

- Assigns a correlation ID (CID) to every request and exposes it to downstream code,
  logs and response headers.
- **Persists only 4xx and 5xx requests by default** (URL, method, headers, body, response,
  timing, user, exception). Successful 2xx/3xx traffic is skipped to keep the table
  small. Set `CATCHALOG_LOG_HTTP_ONLY_ERRORS = False` to persist every request instead.
- Ships a `logging.Handler` that stores standard Python logging records in the database,
  tagged with the CID of the request that produced them.
- Provides an `@audit_model` decorator that records create/update/M2M changes for tracked
  models.
- Renders the above in the Django admin, grouped by correlation ID so that a request log
  links to the log lines and audit entries it produced.
- Ships a management command to prune old rows.

### Filtering what gets persisted

The persistence layer has several knobs, applied in this order:

1. `CATCHALOG_ENABLED` — master switch.
2. Static/media requests are always skipped.
3. `CATCHALOG_WHITELISTED_URLS` / `CATCHALOG_BLACKLISTED_URLS` — regex-based path filters.
4. `CATCHALOG_LOG_SELECTED_METHODS` — HTTP methods to consider.
5. `CATCHALOG_LOG_HTTP_ONLY_ERRORS` (default `True`) — if on, only status >= 400 or
   exceptions are logged.
6. `CATCHALOG_LOG_SELECTED_STATUSES` — if set, only statuses in this list are logged.

So the default is "log 4xx/5xx and exceptions only". Flip `LOG_HTTP_ONLY_ERRORS` off to
get every request, or use `LOG_SELECTED_STATUSES` for a precise allowlist.


## Requirements

- Python 3.10+
- Django 4.2, 5.0, 5.1 or 5.2


## Install

The package is not on PyPI. Install it directly from the repository:

```bash
pip install git+https://github.com/<your-user>/dj-catch-a-log.git
```

Or pin a tag / branch:

```bash
pip install git+https://github.com/<your-user>/dj-catch-a-log.git@main
```


## Quick start

1. Add the app to `INSTALLED_APPS`:

   ```python
   INSTALLED_APPS = [
       # ...
       "django_catch_a_log",
   ]
   ```

2. Add the middlewares. `CorrelationIdMiddleware` must be first so the CID is available to
   every other middleware and view. `PersistRequestMiddleware` wraps the rest of the stack
   to capture the response:

   ```python
   MIDDLEWARE = [
       "django_catch_a_log.middlewares.CorrelationIdMiddleware",
       # ... your other middlewares ...
       "django_catch_a_log.middlewares.PersistRequestMiddleware",
   ]
   ```

3. Run migrations:

   ```bash
   python manage.py migrate
   ```

4. (Optional) Enable the database log handler so `logging` calls are also persisted:

   ```python
   LOGGING = {
       "version": 1,
       "disable_existing_loggers": False,
       "filters": {
           "cid": {"()": "django_catch_a_log.log_filters.CidFilter"},
       },
       "formatters": {
           "console": {"()": "django_catch_a_log.log_formatters.ConsoleFormatter"},
       },
       "handlers": {
           "console": {
               "class": "logging.StreamHandler",
               "formatter": "console",
               "filters": ["cid"],
           },
           "db": {
               "class": "django_catch_a_log.log_handler.DatabaseLogHandler",
               "filters": ["cid"],
           },
       },
       "root": {
           "handlers": ["console", "db"],
           "level": "INFO",
       },
   }
   ```


## Correlation IDs

`CorrelationIdMiddleware` looks at the `X-Correlation-ID` header (configurable) and uses its
value if present, otherwise it generates a UUIDv4. The value is stored in a `ContextVar`, so
it is available from anywhere on the same thread/async task via:

```python
from django_catch_a_log.cid import get_cid

get_cid()  # -> str or None
```

The CID is also attached to `request.correlation_id` and echoed back on the response header.

### Outside the request cycle

For code that runs outside a request (Celery tasks, management commands, scripts) use the
decorator. It supports both sync and async callables and resets the CID after the call so it
does not leak into the next task running on the same worker:

```python
from django_catch_a_log.decorators import with_correlation_id

@with_correlation_id
def my_task(payload):
    ...

# Pass an explicit CID to continue an existing trace:
my_task(payload, cid="abc-123")

# Or let the decorator generate a fresh one:
my_task(payload)
```


## Model audit

Decorate any model you want to track:

```python
from django.db import models
from django_catch_a_log.model_audit import audit_model

@audit_model(exclude=["updated_at"])
class Invoice(models.Model):
    number = models.CharField(max_length=50)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    updated_at = models.DateTimeField(auto_now=True)
```

Every `create`, `update` and `m2m_changed` signal produces an `AuditLog` row containing the
model name, object id, CID and a JSON diff of the changed fields.

To expose an "Audit" button on the model's admin change form, inherit from
`AuditableModelAdmin`:

```python
from django.contrib import admin
from django_catch_a_log.admin import AuditableModelAdmin
from .models import Invoice

@admin.register(Invoice)
class InvoiceAdmin(AuditableModelAdmin):
    pass
```


## Admin

The admin exposes three read-only models:

- `RequestLog` – one row per captured request, with filters for status code, method and
  "slow request" detection.
- `LoggingLog` – application log records captured by `DatabaseLogHandler`.
- `AuditLog` – model change history.

The request detail view shows the logging records that share the same CID, so you can see
the logs a specific request produced without leaving the admin.


## Settings

All settings are prefixed with `CATCHALOG_` and read lazily.

| Setting | Default | Description |
| --- | --- | --- |
| `CATCHALOG_ENABLED` | `True` | Master switch. Disables persistence and admin registration. |
| `CATCHALOG_LOG_HTTP_ONLY_ERRORS` | `True` | When `True`, only persist 4xx/5xx responses and exceptions. |
| `CATCHALOG_LOG_SELECTED_METHODS` | `["GET", "POST", "PUT", "PATCH", "DELETE"]` | HTTP methods to capture. |
| `CATCHALOG_LOG_SELECTED_STATUSES` | `[]` | If non-empty, only persist responses whose status code is in this list. |
| `CATCHALOG_WHITELISTED_URLS` | `[]` | If non-empty, only log requests whose path matches one of these regexes (takes precedence over the blacklist). |
| `CATCHALOG_BLACKLISTED_URLS` | `[]` | Regexes of paths to skip. |
| `CATCHALOG_SENSITIVE_KEYS` | `["password", "token", "access", "refresh", "sessionid", "authorization", "bearer", "csrftoken", "csrfmiddlewaretoken"]` | Keys (matched case-insensitively as substrings) whose values are replaced with `********` in headers, cookies, query params, request body and response body. |
| `CATCHALOG_URL_PATH_MAX_LENGTH` | `1000` | Max length for the `path` field. Change before running migrations. |
| `CATCHALOG_SLOW_REQUEST_THRESHOLD` | `5000` | Milliseconds above which the admin "Slow" filter highlights a request. Set to `0`/`None` to disable. |
| `CATCHALOG_CORRELATION_ID_META_KEY` | `"X_CORRELATION_ID"` | Header used to read/write the CID. |
| `CATCHALOG_CID_MAX_LENGTH` | `255` | Incoming CIDs are truncated to this length before use and storage. |
| `CATCHALOG_AUDIT_LOGGING_ENABLED` | `True` | Enables the `@audit_model` decorator and the `AuditLog` admin. |
| `CATCHALOG_REQUEST_BODY_MAX_BYTES` | `100000` | Request bodies larger than this are replaced with a marker instead of parsed. |
| `CATCHALOG_RESPONSE_BODY_MAX_BYTES` | `100000` | Same as above for responses. |
| `CATCHALOG_LOG_HANDLER_SYNC` | `False` | Write log records synchronously from `emit()` instead of using the background worker thread. See "Log handler reliability" below. |

Two additional settings live on `django.conf.settings` directly (not the `CATCHALOG_`
namespace) for consistency with the `logging` module layout:

| Setting | Default | Description |
| --- | --- | --- |
| `CATCH_A_LOG_QUEUE_SIZE` | `10000` | Max number of log records buffered in memory. Extra records are dropped. |
| `CATCH_A_LOG_BATCH_SIZE` | `100` | Max records inserted per `bulk_create` call. |


## Management commands

```bash
python manage.py prune_catch_a_log --days 30
python manage.py prune_catch_a_log --days 90 --target request
python manage.py prune_catch_a_log --days 30 --dry-run
```

- `--days N` (required) removes rows whose `created_at` is older than `N` days.
- `--target` can be `request`, `logging`, `audit` or `all` (default).
- `--dry-run` counts the affected rows without deleting.
- `--batch-size` controls how many rows are deleted per query (default `5000`).

Run it from cron or a periodic Celery task to keep the tables from growing without bound.


## Log handler reliability

`DatabaseLogHandler` buffers records in an in-process `queue.Queue` and flushes them from a
daemon thread with `bulk_create`. This keeps request latency low, but it means:

- If the process receives `SIGKILL`, runs out of memory, or crashes, any records still in
  the queue are lost. There is no Python-level fix for this; by design the OS does not let
  the process run cleanup code.
- On a clean shutdown (`SIGTERM`, `runserver` reload, gunicorn worker recycle with
  graceful timeout), `logging.shutdown()` calls `close()` which drains the queue with a
  5-second timeout.
- Each process/worker has its own thread and its own queue.

If you cannot tolerate that loss window, set `CATCHALOG_LOG_HANDLER_SYNC = True`. Each
`logger.info(...)` call will then write directly to the database, at the cost of added
latency per log call.

For higher durability requirements consider sending logs out-of-process via one of the
standard Python handlers (`SysLogHandler`, `SocketHandler`, `HTTPHandler`) or a shipper like
Fluentd, Vector or Loki, rather than persisting them through this app.


## Production notes

- `RequestLog`, `LoggingLog` and `AuditLog` grow unbounded. Schedule the prune command.
- The request body is cached by Django's middleware chain to read it. For uploads larger
  than `DATA_UPLOAD_MAX_MEMORY_SIZE` Django refuses to cache the body; in that case the
  request is still logged but `body` is `{}`.
- Audit logging is synchronous and runs inside the same transaction as the model save. That
  guarantees the audit row commits if and only if the data row commits, but it adds one
  `INSERT` per tracked save.
- Sensitive-key matching is substring-based (`"pass"` matches `"passphrase"`). Review
  `CATCHALOG_SENSITIVE_KEYS` for your domain.


## Development

```bash
uv sync                       # install dev deps
pre-commit install            # optional, runs ruff on commit
python tests/manage.py test tests
```

Lint and format:

```bash
ruff check .
ruff format .
```


## License

See `LICENSE`.
