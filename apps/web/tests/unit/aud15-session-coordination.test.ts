// @vitest-environment jsdom
import { afterEach,beforeEach,expect,it,vi } from "vitest";
import { SessionCoordination, SESSION_CHANGE_KEY, SESSION_OPERATION_PREFIX, readSessionCoordination } from "../../lib/session-coordination";
beforeEach(()=>localStorage.clear());afterEach(()=>vi.restoreAllMocks());
it("keeps independent durable markers for two producers and a third observer, including boot after partial completion",()=>{
 const b=new SessionCoordination(),c=new SessionCoordination(),a=new SessionCoordination();const bId=b.begin(),cId=c.begin();
 expect(bId).not.toBe(cId);expect(a.snapshot().pending).toBe(true);b.settle(bId);expect(localStorage.getItem(SESSION_CHANGE_KEY)).toBe(`settled:v2:${bId}`);
 expect(a.snapshot().pending).toBe(true);expect(new SessionCoordination().snapshot().pending).toBe(true);expect(localStorage.getItem(`${SESSION_OPERATION_PREFIX}${cId}`)).toBe("pending");
 c.settle(cId);expect(a.snapshot().pending).toBe(false);expect(new SessionCoordination().snapshot().pending).toBe(false);
});
it("pairs opaque operation ids without overwriting another producer and never stores private values",()=>{
 const b=new SessionCoordination();const id=b.begin();expect(localStorage.getItem(SESSION_CHANGE_KEY)).toBe(`pending:v2:${id}`);expect(b.snapshot().pending).toBe(false);expect(readSessionCoordination().pendingIds).toEqual([id]);
 b.settle(id);expect(localStorage.getItem(SESSION_CHANGE_KEY)).toBe(`settled:v2:${id}`);expect(localStorage.getItem(`${SESSION_OPERATION_PREFIX}${id}`)).toBeNull();
});
it("never removes another producer's marker and fails closed on storage read failure",()=>{
 const b=new SessionCoordination(),a=new SessionCoordination();const id=b.begin();a.settle(id);expect(a.snapshot().pending).toBe(true);
 vi.spyOn(Storage.prototype,"getItem").mockImplementation(()=>{throw new DOMException("unavailable","SecurityError");});expect(a.snapshot()).toMatchObject({available:false,pending:true});
});
it("does not trust an enumeration whose indexes shift during another producer's settlement",()=>{
 const b=new SessionCoordination(),c=new SessionCoordination(),observer=new SessionCoordination();const bId=b.begin(),cId=c.begin();
 const key=Storage.prototype.key;let changed=false;vi.spyOn(Storage.prototype,"key").mockImplementation(function(this:Storage,index:number){const result=key.call(this,index);if(!changed&&result===`${SESSION_OPERATION_PREFIX}${bId}`){changed=true;b.settle(bId);}return result;});
 expect(readSessionCoordination().stable).toBe(false);expect(observer.snapshot().pending).toBe(true);c.settle(cId);expect(observer.snapshot().pending).toBe(false);
});
it("does not start a mutation if its durable announcement cannot be published",()=>{
 const a=new SessionCoordination();vi.spyOn(Storage.prototype,"setItem").mockImplementation(()=>{throw new DOMException("quota","QuotaExceededError");});expect(()=>a.begin()).toThrow();expect(localStorage.length).toBe(0);
});
it("tracks legacy phases by token, not boolean or counter, and ignores unrelated settlement",()=>{
 const a=new SessionCoordination();for(const value of ["pending:B","pending:C","settled:B","settled:unknown"])a.observe(new StorageEvent("storage",{key:SESSION_CHANGE_KEY,newValue:value}));
 expect(a.snapshot().pending).toBe(true);a.observe(new StorageEvent("storage",{key:SESSION_CHANGE_KEY,newValue:"settled:C"}));expect(a.snapshot().pending).toBe(false);
});
