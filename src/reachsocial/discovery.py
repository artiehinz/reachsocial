from __future__ import annotations

from copy import deepcopy
from html import escape
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from .catalog import Catalog, InputField, ServiceDefinition
from .config import Settings, get_settings, x402_network_label


def _schema_name(service: ServiceDefinition) -> str:
    return "".join(part.title() for part in service.id.replace("-", ".").split(".")) + "Input"


def _field_schema(field: InputField) -> dict[str, Any]:
    if field.format == "integer":
        schema: dict[str, Any] = {"type": "integer"}
        if field.minimum is not None:
            schema["minimum"] = field.minimum
        if field.maximum is not None:
            schema["maximum"] = field.maximum
    else:
        schema = {"type": "string"}
        if field.format == "url":
            schema["format"] = "uri"
        if field.max_length is not None:
            schema["maxLength"] = field.max_length
    schema["description"] = field.description
    if field.default is not None:
        schema["default"] = field.default
    return schema


def _service_request_schema(service: ServiceDefinition) -> dict[str, Any]:
    properties = {field.name: _field_schema(field) for field in service.input_fields}
    required = [field.name for field in service.input_fields if field.required]
    input_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }
    if required:
        input_schema["required"] = required
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["input"],
        "properties": {"input": input_schema},
        "title": f"{service.title} request",
        "description": f"Input for `{service.id}`. {service.description}",
    }


def _base_schemas() -> dict[str, Any]:
    nullable_string = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    nullable_integer = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
    nullable_boolean = {"anyOf": [{"type": "boolean"}, {"type": "null"}]}
    return {
        "ReachSocialError": {
            "type": "object",
            "additionalProperties": False,
            "required": ["code", "message", "retryable"],
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "retryable": {"type": "boolean"},
                "request_id": nullable_string,
            },
        },
        "ReachSocialErrorResponse": {
            "type": "object",
            "additionalProperties": False,
            "required": ["error"],
            "properties": {"error": {"$ref": "#/components/schemas/ReachSocialError"}},
        },
        "Media": {
            "type": "object",
            "additionalProperties": False,
            "required": ["type"],
            "properties": {
                "type": {"type": "string", "enum": ["image", "video", "audio"]},
                "url": nullable_string,
                "preview_url": nullable_string,
                "width": nullable_integer,
                "height": nullable_integer,
                "duration_seconds": nullable_integer,
                "expires_at": nullable_string,
            },
        },
        "Author": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "platform_id": nullable_string,
                "handle": nullable_string,
                "display_name": nullable_string,
                "avatar_url": nullable_string,
                "verified": nullable_boolean,
                "canonical_url": nullable_string,
            },
        },
        "Profile": {
            "type": "object",
            "additionalProperties": False,
            "required": ["platform", "canonical_url", "counts", "links", "fields"],
            "properties": {
                "platform": {"type": "string"},
                "canonical_url": {"type": "string", "format": "uri"},
                "platform_id": nullable_string,
                "handle": nullable_string,
                "display_name": nullable_string,
                "biography": nullable_string,
                "avatar_url": nullable_string,
                "verified": nullable_boolean,
                "private": nullable_boolean,
                "counts": {"type": "object", "additionalProperties": nullable_integer},
                "links": {"type": "array", "items": {"type": "string", "format": "uri"}},
                "fields": {"type": "object", "additionalProperties": True},
            },
        },
        "ContentItem": {
            "type": "object",
            "additionalProperties": False,
            "required": ["platform", "canonical_url", "platform_id", "media", "metrics"],
            "properties": {
                "platform": {"type": "string"},
                "canonical_url": {"type": "string", "format": "uri"},
                "platform_id": {"type": "string"},
                "type": nullable_string,
                "author": {"anyOf": [{"$ref": "#/components/schemas/Author"}, {"type": "null"}]},
                "text": nullable_string,
                "published_at": nullable_string,
                "expires_at": nullable_string,
                "media": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/Media"},
                },
                "metrics": {"type": "object", "additionalProperties": nullable_integer},
                "relationships": {"type": "object", "additionalProperties": True},
            },
        },
        "NormalizedData": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "profile": {"anyOf": [{"$ref": "#/components/schemas/Profile"}, {"type": "null"}]},
                "item": {"anyOf": [{"$ref": "#/components/schemas/ContentItem"}, {"type": "null"}]},
                "items": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/ContentItem"},
                },
                "next_cursor": nullable_string,
                "has_more": {"type": "boolean"},
            },
        },
        "ResponseMeta": {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "normalization_version", "response_shape", "latency_ms"],
            "properties": {
                "schema_version": {"type": "string", "const": "1.0"},
                "normalization_version": {"type": "string", "const": "v1"},
                "response_shape": {
                    "type": "string",
                    "enum": ["profile", "item", "feed", "stories"],
                },
                "latency_ms": {"type": "integer", "minimum": 0},
            },
        },
        "NormalizedResponse": {
            "type": "object",
            "additionalProperties": False,
            "required": ["request_id", "service", "status", "cached", "data", "meta"],
            "properties": {
                "request_id": {"type": "string"},
                "service": {"type": "string"},
                "status": {"type": "string", "const": "success"},
                "cached": {"type": "boolean"},
                "data": {"$ref": "#/components/schemas/NormalizedData"},
                "meta": {"$ref": "#/components/schemas/ResponseMeta"},
            },
        },
        "JobAccepted": {
            "type": "object",
            "additionalProperties": False,
            "required": ["job_id", "service", "status", "status_url", "expires_at"],
            "properties": {
                "job_id": {"type": "string"},
                "service": {"type": "string"},
                "status": {"type": "string", "const": "queued"},
                "status_url": {"type": "string"},
                "expires_at": {"type": "string"},
                "job_token": nullable_string,
            },
        },
        "JobStatus": {
            "type": "object",
            "required": ["job_id", "service", "status", "created_at", "expires_at"],
            "properties": {
                "job_id": {"type": "string"},
                "service": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["queued", "running", "succeeded", "failed", "expired"],
                },
                "created_at": nullable_string,
                "expires_at": {"type": "string"},
                "result": {"$ref": "#/components/schemas/NormalizedResponse"},
                "error": {"$ref": "#/components/schemas/ReachSocialError"},
            },
        },
    }


def _service_parameter(operation: dict[str, Any], service_ids: list[str]) -> None:
    for parameter in operation.get("parameters", []):
        if parameter.get("name") == "service_id":
            parameter["schema"] = {"type": "string", "enum": service_ids}
            parameter["description"] = "An enabled service ID from `GET /v1/services`."


def build_openapi_schema(app: FastAPI, catalog: Catalog) -> dict[str, Any]:
    schema = get_openapi(
        title=app.title,
        version=app.version,
        summary=app.summary,
        description=(
            "Provider-neutral social data for B2B applications and x402-capable agents. "
            "Discover executable services at `/v1/services` and the reviewed roadmap at `/v1/catalog`."
        ),
        routes=app.routes,
        servers=app.servers,
    )
    components = schema.setdefault("components", {})
    schema["info"]["contact"] = {"email": get_settings().public_contact_email, "url": str(get_settings().public_base_url).rstrip("/") + "/contact"}
    schema["info"]["x-guidance"] = (
        "Read /v1/services and /status.json for current availability and payment metadata. "
        "Public execution needs no ReachSocial API key. Send JSON {input: {...}} and a random "
        "32–255 character Idempotency-Key, saved before payment. Verify the actual x402 v2 "
        "challenge's network, native USDC asset, receiver, resource, and price before signing. "
        "On a lost response, POST the same input and key to /v1/payments/recover/{service_id}; "
        "recovery never requires another payment. Never generate a new key to retry an uncertain payment."
    )
    components.setdefault("schemas", {}).update(_base_schemas())
    components["securitySchemes"] = {
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "description": "Private ReachSocial B2B API key.",
        },
        "x402Payment": {
            "type": "apiKey",
            "in": "header",
            "name": "PAYMENT-SIGNATURE",
            "description": "x402 v2 payment signature after the initial 402 challenge.",
        },
        "jobToken": {
            "type": "apiKey",
            "in": "header",
            "name": "X-Job-Token",
            "description": "Opaque token returned once for an anonymous asynchronous job.",
        },
        "adminToken": {
            "type": "apiKey",
            "in": "header",
            "name": "X-Admin-Token",
            "description": "Protected owner-operations token; never used by public agents.",
        },
    }
    for service in catalog.discoverable_services():
        components["schemas"][_schema_name(service)] = _service_request_schema(service)

    available = catalog.public_services()
    sync_services = [service for service in available if not service.is_async]
    async_services = [service for service in available if service.is_async]
    paths = schema.get("paths", {})
    resolve = paths.get("/v1/resolve", {}).get("post")
    if resolve:
        resolve["security"] = [{"bearerAuth": []}]

    execute = paths.get("/v1/services/{service_id}/execute", {}).get("post")
    if execute:
        _service_parameter(execute, [service.id for service in sync_services])
        execute["description"] = (
            "Execute one enabled synchronous service. Use either a B2B Bearer key or complete "
            "the x402 challenge returned to an anonymous caller."
        )
        execute["security"] = [{"bearerAuth": []}, {"x402Payment": []}]
        execute["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "oneOf": [
                            {"$ref": f"#/components/schemas/{_schema_name(service)}"}
                            for service in sync_services
                        ]
                    }
                }
            },
        }
        execute["responses"]["200"] = {
            "description": "Normalized provider-neutral result.",
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/NormalizedResponse"}}
            },
        }
        execute["responses"]["402"] = {
            "description": "x402 payment is required.",
            "headers": {
                "PAYMENT-REQUIRED": {
                    "description": "Base64-encoded x402 v2 payment requirements.",
                    "schema": {"type": "string"},
                }
            },
        }

    create_job = paths.get("/v1/services/{service_id}/jobs", {}).get("post")
    if create_job:
        _service_parameter(create_job, [service.id for service in async_services])
        create_job["description"] = (
            "Accept one durable asynchronous job. Poll the returned status URL; anonymous x402 "
            "callers must retain the one-time job token."
        )
        create_job["security"] = [{"bearerAuth": []}, {"x402Payment": []}]
        create_job["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "oneOf": [
                            {"$ref": f"#/components/schemas/{_schema_name(service)}"}
                            for service in async_services
                        ]
                    }
                }
            },
        }
        create_job["responses"]["202"] = {
            "description": "Job accepted.",
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/JobAccepted"}}
            },
        }
        create_job["responses"]["402"] = (
            execute["responses"]["402"] if execute else {"description": "x402 payment is required."}
        )

    get_job = paths.get("/v1/jobs/{job_id}", {}).get("get")
    if get_job:
        get_job["security"] = [{"bearerAuth": []}, {"jobToken": []}]
        get_job["responses"]["200"] = {
            "description": "Current durable job state.",
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JobStatus"}}},
        }

    claim_credit = paths.get("/v1/jobs/{job_id}/credit", {}).get("post")
    if claim_credit:
        claim_credit["security"] = [{"bearerAuth": []}, {"jobToken": []}]

    owner_overview = paths.get("/v1/owner/overview", {}).get("get")
    if owner_overview:
        owner_overview["security"] = [{"adminToken": []}]

    schema["x-reachsocial-services"] = [
        {
            "id": service.id,
            "status": service.status,
            "execution": service.execution,
            "response_shape": service.response_shape,
            "price_cents": service.price_cents if service.status == "available" else None,
            "input_schema": f"#/components/schemas/{_schema_name(service)}",
        }
        for service in catalog.discoverable_services()
    ]
    # Concrete operations describe the existing parameterized runtime route. Only
    # reviewed public services belong in paid discovery; private adapters do not.
    for service in sync_services:
        if not execute:
            break
        operation = deepcopy(execute)
        operation["operationId"] = "execute_" + service.id.replace(".", "_")
        operation["summary"] = service.title
        operation["description"] = service.description + " Save your idempotency key before paying."
        operation["parameters"] = [
            parameter for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
            and parameter.get("name", "").lower() == "idempotency-key"
        ]
        for parameter in operation["parameters"]:
            parameter.update(required=True, schema={"type": "string", "minLength": 32, "maxLength": 255})
        operation["security"] = [{"x402Payment": []}]
        operation["requestBody"]["content"]["application/json"]["schema"] = {
            "$ref": f"#/components/schemas/{_schema_name(service)}"
        }
        examples = {
            "instagram.profile": "https://www.instagram.com/instagram/",
            "instagram.post": "https://www.instagram.com/p/EXAMPLE/",
            "instagram.feed": "https://www.instagram.com/instagram/",
            "instagram.highlight": "https://www.instagram.com/stories/highlights/12345678901234567/",
            "x.profile": "https://x.com/example", "x.feed": "https://x.com/example",
            "x.post": "https://x.com/example/status/1234567890",
            "tiktok.profile": "https://www.tiktok.com/@example", "tiktok.feed": "https://www.tiktok.com/@example",
            "tiktok.video": "https://www.tiktok.com/@example/video/1234567890",
            "youtube.channel": "https://www.youtube.com/@YouTube", "youtube.feed": "https://www.youtube.com/@YouTube",
            "youtube.video": "https://www.youtube.com/watch?v=EXAMPLE1234",
            "facebook.profile": "https://www.facebook.com/example", "reddit.post": "https://www.reddit.com/comments/abc123/",
        }
        if service.id in examples:
            operation["requestBody"]["content"]["application/json"]["examples"] = {
                "request": {"summary": "Illustrative input; example content IDs may not exist", "value": {"input": {"url": examples[service.id]}}}
            }
        operation["x-payment-info"] = {
            "protocols": [{"x402": {}}],
            "price": {"mode": "fixed", "currency": "USD", "amount": f"{service.price_cents / 100:.6f}"},
        }
        operation["responses"]["200"]["headers"] = {
            "PAYMENT-RESPONSE": {"description": "Base64-encoded x402 settlement response.", "schema": {"type": "string"}}
        }
        paths[f"/v1/services/{service.id}/execute"] = {"post": operation}
    return schema


def mcp_access_guidance(settings: Settings) -> str:
    if settings.oauth_enabled and settings.mcp_payment_approval_enabled and not settings.oauth_validation_wallets:
        return (
            "Connect to /mcp/ using OAuth, sign in with your wallet, and approve agent access. "
            "A service tool returns a payment_required request and browser payment link. "
            "Approve that exact request, then use get_reachsocial_request with its request ID. "
            "Login is not payment authorization; result retrieval never creates a payment."
        )
    return "MCP currently requires approved B2B Bearer access. Self-service OAuth/payment access is not publicly released. Use public REST with an x402-compatible client."


def llms_text(catalog: Catalog, settings: Settings) -> str:
    base = str(settings.public_base_url).rstrip("/")
    available = catalog.public_services()
    service_lines = []
    for service in available:
        endpoint = (
            f"/v1/services/{service.id}/jobs"
            if service.is_async
            else f"/v1/services/{service.id}/execute"
        )
        inputs = ", ".join(
            f"{field.name}{'' if field.required else '?'}" for field in service.input_fields
        )
        service_lines.append(
            f"- `{service.id}` — {service.execution}; ${service.price_cents / 100:.2f}; "
            f"POST `{endpoint}`; inputs: {inputs}; returns `{service.response_shape}`."
        )
    return "\n".join(
        [
            "# ReachSocial",
            "",
            "> Provider-neutral public social data for applications and agents. ReachSocial returns normalized metadata and source media URLs; it does not download or retain media bytes.",
            "",
            f"Official site: {base}",
            "",
            "## Machine entry points",
            "",
            f"- Executable service catalog: {base}/v1/services",
            f"- Reviewed service roadmap: {base}/v1/catalog",
            f"- OpenAPI: {base}/openapi.json",
            f"- Agent operating guide: {base}/agent.md",
            f"- Plain-text agent guide: {base}/agent.txt",
            f"- API catalog: {base}/.well-known/api-catalog",
            f"- Status: {base}/status.json",
            f"- MCP server card: {base}/.well-known/mcp.json (returns 503 while MCP is disabled)",
            "",
            "## Available services",
            "",
            *service_lines,
            "",
            "## Authentication and payment",
            "",
            "- B2B clients send `Authorization: Bearer <ReachSocial API key>` and a stable `Idempotency-Key`.",
            "- Anonymous public calls require a random 32–255 character `Idempotency-Key`, then receive an x402 v2 `402 Payment Required` challenge on "
            f"{x402_network_label(settings.x402_network)}. Sign the exact requirement and retry once with `PAYMENT-SIGNATURE`.",
            "- Never submit a wallet private key, provider token, or B2B API key as service input.",
            mcp_access_guidance(settings),
            "",
            "## Execution rule",
            "",
            "Choose the smallest available service matching the URL. Use `/execute` for synchronous services and `/jobs` for asynchronous services. For a job, retain its job token when present and poll the returned status URL until `succeeded`, `failed`, or `expired`; never recreate a pending paid job. A lost paid response can be recovered with the same key and input at `/v1/payments/recover/{service_id}` without another transfer.",
            "",
            "## Contract",
            "",
            "Successful results use schema `1.0` and normalization `v1`. Missing provider fields are null or empty; ReachSocial does not invent them and never exposes raw provider payloads or provider names.",
        ]
    )


def agent_text(catalog: Catalog, settings: Settings) -> str:
    base = str(settings.public_base_url).rstrip("/")
    return "\n".join(
        [
            "# ReachSocial agent guide",
            "",
            "ReachSocial is a paid, provider-neutral social-data surface. Inspect the executable catalog before choosing a service.",
            f"Configured payment network: {x402_network_label(settings.x402_network)} ({settings.x402_network}).",
            "Fetch the live service catalog and /status.json before wallet setup. Older search results may describe a previous release. Confirm the actual payment challenge before signing; stop if it disagrees with the network or price you approved.",
            "",
            "## Current public prices",
            "",
            *[
                f"- {service.id}: ${service.price_cents / 100:.2f} per {'job' if service.is_async else 'request'}."
                for service in catalog.public_services()
            ],
            "",
            "## Safe workflow",
            "",
            f"1. Fetch `{base}/v1/services`; do not infer availability from the roadmap.",
            "2. Resolve or normalize the requested public social URL.",
            "3. Select the smallest service and submit only its documented fields.",
            "4. Reuse one high-entropy idempotency key for retries of the same logical request; anonymous paid calls require it for lost-response recovery.",
            "5. Compare every x402 retry requirement with the original amount, asset, network, receiver, and resource before signing.",
            "6. Poll accepted jobs rather than repeating their paid POST. If the response or job token is lost, use `/v1/payments/recover/{service_id}` with the original key and input.",
            "7. Treat `private`, `not_found`, and `invalid_input` as terminal; retry only errors explicitly marked retryable.",
            "",
            "## Discovery",
            "",
            f"- Human documentation: {base}/docs/api",
            f"- Plain-text version of this guide: {base}/agent.txt",
            f"- OpenAPI: {base}/openapi.json",
            f"- LLM index: {base}/llms.txt",
            f"- Catalog: {base}/v1/catalog",
            f"- Operational status: {base}/status.json",
            f"- MCP server card: {base}/.well-known/mcp.json",
            "",
            f"Currently available services: {', '.join(service.id for service in catalog.public_services())}.",
            mcp_access_guidance(settings),
            "A 503 MCP response is not permission to bypass authentication or retry a payment.",
        ]
    )


def api_catalog(settings: Settings) -> dict[str, Any]:
    base = str(settings.public_base_url).rstrip("/")
    items: list[dict[str, str]] = [{"href": f"{base}/v1/catalog"}]
    if settings.mcp_enabled:
        items.append({"href": f"{base}/mcp"})
    linkset: list[dict[str, Any]] = [
        {"anchor": f"{base}/.well-known/api-catalog", "item": items},
        {
            "anchor": f"{base}/v1/catalog",
            "service-desc": [{"href": f"{base}/openapi.json", "type": "application/openapi+json"}],
            "service-doc": [{"href": f"{base}/docs/api", "type": "text/html"}],
            "status": [{"href": f"{base}/status.json", "type": "application/json"}],
        },
    ]
    if settings.mcp_enabled:
        linkset.append(
            {
                "anchor": f"{base}/mcp",
                "service-desc": [
                    {
                        "href": f"{base}/mcp/server-card",
                        "type": "application/mcp-server-card+json",
                    }
                ],
                "service-doc": [{"href": f"{base}/docs/api", "type": "text/html"}],
                "status": [{"href": f"{base}/status.json", "type": "application/json"}],
            }
        )
    return {"linkset": linkset}


def mcp_server_card(settings: Settings) -> dict[str, Any]:
    base = str(settings.public_base_url).rstrip("/")
    return {
        "$schema": "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json",
        "name": "dev.reachsocial/social-data",
        "title": "ReachSocial",
        "description": (
            "Public social data with wallet login and per-request browser payment approval."
            if settings.oauth_enabled and settings.mcp_payment_approval_enabled and not settings.oauth_validation_wallets
            else "Provider-neutral social data tools for approved B2B clients."
        ),
        "version": "0.2.0",
        "websiteUrl": base,
        "remotes": [
            {
                "type": "streamable-http",
                "url": f"{base}/mcp/",
                "supportedProtocolVersions": ["2025-06-18", "2025-03-26"],
            }
        ],
    }


def robots_text(settings: Settings) -> str:
    base = str(settings.public_base_url).rstrip("/")
    return "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "Allow: /llms.txt",
            "Allow: /agent.md",
            "Allow: /agent.txt",
            "Allow: /.well-known/api-catalog",
            "Allow: /openapi.json",
            "Allow: /v1/catalog",
            "Allow: /v1/services",
            "Disallow: /v1/owner/",
            "",
            f"Host: {base}",
            f"Sitemap: {base}/sitemap.xml",
        ]
    )


def sitemap_xml(catalog: Catalog, settings: Settings) -> str:
    base = str(settings.public_base_url).rstrip("/")
    paths = [
        "",
        "/catalog",
        "/pricing",
        "/docs/api",
        "/status",
        "/contact",
        "/legal/terms",
        "/legal/privacy",
        "/legal/acceptable-use",
        "/legal/refunds",
        *[f"/services/{service.id}" for service in catalog.discoverable_services()],
    ]
    urls = "".join(f"<url><loc>{escape(base + path)}</loc></url>" for path in paths)
    return '<?xml version="1.0" encoding="UTF-8"?>' + (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + urls + "</urlset>"
    )
