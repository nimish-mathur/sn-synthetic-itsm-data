/**
 * NGISynthLoader – v2 (T8.8)
 * Server-side loader for synthetic, backdated ITSM data (fictional client Northgate Industrial).
 * Global scope Script Include, called by the "NGI Synthetic Loader" Scripted REST API.
 * Foundation tooling: deactivate the REST API after the data load.
 */
var NGISynthLoader = Class.create();
NGISynthLoader.prototype = {
    initialize: function() {
        this.TAG_FIELD = 'correlation_id';
        this.TAG_PREFIX = 'NGI-SYNTH-';
        this.ALLOWED_TABLES = ['core_company', 'cmn_location', 'cmn_department', 'sys_user', 'sys_user_group',
                               'sys_user_grmember', 'change_request', 'incident', 'task_sla'];
        this.MAX_BATCH = 500;
        this._cache = {};
    },

    /** Entry point for one batch file: {table, options, resolve, records}. */
    loadBatch: function(payload) {
        if (!payload || this.ALLOWED_TABLES.indexOf(String(payload.table)) < 0) {
            throw new Error('Table not allowed: ' + (payload ? payload.table : 'none'));
        }
        var records = payload.records || [];
        if (records.length > this.MAX_BATCH) {
            throw new Error('Batch too large: ' + records.length + ' > ' + this.MAX_BATCH);
        }
        return this.insertBackdated(String(payload.table), records, payload.options || {}, payload.resolve || {});
    },

    /**
     * Inserts records with caller-supplied sys_id and (optionally) caller-supplied system dates.
     * @param {Object} options {keepSysFields: true (default), runBusinessRules: false (default)}
     * @param {Object} resolve {targetField: {table, match_field, source_key}} name -> sys_id lookups
     */
    insertBackdated: function(table, records, options, resolve) {
        options = options || {};
        resolve = resolve || {};
        var keepSysFields = options.keepSysFields !== false;
        var runBusinessRules = options.runBusinessRules === true;
        var result = { table: table, inserted: 0, skipped: 0, errors: [] };

        for (var i = 0; i < records.length; i++) {
            var rec = records[i];
            try {
                if (!rec.sys_id || !/^[0-9a-f]{32}$/.test(rec.sys_id)) {
                    result.errors.push('Record ' + i + ': invalid sys_id');
                    continue;
                }
                var check = new GlideRecord(table);
                if (check.get(rec.sys_id)) {                 // idempotent: never insert twice
                    result.skipped++;
                    continue;
                }
                if (!this._resolve(rec, resolve, result, i)) continue;

                var gr = new GlideRecord(table);
                gr.newRecord();                              // defaults, e.g. INC/CHG number
                gr.setNewGuidValue(rec.sys_id);
                gr.autoSysFields(!keepSysFields);
                gr.setWorkflow(runBusinessRules);

                for (var field in rec) {
                    if (!rec.hasOwnProperty(field) || field === 'sys_id') continue;
                    if (!gr.isValidField(field)) {
                        result.errors.push('Record ' + i + ': unknown field ' + field);
                        continue;
                    }
                    gr.setValue(field, rec[field]);          // dates in UTC, YYYY-MM-DD HH:mm:ss
                }
                if (gr.insert()) {
                    result.inserted++;
                } else {
                    result.errors.push('Record ' + i + ': insert failed ' + gr.getLastErrorMessage());
                }
            } catch (e) {
                result.errors.push('Record ' + i + ': ' + e);
            }
        }
        return result;
    },

    /** Replaces name keys (e.g. sla_name) by the sys_id of the matching record on this instance. */
    _resolve: function(rec, resolve, result, i) {
        for (var target in resolve) {
            if (!resolve.hasOwnProperty(target)) continue;
            var rule = resolve[target];
            var name = rec[rule.source_key];
            delete rec[rule.source_key];
            if (!name) continue;
            var id = this._lookup(rule.table, rule.match_field, name);
            if (!id) {
                result.errors.push('Record ' + i + ': ' + rule.table + ' "' + name + '" not found or not unique');
                return false;
            }
            rec[target] = id;
        }
        return true;
    },

    _lookup: function(table, field, value) {
        var key = table + '|' + field + '|' + value;
        if (this._cache.hasOwnProperty(key)) return this._cache[key];
        var gr = new GlideRecord(table);
        gr.addQuery(field, value);
        gr.setLimit(2);
        gr.query();
        var id = null, n = 0;
        while (gr.next()) {
            n++;
            id = gr.getUniqueValue();
        }
        this._cache[key] = (n === 1) ? id : null;
        return this._cache[key];
    },

    /**
     * Deletes the given sys_ids (from manifest.json). Extra guards: history records must carry
     * the NGI-SYNTH- tag; users must have source NGI-SYNTH-...
     * @returns {Number} records deleted
     */
    rollbackByIds: function(table, ids) {
        if (this.ALLOWED_TABLES.indexOf(String(table)) < 0) throw new Error('Table not allowed: ' + table);
        if (!ids || !ids.length) return 0;
        if (ids.length > this.MAX_BATCH) throw new Error('Too many ids: ' + ids.length);
        for (var i = 0; i < ids.length; i++) {
            if (!/^[0-9a-f]{32}$/.test(ids[i])) throw new Error('Invalid sys_id: ' + ids[i]);
        }
        var gr = new GlideRecord(table);
        gr.addQuery('sys_id', 'IN', ids.join(','));
        if (table === 'incident' || table === 'change_request') gr.addQuery(this.TAG_FIELD, 'STARTSWITH', this.TAG_PREFIX);
        if (table === 'task_sla') gr.addQuery('task.' + this.TAG_FIELD, 'STARTSWITH', this.TAG_PREFIX);
        if (table === 'sys_user') gr.addQuery('source', 'STARTSWITH', this.TAG_PREFIX);
        if (table === 'sys_user_grmember') gr.addQuery('user.source', 'STARTSWITH', this.TAG_PREFIX);
        gr.query();
        var count = 0;
        while (gr.next()) {
            gr.setWorkflow(false);
            gr.deleteRecord();
            count++;
        }
        return count;
    },

    /** v1 API kept for the T7 smoke test: deletes by load tag. */
    rollback: function(table, tag) {
        if (!tag || tag.indexOf(this.TAG_PREFIX) !== 0) {
            throw new Error('Rollback refused: tag must start with ' + this.TAG_PREFIX);
        }
        var counter = new GlideAggregate(table);
        counter.addQuery(this.TAG_FIELD, tag);
        counter.addAggregate('COUNT');
        counter.query();
        var count = counter.next() ? parseInt(counter.getAggregate('COUNT'), 10) : 0;
        var gr = new GlideRecord(table);
        gr.addQuery(this.TAG_FIELD, tag);
        gr.setWorkflow(false);
        gr.deleteMultiple();
        return count;
    },

    type: 'NGISynthLoader'
};
