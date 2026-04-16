# Security Policy

## Supported Versions

Only the latest release on the `main` branch receives security fixes.

| Version | Supported |
|---------|-----------|
| latest (`main`) | Yes |
| older releases | No |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.** Posting exploit details publicly puts all users at risk before a fix is available.

Instead, use GitHub's private reporting feature:

**[Report a vulnerability](https://github.com/quieromas-ai/orcai-mcp/security/advisories/new)**

Please include:
- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept (if safe to share)
- Affected versions or configurations

**Response expectations:**
- Acknowledgement within 48 hours
- Triage and initial assessment within 7 days
- Fix and coordinated disclosure timeline communicated as soon as possible

## Scope

**In scope:**
- Authentication or authorization bypass in the MCP server or REST API
- Bearer token leakage through logs, error responses, or API endpoints
- Remote code execution via the server process
- SQL injection or data exposure through the task/agent database
- Privilege escalation between agents or tasks

**Out of scope:**
- Vulnerabilities in user-managed infrastructure (nginx, OS, Docker host)
- Issues in upstream dependencies (report those to the respective project)
- Denial-of-service attacks requiring physical or authenticated access
- Security issues in third-party services (Anthropic API, Claude Code CLI)

## Disclosure Policy

We follow coordinated disclosure. A fix will be prepared and released before vulnerability details are made public. We will credit reporters in the release notes unless anonymity is requested.
