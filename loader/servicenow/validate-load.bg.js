// T9 validation – read-only. Counts what the load created; compare with output/ground_truth/counts.json
function count(table, encoded) {
    var ga = new GlideAggregate(table);
    ga.addEncodedQuery(encoded);
    ga.addAggregate('COUNT');
    ga.query();
    return ga.next() ? parseInt(ga.getAggregate('COUNT'), 10) : 0;
}
function groupCount(table, encoded, field) {
    var out = [], ga = new GlideAggregate(table);
    ga.addEncodedQuery(encoded);
    ga.addAggregate('COUNT');
    ga.groupBy(field);
    ga.orderBy(field);
    ga.query();
    while (ga.next()) out.push(ga.getValue(field) + '=' + ga.getAggregate('COUNT'));
    return out.join('  ');
}
gs.info('record_counts:');
gs.info('  core_company       ' + count('core_company', 'name=Northgate Industrial'));
gs.info('  cmn_location       ' + count('cmn_location', 'nameSTARTSWITHNGI '));
gs.info('  cmn_department     ' + count('cmn_department', 'nameSTARTSWITHNGI '));
gs.info('  sys_user           ' + count('sys_user', 'sourceSTARTSWITHNGI-SYNTH-'));
gs.info('  sys_user_group     ' + count('sys_user_group', 'nameSTARTSWITHNGI '));
gs.info('  sys_user_grmember  ' + count('sys_user_grmember', 'user.sourceSTARTSWITHNGI-SYNTH-'));
gs.info('  change_request     ' + count('change_request', 'correlation_id=NGI-SYNTH-CHG-01'));
gs.info('  incident           ' + count('incident', 'correlation_id=NGI-SYNTH-INC-01'));
gs.info('  task_sla           ' + count('task_sla', 'task.correlation_idSTARTSWITHNGI-SYNTH-'));
gs.info('incident by_state:        ' + groupCount('incident', 'correlation_id=NGI-SYNTH-INC-01', 'state'));
gs.info('change_request by_state:  ' + groupCount('change_request', 'correlation_id=NGI-SYNTH-CHG-01', 'state'));
gs.info('task_sla by stage:        ' + groupCount('task_sla', 'task.correlation_idSTARTSWITHNGI-SYNTH-', 'stage'));
gs.info('task_sla without SLA definition (expect 0): ' + count('task_sla', 'task.correlation_idSTARTSWITHNGI-SYNTH-^slaISEMPTY'));
gs.info('ERP wave incidents (subcategory erp, 9-13 Mar 2026): ' + count('incident',
    'correlation_id=NGI-SYNTH-INC-01^subcategory=erp^opened_at>=2026-03-08 23:00:00^opened_at<2026-03-13 23:00:00'));
var first = new GlideRecord('incident');
first.addEncodedQuery('correlation_id=NGI-SYNTH-INC-01');
first.orderBy('opened_at');
first.setLimit(1);
first.query();
if (first.next()) gs.info('first incident: ' + first.number + '  opened ' + first.opened_at + ' (UTC)  created ' + first.sys_created_on);
