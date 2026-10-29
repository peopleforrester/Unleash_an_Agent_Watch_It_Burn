<!-- ABOUTME: The MCP server vetting checklist from Michael's Toronto keynote, handed out at C7 and linked from the
     ABOUTME: KubeCon NA 2026 close (#649). Everything below the marker is a verbatim copy: change it upstream, not here. -->

# Handout: MCP server vetting checklist

C7 showed a poisoned tool blocked because it was never registered. This is the checklist that decides what gets
registered: the six approval gates from Michael's keynote "Governing MCP for a Workforce the Size of a City", MCP Dev
Summit Toronto, 2026-10-06. It is copied unchanged from that talk's published materials.

- Source: `peopleforrester/mcp-for-a-city`, `04-approval-gates-checklist/approval-gates.md` at commit
  `a3e585f011343827bb3468ed1b7b6c1609057271`
  (https://github.com/peopleforrester/mcp-for-a-city/blob/a3e585f011343827bb3468ed1b7b6c1609057271/04-approval-gates-checklist/approval-gates.md)
- Licence: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/), Michael Rishi Forrester. Nothing below the marker
  is changed; this header is the only addition.
- Source sha256: `670e7dab71c09ac03bb42ae06ab1e1e55ec52a6f3fa71683b1f228001b236a8b`
- Copied out: 2026-10-29

To refresh it, replace everything below the marker with the source file as it is now, and update the commit and
sha256 above. `verify/test_mcp_vetting_handout.py` fails if the copy and the stamp disagree.

<!-- verbatim copy below -->
<!--
ABOUTME: The six approval gates from the keynote, as a checklist a platform team can use on Monday.
ABOUTME: Generated from the site's gate data; edit src/data/gates.ts in peopleforrester/mcp-city, not this file.
-->

# MCP server approval: six gates before yes

From "Governing MCP for a Workforce the Size of a City", MCP Dev Summit Toronto, 6 October 2026. A request to allow an MCP server passes through these in order. Walk one interactively at https://mcp.michaelrishiforrester.com/#gates.

## Gate 1: Do we have a relationship with the vendor?

Who answers: Procurement and security

Ask:

- Is this the vendor's own server, or a community fork?
- Do we have a contract, and a support path?
- Who maintains it, and how fast do they fix security issues?

Verify:

- [ ] Registry namespace matches the vendor's domain
- [ ] The server calls the vendor's own first-party API
- [ ] Contract and security contact on file

Anthropic requires first-party API ownership and a named company contact for every directory listing. MintMCP tiers servers Gold, Silver and Bronze by vendor standing.

What people build when this gate says no, with no explanation: A fork of the vendor's server from a personal account, installed from a laptop, because the official one was never listed.

Sources:

- [Anthropic, connector review criteria](https://claude.com/docs/connectors/building/review-criteria)
- [MintMCP, MCP server security and vetting](https://www.mintmcp.com/blog/mcp-server-security-vetting)

## Gate 2: Is there a real business need?

Who answers: The business owner

Ask:

- What job does this do, and who asked for it?
- Is it core to the business, or a convenience?
- What will people build themselves if we say no?
- What data does it reach?

Verify:

- [ ] A named business owner
- [ ] A written use case
- [ ] A data classification for everything it touches

No MCP source weighs business need. This is ordinary third-party risk intake, and it is the gate that stops "everyone wants every server, now".

What people build when this gate says no, with no explanation: A no with no explanation. The user has an agent that writes code, so the agent writes the integration instead, against whatever interface is still open.

Sources:

- [Cerbos, MCP server vetting checklist for enterprises](https://www.cerbos.dev/blog/mcp-server-vetting-checklist)

## Gate 3: Is it well built, and wrapped where we needed?

Who answers: The platform team

Ask:

- One risk level per tool: read and write are separate tools
- Every tool annotated: title, read-only or destructive
- Descriptions describe; they never instruct
- If wrapped, the wrapper exchanges tokens and never forwards the user's

Verify:

- [ ] Run every tool in MCP Inspector with valid input
- [ ] Diff every tool description on every new version
- [ ] Confirm the upstream token is not the client's

Anthropic rejects any single tool that accepts both safe and unsafe HTTP methods. The specification says the server MUST NOT pass through the token it received from the client.

What people build when this gate says no, with no explanation: The mail client's own automation interface, driven by a script the agent wrote, with the user's full session and no tool boundary at all.

Sources:

- [Anthropic, connector review criteria](https://claude.com/docs/connectors/building/review-criteria)
- [MCP specification 2026-07-28, authorization security considerations](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations)
- [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
- [FastMCP, proxy servers](https://gofastmcp.com/servers/proxy)

## Gate 4: Does it speak the current spec?

Who answers: The platform team

Ask:

- Implements the 2026-07-28 revision
- Answers server/discover
- Sends Mcp-Method and Mcp-Name headers
- Says what it still does with the deprecated features

Verify:

- [ ] Call server/discover and read the revision back
- [ ] Watch the headers on a real call
- [ ] Testable without the vendor's cooperation

The first question on SSOJet's CISO list is which revision the server implements, and three of the next four are testable from outside.

What people build when this gate says no, with no explanation: An old-revision server behind a hand-written shim that keeps a session alive, and nobody knows which era the gateway is talking to.

Sources:

- [MCP specification 2026-07-28, changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
- [SSOJet, 12 questions a CISO will ask about your MCP server](https://ssojet.com/blog/ciso-mcp-server-security-questions)

## Gate 5: Does it meet our security standards?

Who answers: The platform team

Ask:

- OAuth 2.0, not static keys, not open access
- Tokens bound to this server as the audience
- No token passthrough to upstreams
- Scopes we can restrict
- A revocation path and a token lifetime

Verify:

- [ ] Probe authorization server discovery
- [ ] Present a foreign-audience token; expect rejection
- [ ] Base rate: 40.55 percent of live servers measured had no authentication at all

Anthropic requires OAuth 2.0 for authenticated services. SSOJet's questions two to eight cover discovery, audience and passthrough. Zhou et al. measured 7,973 live remote servers.

What people build when this gate says no, with no explanation: The approved browser launched with remote debugging on, so the agent drives the web app as the user, under the user's cookies, with nothing to revoke.

Sources:

- [Anthropic, submit a connector to the directory](https://claude.com/docs/connectors/building/submission)
- [SSOJet, 12 questions a CISO will ask about your MCP server](https://ssojet.com/blog/ciso-mcp-server-security-questions)
- [MCP specification 2026-07-28, authorization security considerations](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations)
- [Zhou et al., arXiv 2605.22333](https://arxiv.org/abs/2605.22333)

## Gate 6: Is the vendor certified? SOC 2, ISO 27001

Who answers: Procurement and security

Ask:

- SOC 2 Type II report, not a badge on a website
- ISO 27001 certificate, current
- Where data is processed, how long it is kept, how it is encrypted
- An incident response path for a compromised MCP session

Verify:

- [ ] The audit report on file, dated
- [ ] Data-handling answers in writing
- [ ] A named incident contact

MintMCP: verify "SOC 2 Type II audited status, not marketing claims". SSOJet's last question is the incident response path.

What people build when this gate says no, with no explanation: A free tier signed up with a personal email, holding company data, with no contract and nobody to call when it leaks.

Sources:

- [MintMCP, MCP server security and vetting](https://www.mintmcp.com/blog/mcp-server-security-vetting)
- [SSOJet, 12 questions a CISO will ask about your MCP server](https://ssojet.com/blog/ciso-mcp-server-security-questions)

## Behind all six

Say no when you must, and explain why. The worst thing you can do is say no with no reason and no path.
