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
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '20px', fontFamily: 'monospace' }}>
      <h1 style={{ fontSize: '24px', marginBottom: '20px', borderBottom: '2px solid black', paddingBottom: '10px' }}>
        Document Q&A
      </h1>

      {/* Upload Section */}
      <div style={{ border: '1px solid black', padding: '20px', marginBottom: '20px', backgroundColor: 'white' }}>
        <h2 style={{ fontSize: '18px', marginBottom: '15px' }}>Upload Document</h2>
        
        {documentLoaded ? (
          <div>
            <p style={{ marginBottom: '10px' }}>
              <strong>Current Document:</strong> {documentName}
            </p>
            <p style={{ fontSize: '14px', color: '#666' }}>
              Chat is enabled. Ask questions about the document below.
            </p>
          </div>
        ) : (
          <div>
            <input
              type="file"
              accept=".pdf"
              onChange={handleFileChange}
              style={{ display: 'block', marginBottom: '10px', padding: '5px', border: '1px solid black' }}
            />
            {file && (
              <p style={{ marginBottom: '10px', fontSize: '14px' }}>
                Selected: {file.name}
              </p>
            )}
            <button
              onClick={handleUpload}
              disabled={!file || uploading}
              style={{
                padding: '10px 20px',
                backgroundColor: uploading ? '#ccc' : 'black',
                color: 'white',
                border: 'none',
                cursor: uploading || !file ? 'not-allowed' : 'pointer',
                fontSize: '14px'
              }}
            >
              {uploading ? 'Processing...' : 'Upload PDF'}
            </button>
          </div>
        )}
      </div>

      {/* Chat Section */}
      <div style={{ border: '1px solid black', padding: '20px', backgroundColor: 'white' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
          <h2 style={{ fontSize: '18px', margin: 0 }}>Chat</h2>
          {messages.length > 0 && (
            <button
              onClick={handleClearChat}
              style={{
                padding: '5px 10px',
                backgroundColor: 'white',
                border: '1px solid black',
                cursor: 'pointer',
                fontSize: '12px'
              }}
            >
              Clear Chat
            </button>
          )}
        </div>

        {/* Messages */}
        <div style={{
          border: '1px solid black',
          padding: '10px',
          minHeight: '300px',
          maxHeight: '500px',
          overflowY: 'auto',
          marginBottom: '15px',
          backgroundColor: '#fafafa'
        }}>
          {messages.length === 0 ? (
            <p style={{ color: '#999', fontSize: '14px' }}>
              {documentLoaded ? 'Ask a question about the document...' : 'Upload a document to start chatting'}
            </p>
          ) : (
            messages.map((msg, idx) => (
              <div
                key={idx}
                style={{
                  marginBottom: '15px',
                  padding: '10px',
                  backgroundColor: msg.role === 'user' ? 'white' : '#f0f0f0',
                  border: '1px solid black',
                  borderLeft: msg.role === 'user' ? '4px solid black' : '4px solid #666'
                }}
              >
                <div style={{ fontSize: '12px', fontWeight: 'bold', marginBottom: '5px' }}>
                  {msg.role === 'user' ? 'YOU' : 'ASSISTANT'}
                </div>
                <div style={{ fontSize: '14px', whiteSpace: 'pre-wrap' }}>
                  {msg.content}
                </div>
              </div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div style={{ display: 'flex', gap: '10px' }}>
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyPress={handleKeyPress}
            disabled={!documentLoaded || querying}
            placeholder={documentLoaded ? 'Type your question...' : 'Upload a document first'}
            style={{
              flex: 1,
              padding: '10px',
              border: '1px solid black',
              fontSize: '14px',
              backgroundColor: documentLoaded ? 'white' : '#f0f0f0'
            }}
          />
          <button
            onClick={handleAskQuestion}
            disabled={!documentLoaded || !question.trim() || querying}
            style={{
              padding: '10px 20px',
              backgroundColor: (!documentLoaded || !question.trim() || querying) ? '#ccc' : 'black',
              color: 'white',
              border: 'none',
              cursor: (!documentLoaded || !question.trim() || querying) ? 'not-allowed' : 'pointer',
              fontSize: '14px'
            }}
          >
            {querying ? 'Asking...' : 'Ask'}
          </button>
        </div>
      </div>
    </div>
  )
}
