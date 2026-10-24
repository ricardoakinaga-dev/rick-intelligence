import { expect, test, type Page } from "@playwright/test";

// Real browser/components/transport; deliberately synthetic backend responses.
// These tests are not IdP, live PostgreSQL, ingestion-runtime or clinical proof.
const session = {authenticated:true,user_id:"aud15",email:"aud15@example.invalid",role:"KNOWLEDGE_MANAGER",canonical_role:"KNOWLEDGE_MANAGER",tenant_id:"t",workspace_id:"w",session_id:"s",permissions:["cases.read","cases.manage","cases.review","documents.read","documents.upload","documents.manage","ingestion.run","collections.read"]};
const record = (index:number) => ({contract_version:"clinical-case-contract-v1",clinical_scope_status:"record_review_feedback_only",case_id:`case-${index}`,tenant_id:"t",workspace_id:"w",owner_user_id:"aud15",title:`Case ${index}`,summary:"Human summary",record:"Human summary",hypotheses:[],evidence:[],agent_model:null,tags:[],status:"open",created_by_user_id:"aud15",created_at:1700000000,updated_by_user_id:"aud15",updated_at:1700000000,last_request_id:null,review_count:0,feedback_count:0,last_review_at:null,last_feedback_at:null});
async function identify(page:Page) {
 await page.route("**/api/v1/auth/me",route=>route.fulfill({json:session}));
 await page.route("**/health/ready",route=>route.fulfill({json:{status:"ready"}}));
}
async function caseEndpoints(page:Page) {
 await identify(page);
 await page.route("**/api/v1/cases/catalog/agents",route=>route.fulfill({json:{catalog_status:"configured",items:[]}}));
 await page.route("**/api/v1/cases/case-*",route=>route.fulfill({json:{case:record(Number(route.request().url().split("case-").at(-1))),reviews:[],feedback:[]}}));
}
test("51st case is reachable using the actual pagination transport",async({page})=>{
 await caseEndpoints(page);const offsets:number[]=[];
 await page.route("**/api/v1/cases?**",route=>{
  const offset=Number(new URL(route.request().url()).searchParams.get("offset"));offsets.push(offset);
  return route.fulfill({json:{items:offset===0?Array.from({length:50},(_,i)=>record(i+1)):[record(50),record(51)],total:51,next_offset:offset===0?50:null}});
 });
 await page.goto("/app/cases");await expect(page.getByRole("heading",{name:"Casos registrados"})).toBeVisible();
 await page.getByRole("button",{name:"Carregar mais casos",exact:true}).click();
 await expect(page.getByText("Case 51",{exact:true})).toBeVisible();
 expect(offsets).toContain(0);expect(offsets).toContain(50);await expect(page.getByRole("button",{name:"Carregar mais casos",exact:true})).toHaveCount(0);
});
test("draft B survives a delayed creation A and same-session focus revalidation",async({page})=>{
 await caseEndpoints(page);await page.route("**/api/v1/cases?**",route=>route.fulfill({json:{items:[],total:0,next_offset:null}}));
 let release:(()=>void)|undefined;
 await page.route("**/api/v1/cases",async route=>{await new Promise<void>(resolve=>{release=resolve;});await route.fulfill({status:201,json:record(1)});});
 await page.goto("/app/cases");await page.getByLabel("Título",{exact:true}).fill("A submitted");await page.getByRole("textbox",{name:"Resumo humano",exact:true}).fill("A summary");
 await page.getByRole("button",{name:"Registrar caso",exact:true}).click();await expect.poll(()=>Boolean(release)).toBe(true);
 await page.getByLabel("Título",{exact:true}).fill("B draft");await page.getByRole("textbox",{name:"Resumo humano",exact:true}).fill("B summary");
 await page.getByLabel("Hipóteses registradas").fill("B hypothesis");await page.getByLabel("Referências de evidência").fill("B reference");
 await page.evaluate(()=>window.dispatchEvent(new Event("focus")));await expect(page.getByLabel("Título",{exact:true})).toBeVisible();
 release?.();await expect(page.getByRole("button",{name:"Registrar caso",exact:true})).toBeEnabled();
 await expect(page.getByRole("alert").filter({hasText:"confirme o resultado antes de repetir"})).toHaveCount(1);
 await expect(page.getByLabel("Título",{exact:true})).toHaveValue("B draft");await expect(page.getByRole("textbox",{name:"Resumo humano",exact:true})).toHaveValue("B summary");
 await expect(page.getByLabel("Hipóteses registradas")).toHaveValue("B hypothesis");await expect(page.getByLabel("Referências de evidência")).toHaveValue("B reference");
});
test("job follow-up resumes the same identifier after an outage without a second upload",async({page})=>{
 await identify(page);let uploads=0;let lookups=0;let retries=0;let published=false;
 const document={document_id:"doc",title:"Published after resume",collection_id:"col",workspace_id:"w",status:"published"};
 const envelope=(status:string)=>({status,job_id:"job-original",job:{job_id:"job-original",status,stage:status,progress:status==="published"?1:0,attempt:1,retryable:false}});
 await page.route("**/api/v1/collections?**",route=>route.fulfill({json:{items:[{collection_id:"col",workspace_id:"w",title:"Collection"}],total:1}}));
 await page.route("**/api/v1/documents?**",route=>route.fulfill({json:{items:published?[document]:[],total:published?1:0,next_cursor:null}}));
 await page.route("**/api/v1/documents/upload",route=>{uploads++;return route.fulfill({json:envelope("queued")});});
 await page.route("**/api/v1/ingestion/jobs/job-original/retry",route=>{retries++;return route.fulfill({status:409,json:{error:{code:"conflict"}}});});
 await page.route("**/api/v1/ingestion/jobs/job-original",route=>{
  lookups++;if(lookups===1)return route.fulfill({status:503,json:{error:{code:"provider_unavailable"}}});published=true;return route.fulfill({json:envelope("published")});
 });
 await page.goto("/app/documents");await page.getByLabel("Selecionar documento para upload").setInputFiles({name:"synthetic.txt",mimeType:"text/plain",buffer:Buffer.from("synthetic source")});
 await expect(page.getByRole("button",{name:"Retomar acompanhamento",exact:true})).toBeVisible();await page.getByRole("button",{name:"Retomar acompanhamento",exact:true}).click();
 await expect(page.getByText("Published after resume",{exact:true})).toBeVisible();expect(uploads).toBe(1);expect(retries).toBe(0);expect(lookups).toBe(2);
 await page.reload();await page.getByLabel("Identificador do processo",{exact:true}).fill("job-original");await page.getByRole("button",{name:"Consultar processo",exact:true}).click();
 await expect(page.getByText("Processo: job-original",{exact:true})).toBeVisible();expect(uploads).toBe(1);expect(retries).toBe(0);expect(lookups).toBe(3);
});
test("a malformed delete 2xx does not announce success or remove the visible document",async({page})=>{
 await identify(page);
 await page.route("**/api/v1/collections?**",route=>route.fulfill({json:{items:[],total:0}}));
 await page.route("**/api/v1/documents?**",route=>route.fulfill({json:{items:[{document_id:"doc",title:"Do not remove",collection_id:"col",workspace_id:"w",status:"published"}],total:1,next_cursor:null}}));
 await page.route("**/api/v1/documents/doc",route=>route.fulfill({json:{document_id:"doc",deleted:"false"}}));
 await page.goto("/app/documents");await page.getByRole("button",{name:"Excluir Do not remove",exact:true}).click();await page.getByRole("button",{name:"Excluir documento",exact:true}).click();
 await expect(page.getByRole("alert").filter({hasText:"resposta incompatível"})).toHaveCount(1);await expect(page.getByText("Do not remove",{exact:true})).toBeVisible();
 await expect(page.getByText(/removido e confirmado pelo servidor/)).toHaveCount(0);
});
