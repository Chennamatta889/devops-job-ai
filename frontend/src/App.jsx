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
    indeed_alert: 'Indeed'
  }
  return names[value] || value.replaceAll('_', ' ') || 'Career site'
}

function prettyCompany(value = '') {
  return value
    .replace(/[-_]+/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
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

function App() {
  const [feed, setFeed] = useState({ jobs: [], count: 0, generated_at_utc: null })
  const [query, setQuery] = useState('')
  const [location, setLocation] = useState('')
  const [source, setSource] = useState('all')
  const [skill, setSkill] = useState('all')
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

  const skillOptions = useMemo(
    () =>
      [...new Set(feed.jobs.flatMap((job) => (Array.isArray(job.skills) ? job.skills : [])))]
        .filter(Boolean)
        .sort(),
    [feed.jobs]
  )

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
      if (source !== 'all' && job.source !== source) return false
      if (skill !== 'all' && !skills.includes(skill)) return false
      return true
    })
  }, [feed.jobs, query, location, source, skill])

  async function copyLink(job) {
    try {
      await navigator.clipboard.writeText(job.url)
      setCopiedId(job.id)
      window.setTimeout(() => setCopiedId(''), 1400)
    } catch {
      setError('Could not copy the link. You can open the job and copy it from your browser.')
    }
  }

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
          <div className="eyebrow">DEVOPS · CLOUD · SRE · PLATFORM</div>
          <h1>Find relevant jobs without searching dozens of career sites.</h1>
          <p>
            Our agent continuously discovers roles from supported employer job boards.
            Search the live feed and apply on the company&apos;s original application page.
          </p>
        </div>

        <div className="stats">
          <div>
            <strong>{feed.count}</strong>
            <span>jobs in feed</span>
          </div>
          <div>
            <strong>{filteredJobs.length}</strong>
            <span>matching your filters</span>
          </div>
          <div>
            <strong>Direct</strong>
            <span>employer apply links</span>
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
              placeholder="DevOps, AWS, Kubernetes, SRE…"
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
            <label>Source</label>
            <select value={source} onChange={(event) => setSource(event.target.value)}>
              <option value="all">All sources</option>
              {sourceOptions.map((item) => (
                <option value={item} key={item}>{prettySource(item)}</option>
              ))}
            </select>
          </div>

          <div className="field">
            <label>Skill</label>
            <select value={skill} onChange={(event) => setSkill(event.target.value)}>
              <option value="all">All skills</option>
              {skillOptions.map((item) => (
                <option value={item} key={item}>{item}</option>
              ))}
            </select>
          </div>
        </section>

        <div className="feed-meta">
          <div>
            <h2>Live job feed</h2>
            <p>Last feed change: {updatedText}</p>
          </div>
          {(query || location || source !== 'all' || skill !== 'all') && (
            <button
              className="text-button"
              onClick={() => {
                setQuery('')
                setLocation('')
                setSource('all')
                setSkill('all')
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
            <p>Try a broader role, location, source or skill.</p>
          </div>
        ) : (
          <section className="job-grid">
            {filteredJobs.map((job) => (
              <article className="job-card" key={job.id || job.url}>
                <div className="job-card-top">
                  <div className="source-badge">{prettySource(job.source)}</div>
                  <span className="published">{formatDate(job.published)}</span>
                </div>

                <h3>{job.title}</h3>
                <div className="company">{prettyCompany(job.company)}</div>
                <div className="location">{job.location}</div>

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
                    View & apply
                  </a>
                  <button className="secondary-button" onClick={() => copyLink(job)}>
                    {copiedId === job.id ? 'Copied' : 'Copy link'}
                  </button>
                </div>
              </article>
            ))}
          </section>
        )}

        <section className="trust-card">
          <div>
            <div className="eyebrow dark">HOW IT WORKS</div>
            <h2>The agent finds jobs. You stay in control.</h2>
          </div>
          <p>
            DraftflowAI Jobs does not claim to be the employer and does not guarantee hiring.
            Job links open the original employer or ATS page so users can review the full
            description and submit their own application.
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
