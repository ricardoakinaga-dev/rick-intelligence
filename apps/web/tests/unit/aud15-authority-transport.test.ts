// @vitest-environment jsdom
import { afterEach,beforeEach,expect,it,vi } from "vitest";
import { api, errorMessage } from "../../lib/api";
import { suspendClientAuthority,resumeClientAuthority } from "../../lib/client-authority";
import { SessionCoordination } from "../../lib/session-coordination";
function deferred<T>(){let resolve!:(v:T)=>void;const promise=new Promise<T>(a=>resolve=a);return{promise,resolve};}
beforeEach(()=>{localStorage.clear();resumeClientAuthority();});afterEach(()=>{localStorage.clear();resumeClientAuthority();vi.unstubAllGlobals();});
for(const kind of ["json","form","sse"] as const)it(`blocks and aborts private ${kind}, including a fetch that ignores abort`,async()=>{
 const response=deferred<Response>();const fetcher=vi.fn().mockReturnValue(response.promise);vi.stubGlobal("fetch",fetcher);const event=vi.fn();
 const call=()=>kind==="json"?api.documents("w"):kind==="form"?api.upload(new File(["synthetic"],"f.txt"),"c"):api.chatStream({message:"q"},undefined,event);
 const pending=call();const rejection=expect(pending).rejects.toMatchObject({name:"AbortError",message:expect.stringContaining("ela pode ter sido executada")});const signal=fetcher.mock.calls[0][1].signal as AbortSignal;
 suspendClientAuthority();expect(signal.aborted).toBe(true);expect(errorMessage(signal.reason,"fallback")).toContain("ela pode ter sido executada");await expect(call()).rejects.toMatchObject({code:"session_validation_pending"});expect(fetcher).toHaveBeenCalledOnce();
 resumeClientAuthority();response.resolve(new Response(JSON.stringify({items:[],total:0}),{status:200}));await rejection;expect(event).not.toHaveBeenCalled();
});
for(const kind of ["json","sse"] as const)it(`rejects old ${kind} and blocks admission with two producers even when every storage event is delayed`,async()=>{
 const response=deferred<Response>();const fetcher=vi.fn().mockReturnValue(response.promise);vi.stubGlobal("fetch",fetcher);const event=vi.fn();
 const pending=kind==="json"?api.documents("w"):api.chatStream({message:"q"},undefined,event);const rejection=expect(pending).rejects.toMatchObject({name:"AbortError"});
 const b=new SessionCoordination(),c=new SessionCoordination();const bId=b.begin(),cId=c.begin();b.settle(bId);resumeClientAuthority();
 await expect(api.documents("w")).rejects.toMatchObject({code:"session_validation_pending"});expect(fetcher).toHaveBeenCalledOnce();
 response.resolve(new Response('{"items":[],"total":0}',{status:200}));await rejection;expect(event).not.toHaveBeenCalled();c.settle(cId);
 await expect(api.documents("w")).rejects.toMatchObject({code:"session_validation_pending"});
 resumeClientAuthority();fetcher.mockResolvedValueOnce(new Response('{"items":[],"total":0}',{status:200}));await expect(api.documents("w")).resolves.toMatchObject({total:0});
});
it("never reopens admission against a stamp other than the one actually validated",async()=>{
 const remote=new SessionCoordination();const id=remote.begin();remote.settle(id);const changed=vi.fn();window.addEventListener("rick-session-invalid",changed);
 try{resumeClientAuthority(null);expect(changed).toHaveBeenCalledOnce();await expect(api.documents("w")).rejects.toMatchObject({code:"session_validation_pending"});}finally{window.removeEventListener("rick-session-invalid",changed);}
});
it("a completed unseen producer still invalidates old authority and in-flight results",async()=>{
 const response=deferred<Response>();vi.stubGlobal("fetch",vi.fn().mockReturnValue(response.promise));const pending=api.documents("w");const rejection=expect(pending).rejects.toMatchObject({name:"AbortError"});
 const b=new SessionCoordination();const id=b.begin();b.settle(id);await expect(api.deleteDocument("d")).rejects.toMatchObject({code:"session_validation_pending"});response.resolve(new Response('{"items":[],"total":0}',{status:200}));await rejection;
});
it("suppresses a body that finishes after invalidation even when fetch had already returned",async()=>{
 const body=deferred<string>();const response=new Response("unused",{status:200});vi.spyOn(response,"text").mockReturnValue(body.promise);vi.stubGlobal("fetch",vi.fn().mockResolvedValue(response));
 const pending=api.documents("w");const rejection=expect(pending).rejects.toMatchObject({name:"AbortError",message:expect.stringContaining("ela pode ter sido executada")});await Promise.resolve();suspendClientAuthority();resumeClientAuthority();body.resolve('{"items":[],"total":0}');await rejection;
});
it("permits authority revalidation while private mutations stay blocked",async()=>{
 suspendClientAuthority();const fetcher=vi.fn().mockResolvedValue(new Response('{"error":{"message":"denied"}}',{status:401}));vi.stubGlobal("fetch",fetcher);
 await expect(api.me()).rejects.toMatchObject({status:401});await expect(api.deleteDocument("d")).rejects.toMatchObject({code:"session_validation_pending"});expect(fetcher).toHaveBeenCalledOnce();
});
