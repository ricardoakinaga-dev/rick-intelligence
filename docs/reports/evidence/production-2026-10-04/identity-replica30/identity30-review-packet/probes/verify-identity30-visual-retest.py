"""Pure data gate for a separate fixture and settled browser retest, never full HTTP replay."""
from pathlib import Path
import copy,hashlib,json,struct,sys

def verify(h,b,binding,builds,captures,command,script):
 checks=[]
 def need(name,ok):
  assert ok,name
  checks.append(name)
 need('separate_preparation_only',h['status']=='BROWSER_FIXTURE_READY' and h['http_matrix_repeated'] is False and len(h['checks'])==4)
 for x in h['checks']:need('preparation_'+x['name'],x['passed'] and x['status_code'] in x['expected_status'])
 fixture=next(x['body']['user'] for x in h['checks'] if x['name']=='create_role_fixture')
 need('browser_complete',b['status']=='PASS' and len(b['checks'])==86 and len(b['captures'])==7 and b['mockedRoutes']==0 and not b['errors'] and b['cleanup']['overrides_restored'])
 bn={x['id']:x for x in b['checks']};need('unique_browser_checks',len(bn)==len(b['checks']))
 for x in b['checks']:need('browser_'+x['id'],x['status']=='PASS')
 for n,s in [('before_documents',200),('active_after_revoke_documents_401',401),('fresh_denied_documents',403),('old_denied_after_restore_documents_401',401),('fresh_restored_documents',200)]:
  row=bn[n];need('public_'+n,row['status_code']==s and row['method']=='GET' and row['path']=='/api/v1/documents');need('raw_public_'+n,any(x['method']=='GET' and x['path']=='/api/v1/documents' and x['status_code']==s and x['timestamp']==row['timestamp'] for x in b['http']))
 for x in b['captures']:
  file=x['filename'];p=captures/file;need('safe_capture_name_'+file,Path(file).name==file and p.is_file());raw=p.read_bytes();need('capture_hash_'+file,hashlib.sha256(raw).hexdigest()==x['sha256']);need('PNG_signature_'+file,raw[:8]==b'\x89PNG\r\n\x1a\n');w,height=struct.unpack('>II',raw[16:24]);g=x['geometry'];need('geometry_'+file,w==g['viewport_width']==g['png_width']==g['document_client_width'] and height==g['png_height']==g['document_scroll_height'] and g['document_scroll_width']<=w and g['body_scroll_width']<=w)
  s=bn[file[:-4]+'_settled_capture']['settlement'];need('settled_'+file,s['scrollX']==s['scrollY']==s['finite_running_animations']==0);need('hidden_rail_'+file,not s['declared_hidden_rail'] or s['rail_right']<=0)
 wanted={x['service']:x['image_id'] for x in builds};need('same_commit',len({h['source_commit'],binding['source_commit'],b['candidate_version'],command['source_commit'],*[x['candidate_commit'] for x in builds]})==1)
 need('actual_eight_services',len(binding['actual_services'])==8 and all(x['running'] and x['owner']==h['owner']==binding['owner']==command['owner'] for x in binding['actual_services'].values()))
 for name in ['api','api-peer','worker','web']:need('image_'+name,binding['actual_services'][name]['image_id']==wanted['api' if name=='api-peer' else name] and binding['actual_services'][name]['user']=='10001:10001')
 need('both_api_restored',len(binding['fixture_restored_on_both_apis'])==2 and {x['api'] for x in binding['fixture_restored_on_both_apis']}=={'api_a','api_b'})
 for x in binding['fixture_restored_on_both_apis']:
  u=x['user'];need('fixture_'+x['api'],x['status_code']==200 and u['user_id']==fixture['user_id'] and u['email']==fixture['email'] and u['role']=='KNOWLEDGE_MANAGER' and u['permission_overrides']=={'add':[],'remove':[]} and u['authorized_collection_ids']==['local-knowledge'])
 need('executed_script',command['exit_code']==0 and not command['actual_config_contents_exported'] and command['script_sha256']==hashlib.sha256(script.read_bytes()).hexdigest())
 need('limits',h['production_approved'] is False and h['billable_vendor_calls']==h['mocked_routes']==0)
 return checks

def main():
 root,buildfile,script,output=map(Path,sys.argv[1:]);paths=[root/'result.json',root/'browser/result.json',root/'actual-runtime-binding.json',buildfile,root/'browser-command.json'];h,b,binding,builds,cmd=[json.loads(p.read_text()) for p in paths];data=[h,b,binding,builds,root/'browser',cmd,script];checks=verify(*data);controls=[]
 for case in ['transition_still_running','hidden_mobile_rail_visible','missing_403','foreign_fixture','wrong_peer_image']:
  d=copy.deepcopy(data)
  if case in ('transition_still_running','hidden_mobile_rail_visible'):
   s=next(x for x in d[1]['checks'] if x['id']=='denied-375_settled_capture')['settlement'];s['finite_running_animations']=1 if case=='transition_still_running' else 0;s['rail_right']=20 if case=='hidden_mobile_rail_visible' else 0
  elif case=='missing_403':next(x for x in d[1]['checks'] if x['id']=='fresh_denied_documents')['status_code']=200
  elif case=='foreign_fixture':d[2]['fixture_restored_on_both_apis'][0]['user']['user_id']='foreign-fixture'
  else:d[2]['actual_services']['api-peer']['image_id']='sha256:foreign'
  try:verify(*d)
  except (AssertionError,KeyError,StopIteration):controls.append({'case':case,'status':'REJECTED_KNOWN_BAD'})
  else:raise AssertionError('accepted known bad '+case)
 report={'status':'PASS','checks':len(checks),'checks_detail':checks,'known_bad_controls':controls,'input_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths+[script]},'source_commit':h['source_commit'],'production_approved':False,'limits':'Separate fixture browser-only retest; pure-data recomputation of recorded live observations, not independent live execution or whole HTTP replay.'}
 output.write_text(json.dumps(report,indent=2)+'\n');print(len(checks),'semantic assertions PASS; five known bad rejected')
if __name__=='__main__':main()
