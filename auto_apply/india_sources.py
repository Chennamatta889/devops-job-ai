"""India-focused public career discovery. No authentication or paid API."""
import json, re
from urllib.request import Request, urlopen
from urllib.parse import quote, urlencode
from concurrent.futures import ThreadPoolExecutor
INDIA = re.compile(r"\b(india|hyderabad|secunderabad|bengaluru|bangalore|pune|mumbai|navi mumbai|chennai|gurgaon|gurugram|noida|delhi|kolkata|ahmedabad|kochi|cochin|trivandrum|thiruvananthapuram|coimbatore|mysore|mysuru|indore|jaipur|chandigarh|mohali|bhubaneswar|visakhapatnam|vizag|vadodara|nagpur|lucknow|surat|greater noida|telangana|karnataka|maharashtra|tamil nadu|kerala|gujarat|haryana|uttar pradesh|west bengal|andhra pradesh)\b",re.I)
ROLE = re.compile(r"\b(dev[- ]?ops|devsecops|site reliability|sre|cloud[- ]?ops|cloud (?:engineer|platform|infrastructure|operations|support|administrator)|platform (?:engineer|operations)|(?:it |cloud )?infrastructure (?:engineer|specialist|analyst)|(?:build|release|deployment|production support|production|systems|linux|observability|kubernetes) engineer|(?:devops|cloud|infrastructure) automation engineer|ci/cd engineer)\b",re.I)
def india_location(value):
    return bool(INDIA.search(str(value or "")))
def relevant_role(value):
    return bool(ROLE.search(str(value or "")))
def read(url):
    with urlopen(Request(url,headers={"User-Agent":"IndiaJobAgent/1.0","Accept":"application/json"}),timeout=18) as r:
        return json.load(r)
def ashby(board):
    data=read("https://api.ashbyhq.com/posting-api/job-board/"+quote(board))
    jobs=[]
    for j in data.get("jobs",[]):
        loc=" | ".join([str(j.get("location",""))]+[str(x.get("location","")) for x in j.get("secondaryLocations",[])])
        country=str((j.get("address") or {}).get("postalAddress",{}).get("addressCountry",""))
        if country.lower() in ("in","india"): loc+=" | India"
        if not india_location(loc) or not relevant_role(j.get("title")) or j.get("isListed") is False: continue
        jobs.append(dict(company=board,title=j["title"],location=loc,description=j.get("descriptionPlain") or j.get("descriptionHtml",""),url=j.get("jobUrl",""),apply_url=j.get("applyUrl",""),published=j.get("publishedAt",""),source="ashby"))
    return jobs
def smart(board):
    base="https://api.smartrecruiters.com/v1/companies/"+quote(board)+"/postings"
    jobs=[]; seen=set()
    for q in ("DevOps","Cloud Engineer","Site Reliability","Platform Engineer","Infrastructure Engineer","Release Engineer"):
        try:
            items=read(base+"?"+urlencode({"country":"in","q":q,"limit":25})).get("content",[])
        except Exception: continue
        for j in items:
            ident=str(j.get("id",""))
            if not ident or ident in seen or not relevant_role(j.get("name")): continue
            seen.add(ident)
            loc=j.get("location") or {}
            if str(loc.get("country","")).lower() not in ("in","india") and not india_location(" ".join(str(loc.get(k,"")) for k in ("city","region"))): continue
            try:
                detail=read(base+"/"+quote(ident))
            except Exception: continue
            sections=(detail.get("jobAd") or {}).get("sections") or {}
            body=" ".join(str(sections.get(k,{}).get("text","")) for k in ("jobDescription","qualifications","additionalInformation"))
            if not body.strip(): continue
            jobs.append(dict(company=(j.get("company") or {}).get("name",board),title=j["name"],location=" | ".join([str(loc.get("city","")),str(loc.get("region","")),"India"]),description=body,url="https://jobs.smartrecruiters.com/"+quote(board)+"/"+quote(ident),published=j.get("releasedDate",""),source="smartrecruiters"))
    return jobs
def discover():
    boards=[("ashby",b) for b in ("buspatrol","gradera","openobserve-careers","sarvam","encord","opendr","outmarket","uptimeai","dehazelabs","playpowerlabs","apas","demandbase","plane","sophos","triomics","ema","redis")]+[("smartrecruiters",b) for b in ("BoschGroup","Experian","ServiceNow","Nagarro1","ifs1","Sia","NielsenIQ","Eurofins","Xplor")]
    def run(item):
        kind,board=item
        try:
            rows=(ashby if kind=="ashby" else smart)(board)
            print("India source:",kind,board,"target jobs:",len(rows))
            return rows
        except Exception as exc:
            print("India source unavailable:",kind,board,type(exc).__name__)
            return []
    with ThreadPoolExecutor(max_workers=5) as pool:
        return [j for rows in pool.map(run,boards) for j in rows]
