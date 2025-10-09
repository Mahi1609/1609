# # sentry_init.py (resilient variant)
# """
# Safe Sentry init: will not crash the process if sentry-sdk is missing.
# Place this file in project root and import as the first import in processes.
# """

# import os
# import logging
# from typing import Any, Dict

# logger = logging.getLogger("sentry_init")

# SENTRY_ENABLED = os.getenv("SENTRY_ENABLED", "false").lower() in ("1", "true", "yes")

# if not SENTRY_ENABLED:
#     # no-op shim
#     logger.debug("SENTRY_ENABLED is false — Sentry not initialized.")
# else:
#     try:
#         import sentry_sdk
#         from sentry_sdk.integrations.fastapi import FastApiIntegration
#         from sentry_sdk.integrations.celery import CeleryIntegration
#         from sentry_sdk.integrations.logging import LoggingIntegration
#     except Exception as ex:  # catch ImportError and others
#         logger.warning("sentry-sdk not available or failed to import: %s. Continuing without Sentry.", ex)
#     else:
#         # optional integrations availability
#         SqlalchemyIntegration = None
#         RedisIntegration = None
#         try:
#             from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration as _Sql
#             SqlalchemyIntegration = _Sql
#         except Exception:
#             SqlalchemyIntegration = None

#         try:
#             from sentry_sdk.integrations.redis import RedisIntegration as _Redis
#             RedisIntegration = _Redis
#         except Exception:
#             RedisIntegration = None

#         logging_integration = LoggingIntegration(level=None, event_level="ERROR")
#         integrations = [FastApiIntegration(), CeleryIntegration(), logging_integration]

#         if SqlalchemyIntegration and os.getenv("SENTRY_CAPTURE_SQL", "false").lower() in ("1", "true", "yes"):
#             integrations.append(SqlalchemyIntegration())
#         if RedisIntegration and os.getenv("SENTRY_CAPTURE_REDIS", "false").lower() in ("1", "true", "yes"):
#             integrations.append(RedisIntegration())

#         def before_send(event: Dict[str, Any], hint: Dict[str, Any]) -> Dict[str, Any]:
#             request = event.get("request")
#             if request:
#                 data = request.get("data")
#                 if isinstance(data, dict):
#                     for k in list(data.keys()):
#                         if any(s in k.lower() for s in ("password", "secret", "token", "api_key", "auth")):
#                             data[k] = "[Filtered]"
#             return event

#         try:
#             sentry_sdk.init(
#                 dsn=os.getenv("SENTRY_DSN"),
#                 integrations=integrations,
#                 environment=os.getenv("SENTRY_ENVIRONMENT", "development"),
#                 release=os.getenv("SENTRY_RELEASE"),
#                 traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
#                 send_default_pii=False,
#                 before_send=before_send,
#             )
#             logger.info("Sentry SDK initialized (enabled).")
#         except Exception as init_exc:
#             logger.exception("Sentry SDK failed to initialize: %s", init_exc)
