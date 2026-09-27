// T7 smoke test – 9 backdated incidents + 1 control incident
var TAG = 'NGI-SYNTH-SMOKE-01';
var USER = 'ngi.synth.loader';
var loader = new NGISynthLoader();

function addHours(dt, hours) {           // dt in UTC 'YYYY-MM-DD HH:mm:ss'
    var g = new GlideDateTime();
    g.setValue(dt);
    g.addSeconds(Math.round(hours * 3600));
    return g.getValue();
}
function sid(n) {                         // deterministic test sys_id, 32 hex chars
    return '5e11c7ed' + '0000000000000000000000' + (n < 10 ? '0' + n : '' + n);
}

var opened = ['2025-07-03 07:15:00', '2025-08-12 09:40:00', '2025-09-22 13:05:00',
              '2025-10-14 06:50:00', '2025-11-27 15:30:00', '2025-12-09 08:20:00',
              '2026-01-19 10:10:00', '2026-02-24 12:45:00', '2026-03-11 07:05:00'];
var hoursToResolve = [3, 6, 20, 45, 10, 30, 8, 60, 5];
var cats = ['inquiry', 'software', 'hardware', 'network', 'database', 'password_reset'];
var matrix = [['1', '1', '1'], ['1', '2', '2'], ['2', '2', '3'], ['2', '3', '4']]; // impact, urgency, priority

var records = [];
for (var i = 0; i < opened.length; i++) {
    var m = matrix[i % matrix.length];
    var resolved = addHours(opened[i], hoursToResolve[i]);
    var closed = addHours(resolved, 7 * 24);                 // auto-close = 7 days (T2)
    records.push({
        sys_id: sid(i + 1),
        short_description: '[SMOKE] NGI loader test ' + (i + 1),
        category: cats[i % cats.length],
        impact: m[0], urgency: m[1], priority: m[2],
        state: '7', incident_state: '7', active: 'false',     // Closed (set both: sync rule is off)
        opened_at: opened[i], resolved_at: resolved, closed_at: closed,
        sys_created_on: opened[i], sys_updated_on: closed,
        sys_created_by: USER, sys_updated_by: USER,
        correlation_id: TAG
    });
}

// Control record: inserted WITHOUT keeping our dates, to prove A1 makes a difference
var control = {
    sys_id: sid(10),
    short_description: '[SMOKE] NGI loader control (dates NOT kept)',
    category: 'software', impact: '2', urgency: '2', priority: '3',
    state: '2', incident_state: '2', active: 'true',          // In Progress
    opened_at: '2025-09-01 08:00:00', sys_created_on: '2025-09-01 08:00:00',
    correlation_id: TAG
};

gs.info('Backdated run: ' + JSON.stringify(loader.insertBackdated('incident', records)));
gs.info('Control run:   ' + JSON.stringify(loader.insertBackdated('incident', [control], { keepSysFields: false })));