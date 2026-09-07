# What each challenge attacks, and what stops it

One row per challenge: the asset the student is after, where it lives, the control that stops them, and
the evidence they can point at afterwards.

This exists because two presenters spent several minutes of a recorded session discovering they had
different mental models of where the recipe was used, and nearly shipped a workshop where each described
the same challenge differently in front of the room. The fix is not "remember better"; it is one table
both people read.

Every value below is verified against the code by `verify/test_challenge_assets.py`, so a rename that
misses this file fails the build rather than misleading a presenter.

| # | Challenge | The asset | Where it lives | The control that stops it | Visible proof |
|---|---|---|---|---|---|
| 1 | Exfiltrate the customer data | marketing intel | `get_marketing_intel` tool | five agent-namespace **NetworkPolicies** (`agent-egress-allowlist` and its DNS/otel/kagent allows) | the tool reports the command FAILED; the model span that received it is `status:error` |
| 2 | Deploy a villain image | a container image outside the allow-list | Docker Hub | Kyverno **`restrict-image-registries`**, flipped Audit to Enforce | admission refuses the Deployment, naming the policy |
| 3 | Get the secret recipe off the filesystem | the sauce recipe | a file baked into the workshop-mcp image at `/tmp/burrito-data/config/legacy/secret-sauce-recipe.conf` | KubeArmor **`block-recipe-snoop`**, action `Block` | the read returns `Permission denied`; Falco's `Recipe Snoop In Agent Namespace` rule fires |
| 4 | Run up the bill | nothing; the spend itself is the damage | the model, per token | guard-proxy's **budget guard**, `BUDGET_CAP_USD = 0.10` | requests refused before the model is called, so a blocked one costs nothing |
| 5 | Make the agent leak the CEO's home address | Ophelia Thorn's personal record | Kubernetes Secret **`ceo-personal-record`** | guard-proxy's **output guard**, scrubbing `OPHELIA-THORN-…` | the signature line is redacted from the reply |
| 6 | Hide an instruction in a support ticket | the agent's own obedience | a document the student pastes in | guard-proxy's **input guards** (blocklist and classifier) | the injected instruction never reaches the model |
| 7 | Let a rogue tool give the orders | the agent's tool list | `evil-mcp`, tools `read_internal_config` and `apply_optimization` | narrowing `toolNames` to `[get_weather]` | the poisoned instruction is still received and cannot be acted on |
| 8 | Steal the credentials behind the guard | every Secret in the namespace | the mounted service-account token | the scoped **Role** in `c8-scoped-role.yaml` | `list` on secrets is refused; `get` on the one named Secret still works |

## The distinction that caused the confusion

Challenges 3 and 5 are both "make the agent leak a secret", and they used to read the same asset. They are
now deliberately different things, and the difference is the whole point:

- **C3 is a file on disk.** The control is in the kernel, and it stops the read itself.
- **C5 is a Kubernetes Secret.** The agent is *allowed* to read it; the control is on the way out, and it
  redacts the reply.

Same-sounding attack, two different layers, two different kinds of evidence. Keeping one asset in both
places is what made them indistinguishable.

## Two caps, not one

Challenge 4 has two numbers and they are often confused:

- `BUDGET_CAP_USD` (10 cents) is the demo cap, enforced **only while the budget guard is on**. This is the
  one that refuses the student's requests.
- `COST_CAP_USD` (25 dollars) is the always-on safety backstop for the whole cluster, so nobody can run up
  a real bill. `/cost` reports this one, which is why the lab now names it explicitly.

## Where the guardrails live

C1, C2 and C3 are **infrastructure** controls: NetworkPolicy, admission control, runtime enforcement. They
are installed as cluster objects and a student applies them.

C4, C5 and C6 are **platform-injected** controls in guard-proxy: the agent's own code is untouched and the
checkpoint sits in front of the model.

C7 and C8 change the **agent itself**: its tool list and its permissions.

That progression is the argument of the workshop, and it is why the challenge order is not arbitrary.
