"""Compatibility-shaped legacy matrix backed only by exact v2 observations."""
import aa


def matrix(state):
    s = state['availability']
    models = s.catalog()['models']
    accounts = s.accounts()
    rows = []
    for owner in accounts['owners']:
        if owner['owner'] is None: continue
        cells = {}
        for key in accounts['keys']:
            if key['owner'] != owner['owner']: continue
            for c in key['connections']:
                status = 'ok' if c['state'] == 'working' else c['state']
                cells.setdefault(c['model_id'], []).append({
                    'connection_id':c['id'], 'name':key['reference'], 'model':c['model'],
                    'state':status, 'l1':status, 'l2':'not-run', 'divergent':False,
                    'checked_at':c['checked_at'], 'aa_score':aa.score_for(state.get('aa_scores',{}),c['provider'],c['model'])})
        rows.append({'email':owner['owner'],'cells':cells})
    return {'emails':[row['email'] for row in rows], 'rows':rows,
            'providers':[{'id':m['id'],'provider':m['provider'],'model':m['model'],'probed':bool(m['checked'])} for m in models],
            'diagnostics':{'unassigned':[{'id':k['id'],'provider':k['provider'],'name':k['reference']} for k in accounts['keys'] if k['owner'] is None],
                           'skipped_inactive':[], 'divergent':[], 'inventory_more':{}},
            'aa_stale':state.get('aa_stale',True),'keeperPackVersion':'v2',
            'evidence':'exact_direct_api', 'preferred_api':'/api/v2/catalog'}
