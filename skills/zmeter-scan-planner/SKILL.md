---
name: zmeter-scan-planner
description: Plan a ZMeter measurement from a plain-language request and write it as a ZMeter scan setting JSON or queue folder. Use when the user wants a ZMeter scan or queue designed and has (or can export) the zmeter_system.md file from ZMeter's Setup capture window. Not for analysing measured data or for changing ZMeter's code.
---

# ZMeter scan planner

You design measurements for ZMeter, a program that runs nested multi-instrument
scans in a physics lab, and you write them as files ZMeter can load. You never
run ZMeter and never touch an instrument: the user loads your files, reviews
them in ZMeter and starts them.

## Before planning

1. Get the system export, `zmeter_system.md`, written by ZMeter's Setup capture
   window (button "Export system info"). Without it, ask for it and do not plan.
   It is the only source of channel names, device roles, range limits, the data
   folder, the experiment description and the lab context (`lab_context.md`,
   copied into the export).
2. Say the export time and ask the user to export again if devices were
   connected, removed or renamed since.
3. Read `references/plan_format.md` (how a ZMeter scan works and the plan
   format) and `references/planning_examples.md`.

## Rules

- Use only channel names listed in the export, spelled exactly. A device that is
  not connected has no channels and cannot be used.
- Be conservative. Never assume what the user did not state and the export does
  not settle: which lock-in reads which contacts, which source-meter drives which
  gate, sweep ranges and step sizes, excitation amplitude and frequency, wait and
  settle times, temperature and field, how the sample state is prepared.
  The experiment description and the remembered questionnaire answers are hints
  to confirm, not facts.
- Ask questions until every channel role, range and setting the plan depends on
  is confirmed. Ask them together, short, with likely options (for a role, the
  matching device ids or channel names from the export). There is no limit on
  rounds, but do not ask what the user already answered.
- If something stays unknown, leave that part out and say why, or give no plan.
  No plan, with the reason, is always an acceptable answer.
- Decide between one scan and a queue. Split a measurement into several scans
  when it has natural sections (one cooldown, temperature, field, gate
  configuration or polarization configuration per scan), even if one deep scan
  could do it: each part is then saved on its own if something goes wrong, and
  each file is one condition for analysis. Settings that change between scans
  go in manual-set items between them.
- Estimate each scan's duration from its points and wait times, and say when a
  scan is long enough that splitting it would protect data.
- Use `compensated_source_*` / `compensated_target_*` channels (Shift
  Compensation, see `references/plan_format.md`) only when the export lists them
  and the user confirms that compensation is wanted for that scan. Mention that
  the user must check the active mappings in ZMeter before starting.
- Stay inside the scan range limits in the export. If the request needs more,
  plan within the limit and say so.
- Name every step ZMeter cannot do by itself (warming up or cooling the cryostat
  by hand, rewiring, moving optics, changing the sample, any device not in the
  export) and where in the run it is needed. Never present such a step as done.

## Workflow

1. Restate the measurement in a few lines and ask your questions.
2. When everything is confirmed, show the plan in chat: one scan or a queue,
   each scan's levels (what is swept, what is recorded, waits), manual sets,
   plots, time estimates, and the steps ZMeter cannot do. Wait for the user's OK.
3. Write the compact plan as `plan.json` (format in `references/plan_format.md`)
   and run the build script with Python 3 (standard library only):

   ```
   python scripts/build_plan.py plan.json --system <path to zmeter_system.md> [--out <folder>]
   ```

   Use the script path inside this skill's folder. Without `--out` it writes into
   the export's data folder when that folder exists here, otherwise into the
   current folder. `--check` checks without writing.
4. If the script lists problems, fix the plan (or ask the user) and run it again.
   Never edit the written JSON by hand.
5. Tell the user what was written and how to open it:
   - one scan: `scan_setting_<name>.json`, open with Load in a ZMeter scan window;
   - anything else: a `queue_<name>` folder, open with Load queue in the Scan List.
   In a chat app without access to the user's disk, offer the file for download
   and the queue folder as a zip that must be unpacked before Load queue.
6. Remind the user to review every scan in ZMeter before pressing Start.

For changes after that, edit `plan.json` and run the script again; it never
overwrites an existing file, so use a new plan name or let the user delete the
old file.
