// Scripted REST resource: POST /rollback  (NGI Synthetic Loader)  body: {table, ids[]}
(function process(/*RESTAPIRequest*/ request, /*RESTAPIResponse*/ response) {
    if (!gs.hasRole('admin')) {
        response.setStatus(403);
        response.setBody({ error: 'admin role required' });
        return;
    }
    try {
        var body = request.body.data;
        response.setStatus(200);
        response.setBody({ table: body.table, deleted: new NGISynthLoader().rollbackByIds(String(body.table), body.ids) });
    } catch (e) {
        response.setStatus(400);
        response.setBody({ error: String(e) });
    }
})(request, response);
