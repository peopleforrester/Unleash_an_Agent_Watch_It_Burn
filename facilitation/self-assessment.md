*A checklist you run against your OWN platform to find which agent failure modes you're not covering — including ones not demonstrated live. Usable with no workshop-specific tooling.*

# Self-Assessment — Is Your Agent Platform Covered?

Run this against your own platform. None of it requires anything from this workshop — every item is a question about controls you either have or don't. Score honestly: a "no" or "not sure" is a gap to close, not a failure.

For each item: **Yes / No / Not sure**. Anything that isn't a clear Yes is on your list.

## A. The platform controls (the part you probably already have)

1. Does your admission layer reject non-compliant workloads — not just report them? Have you confirmed the policy is in enforce, not audit?
2. Can any agent or service account create or modify its own RBAC (Roles, RoleBindings, ClusterRoles, ClusterRoleBindings)? It should not be able to.
3. Is your agent's service account scoped to exactly the verbs and namespaces it needs — and nothing more?
4. Are infrastructure changes outside your GitOps flow blocked at admission, or only reverted after the fact? Both is better than either alone.
5. Does your GitOps reconciler actually self-heal drift, and have you tested it recently?
6. Have you verified RBAC and admission interact the way you think? (RBAC is evaluated first — a too-tight role can mask a missing admission policy.)

## B. Input — what reaches the agent (commonly missing)

7. Is anything inspecting prompts before they reach the agent, or does every input go straight through?
8. Can a crafted instruction embedded in user input, a document, or a webpage redirect your agent's behavior? Have you tested it?
9. If you do inspect input, can that inspection actually *reject* a request, or only flag it?
10. Do you know whether your input inspection is rule-based or model-based — and have you accounted for what each one misses?

## C. Output — what the agent returns (commonly missing)

11. Is anything inspecting the agent's responses before they reach the user or a downstream system?
12. If your agent can read a secret, a config value, or PII, what stops it from returning that in a response?
13. Can your output control *block* a response, or only *redact* parts of it? Do you know which you need?
14. Have you tested output inspection against your own real sensitive-data shapes, not just generic examples?

## D. Tools and agency — what the agent can call (commonly missing)

15. Does your agent have an explicit allowlist of tools it may call, or does it inherit every tool a connected server exposes? (Inheriting all of them is the common footgun.)
16. Do you trust the description/metadata of every tool your agent can see? A poisoned tool description can induce calls you never intended.
17. Is there an authorization layer that can deny a specific tool call at runtime — independent of whether the model decides to make it?
18. For high-impact tools, is there a human-approval gate, and have you confirmed it actually enforces (not just displays)?
19. If you added an untrusted tool server tomorrow, what new actions would your agent suddenly be able to take?

## E. Observability — the lens that can leak (failure mode often NOT demoed)

20. Does your tracing/telemetry capture full prompt and response content? If yes — is that content governed the same way your output path is?
21. If your output control blocks a sensitive value from a response, could that same value still land in a trace, log, or span?
22. Do you have a redaction step on the telemetry path that is symmetric with your output control?
23. Is captured content retained, and for how long, and who can read it?

## F. Resilience and operations (failure modes not demoed live)

24. When your agent behaves unpredictably, do you have a reliable, repeatable path to the intended outcome, or does everything depend on the model cooperating?
25. Do your controls fail closed or fail open? When the inspection service is down, does traffic block or sail through?
26. Are your agent's isolation boundaries real (separate clusters / strong tenancy) or namespace-only? What's the blast radius if one agent is compromised?
27. Do you test your controls' *before* and *after* states, or only assume the "on" state works?
28. Can you tear down agent state — including captured trace content — cleanly and verify nothing sensitive persists?

## Scoring

- **Section A mostly Yes:** good — your platform fundamentals are sound. This is the big surface and it's the easy win.
- **Sections B, C, D with No / Not sure:** these are the agent-specific gaps. They're smaller in area but this is where an agent changes your threat model. Prioritize them.
- **Section E No / Not sure:** your observability may be re-leaking what you just blocked. Close it symmetrically.
- **Section F No / Not sure:** your controls may work in the demo and fail on a bad day. Test before/after, fail closed, and confirm your isolation is real.

The pattern: the platform handles the bulk. The thin slice — input, output, tools, and the telemetry sink — is what you have to add for agents. Use this list to find your own thin slice.
