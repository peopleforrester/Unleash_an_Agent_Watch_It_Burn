*Recorded runs of `teardown/delivery-cost-estimate.py`, one file per delivery (#392).*

# Delivery cost estimates

Since 2026-11-05 a delivery's cost is measured, not estimated: `teardown/delivery-cost.py` reads each member
account's billed usage on the delivery's dates from Cost Explorer, and its runs are in `cost/measured/`. The estimator
below stays for a breakdown by resource where the bill gives only a service total.

Cost Explorer cannot give a tag-filtered figure for this fleet. Only the payer account can activate the `project`
and `event` cost-allocation tags, and that account (457247706586) belongs to the lab-account provider, which is not
asked (Michael's ruling on #392, 2026-11-01). Each delivery is therefore estimated from what the member accounts can
read themselves, and the run is kept here so the number is not re-derived from another estimate next time.

Each file is the script's output as printed, saved unedited: the line items, the estimated total, each account's
unfiltered Cost Explorer total for the same window (an upper bound, never the workshop's cost), and what the estimate
leaves out. Name it `<event>.txt`, using the event's `event=` tag value from `infra/terraform/fleet/event.sh`.

## Owed

| Delivery | Window (UTC, end exclusive) | Status |
|---|---|---|
| devopsdays-portland-2026 | 2026-09-06 .. 2026-09-12 | Not yet run. CloudTrail keeps 90 days of event history, so this window can be read until 2026-12-05. |
| ai-engineer-worldsfair-2026 | 2026-06-29 week | Out of reach. The window is past CloudTrail's 90 days, and the script refuses it. |

The Portland run, from a session holding the five fleet profiles:

```
teardown/delivery-cost-estimate.py --start 2026-09-06 --end 2026-09-12 --region us-west-2 \
  --event devopsdays-portland-2026 \
  --profile accen-dev --profile aws1-student31 --profile aws1-student32 \
  --profile aws1-student33 --profile aws1-student34 > cost/estimates/devopsdays-portland-2026.txt
```

For KubeCon NA (2026-11-09 to 12), run it with `--event kubecon-na-2026` over that week once the fleet is down, and
before 2027-02-07, when CloudTrail starts to drop the week.
