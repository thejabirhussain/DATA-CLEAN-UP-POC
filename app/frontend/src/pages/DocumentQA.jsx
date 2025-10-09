import React, { useState, useEffect, useRef } from 'react'

const API_BASE = 'http://localhost:8000'

export default function DocumentQA() {
  const [file, setFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [documentLoaded, setDocumentLoaded] = useState(false)
  const [documentName, setDocumentName] = useState('')
  const [messages, setMessages] = useState([])
  const [question, setQuestion] = useState('')
  const [querying, setQuerying] = useState(false)
  const messagesEndRef = useRef(null)

  useEffect(() => {
    checkStatus()
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  const checkStatus = async () => {
    try {
      const resp = await fetch(`${API_BASE}/rag/status`)
      const data = await resp.json()
      setDocumentLoaded(data.document_loaded)
      setDocumentName(data.pdf_name || '')
    } catch (e) {
      console.error('Failed to check status:', e)
    }
  }

  const handleFileChange = (e) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile && selectedFile.type === 'application/pdf') {
      setFile(selectedFile)
    } else {
      alert('Please select a PDF file')
    }
  }

  const handleUpload = async () => {
    if (!file) return

    setUploading(true)
    const formData = new FormData()
    formData.append('file', file)

    try {
      const resp = await fetch(`${API_BASE}/rag/upload`, {
        method: 'POST',
        body: formData
      })
      const data = await resp.json()
      
      if (data.success) {
        setDocumentLoaded(true)
        setDocumentName(data.filename)
        setMessages([])
        alert('Document uploaded and processed successfully!')
      } else {
        alert('Upload failed: ' + (data.detail || 'Unknown error'))
      }
    } catch (e) {
      alert('Upload error: ' + e.message)
    } finally {
      setUploading(false)
    }
  }

  const handleAskQuestion = async () => {
    if (!question.trim() || querying) return

    const userQuestion = question.trim()
    setQuestion('')
    setMessages(prev => [...prev, { role: 'user', content: userQuestion }])
    setQuerying(true)

    try {
      const resp = await fetch(`${API_BASE}/rag/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: userQuestion })
      })
      const data = await resp.json()

      if (data.success) {
        setMessages(prev => [...prev, { role: 'assistant', content: data.answer }])
      } else {
        setMessages(prev => [...prev, { role: 'assistant', content: 'Error: ' + (data.detail || 'Unknown error') }])
      }
    } catch (e) {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Error: ' + e.message }])
    } finally {
      setQuerying(false)
    }
  }

  const handleClearChat = () => {
    setMessages([])
  }

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleAskQuestion()
    }
  }

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      {/* Upload Section */}
      <section className="bg-white rounded-2xl shadow p-4 mb-6">
        <h2 className="text-base font-semibold mb-3">Upload Document</h2>

        {documentLoaded ? (
          <div>
            <p className="mb-2 text-sm">
              <span className="font-semibold">Current Document:</span> {documentName}
            </p>
            <p className="text-xs text-slate-600">Chat is enabled. Ask questions about the document below.</p>
          </div>
        ) : (
          <div className="space-y-3">
            <input
              type="file"
              accept=".pdf"
              onChange={handleFileChange}
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm"
            />
            {file && (
              <p className="text-sm text-slate-600">Selected: {file.name}</p>
            )}
            <button
              onClick={handleUpload}
              disabled={!file || uploading}
              className="px-4 py-2 rounded-xl text-white text-sm font-medium bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {uploading ? 'Processing…' : 'Upload PDF'}
            </button>
          </div>
        )}
      </section>

      {/* Chat Section */}
      <section className="bg-white rounded-2xl shadow p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold">Chat</h2>
          {messages.length > 0 && (
            <button
              onClick={handleClearChat}
              className="px-3 py-1 rounded-lg bg-slate-100 text-slate-800 text-xs hover:bg-slate-200"
            >
              Clear Chat
            </button>
          )}
        </div>

        {/* Messages */}
        <div className="border border-slate-200 rounded-xl p-3 min-h-[300px] max-h-[500px] overflow-y-auto mb-3 bg-slate-50 flex flex-col">
          {messages.length === 0 ? (
            <p className="text-sm text-slate-500">
              {documentLoaded ? 'Ask a question about the document…' : 'Upload a document to start chatting'}
            </p>
          ) : (
            messages.map((msg, idx) => (
              <div
                key={idx}
                className={`inline-block w-fit max-w-[70%] mb-2.5 px-3 py-1.5 rounded-2xl text-sm ${msg.role === 'user' ? 'bg-emerald-600 text-white self-end' : 'bg-slate-100 text-slate-800 self-start'}`}
              >
                <div className="text-[11px] font-semibold mb-1 opacity-80">
                  {msg.role === 'user' ? 'YOU' : 'ASSISTANT'}
                </div>
                <div className="whitespace-pre-wrap leading-5">{msg.content}</div>
              </div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="flex gap-2">
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyPress={handleKeyPress}
            disabled={!documentLoaded || querying}
            placeholder={documentLoaded ? 'Type your question…' : 'Upload a document first'}
            className="flex-1 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm disabled:bg-slate-100"
          />
          <button
            onClick={handleAskQuestion}
            disabled={!documentLoaded || !question.trim() || querying}
            className="px-4 py-2 rounded-xl bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {querying ? 'Asking…' : 'Ask'}
          </button>
        </div>
      </section>
    </main>
  )
}
