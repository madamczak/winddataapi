<template>
  <!-- =====================================================================
    App.vue — Wind Farm Data Explorer
    - Step 1: select farm + file type + date
    - Step 2: select columns (or "All columns")
    - Step 3: click Fetch Data → table appears
  ====================================================================== -->
  <div class="app">
    <header class="app-header">
      <h1>🌬️ Wind Farm Data Explorer</h1>
    </header>

    <main class="app-body">
      <!-- ── Controls panel ─────────────────────────────────────────── -->
      <section class="controls card">

        <!-- Row 1: Farm + File type -->
        <div class="control-row">
          <div class="control-group">
            <label for="farm-select">Wind Farm</label>
            <select id="farm-select" v-model="selectedFarm" @change="onFarmChange">
              <option value="" disabled>— select farm —</option>
              <option
                v-for="farm in farms"
                :key="farm.directory"
                :value="farm.directory"
              >
                {{ farm.name }} ({{ farm.turbine_count }} turbines)
              </option>
            </select>
          </div>

          <div class="control-group">
            <label for="turbine-select">Turbine</label>
            <select id="turbine-select" v-model="selectedTurbine" :disabled="!selectedFarm">
              <option value="" disabled>— select turbine —</option>
              <option
                v-for="t in availableTurbines"
                :key="t"
                :value="t"
              >
                {{ t }}
              </option>
            </select>
          </div>

          <div class="control-group">
            <label for="file-type-select">File Type</label>
            <select id="file-type-select" v-model="selectedFileType" @change="onFileTypeChange">
              <option value="" disabled>— select type —</option>
              <option
                v-for="ft in availableFileTypes"
                :key="ft"
                :value="ft"
              >
                {{ ft }}
              </option>
            </select>
          </div>

          <div class="control-group">
            <label for="date-input">Date</label>
            <input
              id="date-input"
              type="date"
              v-model="selectedDate"
              :min="minDate"
              :max="maxDate"
              :disabled="!selectedFarm"
            />
            <span v-if="minDate && maxDate" class="date-hint">
              {{ minDate }} → {{ maxDate }}
            </span>
          </div>

          <!-- Hour range filter -->
          <div class="control-group">
            <label>Hour From</label>
            <input
              id="hour-from-input"
              type="number"
              v-model.number="hourFrom"
              min="0"
              max="23"
              placeholder="0"
              :disabled="!selectedDate"
              class="hour-input"
            />
          </div>
          <div class="control-group">
            <label>Hour To</label>
            <input
              id="hour-to-input"
              type="number"
              v-model.number="hourTo"
              min="0"
              max="23"
              placeholder="23"
              :disabled="!selectedDate"
              class="hour-input"
            />
          </div>
        </div>

        <!-- Row 2: Column picker -->
        <div v-if="availableColumns.length" class="control-group column-picker">
          <label>Columns</label>

          <div class="column-toggle-row">
            <label class="checkbox-label all-cols">
              <input type="checkbox" v-model="allColumns" @change="onAllColumnsToggle" />
              <span>All columns</span>
            </label>
          </div>

          <div v-if="!allColumns" class="column-grid">
            <label
              v-for="col in availableColumns"
              :key="col"
              class="checkbox-label"
            >
              <input type="checkbox" :value="col" v-model="selectedColumns" />
              <span>{{ col }}</span>
            </label>
          </div>
        </div>

        <!-- Row 3: Fetch button -->
        <div class="control-row actions">
          <button
            class="btn-primary"
            :disabled="!canFetch || loading"
            @click="fetchData"
          >
            <span v-if="loading">⏳ Loading…</span>
            <span v-else>Fetch Data</span>
          </button>
          <span v-if="error" class="error-msg">{{ error }}</span>
        </div>
      </section>

      <!-- ── Results (tabbed) ───────────────────────────────────────── -->
      <section v-if="result" class="results card">

        <!-- Section title + meta -->
        <div class="results-header">
          <h2>{{ result.farm }} / {{ result.turbine }} / {{ result.file_type }} / {{ result.date }}</h2>
          <span class="row-count">{{ result.row_count.toLocaleString() }} rows</span>
        </div>

        <!-- Tab bar -->
        <div class="tab-bar">
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'table' }"
            @click="activeTab = 'table'"
          >
            📋 Data Table
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'charts' }"
            @click="activeTab = 'charts'"
          >
            📈 Charts
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'report' }"
            @click="activeTab = 'report'"
          >
            📊 Data Quality Report
          </button>
        </div>

        <!-- ── Tab: Data Table ────────────────────────────────────── -->
        <div :class="['tab-panel', activeTab !== 'table' && 'tab-panel--hidden']">
          <!-- Table toolbar -->
          <div class="table-toolbar">
            <input
              class="global-filter"
              type="search"
              v-model="globalFilter"
              placeholder="🔍 Search all columns…"
            />
            <button class="btn-clear" @click="clearFilters" title="Clear all filters &amp; sort">
              ✕ Clear filters
            </button>
            <!-- Rows per page -->
            <label class="page-size-label">
              Rows/page
              <select v-model="tablePageSize" class="page-size-select">
                <option :value="25">25</option>
                <option :value="50">50</option>
                <option :value="100">100</option>
                <option :value="200">200</option>
                <option :value="500">500</option>
              </select>
            </label>
            <div class="download-group">
              <select v-model="downloadFormat" class="download-format-select">
                <option value="csv">CSV</option>
                <option value="json">JSON</option>
              </select>
              <button class="btn-download" @click="downloadFile">
                ⬇ Download
              </button>
            </div>
          </div>

          <!-- Pagination bar -->
          <div class="pagination-bar">
            <button class="page-btn" :disabled="tablePage === 0" @click="tablePage = 0" title="First page">«</button>
            <button class="page-btn" :disabled="tablePage === 0" @click="tablePage--" title="Previous page">‹</button>
            <span class="page-info">
              Rows&nbsp;<strong>{{ tablePageStart + 1 }}–{{ tablePageEnd }}</strong>
              &nbsp;of&nbsp;<strong>{{ filteredRows.length.toLocaleString() }}</strong>
              <template v-if="filteredRows.length !== result.row_count">
                &nbsp;({{ result.row_count.toLocaleString() }} total)
              </template>
              &nbsp;· page&nbsp;{{ tablePage + 1 }}&nbsp;/&nbsp;{{ tableTotalPages }}
            </span>
            <input
              class="page-jump"
              type="number"
              min="1"
              :max="tableTotalPages"
              :value="tablePage + 1"
              @change="jumpTablePage($event.target.value)"
              title="Jump to page"
            />
            <button class="page-btn" :disabled="tablePage >= tableTotalPages - 1" @click="tablePage++" title="Next page">›</button>
            <button class="page-btn" :disabled="tablePage >= tableTotalPages - 1" @click="tablePage = tableTotalPages - 1" title="Last page">»</button>
          </div>

          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th
                    v-for="(col, ci) in result.columns"
                    :key="col"
                    class="sortable"
                    @click="setSort(ci)"
                  >
                    <span class="th-label">{{ col }}</span>
                    <span class="sort-icon">
                      <template v-if="sortCol === ci">
                        {{ sortDir === 1 ? '▲' : '▼' }}
                      </template>
                      <template v-else>⇅</template>
                    </span>
                  </th>
                </tr>
                <tr class="filter-row">
                  <th v-for="(_col, ci) in result.columns" :key="'f' + ci">
                    <input
                      class="col-filter"
                      type="text"
                      placeholder="filter…"
                      v-model="colFilters[ci]"
                    />
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, i) in pagedRows" :key="i">
                  <td v-for="(cell, j) in row" :key="j">{{ cell ?? '—' }}</td>
                </tr>
                <tr v-if="pagedRows.length === 0">
                  <td :colspan="result.columns.length" class="no-rows">No rows match the current filters.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- ── Tab: Charts ────────────────────────────────────────── -->
        <div v-if="activeTab === 'charts'" class="tab-panel">
          <ChartPanel :result="result" />
        </div>

        <!-- ── Tab: Data Quality Report ───────────────────────────── -->
        <div :class="['tab-panel', activeTab !== 'report' && 'tab-panel--hidden']">
          <div class="report">
            <div class="report-title">
              📊 Data Quality Report
              <span class="report-subtitle">
                {{ result.row_count }} rows · {{ result.columns.length }} columns ·
                "good" = non-null &amp; non-zero
              </span>
            </div>
            <div class="report-grid">
              <div
                v-for="stat in columnStats"
                :key="stat.col"
                class="stat-card"
                :class="stat.goodRate < 50 ? 'stat-bad' : stat.goodRate < 90 ? 'stat-warn' : 'stat-ok'"
              >
                <div class="stat-col-name" :title="stat.col">{{ stat.col }}</div>
                <div class="stat-bar-wrap">
                  <div class="stat-bar" :style="{ width: stat.goodRate + '%' }"></div>
                </div>
                <div class="stat-numbers">
                  <span class="stat-fill">{{ stat.goodRate }}% good</span>
                  <span v-if="stat.nullCount" class="stat-null">{{ stat.nullCount }} null</span>
                  <span v-if="stat.zeroCount" class="stat-zero">{{ stat.zeroCount }} zero</span>
                </div>
              </div>
            </div>
          </div>
        </div>

      </section>
    </main>
  </div>
</template>

<script setup>
/**
 * App.vue — main (and only) view for the Wind Farm Data Explorer.
 * Uses Vue 3 Composition API with <script setup>.
 */
import { ref, computed, watch, onMounted } from 'vue'
import { fetchWindFarms, fetchColumns, fetchDayData, fetchTimeRanges } from './api.js'
import ChartPanel from './ChartPanel.vue'

// ── State ──────────────────────────────────────────────────────────────────

/** All wind farms returned by /wind-farms */
const farms = ref([])

/** Columns metadata returned by /wind-farms/columns  { farm, columns_by_type } */
const columnsMap = ref([])

/** Time ranges per farm: { farm, earliest, latest } */
const timeRanges = ref([])

const selectedFarm     = ref('')
const selectedTurbine  = ref('')
const selectedFileType = ref('')
const selectedDate     = ref('')
const selectedColumns  = ref([])
const allColumns       = ref(true)

/** Optional hour range filter (0–23). null = no filter. */
const hourFrom = ref(null)
const hourTo   = ref(null)


const loading = ref(false)
const error   = ref('')
const result  = ref(null)

/** Which results tab is active: 'table' | 'charts' | 'report' */
const activeTab = ref('table')

// ── Sort & filter state ────────────────────────────────────────────────────
const globalFilter   = ref('')   // global search string
const colFilters     = ref([])   // per-column filter strings (indexed by column index)
const sortCol        = ref(null) // column index being sorted, or null
const sortDir        = ref(1)    // 1 = ascending, -1 = descending
const downloadFormat = ref('csv') // 'csv' | 'json'

// ── Table pagination state ─────────────────────────────────────────────────
const tablePage     = ref(0)   // 0-based current page index
const tablePageSize = ref(50)  // rows per page

// ── Derived ────────────────────────────────────────────────────────────────

/** Turbines available for the selected farm */
const availableTurbines = computed(() => {
  if (!selectedFarm.value) return []
  const farm = farms.value.find(f => f.directory === selectedFarm.value)
  return farm?.turbines ?? []
})

/** File types available for the selected farm */
const availableFileTypes = computed(() => {
  if (!selectedFarm.value) return []
  const entry = columnsMap.value.find(e => e.farm === selectedFarm.value)
  return entry ? Object.keys(entry.columns_by_type) : []
})

/** Column names for the selected farm + file type */
const availableColumns = computed(() => {
  if (!selectedFarm.value || !selectedFileType.value) return []
  const entry = columnsMap.value.find(e => e.farm === selectedFarm.value)
  return entry?.columns_by_type[selectedFileType.value] ?? []
})

/** ISO date string (YYYY-MM-DD) for the earliest record in the selected farm */
const minDate = computed(() => {
  if (!selectedFarm.value) return ''
  const tr = timeRanges.value.find(t => t.farm === selectedFarm.value)
  if (!tr?.earliest) return ''
  // earliest may be "2016-01-03 00:00:00" or "2016-01-03T00:00:00+0000"
  return tr.earliest.slice(0, 10)
})

/** ISO date string (YYYY-MM-DD) for the latest record in the selected farm */
const maxDate = computed(() => {
  if (!selectedFarm.value) return ''
  const tr = timeRanges.value.find(t => t.farm === selectedFarm.value)
  if (!tr?.latest) return ''
  return tr.latest.slice(0, 10)
})

/** True only when all required fields are filled */
const canFetch = computed(() =>
  selectedFarm.value &&
  selectedTurbine.value &&
  selectedFileType.value &&
  selectedDate.value
)

/**
 * Rows after applying global filter, per-column filters, and sort.
 * All filtering is case-insensitive string matching.
 */
const filteredRows = computed(() => {
  if (!result.value) return []

  // Skip the expensive filter/sort pass when the table tab isn't visible
  if (activeTab.value !== 'table') return result.value.rows

  const global = globalFilter.value.trim().toLowerCase()
  const perCol = colFilters.value.map(f => (f ?? '').trim().toLowerCase())

  let rows = result.value.rows

  // Global filter — row must contain the string in at least one cell
  if (global) {
    rows = rows.filter(row =>
      row.some(cell => String(cell ?? '').toLowerCase().includes(global))
    )
  }

  // Per-column filters
  perCol.forEach((f, ci) => {
    if (!f) return
    rows = rows.filter(row =>
      String(row[ci] ?? '').toLowerCase().includes(f)
    )
  })

  // Sort
  if (sortCol.value !== null) {
    const ci  = sortCol.value
    const dir = sortDir.value
    rows = [...rows].sort((a, b) => {
      const av = a[ci] ?? ''
      const bv = b[ci] ?? ''
      // Numeric sort when both values are numbers
      const an = parseFloat(av), bn = parseFloat(bv)
      if (!isNaN(an) && !isNaN(bn)) return (an - bn) * dir
      return String(av).localeCompare(String(bv)) * dir
    })
  }

  return rows
})

// ── Table pagination derived ───────────────────────────────────────────────
const tableTotalPages = computed(() =>
  Math.max(1, Math.ceil(filteredRows.value.length / tablePageSize.value))
)
const tablePageStart = computed(() => tablePage.value * tablePageSize.value)
const tablePageEnd   = computed(() =>
  Math.min(tablePageStart.value + tablePageSize.value, filteredRows.value.length)
)
/** The slice of filtered+sorted rows that is actually rendered in the table */
const pagedRows = computed(() =>
  filteredRows.value.slice(tablePageStart.value, tablePageEnd.value)
)

function jumpTablePage(val) {
  const n = parseInt(val, 10)
  if (!isNaN(n)) tablePage.value = Math.max(0, Math.min(tableTotalPages.value - 1, n - 1))
}

/**
 * Per-column data quality stats computed from the raw (unfiltered) result rows.
 * Nulls AND zeros are both treated as problematic values.
 * "Good" = non-null AND non-zero.
 * goodRate drives the colour thresholds and bar width.
 */
const columnStats = computed(() => {
  if (!result.value) return []
  const { columns, rows } = result.value
  const total = rows.length
  if (total === 0) return []

  return columns.map((col, ci) => {
    let nullCount = 0
    let zeroCount = 0
    for (const row of rows) {
      const v = row[ci]
      if (v === null || v === undefined || v === '') {
        nullCount++
      } else if (v === 0 || v === '0' || v === 0.0) {
        zeroCount++
      }
    }
    const badCount  = nullCount + zeroCount
    const goodCount = total - badCount
    const goodRate  = Math.round((goodCount / total) * 100)
    return { col, nullCount, zeroCount, badCount, goodCount, goodRate, total }
  })
})

// ── Handlers ───────────────────────────────────────────────────────────────

function onFarmChange() {
  selectedTurbine.value  = ''
  selectedFileType.value = ''
  selectedColumns.value  = []
  result.value           = null
  error.value            = ''
  // Auto-select first turbine
  const farm = farms.value.find(f => f.directory === selectedFarm.value)
  selectedTurbine.value = farm?.turbines?.[0] ?? ''
  // Auto-set date to the first available date for this farm
  const tr = timeRanges.value.find(t => t.farm === selectedFarm.value)
  selectedDate.value = tr?.earliest ? tr.earliest.slice(0, 10) : ''
}

function onFileTypeChange() {
  selectedColumns.value = []
  allColumns.value      = true
  result.value          = null
  error.value           = ''
}

function onAllColumnsToggle() {
  if (allColumns.value) {
    selectedColumns.value = []
  }
}

/** Toggle sort on a column: none → asc → desc → none */
function setSort(ci) {
  if (sortCol.value !== ci) {
    sortCol.value = ci
    sortDir.value = 1
  } else if (sortDir.value === 1) {
    sortDir.value = -1
  } else {
    sortCol.value = null
    sortDir.value = 1
  }
}

/** Clear all filters and sort */
function clearFilters() {
  globalFilter.value = ''
  colFilters.value   = result.value ? Array(result.value.columns.length).fill('') : []
  sortCol.value      = null
  sortDir.value      = 1
  tablePage.value    = 0
}

/**
 * Download the currently visible (filtered + sorted) rows as CSV or JSON.
 * Filename includes farm, file type and date for easy identification.
 */
function downloadFile() {
  if (!result.value || filteredRows.value.length === 0) return

  const { farm, file_type, date, columns } = result.value
  const rows = filteredRows.value
  const baseName = `${farm}_${file_type}_${date}`

  let content, mimeType, fileName

  if (downloadFormat.value === 'json') {
    // Array of objects: { "Column Name": value, ... }
    const objects = rows.map(row =>
      Object.fromEntries(columns.map((col, i) => [col, row[i] ?? null]))
    )
    content  = JSON.stringify(objects, null, 2)
    mimeType = 'application/json;charset=utf-8;'
    fileName = `${baseName}.json`
  } else {
    // CSV with RFC 4180 escaping
    const escape = val => {
      const s = String(val ?? '')
      return s.includes(',') || s.includes('"') || s.includes('\n')
        ? `"${s.replace(/"/g, '""')}"`
        : s
    }
    const header = columns.map(escape).join(',')
    const body   = rows.map(row => row.map(escape).join(',')).join('\n')
    content  = `${header}\n${body}`
    mimeType = 'text/csv;charset=utf-8;'
    fileName = `${baseName}.csv`
  }

  const blob = new Blob([content], { type: mimeType })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = fileName
  a.click()
  URL.revokeObjectURL(url)
}

async function fetchData() {
  if (!canFetch.value) return
  loading.value = true
  error.value   = ''
  result.value  = null

  try {
    const cols = allColumns.value ? [] : selectedColumns.value
    result.value = await fetchDayData(
      selectedFarm.value,
      selectedDate.value,
      selectedFileType.value,
      selectedTurbine.value,
      cols,
      hourFrom.value !== null && hourFrom.value !== '' ? hourFrom.value : null,
      hourTo.value   !== null && hourTo.value   !== '' ? hourTo.value   : null,
    )
    // Reset sort, filters, pagination and active tab for the new dataset
    globalFilter.value = ''
    colFilters.value   = Array(result.value.columns.length).fill('')
    sortCol.value      = null
    sortDir.value      = 1
    tablePage.value    = 0
    activeTab.value    = 'table'
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

// Reset table to page 1 whenever the filter or sort changes
watch([globalFilter, colFilters, sortCol, sortDir, tablePageSize], () => {
  tablePage.value = 0
})

// ── Initialisation ─────────────────────────────────────────────────────────

onMounted(async () => {
  try {
    const [farmsData, colsData, rangesData] = await Promise.all([
      fetchWindFarms(),
      fetchColumns(),
      fetchTimeRanges(),
    ])
    farms.value      = farmsData
    columnsMap.value = colsData
    timeRanges.value = rangesData
  } catch (e) {
    error.value = `Could not load farm metadata: ${e.message}`
  }
})
</script>

<style>
/* ── Global reset ─────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 14px;
  background: #f0f2f5;
  color: #1a1a2e;
}

/* ── Layout ───────────────────────────────────────────────────────────── */
.app { display: flex; flex-direction: column; min-height: 100vh; }

.app-header {
  background: #1a1a2e;
  color: #fff;
  padding: 16px 24px;
}
.app-header h1 { font-size: 20px; font-weight: 600; }

.app-body {
  flex: 1;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 1600px;
  width: 100%;
  margin: 0 auto;
}

/* ── Card ─────────────────────────────────────────────────────────────── */
.card {
  background: #fff;
  border-radius: 10px;
  padding: 20px 24px;
  box-shadow: 0 2px 8px rgba(0,0,0,.08);
}

/* ── Controls ─────────────────────────────────────────────────────────── */
.controls { display: flex; flex-direction: column; gap: 18px; }

.control-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: flex-end;
}

.control-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 180px;
}
/* Narrower width for the hour number inputs */
.hour-input { max-width: 90px; }
.control-group label {
  font-weight: 600;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .05em;
  color: #555;
}

select, input[type="date"] {
  padding: 8px 10px;
  border: 1px solid #d0d5dd;
  border-radius: 6px;
  font-size: 14px;
  background: #fff;
  color: #1a1a2e;
  cursor: pointer;
}
select:focus, input[type="date"]:focus {
  outline: 2px solid #4361ee;
  border-color: transparent;
}
input[type="date"]:disabled {
  background: #f0f2f5;
  color: #aaa;
  cursor: not-allowed;
}
.date-hint {
  font-size: 11px;
  color: #888;
  margin-top: 2px;
}

/* ── Column picker ────────────────────────────────────────────────────── */
.column-picker { max-width: 100%; }

.column-toggle-row { margin-bottom: 10px; }

.column-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 6px 12px;
  max-height: 240px;
  overflow-y: auto;
  border: 1px solid #e4e7ec;
  border-radius: 6px;
  padding: 10px;
  background: #fafafa;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  cursor: pointer;
  user-select: none;
  padding: 3px 0;
}
.checkbox-label.all-cols { font-weight: 600; }
.checkbox-label input { accent-color: #4361ee; width: 15px; height: 15px; cursor: pointer; }

/* ── Actions row ──────────────────────────────────────────────────────── */
.actions { align-items: center; }

.btn-primary {
  padding: 10px 28px;
  background: #4361ee;
  color: #fff;
  border: none;
  border-radius: 7px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background .15s;
}
.btn-primary:hover:not(:disabled) { background: #3451d1; }
.btn-primary:disabled { opacity: .5; cursor: not-allowed; }

.error-msg {
  color: #e53e3e;
  font-size: 13px;
  font-weight: 500;
}

/* ── Data quality report ──────────────────────────────────────────────── */
.report {
  border: 1px solid #e4e7ec;
  border-radius: 8px;
  padding: 14px 16px;
  background: #fafbfc;
}

.report-title {
  font-weight: 700;
  font-size: 13px;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.report-subtitle {
  font-weight: 400;
  font-size: 12px;
  color: #888;
}

.report-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 8px;
}

.stat-card {
  background: #fff;
  border: 1px solid #e4e7ec;
  border-radius: 7px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.stat-card.stat-ok   { border-left: 3px solid #38a169; }
.stat-card.stat-warn { border-left: 3px solid #d69e2e; }
.stat-card.stat-bad  { border-left: 3px solid #e53e3e; }

.stat-col-name {
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #333;
}

.stat-bar-wrap {
  height: 5px;
  background: #e4e7ec;
  border-radius: 3px;
  overflow: hidden;
}
.stat-bar {
  height: 100%;
  border-radius: 3px;
  background: #4361ee;
  transition: width .3s;
}
.stat-ok   .stat-bar { background: #38a169; }
.stat-warn .stat-bar { background: #d69e2e; }
.stat-bad  .stat-bar { background: #e53e3e; }

.stat-numbers {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 10px;
}
.stat-fill { color: #555; font-weight: 600; }
.stat-null { color: #e53e3e; }
.stat-zero { color: #d69e2e; }

/* ── Tabs ─────────────────────────────────────────────────────────────── */
.tab-bar {
  display: flex;
  gap: 0;
  border-bottom: 2px solid #e4e7ec;
  margin-bottom: 16px;
}

.tab-btn {
  padding: 10px 22px;
  background: none;
  border: none;
  border-bottom: 3px solid transparent;
  margin-bottom: -2px;
  font-size: 14px;
  font-weight: 600;
  color: #888;
  cursor: pointer;
  transition: color .15s, border-color .15s;
  white-space: nowrap;
}
.tab-btn:hover { color: #4361ee; }
.tab-btn.active {
  color: #4361ee;
  border-bottom-color: #4361ee;
}

.tab-panel {
  /* Isolate each panel's layout and paint so toggling display is cheap */
  contain: layout style;
  will-change: contents;
}
.tab-panel--hidden {
  /* Remove from layout & paint without destroying the DOM node */
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  pointer-events: none;
}


/* ── Results ──────────────────────────────────────────────────────────── */
.results { display: flex; flex-direction: column; gap: 14px; }

.results-header {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.results-header h2 { font-size: 15px; font-weight: 600; }
.row-count {
  font-size: 12px;
  color: #888;
  background: #f0f2f5;
  padding: 3px 9px;
  border-radius: 20px;
  white-space: nowrap;
}

/* Global search */
.global-filter {
  padding: 7px 10px;
  border: 1px solid #d0d5dd;
  border-radius: 6px;
  font-size: 13px;
  min-width: 220px;
  flex: 1;
  max-width: 360px;
}
.global-filter:focus { outline: 2px solid #4361ee; border-color: transparent; }

/* Clear filters button */
.btn-clear {
  padding: 7px 14px;
  border: 1px solid #d0d5dd;
  border-radius: 6px;
  background: #fff;
  font-size: 13px;
  cursor: pointer;
  color: #555;
  white-space: nowrap;
}
.btn-clear:hover { background: #f0f2f5; }

/* Download group: format selector + button */
.download-group {
  display: flex;
  align-items: center;
  gap: 0;
}
.download-format-select {
  padding: 7px 8px;
  border: 1px solid #4361ee;
  border-right: none;
  border-radius: 6px 0 0 6px;
  font-size: 13px;
  background: #fff;
  color: #4361ee;
  font-weight: 600;
  cursor: pointer;
  height: 34px;
}
.download-format-select:focus { outline: none; }

/* Download CSV button */
.btn-download {
  padding: 7px 14px;
  border: 1px solid #4361ee;
  border-radius: 0 6px 6px 0;
  background: #4361ee;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: background .15s;
  height: 34px;
}
.btn-download:hover { background: #3451d1; }

/* ── Table toolbar ───────────────────────────────────────────────────── */
.table-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.page-size-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #555;
  white-space: nowrap;
}

.page-size-select {
  padding: 6px 8px;
  border: 1px solid #d0d5dd;
  border-radius: 6px;
  font-size: 13px;
  background: #fff;
  cursor: pointer;
}

/* ── Pagination bar ───────────────────────────────────────────────────── */
.pagination-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 8px 12px;
  background: #fafbfc;
  border: 1px solid #e4e7ec;
  border-radius: 8px;
  font-size: 13px;
  margin-bottom: 10px;
}

.page-btn {
  min-width: 32px;
  height: 32px;
  padding: 0 8px;
  border: 1px solid #d0d5dd;
  border-radius: 6px;
  background: #fff;
  font-size: 15px;
  cursor: pointer;
  color: #4361ee;
  font-weight: 700;
  transition: background .12s;
  line-height: 1;
}
.page-btn:hover:not(:disabled) { background: #eef1fd; }
.page-btn:disabled { color: #ccc; cursor: not-allowed; }

.page-info { color: #555; white-space: nowrap; }

.page-jump {
  width: 58px;
  padding: 5px 8px;
  border: 1px solid #d0d5dd;
  border-radius: 6px;
  font-size: 13px;
  text-align: center;
}
.page-jump:focus { outline: 2px solid #4361ee; border-color: transparent; }
.page-jump::-webkit-inner-spin-button,
.page-jump::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }
.page-jump { -moz-appearance: textfield; }

.table-scroll {
  overflow: auto;
  max-height: 520px;
  border: 1px solid #e4e7ec;
  border-radius: 7px;
}

table {
  border-collapse: collapse;
  width: 100%;
  font-size: 13px;
}

thead {
  position: sticky;
  top: 0;
  z-index: 2;
}

/* Sort header row */
thead tr:first-child th {
  background: #1a1a2e;
  color: #fff;
  padding: 10px 12px;
  text-align: left;
  white-space: nowrap;
  border-right: 1px solid #2d2d4e;
  user-select: none;
}
thead tr:first-child th:last-child { border-right: none; }

th.sortable { cursor: pointer; }
th.sortable:hover { background: #2d2d4e; }
.th-label { margin-right: 4px; }
.sort-icon { font-size: 11px; opacity: .75; }

/* Filter input row */
thead tr.filter-row th {
  background: #f0f2f5;
  padding: 4px 6px;
  border-right: 1px solid #e4e7ec;
  border-bottom: 2px solid #d0d5dd;
}
thead tr.filter-row th:last-child { border-right: none; }

.col-filter {
  width: 100%;
  padding: 4px 6px;
  border: 1px solid #d0d5dd;
  border-radius: 4px;
  font-size: 12px;
  background: #fff;
}
.col-filter:focus { outline: 2px solid #4361ee; border-color: transparent; }

tbody tr:nth-child(even) { background: #f7f8fc; }
tbody tr:hover { background: #eef1fd; }

td {
  padding: 7px 12px;
  border-bottom: 1px solid #e4e7ec;
  border-right: 1px solid #e4e7ec;
  white-space: nowrap;
}
td:last-child { border-right: none; }

.no-rows {
  text-align: center;
  color: #888;
  padding: 24px;
  font-style: italic;
}
</style>

