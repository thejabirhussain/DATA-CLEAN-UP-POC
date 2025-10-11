import React, { useEffect, useMemo, useRef, useState } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { ModuleRegistry, AllCommunityModule } from 'ag-grid-community'
import 'ag-grid-community/styles/ag-grid.css'
import 'ag-grid-community/styles/ag-theme-alpine.css'

// Register all community modules (required for AG Grid v34+)
ModuleRegistry.registerModules([AllCommunityModule])

export const API_BASE = 'http://localhost:8000'

// Inline utility components for status and loading
function Status({ message, type }) {
  if (!message) return null
  const isTiming = message.includes('completed in') || message.includes('Processing completed in') || message.includes('Execution time:') || message.includes('s!') || message.includes('seconds') || message.includes('ms')
  const statusType = isTiming ? 'timing' : type
  return <div className={`status ${statusType}`} style={{ display: 'block' }}>{message}</div>
}

function Loading({ show, children }) {
  if (!show) return null
  return <div className="loading">{children}</div>
}

export default function App() {
  // Global enable/disable parity with original UI
  const [transformEnabled, setTransformEnabled] = useState(false)
  const [chatEnabled, setChatEnabled] = useState(false)
  const [enableUndo, setEnableUndo] = useState(false)

  // Upload section state
  const fileRef = useRef(null)
  const [uploadStatus, setUploadStatus] = useState({ message: '', type: '' })
  const [uploadLoading, setUploadLoading] = useState(false)

  // Transform + follow-up state
  const [instruction, setInstruction] = useState('')
  const [transformStatus, setTransformStatus] = useState({ message: '', type: '' })
  const [transformLoading, setTransformLoading] = useState(false)
  const [sessionId, setSessionId] = useState(null)
  const [followupVisible, setFollowupVisible] = useState(false)
  const [followupMessage, setFollowupMessage] = useState('')
  const [followupQuestions, setFollowupQuestions] = useState([])
  const [followupAnswers, setFollowupAnswers] = useState([])

  // Chat state
  const [chatStatus, setChatStatus] = useState({ message: '', type: '' })
  const [chatLoading, setChatLoading] = useState(false)
  const [chatInput, setChatInput] = useState('')
  const [messages, setMessages] = useState([])
  const chatContainerRef = useRef(null)

  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight
    }
  }, [messages])

  // Data section state
  const [columns, setColumns] = useState([])
  const [data, setData] = useState([])
  const [totalRows, setTotalRows] = useState(0)
  const [page, setPage] = useState(1)
  const [rowsPerPage, setRowsPerPage] = useState(100)
  const [gridQuickFilter, setGridQuickFilter] = useState('')
  const [noDataMsg, setNoDataMsg] = useState('No data uploaded yet')

  // Data functions mirroring original logic
  const displayData = (preview, cols, total) => {
    if (preview && preview.length > 0) {
      setData(preview)
    }
    // If columns are not provided, derive them from the first row of the preview
    if (cols && cols.length) {
      setColumns(cols)
    } else if (preview && preview.length > 0) {
      setColumns(Object.keys(preview[0] || {}))
    } else {
      setColumns([])
    }
    setTotalRows(total || 0)
    if (!preview || preview.length === 0) {
      setNoDataMsg('No data available')
    }
  }

  const loadDataPage = async (targetPage) => {
    try {
      const resp = await fetch(`${API_BASE}/data?page=${targetPage}&rows_per_page=${rowsPerPage}`)
      const result = await resp.json()
      if (resp.ok) {
        setPage(targetPage)
        displayData(result.data, result.columns, result.total_rows)
      } else {
        // keep silent to mirror original minimal error handling here
      }
    } catch (e) {
      // keep silent to mirror original minimal error handling here
    }
  }

  const previousPage = async () => { if (page > 1) await loadDataPage(page - 1) }
  const nextPage = async () => {
    const totalPages = Math.max(1, Math.ceil(totalRows / rowsPerPage))
    if (page < totalPages) await loadDataPage(page + 1)
  }
  const changeRpp = async (rpp) => { setRowsPerPage(rpp); setPage(1); await loadDataPage(1) }

  const refreshFirstPage = async () => { await loadDataPage(1) }

  // Upload
  const uploadFile = async () => {
    const file = fileRef.current?.files?.[0]
    if (!file) {
      setUploadStatus({ message: 'Please select a file first', type: 'error' })
      return
    }
    const formData = new FormData()
    formData.append('file', file)
    setUploadLoading(true)
    try {
      const resp = await fetch(`${API_BASE}/upload`, { method: 'POST', body: formData })
      const result = await resp.json()
      if (resp.ok) {
        setUploadStatus({ message: `File uploaded successfully! ${result.total_rows} rows, ${result.columns.length} columns`, type: 'success' })
        setTransformEnabled(true)
        setChatEnabled(true)
        displayData(result.preview, result.columns, result.total_rows)
        setEnableUndo(false)
      } else {
        setUploadStatus({ message: `Upload failed: ${result.detail}`, type: 'error' })
      }
    } catch (e) {
      setUploadStatus({ message: `Upload error: ${e.message}`, type: 'error' })
    } finally {
      setUploadLoading(false)
    }
  }

  // Transform
  const transformData = async () => {
    const text = instruction.trim()
    if (!text) {
      setTransformStatus({ message: 'Please enter an instruction', type: 'error' })
      return
    }
    const startTime = performance.now()
    setTransformLoading(true)
    try {
      const requestBody = { instruction: text }
      if (sessionId) requestBody.session_id = sessionId
      const resp = await fetch(`${API_BASE}/transform`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(requestBody) })
      const result = await resp.json()
      if (result.success) {
        setSessionId(result.session_id || null)
        if (result.type === 'clarification_needed') {
          setFollowupVisible(true)
          setFollowupMessage(result.message)
          setFollowupQuestions(result.questions || [])
          setFollowupAnswers((result.questions || []).map(() => ''))
          setTransformStatus({ message: 'Additional information needed. Please answer the questions below.', type: 'info' })
        } else {
          const endTime = performance.now()
          const executionTime = ((endTime - startTime) / 1000).toFixed(2)
          let msg = ''
          if (result.type === 'transformation') {
            msg = `Transformation completed in ${executionTime}s! Result: ${result.result_shape[0]} rows × ${result.result_shape[1]} columns`
            displayData(result.preview, result.result_columns, result.total_rows)
            setEnableUndo(true)
          } else {
            msg = `Processing completed in ${executionTime}s! ${result.message || 'Operation successful'}`
          }

          setTransformStatus({ message: msg, type: 'success' })
          setInstruction('')
          setSessionId(null)
          setFollowupVisible(false)
          setFollowupMessage('')
          setFollowupQuestions([])
          setFollowupAnswers([])
        }
      } else {
        setTransformStatus({ message: `Transformation failed: ${result.error}`, type: 'error' })
        setSessionId(null)
        setFollowupVisible(false)
        setFollowupMessage('')
        setFollowupQuestions([])
        setFollowupAnswers([])
      }
    } catch (e) {
      setTransformStatus({ message: `Transform error: ${e.message}`, type: 'error' })
      setSessionId(null)
      setFollowupVisible(false)
      setFollowupMessage('')
      setFollowupQuestions([])
      setFollowupAnswers([])
    } finally {
      setTransformLoading(false)
    }
  }

  const undo = async () => {
    setTransformLoading(true)
    setEnableUndo(false)
    try {
      const resp = await fetch(`${API_BASE}/undo`, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
      const result = await resp.json()
      if (result.success) {
        setTransformStatus({ message: 'Successfully undone last transformation!', type: 'success' })
        displayData(result.preview, result.result_columns, result.total_rows)
      } else {
        setTransformStatus({ message: `Undo failed: ${result.error}`, type: 'error' })
      }
    } catch (e) {
      setTransformStatus({ message: `Undo error: ${e.message}`, type: 'error' })
    } finally {
      setTransformLoading(false)
      setEnableUndo(true)
    }
  }

  const submitFollowup = async () => {
    if (!sessionId) {
      setTransformStatus({ message: 'No active session for follow-up', type: 'error' })
      return
    }
    const startTime = performance.now()
    setTransformLoading(true)
    try {
      const resp = await fetch(`${API_BASE}/follow-up`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: sessionId, responses: followupAnswers }) })
      const result = await resp.json()
      if (result.success) {
        const endTime = performance.now()
        const executionTime = ((endTime - startTime) / 1000).toFixed(2)
        let msg = ''
        if (result.type === 'transformation') {
          msg = `Transformation completed in ${executionTime}s! Result: ${result.result_shape[0]} rows × ${result.result_shape[1]} columns`
          displayData(result.preview, result.result_columns, result.total_rows)
        } else {
          msg = `Processing completed in ${executionTime}s! ${result.message || 'Operation successful'}`
        }

        setTransformStatus({ message: msg, type: 'success' })
        setSessionId(null)
        setFollowupVisible(false)
        setFollowupMessage('')
        setFollowupQuestions([])
        setFollowupAnswers([])
      } else {
        setTransformStatus({ message: `Follow-up processing failed: ${result.error}`, type: 'error' })
      }
    } catch (e) {
      setTransformStatus({ message: `Follow-up error: ${e.message}`, type: 'error' })
    } finally {
      setTransformLoading(false)
    }
  }

  const cancelFollowup = () => {
    setFollowupVisible(false)
    setSessionId(null)
    setTransformStatus({ message: 'Follow-up cancelled. You can try a different instruction.', type: 'info' })
  }

  // Chat
  const addChatMessage = (role, text) => setMessages((prev) => [...prev, { role, text }])

  const sendChat = async () => {
    const message = chatInput.trim()
    if (!message) {
      setChatStatus({ message: 'Please enter a message', type: 'error' })
      return
    }
    addChatMessage('user', message)
    setChatInput('')
    setChatLoading(true)
    try {
      const resp = await fetch(`${API_BASE}/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message }) })
      const result = await resp.json()
      if (result.success) {
        addChatMessage('assistant', result.message)
        if (result.dataframe_updated) {
          await refreshFirstPage()
          setEnableUndo(true)
        }
      } else {
        addChatMessage('assistant', `Sorry, I encountered an error: ${result.error}`)
      }
    } catch (e) {
      addChatMessage('assistant', `Sorry, I'm having connection issues: ${e.message}`)
      setChatStatus({ message: `Connection error: ${e.message}`, type: 'error' })
    } finally {
      setChatLoading(false)
    }
  }

  const onChatKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendChat()
    }
  }

  const showingStart = (page - 1) * rowsPerPage + 1
  const showingEnd = Math.min(page * rowsPerPage, totalRows)
  const totalPages = Math.max(1, Math.ceil(totalRows / rowsPerPage))

  // ag-Grid column and row config derived from existing columns/data
  const columnDefs = useMemo(
    () => (columns || []).map((c) => ({
      field: c,
      headerName: c,
      sortable: true,
      filter: true,
      resizable: true,
      flex: 1,
    })),
    [columns]
  )

  const rowData = useMemo(() => (data || []).map((row) => ({ ...row })), [data])

  const defaultColDef = useMemo(() => ({
    resizable: true,
    sortable: true,
    filter: true,
    // floatingFilter adds a row under the headers. Disable to remove the extra row look.
    floatingFilter: false,
    editable: true,
    flex: 1,
  }), [])

  const gridApiRef = useRef(null)
  const columnApiRef = useRef(null)

  const onGridReady = (params) => {
    gridApiRef.current = params.api
    columnApiRef.current = params.columnApi
    // Auto-size all columns to fit content and container width
    const allIds = params.columnApi.getAllColumns()?.map(col => col.getId()) || []
    if (allIds.length) {
      params.columnApi.autoSizeColumns(allIds, false)
    }
    params.api.sizeColumnsToFit()
  }

  const onCellValueChanged = (event) => {
    // Update local data array to reflect edits; backend is unchanged
    const idx = event.node?.rowIndex
    if (idx != null) {
      setData((prev) => {
        const next = Array.isArray(prev) ? [...prev] : []
        next[idx] = { ...(next[idx] || {}), [event.colDef.field]: event.newValue }
        return next
      })
    }
  }

  return (
    <div className="container">
      <h1>Excel NLP Transformer</h1>

      {/* Upload Section */}
      <div className="section">
        <h2>1. Upload Excel File</h2>
        <input type="file" accept=".xlsx,.xls,.csv" ref={fileRef} />
        <button onClick={uploadFile} disabled={uploadLoading}>Upload File</button>
        <Loading show={uploadLoading}>Uploading...</Loading>
        <Status message={uploadStatus.message} type={uploadStatus.type} />
      </div>

      {/* Transform Section */}
      <div className="section">
        <h2>2. Transform Data with Natural Language</h2>
        <textarea value={instruction} onChange={(e) => setInstruction(e.target.value)} placeholder="Enter your instruction (e.g., 'Concatenate first name and last name columns')" />
        <div>
          <button onClick={transformData} disabled={transformLoading}>Transform Data</button>
          <button onClick={undo} disabled={!enableUndo} style={{ marginLeft: 10, backgroundColor: '#6c757d' }}>Undo</button>
        </div>
        <Loading show={transformLoading}>Processing...</Loading>
        <Status message={transformStatus.message} type={transformStatus.type} />

        {followupVisible && (
          <div id="followupSection" style={{ display: 'block', marginTop: 20, padding: 15, backgroundColor: '#f8f9fa', borderRadius: 5 }}>
            <h3>Additional Information Needed</h3>
            <p>{followupMessage}</p>
            <div>
              {followupQuestions.map((q, i) => (
                <div key={i} style={{ marginBottom: '15px' }}>
                  <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>{`${i + 1}. ${q}`}</label>
                  <textarea
                    value={followupAnswers[i] || ''}
                    onChange={(e) => {
                      const next = [...followupAnswers]
                      next[i] = e.target.value
                      setFollowupAnswers(next)
                    }}
                    placeholder="Enter your response..."
                    style={{ width: '100%', height: '60px', marginBottom: '5px', padding: '8px', border: '1px solid #ddd', borderRadius: '3px' }}
                  />
                </div>
              ))}
            </div>
            <button onClick={submitFollowup}>Submit Responses</button>
            <button onClick={cancelFollowup} style={{ backgroundColor: '#6c757d' }}>Cancel</button>
          </div>
        )}
      </div>

      {/* Chat Section */}
      <div className="section">
        <h2>Chat with AI Assistant</h2>
        <div id="chatContainer" ref={chatContainerRef} style={{ height: 400, overflowY: 'auto', border: '1px solid #ddd', padding: 15, marginBottom: 15, background: '#f9f9f9', borderRadius: 8 }}>
          <div id="chatMessages">
            {messages.map((m, idx) => (
              <div key={idx} style={{ marginBottom: 15, padding: 10, borderRadius: 8, backgroundColor: m.role === 'user' ? '#f8f9fa' : '#e9ecef', marginLeft: m.role === 'user' ? '20%' : 0, marginRight: m.role === 'assistant' ? '20%' : 0 }}>
                {m.text}
              </div>
            ))}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <textarea value={chatInput} onChange={(e) => setChatInput(e.target.value)} onKeyPress={onChatKeyPress} placeholder="Ask me anything about your data or request transformations..." style={{ flex: 1, height: 60 }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            <button onClick={sendChat} disabled={!chatEnabled || chatLoading}>Send</button>
            <button onClick={() => setMessages([])} style={{ backgroundColor: '#6c757d', fontSize: '0.9em' }}>Clear</button>
          </div>
        </div>
        <Loading show={chatLoading}>AI is thinking...</Loading>
        <Status message={chatStatus.message} type={chatStatus.type} />
      </div>

      {/* Data Section */}
      <div className="section">
        <h2>3. Data Preview</h2>
        {totalRows > 0 ? (
          <div id="dataInfo" style={{ display: 'block' }}>
            <strong>Total Rows:</strong> {totalRows} | <strong>Showing:</strong> {showingStart}-{showingEnd}
          </div>
        ) : null}

        <div id="paginationControls" className="pagination-controls" style={{ display: totalRows > 0 ? 'flex' : 'none' }}>
          <button onClick={previousPage} disabled={page === 1}>← Previous</button>
          <span id="pageInfo">{`Page ${page} of ${totalPages}`}</span>
          <button onClick={nextPage} disabled={page === totalPages}>Next →</button>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <label htmlFor="rowsPerPage">Rows per page:</label>
            <select id="rowsPerPage" value={rowsPerPage} onChange={(e) => changeRpp(parseInt(e.target.value, 10))}>
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </div>
        </div>

        {/* Quick filter for grid (client-side, current page only) */}
        {(columns || []).length > 0 && (
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 10 }}>
            <input
              type="text"
              placeholder="Quick filter..."
              value={gridQuickFilter}
              onChange={(e) => setGridQuickFilter(e.target.value)}
              style={{ padding: '8px 10px', border: '1px solid #ced4da', borderRadius: 4, minWidth: 220 }}
            />
          </div>
        )}

        <div className="table-container">
          {(!data || data.length === 0 || (columns || []).length === 0) ? (
            <div className="no-data">{noDataMsg}</div>
          ) : (
            <div className="ag-theme-alpine" style={{ height: 600, width: '100%' }}>
              <AgGridReact
                columnDefs={columnDefs}
                rowData={rowData}
                defaultColDef={defaultColDef}
                animateRows={true}
                rowSelection="single"
                suppressPaginationPanel={true}
                suppressFieldDotNotation={true}
                domLayout="normal"
                headerHeight={42}
                rowHeight={38}
                singleClickEdit={true}
                quickFilterText={gridQuickFilter}
                pagination={true}
                paginationPageSize={rowsPerPage}
                onCellValueChanged={onCellValueChanged}
                onGridReady={onGridReady}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
