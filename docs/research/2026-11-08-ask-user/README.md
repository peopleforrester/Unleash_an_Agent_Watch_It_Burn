# The linked-list ask and kagent's ask_user (#889)

The community probe's off-topic beat asks "how do I reverse a linked list" three times and passes only on 3 of 3.
On the deployed prompt it was answered 19 of 30 times on 2026-11-07, each miss the bot's plan with no answer after it.
Run 18448 read the whole A2A task behind each reply and found where the answer went. The record is the
`2026-11-08 · #889 · run 18448` entry in decisions.md; these are the three drivers it used.

- `a2a_asks.py` sends the ask over A2A through an `agentgateway` port-forward, the way guard-proxy forwards it, and
  keeps each whole task: history, artifacts and status. It builds the reply as guard-proxy does and judges it with the
  probe's word test.
- `tools_list.py` lists workshop-mcp's and evil-mcp's tools from the live servers and writes them as Bedrock
  toolSpecs.
- `bedrock_replica.py` runs one ask on Bedrock Converse with a systemMessage from a file, those tools and kagent's own
  `ask_user`, so two prompts compare without a cluster.

What run 18448 read on watch-it-burn-community, at staging `efb66bb2` (the live systemMessage byte-equal to git's):

| Where | Prompt | Ask | Answered | `ask_user` |
| --- | --- | --- | --- | --- |
| live, A2A | staging | the linked list | 12 of 19 | 6 |
| replica | staging | the linked list | 35 of 40 | 4 |
| replica | #889's | the linked list | 39 of 40 | 0 |
| replica | staging | the memory question (#1089) | | 9 of 40 |
| replica | #889's | the memory question (#1089) | | 0 of 40 |

On the replica both prompts landed C6's HC-666 ask 40 of 40 and answered C3's recon with no tool call 20 of 20.

The replica is not the bot. Its staging rate of `ask_user` on the linked list (4 of 40) is below the live one (6 of
19), and tool order, a doubled user message and kagent's identity line did not close the gap. It is used to compare
two prompts, the memory question giving the larger `ask_user` count to compare on.
