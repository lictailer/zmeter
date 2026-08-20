# ZMeter Deployment CLI Implementation Plan

## Document status

- **Status:** Proposed; no deployment implementation exists yet.
- **Target platform:** 64-bit Windows with PowerShell and Conda.
- **Repository:** `https://github.com/lictailer/zmeter`
- **Planned interface:** An interactive terminal-based PowerShell script.
- **Delivery strategy:** Phase 1 implements and tests the complete user interface with no deployment or environment changes. Phase 2 connects the approved interface to real release download, extraction, and Conda commands.

## Goal

Create a clean, guided terminal script that lets a user perform one of two operations:

1. deploy an unchanged ZMeter release into a user-selected folder; or
2. create or update a Conda environment from the environment YAML contained in a selected ZMeter release.

For either operation, the user can select the newest stable release, the newest beta release, or a specific published release. The script must show the resolved release and operation details and require a final explicit confirmation before doing anything.

The implementation is split into two phases so that the selection rules, prompts, validation, summaries, and error messages can be reviewed without risking a real deployment or environment modification.

## Scope

### In scope

- Query only the official ZMeter GitHub repository.
- Present two top-level actions: **Deploy code** and **Set up environment**.
- Resolve the newest stable release, newest beta release, or an exact published release tag.
- Display useful release information before selection, including channel, tag, publication date, asset name, and download size.
- Ask for and validate a parent directory and deployed folder name for code deployment.
- Download and extract an immutable release package without changing its contents.
- Read the environment YAML belonging to the selected release.
- Create a missing Conda environment or update an existing one with pruning.
- Require a final confirmation for every deployment or environment operation.
- Provide clear success, cancellation, and recovery messages.
- Support hardware-independent automated tests for selection and validation logic.

### Non-goals

- Changing, patching, formatting, or generating ZMeter source files after download.
- Deploying directly from a moving branch head.
- Cloning or deploying another repository supplied by the user.
- Creating tags, releases, branches, commits, pull requests, or other GitHub content.
- Installing Git, PowerShell, Conda, Windows drivers, NI software, vendor SDKs, PowerPoint, or hardware runtimes.
- Selecting a laboratory hardware profile or editing addresses, serial numbers, paths, or device limits.
- Starting ZMeter, discovering instruments, connecting to hardware, or running a measurement.
- Copying laboratory configuration, measurement data, autosaves, PowerPoint logs, or backups between installations.
- Automatically deleting or merging an existing deployment directory or Conda environment.

## Release and channel contract

Branches are used to prepare code, while immutable GitHub Releases are used for deployment. The script must never deploy the current contents of `main` or `beta` directly.

| Channel | Development source | Published release rule | Example tag |
| --- | --- | --- | --- |
| Stable | `main` branch | GitHub Release with `prerelease: false` and a tag matching `vMAJOR.MINOR.PATCH` | `v0.10.0` |
| Beta | `beta` branch | GitHub prerelease with a tag matching `vMAJOR.MINOR.PATCH-beta.NUMBER` | `v0.11.0-beta.1` |

Additional requirements:

- “Newest” means the newest matching **published GitHub Release**, ordered by semantic version. It does not mean the most recently changed branch or the newest GitHub API array entry.
- A specific version must also be a published ZMeter Release and must match one of the supported tag formats. Arbitrary branches, commits, draft releases, and deleted releases are not selectable.
- Stable selection excludes prereleases. Beta selection includes only releases explicitly marked as prereleases and using the beta tag format.
- A stable release must be produced from `main`; a beta release must be produced from `beta`. The release workflow is responsible for enforcing this provenance before packaging.
- Each release must contain one deployable asset named `zmeter-<tag>-windows.zip`.
- Each deployment ZIP must include `deployment-manifest.json` and the release-specific environment YAML at the archive root.
- The manifest must identify at least its schema version, release version, tag, channel, tagged commit, environment filename, and environment-file SHA-256 hash.
- The release asset digest supplied by GitHub should be verified when available. Manifest values and the environment hash must always be verified before execution.

At planning time, the local Git ref list contains a local `beta` branch but does not show `origin/beta`. Before publishing beta packages, confirm that the reviewed beta branch exists on GitHub and that the release-packaging workflow is present on the default branch.

## User experience contract

### Startup and release scan

On startup, the script should:

1. show the repository it will use;
2. perform a read-only GitHub release query;
3. exclude drafts and invalid tags;
4. identify the newest stable and newest beta releases;
5. report a clear unavailable state if one channel has no valid release; and
6. display the main menu only after catalog validation succeeds.

Suggested main menu:

```text
ZMeter Deployment Tool
Repository: https://github.com/lictailer/zmeter

[1] Deploy code
[2] Set up Conda environment
[Q] Quit
```

Both operations use the same release-selection screen:

```text
[1] Newest stable  v0.10.0          18.4 MB  published 2026-08-10
[2] Newest beta    v0.11.0-beta.2   18.6 MB  published 2026-08-18
[3] Specific published version
[B] Back
```

For a specific version, the script asks for a tag, validates it, resolves its release, and then displays the same metadata. A missing or unsupported tag returns the user to version selection without terminating the program.

All prompts must:

- use numbered choices and accept choices case-insensitively where letters are used;
- explain invalid input and let the user retry;
- provide **Back**, **Cancel**, or **Quit** paths where appropriate;
- avoid hidden defaults for destructive or long-running actions;
- print paths in their fully resolved Windows form before confirmation; and
- never treat an empty response as final confirmation.

The final confirmation must require an explicit `Y`; any other response cancels safely.

## Code deployment flow

After release selection, ask for:

1. the parent directory, such as `D:\Xuguo`; and
2. the new deployment folder name, such as `SHG_measurement_08.20.2026`.

The final destination in this example is:

```text
D:\Xuguo\SHG_measurement_08.20.2026
```

Validation rules:

- The parent path must be an existing directory for the initial implementation. The script does not silently create an unknown directory tree.
- The folder name must be one directory name, not an absolute path, relative path, `.`/`..`, drive-qualified value, reserved Windows device name, or name containing invalid Windows filename characters.
- The resolved destination must be a direct child of the resolved parent directory.
- The destination must not be the ZMeter development checkout or one of its ancestors.
- If the destination already exists, stop before download and ask the user to choose a different name. Phase 2 will not merge, delete, or overwrite existing folders.
- Check write access and available space before download. Required free space should include the compressed asset, extracted content, and a safety margin.

The confirmation summary must show:

- operation: deploy code;
- release channel, tag, tagged commit, asset name, and download size;
- resolved parent and destination paths;
- that the destination must not already exist;
- that no Conda environment will be changed; and
- that ZMeter will not be launched.

After confirmation in Phase 2, the script downloads into a temporary staging directory, verifies the package, safely extracts it into a staging folder under the selected parent, and renames the staging folder to the requested final name only after all validation succeeds. The extracted release contents remain unchanged. The deployment contains no `.git` directory and is not a development checkout.

## Environment setup flow

Environment setup uses the same stable, beta, or specific-release selection. After selection, the script reads the environment YAML named by the verified deployment manifest.

To allow stable and beta installations to coexist, the default Conda environment name should be derived from the release tag rather than from the exported `name:` or machine-specific `prefix:` in the YAML:

```text
zmeter-v0.10.0
zmeter-v0.11.0-beta.2
```

The final confirmation summary must show:

- operation: set up Conda environment;
- release channel, tag, tagged commit, and download size;
- environment YAML filename and verified SHA-256 hash;
- resolved Conda environment name;
- whether that environment currently exists;
- whether the planned command is **create** or **update with prune**; and
- that Python dependencies do not install or validate required Windows hardware drivers.

After confirmation in Phase 2:

- If the derived environment does not exist, run `conda env create --name <name> --file <yaml>`.
- If it exists, still run `conda env update --name <name> --file <yaml> --prune` as requested.
- Pass `--name` explicitly so the exported YAML `name:` and machine-specific `prefix:` do not choose the target.
- Stream Conda output to the terminal and preserve its exit code.
- Report success only when Conda exits successfully.
- Do not activate the environment, install drivers, import ZMeter device modules, or launch ZMeter automatically.
- Keep the downloaded package and YAML in a temporary directory and remove only tool-owned temporary content after success or cancellation. On failure, report whether diagnostic temporary content was retained and its exact path.

An environment setup is separate from a code deployment. The user may run either operation independently and must confirm each one independently.

## Proposed implementation structure

The initial implementation should remain small and inspectable:

```text
tools/
  deploy_zmeter.ps1
tests/
  deployment_cli/
    releases.json
    deployment_cli.Tests.ps1
```

The script should isolate side effects behind a few clear operations so Phase 1 and Phase 2 share exactly the same UI logic:

| Responsibility | Proposed function boundary |
| --- | --- |
| Retrieve or load release catalog | `Get-ZMeterReleaseCatalog` |
| Classify and semantically order releases | `Resolve-ZMeterReleaseChoices` |
| Run terminal menus and retry loops | `Read-DeploymentAction`, `Read-ReleaseChoice` |
| Validate deployment paths | `Resolve-DeploymentDestination` |
| Read environment name/existence | `Get-CondaEnvironmentState` |
| Build the final human-readable summary | `Format-OperationSummary` |
| Obtain explicit final consent | `Confirm-Operation` |
| Describe a side effect without running it | `Invoke-PreviewOperation` |
| Download and validate a release | `Get-VerifiedReleasePackage` |
| Extract code into a staging destination | `Install-ZMeterCode` |
| Create or update the selected environment | `Install-ZMeterEnvironment` |

The exact names may change during implementation, but catalog, selection, validation, presentation, confirmation, and execution must remain separated. UI code must not directly call download, filesystem mutation, or Conda commands.

## Phase 1 — terminal UI and logic preview

### Objective

Deliver the complete interactive experience and validate all decisions without downloading or extracting ZMeter, creating deployment directories, or invoking Conda.

### Implementation tasks

1. Add the PowerShell entry script with preview-only behavior.
2. Add a checked-in release-catalog fixture containing:
   - multiple stable releases;
   - multiple beta releases;
   - a draft release;
   - invalid tags;
   - asset names, sizes, publication dates, and manifest metadata; and
   - empty/missing-channel cases for failure testing.
3. Implement release classification and semantic-version ordering independently of API order.
4. Implement the top-level operation menu, version menu, exact-tag input, retry behavior, back/cancel/quit paths, and final confirmation.
5. Implement destination-path and folder-name validation as pure logic.
6. Implement environment-name derivation and simulated existing/missing environment states.
7. Print a clearly marked `PREVIEW ONLY — NO CHANGES WILL BE MADE` banner and a final list of commands/actions that Phase 2 would perform.
8. Prevent side effects structurally:
   - no `Invoke-WebRequest` download;
   - no archive extraction;
   - no `New-Item`, `Move-Item`, `Copy-Item`, or removal against user paths;
   - no invocation of `git`, `gh`, `conda`, ZMeter, or Python; and
   - no environment, registry, profile, or system changes.
9. Add Pester tests if Pester is already available. Do not install it as part of this work. If unavailable, provide a hardware-independent PowerShell assertion harness using only built-in functionality.
10. Add concise usage text for preview mode and fixture selection.

### Phase 1 test scenarios

- Newest stable is selected correctly from an unsorted catalog.
- Newest beta is selected correctly from an unsorted catalog.
- Drafts, malformed tags, missing assets, and mismatched prerelease flags are excluded.
- A specific valid stable or beta tag resolves correctly.
- A missing specific version produces a recoverable error.
- A missing stable or beta channel is displayed as unavailable.
- Asset bytes are formatted consistently as KB, MB, or GB.
- Valid Windows parent/folder combinations resolve to the intended direct child.
- Absolute folder names, traversal, invalid characters, reserved names, checkout collisions, and existing destinations are rejected.
- Create/update environment summaries differ correctly.
- Empty or non-`Y` confirmation cancels.
- Back and quit paths work from every applicable screen.
- No test invokes a network download, Conda, Python, ZMeter, device discovery, or hardware code.

### Phase 1 acceptance gate

Phase 1 is complete only when a maintainer can walk through every menu using fixture data, see accurate final summaries for both operations, cancel safely, and run the hardware-independent logic tests with no deployment or environment side effects. The prompt wording and behavior must be approved before Phase 2 starts.

## Phase 2 — enable deployment and environment installation

### Objective

Replace the preview executors with narrow, verified side-effect implementations while keeping the Phase 1 menus, validation, and confirmation contract unchanged.

### Implementation tasks

1. Add a read-only live catalog provider for the GitHub Releases API while retaining the fixture provider for tests.
2. Use a fixed owner/repository allowlist (`lictailer/zmeter`) and HTTPS URLs returned for that repository only.
3. Support an optional GitHub token for private/rate-limited access without printing or storing it. Public access should not require a token when GitHub permits it.
4. Require the expected `zmeter-<tag>-windows.zip` asset and reject ambiguous duplicate assets.
5. Download to a uniquely named tool-owned temporary directory.
6. Verify the GitHub digest when available, validate safe archive paths, then validate `deployment-manifest.json`, tag, channel, commit, environment filename, and YAML hash.
7. For code deployment:
   - re-check the parent and destination immediately before mutation;
   - create a uniquely named staging directory under the chosen parent;
   - extract only after package validation;
   - reject symlink/reparse-point or path-traversal archive entries;
   - verify the staged result;
   - rename staging to the requested destination as the final step; and
   - clean up only the staging directory created by this invocation if an earlier step fails.
8. For environment setup:
   - verify that `conda` is available before confirmation;
   - obtain existing environment state through Conda without importing ZMeter;
   - run the exact create or update command shown in the final summary;
   - keep the process attached and stream its output; and
   - report Conda failure without claiming rollback, because package updates may be partially applied.
9. Preserve a `-Preview`/`-WhatIf` path that exercises live catalog resolution and all validation but does not download, extract, or invoke Conda.
10. Add mocked tests around HTTP, filesystem, archive verification, process execution, cancellation, and failure cleanup. All test destinations must use disposable temporary paths.
11. Update `documents/environment_windows.md`, the root `README.md`, `project_structure.md`, and `documents/README.md` when the implementation becomes active.

### Failure and recovery requirements

- Network or GitHub API failure: change nothing; display the failing stage and a retry-safe message.
- Rate limit or authentication failure: explain how to provide a token without echoing it.
- Missing/invalid asset or manifest: do not extract to the final destination and do not run Conda.
- Insufficient disk space or unwritable parent: stop before download when detectable.
- Destination appears after confirmation: stop safely; never merge or overwrite it.
- Interrupted code deployment: remove only invocation-owned staging content; never remove a pre-existing path.
- Conda failure: preserve Conda output and exit code, state that the environment may need review, and do not automatically delete the environment.
- Ctrl+C: handle cancellation, clean only invocation-owned temporary/staging paths, and leave existing deployments and environments untouched.

### Phase 2 acceptance gate

Phase 2 is complete when hardware-independent tests demonstrate that the script:

- resolves live-format stable, beta, and exact releases correctly;
- never mutates state before explicit final confirmation;
- deploys a verified fixture package unchanged into the exact requested folder;
- creates or updates only the derived test Conda environment through a mocked process boundary;
- refuses collisions and invalid/unverified packages;
- cleans up only its own temporary and staging paths; and
- reports failures without claiming success or rollback.

One maintainer should then perform a manual Windows deployment to a disposable non-lab directory. Any real Conda installation should also target a disposable test environment first. Neither validation authorizes starting ZMeter or connecting to instruments.

## Security, integrity, and safety requirements

- Hard-code or strictly allowlist the ZMeter repository identity. Do not accept an arbitrary repository URL.
- Treat GitHub release text, archive filenames, manifests, YAML content, and API values as untrusted input.
- Do not execute files from the release package.
- Do not use release notes as commands or instructions.
- Reject archive entries that escape the staging root or rely on links/reparse points.
- Do not place credentials in arguments, logs, manifests, or files in the deployment.
- Do not overwrite an existing deployment, development checkout, environment without the documented Conda update command, or any laboratory data.
- Do not use `git reset`, checkout mutation, or branch switching in a development clone.
- Do not activate or launch the installed application automatically.
- Do not discover, connect to, configure, or test laboratory hardware.
- Make clear that Conda packages do not install or validate Windows drivers and vendor runtimes.

## Validation strategy

Validation must proceed from pure logic to mocked side effects:

1. **Static:** PowerShell syntax parsing and repository diff checks.
2. **Unit:** semantic version classification, channel filtering, size formatting, tag lookup, path validation, environment naming, and confirmation behavior.
3. **Mock/simulation:** GitHub API responses, ZIP/manifest verification, temporary extraction, Conda command construction, exit codes, interruption, and cleanup.
4. **Manual terminal preview:** all Phase 1 menu paths with fixture data.
5. **Manual disposable deployment:** Phase 2 deployment into a temporary non-lab directory.
6. **Manual disposable environment setup:** Phase 2 create/update using an explicitly disposable Conda environment.

No validation step may import or launch ZMeter hardware modules, enumerate resources, connect to instruments, write measurement JSON/PPT/autosaves/backups, or use a laboratory deployment/data directory.

## Definition of done

The overall update is done when:

- stable, beta, and exact published release selection behave according to the release contract;
- the terminal flow is understandable without external instructions;
- every operation shows a complete summary and requires explicit final confirmation;
- code deployments contain the verified release contents unchanged at the requested destination;
- stable and beta Conda environments can coexist and an existing selected environment is updated with `--prune`;
- failures are safe, specific, and retryable;
- automated tests remain hardware-independent;
- maintained setup and structure documentation reflects the final implementation; and
- no real-hardware validation has been performed or implied.

