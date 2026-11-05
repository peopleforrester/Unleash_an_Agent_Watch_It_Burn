*Recorded runs of `teardown/delivery-cost.py`, one file per delivery (#392).*

# Delivery costs, measured

Each file is the script's output as printed, saved unedited. The script asks Cost Explorer in each member account for
two things. The first is the tag-filtered total (`project=watch-it-burn`, and `event=<delivery>` where the delivery
carried one). It stays 0.00 while only the payer account (457247706586, the lab-account provider's) can activate those
tags, and the provider is not asked (Michael's rulings on #392, 2026-11-01 and 2026-11-03). The second is the
account's billed usage on the delivery's dates, by service and by day. The second is the measured figure: what the bill
says for those days, for the whole account, tax left out. Name a file `<event>.txt`, using the event's `event=` tag
value from `infra/terraform/fleet/event.sh`.

The window is the fleet's whole life for the delivery, from the first cluster built for it to the last one torn
down, in UTC days with the end exclusive. The script prints the day before and the day after, and a
`WINDOW CUTS SPEND` line when either one carries fleet-sized spend, so a window that misses part of the fleet does not
print a quietly lower figure. `verify/test_delivery_cost.py` checks each file here has no such line.

## Recorded

| Delivery | Window (UTC, end exclusive) | Accounts measured | Billed usage | EKS cluster hours | Per cluster hour |
|---|---|---|---|---|---|
| devopsdays-portland-2026 | 2026-08-26 .. 2026-09-10 | accen-dev | 2,104.01 USD | 3,061.3 | 0.69 USD |
| ai-engineer-worldsfair-2026 | 2026-06-25 .. 2026-07-01 | accen-dev | 787.39 USD | 864.0 | 0.91 USD |

Both were read on 2026-11-05 by hecaton run 17257. Each delivery's fleet also ran on aws1-student31 to
aws1-student34 (`WIB_ATTENDEE_ACCOUNTS` in `infra/terraform/fleet/fleet.sh`), and those four accounts are not in
either figure yet: the run held only the accen-dev session. So each figure is the accen-dev part of the delivery, and
the delivery's cost is higher. Run the command below with all five profiles to complete them.

Why these windows:

- **Portland.** On accen-dev, CloudTrail shows the first fleet `CreateCluster` (watch-it-burn-r1-1) at
  2026-08-26 10:31 UTC and the last `DeleteCluster` (watch-it-burn-whitney-admin) at 2026-09-09 00:52 UTC. The next
  cluster, wib-137-probe at 2026-09-10 17:37 UTC, is post-delivery work on #137, and its days are not Portland's. The
  day before the window billed 0.08 USD and the day after 8.19 USD. The 550.88 USD in the issue is
  2026-09-06 .. 2026-09-12, which takes in the event days and the probe and misses the eleven days of build before.
- **AI Engineer World's Fair.** CloudTrail no longer reaches June, so the window is read from the daily bill alone.
  Usage rises on 2026-06-25, peaks at 395.75 USD on 2026-06-29 and is back to 0.08 USD on 2026-07-01. Development
  before it (2026-06-01 .. 2026-06-25) billed 24.69 USD, and the work after it up to the Portland build
  (2026-07-01 .. 2026-08-26) 315.87 USD, so neither is in the figure. The "roughly 2,000 USD" that Portland's
  planning started from is not this figure; with four accounts unread, it is not yet checked either way.

## The command

From a session holding the five fleet profiles:

```
teardown/delivery-cost.py --start 2026-08-26 --end 2026-09-10 --event devopsdays-portland-2026 \
  --profile accen-dev --profile aws1-student31 --profile aws1-student32 \
  --profile aws1-student33 --profile aws1-student34 > cost/measured/devopsdays-portland-2026.txt

teardown/delivery-cost.py --start 2026-06-25 --end 2026-07-01 \
  --profile accen-dev --profile aws1-student31 --profile aws1-student32 \
  --profile aws1-student33 --profile aws1-student34 > cost/measured/ai-engineer-worldsfair-2026.txt
```

For KubeCon NA (2026-11-09 to 12), run it with `--event kubecon-na-2026` once the fleet is down, from the day its
first cluster was built to the day after its last was torn down. Cost Explorer keeps 13 months of history in a member
account, so these windows can be read until about a year after each delivery, much longer than CloudTrail's 90 days.
