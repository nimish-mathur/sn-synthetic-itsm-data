# Design – sn-synthetic-itsm-data

> **Transparency notice:** Northgate Industrial (NGI) is a fictional company. All records produced by this generator are synthetic.

## 1. Purpose
Produce 15 months of realistic, backdated ServiceNow ITSM history (incidents, changes, SLAs, assignment) for NGI. That history lets Platform Analytics (P1) and Power BI (P2) show genuine trends, and lets the migration project (P4) reconcile the two against a known ground truth.

**Built on:** ServiceNow Brazil Patch 0 PDI (`glide-brazil-08-25-2026__patch0-08-26-2026`). Configuration lives in `config/ngi.yaml`.

## 2. The core problem this design solves
Records inserted today with past dates do **not** behave like records that aged naturally:

| Gap | Consequence | Design response |
|---|---|---|
| The SLA engine runs in real time | Backdated incidents get no SLAs, or SLAs starting today | `task_sla` rows written directly with computed stages and breach flags |
| No audit, metric or journal history | History-based measures cannot be computed | Every KPI input is an explicit field (see §5) |
| Historic collection evaluates *current* field values | State-based backlog indicators produce false history | Backlog indicators use date conditions (P1) |
| Breakdowns use current values | Past reassignments are not visible historically | Documented limitation (§7) |

## 3. Architecture (D1)
```
config/ngi.yaml ─► Python generator (seeded, deterministic)
                     ├─► JSON batches ─► ServiceNow loader (Script Include NGISynthLoader, global scope)
                     │                     sets our sys_id, keeps our dates, business rules off,
                     │                     respects data policies, tags correlation_id = NGI-SYNTH-<run>
                     └─► ground truth (CSV + expected KPI values) ─► validation, P4 reconciliation
```
- **Why Python:** testable, readable, reproducible (seed), and produces ground truth as a by-product.
- **Why a server-side loader:** only server code can set past system dates (`autoSysFields(false)`). This was verified on Brazil in the T7 smoke test.
- **Why not the ServiceNow SDK for the loader:** SDK 4.8.1 documents neither global-scope builds nor Platform Analytics APIs. The SDK `query` command is used for fact-finding and validation.
- **Deterministic sys_ids** (UUIDv5 → 32 hex): references resolve in one pass, and reloads are idempotent. Verified in T7.

## 4. Decisions

| ID | Decision | Rationale | Trade-off |
|---|---|---|---|
| D1 | Python generator + global Script Include loader | See §3 | Custom code (deviation from configuration-over-customization, documented in best-practices-references.md) |
| D2 | 2025-07-01 → load date, plus daily trickle job | Trends continue after load; screenshots stay current | Trickle job must be maintained during the program |
| D3 | 3,500 employees, 6 sites, 12 groups (~60 agents), ~1,400 incidents/month, ~180 changes/month | Plausible mid-size manufacturer | Volume ratio (~0.4 tickets per employee per month) is a heuristic, not a published benchmark |
| D4 | NGI schedule Mon–Fri 08:00–18:00 Europe/Paris, FR holidays; 8 NGI SLA definitions; demo SLAs deactivated | Owned, documented, time-zone-explicit definitions | P1 resolution set to 4 h (vs OOTB 1 h) for realism. "Business days" written as business hours to avoid ambiguity |
| D5 | Demo incidents and changes backed up to XML, then deleted before load | 2015–2027 demo records distort aging and trends | Demo data lost from PDI (backup kept) |
| D6 | ~3 % planted defects: missing category, retired category value, retired group | Gives P1 data-quality rules and P2 cleansing a real target | Defects must be documented so they aren't mistaken for bugs |
| D7 | Story events: August dip, March 2026 failed ERP change + incident wave, MTTR improvement from Jan 2026 | Dashboards have findings to explain | Events are authored, and documented as such |
| D8 | Generate in Europe/Paris local time, store UTC; admin user time zone Europe/Paris | Time zone handling explicit and testable (P4 variance cause) | None |
| D9 | Add two incident subcategories under `software`: `erp` (ERP / SAP) and `mes` (MES / Shop floor) | OOTB software subcategories (`os`, `email`) cannot describe a manufacturer's core applications or the ERP story event | Small configuration change (update set `NGI-P0-02`) |
| D10 | Reference data loaded with business rules **on** (dates kept); history loaded with business rules **off** | Reference data needs platform logic (e.g. group membership, role inheritance); history must not trigger the SLA engine | Two load modes to document and test |

## 5. KPI → field contract

| KPI | Fields the generator must write |
|---|---|
| Volume by priority / category / group / site | `opened_at`, `impact`, `urgency`, `priority` (standard matrix), `category`, `subcategory`, `assignment_group`, `location`, `caller_id` |
| MTTR | `opened_at`, `resolved_at`, `calendar_stc`, `business_stc` |
| MTTA | Response `task_sla` rows (`start_time`, `end_time`) |
| SLA attainment / breach | `task_sla`: `sla`, `stage`, `has_breached`, `planned_end_time`, `business_percentage`, `active` |
| Backlog & aging | `opened_at`, `resolved_at`, `closed_at`, `state`, `incident_state`, `active` |
| Inactivity (> 5 days not worked) | `sys_updated_on` |
| First-contact resolution | `reassignment_count`, final `assignment_group` |
| Reopen rate | `reopen_count` |
| Resolution quality | `close_code`, `close_notes` (mandatory by data policy, found in T7) |
| Change success rate | `change_request`: `type`, `state`, `close_code`, `start_date`, `end_date` |
| Change-induced incidents | `incident.caused_by` |

## 6. Validation approach
1. **Unit tests** (pytest): distributions, shares summing to 1, date ordering (opened ≤ resolved ≤ closed), priority matrix consistency.
2. **Ground truth:** the generator exports expected KPI values per month.
3. **Instance checks:** after load, `now-sdk query` counts are compared with ground truth.
4. **P4 reconciliation:** generator vs Platform Analytics vs Power BI.

## 7. Reference data
| Table | Records | Notes |
|---|---|---|
| `core_company` | 1 | Northgate Industrial |
| `cmn_location` | 6 | `NGI Lyon (HQ)` and five plants |
| `cmn_department` | 10 | `NGI Production`, `NGI IT`, … |
| `sys_user` | 3,500 | Names combined from per-country pools; e-mail on the reserved `.example` domain; `source = NGI-SYNTH-REF` |
| `sys_user_group` | 12 | "NGI" prefix: the PDI already has demo groups named Service Desk, Network, Database, Hardware, Software |
| `sys_user_grmember` | 64 | Agents are IT staff; site-bound groups use local staff; one group per agent |

Created 30 days before the history window, so no ticket predates its caller or group.

## 8. Incident arrivals (generator part 1)
- **Daily volume:** Poisson draw around `monthly_volume × 12 / 365`, scaled by weekday weight, month factor and the August dip. French public holidays get the Saturday weight.
- **Time of day:** on working days, 88 % between 08:00 and 18:00 Paris time; weekends and holidays between 07:00 and 21:00. Converted to UTC for ServiceNow (summer UTC+2, winter UTC+1; tested).
- **Window:** history ends the day **before** the load date; the daily trickle job takes over from load day.
- **Attributes:** caller drawn from all 3,500 users (location follows the caller), category and priority from configured mixes, impact/urgency always consistent with the priority matrix, subcategory valid for its category.
- **Load order = time order:** records are sorted by `opened_at`, so ServiceNow assigns INC numbers chronologically.
- **ERP wave (D7b):** 220 extra incidents, 9–13 March 2026, category `software` / subcategory `erp`, each with `caused_by` pointing to the failed change. The change's sys_id is derived from a fixed key, so the change module will create exactly that record.
- **Independent random streams:** base volume and the ERP wave use separate streams; switching the event off does not reshuffle the base data.

## 9. Incident lifecycle (generator part 2)
- **Routing:** first-contact resolution by the Service Desk with a category-dependent chance (password resets high, database low; P1s rarely), 60 % overall, rising to 68 % (D7c). Otherwise escalated with 1–3 reassignments to the group for the category (hardware → the caller's regional Workplace Support; `erp` → SAP ERP Support; `mes` → Plant OT).
- **Durations** are drawn in the SLA clock of the priority: P1 in real time (24×7), P2–P4 in NGI business hours (Mon–Fri 08:00–18:00 Paris, French holidays excluded). Resolution effort shrinks linearly to 75 % between January and July 2026 (D7c).
- **Exceptions:** 8 % go on hold (median 16 h, adds real time); 4 % reopen after 1–3 days; 2 % are cancelled; 1.5 % wait 30–90 days on a vendor.
- **State at cut-off** (00:00 Paris on load day): Closed if resolved ≥ 7 days earlier (auto-close), Resolved if more recent, otherwise New / In Progress / On Hold, with a share of open tickets untouched for more than 5 days.
- **Closure fields:** every Resolved/Closed incident has `close_code` (instance values, configured mix) and `close_notes`: the data policy found in T7.
- **Resolve times:** `calendar_stc` (real seconds) and `business_stc` (business seconds) computed from the stored, whole-second timestamps.
- **Resulting SLA picture (before hold pauses, run of 2026-09-27):** resolution targets missed by ~27 % of incidents in H2 2025, ~18 % in Q3 2026: a governance story, not a perfect service.

## 10. Rollback
`task_sla` and reference tables have no `correlation_id`. Every run therefore writes `manifest.json` (sys_ids per table). Rollback deletes by that manifest, never by broad queries.

## 11. Known limitations
- No audit, journal or metric history: the activity stream is empty on historic records.
- Only the final assignment group is stored; intermediate groups of reassigned incidents are not.
- SLA rows are computed by the generator, not by the SLA engine.
- Historic breakdowns reflect current values (for example, the final assignment group).
- The escalation routing placeholder `<region>` resolves to the caller site's Workplace Support group.
- Changes carry no change model (`chg_model`); the Brazil `model` change type is not used.
- Incident close codes are case-sensitive values with spaces (e.g. `Solution provided`), used exactly as on the instance.

## 12. Instance facts
Values read from the PDI are held in `instance_facts` in `config/ngi.yaml`, separate from business settings. They are refreshed from the instance with `now-sdk query` when the release changes.
