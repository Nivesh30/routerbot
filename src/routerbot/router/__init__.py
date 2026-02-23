"""RouterBot router package.

The router sits between the HTTP proxy layer and the provider adapters.
It provides:

- Model-name → deployment resolution
- Load balancing (round-robin, least-connections, latency-based, cost-based, weighted)
- Retry with exponential backoff
- Fallback chains
- Cooldown management for failing deployments

Typical usage::

    from routerbot.router.router import Router

    router = Router(config=loaded_config)
    response = await router.chat_completion(request)
"""

from routerbot.router.router import Deployment, Router

__all__ = ["Deployment", "Router"]
