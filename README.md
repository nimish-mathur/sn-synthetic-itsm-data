# sn-synthetic-itsm-data

**15 months of realistic, backdated ServiceNow ITSM history** (incidents, changes, SLAs, assignment) for Platform Analytics and Power BI work, generated from a single configuration file and loaded into a ServiceNow instance so that trend dashboards show real history from day one.

> **Transparency notice:** "Northgate Industrial" (NGI) is a fictional EU manufacturer. All data produced by this generator is synthetic. No real company or personal data is used; e-mail addresses use the reserved `.example` domain.

## Why this exists
A fresh ServiceNow instance has no history, and records inserted today with past dates do **not** behave like records that aged naturally: the SLA engine only runs live, there is no audit history, and historic data collection evaluates *current* field values. This project generates every field the KPIs need explicitly, computes the SLA records the engine would have written, and records a ground truth to reconcile the instance against.

## Result (loaded 2026-09-28 on a Brazil Patch 0 PDI)
| | Records | Notes |
|---|---|---|
| Users / groups / memberships | 3,500 / 12 / 64 | 6 EU sites, 10 departments, IT agents in site-bound groups |
| Changes | 2,688 | ~97.5 % success; one failed ERP change (Sat 7 Mar 2026) |
| Incidents | 19,637 | Seasonality, French holidays, ERP incident wave, change-induced incidents |
| SLA records | 39,274 | Response + resolution per incident, business hours Europe/Paris, pauses, breaches |

Every count matched the ground truth; see [`docs/design.md` §14](docs/design.md).

**The story in the data:** resolution SLA attainment rises from ~78 % (H2 2025) to ~86 % (Q3 2026) and first-contact resolution from 60 % to 68 % after a KPI-governance programme starts in January 2026; an August holiday dip; a failed SAP upgrade that floods the service desk for a week in March 2026; ~3 % deliberate data-quality defects for data-quality rules to catch.

## How it works
```
config/ngi.yaml ─► Python generator (seeded, deterministic, 116 tests)
                     ├─► JSON batches ─► ServiceNow: Fix Script "NGI Synthetic Load" ─► Script Include NGISynthLoader
                     │                    (our sys_ids, backdated system fields, business rules off for history,
                     │                     data policies respected, idempotent, manifest-based rollback)
                     └─► ground truth (counts) ─► validation, later Platform Analytics ↔ Power BI reconciliation
```

## Quick start
```bash
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -e .
python -m pytest                                     # 116 tests
python -m sn_synth preview                           # CSV previews in output/preview/ (open in Excel)
python -m sn_synth bundle                            # 73 files for the ServiceNow Fix Script
python -m sn_synth export                            # batch files + output/ground_truth/counts.json
```
Loading into ServiceNow: import update sets `NGI-P0-01` (loader) and `NGI-P0-02` (schedule, 8 SLA definitions, subcategories) from `servicenow/update-sets/`, attach `output/upload/*` to the Fix Script, then follow the steps in its header (`smoke` → `load` → `validate-load.bg.js`).

## Design and decisions
- [`docs/design.md`](docs/design.md): problem, architecture, decisions D1–D10 with trade-offs, KPI → field contract, generator rules, load result, known limitations.
- [`docs/best-practices-references.md`](docs/best-practices-references.md): ServiceNow Best Practices assets followed (0001078, 0001199) and documented deviations.
- `config/ngi.yaml`: every business rule of the dataset (volumes, mixes, SLA targets, story events), separated from values read from the instance (`instance_facts`).

## Known limitations (short)
Computed, not engine-produced, SLA records; no audit/journal history; no incident → change link on the Brazil PDI (kept in the ground truth); `opened_by` is the loading user. Full list in the design record.

## Built on
ServiceNow Brazil Patch 0 PDI (`glide-brazil-08-25-2026__patch0-08-26-2026`); configuration kept release-agnostic where possible. Python 3.12.

## License
MIT
