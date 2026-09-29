// T10 data fix: incident.made_sla is set by the live SLA engine, which the history load bypassed,
// so every loaded incident kept the default (true). Set made_sla = false where the resolution SLA breached.
// MODE 'auto': counts first, and only fixes if the count is in the expected range (safety guard).
// MODE 'dryrun' only counts; MODE 'fix' always fixes. Dates are kept (autoSysFields off).
var MODE = 'auto';
var EXPECTED_MIN = 1500, EXPECTED_MAX = 8000;
var ids = {};
var s = new GlideRecord('task_sla');
s.addEncodedQuery('task.correlation_id=NGI-SYNTH-INC-01^has_breached=true^sla.target=resolution');
s.query();
while (s.next()) ids[String(s.getValue('task'))] = true;
var list = Object.keys(ids);
if (MODE === 'auto') {
    MODE = (list.length >= EXPECTED_MIN && list.length <= EXPECTED_MAX) ? 'fix' : 'dryrun';
    if (MODE === 'dryrun') gs.info('SAFETY STOP: count outside ' + EXPECTED_MIN + '-' + EXPECTED_MAX + ', nothing changed.');
}
gs.info('Incidents with a breached resolution SLA: ' + list.length + (MODE === 'fix' ? '  -> setting made_sla=false' : '  (dry run, nothing changed)'));
if (MODE === 'fix') {
    var done = 0;
    for (var i = 0; i < list.length; i += 500) {
        var inc = new GlideRecord('incident');
        inc.addQuery('sys_id', 'IN', list.slice(i, i + 500).join(','));
        inc.addQuery('correlation_id', 'NGI-SYNTH-INC-01');
        inc.query();
        while (inc.next()) {
            inc.autoSysFields(false);
            inc.setWorkflow(false);
            inc.setValue('made_sla', false);
            inc.update();
            done++;
        }
    }
    var check = new GlideAggregate('incident');
    check.addEncodedQuery('correlation_id=NGI-SYNTH-INC-01^made_sla=false');
    check.addAggregate('COUNT');
    check.query();
    gs.info('Updated: ' + done + '   incidents now made_sla=false: ' + (check.next() ? check.getAggregate('COUNT') : '?'));
}
