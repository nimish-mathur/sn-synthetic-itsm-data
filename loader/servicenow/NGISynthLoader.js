var NGISynthLoader = Class.create();
NGISynthLoader.prototype = {
    initialize: function() {
        this.TAG_FIELD = 'correlation_id';   // label field used to find/delete our records
        this.TAG_PREFIX = 'NGI-SYNTH-';      // every load tag must start with this
    },

    /**
     * Inserts records with a caller-supplied sys_id and (optionally) caller-supplied system dates.
     * @param {String} table   target table, e.g. 'incident'
     * @param {Array}  records objects like {sys_id: '<32 hex chars>', field: value, ...}
     * @param {Object} options {keepSysFields: true (default), runBusinessRules: false (default)}
     * @returns {Object} {table, inserted, skipped, errors[]}
     */
    insertBackdated: function(table, records, options) {
        options = options || {};
        var keepSysFields = options.keepSysFields !== false;
        var runBusinessRules = options.runBusinessRules === true;
        var result = { table: table, inserted: 0, skipped: 0, errors: [] };

        for (var i = 0; i < records.length; i++) {
            var rec = records[i];
            try {
                // A3: sys_id must be supplied and valid
                if (!rec.sys_id || !/^[0-9a-f]{32}$/.test(rec.sys_id)) {
                    result.errors.push('Record ' + i + ': invalid sys_id');
                    continue;
                }
                // A4: never insert the same record twice
                var check = new GlideRecord(table);
                if (check.get(rec.sys_id)) {
                    result.skipped++;
                    continue;
                }

                var gr = new GlideRecord(table);
                gr.newRecord();                      // applies defaults, e.g. incident number
                gr.setNewGuidValue(rec.sys_id);      // A3: use our sys_id
                gr.autoSysFields(!keepSysFields);    // A1: keep our dates
                gr.setWorkflow(runBusinessRules);    // A2: no business rules / SLA engine

                for (var field in rec) {
                    if (!rec.hasOwnProperty(field) || field === 'sys_id') continue;
                    if (!gr.isValidField(field)) {
                        result.errors.push('Record ' + i + ': unknown field ' + field);
                        continue;
                    }
                    gr.setValue(field, rec[field]);  // dates are in UTC, format YYYY-MM-DD HH:mm:ss
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

    /**
     * A5: deletes every record carrying the given load tag. Refuses tags not starting with NGI-SYNTH-.
     * @returns {Number} number of records deleted
     */
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