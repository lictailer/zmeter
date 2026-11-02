# zmeter skills

This folder holds agent skills for Claude Code and Codex that help with
zmeter work outside the running program: preparing input files, reading
analysis results, planning scans. Each skill is a self-contained folder with
a `SKILL.md` (what the skill is for and how the agent should work), and
optionally `references/` (background the agent reads when needed) and
`scripts/` (small helpers the agent runs). A skill does not need the zmeter
repository to work, so it can be used on an analysis PC.

Skills never drive lab hardware. They read and write files only.

## Installing a skill

Copy the skill folder (for example `zmeter-shift-mapping/`) into the skills
folder of your agent:

| Agent | Personal skills | Project skills |
| --- | --- | --- |
| Claude Code | `~/.claude/skills/<skill>/` | `<project>/.claude/skills/<skill>/` |
| Codex | `~/.codex/skills/<skill>/` | as configured for your Codex setup |

Then ask the agent for the task in your own words (for example "make shift
compensation CSVs from this alignment notebook"); it picks the skill from the
`description` in `SKILL.md`. Update a skill by copying the folder again.

## Skills

| Skill | What it does |
| --- | --- |
| [`zmeter-shift-mapping`](zmeter-shift-mapping/SKILL.md) | Turns analysis results (notebooks, shift tables, NumPy files) into the two-column mapping CSVs that the Shift Compensation window loads, one CSV per source → target pair, with zmeter's sign convention. |

Planned: `zmeter-scan-planner` (scan planning from a setup export).

## Adding a skill

1. Make a folder `skills/<name>/` with a `SKILL.md` whose front matter has
   `name` and a one-sentence `description` that says when to use it.
2. Keep scripts to the Python standard library where possible, so they run
   in any environment.
3. If the skill writes a file that zmeter reads, add a test under `tests/`
   that loads the skill's output with zmeter's own loader, so the two
   formats cannot drift apart (see `tests/test_shift_mapping_skill.py`).
4. Add the skill to the table above.
