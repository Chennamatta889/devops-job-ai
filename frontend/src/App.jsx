import { useEffect, useMemo, useRef, useState } from 'react'

const FEED_URL =
  import.meta.env.VITE_JOB_FEED_URL ||
  (import.meta.env.BASE_URL + 'data/jobs.json')

const AUTO_APPLY_API_URL = (import.meta.env.VITE_AUTO_APPLY_API_URL || '').replace(/\/$/, '')
const VERIFICATION_STATUS_URL =
  import.meta.env.VITE_VERIFICATION_STATUS_URL ||
  (import.meta.env.BASE_URL + 'data/verification-status.json')

const SUPABASE_URL = (
  import.meta.env.VITE_SUPABASE_URL ||
  'https://badjbyxuvrasdwjgkzkl.supabase.co'
).replace(/\/$/, '')
const SUPABASE_PUBLISHABLE_KEY =
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY ||
  'sb_publishable_2hZDKpj2Y0CoNnzMoMtSwQ_PZ0wlWUP'
const SUPABASE_READY = Boolean(
  SUPABASE_URL &&
  SUPABASE_PUBLISHABLE_KEY &&
  typeof window !== 'undefined' &&
  window.supabase?.createClient
)
const supabaseClient = SUPABASE_READY
  ? window.supabase.createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)
  : null
const AUTO_APPLY_CONSENT_VERSION = '2026-11-v1'

function prettySource(value = '') {
  const names = {
    greenhouse: 'Greenhouse',
    lever: 'Lever',
    ashby: 'Ashby',
    smartrecruiters: 'SmartRecruiters',
    recruitee: 'Recruitee',
    linkedin_alert: 'LinkedIn',
    naukri_alert: 'Naukri',
    indeed_alert: 'Indeed',
    foundit_alert: 'Foundit'
  }
  return names[value] || value.replaceAll('_', ' ') || 'Career site'
}

function prettyCompany(value = '') {
  return value
    .replace(/[-_]+/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function daysSince(value) {
  if (!value) return Infinity
  const time = new Date(value).getTime()
  if (Number.isNaN(time)) return Infinity
  return (Date.now() - time) / 86400000
}

function formatDate(value) {
  if (!value) return 'Recently discovered'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Recently discovered'
  return new Intl.DateTimeFormat('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric'
  }).format(date)
}

const EXPERIENCE_OPTIONS = [
  { value: 'all', label: 'All experience' },
  { value: '0-1', label: '0-1 years', min: 0, max: 1 },
  { value: '2-3', label: '2-3 years', min: 2, max: 3 },
  { value: '3-4', label: '3-4 years', min: 3, max: 4 },
  { value: '4-6', label: '4-6 years', min: 4, max: 6 },
  { value: '6+', label: '6+ years', min: 6, max: Infinity },
  { value: 'unspecified', label: 'Not specified' }
]

function experienceMatches(job, selected) {
  if (selected === 'all') return true
  const min = Number.isFinite(job.experience_min) ? job.experience_min : null
  const max = Number.isFinite(job.experience_max) ? job.experience_max : null
  if (selected === 'unspecified') return min === null
  if (min === null) return false
  const option = EXPERIENCE_OPTIONS.find((item) => item.value === selected)
  if (!option) return true
  const jobMax = max === null ? Infinity : max
  return min <= option.max && jobMax >= option.min
}


const SKILL_RULES = [["AWS","aws|amazon web services"],["Azure","azure"],["GCP","gcp|google cloud"],["Jenkins","jenkins"],["OpenShift","openshift|ocp"],["Docker","docker"],["Kubernetes","kubernetes|k8s"],["Terraform","terraform"],["Linux","linux"],["Python","python"],["Bash","bash"],["PowerShell","powershell"],["GitHub Actions","github actions"],["Git","git"],["CI/CD","ci\\s*[/\\-]\\s*cd|continuous integration|continuous delivery"],["IAM","iam"],["Ansible","ansible"],["Prometheus","prometheus"],["Grafana","grafana"],["ArgoCD","argo\\s*cd"],["JFrog","jfrog|artifactory"],["Dynatrace","dynatrace"],["Splunk","splunk"],["Java","java"],["Spring Boot","spring boot"],[".NET","\\.net|dotnet"],["C#","c#"],["JavaScript","javascript"],["TypeScript","typescript"],["React","react"],["Node.js","node\\.?js"],["SQL","sql"],["PostgreSQL","postgresql|postgres"],["MySQL","mysql"],["Redis","redis"],["Kafka","kafka"],["ETL","etl"],["Selenium","selenium"],["Playwright","playwright"],["Go","golang"]]
const ROLE_RULES = [["DevOps Engineer","devops"],["Site Reliability Engineer","site reliability engineer|\\bsre\\b"],["Cloud Engineer","cloud engineer|cloud devops"],["Platform Engineer","platform engineer"],["Infrastructure Engineer","infrastructure engineer"],[".NET Developer","\\.net developer|dotnet developer|c# developer"],["Java Developer","java developer"],["Frontend Developer","front[ -]?end (?:developer|engineer)"],["Backend Developer","back[ -]?end (?:developer|engineer)"],["Full Stack Developer","full[ -]?stack (?:developer|engineer)"],["QA Engineer","qa engineer|quality assurance engineer|software test engineer"],["Data Engineer","data engineer"]]
const splitList = (value) => String(value || '').split(',').map(x => x.trim()).filter(Boolean)
const mergeList = (a, b) => [...new Map([...a, ...b].map(x => [x.toLowerCase(), x])).values()]
function resumeSuggestions(text, profile) {
  const matches = (rules) => rules.filter(([, p]) => new RegExp('(?:^|[^a-z0-9])(?:' + p + ')(?=$|[^a-z0-9])', 'i').test(text)).map(([name]) => name)
  const skills = matches(SKILL_RULES)
  const roles = matches(ROLE_RULES)
  const existing = splitList(profile.target_roles)
  const generic = !existing.length || existing.every(r => /^(software engineer(?:ing)?|software developer|it professional)$/i.test(r))
  const cloud = roles.some(r => /devops|site reliability|cloud|platform|infrastructure/i.test(r))
  const relevantCloudSkills = skills.filter(x => /^(AWS|Azure|GCP|Jenkins|OpenShift|Docker|Kubernetes|Terraform|CI\/CD)$/i.test(x)).length
  if (generic && relevantCloudSkills >= 4 && !cloud) roles.push('DevOps Engineer')
  const experience = text.match(/(?:\b(?:over|nearly|approximately|around)\s+)?(\d+(?:\.\d+)?)\s*\+?\s*years?\s+(?:of\s+)?(?:professional\s+|total\s+|work\s+)?experience\b/i)
  return {skills: mergeList(splitList(profile.skills), skills).join(', '), target_roles: (generic && roles.length ? roles : existing).join(', '), years_experience: experience && Number(experience[1]) <= 50 ? experience[1] : profile.years_experience}
}
async function readResumeText(file) {
  const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs')
  const worker = await import('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url')
  pdfjs.GlobalWorkerOptions.workerSrc = worker.default
  const doc = await pdfjs.getDocument({data: new Uint8Array(await file.arrayBuffer()), isEvalSupported: false}).promise
  try {
    const pages = []
    for (let n = 1; n <= Math.min(doc.numPages, 20); n++) {
      const page = await doc.getPage(n)
      const content = await page.getTextContent()
      pages.push(content.items.map(item => item.str || '').join(' '))
    }
    return pages.join('\n')
  } finally { await doc.destroy() }
}

function App() {
  const [feed, setFeed] = useState({ jobs: [], count: 0, generated_at_utc: null })
  const [query, setQuery] = useState('')
  const [location, setLocation] = useState('')
  const [source, setSource] = useState('all')
  const [skill, setSkill] = useState('all')
  const [experience, setExperience] = useState('all')
  const [category, setCategory] = useState('all')
  const [postedWithin, setPostedWithin] = useState('30')
  const [verification, setVerification] = useState('all')
  const [visibleCount, setVisibleCount] = useState(40)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [copiedId, setCopiedId] = useState('')
  const [autoBusy, setAutoBusy] = useState(false)
  const [autoMessage, setAutoMessage] = useState('')
  const [testMatchSummary, setTestMatchSummary] = useState(null)
  const [autoConsent, setAutoConsent] = useState(false)
  const [resumeFile, setResumeFile] = useState(null)
  const [resumeReading, setResumeReading] = useState(false)
  const [resumeNotice, setResumeNotice] = useState('')
  const resumeSelection = useRef(0)
  const [authUser, setAuthUser] = useState(null)
  const [authEmail, setAuthEmail] = useState('')
  const [authBusy, setAuthBusy] = useState(false)
  const [authMessage, setAuthMessage] = useState('')
  const [applicationAttempts, setApplicationAttempts] = useState([])
  const [screeningAnswers, setScreeningAnswers] = useState({})
  const [screeningDrafts, setScreeningDrafts] = useState({})
  const [screeningCustom, setScreeningCustom] = useState('')
  const [screeningMessage, setScreeningMessage] = useState('')
  const [screeningBusy, setScreeningBusy] = useState(false)
  const [autoEnabled, setAutoEnabled] = useState(false)
  const [autoProfile, setAutoProfile] = useState({
    name: '',
    email: '',
    phone: '',
    linkedin: '',
    current_location: '',
    notice_period_days: '30',
    current_ctc_lpa: '',
    expected_ctc_lpa: '',
    years_experience: '3',
    target_roles: '',
    skills: '',
    preferred_locations: 'India',
    minimum_match_score: '80',
    daily_application_limit: '10'
  })

  async function loadJobs() {
    setLoading(true)
    setError('')
    try {
      const stamp = Date.now()
      const response = await fetch(FEED_URL + '?t=' + stamp, { cache: 'no-store' })
      if (!response.ok) throw new Error('Job feed returned ' + response.status)
      const data = await response.json()

      let verificationJobs = {}
      try {
        const verificationResponse = await fetch(VERIFICATION_STATUS_URL + '?t=' + stamp, { cache: 'no-store' })
        if (verificationResponse.ok) {
          const verificationData = await verificationResponse.json()
          verificationJobs = verificationData.jobs || {}
        }
      } catch {
        verificationJobs = {}
      }

      const jobs = (Array.isArray(data.jobs) ? data.jobs : []).map((job) => {
        const observation = verificationJobs[String(job.id || '')] || {}
        return {
          ...job,
          verification_status: observation.status || 'unknown',
          verification_checked_at_utc: observation.checked_at_utc || null
        }
      })
      setFeed({
        jobs,
        count: Number(data.count || 0),
        generated_at_utc: data.generated_at_utc || null
      })
    } catch (err) {
      setError(err.message + '. Please refresh in a moment.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadJobs()
  }, [])

  async function loadAutoApplyProfile() {
    if (!supabaseClient) return
    const { data, error: profileError } = await supabaseClient
      .from('candidate_profiles')
      .select('*')
      .maybeSingle()

    if (profileError || !data) {
      if (!profileError) setAutoEnabled(false)
      return
    }

    setAutoEnabled(Boolean(data.auto_apply_enabled))
    setAutoConsent(Boolean(data.auto_apply_enabled && data.consent_version === AUTO_APPLY_CONSENT_VERSION))
    setAutoProfile((current) => ({
      ...current,
      name: data.name || '',
      email: data.email || current.email || '',
      phone: data.phone || '',
      linkedin: data.linkedin || '',
      current_location: data.current_location || '',
      notice_period_days: data.notice_period_days == null ? '' : String(data.notice_period_days),
      current_ctc_lpa: data.current_ctc_lpa == null ? '' : String(data.current_ctc_lpa),
      expected_ctc_lpa: data.expected_ctc_lpa == null ? '' : String(data.expected_ctc_lpa),
      years_experience: data.years_experience == null ? current.years_experience : String(data.years_experience),
      target_roles: Array.isArray(data.target_roles) ? data.target_roles.join(', ') : '',
      skills: Array.isArray(data.skills) ? data.skills.join(', ') : '',
      preferred_locations: Array.isArray(data.preferred_locations) ? data.preferred_locations.join(', ') : 'India',
      minimum_match_score: String(data.minimum_match_score || 80),
      daily_application_limit: String(data.daily_application_limit || 10)
    }))
  }

  async function loadApplicationAttempts() {
    if (!supabaseClient) return
    const { data, error: attemptError } = await supabaseClient
      .from('application_attempts')
      .select('id,title,company,apply_url,match_score,status,message,created_at,updated_at')
      .order('created_at', { ascending: false })
      .limit(10)
    if (attemptError) return
    const attempts = Array.isArray(data) ? data : []
    const ids = attempts.filter(a => a.status === 'SUBMITTED').map(a => a.id)
    if (!ids.length) { setApplicationAttempts(attempts); return }
    const { data: evidence, error: evidenceError } = await supabaseClient
      .from('application_email_confirmations')
      .select('attempt_id,received_at')
      .in('attempt_id',ids)
    const byAttempt = new Map((evidence || []).map(row => [String(row.attempt_id), row.received_at]))
    setApplicationAttempts(attempts.map(a => ({
      ...a,
      email_confirmation: a.status !== 'SUBMITTED' ? null : evidenceError ? 'unavailable' : byAttempt.has(String(a.id)) ? 'confirmed' : 'pending',
      email_received_at: byAttempt.get(String(a.id)) || null
    })))
  }

  const missingScreeningQuestions = useMemo(() => [...new Set(applicationAttempts
    .filter(a => a.status === 'QUESTION_REQUIRED' && String(a.message || '').startsWith('Required information needed: '))
    .flatMap(a => a.message.slice('Required information needed: '.length).split('; ').map(q => q.trim()).filter(Boolean)))], [applicationAttempts])

  useEffect(() => {
    let active = true
    setScreeningAnswers({})
    setScreeningDrafts({})
    setScreeningMessage('')
    if (supabaseClient && authUser?.id) {
      supabaseClient.from('screening_answers').select('question,answer').eq('user_id',authUser.id)
        .then(({data,error}) => {
          if (!active) return
          if (error) { setScreeningMessage(error.message); return }
          setScreeningAnswers(Object.fromEntries((data || []).map(r => [r.question, typeof r.answer === 'boolean' ? (r.answer ? 'Yes' : 'No') : String(r.answer ?? '')])))
        })
    }
    return () => { active = false }
  }, [authUser?.id])

  async function saveScreeningAnswers() {
    if (!supabaseClient || !authUser?.id) return
    const changes = Object.entries(screeningDrafts).filter(([q,value]) => q.trim() && value.trim() && value.trim() !== screeningAnswers[q])
    if (!changes.length) { setScreeningMessage('Enter a new or updated answer first.'); return }
    setScreeningBusy(true)
    try {
      const rows = changes.map(([question, value]) => ({
        user_id:authUser.id, question, answer: value.trim(), updated_at:new Date().toISOString()
      }))
      const {error} = await supabaseClient.from('screening_answers').upsert(rows,{onConflict:'user_id,question'})
      if (error) throw error
      setScreeningAnswers(old=>({...old,...Object.fromEntries(changes.map(([q,v])=>[q,v.trim()]))}))
      setScreeningDrafts({})
      setScreeningMessage('Answers saved privately. Eligible applications blocked by missing answers can be retried by the scheduled worker.')
    } catch (err) { setScreeningMessage(err.message || 'Could not save answers.') }
    finally { setScreeningBusy(false) }
  }

  async function deleteScreeningAnswer(question) {
    if (!supabaseClient || !authUser?.id || screeningBusy) return
    setScreeningBusy(true)
    try {
      const {error} = await supabaseClient.from('screening_answers').delete().eq('user_id',authUser.id).eq('question',question)
      if(error) throw error
      setScreeningAnswers(old=>{const next={...old};delete next[question];return next})
      setScreeningDrafts(old=>{const next={...old};delete next[question];return next})
      setScreeningMessage('Answer removed.')
    } catch(err) { setScreeningMessage(err.message || 'Could not remove answer.') }
    finally {setScreeningBusy(false)}
  }

  useEffect(() => {
    if (!supabaseClient) return undefined
    let active = true

    supabaseClient.auth.getSession().then(({ data }) => {
      if (!active) return
      const user = data?.session?.user || null
      setAuthUser(user)
      if (user?.email) {
        setAuthEmail(user.email)
        setAutoProfile((current) => ({
          ...current,
          email: current.email || user.email
        }))
        loadAutoApplyProfile()
        loadApplicationAttempts()
      }
    })

    const { data: listener } = supabaseClient.auth.onAuthStateChange((_event, session) => {
      if (!active) return
      const user = session?.user || null
      setAuthUser(user)
      if (user?.email) {
        setAuthEmail(user.email)
        setAutoProfile((current) => ({
          ...current,
          email: current.email || user.email
        }))
        window.setTimeout(() => {
          loadAutoApplyProfile()
          loadApplicationAttempts()
        }, 0)
      } else {
        setApplicationAttempts([])
      }
    })

    return () => {
      active = false
      listener?.subscription?.unsubscribe()
    }
  }, [])

  async function sendSignInLink() {
    if (!supabaseClient) return
    const email = authEmail.trim()
    if (!email) {
      setAuthMessage('Enter your email address first.')
      return
    }
    setAuthBusy(true)
    setAuthMessage('')
    try {
      const { error: signInError } = await supabaseClient.auth.signInWithOtp({
        email,
        options: {
          emailRedirectTo: window.location.origin + import.meta.env.BASE_URL,
          shouldCreateUser: true
        }
      })
      if (signInError) throw signInError
      setAuthMessage('Sign-in link sent. Open it from your email to continue.')
    } catch (err) {
      setAuthMessage(err.message || 'Could not send the sign-in link.')
    } finally {
      setAuthBusy(false)
    }
  }

  async function signOutAutoApply() {
    if (!supabaseClient) return
    await supabaseClient.auth.signOut()
    setAuthUser(null)
    setApplicationAttempts([])
    setAutoEnabled(false)
    setAuthMessage('Signed out.')
  }

  async function pauseAutoApply() {
    if (!supabaseClient || !authUser?.id) return
    setAutoBusy(true)
    setAutoMessage('')
    try {
      const { error: pauseError } = await supabaseClient
        .from('candidate_profiles')
        .update({
          auto_apply_enabled: false,
          updated_at: new Date().toISOString()
        })
        .eq('user_id', authUser.id)
      if (pauseError) throw pauseError
      setAutoEnabled(false)
      setAutoConsent(false)
      setAutoMessage('Auto Apply paused. Existing completed applications are unchanged; no new jobs will be queued.')
    } catch (err) {
      setAutoMessage(err.message || 'Could not pause Auto Apply.')
    } finally {
      setAutoBusy(false)
    }
  }

  const sourceOptions = useMemo(
    () => [
      ...new Set(
        feed.jobs.flatMap((job) => [
          job.source,
          ...(Array.isArray(job.discovered_via) ? job.discovered_via : [])
        ]).filter(Boolean)
      )
    ].sort(),
    [feed.jobs]
  )

  const categoryOptions = useMemo(
    () => [...new Set(feed.jobs.map((job) => job.category).filter(Boolean))].sort(),
    [feed.jobs]
  )

  const skillOptions = useMemo(
    () =>
      [...new Set(feed.jobs.flatMap((job) => (Array.isArray(job.skills) ? job.skills : [])))]
        .filter(Boolean)
        .sort(),
    [feed.jobs]
  )

  const normalizedSource = source === 'all' || sourceOptions.includes(source) ? source : 'all'
  const normalizedSkill = skill === 'all' || skillOptions.includes(skill) ? skill : 'all'
  const normalizedExperience = EXPERIENCE_OPTIONS.some((item) => item.value === experience)
    ? experience
    : 'all'
  const normalizedCategory = category === 'all' || categoryOptions.includes(category) ? category : 'all'
  const normalizedPosted = ['1', '3', '7', '14', '30'].includes(postedWithin) ? postedWithin : '30'

  useEffect(() => {
    setVisibleCount(40)
  }, [query, location, normalizedSource, normalizedSkill, normalizedExperience, normalizedCategory, normalizedPosted, verification])

  const filteredJobs = useMemo(() => {
    const q = query.trim().toLowerCase()
    const loc = location.trim().toLowerCase()

    return feed.jobs.filter((job) => {
      const title = String(job.title || '').toLowerCase()
      const company = String(job.company || '').toLowerCase()
      const jobLocation = String(job.location || '').toLowerCase()
      const skills = Array.isArray(job.skills) ? job.skills : []

      if (q && !title.includes(q) && !company.includes(q) && !skills.some((item) => item.includes(q))) {
        return false
      }
      if (loc && !jobLocation.includes(loc)) return false
      const discoveredVia = Array.isArray(job.discovered_via) ? job.discovered_via : []
      if (normalizedSource !== 'all' && job.source !== normalizedSource && !discoveredVia.includes(normalizedSource)) return false
      if (normalizedCategory !== 'all' && job.category !== normalizedCategory) return false
      if (normalizedSkill !== 'all' && !skills.includes(normalizedSkill)) return false
      if (!experienceMatches(job, normalizedExperience)) return false
      if (verification !== 'all' && (job.verification_status || 'unknown') !== verification) return false
      if (daysSince(job.published) > Number(normalizedPosted)) return false
      return true
    })
  }, [feed.jobs, query, location, normalizedSource, normalizedCategory, normalizedSkill, normalizedExperience, normalizedPosted, verification])

  const visibleJobs = filteredJobs.slice(0, visibleCount)

  function saveResumeInBrowser(file) {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open('draftflowai-test', 1)
      request.onupgradeneeded = () => {
        const db = request.result
        if (!db.objectStoreNames.contains('resumes')) db.createObjectStore('resumes')
      }
      request.onerror = () => reject(request.error)
      request.onsuccess = () => {
        const db = request.result
        const tx = db.transaction('resumes', 'readwrite')
        tx.objectStore('resumes').put(file, 'active-resume')
        tx.oncomplete = () => {
          db.close()
          resolve()
        }
        tx.onerror = () => {
          db.close()
          reject(tx.error)
        }
      }
    })
  }

  function scoreProfileJobs(profile) {
    const roles = String(profile.target_roles || '')
      .split(',')
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean)
    const skills = new Set(
      String(profile.skills || '')
        .split(',')
        .map((item) => item.trim().toLowerCase())
        .filter(Boolean)
    )
    const years = Number(profile.years_experience || 0)
    const seniorTitle = /\b(senior|sr\.?|staff|lead|principal|manager|architect|director|head)\b/i
    const cloudTerms = ['cloud', 'devops', 'sre', 'site reliability', 'platform', 'infrastructure', 'kubernetes', 'release', 'build']
    const wantsCloudFamily = roles.some((role) => cloudTerms.some((term) => role.includes(term) || term.includes(role)))

    function roleMatches(job) {
      const title = String(job.title || '').toLowerCase()
      const category = String(job.category || '').toLowerCase()
      if (wantsCloudFamily && category === 'cloud / devops / sre') return true
      return roles.some((role) => {
        if (title.includes(role) || role.includes(title)) return true
        const roleTokens = new Set(role.split(/\s+/).filter((token) => token.length > 2))
        const titleTokens = new Set(title.split(/\s+/).filter((token) => token.length > 2))
        const overlap = [...roleTokens].filter((token) => titleTokens.has(token)).length
        return roleTokens.size > 0 && overlap / roleTokens.size >= 0.5
      })
    }

    function experienceFits(job) {
      if (!Number.isFinite(job.experience_min)) return true
      return Number(job.experience_min) <= years + 0.5
    }

    return feed.jobs
      .filter((job) => {
        if (!roleMatches(job) || !experienceFits(job)) return false
        if (years < 4 && seniorTitle.test(String(job.title || ''))) return false
        return true
      })
      .map((job) => {
        const jobSkills = (job.skills || []).map((item) => String(item).toLowerCase())
        const matchedSkills = jobSkills.filter((item) => skills.has(item)).length
        const skillScore = jobSkills.length ? Math.round((matchedSkills / jobSkills.length) * 35) : 12
        const experienceScore = Number.isFinite(job.experience_min) && Number(job.experience_min) > years ? 10 : 15
        const score = Math.min(100, 45 + skillScore + experienceScore + 5)
        return { job, score }
      })
      .sort((a, b) => b.score - a.score)
  }

  function previewMatchSummary(profile) {
    const threshold = Number(profile.minimum_match_score || 80)
    const scored = scoreProfileJobs(profile)
    return {
      relevant: scored.length,
      strong: scored.filter(({ score }) => score >= threshold).length,
      autoEligible: scored.filter(({ job, score }) =>
        job.direct_apply && job.auto_apply_supported &&
        job.verification_status === 'no_verification_detected' &&
        score >= threshold
      ).length,
      verificationPending: scored.filter(({job, score}) => job.direct_apply && job.auto_apply_supported && score >= threshold && job.verification_status !== 'no_verification_detected').length,
      belowThreshold: scored.filter(({score}) => score < threshold).length
    }
  }

  function updateAutoProfile(field, value) {
    setAutoProfile((current) => ({ ...current, [field]: value }))
  }

  async function chooseResume(file) {
    const selection = ++resumeSelection.current
    setResumeFile(file || null)
    setResumeNotice('')
    setResumeReading(false)
    if (!file || file.size > 6 * 1024 * 1024 || !file.name.toLowerCase().endsWith('.pdf')) return
    setResumeReading(true)
    try {
      const text = await readResumeText(file)
      if (selection !== resumeSelection.current) return
      if (!text.trim()) throw new Error('No selectable text')
      setAutoProfile(current => ({...current, ...resumeSuggestions(text, current)}))
      setResumeNotice('Resume analyzed privately. Review the suggested roles, skills and experience before enabling Auto Apply.')
    } catch {
      if (selection === resumeSelection.current) setResumeNotice('Could not read this PDF automatically. Enter roles and skills manually or upload a text-based PDF.')
    } finally {
      if (selection === resumeSelection.current) setResumeReading(false)
    }
  }

  async function enableAutoApply(event) {
    event.preventDefault()
    setAutoMessage('')
    if (!resumeFile) {
      setAutoMessage('Choose a PDF resume first.')
      return
    }
    if (!autoConsent) {
      setAutoMessage('Please authorize automatic submission before enabling Auto Apply.')
      return
    }

    if (resumeFile.type !== 'application/pdf' && !resumeFile.name.toLowerCase().endsWith('.pdf')) {
      setAutoMessage('Please choose a PDF resume.')
      return
    }
    if (resumeFile.size > 6 * 1024 * 1024) {
      setAutoMessage('Resume must be 6 MB or smaller.')
      return
    }

    setAutoBusy(true)
    try {
      if (supabaseClient) {
        if (!authUser?.id) throw new Error('Sign in before enabling Auto Apply.')

        const userId = authUser.id
        const roles = String(autoProfile.target_roles || '').split(',').map((item) => item.trim()).filter(Boolean)
        const skills = String(autoProfile.skills || '').split(',').map((item) => item.trim()).filter(Boolean)
        const locations = String(autoProfile.preferred_locations || '').split(',').map((item) => item.trim()).filter(Boolean)
        const toNumberOrNull = (value) => String(value || '').trim() === '' ? null : Number(value)

        const profilePayload = {
          user_id: userId,
          name: autoProfile.name.trim(),
          email: autoProfile.email.trim() || authUser.email || '',
          phone: autoProfile.phone.trim(),
          linkedin: autoProfile.linkedin.trim(),
          current_location: autoProfile.current_location.trim(),
          years_experience: Number(autoProfile.years_experience || 0),
          target_roles: roles,
          skills,
          preferred_locations: locations.length ? locations : ['India'],
          notice_period_days: toNumberOrNull(autoProfile.notice_period_days),
          current_ctc_lpa: toNumberOrNull(autoProfile.current_ctc_lpa),
          expected_ctc_lpa: toNumberOrNull(autoProfile.expected_ctc_lpa),
          minimum_match_score: Number(autoProfile.minimum_match_score || 80),
          daily_application_limit: Number(autoProfile.daily_application_limit || 10),
          auto_apply_enabled: false,
          consent_version: '',
          consented_at: null,
          updated_at: new Date().toISOString()
        }

        const { error: profileError } = await supabaseClient
          .from('candidate_profiles')
          .upsert(profilePayload, { onConflict: 'user_id' })
        if (profileError) throw profileError

        const safeName = resumeFile.name.replace(/[^A-Za-z0-9._-]+/g, '-').slice(-120) || 'resume.pdf'
        const storagePath = userId + '/' + Date.now() + '-' + safeName
        const { error: uploadError } = await supabaseClient.storage
          .from('resumes')
          .upload(storagePath, resumeFile, {
            contentType: 'application/pdf',
            upsert: false
          })
        if (uploadError) throw uploadError

        const { error: deactivateError } = await supabaseClient
          .from('resume_variants')
          .update({ active: false, updated_at: new Date().toISOString() })
          .eq('user_id', userId)
          .eq('active', true)
        if (deactivateError) throw deactivateError

        const { error: resumeError } = await supabaseClient
          .from('resume_variants')
          .insert({
            user_id: userId,
            filename: safeName,
            storage_path: storagePath,
            content_type: 'application/pdf',
            resume_text: '',
            target_roles: roles,
            skills,
            years_experience: Number(autoProfile.years_experience || 0),
            active: true
          })
        if (resumeError) throw resumeError

        const { error: enableError } = await supabaseClient
          .from('candidate_profiles')
          .update({
            auto_apply_enabled: true,
            consent_version: AUTO_APPLY_CONSENT_VERSION,
            consented_at: new Date().toISOString(),
            updated_at: new Date().toISOString()
          })
          .eq('user_id', userId)
        if (enableError) throw enableError

        await loadApplicationAttempts()
        setAutoEnabled(true)
        setTestMatchSummary(previewMatchSummary(autoProfile))
        const summary = previewMatchSummary(autoProfile)
        setAutoMessage('Auto Apply enabled securely. ' + summary.autoEligible + ' eligible matches; the scheduled worker will queue new matches within your daily limit. ' + summary.verificationPending + ' strong supported matches await verification or require manual action.')
        return
      }

      if (!AUTO_APPLY_API_URL) {
        await saveResumeInBrowser(resumeFile)
        localStorage.setItem('draftflowai-test-profile', JSON.stringify(autoProfile))
        const summary = previewMatchSummary(autoProfile)
        setTestMatchSummary(summary)
        setAutoMessage(
          `Test resume saved privately in this browser only. Found ${summary.relevant} relevant jobs, ${summary.strong} strong matches, and ${summary.autoEligible} currently auto-apply eligible jobs. No application was submitted.`
        )
        return
      }

      const profileResponse = await fetch(AUTO_APPLY_API_URL + '/auto-apply/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...autoProfile,
          years_experience: Number(autoProfile.years_experience),
          minimum_match_score: Number(autoProfile.minimum_match_score),
          daily_application_limit: Number(autoProfile.daily_application_limit)
        })
      })
      if (!profileResponse.ok) throw new Error((await profileResponse.json()).detail || 'Could not save profile')

      const resumeData = new FormData()
      resumeData.append('file', resumeFile)
      resumeData.append('target_roles', autoProfile.target_roles)
      resumeData.append('skills', autoProfile.skills)
      resumeData.append('years_experience', autoProfile.years_experience)
      const resumeResponse = await fetch(AUTO_APPLY_API_URL + '/auto-apply/resumes', {
        method: 'POST',
        body: resumeData
      })
      if (!resumeResponse.ok) throw new Error((await resumeResponse.json()).detail || 'Could not upload resume')

      const enableResponse = await fetch(AUTO_APPLY_API_URL + '/auto-apply/enable', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ authorize: true })
      })
      if (!enableResponse.ok) throw new Error((await enableResponse.json()).detail || 'Could not enable Auto Apply')

      setAutoMessage('Auto Apply enabled. Matching supported ATS jobs can now be submitted automatically within your daily limit.')
    } catch (err) {
      setAutoMessage(err.message || 'Could not enable Auto Apply.')
    } finally {
      setAutoBusy(false)
    }
  }

  async function copyLink(job) {
    try {
      await navigator.clipboard.writeText(job.url)
      setCopiedId(job.id)
      window.setTimeout(() => setCopiedId(''), 1400)
    } catch {
      setError('Could not copy the link. You can open the job and copy it from your browser.')
    }
  }

  const directCount = useMemo(
    () => feed.jobs.filter((job) => job.direct_apply).length,
    [feed.jobs]
  )

  const updatedText = feed.generated_at_utc
    ? new Intl.DateTimeFormat('en-IN', {
        dateStyle: 'medium',
        timeStyle: 'short'
      }).format(new Date(feed.generated_at_utc))
    : 'Waiting for first agent refresh'

  return (
    <div className="app-shell">
      <header className="hero">
        <nav className="nav">
          <div className="brand">
            <div className="brand-mark">D</div>
            <div>
              <strong>DraftflowAI Jobs</strong>
              <span>Live role discovery</span>
            </div>
          </div>
          <div className="nav-actions">
            <a className="ghost-link" href="#auto-apply">Auto Apply Upgrade</a>
            <button className="ghost-button" onClick={loadJobs} disabled={loading}>
              {loading ? 'Refreshing…' : 'Refresh jobs'}
            </button>
          </div>
        </nav>

        <div className="hero-copy">
          <div className="eyebrow">SOFTWARE · DATA/AI · QA · SECURITY · CLOUD · IT</div>
          <h1>One place to discover fresh technology jobs across India.</h1>
          <p>
            Our agent continuously discovers technology roles posted or updated in the last 30 days.
            Search by role, skill, category, location and experience, then apply on the employer&apos;s original page.
          </p>
        </div>

        <div className="stats">
          <div>
            <strong>{feed.count}</strong>
            <span>technology jobs · last 30 days</span>
          </div>
          <div>
            <strong>{filteredJobs.length}</strong>
            <span>matching your filters</span>
          </div>
          <div>
            <strong>{directCount}</strong>
            <span>direct employer/ATS links</span>
          </div>
        </div>
      </header>

      <main className="content">
        <section className="filter-card">
          <div className="field field-wide">
            <label>Role, company or technology</label>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Java, .NET, Python, React, QA, AI, AWS…"
            />
          </div>

          <div className="field">
            <label>Location</label>
            <input
              value={location}
              onChange={(event) => setLocation(event.target.value)}
              placeholder="Hyderabad, Bengaluru, Remote…"
            />
          </div>

          <div className="field">
            <label>Category</label>
            <select value={normalizedCategory} onChange={(event) => setCategory(event.target.value)}>
              <option value="all">All technology</option>
              {categoryOptions.map((item) => (
                <option value={item} key={item}>{item}</option>
              ))}
            </select>
          </div>

          <div className="field">
            <label>Source</label>
            <select value={normalizedSource} onChange={(event) => setSource(event.target.value)}>
              <option value="all">All sources</option>
              {sourceOptions.map((item) => (
                <option value={item} key={item}>{prettySource(item)}</option>
              ))}
            </select>
          </div>


          <div className="field">
            <label>Skill</label>
            <select value={normalizedSkill} onChange={(event) => setSkill(event.target.value)}>
              <option value="all">All skills</option>
              {skillOptions.map((item) => (
                <option value={item} key={item}>{item}</option>
              ))}
            </select>
          </div>

          <div className="field">
            <label>Experience required</label>
            <select value={normalizedExperience} onChange={(event) => setExperience(event.target.value)}>
              {EXPERIENCE_OPTIONS.map((item) => (
                <option value={item.value} key={item.value}>{item.label}</option>
              ))}
            </select>
          </div>


          <div className="field">
            <label>Posted within</label>
            <select value={normalizedPosted} onChange={(event) => setPostedWithin(event.target.value)}>
              <option value="1">Last 24 hours</option>
              <option value="3">Last 3 days</option>
              <option value="7">Last 7 days</option>
              <option value="14">Last 14 days</option>
              <option value="30">Last 30 days</option>
            </select>
          </div>

          <div className="field">
            <label>Human verification</label>
            <select value={verification} onChange={(event) => setVerification(event.target.value)}>
              <option value="all">All statuses</option>
              <option value="no_verification_detected">No verification detected</option>
              <option value="verification_detected">Verification detected</option>
              <option value="unknown">Not checked / unknown</option>
            </select>
          </div>
        </section>

        <div className="feed-meta">
          <div>
            <h2>Live job feed</h2>
            <p>Last feed change: {updatedText}</p>
          </div>
          {(query.trim() || location.trim() || normalizedSource !== 'all' || normalizedCategory !== 'all' || normalizedSkill !== 'all' || normalizedExperience !== 'all' || normalizedPosted !== '30' || verification !== 'all') && (
            <button
              className="text-button"
              onClick={() => {
                setQuery('')
                setLocation('')
                setSource('all')
                setCategory('all')
                setSkill('all')
                setExperience('all')
                setPostedWithin('30')
                setVerification('all')
              }}
            >
              Clear filters
            </button>
          )}
        </div>

        {error && <div className="error-box">{error}</div>}

        {loading ? (
          <section className="job-grid">
            {[1, 2, 3, 4].map((item) => <div className="skeleton" key={item} />)}
          </section>
        ) : filteredJobs.length === 0 ? (
          <div className="empty-state">
            <h3>No jobs match these filters.</h3>
            <p>Try a broader role, location, source, skill or experience range.</p>
          </div>
        ) : (
          <section className="job-grid">
            {visibleJobs.map((job) => (
              <article className="job-card" key={job.id || job.url}>
                <div className="job-card-top">
                  <div className="badges">
                    <div className="source-badge">{prettySource(job.source)}</div>
                    {(job.discovered_via || []).map((via) => (
                      <div className="discovery-badge" key={via}>via {prettySource(via)}</div>
                    ))}
                    {job.auto_apply_supported && job.verification_status === 'no_verification_detected' && (
                      <div className="auto-badge">No verification detected</div>
                    )}
                    {job.auto_apply_supported && job.verification_status === 'verification_detected' && (
                      <div className="verification-badge">Verification detected</div>
                    )}
                    {job.auto_apply_supported && (!job.verification_status || job.verification_status === 'unknown') && (
                      <div className="verification-unknown-badge">Verification unknown</div>
                    )}
                    {job.category && <div className="category-badge">{job.category}</div>}
                  </div>
                  <span className="published">{formatDate(job.published)}</span>
                </div>

                <h3>{job.title}</h3>
                <div className="company">{prettyCompany(job.company)}</div>
                <div className="location">{job.location}</div>
                <div className="experience">Experience: {job.experience_label || 'Not specified'}</div>

                {job.skills?.length > 0 && (
                  <div className="skills">
                    {job.skills.slice(0, 8).map((item) => (
                      <span className="skill" key={item}>{item}</span>
                    ))}
                  </div>
                )}

                <div className="job-actions">
                  <a
                    className="primary-button"
                    href={job.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {job.direct_apply ? 'Direct company apply' : 'View on ' + prettySource(job.source)}
                  </a>
                  {job.direct_apply && job.listing_url ? (
                    <a
                      className="secondary-button"
                      href={job.listing_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Source listing
                    </a>
                  ) : (
                    <button className="secondary-button" onClick={() => copyLink(job)}>
                      {copiedId === job.id ? 'Copied' : 'Copy link'}
                    </button>
                  )}
                </div>
              </article>
            ))}
          </section>
        )}

        {visibleJobs.length < filteredJobs.length && (
          <div className="load-more-wrap">
            <button className="secondary-button load-more" onClick={() => setVisibleCount((count) => count + 40)}>
              Load more jobs ({filteredJobs.length - visibleJobs.length} remaining)
            </button>
          </div>
        )}

        <section className="upgrade-card" id="auto-apply">
          <div className="upgrade-heading">
            <div>
              <div className="eyebrow dark">AUTO APPLY UPGRADE</div>
              <h2>Upload the right resume and let matching supported jobs apply automatically.</h2>
              <p>
                Set the role, skills, experience and locations that this resume represents.
                DraftflowAI ranks matching jobs, chooses the best resume variant, avoids duplicates,
                respects your daily limit and stops when a required question needs your input.
              </p>
            </div>
            <div className={(supabaseClient || AUTO_APPLY_API_URL) ? 'backend-status ready' : 'backend-status test'}>
              {supabaseClient
                ? 'Production account backend ready'
                : (AUTO_APPLY_API_URL ? 'Legacy private backend connected' : 'Browser-only test mode')}
            </div>
          </div>

          {supabaseClient && (
            <div className="auth-panel">
              {authUser ? (
                <>
                  <div>
                    <strong>{autoEnabled ? 'Auto Apply active' : 'Signed in'}</strong>
                    <span>{authUser.email}</span>
                  </div>
                  {autoEnabled && (
                    <button className="secondary-button" type="button" onClick={pauseAutoApply} disabled={autoBusy}>Pause Auto Apply</button>
                  )}
                  <button className="secondary-button" type="button" onClick={signOutAutoApply}>Sign out</button>
                </>
              ) : (
                <>
                  <div className="field auth-email-field">
                    <label>Sign in for Auto Apply</label>
                    <input
                      type="email"
                      value={authEmail}
                      onChange={(event) => setAuthEmail(event.target.value)}
                      placeholder="you@example.com"
                    />
                  </div>
                  <button className="secondary-button" type="button" onClick={sendSignInLink} disabled={authBusy}>
                    {authBusy ? 'Sending…' : 'Email sign-in link'}
                  </button>
                </>
              )}
              {authMessage && <span className="auth-message">{authMessage}</span>}
            </div>
          )}

          <form className="upgrade-form" onSubmit={enableAutoApply}>
            <div className="field">
              <label>Name</label>
              <input value={autoProfile.name} onChange={(event) => updateAutoProfile('name', event.target.value)} required />
            </div>
            <div className="field">
              <label>Email</label>
              <input type="email" value={autoProfile.email} onChange={(event) => updateAutoProfile('email', event.target.value)} required />
            </div>
            <div className="field">
              <label>Phone</label>
              <input value={autoProfile.phone} onChange={(event) => updateAutoProfile('phone', event.target.value)} />
            </div>
            <div className="field">
              <label>LinkedIn profile</label>
              <input value={autoProfile.linkedin} onChange={(event) => updateAutoProfile('linkedin', event.target.value)} placeholder="https://linkedin.com/in/..." />
            </div>
            <div className="field">
              <label>Current location</label>
              <input value={autoProfile.current_location} onChange={(event) => updateAutoProfile('current_location', event.target.value)} placeholder="Hyderabad, India" />
            </div>
            <div className="field">
              <label>Notice period (days)</label>
              <input type="number" min="0" max="365" value={autoProfile.notice_period_days} onChange={(event) => updateAutoProfile('notice_period_days', event.target.value)} />
            </div>
            <div className="field">
              <label>Current CTC (LPA)</label>
              <input type="number" min="0" step="0.1" value={autoProfile.current_ctc_lpa} onChange={(event) => updateAutoProfile('current_ctc_lpa', event.target.value)} />
            </div>
            <div className="field">
              <label>Expected CTC (LPA)</label>
              <input type="number" min="0" step="0.1" value={autoProfile.expected_ctc_lpa} onChange={(event) => updateAutoProfile('expected_ctc_lpa', event.target.value)} />
            </div>
            <div className="field">
              <label>Experience (years)</label>
              <input type="number" min="0" max="50" step="0.1" value={autoProfile.years_experience} onChange={(event) => updateAutoProfile('years_experience', event.target.value)} required />
            </div>
            <div className="field field-wide">
              <label>Target roles</label>
              <input value={autoProfile.target_roles} onChange={(event) => updateAutoProfile('target_roles', event.target.value)} placeholder="Java Developer, .NET Developer, DevOps Engineer" required />
            </div>
            <div className="field field-wide">
              <label>Skills for this resume</label>
              <input value={autoProfile.skills} onChange={(event) => updateAutoProfile('skills', event.target.value)} placeholder="Java, Spring Boot, AWS, SQL" required />
            </div>
            <div className="field">
              <label>Preferred locations</label>
              <input value={autoProfile.preferred_locations} onChange={(event) => updateAutoProfile('preferred_locations', event.target.value)} placeholder="India, Hyderabad, Bengaluru" />
            </div>
            <div className="field">
              <label>Minimum match</label>
              <select value={autoProfile.minimum_match_score} onChange={(event) => updateAutoProfile('minimum_match_score', event.target.value)}>
                <option value="70">70%</option>
                <option value="75">75%</option>
                <option value="80">80%</option>
                <option value="85">85%</option>
                <option value="90">90%</option>
              </select>
            </div>
            <div className="field">
              <label>Daily application limit</label>
              <select value={autoProfile.daily_application_limit} onChange={(event) => updateAutoProfile('daily_application_limit', event.target.value)}>
                <option value="5">5 per day</option>
                <option value="10">10 per day</option>
                <option value="20">20 per day</option>
                <option value="30">30 per day</option>
              </select>
            </div>
            <div className="field field-wide">
              <label>Resume PDF</label>
              <input
                type="file"
                accept="application/pdf,.pdf"
                onChange={(event) => chooseResume(event.target.files?.[0] || null)}
                required
              />
              <small>PDF only. Resume files must be stored in private backend storage, never in the public job-feed repository.</small>
              {(resumeReading || resumeNotice) && <small role="status">{resumeReading ? 'Reading resume privately…' : resumeNotice}</small>}
            </div>

            <label className="consent-row">
              <input type="checkbox" checked={autoConsent} onChange={(event) => setAutoConsent(event.target.checked)} />
              <span>
                I authorize DraftflowAI to submit applications automatically to matching supported employer ATS jobs using this profile and resume, up to my daily limit. Jobs requiring unknown mandatory answers, login, CAPTCHA or human verification must stop for manual action.
              </span>
            </label>

            <div className="upgrade-actions">
              <button className="primary-button" type="submit" disabled={autoBusy || resumeReading || (supabaseClient && !authUser)}>
                {autoBusy ? 'Saving…' : ((supabaseClient || AUTO_APPLY_API_URL) ? 'Enable Auto Apply' : 'Save & Test Resume')}
              </button>
              {!supabaseClient && !AUTO_APPLY_API_URL && (
                <span className="upgrade-note">Test mode keeps the PDF only in this browser. It is not uploaded to GitHub or any server, and no applications are submitted.</span>
              )}
              {supabaseClient && !authUser && (
                <span className="upgrade-note">Sign in with your email before enabling Auto Apply.</span>
              )}
            </div>
            {testMatchSummary && (
              <div className="test-results">
                <div className="test-result">
                  <strong>{testMatchSummary.relevant}</strong>
                  <span>relevant jobs for your role + experience</span>
                </div>
                <div className="test-result">
                  <strong>{testMatchSummary.strong}</strong>
                  <span>strong matches at your selected score</span>
                </div>
                <div className="test-result">
                  <strong>{testMatchSummary.autoEligible}</strong>
                  <span>currently auto-apply eligible</span>
                </div>
                <div className="test-result"><strong>{testMatchSummary.verificationPending}</strong><span>verification pending or manual action needed</span></div>
                <div className="test-result"><strong>{testMatchSummary.belowThreshold}</strong><span>below minimum match</span></div>
              </div>
            )}
            {supabaseClient && authUser && (
              <div className="application-history">
                <div className="history-heading"><strong>Screening answer bank</strong><button type="button" className="text-button" onClick={loadApplicationAttempts}>Refresh questions</button></div>
                <p>Save accurate answers once. Exact employer questions are reused on future applications. Use the units or format requested; leave unknown answers blank. Never enter passwords, verification codes or sensitive identifiers.</p>
                {[...new Set([...missingScreeningQuestions, ...Object.keys(screeningAnswers), ...Object.keys(screeningDrafts)])].map(question=>(
                  <div className="field field-wide" key={question}>
                    <label>{question}</label>
                    <input value={screeningDrafts[question] ?? screeningAnswers[question] ?? ''} onChange={event=>setScreeningDrafts(old=>({...old,[question]:event.target.value}))} placeholder="Type your accurate answer" maxLength={600}/>
                    {Object.hasOwn(screeningAnswers,question) && <button type="button" className="text-button" disabled={screeningBusy} onClick={()=>deleteScreeningAnswer(question)}>Remove saved answer</button>}
                  </div>
                ))}
                <div className="field field-wide"><label>Add another screening question</label><input value={screeningCustom} onChange={event=>setScreeningCustom(event.target.value)} maxLength={500} placeholder="Type the employer's exact question" />
                  <button type="button" className="secondary-button" disabled={!screeningCustom.trim()} onClick={()=>{const q=screeningCustom.trim();setScreeningDrafts(old=>({...old,[q]:old[q] ?? screeningAnswers[q] ?? ''}));setScreeningCustom('')}}>Add question</button>
                </div>
                <button type="button" className="primary-button" disabled={screeningBusy} onClick={saveScreeningAnswers}>{screeningBusy ? 'Saving…' : 'Save screening answers'}</button>
                {screeningMessage && <div role="status" className="upgrade-message">{screeningMessage}</div>}
              </div>
            )}
            {supabaseClient && authUser && autoEnabled && applicationAttempts.length === 0 && <div className="upgrade-message">No application attempts recorded yet. The worker runs on a scheduled basis; refresh status after it runs. A match is not a confirmed submission. <button type="button" className="text-button" onClick={loadApplicationAttempts}>Refresh status</button></div>}
            {supabaseClient && authUser && applicationAttempts.length > 0 && (
              <div className="application-history">
                <div className="history-heading">
                  <strong>Recent Auto Apply activity</strong>
                  <button className="text-button" type="button" onClick={loadApplicationAttempts}>Refresh status</button>
                </div>
                {applicationAttempts.map((attempt) => (
                  <div className="history-row" key={attempt.id}>
                    <div>
                      <strong>{attempt.title}</strong>
                      <span>{prettyCompany(attempt.company)}</span>
                      {attempt.message && <span className="history-message">{attempt.message}</span>}
                      {attempt.status === 'SUBMITTED' && (
                        <span className="history-message">
                          {attempt.email_confirmation === 'confirmed' ? 'Email confirmed · ' + formatDate(attempt.email_received_at) :
                            attempt.email_confirmation === 'pending' ? 'Pending email confirmation · portal submission recorded' :
                            'Email confirmation status unavailable'}
                        </span>
                      )}
                    </div>
                    <span>{Math.round(Number(attempt.match_score || 0))}%</span>
                    <div className="history-status-wrap">
                      <span className={'history-status status-' + String(attempt.status || '').toLowerCase().replaceAll('_', '-')}>
                        {String(attempt.status || '').replaceAll('_', ' ')}
                      </span>
                      {['HUMAN_VERIFICATION_REQUIRED', 'QUESTION_REQUIRED', 'PROFILE_REQUIRED', 'REVIEW_REQUIRED', 'UNCERTAIN'].includes(attempt.status) && attempt.apply_url && (
                        <a className="history-action" href={attempt.apply_url} target="_blank" rel="noopener noreferrer">Open application</a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {autoMessage && <div className="upgrade-message">{autoMessage}</div>}
          </form>
        </section>

        <section className="trust-card">
          <div>
            <div className="eyebrow dark">HOW IT WORKS</div>
            <h2>The agent finds jobs. You stay in control.</h2>
          </div>
          <p>
            DraftflowAI Jobs indexes recent public technology openings from supported employer career systems
            and approved job-platform feeds. When a verified employer or ATS application URL is available,
            the primary button opens that company application page; otherwise it opens the original listing.
          </p>
        </section>
      </main>

      <footer>
        <strong>DraftflowAI Jobs</strong>
        <span>Job discovery made simpler.</span>
      </footer>
    </div>
  )
}

export default App
