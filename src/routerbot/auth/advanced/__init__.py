"""Advanced authentication module for RouterBot.

Extends the base auth system with:

* **mTLS** - Mutual TLS client certificate authentication
* **Key Scoping** - Per-endpoint, per-model API key restrictions
* **Webhook Auth** - Delegate authentication to an external webhook
* **Token Exchange** - Exchange external IdP tokens for RouterBot tokens
* **Fine-grained Permissions** - Custom permission sets beyond RBAC roles
"""
