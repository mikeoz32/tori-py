# Security Policy

## Supported Versions

Until the first public release, security fixes target the current default
branch. After release, the latest minor release of each independently versioned
package is supported. Older `0.x` minors are not guaranteed security updates.

## Reporting a Vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private
security advisory reporting for
[`mikeoz32/tori-py`](https://github.com/mikeoz32/tori-py/security/advisories/new).
Include affected packages and versions, impact, reproduction steps, and any
known mitigation. Do not include real credentials, personal data, or production
payloads.

The maintainer will acknowledge a report when practical, investigate it, and
coordinate disclosure and fixed releases according to severity. No response or
fix deadline is guaranteed.

## Scope

Security-sensitive behavior includes dependency injection boundaries, request
and message parsing, OpenAPI exposure, SQL transactions, broker authentication
and TLS, redelivery, checkpoint fencing, and shutdown behavior. Application
authorization, secret management, idempotency, outbox/inbox persistence, broker
permissions, and deployment hardening remain application or operator concerns
unless a package explicitly states otherwise.
