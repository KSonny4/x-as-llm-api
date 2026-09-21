// Optional browser regression: PLAYWRIGHT_MODULE may point at an installed
// Playwright package; CHROME_EXECUTABLE selects a system browser. No live API.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('fs'), os=require('os'), path=require('path');
(async()=>{
 const root=__dirname, out=process.env.KEEPER_BROWSER_OUT || fs.mkdtempSync(path.join(os.tmpdir(),'keeper-browser-'));
 fs.mkdirSync(out,{recursive:true});
 const now=1800000000, commit=process.env.QA_COMMIT || 'working-tree';
 const models=Array.from({length:26},(_,i)=>({id:'m'+i,provider:i<24?'zen-test':'other-test',model:i===0?'UNCHECKED_MODEL':i===1?'<img src=x onerror=window.__xss=1>':'test-model-'+i,base_url:'https://provider.invalid/v1',protocol:'openai',eligibility:'free',provenance:'https://provider.invalid/pricing',checked_at:now,working_keys:0,total_keys:1,coding_index:null,connections:[{id:'c'+i,model:i===0?'UNCHECKED_MODEL':'test-model-'+i,protocol:'openai',base_url:'https://provider.invalid/v1',state:'unknown',checked_at:null,retry_at:0,blocked_reason:null}]}));
 models.forEach(m=>Object.assign(m,{exportable:true,state:'unknown',transport_note:'Direct provider API'}));
 Object.assign(models[25],{model:'BRIDGE_ONLY_MODEL',protocol:'zencli',exportable:false,transport_note:'Genuine CLI · text only · no streaming'});
 Object.assign(models[24],{model:'DIRECT_CLI_REQUIRED',state:'cli_required',transport_note:'CLI required · direct free Zen inference disabled by policy'});
 Object.assign(models[0].connections[0],{retry_at:now+600,cooldown_scope:'legacy_scope_unknown'});
 const fixture={now,models,owners:[{owner:null,state:'unknown',working_keys:0,total_keys:1}],keys:[{id:'k1',active:true,supported:true,has_secret:true,owner:null,provider:'zen-test',reference:'TEST_KEY',state:'unknown',working:0,total:26,checked:0,connections:models.map(m=>m.connections[0])}],discovery:[{credential_id:'k1',checked_at:now,succeeded_at:now,error:null}],bridge_error:null,sweep:null,aa:{stale:true,succeeded_at:null},build:commit+'-fixture',worker_error:null};
 const browser=await chromium.launch({...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{}),headless:true});
 try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[],calls=[];
 await page.clock.install();
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://keeper.test/**',async r=>{
  const path=new URL(r.request().url()).pathname;calls.push(path);
  if(path==='/api/v2/session')return r.fulfill({json:{csrf:'test-csrf'}});
  if(path==='/api/v2/catalog')return r.fulfill({json:fixture});
  if(path==='/api/v2/checks')return r.fulfill({status:202,json:{total:26}});
  if(path==='/api/v2/credentials')return r.fulfill({json:{api_key:'synthetic-provider-secret',connection_id:'c0',model:'UNCHECKED_MODEL',protocol:'openai',provider:'zen-test',verified_at:now}});
  const assets={'/':'dashboard.html','/assets/dashboard.css':'dashboard.css','/assets/dashboard.js':'dashboard.js'};
  if(assets[path])return r.fulfill({body:fs.readFileSync(root+'/'+assets[path]),contentType:path.endsWith('.css')?'text/css':path.endsWith('.js')?'text/javascript':'text/html'});
  return r.fulfill({status:404,body:''});
 });
 await page.goto('https://keeper.test/');await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Local snapshot refreshed'));
 await page.screenshot({path:out+'/accounts-desktop.png',fullPage:true});
 await page.locator('#tab-models').click();
 const modelCount=await page.locator('#content > details').count();
 const uncheckedStatus=await page.locator('#content > details').first().locator('summary .badge').innerText();
 const injectionElements=await page.locator('#content img').count();
 const bridge=page.locator('#content > details').filter({has:page.getByText('BRIDGE_ONLY_MODEL / other-test',{exact:true})});
 await bridge.locator('summary').click();
 const bridgeExportUnavailable=await bridge.getByRole('button',{name:'Get verified token',exact:true}).count()===0 && await bridge.getByText('Service-only backend · provider key export unavailable',{exact:true}).count()===1;
 const policy=page.locator('#content > details').filter({has:page.getByText('DIRECT_CLI_REQUIRED / other-test',{exact:true})});
 await policy.locator('summary').click();
 const policyActionsHidden=await policy.getByRole('button').count()===0;
 const aaAttribution=await page.locator('a[href*="artificialanalysis.ai"]').count()>0;
 await page.locator('#content > details').first().locator('summary').click();
 await page.screenshot({path:out+'/models-desktop.png',fullPage:true});
 await page.getByRole('button',{name:'Get verified token',exact:true}).first().click();await page.waitForFunction(()=>!document.querySelector('#credential').hidden);
 const credentialVisible=await page.locator('#config').inputValue();await page.locator('#clear-token').click();
 const cleared=await page.locator('#config').inputValue()==='' && await page.locator('#credential').isHidden();
 await page.getByRole('button',{name:'Get verified token',exact:true}).first().click();
 await page.waitForFunction(()=>!document.querySelector('#credential').hidden);
 await page.clock.fastForward(120001);
 await page.waitForFunction(()=>document.querySelector('#credential').hidden);
 const autoExpired=await page.locator('#config').inputValue()==='';
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:out+'/models-mobile.png',fullPage:true});
 const overflow=await page.evaluate(()=>({body:document.body.scrollWidth,viewport:innerWidth}));
 await page.locator('#search').fill('UNCHECKED_MODEL');const filteredCount=await page.locator('#content > details').count();
 fixture.discovery[0].error='discovery_failed';fixture.bridge_error='bridge_unavailable';
 await page.locator('#search').fill('');await page.locator('#tab-accounts').click();await page.locator('#refresh').click();
 await page.waitForFunction(()=>!document.querySelector('#inventory-warning').hidden);
 const warning=await page.locator('#inventory-warning').innerText();
 await page.locator('#content > details > summary').click();await page.locator('#content details details > summary').click();
 const detail=await page.locator('#content').innerText();
 const legacyCooldownVisible=detail.includes('Legacy cooldown scope unknown');
 const discoveryFailureVisible=warning.includes('Inventory incomplete')&&warning.includes('CLI bridge unavailable')&&detail.includes('Last attempt:')&&detail.includes('Last success:')&&detail.includes('Discovery failed');
 const warningNoOverflow=await page.evaluate(()=>document.body.scrollWidth<=innerWidth);
 // Cross-layer review fixtures are generated by the actual Availability/API
 // projection, not manually relabelled browser objects. No provider transport.
 const review=JSON.parse(require('child_process').execFileSync('python3',[root+'/test_dashboard.py'],{encoding:'utf8'}));
 let reviewRevision=0;
 async function reviewAccounts(doc) {
  Object.keys(fixture).forEach(k=>delete fixture[k]);Object.assign(fixture,doc,{build:doc.build+'-'+(++reviewRevision)});
  await page.locator('#refresh').click();
  await page.waitForFunction(build=>document.querySelector('#build').textContent==='Build '+build,fixture.build);
  await page.locator('#content details > summary').evaluateAll(nodes=>nodes.forEach(n=>n.parentElement.open=true));
 }
 await reviewAccounts(review.before);
 const keyPanel=reference=>page.locator('#content details details').filter({has:page.locator('summary strong').filter({hasText:reference})});
 const admissionResults=[];
 for(const [reference,reason] of [['UNSUPPORTED_KEY','unsupported'],['SIGNIN_KEY','sign in required'],['DISABLED_KEY','disabled'],['REVOKED_KEY','revoked']]) {
  const panel=keyPanel(reference), text=await panel.innerText();
  admissionResults.push(text.includes(reason)&&text.includes('Checking unavailable')&&await panel.getByRole('button',{name:'Check key',exact:true}).isDisabled());
 }
 const admissionVisible=admissionResults.every(Boolean);
 const selected=keyPanel('opencode-zen · ONE');
 const rows=selected.locator('tbody tr');
 const untestedCliBefore=await rows.filter({hasText:'zencli'}).allInnerTexts();
 const directHistoryKeepsCliUntested=untestedCliBefore.length===2&&untestedCliBefore.every(t=>t.includes('unknown')&&t.includes('Not checked')&&!t.includes('cooldown')&&!t.includes('Retry'));
 await reviewAccounts(review.after);
 const cliRows=keyPanel('opencode-zen · ONE').locator('tbody tr').filter({hasText:'zencli'});
 const limitedText=await cliRows.filter({has:page.getByText('a',{exact:true})}).innerText();
 const inheritedText=await cliRows.filter({hasText:'unchecked-sibling'}).innerText();
 const ownVersusApplicableCooldown=limitedText.includes('Last observation: rate limited')&&!limitedText.includes('Not checked')&&inheritedText.includes('No observation yet')&&inheritedText.includes('Not checked')&&inheritedText.includes('same credential / endpoint / protocol');
 await reviewAccounts(review.prior_cli);
 const priorText=await keyPanel('opencode-zen · ONE').locator('tbody tr').filter({hasText:'zencli'}).filter({hasText:'unchecked-sibling'}).innerText();
 const priorCliPolicyAttributed=priorText.includes('Inherited prior CLI endpoint cooldown')&&priorText.includes('http://127.0.0.1:8099/v1')&&priorText.includes('No observation yet');
 const admissionNoOverflow=await page.evaluate(()=>document.body.scrollWidth<=innerWidth);
 const output={commit,priorCliPolicyAttributed,admissionVisible,directHistoryKeepsCliUntested,ownVersusApplicableCooldown,admissionNoOverflow,policyActionsHidden,legacyCooldownVisible,modelCount,uncheckedStatus,bridgeExportUnavailable,aaAttribution,autoExpired,discoveryFailureVisible,warningNoOverflow,injectionElements,scriptExecuted:await page.evaluate(()=>!!window.__xss),credentialActionReceivedSyntheticValue:credentialVisible.includes('synthetic-provider-secret'),credentialCleared:cleared,filteredCount,overflow,pageErrors:errors,networkPaths:[...new Set(calls)]};
 fs.writeFileSync(out+'/result.json',JSON.stringify(output,null,2));console.log(JSON.stringify(output,null,2));
 if(!priorCliPolicyAttributed || !admissionVisible || !directHistoryKeepsCliUntested || !ownVersusApplicableCooldown || !admissionNoOverflow || !policyActionsHidden || !legacyCooldownVisible || !discoveryFailureVisible || !warningNoOverflow || modelCount!==26 || uncheckedStatus!=='unknown' || !bridgeExportUnavailable || !aaAttribution || !autoExpired || injectionElements!==0 || output.scriptExecuted || !output.credentialActionReceivedSyntheticValue || !cleared || filteredCount!==1 || overflow.body>overflow.viewport || errors.length)throw Error('Browser acceptance failed; inspect result.json');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
