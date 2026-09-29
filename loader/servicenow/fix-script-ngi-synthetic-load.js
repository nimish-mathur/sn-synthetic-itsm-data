/**
 * Fix Script: "NGI Synthetic Load"  (browser route – no API password needed)
 *
 * 1. Attach files from output/upload/ to THIS Fix Script record (paperclip icon).
 * 2. Set MODE below, click Update.
 * 3. Click "Run Fix Script" -> "Proceed in Background".
 * 4. Refresh the record: results are in the attachment "load-log-<time>.txt"
 *    (also in System Logs > All, message starting with [NGI.Load]).
 *
 * MODE 'smoke'    : needs 00-smoke-incident.json. Inserts 2 test incidents, re-sends (must skip), deletes them.
 * MODE 'load'     : loads every attached 01-..09- file in name order. Safe to re-run (existing records skipped).
 *                  STOP_BEFORE = '07-' loads only 01-..06- (reference data); '' loads everything.
 * MODE 'rollback' : needs manifest.json. Deletes everything in it, children first.
 */
var MODE = 'load';
var ONLY_PREFIX = '';                 // e.g. '07-' to load only changes; '' = all files
var STOP_BEFORE = '';                 // skip files whose name sorts at or after this; '' = no limit
var FIX_SCRIPT_NAME = 'NGI Synthetic Load';
var SLICE = 500;                      // NGISynthLoader accepts at most 500 records per call
var DROP_FIELDS = { incident: ['caused_by'] };   // fields absent on this instance (Brazil PDI: no incident.caused_by)

(function () {
    var loader = new NGISynthLoader();
    var att = new GlideSysAttachment();
    var log = [];
    var started = new GlideDateTime();

    function say(msg) {
        log.push(msg);
        gs.info('[NGI.Load] ' + msg);
    }

    var me = new GlideRecord('sys_script_fix');
    me.addQuery('name', FIX_SCRIPT_NAME);
    me.query();
    if (me.getRowCount() !== 1) {
        gs.error('[NGI.Load] Expected exactly 1 Fix Script named "' + FIX_SCRIPT_NAME + '", found ' + me.getRowCount() +
                 '. Keep the one with the attachments, delete the others.');
        return;
    }
    me.next();

    function attached(test) {
        var list = [];
        var a = new GlideRecord('sys_attachment');
        a.addQuery('table_name', 'sys_script_fix');
        a.addQuery('table_sys_id', me.getUniqueValue());
        a.orderBy('file_name');
        a.query();
        while (a.next()) {
            var fileName = String(a.getValue('file_name'));          // JS string (avoid Java String quirks)
            if (test(fileName)) list.push({ name: fileName, id: String(a.getUniqueValue()) });
        }
        return list;
    }

    var readMethod = '';
    function read(file) {
        var a = new GlideRecord('sys_attachment');
        if (!a.get(file.id)) throw new Error('attachment record not found: ' + file.name);
        var text = '';
        try {                                                     // 1st choice: getContent
            var c = att.getContent(a);
            if (c) { text = String(c); readMethod = readMethod || 'getContent'; }
        } catch (e1) { /* fall through */ }
        if (!text) {                                              // fallback: stream + GlideTextReader
            var reader = new GlideTextReader(att.getContentStream(file.id));
            var parts = [], line;
            while ((line = reader.readLine()) !== null) parts.push(String(line));
            text = parts.join('\n');
            if (text) readMethod = readMethod || 'getContentStream';
        }
        if (!text) throw new Error('could not read ' + file.name + ' (size_bytes=' + a.getValue('size_bytes') + ')');
        return JSON.parse(text);
    }

    function writeLog() {
        var stamp = String(new GlideDateTime().getValue()).replace(/[: ]/g, '-');   // String(): Java -> JS
        att.write(me, 'load-log-' + MODE + '-' + stamp + '.txt', 'text/plain', log.join('\n'));
    }

    say('MODE=' + MODE + ' started ' + started.getDisplayValue());
    var everything = attached(function () { return true; });
    say('Attachments on this record: ' + everything.length +
        (everything.length ? '  (first ' + everything[0].name + ', last ' + everything[everything.length - 1].name + ')' : ''));
    try {
        if (MODE === 'smoke') {
            var smoke = attached(function (n) { return n === '00-smoke-incident.json'; });
            if (!smoke.length) throw new Error('00-smoke-incident.json is not attached');
            var ids = [];
            var p1 = read(smoke[0]);
            for (var i = 0; i < p1.records.length; i++) ids.push(p1.records[i].sys_id);
            var r1 = loader.loadBatch(p1);
            var r2 = loader.loadBatch(read(smoke[0]));
            var deleted = loader.rollbackByIds('incident', ids);
            say((r1.inserted === 2 && !r1.errors.length ? 'PASS' : 'FAIL') + '  insert 2  ' + JSON.stringify(r1));
            say((r2.skipped === 2 && r2.inserted === 0 ? 'PASS' : 'FAIL') + '  re-send skips 2  ' + JSON.stringify(r2));
            say((deleted === 2 ? 'PASS' : 'FAIL') + '  rollback deletes 2  (deleted ' + deleted + ')');

        } else if (MODE === 'load') {
            var files = attached(function (n) {
                return /^0[1-9]-.*\.json$/.test(n) && (!ONLY_PREFIX || n.indexOf(ONLY_PREFIX) === 0) &&
                       (!STOP_BEFORE || n < STOP_BEFORE);
            });
            if (!files.length) throw new Error('no 01-..09- files attached' + (ONLY_PREFIX ? ' for ' + ONLY_PREFIX : ''));
            for (var dt in DROP_FIELDS) if (DROP_FIELDS.hasOwnProperty(dt)) say('Dropping fields on ' + dt + ': ' + DROP_FIELDS[dt].join(', '));
            say('Files selected: ' + files.length + '  (first ' + files[0].name + ', last ' + files[files.length - 1].name + ')');
            var total = { inserted: 0, skipped: 0 };
            var stop = false;
            for (var f = 0; f < files.length && !stop; f++) {
                var payload = read(files[f]);
                var fileRes = { inserted: 0, skipped: 0 };
                var drop = DROP_FIELDS[payload.table] || [];
                if (drop.length) {
                    for (var r = 0; r < payload.records.length; r++) {
                        for (var x = 0; x < drop.length; x++) delete payload.records[r][drop[x]];
                    }
                }
                for (var s = 0; s < payload.records.length; s += SLICE) {
                    var res = loader.loadBatch({ table: payload.table, options: payload.options,
                        resolve: payload.resolve, records: payload.records.slice(s, s + SLICE) });
                    fileRes.inserted += res.inserted;
                    fileRes.skipped += res.skipped;
                    if (res.errors.length) {
                        say('STOPPED in ' + files[f].name + ' (' + res.errors.length + ' errors). First: ' + res.errors[0]);
                        stop = true;
                        break;
                    }
                }
                total.inserted += fileRes.inserted;
                total.skipped += fileRes.skipped;
                say(files[f].name + '  inserted ' + fileRes.inserted + '  skipped ' + fileRes.skipped);
            }
            say('TOTAL inserted ' + total.inserted + '  skipped ' + total.skipped + (stop ? '  (STOPPED)' : '  (COMPLETE)'));

        } else if (MODE === 'rollback') {
            var man = attached(function (n) { return n === 'manifest.json'; });
            if (!man.length) throw new Error('manifest.json is not attached');
            var tables = read(man[0]).tables;
            var order = ['task_sla', 'incident', 'change_request', 'sys_user_grmember', 'sys_user_group',
                         'sys_user', 'cmn_department', 'cmn_location', 'core_company'];
            for (var t = 0; t < order.length; t++) {
                var list = tables[order[t]] || [];
                var gone = 0;
                for (var k = 0; k < list.length; k += SLICE) gone += loader.rollbackByIds(order[t], list.slice(k, k + SLICE));
                if (list.length) say(order[t] + '  deleted ' + gone + ' of ' + list.length);
            }
        } else {
            throw new Error('Unknown MODE: ' + MODE);
        }
    } catch (e) {
        say('ERROR: ' + e);
    }
    if (readMethod) say('Attachment read method: ' + readMethod);
    say('finished ' + new GlideDateTime().getDisplayValue());
    writeLog();
})();
