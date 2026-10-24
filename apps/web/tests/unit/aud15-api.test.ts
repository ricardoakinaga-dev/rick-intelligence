// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
afterEach(()=>vi.unstubAllGlobals());
for (const payload of ["<html>proxy</html>", "{", "{}", '{"items":[]}', '{"items":[{}],"total":1}', '{"items":[],"total":"0"}']) it(`rejects malformed documents: ${payload}`,async()=>{
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(payload,{status:200,headers:{"x-request-id":"contract-test"}})));
 await expect(api.documents("w")).rejects.toMatchObject({code:"invalid_response",requestId:"contract-test"});
});
for (const payload of [{},{authenticated:true},{authenticated:false,user_id:"u"},{authenticated:true,user_id:"u",workspace_id:"w",session_id:"s",permissions:"admin"}]) it(`rejects false session authority ${JSON.stringify(payload)}`,async()=>{
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify(payload),{status:200})));
 await expect(api.me()).rejects.toMatchObject({code:"invalid_response"});
});
it("signals 401 invalidation without private payload and preserves abort/job signal", async()=>{
 const listener=vi.fn();window.addEventListener("rick-session-invalid",listener);
 try {
  const controller=new AbortController();const abort=new DOMException("cancelled","AbortError");
  const fetcher=vi.fn().mockResolvedValueOnce(new Response('{"error":{"message":"denied"}}',{status:401})).mockRejectedValueOnce(abort);vi.stubGlobal("fetch",fetcher);
  await expect(api.documents("w")).rejects.toMatchObject({status:401});expect(listener).toHaveBeenCalledOnce();expect((listener.mock.calls[0][0] as Event & {detail?:unknown}).detail).toBeUndefined();
  await expect(api.job("id/encoded",controller.signal)).rejects.toBe(abort);expect(fetcher.mock.calls[1][0]).toContain("id%2Fencoded");expect(fetcher.mock.calls[1][1].signal.aborted).toBe(false);controller.abort();expect(fetcher.mock.calls[1][1].signal.aborted).toBe(true);
 } finally {window.removeEventListener("rick-session-invalid",listener);}
});
it("accepts complete session and rejects malformed job and conversation envelopes",async()=>{
 const session={authenticated:true,user_id:"u",email:"u@example.invalid",role:"viewer",canonical_role:"VIEWER",tenant_id:"t",workspace_id:"w",session_id:"s",permissions:["chat.query"]};
 vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(session),{status:200})).mockResolvedValueOnce(new Response('{"job_id":"j","status":"queued","job":{}}',{status:200})).mockResolvedValueOnce(new Response('{"items":[{}],"total":1}',{status:200})));
 await expect(api.me()).resolves.toEqual(session);await expect(api.job("j")).rejects.toMatchObject({code:"invalid_response"});await expect(api.listConversations()).rejects.toMatchObject({code:"invalid_response"});
});
for (const payload of [{document_id:"d",deleted:"false"},{document_id:"other",deleted:true},{document_id:"d",deleted:true,deleted_chunks:"3"}]) it(`rejects invalid delete acknowledgement ${JSON.stringify(payload)}`,async()=>{
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify(payload),{status:200})));await expect(api.deleteDocument("d")).rejects.toMatchObject({code:"invalid_response"});
});
for(const patch of [{job:{job_id:"other",status:"queued",stage:"queued",progress:0,attempt:0}},{job:{job_id:"j",status:"queued",stage:"queued",progress:0,attempt:0,retryable:"false"}},{cancelled:"false"}]) it(`rejects inconsistent job/flags ${JSON.stringify(patch)}`,async()=>{
 const envelope={status:"queued",job_id:"j",job:{job_id:"j",status:"queued",stage:"queued",progress:0,attempt:0},...patch};vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify(envelope),{status:200})));await expect(api.job("j")).rejects.toMatchObject({code:"invalid_response"});
});
it("does not confirm logout from a 200 failure-shaped status",async()=>{
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response('{"status":"failed"}',{status:200})));await expect(api.logout()).rejects.toMatchObject({code:"invalid_response"});
});
it("permits only coherent retry successors and never substitutes a different GET/cancel job",async()=>{
 const valid={status:"queued",job_id:"NEW",job:{job_id:"NEW",status:"queued",stage:"queued",progress:0,attempt:1}};
 vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(valid),{status:200})).mockResolvedValueOnce(new Response(JSON.stringify({...valid,job:{...valid.job,job_id:"OTHER"}}),{status:200})).mockImplementation(async()=>new Response(JSON.stringify(valid),{status:200})));
 await expect(api.retryJob("OLD",new File(["x"],"f.txt"))).resolves.toEqual(valid);await expect(api.retryJob("OLD",new File(["x"],"f.txt"))).rejects.toMatchObject({code:"invalid_response"});
 await expect(api.job("OLD")).rejects.toMatchObject({code:"invalid_response"});await expect(api.cancelJob("OLD")).rejects.toMatchObject({code:"invalid_response"});
});
for(const [name,call] of Object.entries({logout:()=>api.logout(),cases:()=>api.listCases(),case:()=>api.getCase("c"),catalog:()=>api.agentModelCatalog(),users:()=>api.adminUsers(),sessions:()=>api.adminSessions(),health:()=>api.adminHealth(),audit:()=>api.audit(),search:()=>api.search({query:"q"})}))it(`rejects missing consumed fields in ${name}`,async()=>{
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response("{}",{status:200})));await expect(call()).rejects.toMatchObject({code:"invalid_response"});
});
for (const [scope, read] of Object.entries({ readiness: () => api.health(), admin: () => api.adminHealth() })) {
 it(`accepts nullable health detail serialized by the real API (${scope})`, async()=>{
  const payload={status:"ready",checks:[{name:"kernel",ok:true,required:true,detail:null}]};
  vi.stubGlobal("fetch",vi.fn().mockImplementation(async()=>new Response(JSON.stringify(payload),{status:200})));
  await expect(read()).resolves.toEqual(payload);
 });
 for(const detail of [false,0,{},[]])it(`rejects health detail of an incompatible type (${scope}, ${JSON.stringify(detail)})`,async()=>{
  vi.stubGlobal("fetch",vi.fn().mockImplementation(async()=>new Response(JSON.stringify({status:"ready",checks:[{name:"kernel",ok:true,required:true,detail}]}),{status:200})));
  await expect(read()).rejects.toMatchObject({code:"invalid_response"});
 });
}
it("accepts valid empty documents and legitimate no-body logout",async()=>{
 vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(new Response('{"items":[],"total":0}',{status:200})).mockResolvedValueOnce(new Response(null,{status:204})));
 await expect(api.documents("w")).resolves.toEqual({items:[],total:0}); await expect(api.logout()).resolves.toBeUndefined();
});
