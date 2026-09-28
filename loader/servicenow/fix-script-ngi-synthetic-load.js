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
 * MODE 'rollback' : needs manifest.json. Deletes everything in it, children first.
 */
var MODE = 'smoke';
var ONLY_PREFIX = '';                 // e.g. '07-' to load only changes; '' = all files
var FIX_SCRIPT_NAME = 'NGI Synthetic Load';
var SLICE = 500;                      // NGISynthLoader accepts at most 500 records per call

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
    if (!me.get('name', FIX_SCRIPT_NAME)) {
        gs.error('[NGI.Load] Fix Script not found: ' + FIX_SCRIPT_NAME);
        return;
    }

    function attached(test) {
        var list = [];
        var a = new GlideRecord('sys_attachment');
        a.addQuery('table_name', 'sys_script_fix');
        a.addQuery('table_sys_id', me.getUniqueValue());
        a.orderBy('file_name');
        a.query();
        while (a.next()) {
            if (test(a.getValue('file_name'))) list.push({ name: a.getValue('file_name'), id: a.getUniqueValue() });
        }
        return list;
    }

    function read(file) {
        var a = new GlideRecord('sys_attachment');
        a.get(file.id);
        return JSON.parse(att.getContent(a));
    }

    function writeLog() {
        var stamp = new GlideDateTime().getValue().replace(/[: ]/g, '-');
        att.write(me, 'load-log-' + MODE + '-' + stamp + '.txt', 'text/plain', log.join('\n'));
    }

    say('MODE=' + MODE + ' started ' + started.getDisplayValue());
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
                return /^0[1-9]-.*\.json$/.test(n) && (!ONLY_PREFIX || n.indexOf(ONLY_PREFIX) === 0);
            });
            if (!files.length) throw new Error('no 01-..09- files attached' + (ONLY_PREFIX ? ' for ' + ONLY_PREFIX : ''));
            var total = { inserted: 0, skipped: 0 };
            var stop = false;
            for (var f = 0; f < files.length && !stop; f++) {
                var payload = read(files[f]);
                var fileRes = { inserted: 0, skipped: 0 };
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
    say('finished ' + new GlideDateTime().getDisplayValue());
    writeLog();
})();
