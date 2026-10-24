import { expect, test, type Route } from "@playwright/test";

test("same-authority focus temporarily hides private UI without losing draft or focus",async({page})=>{
 const identity={authenticated:true,user_id:"A",email:"A@example.invalid",role:"viewer",canonical_role:"VIEWER",tenant_id:"t",workspace_id:"w",session_id:"s",permissions:["chat.query","history.read"]};
 let hold=false;let pending:Route|undefined;
 await page.route("**/api/v1/auth/me",route=>{if(hold){pending=route;return;}return route.fulfill({json:identity});});
 await page.route("**/api/v1/conversations**",route=>route.fulfill({json:{items:[],total:0}}));
 await page.goto("/app/chat");const input=page.getByLabel("Pergunta",{exact:true});await input.fill("LOCAL DRAFT");await input.focus();
 hold=true;await page.evaluate(()=>window.dispatchEvent(new Event("focus")));
 await expect(input).toBeHidden();await expect.poll(()=>Boolean(pending)).toBe(true);hold=false;await pending!.fulfill({json:identity});
 await expect(input).toBeVisible();await expect(input).toHaveValue("LOCAL DRAFT");await expect(input).toBeFocused();
});

test("two producers cannot release a third tab early, including bootstrap after the first settlement",async({context,page})=>{
 const identity=(id:string)=>({authenticated:true,user_id:id,email:`${id}@example.invalid`,role:"viewer",canonical_role:"VIEWER",tenant_id:"t",workspace_id:id,session_id:`s-${id}`,permissions:["chat.query","history.read"]});
 let current=identity("A");let observerReads=0;
 await context.route("**/api/v1/auth/me",route=>{if(route.request().frame().page()===page)observerReads+=1;return route.fulfill({json:current});});
 await context.route("**/api/v1/conversations**",route=>route.fulfill({json:{items:[],total:0}}));
 await page.goto("/app/chat");await expect(page.getByLabel("Pergunta",{exact:true})).toBeVisible();
 const first=await context.newPage(),second=await context.newPage();await first.goto("/login");await second.goto("/login");
 await first.evaluate(()=>{localStorage.setItem("rick-session-op:opaque-first","pending");localStorage.setItem("rick-session-change","pending:v2:opaque-first");});
 await second.evaluate(()=>{localStorage.setItem("rick-session-op:opaque-second","pending");localStorage.setItem("rick-session-change","pending:v2:opaque-second");});
 await expect(page.getByLabel("Pergunta",{exact:true})).toBeHidden();const before=observerReads;
 await first.evaluate(()=>{localStorage.removeItem("rick-session-op:opaque-first");localStorage.setItem("rick-session-change","settled:v2:opaque-first");});
 await page.evaluate(()=>window.dispatchEvent(new Event("focus")));await expect(page.getByRole("heading",{name:"Sessão em alteração em outra aba."})).toBeVisible();expect(observerReads).toBe(before);
 await page.reload();await expect(page.getByRole("heading",{name:"Sessão em alteração em outra aba."})).toBeVisible();expect(observerReads).toBe(before);
 current=identity("B");await second.evaluate(()=>{localStorage.removeItem("rick-session-op:opaque-second");localStorage.setItem("rick-session-change","settled:v2:opaque-second");});
 await expect(page.locator(".profile-button strong")).toHaveText("B@example.invalid");await expect(page.getByLabel("Pergunta",{exact:true})).toBeVisible();await first.close();await second.close();
});

// Synthetic same-origin transport; this exercises real browser storage delivery
// across pages, not an IdP or a server-side ACL proof.
test("old tab clears A immediately and revalidates B without broadcasting private data", async ({ context, page }) => {
 const identity = (id: string) => ({ authenticated:true,user_id:id,email:`${id}@example.invalid`,role:"viewer",canonical_role:"VIEWER",tenant_id:"t",workspace_id:id,session_id:`s-${id}`,permissions:["chat.query","history.read"] });
 let current = identity("A"); let hold = false; let release: (()=>void) | undefined;
 await context.route("**/api/v1/auth/me",async route=>{ if(hold) await new Promise<void>(resolve=>{release=resolve;}); await route.fulfill({json:current}); });
 await context.route("**/api/v1/conversations**",route=>route.fulfill({json:{items:[],total:0}}));
 await context.route("**/health/ready",route=>route.fulfill({json:{status:"ready"}}));
 await page.goto("/app/chat"); await expect(page.locator(".profile-button strong")).toHaveText("A@example.invalid");
 const other=await context.newPage(); await other.goto("/login");
 await expect.poll(()=>other.locator("html").getAttribute("data-rick-hydrated")).toBe("true");
 hold=true; current=identity("B");
 await other.evaluate(()=>localStorage.setItem("rick-session-change","pending:synthetic-nonce"));
 await expect(page.locator(".profile-button strong")).toBeHidden();
 await expect(page.getByLabel("Pergunta",{exact:true})).toBeHidden();
 await other.evaluate(()=>localStorage.setItem("rick-session-change","settled:synthetic-nonce"));
 await expect.poll(()=>Boolean(release)).toBe(true);
 await expect(page.locator(".profile-button strong")).toBeHidden();
 hold=false; release?.();
 await expect(page.locator(".profile-button strong")).toHaveText("B@example.invalid");
 expect(await other.evaluate(()=>localStorage.getItem("rick-session-change"))).toBe("settled:synthetic-nonce");
 await other.close();
});
