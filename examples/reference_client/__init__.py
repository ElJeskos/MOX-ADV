"""Provider-neutral HTTP/JSON reference client for the module API."""

from examples.reference_client.client import (
    ModuleHttpClientV1,
    ModuleResultEnvelopeV1,
    ModuleTransportError,
    OpenApiContractError,
    TypedModuleErrorV1,
)

__all__ = [
    "ModuleHttpClientV1",
    "ModuleResultEnvelopeV1",
    "ModuleTransportError",
    "OpenApiContractError",
    "TypedModuleErrorV1",
]
