import { expect,it } from "vitest";
import { suspendClientAuthority,resumeClientAuthority,privateRequestLease } from "../../lib/client-authority";
it("does not retain or gate server-side authority across users",()=>{
 expect(typeof window).toBe("undefined");suspendClientAuthority();const lease=privateRequestLease();expect(lease.signal).toBeUndefined();expect(lease.current()).toBe(true);expect(()=>lease.assert()).not.toThrow();resumeClientAuthority();
});
