import { useState } from 'react'

const API_BASE_URL = "http://50.17.126.62";

function scoreClass(score) {
  if (score >= 85) return 'score-high'
  if (score >= 70) return 'score-medium'
  return 'score-low'
}

function App() {
  const [keyword, setKeyword] = useState('DevOps')
  const [location, setLocation] = useState('Hyderabad')
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedJob, setSelectedJob] = useState(null)

  async function searchJobs() {
    setLoading(true)
    setError('')
    setSelectedJob(null)

    try {
      const params = new URLSearchParams({
        keyword,
        location
      })

      const response = await fetch(
        `${API_BASE_URL}/jobs/search?${params.toString()}`
      )

      if (!response.ok) {
        throw new Error(`API returned ${response.status}`)
      }

      const data = await response.json()

      const list = Array.isArray(data)
        ? data
        : data.jobs || data.results || []

      const normalized = list.map((job, index) => ({
        job_id: job.job_id ?? job.id ?? index + 1,
        title: job.title || 'Untitled job',
        company:
          job.company ||
          job.company_name ||
          'Unknown company',
        location:
          job.location ||
          job.location_display ||
          location,
        description: job.description || '',
        url:
          job.url ||
          job.redirect_url ||
          '',
        score: job.score ?? null,
        decision: job.decision ?? null,
        matched_skills:
          job.matched_skills || [],
        missing_skills:
          job.missing_skills || []
      }))

      setJobs(normalized)

    } catch (err) {
      setError(
        `${err.message}. Check VITE_API_BASE_URL and make sure the backend is reachable.`
      )
    } finally {
      setLoading(false)
    }
  }

  async function analyzeJob(job) {
    setSelectedJob({
      ...job,
      analyzing: true
    })

    setError('')

    try {
      const response = await fetch(
        `${API_BASE_URL}/jobs/${job.job_id}/ai-match`
      )

      if (!response.ok) {
        throw new Error(
          `AI match API returned ${response.status}`
        )
      }

      const data = await response.json()

      const analysis =
        data.ai_analysis || data

      setSelectedJob({
        ...job,
        ...analysis,
        analyzing: false
      })

    } catch (err) {
      setSelectedJob(null)
      setError(err.message)
    }
  }

  return (
    <div className="app-shell">

      <header className="topbar">

        <div>
          <div className="eyebrow">
            AI-POWERED JOB SEARCH
          </div>

          <h1>
            DevOps Job AI
          </h1>

          <p>
            Find DevOps roles that actually match your experience.
          </p>
        </div>

        <div className="status-pill">
          <span className="status-dot" />
          API: {API_BASE_URL}
        </div>

      </header>

      <main className="content">

        <section className="search-card">

          <div className="field">

            <label>
              Role
            </label>

            <input
              value={keyword}
              onChange={(e) =>
                setKeyword(e.target.value)
              }
              placeholder="DevOps Engineer"
            />

          </div>

          <div className="field">

            <label>
              Location
            </label>

            <input
              value={location}
              onChange={(e) =>
                setLocation(e.target.value)
              }
              placeholder="Hyderabad"
            />

          </div>

          <button
            className="primary-button"
            onClick={searchJobs}
            disabled={loading}
          >
            {loading
              ? 'Searching...'
              : 'Search Jobs'}
          </button>

        </section>

        {error && (
          <div className="error-box">
            {error}
          </div>
        )}

        <section className="summary-row">

          <div>
            <h2>
              Recommended Jobs
            </h2>

            <p>
              {jobs.length} jobs returned
            </p>
          </div>

        </section>

        <section className="job-list">

          {jobs.length === 0 &&
            !loading && (
              <div className="empty-state">
                Search for DevOps jobs to get started.
              </div>
            )}

          {jobs.map((job) => (

            <article
              className="job-card"
              key={job.job_id}
            >

              <div className="job-main">

                <div className="job-title-row">

                  <div>

                    <h3>
                      {job.title}
                    </h3>

                    <p className="company">
                      {job.company}
                    </p>

                  </div>

                  {job.score !== null && (

                    <div
                      className={`score ${scoreClass(
                        job.score
                      )}`}
                    >

                      <strong>
                        {job.score}%
                      </strong>

                      <span>
                        match
                      </span>

                    </div>

                  )}

                </div>

                <div className="meta">
                  {job.location}
                </div>

                {job.matched_skills?.length > 0 && (

                  <div className="skills">

                    {job.matched_skills
                      .slice(0, 8)
                      .map((skill) => (

                        <span
                          className="skill matched"
                          key={skill}
                        >
                          {skill}
                        </span>

                      ))}

                  </div>

                )}

                {job.missing_skills?.length > 0 && (

                  <div className="missing">

                    Missing:
                    {' '}
                    {job.missing_skills
                      .slice(0, 5)
                      .join(', ')}

                  </div>

                )}

              </div>

              <div className="job-actions">

                <button
                  className="secondary-button"
                  onClick={() =>
                    analyzeJob(job)
                  }
                >
                  AI Analysis
                </button>

                {job.url ? (

                  <a
                    className="primary-button link-button"
                    href={job.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Apply
                  </a>

                ) : (

                  <button
                    className="secondary-button"
                    disabled
                  >
                    No Apply Link
                  </button>

                )}

              </div>

            </article>

          ))}

        </section>

        {selectedJob && (

          <section className="analysis-card">

            <div className="analysis-header">

              <div>

                <div className="eyebrow">
                  AI ANALYSIS
                </div>

                <h2>
                  {selectedJob.title}
                </h2>

                <p>
                  {selectedJob.company}
                </p>

              </div>

              {!selectedJob.analyzing && (

                <div
                  className={`score large ${scoreClass(
                    selectedJob.score || 0
                  )}`}
                >

                  <strong>
                    {selectedJob.score ?? '--'}%
                  </strong>

                  <span>
                    {selectedJob.decision || ''}
                  </span>

                </div>

              )}

            </div>

            {selectedJob.analyzing ? (

              <p>
                Analyzing job...
              </p>

            ) : (

              <>

                <h4>
                  Matched Skills
                </h4>

                <div className="skills">

                  {(selectedJob.matched_skills || [])
                    .map((skill) => (

                      <span
                        className="skill matched"
                        key={skill}
                      >
                        {skill}
                      </span>

                    ))}

                </div>

                <h4>
                  Missing Skills
                </h4>

                <div className="skills">

                  {(selectedJob.missing_skills || [])
                    .length === 0 ? (

                    <span className="good-text">
                      No missing skills
                    </span>

                  ) : (

                    selectedJob.missing_skills
                      .map((skill) => (

                        <span
                          className="skill missing-skill"
                          key={skill}
                        >
                          {skill}
                        </span>

                      ))

                  )}

                </div>

                {selectedJob.reason && (

                  <div className="reason">

                    <h4>
                      Why?
                    </h4>

                    <p>
                      {selectedJob.reason}
                    </p>

                  </div>

                )}

              </>

            )}

          </section>

        )}

      </main>

    </div>
  )
}

export default App
