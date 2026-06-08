# container-build-pipeline Specification

## Purpose

TBD - created by archiving change 'o2-prebuilt-base-image'. Update Purpose after archive.

## Requirements

### Requirement: Application image derives from a prebuilt base image

The application container image SHALL be built in two stages: a prebuilt base image carrying the operating-system packages and Python dependencies, and an application layer that adds only the application source and entrypoint. The application Dockerfile SHALL declare its base via `FROM` referencing the published base image and SHALL NOT install operating-system packages directly.

#### Scenario: Application build skips OS package installation

- **WHEN** the application image is built from the application Dockerfile
- **THEN** no `apt-get install` step runs in the application build
- **AND** the operating-system packages (build toolchain, ffmpeg, age, PostgreSQL client) are already present because they were baked into the base image

#### Scenario: All services share one image

- **WHEN** any of the backend, worker, dispatcher, or beat services is deployed
- **THEN** the same application image is used
- **AND** the running role is selected at container start by the `START_COMMAND` environment variable


<!-- @trace
source: o2-prebuilt-base-image
updated: 2026-06-08
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
  - skills-lock.json
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
-->

---
### Requirement: Base image is a cache, not a contract

The application build SHALL re-run dependency installation from the dependency manifest on top of the base image so that a stale base image never causes missing dependencies in production. When the base image already contains the required dependencies, the install SHALL resolve them as already satisfied without re-downloading large wheels; when the base image is missing newly added dependencies, the install SHALL add only the difference.

#### Scenario: Stale base self-heals

- **WHEN** a dependency is added to the manifest and the base image has not yet been rebuilt
- **AND** the application image is built
- **THEN** the application build installs the newly added dependency on top of the base image
- **AND** the resulting image contains the dependency

#### Scenario: Fresh base makes the install near no-op

- **WHEN** the base image already contains every dependency in the manifest
- **AND** the application image is built
- **THEN** the dependency install resolves all requirements as satisfied
- **AND** no large wheel is re-downloaded or recompiled in the application build


<!-- @trace
source: o2-prebuilt-base-image
updated: 2026-06-08
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
  - skills-lock.json
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
-->

---
### Requirement: Base image is published to a public registry without pull authentication

The base image SHALL be published to a public container registry so that the deployment platform can pull it without configured registry credentials.

#### Scenario: Deployment pulls base without credentials

- **WHEN** the deployment platform builds the application image and resolves the `FROM` base reference
- **THEN** the base image is pulled from the public registry
- **AND** no registry authentication is required for the pull


<!-- @trace
source: o2-prebuilt-base-image
updated: 2026-06-08
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
  - skills-lock.json
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
-->

---
### Requirement: Base image is rebuilt when build inputs change

A continuous-integration workflow SHALL rebuild and publish the base image when the dependency manifest or the base image definition changes, and SHALL also be triggerable manually. Because the base image is a cache and not a correctness dependency, a delayed or missed rebuild SHALL degrade build speed only and SHALL NOT cause a deployment to lack dependencies.

#### Scenario: Manifest change triggers rebuild

- **WHEN** a change to the dependency manifest or the base image definition is pushed to the main branch
- **THEN** the workflow builds the base image and publishes it to the public registry under the stable tag

#### Scenario: Manual rebuild

- **WHEN** an operator manually dispatches the base image workflow
- **THEN** the workflow builds and publishes the base image under the stable tag

<!-- @trace
source: o2-prebuilt-base-image
updated: 2026-06-08
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
  - skills-lock.json
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
-->