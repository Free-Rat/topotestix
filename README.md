![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/Free-Rat/topotestix/ci.yml?style=for-the-badge&logo=nixos)

# TopoTestix

Environment-aware property-based testing framework for distributed systems, built on Nix and NixOS.

Instead of testing only application-level inputs, TopoTestix treats **system configuration as a first-class test dimension**. A fuzzer generates diverse NixOS VM configurations (network topology, resource limits, service versions) from a single seed, runs them as NixOS integration tests, and on failure shrinks the seed to find a minimal reproducing case.

Master Thesis for the master's programme in Computing, specializing in Distributed and Cloud Systems, at Poznań University of Technology.

## Documentation

All design and planning documents live in [`docs/`](docs/):

| File | Content |
|---|---|
| [`docs/idea.md`](docs/idea.md) | Project motivation, core concepts (PBT, environment-aware testing, Nix as test generator), example property categories, and limitations |
| [`docs/architecture.md`](docs/architecture.md) | Module overview (fuzzer, expandTopology, runner, orchestrator), three-layer config composition, data flow, directory structure, and design principles |
| [`docs/target-authoring.md`](docs/target-authoring.md) | Practical cheat sheet for creating new targets: file roles, naming conventions, CLI workflow, result interpretation, and common failure modes |
| [`docs/plan.md`](docs/plan.md) | Phased implementation plan from foundation through shrinking and scale |
| [`docs/testing.md`](docs/testing.md) | How to run tests with nix-unit, test file conventions, and how to verify expected values |
