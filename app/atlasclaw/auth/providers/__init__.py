"""Provider factory — creates the correct AuthProvider from AuthConfig."""

from __future__ import annotations

from app.atlasclaw.auth.config import AuthConfig
from app.atlasclaw.auth.providers.base import AuthProvider


def create_provider(config: AuthConfig) -> AuthProvider:
    """
    Instantiate the AuthProvider specified by ``config.provider``.

    Raises:
        ValueError: if the provider name is not recognised.
    """
    provider_type = config.provider.lower()

    if provider_type == "none":
        from app.atlasclaw.auth.providers.none import NoneProvider
        return NoneProvider(default_user_id=config.none.default_user_id)

    if provider_type == "smartcmp":
        from app.atlasclaw.auth.providers.smartcmp import SmartCMPProvider
        sc = config.smartcmp.expanded()
        return SmartCMPProvider(
            validate_url=sc.validate_url,
            api_base_url=sc.api_base_url,
        )

    if provider_type == "oidc":
        from app.atlasclaw.auth.providers.oidc import OIDCProvider
        oidc = config.oidc.expanded()
        return OIDCProvider(
            issuer=oidc.issuer,
            client_id=oidc.client_id,
            jwks_uri=oidc.jwks_uri,
        )

    if provider_type == "api_key":
        from app.atlasclaw.auth.providers.api_key import APIKeyProvider
        return APIKeyProvider(keys=config.api_key.keys)

    if provider_type == "local":
        from app.atlasclaw.auth.providers.local import LocalAuthProvider
        return LocalAuthProvider()

    raise ValueError(
        f"Unknown auth provider: {config.provider!r}. "
        "Supported values: 'none', 'smartcmp', 'oidc', 'api_key', 'local'."
    )



__all__ = ["create_provider"]
