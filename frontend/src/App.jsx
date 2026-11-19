import { useEffect, useMemo, useState } from 'react'

const FEED_URL =
  import.meta.env.VITE_JOB_FEED_URL ||
  'https://raw.githubusercontent.com/Chennamatta889/devops-job-ai/main/data/jobs.json'

function prettySource(value = '') {
  const names = {
    greenhouse: 'Greenhouse',
    lever: 'Lever',
    ashby: 'Ashby',
    smartrecruiters: 'SmartRecruiters',
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
    () => [...new Set(feed.jobs.map((job) => job.source).filter(Boolean))].sort(),
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
      if (normalizedSource !== 'all' && job.source !== normalizedSource) return false
      if (normalizedCategory !== 'all' && job.category !== normalizedCategory) return false
      if (normalizedSkill !== 'all' && !skills.includes(normalizedSkill)) return false
      if (!experienceMatches(job, normalizedExperience)) return false
      if (daysSince(job.published) > Number(normalizedPosted)) return false
      return true
    })
  }, [feed.jobs, query, location, normalizedSource, normalizedCategory, normalizedSkill, normalizedExperience, normalizedPosted])

  const visibleJobs = filteredJobs.slice(0, visibleCount)

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
          <button className="ghost-button" onClick={loadJobs} disabled={loading}>
            {loading ? 'Refreshing…' : 'Refresh jobs'}
          </button>
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

        <section className="trust-card">
          <div>
            <div className="eyebrow dark">HOW IT WORKS</div>
            <h2>The agent finds jobs. You stay in control.</h2>
          </div>
          <p>
            DraftflowAI Jobs indexes recent public technology openings from supported employer career systems.
            Job links open the original employer or ATS page so users can review the full description,
            confirm availability and submit their own application.
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
