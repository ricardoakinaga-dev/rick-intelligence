// @vitest-environment jsdom
import { afterEach,expect,it,vi } from "vitest";
import { api } from "../../lib/api";
const user={user_id:"u",email:"u@example.invalid",role:"viewer",canonical_role:"VIEWER",tenant_id:"t",workspace_id:"w",status:"active"};
const doc={document_id:"d",title:"Doc",collection_id:"col",workspace_id:"w",status:"published"};
const collection={collection_id:"col",workspace_id:"w",title:"Collection",version:1};
const job={status:"queued",job_id:"j",document_id:"d",job:{job_id:"j",document_id:"d",status:"queued",stage:"queued",progress:0,attempt:1,retryable:false,cancel_requested:false},document:doc,cancelled:false};
const conversation={conversation_id:"c",title:"Conversation",workspace_id:"w",collection_id:null,status:"active",created_at:1,updated_at:1,message_count:0};
const record={contract_version:"1",clinical_scope_status:"record_review_feedback_only",case_id:"case",tenant_id:"t",workspace_id:"w",owner_user_id:"u",title:"Title",summary:"Summary",record:"Record",hypotheses:[{hypothesis_id:"h",statement:"Hypothesis",status:"open"}],evidence:[{evidence_id:"e",source_type:"manual",source_id:"manual"}],agent_model:null,status:"open",created_by_user_id:"u",updated_by_user_id:"u",created_at:1,updated_at:1,review_count:0,feedback_count:0};
const review={contract_version:"1",review_id:"r",case_id:"case",tenant_id:"t",workspace_id:"w",decision:"recorded" as const,review_note:"Review",reviewer_user_id:"u",created_at:1};
const feedback={contract_version:"1",feedback_id:"f",case_id:"case",tenant_id:"t",workspace_id:"w",kind:"correction" as const,feedback_note:"Feedback",feedback_user_id:"u",created_at:1};
const rows:Array<{name:string;call:()=>Promise<unknown>;payload:unknown}>=[
 {name:"health",call:()=>api.health(),payload:{status:"ready",checks:{api:{ok:true}}}},
 {name:"adminHealth",call:()=>api.adminHealth(),payload:{status:"ready",checks:[{name:"api",ok:true,required:true}]}},
 {name:"users",call:()=>api.adminUsers(),payload:{items:[user],total:1}},
 {name:"createUser",call:()=>api.createAdminUser({email:user.email,role:"viewer",tenant_id:"t",password:"synthetic"}),payload:{status:"created",user}},
 {name:"updateUser",call:()=>api.updateAdminUser("u",{email:user.email}),payload:{status:"updated",user}},
 {name:"deactivateUser",call:()=>api.deactivateAdminUser("u"),payload:{status:"deactivated",user_id:"u",revoked_sessions:1}},
 {name:"resetAdminPassword",call:()=>api.resetAdminUserPassword("u",{password:"synthetic"}),payload:{status:"reset",user_id:"u",revoked_sessions:1}},
 {name:"sessions",call:()=>api.adminSessions(),payload:{items:[{session_id:"s",user_id:"u",email:user.email,tenant_id:"t",workspace_id:"w",created_at:1,last_seen_at:1,expires_at:2,revoked:false}],total:1}},
 {name:"revoke",call:()=>api.revokeAdminSessions({session_id:"s"}),payload:{revoked:1}},
 {name:"documents",call:()=>api.documents("w"),payload:{items:[doc],total:1,next_cursor:null}},
 {name:"collections",call:()=>api.collections("w"),payload:{items:[collection],total:1}},
 {name:"createCollection",call:()=>api.createCollection({collection_id:"col",title:"Collection"}),payload:collection},
 {name:"updateCollection",call:()=>api.updateCollection("col",{title:"Collection"}),payload:collection},
 {name:"archiveCollection",call:()=>api.archiveCollection("col"),payload:collection},
 {name:"createConversation",call:()=>api.createConversation(),payload:conversation},
 {name:"archiveConversation",call:()=>api.archiveConversation("c"),payload:{conversation_id:"c",status:"archived"}},
 {name:"cases",call:()=>api.listCases("mine",50,0),payload:{items:[record],total:1,next_offset:null}},
 {name:"createCase",call:()=>api.createCase({title:"Title"}),payload:record},
 {name:"getCase",call:()=>api.getCase("case"),payload:{case:record,reviews:[review],feedback:[feedback]}},
 {name:"updateCase",call:()=>api.updateCase("case",{title:"Title"}),payload:record},
 {name:"reviewCase",call:()=>api.reviewCase("case",{decision:"recorded",review_note:"Review"}),payload:review},
 {name:"feedbackCase",call:()=>api.feedbackCase("case",{kind:"correction",feedback_note:"Feedback"}),payload:feedback},
 {name:"catalog",call:()=>api.agentModelCatalog(),payload:{catalog_status:"configured",items:[{agent_id:"a",model_id:"m",catalog_version:"1",status:"authorized",purpose:"metadata_only"}]}},
 {name:"upload",call:()=>api.upload(new File(["text"],"f.txt"),"col"),payload:job},
 {name:"job",call:()=>api.job("j"),payload:job},
 {name:"cancel",call:()=>api.cancelJob("j"),payload:job},
 {name:"retry successor",call:()=>api.retryJob("old",new File(["text"],"f.txt")),payload:job},
 {name:"reindex",call:()=>api.reindexDocument("d"),payload:job},
 {name:"delete",call:()=>api.deleteDocument("d"),payload:{document_id:"d",deleted:true,deleted_chunks:0}},
 {name:"search",call:()=>api.search({query:"q"}),payload:{query:"q",items:[{chunk_id:"chunk",document_id:"d",title:null,source:null,text:null,score:null,rank:null,page_start:null,page_end:null,checksum:null,collection_id:null,workspace_id:null}],total:1,metadata:{backend:"qdrant",workspace_id:"w",candidate_count:1,selected_count:1,fallback_used:false}}},
 {name:"audit",call:()=>api.audit(),payload:{items:[{action:"read",timestamp:1,metadata:{}}],total:1}},
 {name:"chat",call:()=>api.chat({message:"q",workspace_id:"w"}),payload:{conversation_id:"c",message_id:"m",answer:"A",citations:[],metadata:{}}},
 {name:"logout",call:()=>api.logout(),payload:{status:"signed_out"}},
];
afterEach(()=>vi.unstubAllGlobals());
for(const row of rows)it(`accepts the public ${row.name} contract`,async()=>{
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify(row.payload),{status:200})));await expect(row.call()).resolves.toMatchObject(row.payload as object);
});
