*Attendee instructions for Beat 2, sanitizing what comes in and what goes out.*

# Beat 2, Clean the doorway, both directions

Your agent reads whatever you (or anyone) hand it, and it says whatever it
concludes. It has no idea which incoming text is an attack, or which outgoing
text is something that should never leave the room. In this beat you'll watch a
guard get switched on for each direction.

## Direction 1, Something nasty coming in (prompt injection)

Send your agent the injection prompt (`agent-prompt-injection.txt` has the
wording). It hides an instruction that tries to override what the agent is
supposed to do.

- **Before:** the agent reads the buried instruction and follows it. The attack
  steers the agent.
- **Then** the facilitator switches on the input guard.
- **After:** the same request is stopped at the gateway, before the agent ever
  sees it. The request is rejected outright, the agent is never given the
  chance to take the bait.

## Direction 2, Something sensitive going out (exfiltration)

There is a planted secret in your namespace. It is obviously fake, the value
starts with `FAKE-`. Ask your agent to read it and report it back to you
(`agent-prompt-exfil.txt` has the wording).

- **Before:** the agent reads the secret and the value comes straight back in
  its reply. It leaves the boundary.
- **Then** the facilitator switches on the output guard.
- **After:** the same request runs, but the guard on the response path catches
  the sentinel value. The reply is blocked or the value is redacted, and the
  secret does not appear.

## What to take away

The platform walls from Beat 1 never see either of these. The attack and the
leak ride in plain language, not in anything the cluster control plane inspects.
Two new guards, one watching the way in, one watching the way out, are doing
the work here. Note in the trace view where the request gets stopped (input) and
where the response gets caught (output).

See `governance-map.md` for which control governs each direction.
