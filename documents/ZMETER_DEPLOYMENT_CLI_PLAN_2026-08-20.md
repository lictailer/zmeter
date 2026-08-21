# ZMeter Deployment CLI Implementation Plan

## Document status

- **Status:** Phase 2 implementation active; disposable user deployment and Conda smoke tests remain user-executed.
- **Target platform:** 64-bit Windows with Python 3.12 and Conda already installed.
- **Repository:** `https://github.com/lictailer/zmeter`
- **Installer repository:** `INSERT_DEPLOY_REPOSITORY_URL_HERE`
- **Interface:** One Python script launched by double-click, using a popup terminal for concise `print()` and `input()` interaction.
- **Code location:** The installer source and offline catalog live in a separate repository; this ZMeter repository retains the release workflow and this contract.
- **Delivery strategy:** The approved Phase 1 interface now uses verified live release downloads, staged extraction, and attached Conda commands. Maintainer preview modes remain side-effect free.

## Goal

Create a clean, lightweight Python terminal script that lets a user perform one of two operations:

1. deploy an unchanged ZMeter release into a user-selected folder; or
2. create or update a Conda environment from the environment YAML contained in a selected ZMeter release.

For either operation, the user can select the newest stable release, the newest beta release, or a specific published release. The script must show the resolved release and operation details and require a final explicit confirmation before doing anything.

The implementation was delivered in two phases so that selection, prompts, validation, summaries, and errors were reviewed before enabling real deployment and environment changes.

## Scope

### In scope

- Query only the official ZMeter GitHub repository.
- Present two top-level actions: **Install ZMeter** and **Set up Python environment**.
- Resolve the newest stable release, newest beta release, or an exact published release tag.
- Validate detailed release metadata internally while showing only the selected operation and tag to the user.
- Ask for and validate one complete destination path for code deployment.
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
- Installing Git, Python, Conda, Windows drivers, NI software, vendor SDKs, PowerPoint, or hardware runtimes.
- Selecting a laboratory hardware profile or editing addresses, serial numbers, paths, or device limits.
- Starting ZMeter, discovering instruments, connecting to hardware, or running a measurement.
- Copying laboratory configuration, measurement data, autosaves, PowerPoint logs, or backups between installations.
- Automatically deleting or merging an existing deployment directory or Conda environment.

## Release and channel contract

Immutable published GitHub Releases are the only deployment source for both channels. Branch names, branch heads, and branch provenance are not part of release selection, and the script must never clone or deploy a branch directly.

| Channel | Published release rule | Example tag |
| --- | --- | --- |
| Stable | GitHub Release with `prerelease: false` and a tag matching `vMAJOR.MINOR` | `v1.0` |
| Beta | GitHub prerelease with a tag matching `vMAJOR.MINOR-beta.NUMBER` | `v1.0-beta.1` |

Additional requirements:

- “Newest” means the newest matching **published GitHub Release**, ordered by semantic version. It does not mean the most recently changed branch or the newest GitHub API array entry.
- A specific version must also be a published ZMeter Release and must match one of the supported tag formats. Arbitrary branches, commits, draft releases, and deleted releases are not selectable.
- Stable selection excludes prereleases. Beta selection includes only releases explicitly marked as prereleases and using the beta tag format.
- The existing stable tag `v0.10.0` is the only supported three-component legacy exception. Future three-component stable or beta tags are invalid.
- Major, minor, and beta-number components are canonical non-negative integers: leading zeroes are rejected except for the value `0`.
- `v0.10` and legacy `v0.10.0` normalize to the same stable version. A catalog containing both is ambiguous and must be rejected.
- The release-packaging workflow checks out the published tag for packaging regardless of channel; it does not infer or enforce a source branch.
- Each release must contain one deployable asset named `zmeter-<tag>-windows.zip`.
- Each deployment ZIP must include `deployment-manifest.json` and the release-specific environment YAML at the archive root.
- The manifest must identify at least its schema version, release version, tag, channel, tagged commit, environment filename, and environment-file SHA-256 hash.
- The release asset digest supplied by GitHub should be verified when available. Manifest values and the environment hash must always be verified before execution.

## User experience contract

### Startup and linear interaction

The user downloads the standalone installer repository and double-clicks its root `deploy_zmeter.py`. Windows must associate `.py` files with `python.exe`, not `pythonw.exe`, so a terminal opens. Normal startup reads the allowlisted ZMeter repository's published releases and does not depend on the current working directory.

The interaction is one forward-only sequence:

```text
ZMeter Setup

1. Install ZMeter
2. Set up Python environment

Select an operation: 1

1. Stable - v1.0
2. Beta - v1.0-beta.3
3. Specific version

Select a version: 1
```

There are no Back or Quit menu choices. Invalid input retries only the current prompt. A missing or unsupported exact tag returns to version selection. Closing the terminal, Ctrl+C, or end-of-input cancels safely.

The confirmation shows only the action, selected tag, destination or environment name, and a warning that changes will follow. It requires an explicit `Y`; any other response cancels. Completion, cancellation, and handled errors remain visible until the user presses Enter. `--preview` uses live metadata and Conda state without modifying anything; `--catalog <path>` forces an offline fixture preview.

## Code deployment flow

After release selection, ask for one complete new installation path:

```text
D:\Xuguo\SHG_measurement_08.20.2026
```

Validation rules:

- The path must be absolute and its parent must already exist; the script does not silently create an unknown directory tree.
- The final folder name must not be a reserved Windows device name or contain invalid Windows filename characters.
- The destination must not overlap the ZMeter development checkout in either direction.
- If the destination already exists, stop before download and ask the user to choose a different name. The installer never merges, deletes, or overwrites existing folders.
- Check write access and available space before download. Required free space should include the compressed asset, extracted content, and a safety margin.

The confirmation summary must show:

- operation: install ZMeter;
- selected release tag; and
- resolved destination path.

Commit, asset, manifest, and hash metadata remain validated internally but are omitted from normal output.

After confirmation, the script shows download and extraction progress, verifies the asset and tagged commit, safely extracts into a uniquely named staging folder under the selected parent, and renames that folder to the requested final name only after all validation succeeds. The extracted file bytes remain unchanged. The deployment contains no `.git` directory and is not a development checkout.

## Environment setup flow

Environment setup uses the same stable, beta, or specific-release selection. After selection, the script reads the environment YAML named by the verified deployment manifest.

To allow stable and beta installations to coexist, the Conda environment name is derived from the release tag rather than from the exported `name:` or machine-specific `prefix:` in the YAML:

```text
zmeter-v1.0
zmeter-v1.0-beta.3
```

The final confirmation summary must show:

- operation: set up Python environment;
- selected release tag;
- resolved Conda environment name; and
- whether the planned action is create or update.

The YAML filename, verified hash, and driver limitation remain enforced or documented internally rather than printed in the short confirmation.

After confirmation:

- If the derived environment does not exist, run `conda env create --name <name> --file <yaml>`.
- If it exists, still run `conda env update --name <name> --file <yaml> --prune` as requested.
- Pass `--name` explicitly so the exported YAML `name:` and machine-specific `prefix:` do not choose the target.
- Show release download/verification progress, then stream Conda output to the terminal and preserve its exit code.
- Report success only when Conda exits successfully.
- Do not activate the environment, install drivers, import ZMeter device modules, or launch ZMeter automatically.
- Keep the downloaded package and YAML in a tool-owned temporary directory and remove that content after success, cancellation, or failure. Never remove an existing environment after a failed update.

An environment setup is separate from a code deployment. The user may run either operation independently and must confirm each one independently.

## Implementation structure

The runtime implementation remains one standard-library script in its own repository:

```text
standalone installer repository/
  deploy_zmeter.py
  releases.json

ZMeter repository/
  .github/workflows/package-release.yml
  documents/ZMETER_DEPLOYMENT_CLI_PLAN_2026-08-20.md
```

The script isolates side effects behind clear operations while sharing one UI flow:

| Responsibility | Current function boundary |
| --- | --- |
| Retrieve or load release catalog | `load_catalog` |
| Query the allowlisted GitHub API | `GitHubClient` |
| Classify and semantically order releases | `resolve_release_choices` |
| Run the linear terminal prompts | `select_operation`, `select_release` |
| Validate deployment paths | `resolve_destination` |
| Read environment name/existence | `get_environment_state` |
| Build the short confirmation | `format_summary` |
| Obtain explicit final consent | `confirm` |
| Verify download and package | `download_release_asset`, `verify_release_package` |
| Stage and finalize deployment | `extract_verified_package`, `execute_installation` |
| Locate and invoke Conda | `find_conda_executable`, `execute_environment_setup` |
| Run active or preview interaction | `main` |
| Keep double-click results visible | `run_clicked` |

Catalog, selection, validation, presentation, confirmation, package operations, and Conda execution remain separated. Fixture catalogs always force preview and cannot authorize side effects.

Normal usage is double-clicking `deploy_zmeter.py` in the standalone installer repository. Maintainers may use `python deploy_zmeter.py --preview`; command-line invocation is not the normal user workflow.

## Phase 1 — terminal UI and logic preview

### Objective

Deliver the complete interactive experience and validate all decisions without downloading or extracting ZMeter, creating deployment directories, or invoking Conda.

### Implementation tasks

1. Add one standard-library Python entry script with preview-only behavior and a fixture path resolved from `__file__`.
2. Add a checked-in release-catalog fixture containing:
   - multiple stable releases;
   - multiple beta releases;
   - a draft release;
   - invalid tags;
   - asset names, sizes, publication dates, and manifest metadata; and
   - empty/missing-channel cases for failure testing.
3. Implement strict two-component release classification, the `v0.10.0` exception, normalized-version collision detection, and numeric ordering independently of API order.
4. Implement forward-only operation, version, optional exact-tag, destination, and short confirmation prompts without Back or Quit choices.
5. Implement complete destination-path validation as pure logic.
6. Implement environment-name derivation and injectable simulated existing/missing environment states.
7. Print concise preview, cancellation, error, and completion messages, then pause before closing.
8. Prevent side effects structurally:
   - no HTTP download;
   - no archive extraction;
   - no filesystem mutation against user paths;
   - no child-process invocation of Git, GitHub CLI, Conda, ZMeter, or Python; and
   - no environment, registry, profile, or system changes.
9. Add standard-library `unittest` coverage without installing dependencies.
10. Add concise double-click and `.py` file-association instructions.

### Phase 1 test scenarios

- Newest stable is selected correctly from unsorted `v0.9`, legacy `v0.10.0`, `v0.11`, and `v1.0` releases.
- Newest beta is selected correctly by major, minor, and beta number from an unsorted catalog.
- Drafts, malformed tags, missing assets, and mismatched prerelease flags are excluded.
- A specific valid stable, beta, or legacy `v0.10.0` tag resolves correctly.
- Future patch tags, incomplete beta tags, leading-zero components, and a `v0.10`/`v0.10.0` collision are rejected.
- A missing specific version produces a recoverable error.
- A missing stable or beta channel is displayed as unavailable.
- Asset bytes are formatted consistently as KB, MB, or GB.
- Valid complete Windows destination paths resolve correctly.
- Relative paths, invalid or reserved names, missing parents, checkout overlap, and existing destinations are rejected.
- Create/update environment summaries differ correctly.
- Empty or non-`Y` confirmation cancels.
- Invalid input retries only the current prompt; Ctrl+C and EOF cancel safely.
- Success, cancellation, and handled errors pause before the popup terminal closes.
- No test invokes a network download, Conda, child Python, ZMeter, device discovery, or hardware code.

### Phase 1 acceptance gate

Phase 1 is complete only when a maintainer can double-click the Python file, walk through both concise linear previews using fixture data, cancel safely, read the final message before closing, and run the hardware-independent tests with no deployment or environment side effects.

## Phase 2 — verified deployment and environment installation

### Objective

Replace the preview executor with narrow, verified side-effect implementations while keeping the Phase 1 linear prompts, validation, and confirmation contract unchanged.

### Implemented behavior

1. A read-only GitHub Releases provider supplies the live catalog; the fixture provider remains preview-only.
2. A fixed owner/repository allowlist (`lictailer/zmeter`) accepts only HTTPS GitHub API and release-download URLs.
3. An optional `GITHUB_TOKEN` supports rate-limited access without being printed, stored, or placed in command arguments. Public access requires no token.
4. The expected `zmeter-<tag>-windows.zip` asset is required and ambiguous duplicate assets are rejected.
5. Downloads use a uniquely named tool-owned temporary directory and report byte progress.
6. Package handling verifies the GitHub digest when available, safe archive paths, `deployment-manifest.json`, tag, channel, resolved tagged commit, environment filename, and YAML hash.
7. Code deployment:
   - re-check the parent and destination immediately before mutation;
   - create a uniquely named staging directory under the chosen parent;
   - extract only after package validation;
   - reject symlink/reparse-point or path-traversal archive entries;
   - verify the staged result;
   - rename staging to the requested destination as the final step; and
   - clean up only the staging directory created by this invocation if an earlier step fails.
8. Environment setup:
   - verify that `conda` is available before confirmation;
   - obtain existing environment state through Conda without importing ZMeter;
   - run the exact create or update command shown in the final summary;
   - keep the process attached and stream its output; and
   - report Conda failure without claiming rollback, because package updates may be partially applied.
9. Python preview mode exercises live catalog resolution, destination validation, and read-only Conda state without downloading, extracting, or invoking a modifying Conda command.
10. Mocked tests cover HTTP, filesystem, archive verification, process execution, progress, cancellation, and failure cleanup using disposable temporary paths.
11. The Windows environment guide, root README, project structure, and document index describe the active implementation.

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

The automated Phase 2 gate requires hardware-independent tests to demonstrate that the script:

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

1. **Static:** Python syntax compilation, AST side-effect inspection, and repository diff checks.
2. **Unit:** semantic version classification, channel filtering, size formatting, tag lookup, path validation, environment naming, and confirmation behavior.
3. **Mock/simulation:** GitHub API responses, ZIP/manifest verification, temporary extraction, Conda command construction, exit codes, interruption, and cleanup.
4. **Manual terminal preview:** run both forward-only live `--preview` flows and verify that no destination or environment is created.
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

