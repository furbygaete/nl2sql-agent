# SUBSYSTEMS

## Registry
| ID | Name | Type | Status | Purpose | Spec |
|---|---|---|---|---|---|
| SS-01 | Core Engine | core | active | Main NL2SQL logic, orchestration, and runtime behavior in `src/`. | `.galdr/subsystems/core-engine.md` |
| SS-02 | Data Assets | support | active | Local datasets, fixtures, and domain data in `data/`. | `.galdr/subsystems/data-assets.md` |
| SS-03 | Automation Scripts | support | active | Helper scripts for setup, maintenance, and tooling in `scripts/`. | `.galdr/subsystems/automation-scripts.md` |
| SS-04 | Test Suite | support | active | Unit/integration/e2e verification in `tests/`. | `.galdr/subsystems/test-suite.md` |
| SS-05 | Deployment | support | active | Container build + local orchestration: `Dockerfile`, `.dockerignore`, `docker-compose.yml`. | `.galdr/subsystems/deployment.md` |

## Dependency Graph
```mermaid
graph TD
  SS01[SS-01 Core Engine]
  SS02[SS-02 Data Assets]
  SS03[SS-03 Automation Scripts]
  SS04[SS-04 Test Suite]
  SS05[SS-05 Deployment]

  SS01 --> SS02
  SS03 --> SS01
  SS04 --> SS01
  SS05 --> SS01
  SS05 --> SS03
```
