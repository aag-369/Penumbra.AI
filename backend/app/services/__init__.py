"""Service layer: business logic between the API and the ORM.

Only classes are exported here. Exporting lowercase singletons alongside
same-named submodules makes ``import app.services.portfolio_service`` resolve to
the *instance* rather than the module, which is a subtle and unpleasant bug.
Services are namespaces of static and class methods; the one stateful service,
:class:`KeystoreService`, is reached through :func:`get_keystore`.
"""

from .audit_service import AuditService
from .keystore_service import KeystoreService, get_keystore
from .portfolio_service import ParsedPortfolio, PortfolioService
from .user_service import UserService

__all__ = [
    "AuditService",
    "KeystoreService",
    "get_keystore",
    "PortfolioService",
    "ParsedPortfolio",
    "UserService",
]
