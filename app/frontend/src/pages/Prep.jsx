import React, { useEffect, useRef } from 'react'
import * as XLSX from 'xlsx'
import * as arrow from 'apache-arrow'
import initWasm, { readParquet, Table as ParquetTable, writeParquet, WriterPropertiesBuilder, Compression } from 'parquet-wasm'
import parquetWasmUrl from 'parquet-wasm/esm/parquet_wasm_bg.wasm?url'

// API base to mirror demo.jsx
const API_BASE = 'http://localhost:8000'

export default function Prep(){
  const rootRef = useRef(null)

  useEffect(() => {
    const root = rootRef.current; if (!root) return
    if (root.dataset.bound === '1') return
    root.dataset.bound = '1'
    // State
    let ORIGINAL = []
    let EDITED = []
    let COLUMNS = []
    let BASE_COLUMNS = []
    let PIPELINE = []
    let PAGE_SIZE = 50
    let CURRENT_PAGE = 1
    let parquetReady = false
    let TOTAL_ROWS = 0

    // History (track displayed rows/columns snapshots for manual edits and API-driven changes)
    let HISTORY = []
    let FUTURE = []
    const snapshot = () => ({ rows: clone(EDITED), columns: clone(COLUMNS) })
    let updateHistoryInfo = () => {}
    function pushHistory(){ HISTORY.push(snapshot()); if (HISTORY.length>100) HISTORY.shift(); FUTURE = []; updateHistoryInfo() }
    function canUndo(){ return HISTORY.length > 0 }
    function canRedo(){ return FUTURE.length > 0 }
    async function apiUndo(){
      try{
        const resp = await fetch(`${API_BASE}/undo`, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
        const result = await resp.json()
        if (result.success){
          displayData(result.preview, result.result_columns, result.total_rows)
          updateHistoryInfo()
        }
      } catch(e){ console.warn('Undo failed', e) }
    }

    function setTransformStatus(message, type=''){
      if (!transformStatusEl) return
      transformStatusEl.textContent = message || ''
      transformStatusEl.dataset.type = type || ''
    }
    function undo(){
      if (!canUndo()) return
      const prev = HISTORY.pop()
      FUTURE.push(snapshot())
      EDITED = clone(prev.rows)
      COLUMNS = clone(prev.columns)
      renderTable(); updateHistoryInfo()
    }
    function redo(){
      if (!canRedo()) return
      const next = FUTURE.pop()
      HISTORY.push(snapshot())
      EDITED = clone(next.rows)
      COLUMNS = clone(next.columns)
      renderTable(); updateHistoryInfo()
    }

    // DOM
    const $ = (id) => root.querySelector('#'+id)
    const fileInput = $("file-input"); const pickBtn = $("pick-file"); const dropzone = $("dropzone"); const fileNameEl = $("file-name")
    const exportCSVBtn = $("export-csv"); const exportXLSXBtn = $("export-xlsx"); const exportJSONBtn = $("export-json"); const exportParquetBtn = $("export-parquet"); const saveRecipeBtn = $("save-recipe"); const loadRecipeBtn = $("load-recipe"); const recipeInput = $("recipe-input")
    const undoBtn = $("undo"); const redoBtn = $("redo"); const historyInfo = $("history-info")
    const chatSidebar = $("chat-sidebar"); const chatMessages = $("chat-messages"); const chatInput = $("chat-input"); const chatSend = $("chat-send"); const chatClear = $("chat-clear"); const mainSection = $("main-section"); const sidebarToggle = $("sidebar-toggle"); const llmSelect = $("llm-select"); const llmActiveLabel = $("llm-active")
    // Transform DOM (mirroring demo.jsx)
    const instructionEl = $("instruction"); const transformBtn = $("transform-btn"); const undoBackendBtn = $("undo-backend"); const transformStatusEl = $("transform-status")
    const followupSection = $("followupSection"); const followupMsgEl = $("followupMessage"); const followupQsEl = $("followupQuestions"); const followupSubmitBtn = $("followupSubmit"); const followupCancelBtn = $("followupCancel")
    const rowsPerPageEl = $("rowsPerPage")
    const thead = $("thead"); const tbody = $("tbody"); const rowCount = $("row-count"); const pagingInfo = $("paging-info"); const pageInput = $("page"); const prevBtn = $("prev"); const nextBtn = $("next"); const searchInput = $("search"); const clearEditsBtn = $("clear-edits")
    const readinessList = $("readiness-list")

    // Chat state
    let MESSAGES = []
    let selectedLLM = 'gemini'
    // initialize LLM selector UI
    if (llmSelect){
      llmSelect.value = selectedLLM
      llmSelect.addEventListener('change', () => { 
        selectedLLM = llmSelect.value || 'gemini'
        if (llmActiveLabel) {
          const displayName = llmSelect.options[llmSelect.selectedIndex].text
          llmActiveLabel.textContent = displayName
        }
      })
    }
    if (llmActiveLabel) llmActiveLabel.textContent = 'Gemini 2.5 Flash'
    // Transform state
    let transformLoading = false
    let sessionId = null

    const clone = (x) => JSON.parse(JSON.stringify(x))
    const toTitle = (s) => s.replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.substring(1).toLowerCase())

    // Display helper: render chat messages
    function renderChat(){
      if (!chatMessages) return
      chatMessages.innerHTML = ''
      MESSAGES.forEach(m => {
        const div = document.createElement('div')
        const isUser = m.role === 'user'
        div.className = `max-w-[80%] mb-2 px-3 py-2 rounded-2xl text-sm ${isUser? 'bg-emerald-600 text-white ml-auto' : 'bg-slate-100 text-slate-800 mr-auto'}`
        div.textContent = m.text
        chatMessages.appendChild(div)
      })
      chatMessages.parentElement && (chatMessages.parentElement.scrollTop = chatMessages.parentElement.scrollHeight)
    }

    function refreshColumnSelect(){ /* removed Add Transform UI */ }

    function updateReadiness(){
      if (!readinessList) return
      const required = ['entity_id','legal_entity_name','erp_account_code','natural_account','account_name','amount','currency','period','posting_date']
      readinessList.innerHTML = ''
      required.forEach((req) => {
        const has = COLUMNS.includes(req)
        const li = document.createElement('li')
        li.className = 'flex items-center gap-2'
        li.innerHTML = `<span class="inline-block w-2.5 h-2.5 rounded-full ${has ? 'bg-emerald-500' : 'bg-slate-300'}"></span>
                        <span class="${has ? 'text-slate-700' : 'text-slate-400'}">${req}</span>`
        readinessList.appendChild(li)
      })
    }

    function enableHeaderDrag(){
      const headers = thead.querySelectorAll('th')
      let dragIndex = null
      headers.forEach(th => {
        th.setAttribute('draggable','true')
        th.addEventListener('dragstart', (e) => { dragIndex = Number(th.dataset.colIndex) })
        th.addEventListener('dragover', (e) => { e.preventDefault(); const idx = Number(th.dataset.colIndex); th.classList.toggle('th-drop-left', dragIndex>idx); th.classList.toggle('th-drop-right', dragIndex<idx) })
        th.addEventListener('dragleave', () => { th.classList.remove('th-drop-left','th-drop-right') })
        th.addEventListener('drop', () => { const idx = Number(th.dataset.colIndex); th.classList.remove('th-drop-left','th-drop-right'); if (dragIndex===null || dragIndex===idx) return; const col = COLUMNS.splice(dragIndex,1)[0]; COLUMNS.splice(idx,0,col); pushHistory(); renderTable() })
      })
    }

    function renderTable(){
      rowCount.textContent = TOTAL_ROWS
      thead.innerHTML = ''
      const trh = document.createElement('tr')
      COLUMNS.forEach((c, idx) => {
        const th = document.createElement('th')
        th.className = `px-3 py-2 text-left text-xs font-semibold text-slate-700 border-b border-slate-200 ${idx===0 ? 'sticky-col' : ''}`
        th.textContent = c
        th.dataset.colIndex = idx
        trh.appendChild(th)
      })
      thead.appendChild(trh)
      enableHeaderDrag()

      const totalPages = Math.max(1, Math.ceil(TOTAL_ROWS / PAGE_SIZE))
      CURRENT_PAGE = Math.min(CURRENT_PAGE, totalPages)
      const pageStartNum = (CURRENT_PAGE - 1) * PAGE_SIZE + 1
      const pageEndNum = Math.min(CURRENT_PAGE * PAGE_SIZE, TOTAL_ROWS)

      tbody.innerHTML = ''
      for (let i=0; i<EDITED.length; i++){
        const r = EDITED[i]
        if (!r) continue
        const tr = document.createElement('tr')
        COLUMNS.forEach((c, idx) => {
          const td = document.createElement('td')
          td.className = `px-3 py-1 border-b border-slate-100 ${idx===0 ? 'sticky-col' : ''}`
          const input = document.createElement('input')
          input.value = r[c] ?? ''
          input.className = 'w-full bg-transparent outline-none text-sm'
          input.addEventListener('change', (e) => { pushHistory(); r[c] = e.target.value; updateHistoryInfo() })
          td.appendChild(input)
          tr.appendChild(td)
        })
        tbody.appendChild(tr)
      }

      pageInput.value = CURRENT_PAGE
      prevBtn.disabled = CURRENT_PAGE <= 1
      nextBtn.disabled = CURRENT_PAGE >= totalPages
      pagingInfo.textContent = `Page ${CURRENT_PAGE} / ${totalPages} (rows ${pageStartNum}-${pageEndNum})`

      refreshColumnSelect(); updateReadiness(); toggleControls(true)
    }

    function toggleControls(hasData){ exportCSVBtn.disabled = !hasData; exportXLSXBtn.disabled = !hasData; if (exportJSONBtn) exportJSONBtn.disabled = !hasData; if (exportParquetBtn) exportParquetBtn.disabled = !hasData; saveRecipeBtn.disabled = !hasData; if (clearEditsBtn) clearEditsBtn.disabled = !hasData }

    async function ensureParquetInit(){ if (parquetReady) return; await initWasm(parquetWasmUrl); parquetReady = true }

    function tableToRows(arrowTable){ const cols = arrowTable.schema.fields.map(f => f.name); const n = arrowTable.numRows; const rows = new Array(n); const vectors = cols.map(name => arrowTable.getColumn(name)); for (let i=0;i<n;i++){ const obj={}; for (let c=0;c<cols.length;c++) obj[cols[c]] = vectors[c]?.get(i) ?? null; rows[i]=obj } return { rows, cols } }
    function rowsToArrowTable(rows, cols){ const arrays={}; const headers = cols && cols.length ? cols : Object.keys(rows[0]||{}); headers.forEach(h => arrays[h] = rows.map(r => r[h])); return arrow.tableFromArrays(arrays) }

    // API-powered data display (mirror demo.jsx)
    function displayData(preview, cols, total){
      if (Array.isArray(preview) && preview.length){
        EDITED = clone(preview)
      }
      if (Array.isArray(cols) && cols.length){
        COLUMNS = clone(cols)
      } else if (Array.isArray(preview) && preview.length){
        COLUMNS = Object.keys(preview[0] || {})
      } else {
        COLUMNS = []
      }
      TOTAL_ROWS = total || 0
      ORIGINAL = clone(EDITED)
      renderTable()
    }

    async function loadDataPage(targetPage){
      try{
        const resp = await fetch(`${API_BASE}/data?page=${targetPage}&rows_per_page=${PAGE_SIZE}`)
        const result = await resp.json()
        if (resp.ok){ CURRENT_PAGE = targetPage; displayData(result.data, result.columns, result.total_rows) }
      } catch(e){ /* silent */ }
    }

    // Transform logic (mirroring demo.jsx)
    async function transformData(){
      const text = (instructionEl?.value || '').trim()
      if (!text){ setTransformStatus('Please enter an instruction', 'error'); return }
      const startTime = performance.now(); transformLoading = true; if (transformBtn){ transformBtn.disabled = true; transformBtn.textContent = 'Transforming…'; transformBtn.classList.add('opacity-70') }
      try{
        const body = { instruction: text }
        if (sessionId) body.session_id = sessionId
        const resp = await fetch(`${API_BASE}/transform`, { method:'POST', headers:{ 'Content-Type':'application/json' }, body: JSON.stringify(body) })
        const result = await resp.json()
        if (result.success){
          sessionId = result.session_id || null
          if (result.type === 'clarification_needed'){
            if (followupSection && followupMsgEl && followupQsEl){
              followupSection.classList.remove('hidden')
              followupMsgEl.textContent = result.message || ''
              followupQsEl.innerHTML = ''
              ;(result.questions||[]).forEach((q, idx) => {
                const div = document.createElement('div')
                div.className = 'mb-2'
                div.innerHTML = `<label class="block text-sm font-medium mb-1">${idx+1}. ${q}</label><textarea data-idx="${idx}" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" rows="2" placeholder="Enter your response..."></textarea>`
                followupQsEl.appendChild(div)
              })
            }
            setTransformStatus('Additional information needed. Please answer the questions below.', 'info')
          } else {
            const endTime = performance.now()
            const executionTime = ((endTime - startTime)/1000).toFixed(2)
            let msg = ''
            if (result.type === 'transformation'){
              msg = `Transformation completed in ${executionTime}s! Result: ${result.result_shape[0]} rows × ${result.result_shape[1]} columns`
              pushHistory(); await loadDataPage(1)
            } else {
              msg = `Processing completed in ${executionTime}s! ${result.message || 'Operation successful'}`
            }
            if (result.execution_log && result.execution_log.includes('Execution time:')){
              const m = result.execution_log.match(/Execution time: ([\d.]+)s/); if (m) msg += ` (Backend: ${m[1]}s)`
            }
            setTransformStatus(msg, 'success')
            if (instructionEl) instructionEl.value = ''
            sessionId = null
            if (followupSection){ followupSection.classList.add('hidden') }
            if (followupQsEl) followupQsEl.innerHTML = ''
          }
        } else {
          setTransformStatus(`Transformation failed: ${result.error}`, 'error'); sessionId = null; if (followupSection){ followupSection.classList.add('hidden') }
        }
      } catch(e){ setTransformStatus(`Transform error: ${e.message}`, 'error'); sessionId = null; if (followupSection){ followupSection.classList.add('hidden') } }
      finally{ transformLoading = false; if (transformBtn){ transformBtn.disabled = false; transformBtn.textContent = 'Transform Data'; transformBtn.classList.remove('opacity-70') } }
    }

    async function undoBackend(){
      try{
        const resp = await fetch(`${API_BASE}/undo`, { method:'POST', headers:{ 'Content-Type':'application/json' } })
        const result = await resp.json()
        if (result.success){ setTransformStatus('Successfully undone last transformation!', 'success'); await loadDataPage(1) }
        else { setTransformStatus(`Undo failed: ${result.error}`, 'error') }
      } catch(e){ setTransformStatus(`Undo error: ${e.message}`, 'error') }
    }

    async function submitFollowup(){
      if (!sessionId){ setTransformStatus('No active session for follow-up', 'error'); return }
      const startTime = performance.now(); transformLoading = true
      try{
        const answers = Array.from(followupQsEl?.querySelectorAll('textarea')||[]).map(t => t.value)
        const resp = await fetch(`${API_BASE}/follow-up`, { method:'POST', headers:{ 'Content-Type':'application/json' }, body: JSON.stringify({ session_id: sessionId, responses: answers }) })
        const result = await resp.json()
        if (result.success){
          const endTime = performance.now(); const executionTime = ((endTime - startTime)/1000).toFixed(2)
          let msg = ''
          if (result.type === 'transformation'){
            msg = `Transformation completed in ${executionTime}s! Result: ${result.result_shape[0]} rows × ${result.result_shape[1]} columns`
            pushHistory(); await loadDataPage(1)
          } else { msg = `Processing completed in ${executionTime}s! ${result.message || 'Operation successful'}` }
          if (result.execution_log && result.execution_log.includes('Execution time:')){
            const m = result.execution_log.match(/Execution time: ([\d.]+)s/); if (m) msg += ` (Backend: ${m[1]}s)`
          }
          setTransformStatus(msg, 'success'); sessionId = null; if (followupSection){ followupSection.classList.add('hidden') }; if (followupQsEl) followupQsEl.innerHTML = ''
        } else { setTransformStatus(`Follow-up processing failed: ${result.error}`, 'error') }
      } catch(e){ setTransformStatus(`Follow-up error: ${e.message}`, 'error') }
      finally{ transformLoading = false }
    }

    function cancelFollowup(){
      if (followupSection) followupSection.classList.add('hidden')
      if (followupQsEl) followupQsEl.innerHTML = ''
      sessionId = null
      setTransformStatus('Follow-up cancelled. You can try a different instruction.', 'info')
    }

    async function handleFiles(files){
      if (!files || !files[0]) return
      const f = files[0]
      fileNameEl.textContent = f.name
      const formData = new FormData()
      formData.append('file', f)
      try{
        const resp = await fetch(`${API_BASE}/upload`, { method: 'POST', body: formData })
        const result = await resp.json()
        if (resp.ok){ displayData(result.preview, result.columns, result.total_rows); HISTORY = []; FUTURE = []; updateHistoryInfo() }
      } catch(e){ console.warn('Upload failed', e) }
    }

    pickBtn.addEventListener('click', () => fileInput.click())
    fileInput.addEventListener('change', (e) => handleFiles(e.target.files))
    ;['dragenter','dragover'].forEach(evt => dropzone.addEventListener(evt, (e) => { e.preventDefault(); dropzone.classList.add('bg-emerald-50') }))
    ;['dragleave','drop'].forEach(evt => dropzone.addEventListener(evt, (e) => { e.preventDefault(); dropzone.classList.remove('bg-emerald-50') }))
    dropzone.addEventListener('drop', (e) => handleFiles(e.dataTransfer.files))

    // Search & paging
    searchInput.addEventListener('input', () => { const q = searchInput.value.toLowerCase(); if (!q) { EDITED = clone(ORIGINAL); renderTable(); return } EDITED = ORIGINAL.filter(r => COLUMNS.some(c => String(r[c] ?? '').toLowerCase().includes(q))); renderTable() })
    clearEditsBtn.addEventListener('click', () => { EDITED = clone(ORIGINAL); renderTable() })
    prevBtn.addEventListener('click', async () => { if (CURRENT_PAGE > 1) await loadDataPage(CURRENT_PAGE - 1) })
    nextBtn.addEventListener('click', async () => { const totalPages = Math.max(1, Math.ceil(TOTAL_ROWS / PAGE_SIZE)); if (CURRENT_PAGE < totalPages) await loadDataPage(CURRENT_PAGE + 1) })
    pageInput.addEventListener('change', async () => { const totalPages = Math.max(1, Math.ceil(TOTAL_ROWS / PAGE_SIZE)); const p = Math.max(1, Math.min(totalPages, parseInt(pageInput.value||'1',10))); await loadDataPage(p) })

    // Sidebar toggle behavior: flex row, sidebar width animates to 0 without vertical reflow
    function setSidebar(open){
      if (!chatSidebar || !mainSection) return
      if (open){
        chatSidebar.classList.remove('w-0','opacity-0','-translate-x-3','pointer-events-none')
        chatSidebar.classList.add('w-[360px]')
        if (sidebarToggle) sidebarToggle.textContent = 'Close Menu'
      } else {
        chatSidebar.classList.remove('w-[360px]')
        chatSidebar.classList.add('w-0','opacity-0','-translate-x-3','pointer-events-none')
        if (sidebarToggle) sidebarToggle.textContent = 'Open Menu'
      }
      if (sidebarToggle) sidebarToggle.setAttribute('aria-expanded', String(open))
    }
    let sidebarOpen = true
    setSidebar(sidebarOpen)
    if (sidebarToggle) sidebarToggle.addEventListener('click', () => { sidebarOpen = !sidebarOpen; setSidebar(sidebarOpen) })

    if (undoBtn) undoBtn.addEventListener('click', async () => { if (canUndo()) { undo() } else { await apiUndo() } })
    if (redoBtn) redoBtn.addEventListener('click', redo)
    window.addEventListener('keydown', (e) => { const z = (e.key === 'z' || e.key === 'Z'); if ((e.metaKey || e.ctrlKey) && z && !e.shiftKey) { e.preventDefault(); undo() } if ((e.metaKey || e.ctrlKey) && z && e.shiftKey) { e.preventDefault(); redo() } })

    function updateHistoryUI(){
      const undoAvail = canUndo()
      const redoAvail = canRedo()
      const setBtnState = (btn, enabled, title) => {
        if (!btn) return
        btn.disabled = !enabled
        btn.classList.toggle('opacity-50', !enabled)
        btn.classList.toggle('cursor-not-allowed', !enabled)
        btn.classList.toggle('hover:bg-slate-200', enabled)
        btn.classList.toggle('bg-emerald-50', enabled)
        btn.classList.toggle('text-emerald-800', enabled)
        btn.setAttribute('title', title)
        const badge = btn.querySelector('.badge')
        if (badge) badge.textContent = enabled ? (title.match(/\((\d+)\)/)?.[1] || '') : ''
      }
      const undoTitle = `Undo (Ctrl+Z)${undoAvail ? ` — (${HISTORY.length})` : ''}`
      const redoTitle = `Redo (Ctrl+Y or Ctrl+Shift+Z)${redoAvail ? ` — (${FUTURE.length})` : ''}`
      setBtnState(undoBtn, undoAvail, undoTitle)
      setBtnState(redoBtn, redoAvail, redoTitle)
      if (historyInfo) historyInfo.textContent = `undo:${HISTORY.length} redo:${FUTURE.length}`
    }
    updateHistoryInfo = updateHistoryUI

    // Chat send
    function addChatMessage(role, text){ MESSAGES.push({ role, text }); renderChat() }
    async function sendChat(){
      if (!chatInput) return
      const message = (chatInput.value||'').trim(); if (!message) return
      addChatMessage('user', message); chatInput.value = ''
      const prevLabel = chatSend ? chatSend.textContent : ''
      if (chatSend){ chatSend.disabled = true; chatSend.textContent = 'Sending…'; chatSend.classList.add('opacity-70') }
      try{
        const resp = await fetch(`${API_BASE}/chat`, { method:'POST', headers:{ 'Content-Type':'application/json' }, body: JSON.stringify({ message, model: selectedLLM }) })
        const result = await resp.json()
        if (result.success){
          addChatMessage('assistant', result.message)
          if (result.dataframe_updated){ pushHistory(); await loadDataPage(1) }
        } else { addChatMessage('assistant', `Sorry, I encountered an error: ${result.error}`) }
      } catch(e){ addChatMessage('assistant', `Sorry, I'm having connection issues: ${e.message}`) }
      finally{ if (chatSend){ chatSend.disabled = false; chatSend.textContent = prevLabel || 'Send'; chatSend.classList.remove('opacity-70') } }
    }
    if (chatSend) chatSend.addEventListener('click', sendChat)
    if (chatInput) chatInput.addEventListener('keydown', (e) => { if (e.key==='Enter' && !e.shiftKey){ e.preventDefault(); sendChat() } })
    if (chatClear) chatClear.addEventListener('click', () => { MESSAGES = []; renderChat() })
    if (transformBtn) transformBtn.addEventListener('click', transformData)
    if (undoBackendBtn) undoBackendBtn.addEventListener('click', undoBackend)
    if (followupSubmitBtn) followupSubmitBtn.addEventListener('click', submitFollowup)
    if (followupCancelBtn) followupCancelBtn.addEventListener('click', () => { if (followupSection) followupSection.classList.add('hidden'); if (followupQsEl) followupQsEl.innerHTML = ''; sessionId = null; setTransformStatus('Follow-up cancelled. You can try a different instruction.', 'info') })
    if (rowsPerPageEl) rowsPerPageEl.addEventListener('change', async (e) => { PAGE_SIZE = parseInt(e.target.value,10) || 50; await loadDataPage(1) })

    // removed addStep/pipeline UI

    function collectParams(){ const params = {}; ['p-find','p-repl','p-regex','p-fill','p-delim','p-base','p-max','p-reg','p-newname','p-expr','p-cols','p-opr','p-const','p-col2'].forEach(id => { const el = $(id); if (el) params[id] = el.value }); return params }

    // Apply all enabled steps in order, resetting from ORIGINAL each time
    function applyPipeline(){
      EDITED = clone(ORIGINAL)
      // Reset columns to baseline before re-applying steps to avoid duplications
      COLUMNS = clone(BASE_COLUMNS)
      const enabledSteps = PIPELINE.filter(s => s.enabled !== false)
      enabledSteps.forEach(step => { EDITED = applyStep(EDITED, step) })
    }

    function safeNum(v){ const n = Number(String(v).replace(/[, ]+/g,'')); return Number.isFinite(n) ? n : NaN }
    function doMath(a,b,opr){ switch(opr){ case '+': return a+b; case '-': return a-b; case '*': return a*b; case '/': return b===0? '': a/b; default: return a } }

    function applyStep(rows, step){
      const { op, col, params } = step
      const out = rows.map(r => ({ ...r }))
      if (op === 'trim') out.forEach(r => { if (r[col] != null) r[col] = String(r[col]).trim() })
      else if (op === 'upper') out.forEach(r => { if (r[col] != null) r[col] = String(r[col]).toUpperCase() })
      else if (op === 'lower') out.forEach(r => { if (r[col] != null) r[col] = String(r[col]).toLowerCase() })
      else if (op === 'title') out.forEach(r => { if (r[col] != null) r[col] = toTitle(String(r[col])) })
      else if (op === 'replace'){
        const find = params['p-find'] || ''
        const repl = params['p-repl'] || ''
        const isRegex = (params['p-regex'] === 'yes')
        const re = isRegex ? new RegExp(find,'g') : null
        out.forEach(r => { const s = String(r[col] ?? ''); r[col] = isRegex ? s.replace(re, repl) : s.split(find).join(repl) })
      } else if (op === 'coerce_number') out.forEach(r => { const n = safeNum(r[col]); r[col] = Number.isFinite(n) ? n : '' })
      else if (op === 'coerce_date') out.forEach(r => { const d = new Date(r[col]); r[col] = isNaN(+d) ? '' : d.toISOString().slice(0,10) })
      else if (op === 'fill_empty'){ const fill = params['p-fill'] ?? ''; out.forEach(r => { if (r[col] === '' || r[col] == null) r[col] = fill }) }
      else if (op === 'split'){
        const delim = params['p-delim'] ?? ''
        const base = params['p-base'] || (col + '_part')
        const max = parseInt(params['p-max']||'0',10) || undefined
        out.forEach(r => { const parts = String(r[col] ?? '').split(delim); const use = max ? parts.slice(0, max) : parts; use.forEach((p,i) => { const name = `${base}_${i+1}`; if (!COLUMNS.includes(name)) COLUMNS.push(name); r[name] = p }) })
      } else if (op === 'extract'){
        try{ const re = new RegExp(params['p-reg']||''); const newname = params['p-newname'] || (col + '_extracted'); if (!COLUMNS.includes(newname)) COLUMNS.push(newname); out.forEach(r => { const m = String(r[col] ?? '').match(re); r[newname] = m && m[1] ? m[1] : '' }) } catch(e) { console.warn('Bad RegExp', e) }
      } else if (op === 'delete_col'){ COLUMNS = COLUMNS.filter(c => c !== col); out.forEach(r => { delete r[col] }) }
      else if (op === 'rename_col'){ const newname = params['p-newname'] || col; if (!COLUMNS.includes(newname)) { COLUMNS = COLUMNS.map(c => c === col ? newname : c); out.forEach(r => { r[newname] = r[col]; delete r[col] }) } }
      else if (op === 'new_col_compute'){ const name = params['p-newname'] || 'computed'; if (!COLUMNS.includes(name)) COLUMNS.push(name); out.forEach(r => { try { const ctx = { ...r, Number, String, Math, Date, Object }; r[name] = Function('ctx', 'with (ctx) { return ' + (params['p-expr']||'null') + '; }')(ctx) } catch(e) { r[name] = '' } }) }
      else if (op === 'merge_cols'){ const cols = (params['p-cols']||'').split(',').map(s => s.trim()).filter(Boolean); const delim = params['p-delim'] || ''; const newname = params['p-newname'] || 'merged'; if (!COLUMNS.includes(newname)) COLUMNS.push(newname); out.forEach(r => { r[newname] = cols.map(c => r[c] ?? '').join(delim) }) }
      else if (op === 'math_col_const'){ const opr = params['p-opr'] || '+'; const k = Number(params['p-const']||'0'); out.forEach(r => { const a = safeNum(r[col]); if (!Number.isFinite(a)) { r[col] = ''; return } r[col] = doMath(a,k,opr) }) }
      else if (op === 'math_two_cols'){ const col2 = params['p-col2'] || ''; const opr = params['p-opr'] || '+'; const newname = params['p-newname'] || col; if (!COLUMNS.includes(newname)) COLUMNS.push(newname); out.forEach(r => { const a = safeNum(r[col]); const b = safeNum(r[col2]); r[newname] = (Number.isFinite(a) && Number.isFinite(b)) ? doMath(a,b,opr) : '' }) }
      return out
    }

    // Removed NL local parser and AI step preview in favor of chat-only UI

    

    

    

    

    

    function downloadString(str, type, filename){ const blob = new Blob([str], { type }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = filename; document.body.appendChild(a); a.click(); setTimeout(()=>{ document.body.removeChild(a); URL.revokeObjectURL(url) },0) }

    exportCSVBtn.addEventListener('click', () => { const ws = XLSX.utils.json_to_sheet(EDITED, { header: COLUMNS }); const csv = XLSX.utils.sheet_to_csv(ws); downloadString(csv, 'text/csv;charset=utf-8;', 'cleaned_page.csv') })
    exportXLSXBtn.addEventListener('click', () => { const ws = XLSX.utils.json_to_sheet(EDITED, { header: COLUMNS }); const wb = XLSX.utils.book_new(); XLSX.utils.book_append_sheet(wb, ws, 'Cleaned'); const out = XLSX.write(wb, { type: 'array', bookType: 'xlsx' }); const blob = new Blob([out], { type: 'application/octet-stream' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'cleaned.xlsx'; document.body.appendChild(a); a.click(); setTimeout(()=>{ document.body.removeChild(a); URL.revokeObjectURL(url) },0) })
    if (exportJSONBtn) exportJSONBtn.addEventListener('click', () => { const jsonStr = JSON.stringify(EDITED, null, 2); const blobType = 'application/json'; const url = URL.createObjectURL(new Blob([jsonStr], { type: blobType })); const a = document.createElement('a'); a.href = url; a.download = 'cleaned.json'; document.body.appendChild(a); a.click(); setTimeout(()=>{ document.body.removeChild(a); URL.revokeObjectURL(url) },0) })
    if (exportParquetBtn) exportParquetBtn.addEventListener('click', async () => { try { await ensureParquetInit(); const table = rowsToArrowTable(EDITED, COLUMNS); const wasmTable = ParquetTable.fromIPCStream(arrow.tableToIPC(table, 'stream')); const writerProps = new WriterPropertiesBuilder().setCompression(Compression.ZSTD).build(); const pq = writeParquet(wasmTable, writerProps); const blob = new Blob([pq], { type: 'application/octet-stream' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'cleaned.parquet'; document.body.appendChild(a); a.click(); setTimeout(()=>{ document.body.removeChild(a); URL.revokeObjectURL(url) },0) } catch (e){ console.error(e); alert('Failed to export Parquet: ' + e.message) } })
    saveRecipeBtn.addEventListener('click', () => { const recipe = JSON.stringify({ pipeline: PIPELINE, columns: COLUMNS }, null, 2); downloadString(recipe,'application/json','recipe.json') })
    loadRecipeBtn.addEventListener('click', () => recipeInput.click())
    recipeInput.addEventListener('change', async (e) => { const f = e.target.files?.[0]; if (!f) return; const txt = await f.text(); const data = JSON.parse(txt); if (Array.isArray(data.columns)) { COLUMNS = data.columns } HISTORY = []; FUTURE = []; updateHistoryInfo(); renderTable() })

    // No params to render for removed transform UI

    return () => { /* cleanup minimal */ }
  }, [])

  return (
    <main ref={rootRef} className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      <section className="bg-white rounded-2xl shadow p-4 mb-6">
        <div className="flex flex-wrap items-center gap-3">
          <input id="file-input" type="file" accept=".csv,.xlsx,.xls,.json,.parquet,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel" className="hidden" />
          <button id="pick-file" className="px-4 py-2 rounded-xl bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700">Load Data</button>
          <div id="dropzone" className="flex-1 min-w-[260px] border-2 border-dashed border-slate-300 rounded-xl p-3 text-sm text-slate-600">Drag & drop CSV/XLSX/JSON/Parquet here</div>
          <span id="file-name" className="text-sm text-slate-500"></span>
          <div className="ml-auto flex items-center gap-2">
            <button id="export-csv" className="px-3 py-2 rounded-lg bg-slate-100 text-slate-800 text-sm hover:bg-slate-200" disabled>Export CSV</button>
            <button id="export-xlsx" className="px-3 py-2 rounded-lg bg-slate-100 text-slate-800 text-sm hover:bg-slate-200" disabled>Export XLSX</button>
            <button id="export-json" className="px-3 py-2 rounded-lg bg-slate-100 text-slate-800 text-sm hover:bg-slate-200" disabled>Export JSON</button>
            <button id="export-parquet" className="px-3 py-2 rounded-lg bg-slate-100 text-slate-800 text-sm hover:bg-slate-200" disabled>Export Parquet</button>
            <button id="save-recipe" className="px-3 py-2 rounded-lg bg-slate-100 text-slate-800 text-sm hover:bg-slate-200" disabled>Save Recipe</button>
            <button id="load-recipe" className="px-3 py-2 rounded-lg bg-slate-100 text-slate-800 text-sm hover:bg-slate-200">Load Recipe</button>
            <input id="recipe-input" type="file" accept="application/json" className="hidden" />
          </div>
        </div>
      </section>

      <div className="flex gap-6 items-start">
        {/* Collapsible Sidebar: Transform + Chat as separate cards */}
        <aside id="chat-sidebar" className="transform transition-[width,opacity,transform] duration-300 bg-transparent w-[360px] overflow-hidden">
          <div className="space-y-4">
            <div className="bg-white rounded-2xl shadow p-4">
              <div className="flex items-center mb-2">
                <h2 className="text-base font-semibold">AI Assistant</h2>
              </div>
              <h3 className="text-sm font-semibold mb-2">Transform Data with Natural Language</h3>
              <textarea id="instruction" className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm mb-2" rows={3} placeholder="Enter your instruction (e.g., 'Concatenate first name and last name columns')"></textarea>
              <div className="flex items-center gap-2 mb-2">
                <button id="transform-btn" className="px-3 py-2 rounded-xl bg-emerald-600 text-white text-sm hover:bg-emerald-700">Transform Data</button>
                <button id="undo-backend" className="px-3 py-2 rounded-xl bg-slate-800 text-white text-sm hover:bg-slate-900">Undo</button>
              </div>
              <div id="transform-status" className="text-xs text-slate-600"></div>
              <div id="followupSection" className="hidden mt-3 p-3 bg-slate-50 rounded-xl">
                <h4 className="text-sm font-semibold mb-1">Additional Information Needed</h4>
                <p id="followupMessage" className="text-sm mb-2"></p>
                <div id="followupQuestions" className="mb-2"></div>
                <div className="flex items-center gap-2">
                  <button id="followupSubmit" className="px-3 py-1.5 rounded bg-emerald-600 text-white text-xs">Submit Responses</button>
                  <button id="followupCancel" className="px-3 py-1.5 rounded bg-slate-300 text-slate-800 text-xs">Cancel</button>
                </div>
              </div>
            </div>

            <div className="bg-white rounded-2xl shadow p-4">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-semibold">Chat with AI Assistant</h3>
                <div className="flex items-center gap-2">
                  <label htmlFor="llm-select" className="text-xs text-slate-600">Model</label>
                  <select id="llm-select" className="rounded border border-slate-300 text-xs px-2 py-1">
                    <option value="gemini">Gemini 2.5 Flash</option>
                    <option value="ollama">DeepSeek R1 32B (Ollama)</option>
                  </select>
                </div>
              </div>
              <div className="text-[11px] text-slate-500 mb-2">Active: <span id="llm-active" className="font-medium">Gemini</span></div>
              <div className="h-64 overflow-y-auto pr-1 mb-2">
                <div id="chat-messages" className="flex flex-col"></div>
              </div>
              <div className="space-y-2">
                <textarea id="chat-input" className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" rows={3} placeholder="Ask about your data or request transformations..."></textarea>
                <div className="flex items-center gap-2">
                  <button id="chat-send" className="px-3 py-2 rounded-xl bg-emerald-600 text-white text-sm hover:bg-emerald-700">Send</button>
                  <button id="chat-clear" className="px-3 py-2 rounded-xl bg-slate-200 text-slate-800 text-sm">Clear</button>
                </div>
              </div>
            </div>
          </div>
        </aside>

        <section id="main-section" className="flex-1 min-w-0 bg-white rounded-2xl shadow p-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="text-sm text-slate-600">Rows: <span id="row-count">0</span></div>
            <div className="ml-auto flex items-center gap-2">
              <button id="sidebar-toggle" className="px-3 py-2 rounded-lg bg-slate-100 text-sm">Close Menu</button>
              <button id="undo" aria-label="Undo" className="px-3 py-2 rounded-lg bg-slate-100 text-sm flex items-center gap-2 opacity-50 cursor-not-allowed" disabled>
                <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4"><path d="M7.707 3.293a1 1 0 00-1.414 0L1.586 8l4.707 4.707a1 1 0 001.414-1.414L5.414 9H11a4 4 0 010 8h-2a1 1 0 100 2h2a6 6 0 000-12H5.414l2.293-2.293a1 1 0 000-1.414z"/></svg>
                <span>Undo</span>
                <span className="badge text-[10px] px-1 rounded bg-slate-200 text-slate-700"></span>
              </button>
              <button id="redo" aria-label="Redo" className="px-3 py-2 rounded-lg bg-slate-100 text-sm flex items-center gap-2 opacity-50 cursor-not-allowed" disabled>
                <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4"><path d="M12.293 3.293a1 1 0 011.414 0L18.414 8l-4.707 4.707a1 1 0 01-1.414-1.414L14.586 9H9a4 4 0 100 8h2a1 1 0 110 2H9a6 6 0 110-12h5.586l-2.293-2.293a1 1 0 010-1.414z"/></svg>
                <span>Redo</span>
                <span className="badge text-[10px] px-1 rounded bg-slate-200 text-slate-700"></span>
              </button>
              <div className="hidden sm:block text-xs text-slate-500 ml-1" id="history-info"></div>
              <input id="search" className="rounded-xl border border-slate-300 px-3 py-2 text-sm" placeholder="Search rows" />
              <button id="clear-edits" className="px-3 py-2 rounded-lg bg-slate-100 text-slate-800 text-sm hover:bg-slate-200" disabled>Reset to Original</button>
            </div>
          </div>
          <div id="table-wrap" className="table-wrap h-[calc(100vh-240px)] border border-slate-200 rounded-xl">
            <table id="grid" className="w-full text-sm">
              <thead id="thead"></thead>
              <tbody id="tbody"></tbody>
            </table>
          </div>
          <div className="flex items-center justify-between mt-3">
            <div className="text-xs text-slate-500" id="paging-info"></div>
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <label htmlFor="rowsPerPage" className="text-xs text-slate-500">Rows per page:</label>
                <select id="rowsPerPage" className="rounded border border-slate-300 text-sm px-2 py-1">
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                </select>
              </div>
              <div className="flex items-center gap-2">
                <button id="prev" className="px-3 py-1 rounded-lg bg-slate-100 text-sm" disabled>Prev</button>
                <input id="page" type="number" className="w-16 text-center rounded-lg border border-slate-300 text-sm px-2 py-1" defaultValue={1} min={1} />
                <button id="next" className="px-3 py-1 rounded-lg bg-slate-100 text-sm" disabled>Next</button>
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  )
}
