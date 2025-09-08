import React, { useEffect, useRef } from 'react'
import * as XLSX from 'xlsx'

export default function Diagnostics(){
  const rootRef = useRef(null)

  useEffect(() => {
    const root = rootRef.current
    if (!root) return

    // Utilities
    const fmtInt = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 })
    const fmt2 = new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    const el = sel => root.querySelector(sel)

    function toCSV(rows){
      if (!rows || !rows.length) return ''
      const headers = Object.keys(rows[0])
      const esc = s => '"' + String(s ?? '').replace(/"/g, '""') + '"'
      const lines = [headers.join(',')]
      for (const r of rows) lines.push(headers.map(h => esc(r[h])).join(','))
      return lines.join('\n')
    }

    function download(filename, text){
      const blob = new Blob([text], { type: 'text/csv;charset=utf-8;' })
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = filename
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
    }

    function flatten(obj, prefix = '', out = {}){
      for (const [k, v] of Object.entries(obj)){
        const key = prefix ? `${prefix}.${k}` : k
        if (v && typeof v === 'object' && !Array.isArray(v) && !(v instanceof Date)) flatten(v, key, out)
        else out[key] = v
      }
      return out
    }

    function validNumber(x){
      if (x === null || x === undefined || x === '') return null
      const n = Number(String(x).toString().replace(/[^\d.-]/g, ''))
      return Number.isFinite(n) ? n : null
    }

    function parseDateLoose(x){
      if (x === null || x === undefined || x === '') return null
      const d = new Date(x)
      return isNaN(+d) ? null : d
    }

    async function parseFile(file){
      const name = file.name || ''
      const ext = name.split('.').pop().toLowerCase()
      if (["xlsx","xls","csv"].includes(ext)){
        const buf = await file.arrayBuffer()
        const wb = XLSX.read(buf, { type: 'array' })
        const sheet = wb.Sheets[wb.SheetNames[0]]
        const rows = XLSX.utils.sheet_to_json(sheet, { defval: null })
        return rows.map(r => flatten(r))
      } else if (ext === 'json'){
        const txt = await file.text()
        let data = JSON.parse(txt)
        if (Array.isArray(data)) return data.map(r => (typeof r === 'object' ? flatten(r) : { value: r }))
        else if (Array.isArray(data.data)) return data.data.map(r => (typeof r === 'object' ? flatten(r) : { value: r }))
        else return [flatten(data)]
      } else { throw new Error('Unsupported file type') }
    }

    function inferColumns(rows){ const cols = new Set(); for (const r of rows) for (const k of Object.keys(r)) cols.add(k); return Array.from(cols) }

    const state = { anyRows: [], anyCols: [], anomalies: null, anomTableRows: [], glRows: [], tbRows: [] }

    function populateSelectOptions(select, options){ select.innerHTML=''; for (const c of options){ const opt=document.createElement('option'); opt.value=c; opt.textContent=c; select.appendChild(opt) } }

    function computeAnomalies(rows, cols, { keyCols = [], numCols = [], dateCols = [], chkOut = true, chkDup = true, chkSusp = true } = {}){
      const N = rows.length; const C = cols.length
      const issuesByRow = new Map()
      const pushIssue = (idx, col, type, detail) => { if (!issuesByRow.has(idx)) issuesByRow.set(idx, []); issuesByRow.get(idx).push({ col, type, detail }) }

      let missingCells = 0, mismatches = 0, badDates = 0, suspCount = 0

      const numStats = {}
      for (const col of numCols){
        const vals = rows.map(r => validNumber(r[col])).filter(v => v !== null)
        const mean = vals.reduce((a,b)=>a+b,0) / (vals.length || 1)
        const sd = Math.sqrt(vals.reduce((a,b)=>a + Math.pow(b - mean,2),0) / (Math.max(1, vals.length - 1)))
        numStats[col] = { mean, sd }
      }

      let dupCount = 0
      if (chkDup){
        const seen = new Map()
        for (let i=0;i<N;i++){
          const key = keyCols.length ? keyCols.map(k => rows[i][k]).join('\u241F') : JSON.stringify(rows[i])
          if (seen.has(key)) { dupCount++; pushIssue(i, keyCols.join(','), 'duplicate', 'Duplicate key/row') }
          else seen.set(key, i)
        }
      }

      const suspiciousRe = /\?|^\s*(NA|N\/A|null|NULL|nan|NIL)\s*$/i
      for (let i=0;i<N;i++){
        const r = rows[i]
        for (const col of cols){
          const v = r[col]
          if (v === null || v === undefined || v === '') { missingCells++; continue }
          if (chkSusp && typeof v === 'string' && suspiciousRe.test(v)) { suspCount++; pushIssue(i, col, 'suspicious', String(v)) }
        }
        for (const col of numCols){
          const num = validNumber(r[col])
          if (num === null) { mismatches++; pushIssue(i, col, 'type', 'Expected number') }
          else if (chkOut && Number.isFinite(num) && numStats[col].sd > 0){
            const z = (num - numStats[col].mean) / numStats[col].sd
            if (Math.abs(z) >= 3) pushIssue(i, col, 'outlier', `z=${z.toFixed(2)}`)
          }
        }
        for (const col of dateCols){
          const d = parseDateLoose(r[col])
          if (!d) { badDates++; pushIssue(i, col, 'date', 'Invalid date') }
          else { const y = d.getFullYear(); if (y < 1990 || y > 2100) { badDates++; pushIssue(i, col, 'date', `Out-of-range year ${y}`) } }
        }
      }

      const anomRows = []
      issuesByRow.forEach((reasons, idx) => {
        const base = { _row: idx + 1 }
        for (const c of cols) base[c] = rows[idx][c]
        base._issues = reasons.map(x => `${x.col}:${x.type}${x.detail?`(${x.detail})`:''}`).join('; ')
        anomRows.push(base)
      })
      const outlierCount = Array.from(issuesByRow.values()).flat().filter(x => x.type === 'outlier').length
      return { issuesByRow, exportRows: anomRows, counts: { rows: N, cols: C, missing: missingCells, mismatch: mismatches, outliers: outlierCount, dup: dupCount, susp: suspCount, badDates } }
    }

    function renderAnomalyTable(rows, cols, issuesByRow){
      const wrap = el('#anomaly-table-wrap')
      if (!rows.length){ wrap.innerHTML = '<div class="text-sm text-slate-500">No rows with anomalies.</div>'; return }
      const header = `<thead><tr>${['#', ...cols].map(h => `<th class=\"px-3 py-2 text-left text-xs font-medium text-slate-500 border-b\">${h}</th>`).join('')}<th class=\"px-3 py-2 text-left text-xs font-medium text-slate-500 border-b\">Issues</th></tr></thead>`
      const body = rows.map((r) => {
        const idx = r._row - 1
        const issues = issuesByRow.get(idx) || []
        const cellFlags = new Map()
        for (const it of issues){ if (!cellFlags.has(it.col)) cellFlags.set(it.col, []); cellFlags.get(it.col).push(it) }
        const tds = cols.map(c => {
          const flags = cellFlags.get(c) || []
          const cls = flags.some(f => f.type === 'outlier' || f.type === 'type' || f.type === 'date' || f.type === 'duplicate') ? 'cell-bad' : (flags.some(f => f.type === 'suspicious') ? 'cell-warn' : '')
          const title = flags.map(f => `${f.type}${f.detail?` (${f.detail})`:''}`).join('; ')
          return `<td class=\"px-3 py-1 border-b ${cls}\" title=\"${title}\">${r[c] ?? ''}</td>`
        }).join('')
        const issuesText = (issues.map(x => `${x.col}:${x.type}${x.detail?`(${x.detail})`:''}`).join('; '))
        return `<tr><td class=\"px-3 py-1 border-b text-slate-500\">${r._row}</td>${tds}<td class=\"px-3 py-1 border-b text-slate-700\">${issuesText}</td></tr>`
      }).join('')
      wrap.innerHTML = `<table class="w-full text-sm">${header}<tbody>${body}</tbody></table>`
    }

    function groupKey(r, cols){ return cols.map(k => r[k]).join('\u241F') }

    function doReconciliation(glRows, tbRows, { glAcct, glAmt, glEnt, tbAcct, tbAmt, tbEnt, tol = 0 }){
      const glKeyCols = glEnt ? [glEnt, glAcct] : [glAcct]
      const tbKeyCols = tbEnt ? [tbEnt, tbAcct] : [tbAcct]
      const glMap = new Map(); let glSum = 0
      for (const r of glRows){ const k = groupKey(r, glKeyCols); const v = validNumber(r[glAmt]) ?? 0; glSum += v; glMap.set(k, (glMap.get(k) || 0) + v) }
      const tbMap = new Map(); let tbSum = 0
      for (const r of tbRows){ const k = groupKey(r, tbKeyCols); const v = validNumber(r[tbAmt]) ?? 0; tbSum += v; tbMap.set(k, (tbMap.get(k) || 0) + v) }
      const keys = new Set([...glMap.keys(), ...tbMap.keys()])
      const diffs = []
      for (const k of keys){
        const glv = glMap.get(k) || 0
        const tbv = tbMap.get(k) || 0
        const variance = glv - tbv
        if (Math.abs(variance) > Number(tol)){
          const parts = k.split('\u241F'); const obj = {}
          if (glEnt) obj[glEnt] = parts[0]
          if (tbEnt && !glEnt) obj[tbEnt] = parts[0]
          obj['Account'] = parts[glEnt ? 1 : 0]
          obj['GL Sum'] = glv
          obj['TB Amount'] = tbv
          obj['Variance'] = variance
          diffs.push(obj)
        }
      }
      const totalVar = glSum - tbSum
      return { diffs, totalVar, glSum, tbSum }
    }

    function renderReconTable(rows){
      const wrap = el('#recon-table-wrap')
      if (!rows.length){ wrap.innerHTML = '<div class="text-sm text-slate-500">No variances above tolerance.</div>'; return }
      const cols = Object.keys(rows[0])
      const header = `<thead><tr>${cols.map(h => `<th class=\"px-3 py-2 text-left text-xs font-medium text-slate-500 border-b\">${h}</th>`).join('')}</tr></thead>`
      const body = rows.map(r => `<tr>${cols.map(c => {
        const v = r[c]; const isNum = (typeof v === 'number'); const cls = (c === 'Variance' && Math.abs(v) > 0) ? 'cell-bad mono' : (isNum ? 'mono' : ''); const val = isNum ? fmt2.format(v) : v; return `<td class=\"px-3 py-1 border-b ${cls}\">${val ?? ''}</td>`
      }).join('')}</tr>`).join('')
      wrap.innerHTML = `<table class="w-full text-sm">${header}<tbody>${body}</tbody></table>`
    }

    function setTab(id){
      const isAnom = id === 'anomaly'
      el('#panel-anomaly').classList.toggle('hidden', !isAnom)
      el('#panel-recon').classList.toggle('hidden', isAnom)
      el('#tab-anomaly').classList.toggle('border-emerald-600', isAnom)
      el('#tab-anomaly').classList.toggle('text-emerald-700', isAnom)
      el('#tab-recon').classList.toggle('border-emerald-600', !isAnom)
      el('#tab-recon').classList.toggle('text-emerald-700', !isAnom)
      if (isAnom) el('#tab-recon').classList.remove('border-emerald-600','text-emerald-700')
      else el('#tab-anomaly').classList.remove('border-emerald-600','text-emerald-700')
    }

    // Wire up
    el('#tab-anomaly').addEventListener('click', () => setTab('anomaly'))
    el('#tab-recon').addEventListener('click', () => setTab('recon'))

    function enableDropzone(zone, onFile){
      zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('ring-2','ring-emerald-300') })
      zone.addEventListener('dragleave', () => { zone.classList.remove('ring-2','ring-emerald-300') })
      zone.addEventListener('drop', async e => { e.preventDefault(); zone.classList.remove('ring-2','ring-emerald-300'); const f = e.dataTransfer.files?.[0]; if (f) onFile(f) })
    }

    // Anomaly uploads
    el('#file-any').addEventListener('change', async (e) => {
      const f = e.target.files?.[0]; if (!f) return
      const rows = await parseFile(f)
      state.anyRows = rows
      state.anyCols = inferColumns(rows)
      populateSelectOptions(el('#keys-select'), state.anyCols)
      populateSelectOptions(el('#nums-select'), state.anyCols)
      populateSelectOptions(el('#dates-select'), state.anyCols)
      el('#anomaly-setup').classList.remove('hidden')
      el('#sum-rows').textContent = fmtInt.format(rows.length)
      el('#sum-cols').textContent = fmtInt.format(state.anyCols.length)
      ['#sum-missing','#sum-mismatch','#sum-outliers','#sum-dup','#sum-susp','#sum-bad-dates'].forEach(id => el(id).textContent = '—')
      el('#anomaly-table-card').classList.add('hidden')
    })
    enableDropzone(el('#dropzone-any'), async (f) => {
      const rows = await parseFile(f)
      state.anyRows = rows
      state.anyCols = inferColumns(rows)
      populateSelectOptions(el('#keys-select'), state.anyCols)
      populateSelectOptions(el('#nums-select'), state.anyCols)
      populateSelectOptions(el('#dates-select'), state.anyCols)
      el('#anomaly-setup').classList.remove('hidden')
      el('#sum-rows').textContent = fmtInt.format(rows.length)
      el('#sum-cols').textContent = fmtInt.format(state.anyCols.length)
      ['#sum-missing','#sum-mismatch','#sum-outliers','#sum-dup','#sum-susp','#sum-bad-dates'].forEach(id => el(id).textContent = '—')
      el('#anomaly-table-card').classList.add('hidden')
    })

    el('#btn-scan').addEventListener('click', () => {
      if (!state.anyRows.length) return
      const keyCols = Array.from(el('#keys-select').selectedOptions).map(o => o.value)
      const numCols = Array.from(el('#nums-select').selectedOptions).map(o => o.value)
      const dateCols = Array.from(el('#dates-select').selectedOptions).map(o => o.value)
      const chkOut = el('#chk-outliers').checked
      const chkDup = el('#chk-duplicates').checked
      const chkSusp = el('#chk-suspicious').checked
      const res = computeAnomalies(state.anyRows, state.anyCols, { keyCols, numCols, dateCols, chkOut, chkDup, chkSusp })
      state.anomalies = res
      state.anomTableRows = res.exportRows
      el('#sum-rows').textContent = fmtInt.format(res.counts.rows)
      el('#sum-cols').textContent = fmtInt.format(res.counts.cols)
      el('#sum-missing').textContent = fmtInt.format(res.counts.missing)
      el('#sum-mismatch').textContent = fmtInt.format(res.counts.mismatch)
      el('#sum-outliers').textContent = fmtInt.format(res.counts.outliers)
      el('#sum-dup').textContent = fmtInt.format(res.counts.dup)
      el('#sum-susp').textContent = fmtInt.format(res.counts.susp)
      el('#sum-bad-dates').textContent = fmtInt.format(res.counts.badDates)
      el('#anomaly-count').textContent = `${fmtInt.format(state.anomTableRows.length)} rows with issues`
      renderAnomalyTable(state.anomTableRows, state.anyCols, res.issuesByRow)
      el('#anomaly-table-card').classList.remove('hidden')
    })

    el('#btn-export-anoms').addEventListener('click', () => { if (!state.anomTableRows.length) return; download('anomalies.csv', toCSV(state.anomTableRows)) })

    // Reconciliation uploads
    function afterLoadGL(rows){ state.glRows = rows; const cols = inferColumns(rows); populateSelectOptions(el('#gl-account'), cols); populateSelectOptions(el('#gl-amount'), cols); populateSelectOptions(el('#gl-entity'), ['(none)', ...cols]); el('#gl-selects').classList.remove('hidden'); el('#gl-rows').textContent = fmtInt.format(rows.length) }
    function afterLoadTB(rows){ state.tbRows = rows; const cols = inferColumns(rows); populateSelectOptions(el('#tb-account'), cols); populateSelectOptions(el('#tb-amount'), cols); populateSelectOptions(el('#tb-entity'), ['(none)', ...cols]); el('#tb-selects').classList.remove('hidden'); el('#tb-rows').textContent = fmtInt.format(rows.length) }

    el('#file-gl').addEventListener('change', async e => { const f = e.target.files?.[0]; if (!f) return; afterLoadGL(await parseFile(f)) })
    el('#file-tb').addEventListener('change', async e => { const f = e.target.files?.[0]; if (!f) return; afterLoadTB(await parseFile(f)) })
    enableDropzone(el('#dropzone-gl'), async f => afterLoadGL(await parseFile(f)))
    enableDropzone(el('#dropzone-tb'), async f => afterLoadTB(await parseFile(f)))

    el('#btn-recon').addEventListener('click', () => {
      if (!state.glRows.length || !state.tbRows.length) return
      const glAcct = el('#gl-account').value
      const glAmt = el('#gl-amount').value
      const glEntVal = el('#gl-entity').value; const glEnt = (glEntVal && glEntVal !== '(none)') ? glEntVal : null
      const tbAcct = el('#tb-account').value
      const tbAmt = el('#tb-amount').value
      const tbEntVal = el('#tb-entity').value; const tbEnt = (tbEntVal && tbEntVal !== '(none)') ? tbEntVal : null
      const tol = Number(el('#tol').value || 0)
      const { diffs, totalVar, glSum, tbSum } = doReconciliation(state.glRows, state.tbRows, { glAcct, glAmt, glEnt, tbAcct, tbAmt, tbEnt, tol })
      el('#gl-sum').textContent = fmt2.format(glSum)
      el('#tb-sum').textContent = fmt2.format(tbSum)
      el('#total-var').textContent = fmt2.format(totalVar)
      el('#tie-status').textContent = Math.abs(totalVar) <= tol ? 'Ties (within tolerance)' : 'Does not tie'
      el('#tie-status').className = 'font-semibold ' + (Math.abs(totalVar) <= tol ? 'text-emerald-700' : 'text-red-700')
      renderReconTable(diffs)
      el('#recon-count').textContent = `${fmtInt.format(diffs.length)} accounts with variance > tolerance`
      el('#recon-table-card').classList.remove('hidden')
    })

    el('#btn-export-recon').addEventListener('click', () => {
      const wrap = el('#recon-table-wrap'); const table = wrap.querySelector('table'); if (!table) return
      const headers = Array.from(table.querySelectorAll('thead th')).map(th => th.textContent)
      const rows = Array.from(table.querySelectorAll('tbody tr')).map(tr => { const obj={}; const tds=tr.querySelectorAll('td'); headers.forEach((h,i)=>obj[h]=tds[i]?.textContent ?? ''); return obj })
      download('reconciliation_variances.csv', toCSV(rows))
    })

    return () => { /* no special cleanup */ }
  }, [])

  return (
    <main ref={rootRef} className="max-w-7xl mx-auto px-6 pb-16">
      <div className="mb-4">
        <nav className="flex gap-2 border-b">
          <button id="tab-anomaly" className="tab-btn border-b-2 border-emerald-600 text-emerald-700 -mb-px px-4 py-2 text-sm font-medium">Anomaly Scan</button>
          <button id="tab-recon" className="tab-btn border-b-2 border-transparent text-slate-600 hover:text-slate-800 -mb-px px-4 py-2 text-sm font-medium">GL ↔ TB Reconciliation</button>
        </nav>
      </div>

      <section id="panel-anomaly" className="space-y-6">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            <div className="bg-white rounded-2xl shadow p-5">
              <h2 className="font-semibold mb-3">Upload data</h2>
              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium mb-1">File</label>
                  <input id="file-any" type="file" accept=".xlsx,.xls,.csv,.json" className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm" />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Or drop here</label>
                  <div id="dropzone-any" className="rounded-xl border-2 border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">Drop a file (XLS/XLSX/CSV/JSON)</div>
                </div>
              </div>

              <div id="anomaly-setup" className="mt-6 hidden">
                <div className="grid sm:grid-cols-3 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-1">Key columns (optional for duplicate checks)</label>
                    <select id="keys-select" multiple className="w-full h-28 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm"></select>
                    <p className="text-xs text-slate-500 mt-1">Use Ctrl/Cmd-click to select multiple.</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1">Numeric columns (outlier scan)</label>
                    <select id="nums-select" multiple className="w-full h-28 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm"></select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1">Date columns</label>
                    <select id="dates-select" multiple className="w-full h-28 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm"></select>
                  </div>
                </div>
                <div className="mt-4 grid sm:grid-cols-3 gap-4">
                  <label className="inline-flex items-center gap-2 text-sm">
                    <input id="chk-outliers" type="checkbox" className="rounded" defaultChecked /> Outliers (|z| ≥ 3)
                  </label>
                  <label className="inline-flex items-center gap-2 text-sm">
                    <input id="chk-duplicates" type="checkbox" className="rounded" defaultChecked /> Duplicate keys
                  </label>
                  <label className="inline-flex items-center gap-2 text-sm">
                    <input id="chk-suspicious" type="checkbox" className="rounded" defaultChecked /> Suspicious strings (?, NA, null)
                  </label>
                </div>
                <div className="mt-4">
                  <button id="btn-scan" className="rounded-xl bg-emerald-600 text-white px-4 py-2 text-sm font-medium hover:bg-emerald-700">Run Anomaly Scan</button>
                  <button id="btn-export-anoms" className="ml-2 rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50">Export anomalies (CSV)</button>
                </div>
              </div>
            </div>
          </div>
          <div className="lg:col-span-1">
            <div className="bg-white rounded-2xl shadow p-5">
              <h3 className="font-semibold mb-3">Anomaly Summary</h3>
              <dl id="anomaly-summary" className="grid grid-cols-2 gap-4 text-sm">
                <div className="p-3 rounded-xl bg-slate-50">
                  <dt className="text-slate-500">Rows</dt>
                  <dd id="sum-rows" className="text-lg font-semibold">—</dd>
                </div>
                <div className="p-3 rounded-xl bg-slate-50">
                  <dt className="text-slate-500">Columns</dt>
                  <dd id="sum-cols" className="text-lg font-semibold">—</dd>
                </div>
                <div className="p-3 rounded-xl bg-slate-50">
                  <dt className="text-slate-500">Missing cells</dt>
                  <dd id="sum-missing" className="text-lg font-semibold">—</dd>
                </div>
                <div className="p-3 rounded-xl bg-slate-50">
                  <dt className="text-slate-500">Type mismatches</dt>
                  <dd id="sum-mismatch" className="text-lg font-semibold">—</dd>
                </div>
                <div className="p-3 rounded-xl bg-slate-50">
                  <dt className="text-slate-500">Outliers</dt>
                  <dd id="sum-outliers" className="text-lg font-semibold">—</dd>
                </div>
                <div className="p-3 rounded-xl bg-slate-50">
                  <dt className="text-slate-500">Duplicates</dt>
                  <dd id="sum-dup" className="text-lg font-semibold">—</dd>
                </div>
                <div className="p-3 rounded-xl bg-slate-50">
                  <dt className="text-slate-500">Suspicious strings</dt>
                  <dd id="sum-susp" className="text-lg font-semibold">—</dd>
                </div>
                <div className="p-3 rounded-xl bg-slate-50">
                  <dt className="text-slate-500">Bad dates</dt>
                  <dd id="sum-bad-dates" className="text-lg font-semibold">—</dd>
                </div>
              </dl>
            </div>
          </div>
        </div>

        <div id="anomaly-table-card" className="bg-white rounded-2xl shadow p-5 hidden">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold">Rows with anomalies</h3>
            <div className="text-sm text-slate-500" id="anomaly-count">—</div>
          </div>
          <div className="scroll-wrap sticky-th" id="anomaly-table-wrap"></div>
        </div>
      </section>

      <section id="panel-recon" className="space-y-6 hidden">
        <div className="bg-white rounded-2xl shadow p-5">
          <h2 className="font-semibold mb-3">Upload GL detail and TB summary</h2>
          <div className="grid md:grid-cols-2 gap-6">
            <div>
              <h3 className="font-medium mb-2">GL Detail</h3>
              <div className="grid sm:grid-cols-2 gap-4">
                <input id="file-gl" type="file" accept=".xlsx,.xls,.csv,.json" className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm" />
                <div id="dropzone-gl" className="rounded-xl border-2 border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">Drop GL file</div>
              </div>
              <div id="gl-selects" className="mt-4 hidden grid sm:grid-cols-3 gap-3">
                <div>
                  <label className="block text-sm font-medium mb-1">Account column</label>
                  <select id="gl-account" className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm"></select>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Amount column</label>
                  <select id="gl-amount" className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm"></select>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Optional: Entity/Segment</label>
                  <select id="gl-entity" className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm"></select>
                </div>
              </div>
            </div>
            <div>
              <h3 className="font-medium mb-2">Trial Balance (TB)</h3>
              <div className="grid sm:grid-cols-2 gap-4">
                <input id="file-tb" type="file" accept=".xlsx,.xls,.csv,.json" className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm" />
                <div id="dropzone-tb" className="rounded-xl border-2 border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">Drop TB file</div>
              </div>
              <div id="tb-selects" className="mt-4 hidden grid sm:grid-cols-3 gap-3">
                <div>
                  <label className="block text-sm font-medium mb-1">Account column</label>
                  <select id="tb-account" className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm"></select>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Amount column</label>
                  <select id="tb-amount" className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm"></select>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Optional: Entity/Segment</label>
                  <select id="tb-entity" className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm"></select>
                </div>
              </div>
            </div>
          </div>
          <div className="mt-4 grid md:grid-cols-4 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">Variance tolerance</label>
              <input id="tol" type="number" step="0.01" defaultValue="0" className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm" />
              <p className="text-xs text-slate-500 mt-1">Only show rows where |variance| &gt; tolerance.</p>
            </div>
            <div className="md:col-span-3 flex items-end gap-2">
              <button id="btn-recon" className="rounded-xl bg-emerald-600 text-white px-4 py-2 text-sm font-medium hover:bg-emerald-700">Run Reconciliation</button>
              <button id="btn-export-recon" className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50">Export variances (CSV)</button>
            </div>
          </div>
        </div>
        <div id="recon-summary-card" className="grid md:grid-cols-3 gap-4">
          <div className="bg-white rounded-2xl shadow p-5">
            <h3 className="font-semibold mb-2">GL Totals</h3>
            <dl className="text-sm grid grid-cols-2 gap-2">
              <dt className="text-slate-500">Rows</dt><dd id="gl-rows" className="font-semibold">—</dd>
              <dt className="text-slate-500">Sum</dt><dd id="gl-sum" className="mono font-semibold">—</dd>
            </dl>
          </div>
          <div className="bg-white rounded-2xl shadow p-5">
            <h3 className="font-semibold mb-2">TB Totals</h3>
            <dl className="text-sm grid grid-cols-2 gap-2">
              <dt className="text-slate-500">Rows</dt><dd id="tb-rows" className="font-semibold">—</dd>
              <dt className="text-slate-500">Sum</dt><dd id="tb-sum" className="mono font-semibold">—</dd>
            </dl>
          </div>
          <div className="bg-white rounded-2xl shadow p-5">
            <h3 className="font-semibold mb-2">Overall Tie-Out</h3>
            <dl className="text-sm grid grid-cols-2 gap-2">
              <dt className="text-slate-500">Variance</dt><dd id="total-var" className="mono font-semibold">—</dd>
              <dt className="text-slate-500">Status</dt><dd id="tie-status" className="font-semibold">—</dd>
            </dl>
          </div>
        </div>
        <div id="recon-table-card" className="bg-white rounded-2xl shadow p-5 hidden">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold">Accounts not tying to TB</h3>
            <div className="text-sm text-slate-500" id="recon-count">—</div>
          </div>
          <div className="scroll-wrap sticky-th" id="recon-table-wrap"></div>
        </div>
      </section>
    </main>
  )
}
