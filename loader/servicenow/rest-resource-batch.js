// Scripted REST resource: POST /batch  (NGI Synthetic Loader)
(function process(/*RESTAPIRequest*/ request, /*RESTAPIResponse*/ response) {
    if (!gs.hasRole('admin')) {
        response.setStatus(403);
        response.setBody({ error: 'admin role required' });
        return;
    }
    try {
        response.setStatus(200);
        response.setBody(new NGISynthLoader().loadBatch(request.body.data));
    } catch (e) {
        response.setStatus(400);
        response.setBody({ error: String(e) });
    }
})(request, response);
