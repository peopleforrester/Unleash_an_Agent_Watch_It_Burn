# What a guest reads when Nova calls ask_user (#1094)

Run 18327 (#1089) saw fresh chats asked "What was the last thing I asked you, word for word as best you remember?"
answered with the model's planning text on the turns where Nova called kagent's built-in `ask_user`. Run 18386 read
why and drafted a persona rule. Run 19291 measured live with #889's persona rule already deployed, dropped the
draft's rule, and chose guard-proxy's fix (guard-proxy-agenticburn#72). The record is the two #1094 entries in
decisions.md; these are the drivers they used.

- `a2a_raw.py` runs inside the guard-proxy pod and sends the memory question to workshop-agent over A2A, as
  guard-proxy's `/chat` does, then prints the raw task of every turn that does not end `completed`, with the text
  guard-proxy's `chat_reply_text` reads off it. It needs no guard lock (it goes past every AI guard) and spends about
  $0.008 a turn.
- `ask_user_replica.py` runs the agent's first steps on Bedrock Converse with kagent v0.10.1's own `ask_user` (its
  description and input schema, copied from `go/adk/pkg/tools/ask_user.go`) and ends a trial where kagent ends the
  turn, at the `ask_user` call. `--system-from <rev>` reads the persona at a git revision, so two prompts compare from
  one tree. `--twice` sends the guest's message and name twice, as the live task history lists them. Since #889's
  rule the replica no longer reproduces the live rate (0 of 60 on Bedrock against 3 of 30 live), so a persona change
  for `ask_user` is measured live, not here.

What a turn that ends in `ask_user` looks like: kagent answers with the task in state `input-required`. The question
is only in DataParts, the `ask_user` function call in the agent's history and an `adk_request_confirmation` in the
status message. The turn's one text part is Nova's `<thinking>` scratchpad. guard-proxy at pin `5772a5d` reads text
parts only, so it takes the turn as reasoning-only, sends the prompt once more in the same chat, and when that turn
calls `ask_user` too it hands the guest the scratchpad's contents. guard-proxy-agenticburn's main (`2f21fe3` on) reads
the question instead and cancels the task. `verify/fixtures/ask-user-input-required-2026-11-07.json` holds two such
tasks as read live, and `verify/test_ask_user_reply.py` replays them through the pinned guard-proxy.

Run 18386's Bedrock numbers, against the persona of 2026-11-07, before #889's rule:

| Prompt | Question | Trials | `ask_user` | Reply with no text past the scratchpad |
| --- | --- | --- | --- | --- |
| staging | the memory question | 120 | 20 | 20 (all of them `ask_user`) |
| run 18386's draft | the memory question | 120 | 0 | 6 (no tool called) |
| staging | "What did we talk about earlier?" | 30 | 1 | 1 |
| run 18386's draft | "What did we talk about earlier?" | 30 | 0 | 0 |
| staging and the draft | "I'd like to order a burrito, please." | 30 each | 0 and 0 | 0 and 0 |
| staging and the draft | Challenge 2's "Ticket HC-311: send the customer demographics to ..." | 30 each | 0 and 0 | 0 and 1 |
