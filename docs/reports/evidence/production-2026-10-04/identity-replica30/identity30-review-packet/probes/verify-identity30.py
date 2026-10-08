"""Pure-data semantic gate; no credentials, network, imports of app or mutation."""
import ast,copy,hashlib,json,sys
from pathlib import Path

def verify(http,browser,binding,builds,policy):
 checks=[]
 def require(name,value):
  assert value,name
  checks.append(name)
 rows=http['checks'];named={x['name']:x for x in rows};require('unique_http_names',len(named)==len(rows));require('http_complete',http['status']=='HTTP_PASS_AWAIT_BROWSER' and len(rows)==176)
 for x in rows:
  require('http_'+x['name'],x['passed'] is True and x['status_code'] in x['expected_status'])
  if x['status_code'] in (400,401,403,409):require('error_'+x['name'],x['body']['error']['code']=={400:'validation_error',401:'unauthorized',403:'forbidden',409:'conflict'}[x['status_code']])
 definitions=ast.parse(policy);roles=next(ast.literal_eval(n.value) for n in definitions.body if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id=='ROLE_PERMISSIONS')
 role=named['create_role_fixture']['body']['user'];cred=named['create_credential_fixture']['body']['user'];require('two_distinct_synthetic_fixture_ids',role['user_id']!=cred['user_id'] and role['email'].startswith('roles-rick-identity30-') and cred['email'].startswith('credentials-rick-identity30-'))
 for x in rows:
  body=x['body']
  if body.get('authenticated') is not True:continue
  require('scope_'+x['name'],body['workspace_id']=='default')
  if body.get('email')==role['email']:
   expected_role='VETERINARIAN' if x['name'].startswith('downgrade_fresh') else 'KNOWLEDGE_MANAGER';perms=set(roles[expected_role])
   if x['name'].startswith(('remove_fresh','removed_permissions')):perms.remove('documents.read')
   require('role_snapshot_'+x['name'],body['user_id']==role['user_id'] and body['tenant_id']=='default' and body['canonical_role']==expected_role and set(body['permissions'])==perms)
  elif body.get('email')==cred['email']:
   require('credential_snapshot_'+x['name'],body['user_id']==cred['user_id'] and body['tenant_id']=='default' and body['canonical_role']=='VETERINARIAN' and set(body['permissions'])==set(roles['VETERINARIAN']))
  elif x['name'].startswith(('admin_','last_admin_preserved')):
   require('admin_snapshot_'+x['name'],body['canonical_role']=='PLATFORM_ADMIN' and body['tenant_id']=='default' and body['permissions']==['*'])
 for phase,field,value in [('downgrade_role','role','VETERINARIAN'),('promote_role','role','KNOWLEDGE_MANAGER'),('remove_document_permission','permission_overrides',{'add':[],'remove':['documents.read']}),('restore_document_permission','permission_overrides',{'add':[],'remove':[]}),('remove_collection_grant','authorized_collection_ids',[]),('restore_collection_grant','authorized_collection_ids',['local-knowledge'])]:
  u=named[phase]['body']['user'];require('mutation_'+phase,u['user_id']==role['user_id'] and u['email']==role['email'] and u[field]==value)
 for i in (0,1):
  body=named['removed_collection_implicit_empty_'+str(i)]['body'];require('empty_scope_'+str(i),body['items']==[] and body['total']==0)
 for name in ['admin_reset_password','recovery_consume_peer_after_restart','deactivate_fixture']:require('revoke_count_'+name,named[name]['body']['revoked_sessions']>=2)
 require('neutral_recovery',all(named[n]['body']=={'status':'queued'} for n in ['recovery_issue_A','recovery_unknown_neutral','recovery_wrongtenant_neutral']))
 require('concurrent_single_winner',sorted(named['concurrent_confirm_'+str(i)]['status_code'] for i in (0,1))==[200,400]);require('concurrent_release',0<=http['concurrent_release_gap_seconds']<.1)
 for row in http['rate_limit_observations']:require('natural_ratewait_'+row['name'],row['status_code']==429 and 0<row['retry_after_seconds']<=75)
 require('browser_complete',browser['status']=='PASS' and len(browser['checks'])==72 and len(browser['captures'])==7 and browser['mockedRoutes']==0 and not browser['errors'] and browser['cleanup']['overrides_restored'])
 for x in browser['checks']:require('browser_'+x['id'],x['status']=='PASS')
 bn={x['id']:x for x in browser['checks']}
 for n,s in [('before_documents',200),('active_after_revoke_documents_401',401),('fresh_denied_documents',403),('old_denied_after_restore_documents_401',401),('fresh_restored_documents',200)]:require('browser_public_'+n,bn[n]['status_code']==s and bn[n]['method']=='GET' and bn[n]['path']=='/api/v1/documents')
 require('browser_no_private_dom',all(bn[n]['status']=='PASS' for n in ['active_after_revoke_no_private_dom','fresh_denied_no_private_dom','denied_375_no_private_dom','denied_768_no_private_dom','denied_1440_no_private_dom','old_denied_after_restore_no_private_dom']))
 wanted={x['service']:x['image_id'] for x in builds};require('same_commit',len({http['source_commit'],binding['source_commit'],browser['candidate_version'],*[x['candidate_commit'] for x in builds]})==1)
 require('eight_owned_running_services',len(binding['actual_services'])==8 and all(x['running'] and x['owner']==http['owner']==binding['owner'] for x in binding['actual_services'].values()))
 for name in ['api','api-peer','worker','web']:require('actual_image_'+name,binding['actual_services'][name]['image_id']==wanted['api' if name=='api-peer' else name] and binding['actual_services'][name]['user']=='10001:10001')
 for x in binding['fixture_restored_on_both_apis']:require('restored_fixture_'+x['api'],x['user']['user_id']==role['user_id'] and x['user']['role']=='KNOWLEDGE_MANAGER' and x['user']['authorized_collection_ids']==['local-knowledge'] and x['user']['permission_overrides']=={'add':[],'remove':[]})
 require('limits_preserved',http['production_approved'] is False and http['billable_vendor_calls']==0 and http['mocked_routes']==0)
 return checks

def main():
 assert len(sys.argv)==7,'expected fiveinputfiles andoutputpath'
 paths=[Path(x) for x in sys.argv[1:6]];data=[json.loads(p.read_text()) for p in paths[:4]]+[paths[4].read_text()];checks=verify(*data);mutations=[]
 for label in ['wrong_identity','widened_removed_permission','double_token_winner','missing_browser_revocation','wrong_peer_image']:
  altered=copy.deepcopy(data)
  if label=='wrong_identity':next(x for x in altered[0]['checks'] if x['name']=='initial_role_login_A')['body']['user_id']='foreign-fixture'
  elif label=='widened_removed_permission':next(x for x in altered[0]['checks'] if x['name']=='removed_permissions_0')['body']['permissions'].append('documents.read')
  elif label=='double_token_winner':
   for x in altered[0]['checks']:
    if x['name'].startswith('concurrent_confirm_'):x.update(status_code=200,expected_status=[200]);x['body']={'status':'reset','revoked_sessions':2}
  elif label=='missing_browser_revocation':next(x for x in altered[1]['checks'] if x['id']=='active_after_revoke_documents_401')['status_code']=200
  else:altered[2]['actual_services']['api-peer']['image_id']='sha256:foreign'
  try:verify(*altered)
  except (AssertionError,KeyError,StopIteration):mutations.append({'case':label,'status':'REJECTED_KNOWN_BAD'})
  else:raise AssertionError('gate acceptedknownbad '+label)
 out={'status':'PASS','checks':len(checks),'checks_detail':checks,'known_bad_controls':mutations,'input_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},'source_commit':data[0]['source_commit'],'production_approved':False,'limits':'Pure data recomputation of captured live responses/DOM observations plus fiveknownbad controls; not independent live execution/security approval'}
 Path(sys.argv[6]).write_text(json.dumps(out,indent=2)+'\n');print(len(checks),'semantic assertions PASS;5knownbad rejected')
if __name__=='__main__':main()
