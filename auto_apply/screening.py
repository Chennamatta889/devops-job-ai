"""Screening answers use explicit candidate facts, never guessed declarations."""
import re
def normalize(s):
    return re.sub(r"[^a-z0-9]+"," ",str(s or "").lower()).strip()
def answer_for(question, profile):
    q=normalize(question)
    if not q: return None
    answers=profile.get("screening_answers",{})
    if isinstance(answers,dict):
        for key,value in answers.items():
            if normalize(key)==q and isinstance(value,(str,int,float,bool)):
                if isinstance(value, str) and value.strip().lower() in ("yes", "no"):
                    return value.strip().lower() == "yes"
                return value
    q=re.sub(r"^(?:please (?:enter|provide|specify|share|select) (?:your )?|what (?:is|are) your )","",q)
    q=re.sub(r" (?:required|optional)$","",q)
    city_match=re.fullmatch(r"(?:are you )?(?:currently )?(?:living|located|based|residing) in ([a-z0-9 ]+)",q)
    if city_match and profile.get("current_location"):
        city=normalize(city_match.group(1))
        return city in normalize(profile["current_location"])
    relocate_city=re.fullmatch(r"(?:if not )?(?:will|would) you be (?:comfortable|willing|open to) relocat(?:e|ing) to ([a-z0-9 ]+)",q)
    if relocate_city and profile.get("willing_to_relocate") is not None:
        return bool(profile["willing_to_relocate"])
    if ("relocate to hyderabad" in q and "work from the office" in q) and profile.get("willing_to_relocate") is not None and profile.get("open_to_onsite") is not None:
        return bool(profile["willing_to_relocate"]) and bool(profile["open_to_onsite"])
    if ("rotational shift" in q or "night shift" in q or "work in shifts" in q) and profile.get("willing_to_work_in_shifts") is not None:
        if ("work from office" in q or "work from office role" in q) and profile.get("open_to_onsite") is not None:
            return bool(profile["willing_to_work_in_shifts"]) and bool(profile["open_to_onsite"])
        return bool(profile["willing_to_work_in_shifts"])
    if q in ("what is your current notice period","current notice period"):
        if profile.get("notice_period_days") is not None: return profile["notice_period_days"]
    if q in ("what is your expected annual ctc range","expected annual ctc range"):
        if profile.get("expected_ctc_lpa") is not None: return f"{profile['expected_ctc_lpa']:g} LPA"
        if profile.get("expected_ctc_inr") is not None: return f"{float(profile['expected_ctc_inr'])/100000:g} LPA"
    if q in ("how did you come to know about plane","how did you hear about us","how did you hear about this role"):
        if profile.get("application_source"): return profile["application_source"]
    if q in ("if available immediately what was your last working day in the previous organisation","if available immediately what was your last working day in the previous organization"):
        if profile.get("immediate_joiner") is False or (isinstance(profile.get("notice_period_days"),int) and profile["notice_period_days"]>0):
            return f"Not applicable - serving a {profile.get('notice_period_days',0)}-day notice period."
    if q in ("what is the earliest you would want to start","earliest start date","when can you start","when would you be available to start","if you are offered by when can you join"):

        if profile.get("earliest_start_date"): return profile["earliest_start_date"]
        days=profile.get("notice_period_days")
        if type(days) is int and days>=0:
            return f"Available after my {days}-day notice period."
    fields=(
        (r"^(?:current|present) (?:work |job |residential )?(?:location|city)(?: in india)?$","current_location"),
        (r"^(?:current|present) (?:company|employer|organization)(?: name)?$|^name of (?:your )?(?:current|present) (?:company|employer|organization)$","current_company"),
        (r"^(?:preferred|desired) (?:job |work )?(?:location|city)(?: s)?$","preferred_location"),
        (r"^(?:are you )?(?:willing|open|ready) to relocate(?: .+)?$","willing_to_relocate"),
        (r"^(?:are you an? )?immediate joiner$","immediate_joiner"),
        (r"^(?:are you )?(?:willing|available|open) to work (?:in )?(?:rotational |night |flexible )?shifts$","willing_to_work_in_shifts"),
        (r"^(?:are you )?(?:willing|available|open) to (?:work|participate) (?:in )?on call(?: rotations?)?$","willing_to_work_on_call"),
        (r"^(?:are you )?(?:open|willing) to work (?:in )?(?:a )?hybrid(?: model)?$","open_to_hybrid"),
        (r"^(?:are you )?(?:open|willing) to work (?:in )?(?:a )?remote(?: model)?$","open_to_remote"),
        (r"^(?:are you )?(?:open|willing) to work (?:in )?(?:a )?on site(?: model)?$","open_to_onsite"),
        (r"^(?:country|country of residence)$","country"),
        (r"^(?:state|state of residence)$","state"),
        (r"^(?:nationality|citizenship)$","nationality"),
        (r"^(?:gender)$","gender"),
        (r"^(?:graduation year|year of graduation|year of passing|passing year)$","graduation_year"),
        (r"^(?:degree|highest degree|educational qualification|qualification)$","education"),
        (r"^(?:university|university name|college|college name)$","university"),
        (r"^(?:degree specialization|field of study|major)$","degree_specialization"),
        (r"^(?:total|overall) (?:work |professional )?experience(?: in)? years$","experience_years"),
        (r"^(?:total|overall) (?:work |professional )?experience(?: in)? months$","experience_months"),
        (r"^(?:reason for (?:job )?change|why are you looking for a change|why are you leaving your current (?:job|company))$","reason_for_change"),
        (r"^(?:preferred employment type|employment type preference)$","preferred_employment_type"),
        (r"^(?:your |legal |full )?name$|^first and last name$","name"),
        (r"^(?:your |legal )?(?:first|given) name$","first_name"),
        (r"^(?:your |legal )?(?:last|family|sur) ?name$","last_name"),
        (r"^(?:your )?email(?: address)?$","email"),
        (r"^(?:your )?(?:phone|mobile)(?: number)?$","phone"),
        (r"^(?:what is your )?(?:preferred location|preferred city|preferred work location)$","preferred_location"),
        (r"^(?:are you )?(?:willing to relocate(?: within india)?|open to relocation(?: for this role)?)$","willing_to_relocate"),
                (r"^(?:what is your )?(?:current (?:ctc|annual salary|salary)|current annual salary|current ctc last drawn ctc)$","current_ctc_inr"),
        (r"^(?:what is your )?current (?:ctc|annual salary) (?:inr|in inr|in rupees|in rs|rs)$","current_ctc_inr"),
        (r"^(?:what is your )?(?:expected (?:ctc|annual salary|salary)|expected annual salary)$","expected_ctc_inr"),
        (r"^(?:what is your )?expected (?:ctc|annual salary) (?:inr|in inr|in rupees|in rs|rs)$","expected_ctc_inr"),
        (r"^(?:what is your )?current ctc (?:in )?lpa$","current_ctc_lpa"),
        (r"^(?:what is your )?expected ctc (?:in )?lpa$","expected_ctc_lpa"),
        (r"^(?:why are you interested in (?:this role|this position|this opportunity)|why do you want to join us|why are you interested|why this company|what interests you about [a-z0-9 ]+)$","interest_statement"),
        (r"^(?:what is your )?(?:current (?:company|employer|organization)|company name)$","current_company"),
        (r"^(?:what is your )?(?:current location|current city|city of residence|location|city)$","current_location"),
        (r"^(?:what is your )?(?:notice period|notice period in days|notice period days|how many days is your notice period)$","notice_period_days"),
                (r"^(?:how many years of )?relevant (?:work |professional )?experience(?: do you have| in years)?$|^(?:what is your )?total work experience in a similar role capacity$","experience_years"),
        (r"^(?:what is your )?(?:total (?:work |professional )?experience in years|total years of experience|years of professional experience|how many years of (?:total |professional |work )?experience do you have)$","experience_years"),
        (r"^(?:(?:what is )?your )?(?:linkedin profile|linkedin profile url|linkedin profile link|linkedin url)$","linkedin"),
        (r"^(?:what is your )?(?:github profile|github profile url|github url)$","github"),
        (r"^(?:what is your )?(?:highest qualification|highest educational qualification)$","education"),
        (r"^(?:will you now or in the future require sponsorship|do you (?:now or in the future )?require (?:visa |employment )?sponsorship|will you require sponsorship (?:now or in the future)?|do you require (?:us |u s )?visa sponsorship)$","requires_us_visa_sponsorship"),
        (r"^(?:do you have an offer in hand|do you currently have an offer in hand|offer in hand)$","offer_in_hand"),
        (r"^(?:are you willing to take (?:an? )?(?:online |technical )?assessment|are you willing to complete (?:an? )?(?:online |technical )?assessment|assessment consent)$","willing_to_take_assessments"),
        (r"^(?:can you provide (?:valid )?(?:india |indian )?(?:right to work|work authorization|work eligibility) (?:proof|documents?)|do you have (?:valid )?(?:india |indian )?(?:right to work|work authorization|work eligibility))$","can_provide_india_right_to_work_proof"),
    )
    for pattern,key in fields:
        if re.fullmatch(pattern,q) and profile.get(key) is not None and profile.get(key)!="":
            return profile[key]
    return None
def as_text(value):
    if isinstance(value,bool): return "Yes" if value else "No"
    return str(value)
def option_match(question, value, label, profile=None):
    q=normalize(question); v=normalize(value); l=normalize(label)
    if not v or not l: return False
    if l==v: return True
    if not (re.search(r"\b(?:location|city)\b",q) and l.startswith(v+" ")): return False
    country=normalize((profile or {}).get("country"))
    if country and len(l.split())>=3 and country not in l:
        return False
    return True
def field_question(field):
    return field.evaluate("""el => {
        const labels=Array.from(el.labels||[]).map(l=>l.innerText);
        const ids=(el.getAttribute('aria-labelledby')||'').split(/\\s+/).filter(Boolean);
        const aria=ids.map(id=>document.getElementById(id)?.innerText||'');
        const group=el.closest('fieldset');
        const legend=group?.querySelector('legend')?.innerText||'';
        const lever=el.closest(".application-question,.custom-question,.application-question-container,.application-question-group,[data-field-id],[data-qa*=question]");
        const prompt=lever?.querySelector("label:not([for]),.application-label,.application-question-label,.question-label,.application-question-title,legend,[role=heading]")?.innerText||"";
        return (el.getAttribute('aria-label')||aria.join(' ').trim()||labels.join(' ').trim()||legend||prompt||el.getAttribute('placeholder')||'').trim();
    }""")
def location_suggestion_matches(value, primary, label):
    parts = [normalize(x) for x in str(value).split(",") if normalize(x)]
    if not parts:
        return False
    if len(parts) > 1:
        return normalize(label) == " ".join(parts)
    return normalize(primary) == parts[0] or normalize(label) == parts[0]

def select_lever_location(page, profile, verification_required, diagnostic=None):
    """Use visible suggestions only. Diagnostic output contains counts, not candidate or option text."""
    trace = diagnostic if diagnostic is not None else {}
    trace.update({"field_count": 0, "dropdown_count": 0, "option_count": 0, "match_count": 0})
    def stop(reason, status="unresolved"):
        trace["result"] = reason
        return status
    field = page.locator('input.location-input[name="location"]:visible, input[name="location"][autocomplete]:visible')
    trace["field_count"] = field.count()
    if not trace["field_count"]:
        return stop("no_location_field", "not_present")
    if verification_required(page):
        return stop("challenge", "verification")
    if trace["field_count"] != 1:
        return stop("multiple_location_fields")
    value = answer_for("Current location", profile)
    if not isinstance(value, str) or not value.strip():
        return stop("missing_profile_answer")
    trace["qualified_answer"] = len(value.split(",")) > 1
    if not field.is_enabled() or field.get_attribute("readonly") is not None:
        return stop("field_not_editable")
    city = value.split(",")[0].strip()
    if not city:
        return stop("missing_city")
    field.click()
    if verification_required(page):
        return stop("challenge", "verification")
    field.fill("")
    field.press_sequentially(city, delay=100)
    for _ in range(48):
        if verification_required(page):
            return stop("challenge", "verification")
        dropdown = page.locator(".pac-container:visible")
        mode = "places"
        if dropdown.count() == 0:
            controls = field.get_attribute("aria-controls") or field.get_attribute("aria-owns")
            if controls:
                dropdown = page.locator('[role=listbox]:visible').filter(has=page.locator('[role=option]'))
                if dropdown.count() != 1 or dropdown.get_attribute("id") != controls:
                    dropdown = page.locator(".pac-container:visible")
                else:
                    mode = "aria"
        trace["dropdown_count"] = max(trace["dropdown_count"], dropdown.count())
        if dropdown.count() == 1:
            options = dropdown.locator(".pac-item:visible") if mode == "places" else dropdown.get_by_role("option")
            trace["option_count"] = max(trace["option_count"], options.count())
            matches = []
            for i in range(options.count()):
                opt = options.nth(i)
                if not opt.is_visible() or not opt.is_enabled():
                    continue
                primary = opt.locator(".pac-item-query")
                primary_text = primary.inner_text() if primary.count() == 1 else ""
                label = opt.evaluate("el => Array.from(el.querySelectorAll(':scope > span')).map(s => s.innerText.trim()).filter(Boolean).join(' ') || el.innerText")
                if location_suggestion_matches(value, primary_text, label) or location_suggestion_matches(value, primary_text, opt.inner_text()):
                    matches.append(opt)
            trace["match_count"] = max(trace["match_count"], len(matches))
            if len(matches) == 1:
                if verification_required(page):
                    return stop("challenge", "verification")
                matches[0].click()
                page.wait_for_timeout(500)
                if verification_required(page):
                    return stop("challenge", "verification")
                selected = field.input_value().strip()
                trace["selection_value_present"] = bool(selected)
                trace["dropdown_closed"] = dropdown.count() == 0
                if selected and trace["dropdown_closed"] and (not trace["qualified_answer"] or normalize(selected) == normalize(value)):
                    return stop("selected", "selected")
                return stop("selection_not_confirmed")
            if len(matches) > 1:
                return stop("multiple_matching_options")
        page.wait_for_timeout(250)
    if verification_required(page):
        return stop("challenge", "verification")
    if trace["option_count"]:
        return stop("no_matching_option")
    return stop("no_visible_options")

def fill_screening(page,profile):
    fields=page.locator('input:visible:not([type=hidden]):not([type=submit]):not([type=button]):not([type=file]):not([type=checkbox]):not([type=radio]), textarea:visible, select:visible')
    filled=0
    for i in range(fields.count()):
        field=fields.nth(i)
        if not field.is_enabled() or field.get_attribute("readonly") is not None: continue
        tag=field.evaluate("el => el.tagName.toLowerCase()")
        if field.input_value().strip() and tag!="select": continue
        if field.get_attribute("role")=="combobox": continue
        question=field_question(field)
        answer=answer_for(question,profile)
        if answer is None: continue
        value=as_text(answer)
        if field.get_attribute("type")=="date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}",value): continue
        if tag=="select":
            options=field.locator("option").evaluate_all("els => els.map(e => ({label:e.textContent.trim(), value:e.value, disabled:e.disabled}))")
            choices=[o for o in options if not o["disabled"] and o["value"] and option_match(question,value,o["label"],profile)]
            if len(choices)!=1: continue
            field.select_option(value=choices[0]["value"])
        else:
            field.fill(value)
        filled+=1
    radios=page.locator('fieldset:visible, [role=radiogroup]:visible, .application-question:visible, .application-field:visible')
    for i in range(radios.count()):
        group=radios.nth(i)
        legend=group.locator("legend")
        if group.get_by_role("radio").count()==0: continue
        question=legend.inner_text() if legend.count()==1 else field_question(group)
        if not question:
            labels=group.locator(".application-label,.application-question-label,.question-label,.application-question-title")
            if labels.count()==1: question=labels.inner_text()
        answer=answer_for(question,profile)
        if answer is None: continue
        names=[as_text(answer)]
        if isinstance(answer,bool): names.extend(["True"] if answer else ["False"])
        options=None
        for candidate in names:
            found=group.get_by_role("radio",name=re.compile(r"^"+re.escape(candidate)+r"$",re.I))
            if found.count()==1:
                options=found; break
        if options is not None and options.is_enabled() and not options.is_checked():
            options.check()
            filled+=1
    checks=page.locator('input[type=checkbox]:visible')
    for i in range(checks.count()):
        field=checks.nth(i)
        if not field.is_enabled(): continue
        # Only explicitly supplied Boolean answers authorize checking a box.
        question=field_question(field)
        explicit=profile.get("screening_answers",{})
        answer=next((v for k,v in explicit.items() if normalize(k)==normalize(question) and isinstance(v,bool)),None) if isinstance(explicit,dict) and question else None
        if answer is not None and field.is_checked()!=answer:
            field.set_checked(answer)
            filled+=1
    combos=page.locator('[role=combobox]:visible:not(select)')
    for i in range(combos.count()):
        field=combos.nth(i)
        question=field_question(field)
        answer=answer_for(question,profile)
        if answer is None or not field.is_enabled(): continue
        # Select only an unambiguous exact visible option from the linked listbox.
        controls=field.get_attribute("aria-controls")
        if not controls:
            if re.search(r"\b(?:location|city)\b",normalize(question)):
                field.fill(as_text(answer))
                field.press("Tab")
                filled+=1
            continue
        field.click()
        scope=page.locator('[role=listbox]:visible')
        if scope.count()!=1 or scope.get_attribute("id")!=controls:
            field.press("Escape"); continue
        options=scope.get_by_role("option")
        matches=[]
        for j in range(options.count()):
            opt=options.nth(j)
            if opt.is_visible() and opt.is_enabled() and option_match(question,answer,opt.inner_text(),profile):
                matches.append(opt)
        if len(matches)==1:
            matches[0].click()
            filled+=1
        else:
            field.press("Escape")
    return filled

def unanswered_required(page):
    """Return field labels only; never return input values or candidate secrets."""
    return page.locator('input:visible[required],textarea:visible[required],select:visible[required], [aria-required=true]:visible').evaluate_all("""els => {
        const missing=[];
        const visited=new Set();
        for(const el of els){
            if(el.disabled||el.readOnly||el.type==='file'||el.type==='hidden') continue;
            let empty=false;
            if(el.type==='radio'){
                const group=Array.from(document.querySelectorAll('input[type=radio]')).filter(x=>x.name===el.name&&x.form===el.form);
                empty=!group.some(x=>x.checked);
            }else if(el.type==='checkbox') empty=!el.checked;
            else if(el.getAttribute('role')==='combobox'&&el.tagName!=='SELECT') empty=!el.value && !el.getAttribute('aria-valuetext') && !el.querySelector('[aria-selected=true]');
            else if('value' in el) empty=!String(el.value||'').trim();
            else empty=true;
            if(!empty) continue;
            const legend=el.closest('fieldset')?.querySelector('legend')?.innerText;
            const labels=Array.from(el.labels||[]).map(l=>l.innerText).join(' ');
            const aria=(el.getAttribute('aria-labelledby')||'').split(/\\s+/).map(id=>document.getElementById(id)?.innerText||'').join(' ');
            const wrapper=el.closest('.application-question,.custom-question,.application-question-container,.application-question-group,[data-field-id],[data-qa*=question]');
            const prompt=wrapper?.querySelector('label:not([for]),.application-label,.application-question-label,.question-label,.application-question-title,legend,[role=heading]')?.innerText;
            const groupPrompt=(el.type==='radio'||el.type==='checkbox') ? prompt : '';
            const label=(legend||groupPrompt||el.getAttribute('aria-label')||aria.trim()||labels||prompt||el.getAttribute('placeholder')||el.name||'Unlabeled required field').replace(/\\s+/g,' ').trim().slice(0,180);
            if(!visited.has(label)){visited.add(label);missing.push(label)}
        }
        return missing.slice(0,30);
    }""")
