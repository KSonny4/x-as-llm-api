'use strict';
// No provider data is interpolated as markup. Secrets live only in this closure/explicit panel.
(() => {
  const $ = id => document.getElementById(id);
  let snapshot, csrf, view = 'accounts', credential, clearTimer, loading = false;
  const openDetails = new Set();
  const el = (tag, text, cls) => {const n = document.createElement(tag); if(text !== undefined) n.textContent = text; if(cls) n.className = cls; return n;};
  const stamp = value => value ? new Date(value * 1000).toLocaleString() : 'Not checked';
  const label = value => (value || 'unknown').replaceAll('_', ' ');
  const badge = state => el('span', label(state), 'badge ' + state);
  const notice = (text, error = false) => {$('notice').textContent = text; $('notice').className = error ? 'error' : '';};
  async function api(path, body) {
    const options = {credentials:'same-origin', cache:'no-store', headers:{}};
    if(body !== undefined) {options.method='POST'; options.headers={'Content-Type':'application/json','X-Keeper-CSRF':csrf}; options.body=JSON.stringify(body);}
    const r = await fetch('/api/v2/' + path, options);
    if(r.status === 401) {clearCredential(); throw Error('Session expired. Sign in at /login.');}
    const data = await r.json();
    if(!r.ok) throw Error(label(data.error || 'Request failed'));
    return data;
  }
  function button(text, action) {
    const b = el('button', text); b.type='button';
    b.onclick = async () => {b.disabled=true; notice('Working…'); try {await action();} catch(e) {notice(e.message, true);} finally {b.disabled=false;}};
    return b;
  }
  function details(id, title) {
    const d=el('details'), summary=el('summary'); summary.append(title); d.append(summary);
    d.open=openDetails.has(id); d.ontoggle=()=>d.open?openDetails.add(id):openDetails.delete(id); return d;
  }
  function matches(provider, values) {
    return (!$('provider').value || $('provider').value === provider) && values.join(' ').toLowerCase().includes($('search').value.toLowerCase());
  }
  function cellsTable(cells) {
    const wrap=el('div', undefined, 'table-wrap'), table=el('table'), head=el('thead'), hr=el('tr');
    ['Model / route','Result / reason','Last check / retry'].forEach(t=>{const th=el('th',t);th.scope='col';hr.append(th);});head.append(hr);table.append(head);
    const body=el('tbody');
    cells.forEach(c=>{const row=el('tr'), name=el('td'), state=el('td'), time=el('td');
      name.append(el('strong',c.model),el('p',c.protocol+' · '+c.base_url,'muted'));
      state.append(badge(c.state));if(c.blocked_reason) state.append(el('p',label(c.blocked_reason),'muted'));
      time.append(el('span',stamp(c.checked_at)));if(c.retry_at > snapshot.now)time.append(el('p','Retry '+stamp(c.retry_at)));
      row.append(name,state,time);body.append(row);});table.append(body);wrap.append(table);return wrap;
  }
  async function check(scope) {const p=await api('checks',scope);notice('Queued '+p.total+' eligible connections. Cooldowns remain in effect.');await refresh(false);}
  function clearCredential() {credential=null;clearTimeout(clearTimer);$('config').value='';$('credential').hidden=true;}
  function showCredential(data) {
    credential=data;$('config').value=JSON.stringify(data,null,2);$('credential').hidden=false;
    $('credential-meta').textContent=data.provider+' · '+data.model+' · '+data.protocol+' · Verified '+stamp(data.verified_at);
    clearTimeout(clearTimer);clearTimer=setTimeout(clearCredential,120000);notice('Verified provider connection ready.');
    $('copy-token').focus();
  }
  async function getToken(id) {clearCredential();showCredential(await api('credentials',{model_id:id}));await refresh(false);}
  function render() {
    if(!snapshot)return;
    const content=$('content'), fragment=document.createDocumentFragment();let count=0;
    if(view==='accounts') snapshot.owners.forEach(owner=>{
      const keys=snapshot.keys.filter(k=>k.owner===owner.owner && matches(k.provider,[owner.owner||'Unassigned',k.reference,...k.connections.map(c=>c.model)]));
      if(!keys.length)return;count++;
      const title=el('span',undefined,'row');title.append(el('strong',owner.owner||'Unassigned'),badge(owner.state),el('span',owner.working_keys+' / '+owner.total_keys+' working keys','muted'));
      const d=details('owner:'+owner.owner,title), inner=el('div',undefined,'detail');
      keys.forEach(k=>{const title=el('span',undefined,'row');title.append(el('strong',k.provider+' · '+k.reference),badge(k.state),el('span',k.working+' / '+k.total+' working · '+k.checked+' checked','muted'));
        const key=details(k.id,title), detail=el('div',undefined,'detail');
        detail.append(button('Check key',()=>check({credential_id:k.id})),cellsTable(k.connections));key.append(detail);inner.append(key);});d.append(inner);fragment.append(d);
    });
    else snapshot.models.filter(m=>matches(m.provider,[m.model,m.provider])).forEach(m=>{
      count++;const title=el('span',undefined,'row');title.append(el('strong',m.model+' / '+m.provider),badge(m.eligibility==='free'?m.state:m.eligibility),el('span','Coding '+(m.coding_index??'— unmatched')+' · '+m.working_keys+' / '+m.total_keys+' keys','muted'));
      const d=details(m.id,title), inner=el('div',undefined,'detail'), actions=el('div',undefined,'actions');
      actions.append(button('Check model',()=>check({model_id:m.id})),button('Get verified token',()=>getToken(m.id)));
      inner.append(el('p',m.protocol+' · '+m.base_url,'muted'),el('p','Eligibility: '+m.eligibility+' · '+(m.provenance||'No pricing proof')+' · '+stamp(m.checked_at),'muted'),actions,cellsTable(m.connections));d.append(inner);fragment.append(d);
    });
    if(!count)fragment.append(el('p','No matching results. Try another filter; unknown and disabled entries remain accounted for.','muted'));
    content.replaceChildren(fragment);
    $('key-health').textContent=snapshot.keys.filter(k=>k.state==='working').length+' / '+snapshot.keys.length+' working';
    $('coverage').textContent=snapshot.models.length+' models · '+snapshot.keys.reduce((n,k)=>n+k.checked,0)+' checked pairs';
    const p=snapshot.sweep;$('progress').textContent=p?p.done+' / '+p.total+' completed · '+p.pending+' pending':'Not started';
    $('sweep-time').textContent=p?stamp(p.created_at)+' · '+p.blocked+' blocked':'Daily and manual, paced to protect free quotas';
    $('aa-status').textContent='AA Coding Index · '+(snapshot.aa.stale?'Stale / unavailable':'Cached')+' · '+stamp(snapshot.aa.succeeded_at);
    $('build').textContent='Build '+snapshot.build;
  }
  async function refresh(announce=true) {
    if(loading)return;loading=true;
    try {snapshot=await api('catalog');const chosen=$('provider').value;const providers=[...new Set([...snapshot.models,...snapshot.keys].map(m=>m.provider))].sort();
      $('provider').replaceChildren(el('option','All providers'));$('provider').firstChild.value='';providers.forEach(p=>{const o=el('option',p);o.value=p;$('provider').append(o);});$('provider').value=chosen;
      // Avoid replacing a focused control while periodic polling is in progress.
      if(announce || !$('content').contains(document.activeElement))render();
      if(snapshot.worker_error)notice('Background checks stopped. Administrator attention required.',true);
      else if(announce)notice('Local snapshot refreshed. Page reads never run inference.');
    } finally {loading=false;}
  }
  ['accounts','models'].forEach(tab=>{$('tab-'+tab).onclick=()=>{view=tab;['accounts','models'].forEach(t=>$('tab-'+t).setAttribute('aria-pressed',String(t===tab)));render();};});
  $('search').oninput=render;$('provider').onchange=render;
  $('refresh').onclick=()=>refresh().catch(e=>notice(e.message,true));
  $('check-all').onclick=async()=>{const b=$('check-all');b.disabled=true;try{await check({});}catch(e){notice(e.message,true);}finally{b.disabled=false;}};
  $('copy-token').onclick=()=>navigator.clipboard.writeText(credential.api_key).then(()=>notice('Provider token copied.')).catch(()=>notice('Clipboard unavailable. Select the config manually.',true));
  $('copy-config').onclick=()=>navigator.clipboard.writeText($('config').value).then(()=>notice('Connection config copied.')).catch(()=>notice('Clipboard unavailable. Select the config manually.',true));
  $('clear-token').onclick=clearCredential;
  $('replace').onclick=async()=>{const id=credential.connection_id;clearCredential();try{showCredential(await api('feedback',{connection_id:id,reason:'client_failure'}));}catch(e){notice(e.message,true);}await refresh(false);};
  $('logout').onclick=async()=>{clearCredential();await fetch('/api/v1/session/logout',{method:'POST',credentials:'same-origin'});location='/login';};
  window.addEventListener('pagehide',clearCredential);
  (async()=>{try{csrf=(await api('session')).csrf;await refresh();}catch(e){notice(e.message,true);}})();
  setInterval(()=>{if(!document.hidden)refresh(false).catch(e=>notice('Status refresh failed: '+e.message,true));},15000);
})();
