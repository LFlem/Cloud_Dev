import { useEffect, useRef, useMemo, useState } from 'react'
import * as signalR from '@microsoft/signalr'
import './App.css'

const STATUS_STEPS = ['CREATED', 'UPLOADED', 'QUEUED', 'PROCESSING', 'PROCESSED']
const STATUS_LABELS = {
  CREATED: 'Créé',
  UPLOADED: 'Uploadé',
  QUEUED: 'En attente',
  PROCESSING: 'Traitement IA',
  PROCESSED: 'Traité',
  ERROR: 'Erreur',
}

function App() {
  const [apiBaseUrl, setApiBaseUrl] = useState(
    import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000',
  )
  const [functionsUrl, setFunctionsUrl] = useState(
    import.meta.env.VITE_FUNCTIONS_BASE_URL || '',
  )
  const [selectedFile, setSelectedFile] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [job, setJob] = useState(null)
  const [uploadDone, setUploadDone] = useState(false)
  const [jobStatus, setJobStatus] = useState(null)
  const connectionRef = useRef(null)

  const isReady = useMemo(() => Boolean(selectedFile) && !isLoading, [selectedFile, isLoading])

  useEffect(() => {
    return () => { connectionRef.current?.stop() }
  }, [])

  const connectSignalR = async (jobId) => {
    if (!functionsUrl) return
    try {
      const conn = new signalR.HubConnectionBuilder()
        .withUrl(`${functionsUrl}/api/negotiate`)
        .withAutomaticReconnect()
        .configureLogging(signalR.LogLevel.Warning)
        .build()

      conn.on('statusUpdate', (data) => {
        if (data.documentId === jobId) {
          setJobStatus(data)
        }
      })

      await conn.start()
      connectionRef.current = conn
    } catch (e) {
      console.warn('SignalR connection failed:', e)
    }
  }

  const onSelectFile = (event) => {
    const file = event.target.files?.[0] || null
    setSelectedFile(file)
    setError('')
    setJob(null)
    setUploadDone(false)
    setJobStatus(null)
    connectionRef.current?.stop()
    connectionRef.current = null
  }

  const onUpload = async (event) => {
    event.preventDefault()
    if (!selectedFile) return

    setIsLoading(true)
    setError('')
    setJob(null)
    setUploadDone(false)
    setJobStatus(null)

    try {
      const createResponse = await fetch(`${apiBaseUrl}/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          fileName: selectedFile.name,
          contentType: selectedFile.type || 'application/octet-stream',
        }),
      })

      const createData = await createResponse.json()
      if (!createResponse.ok) throw new Error(createData.detail || 'Création du job impossible.')

      setJob(createData)
      await connectSignalR(createData.jobId)

      const uploadResponse = await fetch(createData.uploadUrl, {
        method: 'PUT',
        headers: {
          'x-ms-blob-type': 'BlockBlob',
          'Content-Type': selectedFile.type || 'application/octet-stream',
        },
        body: selectedFile,
      })

      if (!uploadResponse.ok) {
        const detail = await uploadResponse.text()
        throw new Error(`Upload refusé (${uploadResponse.status}). ${detail}`)
      }

      setUploadDone(true)
    } catch (err) {
      setError(err.message || 'Une erreur est survenue.')
    } finally {
      setIsLoading(false)
    }
  }

  const currentStatus = jobStatus?.status || job?.status || null
  const currentIdx = STATUS_STEPS.indexOf(currentStatus)
  const isError = currentStatus === 'ERROR'

  return (
    <main className="page">
      <section className="card">
        <p className="chip">Pipeline Cloud IA</p>
        <h1>Upload de document vers Azure</h1>
        <p className="subtitle">
          POST /jobs → PUT blob → traitement IA → tags en temps réel
        </p>

        <form className="form" onSubmit={onUpload}>
          <label className="field">
            URL API
            <input
              type="text"
              value={apiBaseUrl}
              onChange={(e) => setApiBaseUrl(e.target.value.trim())}
              placeholder="http://127.0.0.1:8000"
            />
          </label>
          <label className="field">
            URL Functions (SignalR)
            <input
              type="text"
              value={functionsUrl}
              onChange={(e) => setFunctionsUrl(e.target.value.trim())}
              placeholder="https://myiotappcode.azurewebsites.net"
            />
          </label>
          <label className="field">
            Fichier
            <input type="file" onChange={onSelectFile} />
          </label>
          <button type="submit" disabled={!isReady}>
            {isLoading ? 'Upload en cours...' : 'Créer le job + uploader'}
          </button>
        </form>

        {selectedFile && (
          <p className="note">
            Fichier : <strong>{selectedFile.name}</strong>{' '}
            ({selectedFile.type || 'application/octet-stream'})
          </p>
        )}

        {error && <div className="result error">{error}</div>}

        {job && (
          <div className="result job">
            <p>Job : <strong>{job.jobId}</strong></p>

            <div className="pipeline">
              {STATUS_STEPS.map((s, idx) => (
                <span
                  key={s}
                  className={[
                    'step',
                    currentStatus === s && !isError ? 'active' : '',
                    idx < currentIdx && !isError ? 'done' : '',
                  ].join(' ').trim()}
                >
                  {STATUS_LABELS[s]}
                </span>
              ))}
              {isError && <span className="step error-step">{STATUS_LABELS.ERROR}</span>}
            </div>

            {jobStatus?.message && (
              <p className="status-message">{jobStatus.message}</p>
            )}

            {uploadDone && !jobStatus && (
              <p className="status-message">Fichier uploadé — en attente du pipeline…</p>
            )}

            {jobStatus?.tags?.length > 0 && (
              <div className="tags">
                {jobStatus.tags.map((tag) => (
                  <span key={tag} className="tag">{tag}</span>
                ))}
              </div>
            )}
          </div>
        )}
      </section>
    </main>
  )
}

export default App
