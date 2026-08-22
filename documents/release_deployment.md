# Release Deployment

## Maintained boundary

The standalone Windows installer is maintained in
[lictailer/zmeter-deploy](https://github.com/lictailer/zmeter-deploy). ZMeter's
`release/beta` branch contains the reconstruction, release-packaging workflow,
manifest contract, environment YAML, and user-facing installer links. The
installer repository contains the executable deployment tool.

Do not deploy from a moving branch head. Deployable code and environment input
come from published ZMeter releases and their verified release assets.

## Installer responsibilities

The installer can:

- select the newest stable, newest beta, or an exact published release;
- verify the expected release ZIP, digest when available, manifest, tagged
  commit, channel, and environment-file hash;
- extract a verified release into a new destination without modifying its
  contents; or
- create/update the release-specific Conda environment with an explicit name.

It requires explicit confirmation before mutation, does not merge or overwrite
an existing deployment, and does not launch ZMeter, install hardware drivers,
select a device profile, access hardware, or copy laboratory data.

For a non-modifying live check, run from the installer repository:

```powershell
python deploy_zmeter.py --preview
```

An offline catalog can be inspected with:

```powershell
python deploy_zmeter.py --catalog <path>
```

Catalog mode never installs or changes anything. Exact installer behavior and
maintenance belong to the standalone repository rather than duplicated ZMeter
documentation.

## ZMeter release responsibilities

The ZMeter release workflow must produce the expected Windows ZIP and
`deployment-manifest.json`, bind the artifact to the release tag/commit/channel,
include the named environment YAML, and preserve the published source unchanged.
Stable promotion remains separate from beta integration and requires the
maintained release validation process.

## Remaining user validation

The installer implementation exists, but disposable Windows smoke evidence
remains environment-specific:

1. preview a published release without mutation;
2. deploy to a new disposable non-lab directory and verify its manifest/content;
3. create or update a disposable release-specific Conda environment;
4. confirm cancellation, collision refusal, and visible failure handling;
5. verify ZMeter and hardware are never launched or accessed by the installer.

This validation does not authorize a laboratory profile or hardware operation.
