# Attribution

This workshop and repository stand on the work of many open-source projects and
their communities. This file credits them. It carries attribution only; it does
not grant or state a license for this repository.

## Workshop

**Build a Platform, Unleash an Agent on it... and Watch it Burn!**
A hands-on workshop at AI Engineer World's Fair 2026 (San Francisco, Moscone West).

Presented by:

- **Michael Forrester** (Accenture)
- **Whitney Lee**

## Projects used

Every component below is the work of its own project and community and is used
here under its own license. Pinned versions are in
[`VERSIONS.lock`](VERSIONS.lock).

### Platform foundation

- **Argo CD** (GitOps): Cloud Native Computing Foundation
- **Kyverno** (admission policy, cosign image signing): Cloud Native Computing Foundation
- **Falco**, **Falcosidekick**, and **Falco Talon** (runtime detection and response): The Falco Project, Cloud Native Computing Foundation
- **Istio** ambient mode (service mesh, mTLS): Cloud Native Computing Foundation
- **SPIFFE / SPIRE** (workload identity): Cloud Native Computing Foundation
- **External Secrets Operator** (secrets): Cloud Native Computing Foundation
- **cert-manager** (certificates): Cloud Native Computing Foundation
- **Backstage** (developer portal): Cloud Native Computing Foundation, originally created at Spotify

### Observability

- **Datadog** (primary observability): Datadog, Inc.
- **Prometheus**: Cloud Native Computing Foundation
- **OpenTelemetry**: Cloud Native Computing Foundation
- **Grafana**, **Tempo**, and **Loki**: Grafana Labs

### Agent and AI layer

- **kagent** (the in-cluster agent): Cloud Native Computing Foundation
- **agentgateway** (MCP authorization): agentgateway.dev
- **LLM Guard** (input and output filtering): Protect AI
- **Amazon Bedrock** (the model backend): Amazon Web Services

### Provisioning and tooling

- **Terraform** and the community **EKS**, **VPC**, and **EKS Pod Identity** modules: HashiCorp and the Terraform AWS Provider community
- **Amazon EKS**: Amazon Web Services
- **Kubernetes**, **Helm**, and **kubectl**: Cloud Native Computing Foundation

## Notes

Project names and logos are trademarks of their respective owners. Listing a
project here does not imply that project endorses this workshop. The Cloud
Native Computing Foundation is a project of the Linux Foundation; consult each
project for its current governance and license.
