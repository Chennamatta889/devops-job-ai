const ids=["fullName","email","phone","location","linkedin"];
const result=document.getElementById("result");
const siteStatus=document.getElementById("siteStatus");
const resumeStatus=document.getElementById("resumeStatus");

function show(message,type=""){
  result.hidden=false;
  result.className="result"+(type?" "+type:"");
  result.textContent=message;
}

async function currentTab(){
  const tabs=await chrome.tabs.query({active:true,currentWindow:true});
  return tabs[0];
}

function supported(url=""){
  try{
    const host=new URL(url).hostname.toLowerCase();
    return ["job-boards.greenhouse.io","boards.greenhouse.io","jobs.lever.co","jobs.ashbyhq.com"].includes(host);
  }catch{return false}
}

async function loadSession(){
  const data=await chrome.storage.session.get(["candidateProfile","resumePdf"]);
  const p=data.candidateProfile||{};
  ids.forEach(id=>{document.getElementById(id).value=p[id]||""});
  resumeStatus.textContent=data.resumePdf
    ? `Resume ready for this session: ${data.resumePdf.name}`
    : "Nothing is synced. Session data clears when Chrome closes.";
}

async function saveSession(){
  const profile={};
  ids.forEach(id=>profile[id]=document.getElementById(id).value.trim());
  if(!profile.fullName||!profile.email||!profile.phone){
    show("Full name, email, and phone are required.","error"); return false;
  }
  await chrome.storage.session.set({candidateProfile:profile});
  const file=document.getElementById("resume").files[0];
  if(file){
    if(file.type!=="application/pdf"&&!file.name.toLowerCase().endsWith(".pdf")){
      show("Please choose a PDF resume.","error"); return false;
    }
    if(file.size>6*1024*1024){
      show("Resume must be 6 MB or smaller.","error"); return false;
    }
    const bytes=new Uint8Array(await file.arrayBuffer());
    let binary="";
    const chunk=0x8000;
    for(let i=0;i<bytes.length;i+=chunk){
      binary+=String.fromCharCode(...bytes.subarray(i,i+chunk));
    }
    const base64=btoa(binary);
    await chrome.storage.session.set({resumePdf:{name:file.name,type:"application/pdf",base64}});
    resumeStatus.textContent=`Resume ready for this session: ${file.name}`;
  }
  show("Candidate data saved for this Chrome session.","success");
  return true;
}

async function send(command){
  const tab=await currentTab();
  if(!tab?.id||!supported(tab.url)){
    show("Open a supported Greenhouse, Lever, or Ashby application tab first.","error"); return;
  }
  const data=await chrome.storage.session.get(["candidateProfile","resumePdf"]);
  if(!data.candidateProfile||!data.resumePdf){
    show("Save your candidate details and PDF resume first.","error"); return;
  }
  try{
    const response=await chrome.tabs.sendMessage(tab.id,{
      type:"DRAFTFLOW_ASSISTED_APPLY",
      command,
      profile:data.candidateProfile,
      resume:data.resumePdf
    });
    if(!response){show("The application page did not respond. Reload it and try again.","error");return}
    const type=response.status==="ready"||response.status==="submitted"?"success":
      response.status==="verification_required"||response.status==="missing_required"?"error":"";
    show(response.message||response.status,type);
  }catch(err){
    show("Could not access this application tab. Reload it and try again.","error");
  }
}

document.getElementById("save").addEventListener("click",saveSession);
document.getElementById("fill").addEventListener("click",async()=>{if(await saveSession()) await send("fill")});
document.getElementById("continue").addEventListener("click",()=>send("check"));
document.getElementById("submit").addEventListener("click",()=>send("submit"));

(async()=>{
  await loadSession();
  const tab=await currentTab();
  siteStatus.textContent=supported(tab?.url)
    ? "Supported application detected. Fill the form, complete any human verification yourself, then re-check."
    : "Open a supported Greenhouse, Lever, or Ashby application.";
})();
