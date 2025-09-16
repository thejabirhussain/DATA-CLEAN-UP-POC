import React, { useEffect, useRef } from 'react'
import * as XLSX from 'xlsx'
import * as arrow from 'apache-arrow'
import initWasm, { readParquet, Table as ParquetTable, writeParquet, WriterPropertiesBuilder, Compression } from 'parquet-wasm'
import parquetWasmUrl from 'parquet-wasm/esm/parquet_wasm_bg.wasm?url'

export default function Diagnostics(){
  const rootRef = useRef(null)

  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    // Prevent double-binding in React 18 Strict Mode (dev) where effects run twice
    if (root.dataset.bound === '1') return
    root.dataset.bound = '1'

    // Utilities
    const fmtInt = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 })
    const fmt2 = new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    const el = sel => root.querySelector(sel)
    const setTextAll = (sel, text) => { root.querySelectorAll(sel).forEach(n => { n.textContent = text }) }

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
      const s = String(x)
      // Remove everything except digits, decimal point, and minus sign
      const cleaned = s.replace(/[^\d.-]/g, '')
      // If nothing meaningful remains (no digits), treat as non-number
      if (!/[0-9]/.test(cleaned)) return null
      // Prevent strings like '-' or '.' or '-.' being treated as numbers
      if (/^[-.]+$/.test(cleaned)) return null
      const n = Number(cleaned)
      return Number.isFinite(n) ? n : null
    }

    function parseDateLoose(x){
      if (x === null || x === undefined || x === '') return null
      // Only treat string-like values with common date separators as dates
      if (typeof x !== 'string') return null
      const s = x.trim()
      // Quick precheck: contains '-', '/', or 'T' (ISO). Avoid free-form numerics.
      if (!/[\-\/T]/.test(s)) return null
      const d = new Date(s)
      if (isNaN(+d)) return null
      const y = d.getFullYear()
      // Reasonable year bounds for business data
      if (y < 1900 || y > 2100) return null
      return d
    }

    let parquetReady = false
    async function ensureParquetInit(){ if (parquetReady) return; await initWasm(parquetWasmUrl); parquetReady = true }

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

    function rowsToArrowTable(rows){
      const cols = Object.keys(rows[0] || {})
      const arrays = {}; cols.forEach(h => arrays[h] = rows.map(r => r[h]))
      return arrow.tableFromArrays(arrays)
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
      } else if (ext === 'parquet'){
        await ensureParquetInit()
        const buf = new Uint8Array(await file.arrayBuffer())
        const wasmTable = readParquet(buf)
        const table = arrow.tableFromIPC(wasmTable.intoIPCStream())
        const { rows } = tableToRows(table)
        return rows.map(r => flatten(r))
      } else { throw new Error('Unsupported file type') }
    }

    function inferColumns(rows){ const cols = new Set(); for (const r of rows) for (const k of Object.keys(r)) cols.add(k); return Array.from(cols) }

    // Infer disjoint column categories to avoid duplicate appearance across selects
    function inferColumnCategories(rows, cols){
      const stats = {}
      for (const c of cols){ stats[c] = { total: 0, num: 0, date: 0 } }
      for (const r of rows){
        for (const c of cols){
          const v = r[c]
          if (v === null || v === undefined || v === '') continue
          stats[c].total++
          if (validNumber(v) !== null) stats[c].num++
          if (parseDateLoose(v)) stats[c].date++
        }
      }
      const dateCols = []
      const numCols = []
      const keyCols = []
      const used = new Set()
      // Classify dates first (>=60% look like dates)
      for (const c of cols){ const s = stats[c]; const frac = s.total ? (s.date / s.total) : 0; if (frac >= 0.6){ dateCols.push(c); used.add(c) } }
      // Then numbers among remaining (>=75% numbers) to reduce false positives
      for (const c of cols){ if (used.has(c)) continue; const s = stats[c]; const frac = s.total ? (s.num / s.total) : 0; if (frac >= 0.75){ numCols.push(c); used.add(c) } }
      // Remaining are treated as key/categorical columns
      for (const c of cols){ if (!used.has(c)) keyCols.push(c) }
      return { keyCols, numCols, dateCols }
    }

    const state = { anyRows: [], anyCols: [], anomalies: null, anomTableRows: [], glRows: [], tbRows: [] }

    function populateSelectOptions(select, options){ select.innerHTML=''; for (const c of options){ const opt=document.createElement('option'); opt.value=c; opt.textContent=c; select.appendChild(opt) } }

    function computeAnomalies(rows, cols, { keyCols = [], numCols = [], dateCols = [], chkOut = true, chkDup = true, chkSusp = true } = {}){
      const N = rows.length; const C = cols.length
      const issuesByRow = new Map()
      const pushIssue = (idx, col, type, detail) => { if (!issuesByRow.has(idx)) issuesByRow.set(idx, []); issuesByRow.get(idx).push({ col, type, detail }) }

      let missingCells = 0, mismatches = 0, badDates = 0, suspCount = 0

      // Track per-column missing counts to detect mostly-empty columns
      const missingByCol = new Map(); for (const c of cols) missingByCol.set(c, 0)

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
          if (v === null || v === undefined || v === '') { missingCells++; missingByCol.set(col, missingByCol.get(col)+1); continue }
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

      // Compute mostly-empty columns (>=80% empty)
      const mostlyEmpty = []
      for (const col of cols){
        const miss = missingByCol.get(col) || 0
        const pct = N ? miss / N : 0
        if (pct >= 0.8) mostlyEmpty.push({ column: col, pctEmpty: pct })
      }

      const anomRows = []
      issuesByRow.forEach((reasons, idx) => {
        const base = { _row: idx + 1 }
        for (const c of cols) base[c] = rows[idx][c]
        base._issues = reasons.map(x => `${x.col}:${x.type}${x.detail?`(${x.detail})`:''}`).join('; ')
        anomRows.push(base)
      })
      const outlierCount = Array.from(issuesByRow.values()).flat().filter(x => x.type === 'outlier').length
      return { issuesByRow, exportRows: anomRows, mostlyEmpty, counts: { rows: N, cols: C, missing: missingCells, mismatch: mismatches, outliers: outlierCount, dup: dupCount, susp: suspCount, badDates, mostlyEmpty: mostlyEmpty.length } }
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

    // Initialize accordion dropdown behavior
    setupAccordions()

    function enableDropzone(zone, onFile){
      zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('ring-2','ring-emerald-300') })
      zone.addEventListener('dragleave', () => { zone.classList.remove('ring-2','ring-emerald-300') })
      zone.addEventListener('drop', async e => { e.preventDefault(); zone.classList.remove('ring-2','ring-emerald-300'); const f = e.dataTransfer.files?.[0]; if (f) onFile(f) })
    }

    // Simple accordion toggles for anomaly cards (event delegation)
    function setupAccordions(){
      root.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-acc-toggle]')
        if (!btn || !root.contains(btn)) return
        e.preventDefault()
        const target = btn.getAttribute('data-acc-toggle')
        if (!target) return
        const panel = el(target)
        if (!panel) return
        const isHidden = panel.classList.toggle('hidden')
        // aria-expanded for a11y
        btn.setAttribute('aria-expanded', String(!isHidden))
        btn.querySelector('.chev')?.classList.toggle('rotate-180')
      })
    }

    // Render segregated anomaly tables with highlighted cells by type
    function renderAnomalyBuckets(res){
      const byRow = res.issuesByRow
      const cols = state.anyCols
      const rows = state.anyRows

      function groupByType(type){
        const map = new Map()
        byRow.forEach((arr, idx) => {
          arr.forEach(it => {
            if (it.type !== type) return
            if (!map.has(idx)) map.set(idx, { cols: new Map() })
            // track per-col details (could be multiple)
            const colMap = map.get(idx).cols
            if (!colMap.has(it.col)) colMap.set(it.col, [])
            colMap.get(it.col).push(it.detail || '')
          })
        })
        return map
      }

      function renderTable(containerId, type){
        const cont = el(containerId)
        if (!cont) return
        const grouped = groupByType(type)
        if (!grouped.size){ cont.innerHTML = '<div class="text-slate-500 text-sm">None</div>'; return }
        const thead = `<thead><tr><th class=\"px-3 py-2 text-left text-xs font-medium text-slate-500 border-b\">#</th>${cols.map(h => `<th class=\"px-3 py-2 text-left text-xs font-medium text-slate-500 border-b\">${h}</th>`).join('')}</tr></thead>`
        const tbody = Array.from(grouped.keys()).sort((a,b)=>a-b).map(idx => {
          const r = rows[idx] || {}
          const colMap = grouped.get(idx).cols
          const tds = cols.map(c => {
            const v = r[c]
            const has = colMap.has(c)
            const cls = type === 'suspicious' ? (has ? 'cell-warn' : '') : (has ? 'cell-bad' : '')
            const title = has ? `${type}${(colMap.get(c) || []).filter(Boolean).length ? (' ('+colMap.get(c).filter(Boolean).join(', ')+')') : ''}` : ''
            return `<td class=\"px-3 py-1 border-b ${cls}\" title=\"${title}\">${v ?? ''}</td>`
          }).join('')
          return `<tr><td class=\"px-3 py-1 border-b text-slate-500\">${idx+1}</td>${tds}</tr>`
        }).join('')
        cont.innerHTML = `<div class=\"scroll-wrap\"><table class=\"w-full text-sm\">${thead}<tbody>${tbody}</tbody></table></div>`
        return grouped.size
      }

      const dupN = renderTable('#dup-list', 'duplicate') || 0
      const suspN = renderTable('#susp-list', 'suspicious') || 0
      const numN = renderTable('#num-mismatch-list', 'type') || 0
      const outN = renderTable('#outlier-list', 'outlier') || 0
      const dateN = renderTable('#date-list', 'date') || 0

      const setCnt = (id, n) => { const sp = el(id); if (sp) sp.textContent = String(n) }
      setCnt('#cnt-dup', dupN)
      setCnt('#cnt-susp', suspN)
      setCnt('#cnt-num-mismatch', numN)
      setCnt('#cnt-outliers', outN)
      setCnt('#cnt-date', dateN)
      const sumEmpty = el('#cnt-mostly-empty'); if (sumEmpty) sumEmpty.textContent = String(res.mostlyEmpty.length)
      const sumAll = el('#cnt-summary'); if (sumAll) sumAll.textContent = String(res.exportRows.length)
    }

    // Anomaly uploads
    el('#file-any').addEventListener('change', async (e) => {
      const f = e.target.files?.[0]; if (!f) return
      const rows = await parseFile(f)
      state.anyRows = rows
      state.anyCols = inferColumns(rows)
      const cats = inferColumnCategories(rows, state.anyCols)
      populateSelectOptions(el('#keys-select'), cats.keyCols)
      populateSelectOptions(el('#nums-select'), cats.numCols)
      populateSelectOptions(el('#dates-select'), cats.dateCols)
      el('#anomaly-setup').classList.remove('hidden')
      setTextAll('#sum-rows', fmtInt.format(rows.length))
      setTextAll('#sum-cols', fmtInt.format(state.anyCols.length))
      ;['#sum-missing','#sum-mismatch','#sum-outliers','#sum-dup','#sum-susp','#sum-bad-dates','#sum-mostly-empty'].forEach(id => setTextAll(id, '—'))
      el('#anomaly-table-card').classList.add('hidden')
      const emptyList = el('#mostly-empty-list'); if (emptyList) emptyList.innerHTML = ''
      const emptyCard = el('#mostly-empty-card'); if (emptyCard) emptyCard.classList.add('hidden')
      // Clear segregated cards
      ['#dup-list','#susp-list','#num-mismatch-list','#outlier-list','#date-list'].forEach(id => { const ul = el(id); if (ul) ul.innerHTML = '' })
      ['#cnt-dup','#cnt-susp','#cnt-num-mismatch','#cnt-outliers','#cnt-date','#cnt-mostly-empty','#cnt-summary'].forEach(id => { const sp = el(id); if (sp) sp.textContent = '0' })
    })
    enableDropzone(el('#dropzone-any'), async (f) => {
      const rows = await parseFile(f)
      state.anyRows = rows
      state.anyCols = inferColumns(rows)
      const cats = inferColumnCategories(rows, state.anyCols)
      populateSelectOptions(el('#keys-select'), cats.keyCols)
      populateSelectOptions(el('#nums-select'), cats.numCols)
      populateSelectOptions(el('#dates-select'), cats.dateCols)
      el('#anomaly-setup').classList.remove('hidden')
      el('#sum-rows').textContent = fmtInt.format(rows.length)
      el('#sum-cols').textContent = fmtInt.format(state.anyCols.length)
      ['#sum-missing','#sum-mismatch','#sum-outliers','#sum-dup','#sum-susp','#sum-bad-dates','#sum-mostly-empty'].forEach(id => el(id).textContent = '—')
      el('#anomaly-table-card').classList.add('hidden')
      const emptyList = el('#mostly-empty-list'); if (emptyList) emptyList.innerHTML = ''
      const emptyCard = el('#mostly-empty-card'); if (emptyCard) emptyCard.classList.add('hidden')
      // Clear segregated cards and reset counters
      ['#dup-list','#susp-list','#num-mismatch-list','#outlier-list','#date-list'].forEach(id => { const ul = el(id); if (ul) ul.innerHTML = '' })
      ['#cnt-dup','#cnt-susp','#cnt-num-mismatch','#cnt-outliers','#cnt-date','#cnt-mostly-empty','#cnt-summary'].forEach(id => { const sp = el(id); if (sp) sp.textContent = '0' })
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
      setTextAll('#sum-rows', fmtInt.format(res.counts.rows))
      setTextAll('#sum-cols', fmtInt.format(res.counts.cols))
      setTextAll('#sum-missing', fmtInt.format(res.counts.missing))
      setTextAll('#sum-mismatch', fmtInt.format(res.counts.mismatch))
      setTextAll('#sum-outliers', fmtInt.format(res.counts.outliers))
      setTextAll('#sum-dup', fmtInt.format(res.counts.dup))
      setTextAll('#sum-susp', fmtInt.format(res.counts.susp))
      setTextAll('#sum-bad-dates', fmtInt.format(res.counts.badDates))
      setTextAll('#sum-mostly-empty', fmtInt.format(res.counts.mostlyEmpty))
      // Render mostly-empty columns list
      const emptyList = el('#mostly-empty-list')
      if (emptyList){
        if (res.mostlyEmpty.length){
          emptyList.innerHTML = res.mostlyEmpty
            .sort((a,b)=> b.pctEmpty - a.pctEmpty)
            .map(x => `<li class=\"py-0.5\"><span class=\"font-medium\">${x.column}</span> — ${fmt2.format(x.pctEmpty*100)}%</li>`)
            .join('')
        } else {
          emptyList.innerHTML = '<li class="text-slate-500">None</li>'
        }
      }
      const emptyCard = el('#mostly-empty-card'); if (emptyCard) emptyCard.classList.remove('hidden')
      el('#anomaly-count').textContent = `${fmtInt.format(state.anomTableRows.length)} rows with issues`
      renderAnomalyTable(state.anomTableRows, state.anyCols, res.issuesByRow)
      el('#anomaly-table-card').classList.remove('hidden')
      // Populate segregated dropdown cards
      renderAnomalyBuckets(res)
    })

    el('#btn-export-anoms').addEventListener('click', () => { if (!state.anomTableRows.length) return; download('anomalies.csv', toCSV(state.anomTableRows)) })
    const btnExportAnomsJSON = el('#btn-export-anoms-json')
    if (btnExportAnomsJSON) btnExportAnomsJSON.addEventListener('click', () => {
      if (!state.anomTableRows.length) return
      const jsonStr = JSON.stringify(state.anomTableRows, null, 2)
      const blob = new Blob([jsonStr], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'anomalies.json'; document.body.appendChild(a); a.click(); setTimeout(()=>{ document.body.removeChild(a); URL.revokeObjectURL(url) },0)
    })
    const btnExportAnomsParquet = el('#btn-export-anoms-parquet')
    if (btnExportAnomsParquet) btnExportAnomsParquet.addEventListener('click', async () => {
      if (!state.anomTableRows.length) return
      try{
        await ensureParquetInit()
        const table = rowsToArrowTable(state.anomTableRows)
        const wasmTable = ParquetTable.fromIPCStream(arrow.tableToIPC(table, 'stream'))
        const writerProps = new WriterPropertiesBuilder().setCompression(Compression.ZSTD).build()
        const pq = writeParquet(wasmTable, writerProps)
        const blob = new Blob([pq], { type: 'application/octet-stream' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a'); a.href=url; a.download='anomalies.parquet'; document.body.appendChild(a); a.click(); setTimeout(()=>{ document.body.removeChild(a); URL.revokeObjectURL(url) },0)
      } catch(e){ console.error(e); alert('Failed to export Parquet: ' + e.message) }
    })

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
    const btnExportReconJSON = el('#btn-export-recon-json')
    if (btnExportReconJSON) btnExportReconJSON.addEventListener('click', () => {
      const wrap = el('#recon-table-wrap'); const table = wrap.querySelector('table'); if (!table) return
      const headers = Array.from(table.querySelectorAll('thead th')).map(th => th.textContent)
      const rows = Array.from(table.querySelectorAll('tbody tr')).map(tr => { const obj={}; const tds=tr.querySelectorAll('td'); headers.forEach((h,i)=>obj[h]=tds[i]?.textContent ?? ''); return obj })
      const jsonStr = JSON.stringify(rows, null, 2)
      const blob = new Blob([jsonStr], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'reconciliation_variances.json'; document.body.appendChild(a); a.click(); setTimeout(()=>{ document.body.removeChild(a); URL.revokeObjectURL(url) },0)
    })
    const btnExportReconParquet = el('#btn-export-recon-parquet')
    if (btnExportReconParquet) btnExportReconParquet.addEventListener('click', async () => {
      const wrap = el('#recon-table-wrap'); const table = wrap.querySelector('table'); if (!table) return
      const headers = Array.from(table.querySelectorAll('thead th')).map(th => th.textContent)
      const rows = Array.from(table.querySelectorAll('tbody tr')).map(tr => { const obj={}; const tds=tr.querySelectorAll('td'); headers.forEach((h,i)=>obj[h]=tds[i]?.textContent ?? ''); return obj })
      try{
        await ensureParquetInit()
        const atable = rowsToArrowTable(rows)
        const wasm = ParquetTable.fromIPCStream(arrow.tableToIPC(atable, 'stream'))
        const props = new WriterPropertiesBuilder().setCompression(Compression.ZSTD).build()
        const pq = writeParquet(wasm, props)
        const blob = new Blob([pq], { type: 'application/octet-stream' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a'); a.href=url; a.download='reconciliation_variances.parquet'; document.body.appendChild(a); a.click(); setTimeout(()=>{ document.body.removeChild(a); URL.revokeObjectURL(url) },0)
      } catch(e){ console.error(e); alert('Failed to export Parquet: ' + e.message) }
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
                  <input id="file-any" type="file" accept=".xlsx,.xls,.csv,.json,.parquet" className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm" />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Or drop here</label>
                  <div id="dropzone-any" className="rounded-xl border-2 border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">Drop a file (XLS/XLSX/CSV/JSON/Parquet)</div>
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
                  <button id="btn-export-anoms-json" className="ml-2 rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50">Export anomalies (JSON)</button>
                  <button id="btn-export-anoms-parquet" className="ml-2 rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50">Export anomalies (Parquet)</button>
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
                <div className="p-3 rounded-xl bg-slate-50">
                  <dt className="text-slate-500">Mostly-empty columns (≥80%)</dt>
                  <dd id="sum-mostly-empty" className="text-lg font-semibold">—</dd>
                </div>
              </dl>
            </div>
          </div>
        </div>

        {/* Accordion: Summary */}
        <div id="summary-card" className="bg-white rounded-2xl shadow">
          <button className="w-full flex items-center justify-between px-5 py-3" data-acc-toggle="#summary-panel">
            <h3 className="font-semibold">Summary</h3>
            <div className="text-sm text-slate-500">Total anomalies: <span id="cnt-summary">0</span> <span className="chev inline-block transform transition-transform">▾</span></div>
          </button>
          <div id="summary-panel" className="p-5">
            <dl id="anomaly-summary-inline" className="grid grid-cols-2 md:grid-cols-5 gap-4 text-sm">
              <div className="p-3 rounded-xl bg-slate-50"><dt className="text-slate-500">Rows</dt><dd id="sum-rows" className="text-lg font-semibold">—</dd></div>
              <div className="p-3 rounded-xl bg-slate-50"><dt className="text-slate-500">Columns</dt><dd id="sum-cols" className="text-lg font-semibold">—</dd></div>
              <div className="p-3 rounded-xl bg-slate-50"><dt className="text-slate-500">Missing cells</dt><dd id="sum-missing" className="text-lg font-semibold">—</dd></div>
              <div className="p-3 rounded-xl bg-slate-50"><dt className="text-slate-500">Type mismatches</dt><dd id="sum-mismatch" className="text-lg font-semibold">—</dd></div>
              <div className="p-3 rounded-xl bg-slate-50"><dt className="text-slate-500">Duplicates</dt><dd id="sum-dup" className="text-lg font-semibold">—</dd></div>
            </dl>
          </div>
        </div>

        {/* Mostly-empty columns list (accordion) */}
        <div id="mostly-empty-card" className="bg-white rounded-2xl shadow">
          <button className="w-full flex items-center justify-between px-5 py-3" data-acc-toggle="#mostly-empty-panel">
            <h3 className="font-semibold">Mostly-empty columns (≥80% empty)</h3>
            <div className="text-sm text-slate-500">Count: <span id="cnt-mostly-empty">0</span> <span className="chev inline-block transform transition-transform">▾</span></div>
          </button>
          <div id="mostly-empty-panel" className="p-5 hidden">
            <ul id="mostly-empty-list" className="text-sm list-disc pl-6"></ul>
          </div>
        </div>

        {/* Duplicates */}
        <div id="dup-card" className="bg-white rounded-2xl shadow">
          <button className="w-full flex items-center justify-between px-5 py-3" data-acc-toggle="#dup-panel">
            <h3 className="font-semibold">Duplicates</h3>
            <div className="text-sm text-slate-500">Count: <span id="cnt-dup">0</span> <span className="chev inline-block transform transition-transform">▾</span></div>
          </button>
          <div id="dup-panel" className="p-5 hidden">
            <div id="dup-list" className="text-sm"></div>
          </div>
        </div>

        {/* Suspicious values */}
        <div id="susp-card" className="bg-white rounded-2xl shadow">
          <button className="w-full flex items-center justify-between px-5 py-3" data-acc-toggle="#susp-panel">
            <h3 className="font-semibold">Unknown / suspicious values (?, NA, null)</h3>
            <div className="text-sm text-slate-500">Count: <span id="cnt-susp">0</span> <span className="chev inline-block transform transition-transform">▾</span></div>
          </button>
          <div id="susp-panel" className="p-5 hidden">
            <div id="susp-list" className="text-sm"></div>
          </div>
        </div>

        {/* Type mismatches (numbers) */}
        <div id="num-mismatch-card" className="bg-white rounded-2xl shadow">
          <button className="w-full flex items-center justify-between px-5 py-3" data-acc-toggle="#num-mismatch-panel">
            <h3 className="font-semibold">Type mismatches (Numeric columns)</h3>
            <div className="text-sm text-slate-500">Count: <span id="cnt-num-mismatch">0</span> <span className="chev inline-block transform transition-transform">▾</span></div>
          </button>
          <div id="num-mismatch-panel" className="p-5 hidden">
            <div id="num-mismatch-list" className="text-sm"></div>
          </div>
        </div>

        {/* Outliers (numeric) */}
        <div id="outlier-card" className="bg-white rounded-2xl shadow">
          <button className="w-full flex items-center justify-between px-5 py-3" data-acc-toggle="#outlier-panel">
            <h3 className="font-semibold">Outliers (Numeric columns)</h3>
            <div className="text-sm text-slate-500">Count: <span id="cnt-outliers">0</span> <span className="chev inline-block transform transition-transform">▾</span></div>
          </button>
          <div id="outlier-panel" className="p-5 hidden">
            <div id="outlier-list" className="text-sm"></div>
          </div>
        </div>

        {/* Dates */}
        <div id="date-card" className="bg-white rounded-2xl shadow">
          <button className="w-full flex items-center justify-between px-5 py-3" data-acc-toggle="#date-panel">
            <h3 className="font-semibold">Date anomalies</h3>
            <div className="text-sm text-slate-500">Count: <span id="cnt-date">0</span> <span className="chev inline-block transform transition-transform">▾</span></div>
          </button>
          <div id="date-panel" className="p-5 hidden">
            <div id="date-list" className="text-sm"></div>
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
                <input id="file-gl" type="file" accept=".xlsx,.xls,.csv,.json,.parquet" className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm" />
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
                <input id="file-tb" type="file" accept=".xlsx,.xls,.csv,.json,.parquet" className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm" />
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
              <button id="btn-export-recon-json" className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50">Export variances (JSON)</button>
              <button id="btn-export-recon-parquet" className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50">Export variances (Parquet)</button>
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
