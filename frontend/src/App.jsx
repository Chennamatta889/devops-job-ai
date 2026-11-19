import { useEffect, useMemo, useState } from 'react'

const FEED_URL =
  import.meta.env.VITE_JOB_FEED_URL ||
  'https://raw.githubusercontent.com/Chennamatta889/devops-job-ai/main/data/jobs.json'

const AUTO_APPLY_API_URL = (import.meta.env.VITE_AUTO_APPLY_API_URL || '').replace(/\/$/, '')

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

function App() {
  const [feed, setFeed] = useState({ jobs: [], count: 0, generated_at_utc: null })
  const [query, setQuery] = useState('')
  const [location, setLocation] = useState('')
  const [source, setSource] = useState('all')
  const [skill, setSkill] = useState('all')
  const [experience, setExperience] = useState('all')
  const [category, setCategory] = useState('all')
  const [postedWithin, setPostedWithin] = useState('30')
  const [visibleCount, setVisibleCount] = useState(40)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [copiedId, setCopiedId] = useState('')
  const [autoBusy, setAutoBusy] = useState(false)
  const [autoMessage, setAutoMessage] = useState('')
  const [testMatchSummary, setTestMatchSummary] = useState(null)
  const [autoConsent, setAutoConsent] = useState(false)
  const [resumeFile, setResumeFile] = useState(null)
  const [autoProfile, setAutoProfile] = useState({
    name: '',
    email: '',
    phone: '',
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
      const response = await fetch(FEED_URL + '?t=' + Date.now(), { cache: 'no-store' })
      if (!response.ok) throw new Error('Job feed returned ' + response.status)
      const data = await response.json()
      setFeed({
        jobs: Array.isArray(data.jobs) ? data.jobs : [],
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
  }, [query, location, normalizedSource, normalizedSkill, normalizedExperience, normalizedCategory, normalizedPosted])

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
      if (daysSince(job.published) > Number(normalizedPosted)) return false
      return true
    })
  }, [feed.jobs, query, location, normalizedSource, normalizedCategory, normalizedSkill, normalizedExperience, normalizedPosted])

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

  function previewMatchSummary(profile) {
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
    const threshold = Number(profile.minimum_match_score || 80)
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

    const relevant = feed.jobs.filter((job) => {
      if (!roleMatches(job) || !experienceFits(job)) return false
      if (years < 4 && seniorTitle.test(String(job.title || ''))) return false
      return true
    })

    const scored = relevant.map((job) => {
      const jobSkills = (job.skills || []).map((item) => String(item).toLowerCase())
      const matchedSkills = jobSkills.filter((item) => skills.has(item)).length
      const skillScore = jobSkills.length ? Math.round((matchedSkills / jobSkills.length) * 35) : 12
      const experienceScore = Number.isFinite(job.experience_min) && Number(job.experience_min) > years ? 10 : 15
      const score = Math.min(100, 45 + skillScore + experienceScore + 5)
      return { job, score }
    })

    return {
      relevant: relevant.length,
      strong: scored.filter(({ score }) => score >= threshold).length,
      autoEligible: scored.filter(({ job, score }) => job.auto_apply_supported && score >= threshold).length
    }
  }

  function updateAutoProfile(field, value) {
    setAutoProfile((current) => ({ ...current, [field]: value }))
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
        </section>

        <div className="feed-meta">
          <div>
            <h2>Live job feed</h2>
            <p>Last feed change: {updatedText}</p>
          </div>
          {(query.trim() || location.trim() || normalizedSource !== 'all' || normalizedCategory !== 'all' || normalizedSkill !== 'all' || normalizedExperience !== 'all' || normalizedPosted !== '30') && (
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
                    {job.auto_apply_supported && <div className="auto-badge">Auto-apply eligible</div>}
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
            <div className={AUTO_APPLY_API_URL ? 'backend-status ready' : 'backend-status test'}>
              {AUTO_APPLY_API_URL ? 'Secure backend connected' : 'Browser-only test mode'}
            </div>
          </div>

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
                onChange={(event) => setResumeFile(event.target.files?.[0] || null)}
                required
              />
              <small>PDF only. Resume files must be stored in private backend storage, never in the public job-feed repository.</small>
            </div>

            <label className="consent-row">
              <input type="checkbox" checked={autoConsent} onChange={(event) => setAutoConsent(event.target.checked)} />
              <span>
                I authorize DraftflowAI to submit applications automatically to matching supported employer ATS jobs using this profile and resume, up to my daily limit. Jobs requiring unknown mandatory answers, login, CAPTCHA or human verification must stop for manual action.
              </span>
            </label>

            <div className="upgrade-actions">
              <button className="primary-button" type="submit" disabled={autoBusy}>
                {autoBusy ? 'Saving…' : (AUTO_APPLY_API_URL ? 'Enable Auto Apply' : 'Save & Test Resume')}
              </button>
              {!AUTO_APPLY_API_URL && (
                <span className="upgrade-note">Test mode keeps the PDF only in this browser. It is not uploaded to GitHub or any server, and no applications are submitted.</span>
              )}
            </div>
            {testMatchSummary && !AUTO_APPLY_API_URL && (
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
