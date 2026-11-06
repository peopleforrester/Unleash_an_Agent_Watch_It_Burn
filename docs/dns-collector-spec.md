# DNS collector build spec (for the provisioning app)

Hand this to the provisioning agent. It is the sibling of `docs/beacon-collector-spec.md`, for the same
authorized, disposable workshop: we stage the Challenge 1 exfil on our own throwaway clusters and then watch it
in a room view, so the audience sees the data leave and, once the control is installed, sees it stop. This spec
formalizes the DNS stage already designed in benign functional terms in
`docs/research/2026-10-31-c1-dns-exfil-beat.md`. Goal: give the DNS stage the same stateful collector and room
view the beacon already has, so the second exfil door is visible on a projector beside the first. This is the
parallel construction of the accepted beacon pattern, at the same altitude: it names the channel, the pieces to
build and the checks that prove them. It does not specify how the agent's tool produces the lookups; that piece
is written at build time inside the lab, under the same review as the existing C1 beat.

## What exists today

The beacon collector in `docs/beacon-collector-spec.md` catches the Challenge 1 HTTPS exfil: the agent is talked
into POSTing marketing intel to `/beacon`, the collector stores it, and `/beacon/view` shows the room a live
count and recent payloads. That covers stage 1 and stage 2 of the beat.

The DNS stage (stage 2b in the research doc) has no collector yet. On a cluster with the stage 2 egress policy
applied, the HTTPS POST is held, because a NetworkPolicy matches addresses and ports. A DNS query is a different
shape: `policies/network-policies/per-namespace/agent-allow-dns.yaml` opens UDP and TCP 53 to `kube-system` so
pods resolve Bedrock and in-cluster names, CoreDNS forwards a name it does not serve to an upstream resolver, and
that resolver walks to whichever authoritative server owns the zone. The query name itself can carry data, and
the L3/L4 allowlist never sees it. `challenges/c1-exfil-s3/dns-exfil.py` is the in-image tool side of this: it
builds one query name `<marker>.<demographics>.<collector-zone>` and looks it up with the stdlib resolver that
`python:3.12-slim` already ships, so the tool image stays `curl` and `ca-certificates` only. What is missing is
the far end: a collector that owns `<collector-zone>`, answers the lookup so it succeeds, records it, and shows
the room the data arriving. This spec is that far end (#726, split into #940 for the spec itself).

## Routes to add (on the provisioning service and its zone)

Two pieces: an authoritative nameserver that owns the delegated zone (the ingest), and a `GET /dns/view` page on
the provisioning app (the room view), beside `/beacon/view`. Storage is the provisioning app's existing `/data`
volume, the same deploy and storage pattern the beacon uses (Flask on the provisioning app, records under
`/data`).

### 1. Authoritative nameserver for the delegated zone (ingest)

- Serve as the authoritative nameserver for the delegated exfil subdomain (a subdomain of `agenticburn.com`,
  delegated per the one hand-off below). UDP and TCP 53 must reach it from the internet.
- Answer every query under the zone so the caller sees a successful lookup: return a valid answer with NOERROR
  (a fixed A record for the zone is enough) for any name at any depth under the zone. The lookup succeeding is
  what keeps the tool's resolver call clean and the demo predictable; a name that returned no address would
  still have carried its data, but answering removes a failing path from the picture.
- Append one record per query to durable storage on the existing `/data` volume (survives redeploys): a SQLite
  table `dns_queries` or an appended JSONL file. Fields:
  `{ ts: <iso8601 UTC>, remote_ip: <source address of the query, the forwarding resolver>, qname: <the full query name, truncated to the 255-byte DNS name limit> }`.
- Increment a running total counter.
- Do not validate or constrain the query name's shape: it is arbitrary, chosen by the sender, riding in a label,
  and the collector records it as received.

### 2. `GET /dns/view`: the room view

- A `GET /dns/view` page on the provisioning service, beside `/beacon/view`, rendered the same way: a big total
  count, then a table of the last ~50 queries (`ts`, `remote_ip`, `qname`), and below it the reassembled payload.
- Reassembly: the delivered payload is carried across one or more query names under the zone. The view
  reassembles it in sequence, ordering the recorded names by the marker and the sequence the tool puts in each,
  then concatenating the carried labels in that order into the delivered payload. The current beat in
  `dns-exfil.py` delivers the whole demographic summary in a single label, so for it the in-sequence reassembly
  is that one label decoded; the view is written to concatenate in order when a payload spans several labeled
  queries. Show the reassembled text, for example the "how many customers are humans versus vampires"
  demographic shares, so the room reads the exfiltrated content and not only that a query arrived.
- Auto-refresh ~5s (`<meta http-equiv="refresh" content="5">` is fine) so the room watches the queries arrive
  live. Keep it readable on a projector.

### 3. (optional) `POST /dns/reset` or a button on the view

Clear the records, the counter and the reassembly between rehearsal runs, as the beacon has.

## Notes

- **Storage** goes under the same `/data` volume the provisioning app already mounts, the same place the beacon
  keeps its records.
- **Pedagogy:** the DNS collector sits beside the beacon collector so the two doors are shown together. On the
  Community cluster, or an attendee cluster before the student applies the control, both the beacon POST and the
  DNS query land. With the stage 2 egress policy applied, the beacon count holds still while the DNS view keeps
  filling: the room sees an enforced, green NetworkPolicy and the data leaving anyway, through the one door the
  policy cannot match. Once the FQDN-aware control in `challenges/c1-exfil-s3/fix/` is applied, the DNS view
  stops moving too. The collector is what makes that whole arc visible on the projector.
- **The tool side is already built** and covered offline (`challenges/c1-exfil-s3/dns-exfil.py`,
  `verify/test_c1_dns_exfil.py`); it adds no encoder and no new binary. How the lookups are produced inside the
  lab stays at build time, under the same review as the existing C1 beat, exactly as the research doc keeps it.
- **Where the nameserver runs** (the provisioning host or a small dedicated one) is settled at build time; the
  record store and the view live with the provisioning app either way.

## The one zone hand-off (on Michael's side, not provisioning's)

The exfil subdomain must be delegated to the collector's nameserver. That delegation is a registrar change on
Michael's side (NS records for the subdomain on `agenticburn.com`, in Namecheap per `infra/dns/README.md`), the
same kind of one-time hand-off as the beacon's apex repoint. Once the nameserver and `/dns/view` are live on the
provisioning service, tell Michael and report the zone and the nameserver address; he adds the delegation. The
provisioning agent does not touch the registrar, the same way it does not touch apex for the beacon.

## Both domains

The room is shown `burritobot.co`, so the `/dns/view` page is served on both hosts beside the beacon view:
`agenticburn.com/dns/view` and `burritobot.co/dns/view`, routed into the provisioning app the way `/beacon/view`
already is on both. The exfil zone itself stays a delegated subdomain of `agenticburn.com`: the lookups travel to
the authoritative nameserver by DNS delegation, independent of which host the room's screen shows, so the
collector's records and its one shared count do not change with the domain. A later profile that wants the zone
under `burritobot.co` as well makes that second delegation in its own issue.
