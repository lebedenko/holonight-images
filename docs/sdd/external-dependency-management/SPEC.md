# External dependency management — holonight-images

Work package: EDM-009
Baseline: `d834984dc413dc9e56f7f3157fa605d6a8667088`
Umbrella audit: `38146d8f474317f3f8d72699f60e6d16a71dd165`
Status: Planned; adoption awaits the canonical bundle/environment handoff.

## Requirements

- Configuration and normal build commands shall never acquire dependencies or prepare source providers.
- `task deps` shall explicitly prepare supplied local providers and check installed external prerequisites.
- Internal providers shall resolve only from approved prefixes; external packages shall resolve from an explicit
  external prefix or normal system locations.
- Enabled dependency-dependent features shall require their dependencies; minimal profiles shall disable them explicitly.
- Where production components use Qt, discovery shall require >=6.11; private Qt components shall match
  the selected public version exactly.
- Where tests use GTest, consumers shall require installed GTest >=1.14 CONFIG and any GMock targets they use.
- Existing public APIs, component switches, install-tree consumers and acceptance coverage shall be preserved.

## Design

Adopt canonical `tooling/modules/holonight-images.json` and `.cmake`, then synchronize bundle 2.0.0 into this repository.
The copied metadata is owned by this standalone checkout. CMake performs authoritative discovery; shared probes
provide prerequisite diagnostics and record resolved versions/paths. Incompatible caches and local provider install
trees are archived before reuse. Package acquisition occurs only in explicit environment preparation. CI switches
build/runtime/release lanes together to qualified immutable images and runs acceptance offline after preparation.

Preserve existing dependency interfaces and component switches; adopt installed GTest CONFIG discovery where tests use it.

## Implementation and verification tasks

- [ ] Confirm the exact baseline and canonical handoff before implementation.
- [ ] Adopt declarations, prefix helpers, explicit preparation and compatibility signatures.
- [ ] Apply the repository-specific discovery changes above.
- [ ] Update Task, CI preparation/entrypoints, Dockerfiles, release lanes and contributor instructions.
- [ ] Run declaration/CMake/profile consistency checks and offline missing-package regressions.
- [ ] Run narrow regressions, clean acceptance, installed-package consumers and required quality checks.
- [ ] Inspect complete logs; record commands, versions, features, warnings and manual checks.
- [ ] Make a repository-local commit only after local verification; publish only when authorized.

Implementation has not started. No build/test result is claimed for the adoption.
