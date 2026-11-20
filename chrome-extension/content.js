(()=>{
  if(window.__draftflowAssistedApplyLoaded) return;
  window.__draftflowAssistedApplyLoaded=true;

  const challengePatterns=[
    /verify (?:that )?you are (?:a )?human/i,
    /complete the (?:captcha|security check)/i,
    /checking your browser/i,
    /human verification/i,
    /i am not a robot/i,
    /i'm not a robot/i
  ];

  function visible(el){
    if(!el) return false;
    const style=getComputedStyle(el);
    const rect=el.getBoundingClientRect();
    return style.display!=="none"&&style.visibility!=="hidden"&&rect.width>1&&rect.height>1;
  }

  function challengePresent(){
    const frames=[...document.querySelectorAll('iframe[src*="captcha" i],iframe[src*="challenge" i],iframe[src*="turnstile" i],iframe[title*="captcha" i],iframe[title*="challenge" i]')];
    if(frames.some(frame=>{
      if(!visible(frame)) return false;
      const rect=frame.getBoundingClientRect();
      const text=((frame.title||"")+" "+(frame.src||"")).toLowerCase();
      if(text.includes("recaptcha")&&rect.width<=100&&rect.height<=100&&!text.includes("challenge")) return false;
      return true;
    })) return true;
    const text=(document.body?.innerText||"").slice(0,120000);
    return challengePatterns.some(pattern=>pattern.test(text));
  }

  function findByLabel(pattern){
    const labels=[...document.querySelectorAll("label")];
    for(const label of labels){
      if(!pattern.test((label.innerText||"").trim())) continue;
      const id=label.htmlFor;
      let field=id?document.getElementById(id):label.querySelector("input,textarea,select");
      if(field&&visible(field)) return field;
    }
    return null;
  }

  function firstVisible(selectors){
    for(const selector of selectors){
      for(const el of document.querySelectorAll(selector)){
        if(visible(el)) return el;
      }
    }
    return null;
  }

  function setValue(el,value){
    if(!el||!value) return false;
    try{
      el.focus();
      const proto=el.tagName==="TEXTAREA"?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
      const desc=Object.getOwnPropertyDescriptor(proto,"value");
      if(desc?.set) desc.set.call(el,value); else el.value=value;
      el.dispatchEvent(new Event("input",{bubbles:true}));
      el.dispatchEvent(new Event("change",{bubbles:true}));
      el.blur();
      return true;
    }catch{return false}
  }

  function locationNeedsManualSelection(){
    return [...document.querySelectorAll('input.location-input, input[name="location"][role="combobox"], input[name="location"][aria-autocomplete="list"]')].some(visible);
  }

  function fillNamed(profile){
    const parts=(profile.fullName||"").trim().split(/\s+/);
    const first=parts[0]||"";
    const last=parts.slice(1).join(" ");
    const fields=[
      [first,/^first name/i,['input[name*="first" i]','input[id*="first" i]','input[autocomplete="given-name"]']],
      [last,/^last name/i,['input[name*="last" i]','input[id*="last" i]','input[autocomplete="family-name"]']],
      [profile.fullName,/^(full |legal |your )?name/i,['input[name="name" i]','input[name*="full_name" i]','input[autocomplete="name"]']],
      [profile.email,/^email/i,['input[type="email"]','input[name*="email" i]']],
      [profile.phone,/^phone|mobile/i,['input[type="tel"]','input[name*="phone" i]']],
      [profile.location,/^location|city/i,['input[name*="location" i]','input[name*="city" i]']],
      [profile.linkedin,/linkedin/i,['input[name*="linkedin" i]','input[id*="linkedin" i]','input[name*="urls" i]']]
    ];
    let count=0;
    for(const [value,labelPattern,selectors] of fields){
      if(challengePresent()) break;
      if(!value) continue;
      const field=findByLabel(labelPattern)||firstVisible(selectors);
      if(!field||field.disabled||field.readOnly||String(field.value||"").trim()) continue;
      if(field.matches('[role="combobox"], [aria-autocomplete="list"], input.location-input')) continue;
      if(setValue(field,value)) count++;
    }
    return count;
  }

  function b64ToFile(resume){
    const binary=atob(resume.base64);
    const bytes=new Uint8Array(binary.length);
    for(let i=0;i<binary.length;i++) bytes[i]=binary.charCodeAt(i);
    return new File([bytes],resume.name||"Resume.pdf",{type:"application/pdf"});
  }

  function attachResume(resume){
    const inputs=[...document.querySelectorAll('input[type="file"]')].filter(el=>{
      const name=((el.name||"")+" "+(el.id||"")+" "+(el.getAttribute("aria-label")||"")).toLowerCase();
      return /resume|cv|curriculum/.test(name)||document.querySelectorAll('input[type="file"]').length===1;
    });
    if(inputs.length!==1) return false;
    try{
      const dt=new DataTransfer();
      dt.items.add(b64ToFile(resume));
      inputs[0].files=dt.files;
      inputs[0].dispatchEvent(new Event("input",{bubbles:true}));
      inputs[0].dispatchEvent(new Event("change",{bubbles:true}));
      return true;
    }catch{return false}
  }

  function missingRequired(){
    const missing=[];
    const required=[...document.querySelectorAll('input[required],textarea[required],select[required],[aria-required="true"]')];
    for(const el of required){
      if(!visible(el)) continue;
      const type=(el.type||"").toLowerCase();
      if(["hidden","submit","button"].includes(type)) continue;
      if(type==="file"){
        if(el.files?.length) continue;
      }else if(type==="checkbox"||type==="radio"){
        if(type==="radio"&&el.name){
          const group=[...document.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`)];
          if(group.some(x=>x.checked)) continue;
        }else if(el.checked) continue;
      }else if(String(el.value||"").trim()){
        continue;
      }
      const label=el.getAttribute("aria-label")||el.name||el.id||"required field";
      if(!missing.includes(label)) missing.push(label);
    }
    return missing;
  }

  function submitButton(){
    const candidates=[...document.querySelectorAll('button,input[type="submit"]')].filter(visible);
    return candidates.find(el=>/^(submit application|submit|apply for this job|apply)$/i.test((el.innerText||el.value||"").trim()))||null;
  }

  function status(){
    if(challengePresent()){
      return {status:"verification_required",message:"Human verification is present. Complete it manually in this same tab, then click Re-check after verification."};
    }
    if(locationNeedsManualSelection()){
      return {status:"review",message:"Select your exact location from the employer dropdown, review all fields, and use the employer\u2019s Submit button yourself. This extension cannot independently verify the location selection."};
    }
    const missing=missingRequired();
    if(missing.length){
      return {status:"missing_required",message:"Manual input is still required: "+missing.slice(0,6).join(", "),missing};
    }
    const button=submitButton();
    if(!button||button.disabled||button.getAttribute("aria-disabled")==="true"||document.querySelector("input:invalid:not([type=hidden]),textarea:invalid,select:invalid,[aria-invalid=true]")){
      return {status:"review",message:"Review invalid fields or wait for the employer form to finish loading before submitting."};
    }
    return {status:"ready",message:"All detected required fields are complete and no human verification is visible. Ready to submit."};
  }

  chrome.runtime.onMessage.addListener((message,_sender,sendResponse)=>{
    if(message?.type!=="DRAFTFLOW_ASSISTED_APPLY") return;
    (async()=>{
      if(message.command==="fill"){
        if(challengePresent()){
          sendResponse({status:"verification_required",message:"Human verification is already present. Complete it manually, then re-check."}); return;
        }
        const filled=fillNamed(message.profile||{});
        if(challengePresent()){sendResponse(status());return;}
        const attached=attachResume(message.resume||{});
        const next=status();
        next.message=`Filled ${filled} candidate fields. Resume ${attached?"attached":"needs manual attachment"}. ${next.message}`;
        sendResponse(next);
        return;
      }
      if(message.command==="check"){
        sendResponse(status()); return;
      }
      if(message.command==="submit"){
        const current=status();
        if(current.status!=="ready"){
          sendResponse(current); return;
        }
        const button=submitButton();
        if(!button){
          sendResponse({status:"review",message:"Submit button is not available."}); return;
        }
        button.click();
        sendResponse({status:"submission_attempted",message:"Submit was clicked. Submission is not confirmed. Check the employer confirmation page and email before recording success."});
        return;
      }
      sendResponse({status:"review",message:"Unknown command."});
    })();
    return true;
  });
})();
