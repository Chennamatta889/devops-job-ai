"""One requested assisted-application pilot. No automatic submit."""
from datetime import datetime, timezone
import json
import requests
from supabase_worker import (rest_get, headers, base_url, get_profile, get_resume,
    download_resume, get_screening_answers, enrich_matching_profile, _list,
    patch_attempt, fetch_public_json, PUBLIC_JOB_FEED_URL, match_score, CONSENT_VERSION)
from cloud_handoff import prepare_handoff, SteelSessions, HandoffError
TABLE="mobile_handoff_requests"
def update(id, expected, values):
    response=requests.patch(f"{base_url()}/rest/v1/{TABLE}",
        params={"attempt_id":f"eq.{id}","status":f"eq.{expected}"},
        headers=headers({"Prefer":"return=representation"}),
        data=json.dumps(values),timeout=25)
    response.raise_for_status()
    return response.json()
def main():
    rows=rest_get(TABLE,{"status":"eq.REQUESTED","select":"attempt_id","limit":"2"})
    if len(rows)!=1:
        print("Exactly one private request required; no action.")
        return
    id=int(rows[0]["attempt_id"])
    if not update(id,"REQUESTED",{"status":"PREPARING"}): return
    client=None
    handoff=None
    published=False
    try:
        attempts=rest_get("application_attempts",{"id":f"eq.{id}","status":"eq.HANDOFF_REQUESTED","select":"*","limit":"1"})
        if len(attempts)!=1: raise HandoffError("request_not_found")
        attempt=attempts[0]
        if not patch_attempt(id,"HANDOFF_REQUESTED",{"status":"HANDOFF_PREPARING","message":"Preparing one requested mobile application."}):
            raise HandoffError("attempt_claim_failed")
        uid=attempt["user_id"]
        profile=get_profile(uid)
        if not profile or not profile.get("auto_apply_enabled") or profile.get("consent_version")!=CONSENT_VERSION:
            raise HandoffError("candidate_consent_unavailable")
        job=next((j for j in fetch_public_json(PUBLIC_JOB_FEED_URL).get("jobs",[]) if j.get("id")==attempt["external_job_id"] and j.get("url")==attempt["apply_url"]),None)
        if not job or not job.get("auto_apply_supported"): raise HandoffError("job_unavailable")
        resume=get_resume(uid)
        if not resume: raise HandoffError("resume_required")
        candidate=enrich_matching_profile(profile)
        score=match_score(job,candidate)
        candidate["screening_answers"]=get_screening_answers(uid)
        for key in ("target_roles","skills","preferred_locations"):
            candidate[key]=", ".join(_list(candidate.get(key)))
        pdf=download_resume(resume["storage_path"])
        client=SteelSessions()
        handoff=prepare_handoff(job,candidate,pdf,consent=True,client=client)
        if not update(id,"PREPARING",{"status":"READY","viewer_url":handoff.viewer_url,
            "expires_at":handoff.expires_at.isoformat(),"reason":handoff.reason,
            "resume_attached":handoff.resume_attached,"fields_filled":handoff.fields_filled}):
            raise HandoffError("private_handoff_record_failed")
        published=True
        patch_attempt(id,"HANDOFF_PREPARING",{"status":"ASSISTANCE_REQUIRED","match_score":score,
            "message":f"Live mobile session prepared. {handoff.fields_filled} supported fields filled; resume attachment detected: {'yes' if handoff.resume_attached else 'no'}. Review and submit yourself. Session expires shortly.",
            "updated_at":datetime.now(timezone.utc).isoformat()})
        print("Mobile handoff ready; no automated submission. Check the private dashboard.")
    except Exception as exc:
        reason=str(exc) if isinstance(exc,HandoffError) else type(exc).__name__
        if not published:
            if handoff and client:
                try: client.release(handoff.session_id)
                except Exception: pass
            try: update(id,"PREPARING",{"status":"FAILED","reason":reason[:100]})
            except Exception: pass
            try: patch_attempt(id,"HANDOFF_PREPARING",{"status":"REVIEW_REQUIRED","message":"Mobile handoff failed; no automatic submission. "+reason[:100]})
            except Exception: pass
        print("Handoff pilot error:",reason[:100])
        raise SystemExit(1) from None
if __name__=="__main__": main()
