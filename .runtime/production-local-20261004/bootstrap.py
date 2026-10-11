from datetime import datetime, timezone
import io,json,os
from pathlib import Path
import psycopg
from rick_identity.passwords import hash_password
from rick_identity.postgres import PostgresUserStore
from rick_storage.s3_object_store import AwsCredentials, _sign_request
from services.object_store_transport import StdlibS3HttpTransport
from urllib.request import Request,urlopen
from urllib.error import HTTPError
secret=json.loads(Path('/run/local-test/secrets.json').read_text())
def connect(): return psycopg.connect(os.environ['RICK_EXTERNAL_DATABASE_DSN'],connect_timeout=5)
with connect() as c:
 with c.cursor() as cur:
  cur.execute("INSERT INTO rick_tenants (tenant_id,display_name) VALUES (%s,%s),(%s,%s) ON CONFLICT DO NOTHING",('default','RICK — teste local','local-other','Organização isolada de teste'))
store=PostgresUserStore(connect)
for user_id,email,tenant,role,grants in [('local-admin',secret['admin_email'],'default','PLATFORM_ADMIN',['*']),('local-other-admin','other@rick.local','local-other','PLATFORM_ADMIN',['*'])]:
 store.save({'user_id':user_id,'email':email,'tenant_id':tenant,'workspace_id':'default','role':role,'status':'active','authorized_collection_ids':grants,'permission_overrides':{'add':[],'remove':[]},'password_hash':hash_password(secret['admin_password']),'password_version':1,'role_version':1})
with connect() as c:
 with c.cursor() as cur:
  cur.execute("INSERT INTO rick_collections (tenant_id,workspace_id,collection_id,title,description,created_by) VALUES (%s,%s,%s,%s,%s,%s),(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",('default','default','local-knowledge','Conhecimento — teste local','Documentos sintéticos para testar o programa.','local-admin','local-other','default','other-knowledge','Organização isolada','Documento de teste de isolamento.','local-other-admin'))
url=os.environ['RICK_OBJECT_STORE_ENDPOINT']+'/'+os.environ['RICK_OBJECT_STORE_BUCKET']
headers=_sign_request(method='PUT',url=url,headers={},body=b'',credentials=AwsCredentials(os.environ['RICK_OBJECT_STORE_ACCESS_KEY_ID'],os.environ['RICK_OBJECT_STORE_SECRET_ACCESS_KEY']),region='us-east-1',service='s3',clock=lambda:datetime.now(timezone.utc))
try:
 with urlopen(Request(url,data=b'',headers=headers,method='PUT'),timeout=10) as r:
  assert r.status==200
except HTTPError as error:
 assert error.code==409
 assert b'BucketAlreadyOwnedByYou' in error.read(4096)
# Exercise native PDF rendering and parsing on the final Alpine runtime.
import pypdfium2 as pdfium
import pdfplumber
buffer=io.BytesIO()
with pdfium.PdfDocument.new() as generated:
 page=generated.new_page(595,842)
 page.close()
 generated.save(buffer)
payload=buffer.getvalue()
with pdfium.PdfDocument(payload) as doc:
 assert len(doc)==1
 page=doc[0]
 try:
  rendered=page.render(scale=.25)
  try:
   assert rendered.width>0 and rendered.height>0
  finally: rendered.close()
 finally: page.close()
with pdfplumber.open(io.BytesIO(payload)) as doc: assert len(doc.pages)==1
print(json.dumps({'seeded_internal_postgres_accounts':2,'seeded_isolated_tenants':2,'bucket_ready':True,'native_pdf_render_parse':'PASS','billable_vendor_calls':0}))
