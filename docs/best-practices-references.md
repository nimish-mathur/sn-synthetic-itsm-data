# Best Practices References – sn-synthetic-itsm-data

Sources consulted (ServiceNow Best Practices Library, login required; referenced, not reproduced):
- **0001078** – Platform Analytics – Process Workshop Presentation (Australia, updated May 2026)
- **0001199** – Platform Analytics – Starter Stories (Australia)

Note: sources target the Australia release; this program runs on a Brazil Patch 0 PDI.

| Decision | Best Practice source | Applied how | Deviation + trade-off |
|---|---|---|---|
| KPI inputs are stored as fields on the source records, not computed by analytics scripts | 0001078 – "Scripting precaution" | Generator writes `resolved_at`, `calendar_stc`, `business_stc`, `reassignment_count`, `reopen_count`, `close_code` directly | None |
| Leading indicators require supporting data fields | 0001078 – "Leading/Lagging cascading down the stakeholder chain" | Generator produces realistic `sys_updated_on` (inactivity), reassignment distribution, and a long-running incident tail (>30 days) | None |
| Historic data collection run once, then deactivated | 0001199 – "Configuring & executing historical data collection" | After load: run historic job, then set inactive / On Demand (P1) | None |
| SLA-based measures use a database view | 0001078 – "Leverage the platform" | MTTA measured from response SLA records joined to incidents (P1) | None |
| Start from OOTB content, clone and adapt | 0001078 – "Additional unique analytics…"; 0001199 – "Enabling content pack plugins", "Checking indicator sources" | Generator populates the standard fields OOTB ITSM indicator sources expect | State-based OOTB sources give incorrect history under historic collection → date-based clones for backlog history. *Judgment, no library reference yet* |
| Analytics artifacts use subject-code prefixes | 0001078 – "Naming standards" (indicators, visualizations, filters, jobs) | e.g. `INC: MTTR (hours)`, job `ITSM.Historic` | Update sets use program naming `NGI-P<n>-<seq>-<desc>` for delivery traceability |
| Backdated records loaded with business rules and system-field updates disabled | *Standard practice / judgment, no library reference yet* | Loader sets `sys_created_on` / `sys_updated_on` and bypasses the SLA engine; `task_sla` rows written directly | Deviates from "configuration over customization": custom loader script. Trade-off: realistic history vs. no audit trail or engine-computed SLAs |
| History loaded by a Fix Script reading attachments (browser session), not the REST API | *Judgment, no library reference* | Fix Script "NGI Synthetic Load" + Script Include NGISynthLoader, update set NGI-P0-01 | Custom tooling; REST API deactivated after API password logins failed (401). Trade-off: no stored credentials vs. manual attachment step |
| incident.made_sla corrected after load | *Judgment, no library reference* | fix-made-sla.bg.js sets made_sla=false where the resolution SLA breached | Post-load data fix, needed because the SLA engine was bypassed for history |
