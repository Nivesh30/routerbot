"""Middleware infrastructure for RouterBot proxy.

All middleware in this package follows the same pattern: they are ASGI
middleware classes that can be added to the FastAPI application via
``app.add_middleware()``.

Available middleware:

- :class:`~routerbot.proxy.middleware.size_limit.RequestSizeLimitMiddleware`
  — reject requests whose body exceeds a configurable limit.
- :class:`~routerbot.proxy.middleware.logging_mw.RequestLoggingMiddleware`
  — structured JSON logging for every request.
- :class:`~routerbot.proxy.middleware.robots.RobotsTxtMiddleware`
  — respond to ``GET /robots.txt`` with ``Disallow: /``.

The ``request_id`` and ``cors`` cross-cutting concerns are already handled
in ``app.py`` using FastAPI's built-in CORS middleware and an ``@app.middleware``
decorator respectively.
"""
