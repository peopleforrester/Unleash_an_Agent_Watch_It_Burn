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
| devopsdays-portland-2026 | 2026-08-26 .. 2026-09-10 | all five | 2,865.86 USD | 3,764.6 | 0.76 USD |
| ai-engineer-worldsfair-2026 | 2026-06-25 .. 2026-07-01 | all five | 1,776.60 USD | 1,959.7 | 0.91 USD |

By account, in USD:

| Delivery | accen-dev | aws1-student31 | aws1-student32 | aws1-student33 | aws1-student34 |
|---|---|---|---|---|---|
| devopsdays-portland-2026 | 2,104.01 | 260.90 | 154.84 | 162.11 | 183.99 |
| ai-engineer-worldsfair-2026 | 787.39 | 249.39 | 245.85 | 245.33 | 248.64 |

The five are the fleet accounts in `WIB_ATTENDEE_ACCOUNTS` (`infra/terraform/fleet/fleet.sh`), and
`verify/test_delivery_cost.py` fails a file that leaves one out. Both files were written on 2026-11-05 by hecaton run
17307: accen-dev asked live (its figures match run 17257's read of the same day to the cent), and the four student
accounts read from `recorded/`, below. Tax posted inside Portland's window, left out, is 306.08 USD across the five
(206.97 on accen-dev, the rest on 2026-09-01 in the student accounts); the World's Fair window has none.

## recorded/

This run's session signs into accen-dev only. The four student accounts' Cost Explorer was read by escalation 809 of
hecaton run 17297, run in each account by a higher hecaton tier that holds its credentials on 2026-11-05 and posted on #392, one comment per
account. Each `recorded/<profile>/` holds that comment's two replies byte for byte: `cost-by-service-record-type.json`
(daily unblended cost by service and record type, 2026-06-24 .. 2026-09-12) and `eks-usage-by-usage-type.json` (daily
EKS usage by usage type, 2026-06-25 .. 2026-09-10), with `meta.json` naming the account and the comment. Together they
cover both windows and the day either side. The script reads them with `--recorded <dir>` in place of `--profile`,
refuses a reply that is paged, not daily, grouped otherwise or short of the window, and prints such an account's tag
figure as not read. The test replays them and checks each student account's block in both files against the replay.

Spend in the student accounts outside both windows is the Packt workshop of 2026-07-23 (its 250-cluster rehearsal on
2026-07-22; talks-knowledge `talks/register.md` section 9), 145.24 to 148.76 USD an account over 2026-07-22 ..
07-24, a different talk that shares the accounts; the rest of that time billed 0.39 USD or less an account. In the
student accounts Portland's spend runs 2026-09-02 .. 09-09, most of it on 09-07 and 09-08, and the World's Fair's
2026-06-27 .. 06-30; every edge day billed 0.01 USD or less.

Why these windows:

- **Portland.** On accen-dev, CloudTrail shows the first fleet `CreateCluster` at 2026-08-26 10:31 UTC and the last `DeleteCluster` (watch-it-burn-whitney-admin) at 2026-09-09 00:52 UTC. The next
  cluster, wib-137-probe at 2026-09-10 17:37 UTC, is post-delivery work on #137, and its days are not Portland's. The
  day before the window billed 0.08 USD and the day after 8.19 USD. The 550.88 USD in the issue is
  2026-09-06 .. 2026-09-12, which takes in the event days and the probe and misses the eleven days of build before.
- **AI Engineer World's Fair.** CloudTrail no longer reaches June, so the window is read from the daily bill alone.
  Usage rises on 2026-06-25, peaks at 395.75 USD on 2026-06-29 and is back to 0.08 USD on 2026-07-01. Development
  before it (2026-06-01 .. 2026-06-25) billed 24.69 USD, and the work after it up to the Portland build
  (2026-07-01 .. 2026-08-26) 315.87 USD, so neither is in the figure. The "roughly 2,000 USD" that Portland's
  planning started from was a forecast; the five accounts measured 1,776.60 USD.

## The command

As run on 2026-11-05, from a session holding accen-dev:

```
teardown/delivery-cost.py --start 2026-08-26 --end 2026-09-10 --event devopsdays-portland-2026 \
  --profile accen-dev --recorded cost/measured/recorded/aws1-student31 \
  --recorded cost/measured/recorded/aws1-student32 --recorded cost/measured/recorded/aws1-student33 \
  --recorded cost/measured/recorded/aws1-student34 > cost/measured/devopsdays-portland-2026.txt

teardown/delivery-cost.py --start 2026-06-25 --end 2026-07-01 \
  --profile accen-dev --recorded cost/measured/recorded/aws1-student31 \
  --recorded cost/measured/recorded/aws1-student32 --recorded cost/measured/recorded/aws1-student33 \
  --recorded cost/measured/recorded/aws1-student34 > cost/measured/ai-engineer-worldsfair-2026.txt
```

From a session holding all five profiles, give each as `--profile` instead.

For KubeCon NA (2026-11-09 to 12), run it with `--event kubecon-na-2026` once the fleet is down, from the day its
first cluster was built to the day after its last was torn down. Cost Explorer keeps 13 months of history in a member
account, so these windows can be read until about a year after each delivery, much longer than CloudTrail's 90 days.
