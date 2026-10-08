"""I1 bounded pure-data recomputation. No app imports, network or child processes."""
import ast, copy, hashlib, json, stat, struct, zlib
from datetime import datetime
from pathlib import Path
P=Path('/tmp/rick-production-20261004/identity30-review-packet')
O=Path('/tmp/rick-production-20261004/identity30-review-output')
checks=[]
def need(label, ok):
    if not ok: raise AssertionError(label)
    checks.append(label)
def read(f): return json.loads((P/f).read_text())
def sha(raw): return hashlib.sha256(raw).hexdigest()
def stamp(s): return datetime.fromisoformat(s.replace('Z','+00:00'))
manifest=read('manifest.json')['files']; contract=read('review-contract.json'); commit=contract['candidate_commit']
actual={str(p.relative_to(P)) for p in P.rglob('*') if p.is_file()}
need('manifest_inventory',actual==set(manifest)|{'manifest.json'})
for f,m in manifest.items():
    p=P/f; need('no_symlink:'+f,not p.is_symlink()); raw=p.read_bytes()
    need('manifest_hash:'+f,sha(raw)==m['sha256'])
    need('manifest_size:'+f,len(raw)==m['size'])
    need('manifest_mode:'+f,format(stat.S_IMODE(p.stat().st_mode),'04o')==m['mode'])
for f,m in contract['source_files'].items():
    raw=(P/'source'/f).read_bytes()
    need('contract_source:'+f,sha(raw)==m['sha256'] and len(raw)==m['size'])
need('source_inventory',{'source/'+f for f in contract['source_files']}=={f for f in manifest if f.startswith('source/')})
builds=read('inputs/build-results.json'); wanted={x['service']:x['image_id'] for x in builds}
for x in builds:
    need('build_revision:'+x['service'],x['exit_code']==0 and x['candidate_commit']==commit==x['labels']['org.opencontainers.image.revision'] and 'org.opencontainers.image.revision='+commit in x['argv'])
policy=ast.parse((P/'source/packages/authorization/src/rick_authorization/policy.py').read_text())
roles=next(ast.literal_eval(n.value) for n in policy.body if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id=='ROLE_PERMISSIONS')
runs={r:{'h':read(f'evidence/{r}/result.json'),'b':read(f'evidence/{r}/browser/result.json'),'binding':read(f'evidence/{r}/actual-runtime-binding.json'),'command':read(f'evidence/{r}/browser-command.json'),'teardown':read(f'evidence/{r}/teardown-and-original-health.json')} for r in ['run1','run2']}
# Fixed semantic expectations, independent of captured passed/expected_status flags.
def semantic(r,d):
    h,b,bind,cmd,t=(d[k] for k in ['h','b','binding','command','teardown'])
    rows={x['name']:x for x in h['checks']}; bn={x['id']:x for x in b['checks']}
    need(r+':unique_http',len(rows)==len(h['checks']))
    need(r+':unique_browser',len(bn)==len(b['checks']))
    fixture=rows['create_role_fixture']['body']['user']
    need(r+':fixture_owner',fixture['email']=='roles-'+h['owner']+'@example.invalid')
    need(r+':record_bindings',h['source_commit']==bind['source_commit']==cmd['source_commit']==b['candidate_version']==t['source_commit']==commit and h['owner']==bind['owner']==cmd['owner']==t['owner'])
    need(r+':image_report',h['images']==wanted)
    expected_names={'postgres','redis','qdrant','object-store','api','api-peer','worker','web'}
    need(r+':owned_services',set(bind['actual_services'])==expected_names)
    need(r+':unique_owned_ids',len({x['container_id'] for x in bind['actual_services'].values()})==8)
    for n,v in bind['actual_services'].items():
        need(r+':owned:'+n,v['owner']==h['owner'] and v['running'] is True)
        if n in ['api','api-peer','worker','web']:
            need(r+':image:'+n,v['image_id']==wanted['api' if n=='api-peer' else n] and v['user']=='10001:10001')
    need(r+':both_restored',len(bind['fixture_restored_on_both_apis'])==2 and {x['api'] for x in bind['fixture_restored_on_both_apis']}=={'api_a','api_b'})
    for x in bind['fixture_restored_on_both_apis']:
        u=x['user'];need(r+':restored:'+x['api'],x['status_code']==200 and u['user_id']==fixture['user_id'] and u['email']==fixture['email'] and u['tenant_id']==u['workspace_id']=='default' and u['role']=='KNOWLEDGE_MANAGER' and u['status']==u['membership_status']=='active' and u['authorized_collection_ids']==['local-knowledge'] and u['permission_overrides']=={'add':[],'remove':[]})
    script='probes/browser-before-settlement.cjs' if r=='run1' else 'probes/identity30-browser.cjs'
    need(r+':executed_script',cmd['script_sha256']==sha((P/script).read_bytes()) and cmd['exit_code']==0 and cmd['actual_config_contents_exported'] is False)
    need(r+':sanitized_argv',len(cmd['argv'])==3 and cmd['argv'][1]=='/tmp/rick-production-20261004/identity30-browser.cjs' and cmd['argv'][2]=='<private owned-clone config>')
    need(r+':command_log',(P/f'evidence/{r}/browser-command.log').read_text()=='IDENTITY30_PASS\n')
    need(r+':command_timeline',stamp(cmd['start'])<=stamp(b['started_at'])<=stamp(b['finished_at'])<=stamp(cmd['end'])<stamp(bind['recorded_at'])<stamp(t['start'])<=stamp(t['end']))
    stages=[('before_documents',200,'before'),('active_after_revoke_documents_401',401,'before'),('fresh_denied_documents',403,'fresh_denied'),('old_denied_after_restore_documents_401',401,'fresh_denied'),('fresh_restored_documents',200,'fresh_restored')]
    last=stamp(b['started_at'])
    for n,s,context in stages:
        x=bn[n];need(r+':status:'+n,x['method']=='GET' and x['path']=='/api/v1/documents' and x['status_code']==s)
        need(r+':action_order:'+n,last<=stamp(x['action_at'])<=stamp(x['request_at'])<=stamp(x['timestamp']))
        raw=[e for e in b['http'] if e['context']==context and e['method']==x['method'] and e['path']==x['path'] and e['status_code']==s and abs((stamp(e['timestamp'])-stamp(x['timestamp'])).total_seconds())<=.01]
        need(r+':raw_match:'+n,len(raw)==1)
        completed=bn[n+'_completed'];need(r+':completed:'+n,completed['status_code']==s and stamp(completed['timestamp'])>=stamp(x['timestamp']))
        last=stamp(x['timestamp'])
    for n in ['peer_remove_documents_read','peer_restore_documents_read','finally_restore_overrides_1']:
        x=bn[n];need(r+':browser_patch:'+n,x['method']=='PATCH' and x['path']=='/api/v1/admin/users/'+fixture['user_id'] and x['status_code'] in [200,202])
    need(r+':remove_before_denial',stamp(bn['before_documents']['timestamp'])<stamp(bn['peer_remove_documents_read']['timestamp'])<stamp(bn['active_after_revoke_documents_401']['action_at']))
    need(r+':restore_before_old_denial',stamp(bn['fresh_denied_documents']['timestamp'])<stamp(bn['peer_restore_documents_read']['timestamp'])<stamp(bn['old_denied_after_restore_documents_401']['action_at']))
    for n in ['active_after_revoke','fresh_denied','denied_375','denied_768','denied_1440','old_denied_after_restore']:
        need(r+':safe_dom:'+n,bn[n+'_safe_denial']['status']=='PASS' and bn[n+'_no_private_dom']['status']=='PASS')
    if r=='run2':
        need('run2:preparation_only',h['http_matrix_repeated'] is False and set(rows)=={'admin_A','admin_B','create_role_fixture','grant_local_collection'})
        for c in b['captures']:
            s=bn[c['filename'][:-4]+'_settled_capture']['settlement']
            need('run2:settled:'+c['filename'],s['scrollX']==s['scrollY']==s['finite_running_animations']==0 and (not s['declared_hidden_rail'] or s['rail_right']<=0))
    else:
        cred=rows['create_credential_fixture']['body']['user']
        need('run1:distinct_credential_fixture',cred['user_id']!=fixture['user_id'] and cred['email']=='credentials-'+h['owner']+'@example.invalid')
        for x in h['checks']:
            body=x['body'];n=x['name']
            if body.get('authenticated') is True and body.get('email') in [fixture['email'],cred['email']]:
                u=fixture if body['email']==fixture['email'] else cred
                role='VETERINARIAN' if u==cred or n.startswith('downgrade_fresh') else 'KNOWLEDGE_MANAGER'
                perms=set(roles[role]);perms-= {'documents.read'} if n.startswith(('remove_fresh','removed_permissions')) else set()
                need('run1:identity:'+n,body['user_id']==u['user_id'] and body['tenant_id']==body['workspace_id']=='default' and body['canonical_role']==role and set(body['permissions'])==perms)
        phases=['downgrade_old','promotion_old','remove_old','restore_old_cannot_widen','collection_old','collection_restore_old','admin_reset_old_sessions','recovery_old_sessions','concurrent_recovery_old_sessions','deactivate_old_sessions']
        for phase in phases:
            for i in [0,1]:
                for j in [0,1]:
                    for suffix,path in [('me','/api/v1/auth/me'),('documents','/api/v1/documents')]:
                        n=f'{phase}_cookie{i}_api{j}_{suffix}';x=rows[n]
                        need('run1:fixed_revocation:'+n,x['status_code']==401 and x['method']=='GET' and x['path']==path and x['body']['error']['code']=='unauthorized' and 'items' not in x['body'])
        fixed={'foreign_target_update_denied':403,'last_admin_downgrade_guard':409,'last_admin_deactivate_guard':409,'recovery_replay_origin_denied':400}
        for i in [0,1]:
            for prefix in ['downgrade_fresh_documents','downgrade_no_admin','removed_document_denied','removed_collection_explicit_denied']:fixed[prefix+'_'+str(i)]=403
            for prefix in ['admin_reset_old_password','recovery_old_password','concurrent_loser_password','disabled_login_denied']:fixed[prefix+'_'+str(i)]=401
            for prefix in ['initial_documents','session_survives_api_restart','concurrent_winner_password','last_admin_preserved']:fixed[prefix+'_'+str(i)]=200
        for n,s in fixed.items():need('run1:fixed_status:'+n,rows[n]['status_code']==s)
        for i in [0,1]:
            need('run1:published_initial:'+str(i),any(x['title']=='teste-local.md' and x['status']=='published' and x['collection_id']=='local-knowledge' for x in rows['initial_documents_'+str(i)]['body']['items']))
            body=rows['removed_collection_implicit_empty_'+str(i)]['body'];need('run1:empty_scope:'+str(i),body['items']==[] and body['total']==0)
        foreign=json.dumps(rows['foreign_fixture_not_visible']['body']);need('run1:foreign_hidden',fixture['email'] not in foreign and cred['email'] not in foreign)
        need('run1:neutral_recovery',all(rows[n]['body']=={'status':'queued'} for n in ['recovery_issue_A','recovery_unknown_neutral','recovery_wrongtenant_neutral']))
        need('run1:single_winner',sorted(rows['concurrent_confirm_'+str(i)]['status_code'] for i in [0,1])==[200,400])
        need('run1:dispatch_gap',0<=h['concurrent_release_gap_seconds']<.1)
        for n in ['admin_reset_password','recovery_consume_peer_after_restart','deactivate_fixture']:need('run1:revoke_count:'+n,rows[n]['body']['revoked_sessions']>=2)
        events={x['body']['audit_event_id'] for x in h['checks'] if x['body'].get('audit_event_id')}
        need('run1:ten_audit_events',len(events)==10)
        for e in events:
            a,d=rows['audit_A_'+e],rows['audit_peer_'+e]
            need('run1:audit_consistency:'+e,a['status_code']==d['status_code']==200 and a['body']==d['body'] and a['body']['event_id']==e and a['body']['status']=='published')
        for x in h['rate_limit_observations']:
            need('run1:natural_wait:'+x['name'],x['status_code']==429 and 0<x['retry_after_seconds']<=75 and (stamp(rows[x['name']]['at'])-stamp(x['at'])).total_seconds()>=x['retry_after_seconds'])
    need(r+':teardown_owner_counts',t['owned_containers_removed']==8 and t['owned_volumes_removed']==4 and t['owned_networks_removed'] is True)
    need(r+':original_seven',set(t['original_services'])==expected_names-{'api-peer'} and len({x['container_id'] for x in t['original_services'].values()})==7)
    for n,v in t['original_services'].items():
        need(r+':original_running:'+n,v['running'] is True and v['container_id'] not in {x['container_id'] for x in bind['actual_services'].values()})
        if n in ['api','web','worker','postgres']:need(r+':original_health:'+n,v['health']=='healthy')
        if n in wanted:need(r+':original_image:'+n,v['image_id']==wanted[n])
    need(r+':recorded_original_endpoints',len(t['endpoints'])==3 and all(s==200 for s in t['endpoints'].values()))
for r,d in runs.items():semantic(r,d)
need('two_distinct_owners',runs['run1']['h']['owner']!=runs['run2']['h']['owner'])
need('two_distinct_role_fixtures',runs['run1']['binding']['fixture_restored_on_both_apis'][0]['user']['user_id']!=runs['run2']['binding']['fixture_restored_on_both_apis'][0]['user']['user_id'])
need('clone_graphs_disjoint',not {x['container_id'] for x in runs['run1']['binding']['actual_services'].values()} & {x['container_id'] for x in runs['run2']['binding']['actual_services'].values()})
need('original_graph_identical',runs['run1']['teardown']['original_services']==runs['run2']['teardown']['original_services'])
correction=read('evidence/visual-settlement-failure.json')
need('visual_script_before',correction['before_script_sha256']==sha((P/'probes/browser-before-settlement.cjs').read_bytes()))
need('visual_script_after',correction['after_script_sha256']==sha((P/'probes/identity30-browser.cjs').read_bytes()))
# Verify actual PNG containers, all chunk CRCs and image data size, not JSON dimensions alone.
pngs=[]
for r,d in runs.items():
    for c in d['b']['captures']:
        f=c['filename'];need(r+':png_safe_name:'+f,Path(f).name==f)
        raw=(P/f'evidence/{r}/browser'/f).read_bytes();need(r+':png_hash:'+f,sha(raw)==c['sha256'])
        need(r+':png_signature:'+f,raw[:8]==b'\x89PNG\r\n\x1a\n')
        pos=8;chunks=[];idat=b'';ihdr=None
        while pos<len(raw):
            size=struct.unpack('>I',raw[pos:pos+4])[0];kind=raw[pos+4:pos+8];data=raw[pos+8:pos+8+size];crc=struct.unpack('>I',raw[pos+8+size:pos+12+size])[0]
            need(r+':png_crc:'+f+':'+str(pos),zlib.crc32(kind+data)&0xffffffff==crc)
            chunks.append(kind);pos+=12+size
            if kind==b'IHDR':ihdr=struct.unpack('>IIBBBBB',data)
            if kind==b'IDAT':idat+=data
        w,h,depth,color,compression,filtering,interlace=ihdr;g=c['geometry']
        need(r+':png_structure:'+f,chunks[0]==b'IHDR' and chunks[-1]==b'IEND' and pos==len(raw) and depth==8 and color in [2,6] and compression==filtering==interlace==0)
        pixels=zlib.decompress(idat);stride=w*({2:3,6:4}[color])+1
        need(r+':png_data:'+f,len(pixels)==h*stride and all(pixels[y*stride]<=4 for y in range(h)))
        need(r+':png_geometry:'+f,w==g['png_width']==g['viewport_width']==g['document_client_width'] and h==g['png_height']==g['document_scroll_height'] and g['document_scroll_width']<=w and g['body_scroll_width']<=w)
        pngs.append({'run':r,'filename':f,'sha256':sha(raw),'width':w,'height':h,'all_chunk_crcs_valid':True,'decoded_data_size_valid':True})
# No acquisition of secret values: check prohibited public fields in supplied JSON only.
prohibited={'password_hash','password_plain','password','new_password','csrf_token','session_token','token'}
def redacted(v,loc):
    if isinstance(v,dict):
        need('public_keys:'+loc,not prohibited & set(v))
        for k,x in v.items():redacted(x,loc+'/'+k)
    elif isinstance(v,list):
        for i,x in enumerate(v):redacted(x,loc+'/'+str(i))
for r,d in runs.items():
    for x in d['h']['checks']:redacted(x['body'],r+'/'+x['name'])
# I1-authored rejectable controls, using fixed expectations above.
controls=[]
for case in ['missing_401_cartesian_cell','false_expected_status_200','foreign_browser_patch','foreign_restored_email','foreign_command_owner','missing_raw_browser_response','audit_not_published','double_reset_winner','visible_hidden_rail','old_password_accepted']:
    d=copy.deepcopy(runs);target=d['run1']
    if case=='missing_401_cartesian_cell':target['h']['checks']=[x for x in target['h']['checks'] if x['name']!='downgrade_old_cookie1_api1_documents']
    elif case=='false_expected_status_200':next(x for x in target['h']['checks'] if x['name']=='downgrade_old_cookie1_api1_documents').update(status_code=200,expected_status=[200],passed=True)
    elif case=='foreign_browser_patch':next(x for x in target['b']['checks'] if x['id']=='peer_remove_documents_read')['path']='/api/v1/admin/users/foreign'
    elif case=='foreign_restored_email':target['binding']['fixture_restored_on_both_apis'][0]['user']['email']='foreign@example.invalid'
    elif case=='foreign_command_owner':target['command']['owner']='rick-identity30-foreign'
    elif case=='missing_raw_browser_response':target['b']['http']=[x for x in target['b']['http'] if not (x['context']=='before' and x['path']=='/api/v1/documents' and x['status_code']==401)]
    elif case=='audit_not_published':next(x for x in target['h']['checks'] if x['name'].startswith('audit_A_'))['body']['status']='pending'
    elif case=='double_reset_winner':
        for x in target['h']['checks']:
            if x['name'].startswith('concurrent_confirm_'):x.update(status_code=200,expected_status=[200],passed=True)
    elif case=='visible_hidden_rail':next(x for x in d['run2']['b']['checks'] if x['id']=='denied-375_settled_capture')['settlement']['rail_right']=10
    else:next(x for x in target['h']['checks'] if x['name']=='admin_reset_old_password_0').update(status_code=200,expected_status=[200],passed=True)
    count=len(checks)
    try:
        for r,v in d.items():semantic(r,v)
    except (AssertionError,KeyError) as e:controls.append({'case':case,'status':'REJECTED_KNOWN_BAD','reason':str(e)})
    else:raise AssertionError('accepted_bad:'+case)
    finally:del checks[count:]
report={'status':'PASS','criterion':contract['criterion'],'candidate_commit':commit,'manifest_files_recomputed':len(manifest),'contract_sources_recomputed':len(contract['source_files']),'independent_data_assertions':len(checks),'checks':checks,'pngs':pngs,'known_bad_controls':controls,'runs':{r:{'owner':d['h']['owner'],'http_rows_recorded':len(d['h']['checks']),'browser_rows_recorded':len(d['b']['checks']),'fixture':next(x['body']['user'] for x in d['h']['checks'] if x['name']=='create_role_fixture')} for r,d in runs.items()},'limitations':['Recorded evidence only; zero live requests or application execution.','Config credential hashes, original initial baseline, delivery factory bytes and actual image layers excluded from packet; not independently recomputable.','PNG dimensions and container bytes independently recomputed; DOM sizes and observations remain recorded browser facts.','No browser response bodies or full DOM dumps are present.']}
(O/'independent-recomputed.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ['status','manifest_files_recomputed','contract_sources_recomputed','independent_data_assertions']}))
print('PNG containers checked:',len(pngs),'; I1 controls rejected:',len(controls))
