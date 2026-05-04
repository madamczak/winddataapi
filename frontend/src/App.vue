<template>
  <div class="app">
    <header class="app-header">
      <h1>🌬️ Wind Farm Data Explorer</h1>
      <!-- ── Top-level navigation tabs ───────────────────────────── -->
      <div class="main-tab-bar">
        <button class="main-tab-btn" :class="{ active: mainTab === 'query' }" @click="mainTab = 'query'">🔍 Query for Data</button>
        <button class="main-tab-btn" :class="{ active: mainTab === 'events' }" @click="mainTab = 'events'">📅 Query for Events</button>
        <button class="main-tab-btn" :class="{ active: mainTab === 'custom' }" @click="mainTab = 'custom'">⭐ Custom Queries</button>
      </div>
    </header>

    <main class="app-body">

      <!-- ══ PAGE: Query for Data ══ -->
      <template v-if="mainTab === 'query'">
        <section class="controls card">
          <div class="control-row">
            <div class="control-group">
              <label for="farm-select">Wind Farm</label>
              <select id="farm-select" v-model="selectedFarm" @change="onFarmChange">
                <option value="" disabled>— select farm —</option>
                <option v-for="farm in farms" :key="farm.directory" :value="farm.directory">
                  {{ farm.name }} ({{ farm.turbine_count }} turbines)
                </option>
              </select>
            </div>
            <div class="control-group">
              <label for="turbine-select">Turbine</label>
              <select id="turbine-select" v-model="selectedTurbine" :disabled="!selectedFarm">
                <option value="" disabled>— select turbine —</option>
                <option v-for="t in availableTurbines" :key="t" :value="t">{{ t }}</option>
              </select>
            </div>
            <div class="control-group">
              <label for="file-type-select">File Type</label>
              <select id="file-type-select" v-model="selectedFileType" @change="onFileTypeChange">
                <option value="" disabled>— select type —</option>
                <option v-for="ft in availableFileTypes" :key="ft" :value="ft">{{ ft }}</option>
              </select>
            </div>
            <div class="control-group">
              <label for="date-input">Date</label>
              <input id="date-input" type="date" v-model="selectedDate" :min="minDate" :max="maxDate" :disabled="!selectedFarm" />
              <span v-if="minDate && maxDate" class="date-hint">{{ minDate }} → {{ maxDate }}</span>
            </div>
            <div class="control-group">
              <label>Hour From</label>
              <input type="number" v-model.number="hourFrom" min="0" max="23" placeholder="0" :disabled="!selectedDate" class="hour-input" />
            </div>
            <div class="control-group">
              <label>Hour To</label>
              <input type="number" v-model.number="hourTo" min="0" max="23" placeholder="23" :disabled="!selectedDate" class="hour-input" />
            </div>
          </div>

          <div v-if="availableColumns.length" class="control-group column-picker">
            <label>Columns</label>
            <div class="column-toggle-row">
              <label class="checkbox-label all-cols">
                <input type="checkbox" v-model="allColumns" @change="onAllColumnsToggle" />
                <span>All columns</span>
              </label>
            </div>
            <div v-if="!allColumns" class="column-grid">
              <label v-for="col in availableColumns" :key="col" class="checkbox-label">
                <input type="checkbox" :value="col" v-model="selectedColumns" />
                <span>{{ col }}</span>
              </label>
            </div>
          </div>

          <div class="control-row actions">
            <button class="btn-primary" :disabled="!canFetch || loading" @click="fetchData">
              <span v-if="loading">⏳ Loading…</span>
              <span v-else>Fetch Data</span>
            </button>
            <span v-if="error" class="error-msg">{{ error }}</span>
          </div>
        </section>

        <section v-if="result" class="results card">
          <div class="results-header">
            <h2>{{ result.farm }} / {{ result.turbine }} / {{ result.file_type }} / {{ result.date }}</h2>
            <span class="row-count">{{ result.row_count.toLocaleString() }} rows</span>
          </div>

          <div class="tab-bar">
            <button class="tab-btn" :class="{ active: activeTab === 'table' }" @click="activeTab = 'table'">📋 Data Table</button>
            <button class="tab-btn" :class="{ active: activeTab === 'charts' }" @click="activeTab = 'charts'">📈 Charts</button>
            <button class="tab-btn" :class="{ active: activeTab === 'report' }" @click="activeTab = 'report'">📊 Data Quality Report</button>
          </div>

          <div :class="['tab-panel', activeTab !== 'table' && 'tab-panel--hidden']">
            <div class="table-toolbar">
              <input class="global-filter" type="search" v-model="globalFilter" placeholder="🔍 Search all columns…" />
              <button class="btn-clear" @click="clearFilters" title="Clear all filters &amp; sort">✕ Clear filters</button>
              <label class="page-size-label">
                Rows/page
                <select v-model="tablePageSize" class="page-size-select">
                  <option :value="25">25</option><option :value="50">50</option>
                  <option :value="100">100</option><option :value="200">200</option>
                  <option :value="500">500</option>
                </select>
              </label>
              <div class="download-group">
                <select v-model="downloadFormat" class="download-format-select">
                  <option value="csv">CSV</option><option value="json">JSON</option>
                </select>
                <button class="btn-download" @click="downloadFile">⬇ Download</button>
              </div>
            </div>
            <div class="pagination-bar">
              <button class="page-btn" :disabled="tablePage === 0" @click="tablePage = 0">«</button>
              <button class="page-btn" :disabled="tablePage === 0" @click="tablePage--">‹</button>
              <span class="page-info">
                Rows&nbsp;<strong>{{ tablePageStart + 1 }}–{{ tablePageEnd }}</strong>
                &nbsp;of&nbsp;<strong>{{ filteredRows.length.toLocaleString() }}</strong>
                <template v-if="filteredRows.length !== result.row_count">&nbsp;({{ result.row_count.toLocaleString() }} total)</template>
                &nbsp;· page&nbsp;{{ tablePage + 1 }}&nbsp;/&nbsp;{{ tableTotalPages }}
              </span>
              <input class="page-jump" type="number" min="1" :max="tableTotalPages" :value="tablePage + 1" @change="jumpTablePage($event.target.value)" />
              <button class="page-btn" :disabled="tablePage >= tableTotalPages - 1" @click="tablePage++">›</button>
              <button class="page-btn" :disabled="tablePage >= tableTotalPages - 1" @click="tablePage = tableTotalPages - 1">»</button>
            </div>
            <div class="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th v-for="(col, ci) in result.columns" :key="col" class="sortable" @click="setSort(ci)">
                      <span class="th-label">{{ col }}</span>
                      <span class="sort-icon">
                        <template v-if="sortCol === ci">{{ sortDir === 1 ? '▲' : '▼' }}</template>
                        <template v-else>⇅</template>
                      </span>
                    </th>
                  </tr>
                  <tr class="filter-row">
                    <th v-for="(_col, ci) in result.columns" :key="'f' + ci">
                      <input class="col-filter" type="text" placeholder="filter…" v-model="colFilters[ci]" />
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

          <div v-if="activeTab === 'charts'" class="tab-panel">
            <ChartPanel :result="result" />
          </div>

          <div :class="['tab-panel', activeTab !== 'report' && 'tab-panel--hidden']">
            <div class="report">
              <div class="report-title">
                📊 Data Quality Report
                <span class="report-subtitle">{{ result.row_count }} rows · {{ result.columns.length }} columns · "good" = non-null &amp; non-zero</span>
              </div>
              <div class="report-grid">
                <div v-for="stat in columnStats" :key="stat.col" class="stat-card" :class="stat.goodRate < 50 ? 'stat-bad' : stat.goodRate < 90 ? 'stat-warn' : 'stat-ok'">
                  <div class="stat-col-name" :title="stat.col">{{ stat.col }}</div>
                  <div class="stat-bar-wrap"><div class="stat-bar" :style="{ width: stat.goodRate + '%' }"></div></div>
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
      </template>


      <!-- ══ PAGE: Query for Events ══ -->
      <template v-if="mainTab === 'events'">
        <section class="controls card">
          <div class="control-row">
            <div class="control-group">
              <label>Wind Farm</label>
              <select v-model="evFarm" @change="onEvFarmChange">
                <option value="" disabled>— select farm —</option>
                <option v-for="farm in farms" :key="farm.directory" :value="farm.directory">
                  {{ farm.name }} ({{ farm.turbine_count }} turbines)
                </option>
              </select>
            </div>
            <div class="control-group">
              <label>Turbine</label>
              <select v-model="evTurbine" :disabled="!evFarm" @change="onEvTurbineChange">
                <option value="" disabled>— select turbine —</option>
                <option v-for="t in evAvailableTurbines" :key="t" :value="t">{{ t }}</option>
              </select>
            </div>
            <div class="control-group">
              <label>Event Type (IEC Category)</label>
              <select v-model="evCategory" :disabled="!evTurbine || evLoadingTypes">
                <option value="" disabled>{{ evLoadingTypes ? '⏳ Loading…' : '— select category —' }}</option>
                <option v-for="et in evEventTypes" :key="et" :value="et">{{ et }}</option>
              </select>
            </div>
            <div class="control-group">
              <label>Max Events</label>
              <select v-model.number="evLimit">
                <option :value="100">100</option><option :value="250">250</option>
                <option :value="500">500</option><option :value="1000">1000</option>
              </select>
            </div>
          </div>
          <div class="control-row actions">
            <button class="btn-primary" :disabled="!evCanFetch || evLoading" @click="fetchEventsData">
              <span v-if="evLoading">⏳ Loading…</span>
              <span v-else>Load Events</span>
            </button>
            <span v-if="evError" class="error-msg">{{ evError }}</span>
          </div>
        </section>

        <section v-if="evEvents.length" class="results card">
          <div class="results-header">
            <h2>{{ evFarm }} / {{ evTurbine }} — {{ evCategory || 'All events' }}</h2>
            <span class="row-count">{{ evEvents.length.toLocaleString() }} events</span>
          </div>
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th v-for="col in evDisplayCols" :key="col">{{ col }}</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(ev, i) in evEvents" :key="i">
                  <td v-for="col in evDisplayCols" :key="col">{{ ev[col] ?? '—' }}</td>
                  <td>
                    <a class="ev-link" href="#" @click.prevent="goToDataForEvent(ev)" title="Open this period in Query for Data">→ View Data</a>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
        <section v-else-if="evFetched && !evLoading" class="results card">
          <p style="padding:20px; color:#888; text-align:center;">No events found for the selected criteria.</p>
        </section>
      </template>


      <!-- ══ PAGE: Custom Queries ══ -->
      <template v-if="mainTab === 'custom'">

        <div v-if="cqLoadError" class="card cq-load-error">
          ⚠️ Could not load <code>custom_queries.json</code>: {{ cqLoadError }}<br/>
          <small>Make sure the file exists at <code>frontend/public/custom_queries.json</code> and is valid JSON.</small>
        </div>

        <div v-else-if="customQueries.length === 0" class="card cq-load-error">
          No queries defined yet. Edit <code>frontend/public/custom_queries.json</code> to add some.
        </div>

        <div v-else class="cq-grid">
          <div
            v-for="q in customQueries"
            :key="q.id"
            class="cq-card"
            :class="{ 'cq-card--active': cqActiveId === q.id }"
          >
            <!-- Card header -->
            <div class="cq-card-header">
              <span :class="['cq-type-badge', q.type === 'data' ? 'cq-badge-data' : 'cq-badge-events']">
                {{ q.type === 'data' ? '📊 Data' : '📅 Events' }}
              </span>
              <span class="cq-farm-tag">{{ q.farm }} / {{ q.turbine }}</span>
            </div>

            <!-- Card body -->
            <div class="cq-card-body">
              <h3 class="cq-title">{{ q.name }}</h3>
              <p class="cq-desc">{{ q.description }}</p>

              <!-- Query detail chips -->
              <div class="cq-chips">
                <template v-if="q.type === 'data'">
                  <span class="chip">📅 {{ q.date }}</span>
                  <span v-if="q.file_type" class="chip">{{ q.file_type }}</span>
                  <span v-if="q.hour_from != null || q.hour_to != null" class="chip">
                    ⏰ {{ q.hour_from ?? 0 }}h – {{ q.hour_to ?? 23 }}h
                  </span>
                  <span v-if="q.columns && q.columns.length" class="chip">{{ q.columns.length }} columns</span>
                  <span v-else class="chip">all columns</span>
                </template>
                <template v-else>
                  <span v-if="q.iec_category" class="chip">{{ q.iec_category }}</span>
                  <span v-if="q.status" class="chip">Status: {{ q.status }}</span>
                  <span class="chip">limit {{ q.limit ?? 500 }}</span>
                </template>
              </div>
            </div>

            <!-- Run button -->
            <div class="cq-card-footer">
              <button
                class="btn-primary cq-run-btn"
                :disabled="cqLoadingId === q.id"
                @click="runCustomQuery(q)"
              >
                <span v-if="cqLoadingId === q.id">⏳ Running…</span>
                <span v-else>▶ Run Query</span>
              </button>
              <span v-if="cqErrors[q.id]" class="error-msg">{{ cqErrors[q.id] }}</span>
            </div>

            <!-- Inline results -->
            <div v-if="cqActiveId === q.id && cqResults[q.id]" class="cq-results">
              <template v-if="q.type === 'data'">
                <div class="cq-results-header">
                  <span class="row-count">{{ cqResults[q.id].row_count ?? cqResults[q.id].rows?.length ?? 0 }} rows</span>
                  <div class="download-group">
                    <select v-model="cqDownloadFmt[q.id]" class="download-format-select">
                      <option value="csv">CSV</option><option value="json">JSON</option>
                    </select>
                    <button class="btn-download" @click="downloadCqResult(q)">⬇ Download</button>
                  </div>
                </div>
                <div class="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th v-for="col in cqResults[q.id].columns" :key="col">{{ col }}</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="(row, i) in cqResults[q.id].rows.slice(0, 200)" :key="i">
                        <td v-for="(cell, j) in row" :key="j">{{ cell ?? '—' }}</td>
                      </tr>
                      <tr v-if="cqResults[q.id].rows.length > 200">
                        <td :colspan="cqResults[q.id].columns.length" class="no-rows">
                          … {{ cqResults[q.id].rows.length - 200 }} more rows (download to see all)
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </template>

              <template v-else>
                <div class="cq-results-header">
                  <span class="row-count">{{ cqResults[q.id].count }} events</span>
                  <div class="download-group">
                    <select v-model="cqDownloadFmt[q.id]" class="download-format-select">
                      <option value="csv">CSV</option><option value="json">JSON</option>
                    </select>
                    <button class="btn-download" @click="downloadCqResult(q)">⬇ Download</button>
                  </div>
                </div>
                <div class="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th v-for="col in cqEvDisplayCols(q.id)" :key="col">{{ col }}</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="(ev, i) in cqResults[q.id].events" :key="i">
                        <td v-for="col in cqEvDisplayCols(q.id)" :key="col">{{ ev[col] ?? '—' }}</td>
                        <td>
                          <a class="ev-link" href="#" @click.prevent="goToDataFromCq(ev, q)">→ View Data</a>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </template>
            </div>
          </div>
        </div>
      </template>

    </main>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { fetchWindFarms, fetchColumns, fetchDayData, fetchTimeRanges, fetchEventTypes, fetchEvents } from './api.js'
import ChartPanel from './ChartPanel.vue'

// ── Top-level tab ──────────────────────────────────────────────────────────
const mainTab = ref('query')

// ── Query for Data state ───────────────────────────────────────────────────
const farms        = ref([])
const columnsMap   = ref([])
const timeRanges   = ref([])

const selectedFarm     = ref('')
const selectedTurbine  = ref('')
const selectedFileType = ref('')
const selectedDate     = ref('')
const selectedColumns  = ref([])
const allColumns       = ref(true)
const hourFrom         = ref(null)
const hourTo           = ref(null)
const loading          = ref(false)
const error            = ref('')
const result           = ref(null)
const activeTab        = ref('table')

const globalFilter   = ref('')
const colFilters     = ref([])
const sortCol        = ref(null)
const sortDir        = ref(1)
const downloadFormat = ref('csv')
const tablePage      = ref(0)
const tablePageSize  = ref(50)

// ── Computed (Query for Data) ──────────────────────────────────────────────
const availableTurbines = computed(() => {
  if (!selectedFarm.value) return []
  const farm = farms.value.find(f => f.directory === selectedFarm.value)
  return farm?.turbines ?? []
})
const availableFileTypes = computed(() => {
  if (!selectedFarm.value) return []
  const entry = columnsMap.value.find(e => e.farm === selectedFarm.value)
  return entry ? Object.keys(entry.columns_by_type) : []
})
const availableColumns = computed(() => {
  if (!selectedFarm.value || !selectedFileType.value) return []
  const entry = columnsMap.value.find(e => e.farm === selectedFarm.value)
  return entry?.columns_by_type[selectedFileType.value] ?? []
})
const minDate = computed(() => {
  const tr = timeRanges.value.find(t => t.farm === selectedFarm.value)
  return tr?.earliest?.slice(0, 10) ?? ''
})
const maxDate = computed(() => {
  const tr = timeRanges.value.find(t => t.farm === selectedFarm.value)
  return tr?.latest?.slice(0, 10) ?? ''
})
const canFetch = computed(() => !!(selectedFarm.value && selectedTurbine.value && selectedFileType.value && selectedDate.value))

const filteredRows = computed(() => {
  if (!result.value) return []
  if (activeTab.value !== 'table') return result.value.rows
  const global = globalFilter.value.trim().toLowerCase()
  const perCol = colFilters.value.map(f => (f ?? '').trim().toLowerCase())
  let rows = result.value.rows
  if (global) rows = rows.filter(row => row.some(cell => String(cell ?? '').toLowerCase().includes(global)))
  perCol.forEach((f, ci) => { if (f) rows = rows.filter(row => String(row[ci] ?? '').toLowerCase().includes(f)) })
  if (sortCol.value !== null) {
    const ci = sortCol.value, dir = sortDir.value
    rows = [...rows].sort((a, b) => {
      const av = a[ci] ?? '', bv = b[ci] ?? ''
      const an = parseFloat(av), bn = parseFloat(bv)
      if (!isNaN(an) && !isNaN(bn)) return (an - bn) * dir
      return String(av).localeCompare(String(bv)) * dir
    })
  }
  return rows
})
const tableTotalPages = computed(() => Math.max(1, Math.ceil(filteredRows.value.length / tablePageSize.value)))
const tablePageStart  = computed(() => tablePage.value * tablePageSize.value)
const tablePageEnd    = computed(() => Math.min(tablePageStart.value + tablePageSize.value, filteredRows.value.length))
const pagedRows       = computed(() => filteredRows.value.slice(tablePageStart.value, tablePageEnd.value))

const columnStats = computed(() => {
  if (!result.value) return []
  const { columns, rows } = result.value
  const total = rows.length
  if (total === 0) return []
  return columns.map((col, ci) => {
    let nullCount = 0, zeroCount = 0
    for (const row of rows) {
      const v = row[ci]
      if (v === null || v === undefined || v === '') nullCount++
      else if (v === 0 || v === '0' || v === 0.0) zeroCount++
    }
    const goodCount = total - nullCount - zeroCount
    const goodRate  = Math.round((goodCount / total) * 100)
    return { col, nullCount, zeroCount, goodCount, goodRate, total }
  })
})

function jumpTablePage(val) {
  const n = parseInt(val, 10)
  if (!isNaN(n)) tablePage.value = Math.max(0, Math.min(tableTotalPages.value - 1, n - 1))
}

// ── Handlers (Query for Data) ──────────────────────────────────────────────
function onFarmChange() {
  selectedTurbine.value  = ''
  selectedFileType.value = ''
  selectedColumns.value  = []
  result.value           = null
  error.value            = ''
  const farm = farms.value.find(f => f.directory === selectedFarm.value)
  selectedTurbine.value = farm?.turbines?.[0] ?? ''
  const tr = timeRanges.value.find(t => t.farm === selectedFarm.value)
  selectedDate.value = tr?.earliest ? tr.earliest.slice(0, 10) : ''
}
function onFileTypeChange() { selectedColumns.value = []; allColumns.value = true; result.value = null; error.value = '' }
function onAllColumnsToggle() { if (allColumns.value) selectedColumns.value = [] }
function setSort(ci) {
  if (sortCol.value !== ci) { sortCol.value = ci; sortDir.value = 1 }
  else if (sortDir.value === 1) sortDir.value = -1
  else { sortCol.value = null; sortDir.value = 1 }
}
function clearFilters() {
  globalFilter.value = ''; colFilters.value = result.value ? Array(result.value.columns.length).fill('') : []
  sortCol.value = null; sortDir.value = 1; tablePage.value = 0
}
function downloadFile() {
  if (!result.value || filteredRows.value.length === 0) return
  const { farm, file_type, date, columns } = result.value
  const rows = filteredRows.value
  const baseName = `${farm}_${file_type}_${date}`
  let content, mimeType, fileName
  if (downloadFormat.value === 'json') {
    const objects = rows.map(row => Object.fromEntries(columns.map((col, i) => [col, row[i] ?? null])))
    content = JSON.stringify(objects, null, 2); mimeType = 'application/json;charset=utf-8;'; fileName = `${baseName}.json`
  } else {
    const escape = val => { const s = String(val ?? ''); return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g, '""')}"` : s }
    content = `${columns.map(escape).join(',')}\n${rows.map(row => row.map(escape).join(',')).join('\n')}`
    mimeType = 'text/csv;charset=utf-8;'; fileName = `${baseName}.csv`
  }
  const blob = new Blob([content], { type: mimeType }), url = URL.createObjectURL(blob), a = document.createElement('a')
  a.href = url; a.download = fileName; a.click(); URL.revokeObjectURL(url)
}
async function fetchData() {
  if (!canFetch.value) return
  loading.value = true; error.value = ''; result.value = null
  try {
    const cols = allColumns.value ? [] : selectedColumns.value
    result.value = await fetchDayData(
      selectedFarm.value, selectedDate.value, selectedFileType.value, selectedTurbine.value, cols,
      hourFrom.value !== null && hourFrom.value !== '' ? hourFrom.value : null,
      hourTo.value   !== null && hourTo.value   !== '' ? hourTo.value   : null,
    )
    globalFilter.value = ''; colFilters.value = Array(result.value.columns.length).fill('')
    sortCol.value = null; sortDir.value = 1; tablePage.value = 0; activeTab.value = 'table'
  } catch (e) { error.value = e.message }
  finally { loading.value = false }
}

watch([globalFilter, colFilters, sortCol, sortDir, tablePageSize], () => { tablePage.value = 0 })

// ── Events tab state ───────────────────────────────────────────────────────
const evFarm         = ref('')
const evTurbine      = ref('')
const evCategory     = ref('')
const evLimit        = ref(500)
const evEventTypes   = ref([])
const evLoadingTypes = ref(false)
const evLoading      = ref(false)
const evError        = ref('')
const evEvents       = ref([])
const evColumns      = ref([])
const evFetched      = ref(false)

const evAvailableTurbines = computed(() => {
  if (!evFarm.value) return []
  const farm = farms.value.find(f => f.directory === evFarm.value)
  return farm?.turbines ?? []
})
const evDisplayCols = computed(() => {
  const preferred = ['Timestamp start', 'Timestamp end', 'Duration', 'IEC category', 'Status', 'Code', 'Message']
  return preferred.filter(c => evColumns.value.includes(c))
})
const evCanFetch = computed(() => !!(evFarm.value && evTurbine.value && evCategory.value))

async function onEvFarmChange() {
  evTurbine.value = ''; evCategory.value = ''; evEventTypes.value = []; evEvents.value = []; evFetched.value = false; evError.value = ''
  const farm = farms.value.find(f => f.directory === evFarm.value)
  evTurbine.value = farm?.turbines?.[0] ?? ''
  if (evTurbine.value) await loadEventTypes()
}
async function onEvTurbineChange() {
  evCategory.value = ''; evEventTypes.value = []; evEvents.value = []; evFetched.value = false; evError.value = ''
  if (evTurbine.value) await loadEventTypes()
}
async function loadEventTypes() {
  evLoadingTypes.value = true; evError.value = ''
  try {
    evEventTypes.value = await fetchEventTypes(evFarm.value, evTurbine.value)
    if (evEventTypes.value.length) evCategory.value = evEventTypes.value[0]
  } catch (e) { evError.value = `Could not load event types: ${e.message}` }
  finally { evLoadingTypes.value = false }
}
async function fetchEventsData() {
  if (!evCanFetch.value) return
  evLoading.value = true; evError.value = ''; evEvents.value = []; evFetched.value = false
  try {
    const data = await fetchEvents(evFarm.value, evTurbine.value, evCategory.value, null, evLimit.value)
    evEvents.value = data.events; evColumns.value = data.columns; evFetched.value = true
  } catch (e) { evError.value = e.message }
  finally { evLoading.value = false }
}

async function goToDataForEvent(ev) {
  const tsStart = ev['Timestamp start']
  const tsEnd   = ev['Timestamp end']
  if (!tsStart) return
  const startDate = tsStart.slice(0, 10)
  const startHour = parseInt(tsStart.slice(11, 13), 10)
  const endHour   = tsEnd ? Math.min(23, parseInt(tsEnd.slice(11, 13), 10)) : startHour

  selectedFarm.value = evFarm.value
  onFarmChange()
  selectedTurbine.value  = evTurbine.value
  selectedFileType.value = 'data'
  selectedDate.value     = startDate
  hourFrom.value         = startHour
  hourTo.value           = endHour
  allColumns.value       = true
  selectedColumns.value  = []
  mainTab.value = 'query'
  await new Promise(r => setTimeout(r, 50))
  await fetchData()
}

// ── Custom Queries tab state ───────────────────────────────────────────────
const customQueries  = ref([])
const cqLoadError    = ref('')
const cqLoadingId    = ref(null)   // id of the query currently running
const cqActiveId     = ref(null)   // id of the query whose results are shown
const cqResults      = ref({})     // id → API response
const cqErrors       = ref({})     // id → error string
const cqDownloadFmt  = ref({})     // id → 'csv' | 'json'

async function loadCustomQueries() {
  try {
    const res = await fetch('/custom_queries.json')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    customQueries.value = data
    // seed download format defaults
    for (const q of data) cqDownloadFmt.value[q.id] = 'csv'
  } catch (e) {
    cqLoadError.value = e.message
  }
}

async function runCustomQuery(q) {
  cqLoadingId.value = q.id
  cqErrors.value[q.id] = ''
  try {
    let result
    if (q.type === 'data') {
      result = await fetchDayData(
        q.farm, q.date, q.file_type ?? 'data', q.turbine,
        q.columns ?? [], q.hour_from ?? null, q.hour_to ?? null
      )
    } else {
      result = await fetchEvents(
        q.farm, q.turbine,
        q.iec_category ?? null,
        q.status ?? null,
        q.limit ?? 500
      )
    }
    cqResults.value[q.id] = result
    cqActiveId.value = q.id
  } catch (e) {
    cqErrors.value[q.id] = e.message
  } finally {
    cqLoadingId.value = null
  }
}

function cqEvDisplayCols(id) {
  const r = cqResults.value[id]
  if (!r) return []
  const preferred = ['Timestamp start', 'Timestamp end', 'Duration', 'IEC category', 'Status', 'Code', 'Message']
  return preferred.filter(c => (r.columns ?? []).includes(c))
}

function downloadCqResult(q) {
  const r = cqResults.value[q.id]
  if (!r) return
  const fmt = cqDownloadFmt.value[q.id] ?? 'csv'
  const baseName = q.id
  let content, mimeType, fileName

  if (q.type === 'data') {
    const { columns, rows } = r
    if (fmt === 'json') {
      const objects = rows.map(row => Object.fromEntries(columns.map((c, i) => [c, row[i] ?? null])))
      content = JSON.stringify(objects, null, 2); mimeType = 'application/json;charset=utf-8;'; fileName = `${baseName}.json`
    } else {
      const esc = v => { const s = String(v ?? ''); return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g, '""')}"` : s }
      content = `${columns.map(esc).join(',')}\n${rows.map(row => row.map(esc).join(',')).join('\n')}`
      mimeType = 'text/csv;charset=utf-8;'; fileName = `${baseName}.csv`
    }
  } else {
    const { columns, events } = r
    if (fmt === 'json') {
      content = JSON.stringify(events, null, 2); mimeType = 'application/json;charset=utf-8;'; fileName = `${baseName}.json`
    } else {
      const esc = v => { const s = String(v ?? ''); return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g, '""')}"` : s }
      content = `${columns.map(esc).join(',')}\n${events.map(ev => columns.map(c => esc(ev[c])).join(',')).join('\n')}`
      mimeType = 'text/csv;charset=utf-8;'; fileName = `${baseName}.csv`
    }
  }
  const blob = new Blob([content], { type: mimeType }), url = URL.createObjectURL(blob), a = document.createElement('a')
  a.href = url; a.download = fileName; a.click(); URL.revokeObjectURL(url)
}

async function goToDataFromCq(ev, q) {
  const tsStart = ev['Timestamp start']
  const tsEnd   = ev['Timestamp end']
  if (!tsStart) return
  selectedFarm.value = q.farm; onFarmChange()
  selectedTurbine.value  = q.turbine
  selectedFileType.value = 'data'
  selectedDate.value     = tsStart.slice(0, 10)
  hourFrom.value         = parseInt(tsStart.slice(11, 13), 10)
  hourTo.value           = tsEnd ? Math.min(23, parseInt(tsEnd.slice(11, 13), 10)) : hourFrom.value
  allColumns.value       = true; selectedColumns.value = []
  mainTab.value = 'query'
  await new Promise(r => setTimeout(r, 50))
  await fetchData()
}

// ── Initialisation ─────────────────────────────────────────────────────────
onMounted(async () => {
  try {
    const [farmsData, colsData, rangesData] = await Promise.all([fetchWindFarms(), fetchColumns(), fetchTimeRanges()])
    farms.value = farmsData; columnsMap.value = colsData; timeRanges.value = rangesData
  } catch (e) { error.value = `Could not load farm metadata: ${e.message}` }
  await loadCustomQueries()
})
</script>

<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; font-size: 14px; background: #f0f2f5; color: #1a1a2e; }
.app { display: flex; flex-direction: column; min-height: 100vh; }

.app-header { background: #1a1a2e; color: #fff; padding: 12px 24px 0; }
.app-header h1 { font-size: 20px; font-weight: 600; margin-bottom: 10px; }

/* ── Main page tabs ── */
.main-tab-bar { display: flex; gap: 4px; }
.main-tab-btn {
  padding: 8px 22px; background: rgba(255,255,255,.10); border: 1px solid rgba(255,255,255,.20);
  border-bottom: none; border-radius: 6px 6px 0 0; color: rgba(255,255,255,.70);
  font-size: 13px; font-weight: 600; cursor: pointer; transition: background .15s, color .15s;
}
.main-tab-btn:hover { background: rgba(255,255,255,.2); color: #fff; }
.main-tab-btn.active { background: #f0f2f5; border-color: rgba(255,255,255,.20); color: #1a1a2e; }

.app-body { flex: 1; padding: 24px; display: flex; flex-direction: column; gap: 20px; max-width: 1600px; width: 100%; margin: 0 auto; }
.card { background: #fff; border-radius: 10px; padding: 20px 24px; box-shadow: 0 2px 8px rgba(0,0,0,.08); }
.controls { display: flex; flex-direction: column; gap: 18px; }
.control-row { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-end; }
.control-group { display: flex; flex-direction: column; gap: 6px; min-width: 180px; }
.hour-input { max-width: 90px; }
.control-group label { font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: #555; }

select, input[type="date"] { padding: 8px 10px; border: 1px solid #d0d5dd; border-radius: 6px; font-size: 14px; background: #fff; color: #1a1a2e; cursor: pointer; }
select:focus, input[type="date"]:focus { outline: 2px solid #4361ee; border-color: transparent; }
input[type="date"]:disabled { background: #f0f2f5; color: #aaa; cursor: not-allowed; }
.date-hint { font-size: 11px; color: #888; margin-top: 2px; }

.column-picker { max-width: 100%; }
.column-toggle-row { margin-bottom: 10px; }
.column-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 6px 12px; max-height: 240px; overflow-y: auto; border: 1px solid #e4e7ec; border-radius: 6px; padding: 10px; background: #fafafa; }
.checkbox-label { display: flex; align-items: center; gap: 7px; font-size: 13px; cursor: pointer; user-select: none; padding: 3px 0; }
.checkbox-label.all-cols { font-weight: 600; }
.checkbox-label input { accent-color: #4361ee; width: 15px; height: 15px; cursor: pointer; }

.actions { align-items: center; }
.btn-primary { padding: 10px 28px; background: #4361ee; color: #fff; border: none; border-radius: 7px; font-size: 14px; font-weight: 600; cursor: pointer; transition: background .15s; }
.btn-primary:hover:not(:disabled) { background: #3451d1; }
.btn-primary:disabled { opacity: .5; cursor: not-allowed; }
.error-msg { color: #e53e3e; font-size: 13px; font-weight: 500; }

.report { border: 1px solid #e4e7ec; border-radius: 8px; padding: 14px 16px; background: #fafbfc; }
.report-title { font-weight: 700; font-size: 13px; margin-bottom: 12px; display: flex; align-items: center; gap: 10px; }
.report-subtitle { font-weight: 400; font-size: 12px; color: #888; }
.report-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 8px; }
.stat-card { background: #fff; border: 1px solid #e4e7ec; border-radius: 7px; padding: 8px 10px; display: flex; flex-direction: column; gap: 5px; }
.stat-card.stat-ok   { border-left: 3px solid #38a169; }
.stat-card.stat-warn { border-left: 3px solid #d69e2e; }
.stat-card.stat-bad  { border-left: 3px solid #e53e3e; }
.stat-col-name { font-size: 11px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #333; }
.stat-bar-wrap { height: 5px; background: #e4e7ec; border-radius: 3px; overflow: hidden; }
.stat-bar { height: 100%; border-radius: 3px; background: #4361ee; transition: width .3s; }
.stat-ok .stat-bar { background: #38a169; } .stat-warn .stat-bar { background: #d69e2e; } .stat-bad .stat-bar { background: #e53e3e; }
.stat-numbers { display: flex; gap: 6px; flex-wrap: wrap; font-size: 10px; }
.stat-fill { color: #555; font-weight: 600; } .stat-null { color: #e53e3e; } .stat-zero { color: #d69e2e; }

.tab-bar { display: flex; gap: 0; border-bottom: 2px solid #e4e7ec; margin-bottom: 16px; }
.tab-btn { padding: 10px 22px; background: none; border: none; border-bottom: 3px solid transparent; margin-bottom: -2px; font-size: 14px; font-weight: 600; color: #888; cursor: pointer; transition: color .15s, border-color .15s; white-space: nowrap; }
.tab-btn:hover { color: #4361ee; }
.tab-btn.active { color: #4361ee; border-bottom-color: #4361ee; }
.tab-panel { contain: layout style; will-change: contents; }
.tab-panel--hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; pointer-events: none; }

.results { display: flex; flex-direction: column; gap: 14px; }
.results-header { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.results-header h2 { font-size: 15px; font-weight: 600; }
.row-count { font-size: 12px; color: #888; background: #f0f2f5; padding: 3px 9px; border-radius: 20px; white-space: nowrap; }

.global-filter { padding: 7px 10px; border: 1px solid #d0d5dd; border-radius: 6px; font-size: 13px; min-width: 220px; flex: 1; max-width: 360px; }
.global-filter:focus { outline: 2px solid #4361ee; border-color: transparent; }
.btn-clear { padding: 7px 14px; border: 1px solid #d0d5dd; border-radius: 6px; background: #fff; font-size: 13px; cursor: pointer; color: #555; white-space: nowrap; }
.btn-clear:hover { background: #f0f2f5; }
.download-group { display: flex; align-items: center; gap: 0; }
.download-format-select { padding: 7px 8px; border: 1px solid #4361ee; border-right: none; border-radius: 6px 0 0 6px; font-size: 13px; background: #fff; color: #4361ee; font-weight: 600; cursor: pointer; height: 34px; }
.download-format-select:focus { outline: none; }
.btn-download { padding: 7px 14px; border: 1px solid #4361ee; border-radius: 0 6px 6px 0; background: #4361ee; color: #fff; font-size: 13px; font-weight: 600; cursor: pointer; white-space: nowrap; transition: background .15s; height: 34px; }
.btn-download:hover { background: #3451d1; }

.table-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.page-size-label { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: #555; white-space: nowrap; }
.page-size-select { padding: 6px 8px; border: 1px solid #d0d5dd; border-radius: 6px; font-size: 13px; background: #fff; cursor: pointer; }

.pagination-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px 12px; background: #fafbfc; border: 1px solid #e4e7ec; border-radius: 8px; font-size: 13px; margin-bottom: 10px; }
.page-btn { min-width: 32px; height: 32px; padding: 0 8px; border: 1px solid #d0d5dd; border-radius: 6px; background: #fff; font-size: 15px; cursor: pointer; color: #4361ee; font-weight: 700; transition: background .12s; line-height: 1; }
.page-btn:hover:not(:disabled) { background: #eef1fd; }
.page-btn:disabled { color: #ccc; cursor: not-allowed; }
.page-info { color: #555; white-space: nowrap; }
.page-jump { width: 58px; padding: 5px 8px; border: 1px solid #d0d5dd; border-radius: 6px; font-size: 13px; text-align: center; }
.page-jump:focus { outline: 2px solid #4361ee; border-color: transparent; }
.page-jump::-webkit-inner-spin-button, .page-jump::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }
.page-jump { -moz-appearance: textfield; }

.table-scroll { overflow: auto; max-height: 520px; border: 1px solid #e4e7ec; border-radius: 7px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
thead { position: sticky; top: 0; z-index: 2; }
thead tr:first-child th { background: #1a1a2e; color: #fff; padding: 10px 12px; text-align: left; white-space: nowrap; border-right: 1px solid #2d2d4e; user-select: none; }
thead tr:first-child th:last-child { border-right: none; }
th.sortable { cursor: pointer; } th.sortable:hover { background: #2d2d4e; }
.th-label { margin-right: 4px; } .sort-icon { font-size: 11px; opacity: .75; }
thead tr.filter-row th { background: #f0f2f5; padding: 4px 6px; border-right: 1px solid #e4e7ec; border-bottom: 2px solid #d0d5dd; }
thead tr.filter-row th:last-child { border-right: none; }
.col-filter { width: 100%; padding: 4px 6px; border: 1px solid #d0d5dd; border-radius: 4px; font-size: 12px; background: #fff; }
.col-filter:focus { outline: 2px solid #4361ee; border-color: transparent; }
tbody tr:nth-child(even) { background: #f7f8fc; } tbody tr:hover { background: #eef1fd; }
td { padding: 7px 12px; border-bottom: 1px solid #e4e7ec; border-right: 1px solid #e4e7ec; white-space: nowrap; }
td:last-child { border-right: none; }
.no-rows { text-align: center; color: #888; padding: 24px; font-style: italic; }

/* ── Event action link ── */
.ev-link { color: #4361ee; font-weight: 600; font-size: 12px; text-decoration: none; white-space: nowrap; padding: 3px 8px; border: 1px solid #4361ee; border-radius: 4px; transition: background .12s; }
.ev-link:hover { background: #eef1fd; }

/* ── Custom Queries tab ── */
.cq-load-error { color: #c53030; background: #fff5f5; border: 1px solid #feb2b2; border-radius: 8px; padding: 16px 20px; font-size: 13px; line-height: 1.6; }
.cq-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 18px; align-items: start; }
.cq-card {
  background: #fff; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,.08);
  display: flex; flex-direction: column; overflow: hidden;
  border: 2px solid transparent; transition: border-color .15s, box-shadow .15s;
}
.cq-card:hover { box-shadow: 0 4px 16px rgba(67,97,238,.12); }
.cq-card--active { border-color: #4361ee; }
.cq-card-header { display: flex; align-items: center; gap: 8px; padding: 10px 16px 0; }
.cq-type-badge { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 20px; }
.cq-badge-data   { background: #e0e7ff; color: #3730a3; }
.cq-badge-events { background: #dcfce7; color: #166534; }
.cq-farm-tag { font-size: 11px; color: #888; font-family: monospace; margin-left: auto; }
.cq-card-body { padding: 10px 16px 14px; flex: 1; }
.cq-title { font-size: 14px; font-weight: 700; color: #1a1a2e; margin-bottom: 5px; }
.cq-desc  { font-size: 12px; color: #666; line-height: 1.5; margin-bottom: 10px; }
.cq-chips { display: flex; flex-wrap: wrap; gap: 5px; }
.chip { font-size: 11px; background: #f0f2f5; border: 1px solid #e4e7ec; border-radius: 4px; padding: 2px 7px; color: #444; white-space: nowrap; }
.cq-card-footer { padding: 10px 16px 14px; border-top: 1px solid #f0f2f5; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.cq-run-btn { padding: 8px 20px; font-size: 13px; }
.cq-results { border-top: 2px solid #4361ee; padding: 14px 16px; background: #fafbff; }
.cq-results-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }

</style>

