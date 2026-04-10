import { useMemo, useState } from 'react'
import './App.css'

function App() {
  const [apiBaseUrl, setApiBaseUrl] = useState(
    import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000',
  )
  const [selectedFile, setSelectedFile] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [job, setJob] = useState(null)
  const [uploadResult, setUploadResult] = useState('')

  const isReady = useMemo(() => Boolean(selectedFile) && !isLoading, [selectedFile, isLoading])

  const onSelectFile = (event) => {
    const file = event.target.files?.[0] || null
    setSelectedFile(file)
    setError('')
    setJob(null)
    setUploadResult('')
  }

  const onUpload = async (event) => {
    event.preventDefault()
    if (!selectedFile) {
      setError('Choisis un fichier avant de lancer l upload.')
      return
    }

    setIsLoading(true)
    setError('')
    setJob(null)
    setUploadResult('')

    try {
      const createResponse = await fetch(`${apiBaseUrl}/jobs`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({
          fileName: selectedFile.name,
          contentType: selectedFile.type || 'application/octet-stream',
        }),
      })

      const createData = await createResponse.json()
      if (!createResponse.ok) {
        throw new Error(createData.detail || 'Creation du job impossible.')
      }

      setJob(createData)

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
        throw new Error(`Upload refuse (${uploadResponse.status}). ${detail}`)
      }

      setUploadResult('Fichier upload avec succes vers Azure Blob.')
    } catch (uploadError) {
      setError(uploadError.message || 'Une erreur est survenue.')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <main className="page">
      <section className="card">
        <p className="chip">Local Upload Client</p>
        <h1>Upload vers Azure Blob via ton API Jobs</h1>
        <p className="subtitle">
          Cette page enchaine automatiquement: POST /jobs puis PUT du fichier vers uploadUrl.
        </p>

        <form className="form" onSubmit={onUpload}>
          <label className="field">
            URL API
            <input
              type="text"
              value={apiBaseUrl}
              onChange={(event) => setApiBaseUrl(event.target.value.trim())}
              placeholder="http://127.0.0.1:8000"
            />
          </label>

          <label className="field">
            Fichier
            <input type="file" onChange={onSelectFile} />
          </label>

          <button type="submit" disabled={!isReady}>
            {isLoading ? 'Upload en cours...' : 'Creer le job + uploader'}
          </button>
        </form>

        {selectedFile && (
          <p className="note">
            Fichier choisi: <strong>{selectedFile.name}</strong> ({selectedFile.type || 'application/octet-stream'})
          </p>
        )}

        {error && <div className="result error">{error}</div>}
        {uploadResult && <div className="result success">{uploadResult}</div>}

        {job && (
          <div className="result job">
            <p>
              Job cree: <strong>{job.jobId}</strong>
            </p>
            <p>Status: {job.status}</p>
            <p>createdAt: {job.createdAt}</p>
            <p>
              Upload URL: <a href={job.uploadUrl}>{job.uploadUrl}</a>
            </p>
          </div>
        )}
      </section>
    </main>
  )
}

export default App
