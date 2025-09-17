import React, { useEffect, useRef } from 'react'
import * as XLSX from 'xlsx'
import * as arrow from 'apache-arrow'
import initWasm, { readParquet, Table as ParquetTable, writeParquet, WriterPropertiesBuilder, Compression } from 'parquet-wasm'
import parquetWasmUrl from 'parquet-wasm/esm/parquet_wasm_bg.wasm?url'

export default function Home(){
  const rootRef = useRef(null)

  useEffect(() => {
    // Mirror the structure/IDs from original index.html
    const root = rootRef.current
    if (!root) return

    // State
    let ORIGINAL = []
    let EDITED = []
    let COLUMNS = []
    let PIPELINE = []
    const PAGE_SIZE = 50
    let CURRENT_PAGE = 1
    let parquetReady = false

    // History (Undo/Redo)
    let HISTORY = []
    let FUTURE = []
    const snapshot = () => ({ rows: clone(EDITED), columns: clone(COLUMNS) })
    function pushHistory(){
      // Push current state then clear FUTURE
      HISTORY.push(snapshot())
      if (HISTORY.length > 100) HISTORY.shift()
      FUTURE = []
      updateHistoryUI()
    }
    function canUndo(){ return HISTORY.length > 0 }
    function canRedo(){ return FUTURE.length > 0 }
    function showToast(msg){
      const toast = document.createElement('div')
      toast.className = 'fixed top-4 right-4 z-50 bg-slate-900 text-white text-sm px-3 py-2 rounded-lg shadow-lg opacity-0 transition-opacity'
      toast.textContent = msg
      document.body.appendChild(toast)
      // Force reflow then fade in
      requestAnimationFrame(() => { toast.classList.remove('opacity-0'); toast.classList.add('opacity-90') })
      setTimeout(() => {
        toast.classList.remove('opacity-90'); toast.classList.add('opacity-0')
        setTimeout(() => { document.body.removeChild(toast) }, 250)
      }, 1600)
    }

    function undo(){
      if (!canUndo()) return
      const prev = HISTORY.pop()
      // push present into FUTURE
      FUTURE.push(snapshot())
      EDITED = clone(prev.rows)
      COLUMNS = clone(prev.columns)
      renderTable(); updateHistoryUI();
      showToast(`Undid 1 change • remaining: ${HISTORY.length}`)
    }
    function redo(){
      if (!canRedo()) return
      const next = FUTURE.pop()
      // push present into HISTORY
      HISTORY.push(snapshot())
      EDITED = clone(next.rows)
      COLUMNS = clone(next.columns)
      renderTable(); updateHistoryUI();
      showToast(`Redid 1 change • remaining: ${FUTURE.length}`)
    }

    // DOM helpers (scoped to this component)
    const $ = (id) => root.querySelector('#'+id)
    const fileInput = $("file-input")
    const pickBtn = $("pick-file")
    const dropzone = $("dropzone")
    const fileNameEl = $("file-name")

    const exportCSVBtn = $("export-csv")
    const exportXLSXBtn = $("export-xlsx")
    const exportJSONBtn = $("export-json")
    const exportParquetBtn = $("export-parquet")
    const saveRecipeBtn = $("save-recipe")
    const loadRecipeBtn = $("load-recipe")
    const recipeInput = $("recipe-input")
    const undoBtn = $("undo")
    const redoBtn = $("redo")

    const tCol = $("t-col")
    const tOp = $("t-op")
    const tParams = $("t-params")
    const addStepBtn = $("add-step")
    const runBtn = $("run-pipeline")
    const enablePipeline = $("enable-pipeline")
    const pipelineList = $("pipeline")

    const thead = $("thead")
    const tbody = $("tbody")
    const rowCount = $("row-count")
    const pagingInfo = $("paging-info")
    const pageInput = $("page")
    const prevBtn = $("prev")
    const nextBtn = $("next")
    const searchInput = $("search")
    const clearEditsBtn = $("clear-edits")

    const readinessList = $("readiness-list")

    const clone = (x) => JSON.parse(JSON.stringify(x))
    const toTitle = (s) => s.replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.substring(1).toLowerCase())

    async function ensureParquetInit(){
      if (parquetReady) return
      await initWasm(parquetWasmUrl)
      parquetReady = true
    }

    function tableToRows(arrowTable){
      const cols = arrowTable.schema.fields.map(f => f.name)
      const n = arrowTable.numRows
      const rows = new Array(n)
      const vectors = cols.map(name => arrowTable.getColumn(name))
      for (let i=0; i<n; i++){
        const obj = {}
        for (let c=0; c<cols.length; c++) obj[cols[c]] = vectors[c]?.get(i) ?? null
        rows[i] = obj
      }
      return { rows, cols }
    }

    function rowsToArrowTable(rows, cols){
      const arrays = {}
      const headers = cols && cols.length ? cols : Object.keys(rows[0] || {})
      headers.forEach(h => { arrays[h] = rows.map(r => r[h]) })
      return arrow.tableFromArrays(arrays)
    }

    function renderParams(){
      const op = tOp.value
      tParams.innerHTML = ''
      const add = (label, id, ph='', type='text') => {
        const wrapper = document.createElement('div')
        wrapper.innerHTML = `<label class="block text-xs text-slate-600">${label}</label>
          <input id="${id}" type="${type}" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" placeholder="${ph}">`
        tParams.appendChild(wrapper)
      }
      const addSelect = (label, id, opts) => {
        const wrapper = document.createElement('div')
        const options = opts.map(o => `<option value="${o}">${o}</option>`).join('')
        wrapper.innerHTML = `<label class="block text-xs text-slate-600">${label}</label>
          <select id="${id}" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">${options}</select>`
        tParams.appendChild(wrapper)
      }
      if (op === 'replace') { add('Find','p-find','e.g., \\s+'); add('Replace With','p-repl','e.g., space'); addSelect('Use RegExp?','p-regex',['no','yes']) }
      else if (op === 'fill_empty') { add('Value for blanks','p-fill','e.g., 0') }
      else if (op === 'split') { add('Delimiter','p-delim','e.g., - or ,'); add('New column base name','p-base','e.g., part'); add('Max parts (optional)','p-max','e.g., 3','number') }
      else if (op === 'extract') { add('RegExp (capture group 1 used)','p-reg','e.g., (\\d{4,})'); add('New column name','p-newname','e.g., natural_account') }
      else if (op === 'rename_col') { add('New column name','p-newname','e.g., natural_account') }
      else if (op === 'new_col_compute') { add('New column name','p-newname','e.g., amount_usd'); add('Compute expression','p-expr','e.g., Number(amount) * 1.1') }
      else if (op === 'merge_cols') { add('Columns to merge (comma separated)','p-cols','e.g., company, dept, account'); add('Delimiter','p-delim','e.g., -'); add('New column name','p-newname','e.g., account_path') }
      else if (op === 'math_col_const') { addSelect('Operator','p-opr',['+','-','*','/']); add('Constant','p-const','e.g., 100') }
      else if (op === 'math_two_cols') { add('Other column','p-col2','e.g., quantity'); addSelect('Operator','p-opr',['+','-','*','/']); add('New column name (optional)','p-newname','e.g., total') }
    }

    function refreshColumnSelect(){ tCol.innerHTML = COLUMNS.map(c=>`<option value="${c}">${c}</option>`).join('') }

    function updateReadiness(){
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

    function renderTable(){
      rowCount.textContent = EDITED.length
      thead.innerHTML = ''
      const trh = document.createElement('tr')
      COLUMNS.forEach((c, idx) => {
        const th = document.createElement('th')
        th.className = `px-3 py-2 text-left text-xs font-semibold text-slate-700 border-b border-slate-200 ${idx===0?'sticky-col':''}`
        th.textContent = c
        trh.appendChild(th)
      })
      thead.appendChild(trh)

      const totalPages = Math.max(1, Math.ceil(EDITED.length / PAGE_SIZE))
      CURRENT_PAGE = Math.min(CURRENT_PAGE, totalPages)
      const start = (CURRENT_PAGE - 1) * PAGE_SIZE
      const end = Math.min(start + PAGE_SIZE, EDITED.length)

      tbody.innerHTML = ''
      for (let i=start; i<end; i++){
        const r = EDITED[i]
        const tr = document.createElement('tr')
        COLUMNS.forEach((c, idx) => {
          const td = document.createElement('td')
          td.className = `px-3 py-1 border-b border-slate-100 ${idx===0?'sticky-col':''}`
          const input = document.createElement('input')
          input.value = r[c] ?? ''
          input.className = 'w-full bg-transparent outline-none text-sm'
          input.addEventListener('change', (e)=> { pushHistory(); r[c] = e.target.value; updateHistoryUI() })
          td.appendChild(input)
          tr.appendChild(td)
        })
        tbody.appendChild(tr)
      }

      pageInput.value = CURRENT_PAGE
      prevBtn.disabled = CURRENT_PAGE <= 1
      nextBtn.disabled = CURRENT_PAGE >= totalPages
      pagingInfo.textContent = `Page ${CURRENT_PAGE} / ${totalPages} (rows ${start+1}-${end})`

      refreshColumnSelect()
      updateReadiness()
      toggleControls(true)
      updateHistoryUI()
    }

    function toggleControls(hasData){
      exportCSVBtn.disabled = !hasData
      exportXLSXBtn.disabled = !hasData
      if (exportJSONBtn) exportJSONBtn.disabled = !hasData
      if (exportParquetBtn) exportParquetBtn.disabled = !hasData
      saveRecipeBtn.disabled = !hasData
      addStepBtn.disabled = !hasData
      runBtn.disabled = !hasData
      clearEditsBtn.disabled = !hasData
      updateHistoryUI()
    }

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
      const info = $("history-info")
      if (info) info.textContent = `undo:${HISTORY.length} redo:${FUTURE.length}`
    }

    async function handleFiles(files){
      if (!files || !files[0]) return
      const f = files[0]
      fileNameEl.textContent = f.name
      const name = f.name || ''
      const ext = name.includes('.') ? name.split('.').pop().toLowerCase() : ''
      if (['xlsx','xls','csv'].includes(ext)){
        const buf = await f.arrayBuffer()
        const wb = XLSX.read(buf, { type: 'array' })
        const ws = wb.Sheets[wb.SheetNames[0]]
        const json = XLSX.utils.sheet_to_json(ws, { defval: '', raw: false })
        const headerRow = XLSX.utils.sheet_to_json(ws, { header: 1 })[0] || []
        COLUMNS = (headerRow.length ? headerRow : Object.keys(json[0] || {})).map(String)
        ORIGINAL = json
        EDITED = clone(json)
      } else if (ext === 'json'){
        const txt = await f.text()
        let data = JSON.parse(txt)
        if (!Array.isArray(data)) data = Array.isArray(data?.data) ? data.data : [data]
        const cols = new Set(); data.forEach(r => Object.keys(r||{}).forEach(k => cols.add(String(k))))
        COLUMNS = Array.from(cols)
        ORIGINAL = data
        EDITED = clone(data)
      } else if (ext === 'parquet'){
        await ensureParquetInit()
        const buf = new Uint8Array(await f.arrayBuffer())
        const wasmTable = readParquet(buf)
        const table = arrow.tableFromIPC(wasmTable.intoIPCStream())
        const { rows, cols } = tableToRows(table)
        COLUMNS = cols
        ORIGINAL = rows
        EDITED = clone(rows)
      } else {
        alert('Unsupported file type. Please upload CSV, XLSX, JSON, or Parquet.')
        return
      }
      PIPELINE = []
      renderTable()
      renderPipeline()
    }

    pickBtn.addEventListener('click', () => fileInput.click())
    fileInput.addEventListener('change', (e) => handleFiles(e.target.files))

    ;['dragenter','dragover'].forEach(evt => dropzone.addEventListener(evt, (e) => { e.preventDefault(); dropzone.classList.add('bg-emerald-50') }))
    ;['dragleave','drop'].forEach(evt => dropzone.addEventListener(evt, (e) => { e.preventDefault(); dropzone.classList.remove('bg-emerald-50') }))
    dropzone.addEventListener('drop', (e) => handleFiles(e.dataTransfer.files))

    // Search
    searchInput.addEventListener('input', () => {
      const q = searchInput.value.toLowerCase()
      if (!q) { EDITED = clone(ORIGINAL); renderTable(); return }
      EDITED = ORIGINAL.filter(r => COLUMNS.some(c => String(r[c] ?? '').toLowerCase().includes(q)))
      CURRENT_PAGE = 1; renderTable()
    })

    clearEditsBtn.addEventListener('click', () => { pushHistory(); EDITED = clone(ORIGINAL); renderTable() })

    // Paging
    prevBtn.addEventListener('click', () => { CURRENT_PAGE = Math.max(1, CURRENT_PAGE - 1); renderTable() })
    nextBtn.addEventListener('click', () => { CURRENT_PAGE += 1; renderTable() })
    pageInput.addEventListener('change', () => { CURRENT_PAGE = Math.max(1, parseInt(pageInput.value||'1',10)); renderTable() })

    // Transform params
    tOp.addEventListener('change', renderParams)

    // Pipeline
    const pipelineListEl = pipelineList

    function renderPipeline(){
      pipelineListEl.innerHTML = ''
      PIPELINE.forEach((step, idx) => {
        const li = document.createElement('li')
        li.className = 'border border-slate-200 rounded-xl p-2 flex items-start gap-2'
        const label = document.createElement('div')
        label.className = 'text-xs flex-1'
        label.textContent = `${idx+1}. ${step.op} on ${step.col}`
        const btns = document.createElement('div')
        btns.className = 'flex items-center gap-2'
        const onoff = document.createElement('input')
        onoff.type = 'checkbox'
        onoff.checked = step.enabled !== false
        onoff.addEventListener('change', () => { step.enabled = onoff.checked })
        const del = document.createElement('button')
        del.textContent = 'Delete'
        del.className = 'px-2 py-1 rounded bg-slate-100 text-xs'
        del.addEventListener('click', () => { PIPELINE.splice(idx,1); renderPipeline() })
        btns.appendChild(onoff); btns.appendChild(del)
        li.appendChild(label); li.appendChild(btns)
        pipelineListEl.appendChild(li)
      })
    }

    function addStep(step){ PIPELINE.push(step); renderPipeline() }

    function collectParams(){
      const params = {}
      ;['p-find','p-repl','p-regex','p-fill','p-delim','p-base','p-max','p-reg','p-newname','p-expr','p-cols','p-opr','p-const','p-col2']
        .forEach(id => { const el = $(id); if (el) params[id] = el.value })
      return params
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
        out.forEach(r => {
          const parts = String(r[col] ?? '').split(delim)
          const use = max ? parts.slice(0, max) : parts
          use.forEach((p,i) => { const name = `${base}_${i+1}`; if (!COLUMNS.includes(name)) COLUMNS.push(name); r[name] = p })
        })
      } else if (op === 'extract'){
        try{
          const re = new RegExp(params['p-reg']||'')
          const newname = params['p-newname'] || (col + '_extracted')
          if (!COLUMNS.includes(newname)) COLUMNS.push(newname)
          out.forEach(r => { const m = String(r[col] ?? '').match(re); r[newname] = m && m[1] ? m[1] : '' })
        } catch(e) { console.warn('Bad RegExp', e) }
      } else if (op === 'delete_col'){
        COLUMNS = COLUMNS.filter(c => c !== col)
        out.forEach(r => { delete r[col] })
      } else if (op === 'rename_col'){
        const newname = params['p-newname'] || col
        if (!COLUMNS.includes(newname)){
          COLUMNS = COLUMNS.map(c => c === col ? newname : c)
          out.forEach(r => { r[newname] = r[col]; delete r[col] })
        }
      } else if (op === 'new_col_compute'){
        const name = params['p-newname'] || 'computed'
        if (!COLUMNS.includes(name)) COLUMNS.push(name)
        out.forEach(r => { try { const ctx = { ...r, Number, String, Math, Date }; r[name] = Function('ctx', 'with (ctx) { return ' + (params['p-expr']||'null') + '; }')(ctx) } catch(e) { r[name] = '' } })
      } else if (op === 'merge_cols'){
        const cols = (params['p-cols']||'').split(',').map(s => s.trim()).filter(Boolean)
        const delim = params['p-delim'] || ''
        const newname = params['p-newname'] || 'merged'
        if (!COLUMNS.includes(newname)) COLUMNS.push(newname)
        out.forEach(r => { r[newname] = cols.map(c => r[c] ?? '').join(delim) })
      } else if (op === 'math_col_const'){
        const opr = params['p-opr'] || '+'
        const k = Number(params['p-const']||'0')
        out.forEach(r => { const a = safeNum(r[col]); if (!Number.isFinite(a)) { r[col] = ''; return } r[col] = doMath(a,k,opr) })
      } else if (op === 'math_two_cols'){
        const col2 = params['p-col2'] || ''
        const opr = params['p-opr'] || '+'
        const newname = params['p-newname'] || col
        if (!COLUMNS.includes(newname)) COLUMNS.push(newname)
        out.forEach(r => { const a = safeNum(r[col]); const b = safeNum(r[col2]); r[newname] = (Number.isFinite(a) && Number.isFinite(b)) ? doMath(a,b,opr) : '' })
      }
      return out
    }

    function applyPipeline(){ EDITED = clone(ORIGINAL); const enabled = PIPELINE.filter(s => s.enabled !== false); enabled.forEach(step => { EDITED = applyStep(EDITED, step) }) }

    // Wire buttons
    runBtn.addEventListener('click', () => { if (!enablePipeline.checked) return; pushHistory(); applyPipeline(); renderTable(); })
    addStepBtn.addEventListener('click', () => { if (!COLUMNS.length) return; const step = { op: tOp.value, col: tCol.value, params: collectParams(), enabled: true }; addStep(step) })

    // Export
    function downloadString(str, type, filename){ const blob = new Blob([str], { type }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = filename; document.body.appendChild(a); a.click(); setTimeout(()=>{ document.body.removeChild(a); URL.revokeObjectURL(url) },0) }

    exportCSVBtn.addEventListener('click', () => {
      const ws = XLSX.utils.json_to_sheet(EDITED, { header: COLUMNS })
      const csv = XLSX.utils.sheet_to_csv(ws)
      downloadString(csv, 'text/csv;charset=utf-8;', 'cleaned.csv')
    })

    exportXLSXBtn.addEventListener('click', () => {
      const ws = XLSX.utils.json_to_sheet(EDITED, { header: COLUMNS })
      const wb = XLSX.utils.book_new()
      XLSX.utils.book_append_sheet(wb, ws, 'Cleaned')
      const out = XLSX.write(wb, { type: 'array', bookType: 'xlsx' })
      const blob = new Blob([out], { type: 'application/octet-stream' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'cleaned.xlsx'; document.body.appendChild(a); a.click(); setTimeout(()=>{ document.body.removeChild(a); URL.revokeObjectURL(url) },0)
    })

    if (exportJSONBtn) exportJSONBtn.addEventListener('click', () => {
      const jsonStr = JSON.stringify(EDITED, null, 2)
      downloadString(jsonStr, 'application/json', 'cleaned.json')
    })

    if (exportParquetBtn) exportParquetBtn.addEventListener('click', async () => {
      try {
        await ensureParquetInit()
        const table = rowsToArrowTable(EDITED, COLUMNS)
        const wasmTable = ParquetTable.fromIPCStream(arrow.tableToIPC(table, 'stream'))
        const writerProps = new WriterPropertiesBuilder().setCompression(Compression.ZSTD).build()
        const parquetUint8 = writeParquet(wasmTable, writerProps)
        const blob = new Blob([parquetUint8], { type: 'application/octet-stream' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a'); a.href = url; a.download = 'cleaned.parquet'; document.body.appendChild(a); a.click(); setTimeout(()=>{ document.body.removeChild(a); URL.revokeObjectURL(url) },0)
      } catch (e) { console.error(e); alert('Failed to export Parquet: ' + e.message) }
    })

    saveRecipeBtn.addEventListener('click', () => { const recipe = JSON.stringify({ pipeline: PIPELINE, columns: COLUMNS }, null, 2); downloadString(recipe,'application/json','recipe.json') })

    loadRecipeBtn.addEventListener('click', () => recipeInput.click())
    recipeInput.addEventListener('change', async (e) => {
      const f = e.target.files?.[0]; if (!f) return;
      const txt = await f.text(); const data = JSON.parse(txt)
      if (Array.isArray(data.columns)) COLUMNS = data.columns
      if (Array.isArray(data.pipeline)) PIPELINE = data.pipeline
      HISTORY = []; FUTURE = []; updateHistoryUI()
      renderPipeline(); renderTable()
    })

    // Undo/Redo buttons and shortcuts
    if (undoBtn) undoBtn.addEventListener('click', undo)
    if (redoBtn) redoBtn.addEventListener('click', redo)
    window.addEventListener('keydown', (e) => {
      const z = (e.key === 'z' || e.key === 'Z')
      const y = (e.key === 'y' || e.key === 'Y')
      if ((e.ctrlKey || e.metaKey) && z && !e.shiftKey){ e.preventDefault(); undo() }
      else if ((e.ctrlKey || e.metaKey) && (y || (z && e.shiftKey))){ e.preventDefault(); redo() }
    })

    // Initial
    renderParams()

    return () => {
      // Cleanup listeners when component unmounts
      root.querySelectorAll('button,input,select').forEach(el => {
        const cloneEl = el.cloneNode(true)
        el.parentNode && el.parentNode.replaceChild(cloneEl, el)
      })
    }
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

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <section className="lg:col-span-1 space-y-6">
          <div className="bg-white rounded-2xl shadow p-4">
            <h2 className="text-base font-semibold mb-2">Mapping Readiness</h2>
            <p className="text-xs text-slate-600 mb-3">These columns make downstream COA/GL → Tax mapping easier. Use the tools below to create/clean them.</p>
            <ul id="readiness-list" className="space-y-2 text-sm"></ul>
          </div>

          <div className="bg-white rounded-2xl shadow p-4">
            <h2 className="text-base font-semibold mb-3">Add Transform</h2>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-slate-600">Target Column</label>
                <select id="t-col" className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"></select>
              </div>
              <div>
                <label className="block text-xs text-slate-600">Operation</label>
                <select id="t-op" className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">
                  <option value="trim">Trim</option>
                  <option value="upper">Uppercase</option>
                  <option value="lower">Lowercase</option>
                  <option value="title">Title Case</option>
                  <option value="replace">Replace (find → with)</option>
                  <option value="coerce_number">Coerce → Number</option>
                  <option value="coerce_date">Coerce → Date (ISO)</option>
                  <option value="fill_empty">Fill empties</option>
                  <option value="split">Split by delimiter</option>
                  <option value="extract">Extract by RegExp</option>
                  <option value="delete_col">Delete column</option>
                  <option value="rename_col">Rename column</option>
                  <option value="new_col_compute">New column: compute</option>
                  <option value="merge_cols">Merge columns</option>
                  <option value="math_col_const">Math: col ± × ÷ const</option>
                  <option value="math_two_cols">Math: col1 ± × ÷ col2</option>
                </select>
              </div>
              <div id="t-params" className="grid grid-cols-1 gap-2"></div>
              <div className="flex items-center gap-2">
                <button id="add-step" className="px-3 py-2 rounded-xl bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700" disabled>Add Step</button>
                <button id="run-pipeline" className="px-3 py-2 rounded-xl bg-slate-800 text-white text-sm hover:bg-slate-900" disabled>Run</button>
                <label className="flex items-center gap-2 text-xs text-slate-600 ml-auto">
                  <input id="enable-pipeline" type="checkbox" className="rounded" defaultChecked /> Enable
                </label>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-2xl shadow p-4">
            <h2 className="text-base font-semibold mb-3">Pipeline</h2>
            <ol id="pipeline" className="space-y-2 text-sm"></ol>
          </div>
        </section>

        <section className="lg:col-span-3 bg-white rounded-2xl shadow p-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="text-sm text-slate-600">Rows: <span id="row-count">0</span></div>
            <div className="ml-auto flex items-center gap-2">
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
              {/* <div id="history-info" className="hidden sm:block text-xs text-slate-500 ml-1"></div> */}
              <input id="search" className="rounded-xl border border-slate-300 px-3 py-2 text-sm" placeholder="Search rows" />
              <button id="clear-edits" className="px-3 py-2 rounded-lg bg-slate-100 text-slate-800 text-sm hover:bg-slate-200" disabled>Reset to Original</button>
            </div>
          </div>
          <div className="table-wrap border border-slate-200 rounded-xl">
            <table id="grid" className="w-full text-sm">
              <thead id="thead"></thead>
              <tbody id="tbody"></tbody>
            </table>
          </div>
          <div className="flex items-center justify-between mt-3">
            <div className="text-xs text-slate-500" id="paging-info"></div>
            <div className="flex items-center gap-2">
              <button id="prev" className="px-3 py-1 rounded-lg bg-slate-100 text-sm" disabled>Prev</button>
              <input id="page" type="number" className="w-16 text-center rounded-lg border border-slate-300 text-sm px-2 py-1" defaultValue={1} min={1} />
              <button id="next" className="px-3 py-1 rounded-lg bg-slate-100 text-sm" disabled>Next</button>
            </div>
          </div>
        </section>
      </div>
    </main>
  )
}
