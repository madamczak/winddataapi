<template>
  <!--
    ChartPanel.vue — Charts tab for the Wind Farm Data Explorer.
    Renders one line chart per selected numeric column, all sharing
    the same time axis (first column detected as timestamp).
    Uses Chart.js via vue-chartjs.
  -->
  <div class="chart-panel">

    <!-- ── Controls row ─────────────────────────────────────────────── -->
    <div class="chart-controls">
      <!-- Column selector: only numeric columns are listed -->
      <div class="chart-control-group">
        <label class="chart-label">Columns to plot</label>
        <div class="chart-col-list">
          <label
            v-for="col in numericColumns"
            :key="col"
            class="chart-checkbox"
          >
            <input
              type="checkbox"
              :value="col"
              v-model="selectedCols"
            />
            {{ col }}
          </label>
          <span v-if="numericColumns.length === 0" class="chart-empty">
            No numeric columns in this dataset.
          </span>
        </div>
      </div>

      <!-- Chart type -->
      <div class="chart-control-group">
        <label class="chart-label">Chart type</label>
        <div class="chart-type-btns">
          <button
            v-for="t in chartTypes"
            :key="t.value"
            class="chart-type-btn"
            :class="{ active: chartType === t.value }"
            @click="chartType = t.value"
          >{{ t.label }}</button>
        </div>
      </div>

      <!-- Page size -->
      <div class="chart-control-group">
        <label class="chart-label">Rows per page</label>
        <select v-model="pageSize" class="chart-select" @change="currentPage = 0">
          <option :value="25">25</option>
          <option :value="50">50</option>
          <option :value="100">100</option>
          <option :value="200">200</option>
          <option :value="500">500</option>
        </select>
      </div>
    </div>

    <!-- ── Pagination bar ────────────────────────────────────────────── -->
    <div class="pagination-bar">
      <button class="page-btn" :disabled="currentPage === 0" @click="currentPage = 0" title="First page">«</button>
      <button class="page-btn" :disabled="currentPage === 0" @click="currentPage--" title="Previous page">‹</button>

      <span class="page-info">
        Rows&nbsp;
        <strong>{{ pageStart + 1 }}–{{ pageEnd }}</strong>
        &nbsp;of&nbsp;
        <strong>{{ totalRows }}</strong>
        &nbsp;(page&nbsp;{{ currentPage + 1 }}&nbsp;/&nbsp;{{ totalPages }})
      </span>

      <!-- Jump-to-page input -->
      <input
        class="page-jump"
        type="number"
        min="1"
        :max="totalPages"
        :value="currentPage + 1"
        @change="jumpToPage($event.target.value)"
        title="Jump to page"
      />

      <button class="page-btn" :disabled="currentPage >= totalPages - 1" @click="currentPage++" title="Next page">›</button>
      <button class="page-btn" :disabled="currentPage >= totalPages - 1" @click="currentPage = totalPages - 1" title="Last page">»</button>
    </div>

    <!-- ── No columns selected hint ─────────────────────────────────── -->
    <div v-if="selectedCols.length === 0" class="chart-hint">
      ☝️ Select at least one column above to display a chart.
    </div>

    <!-- ── One chart per selected column ────────────────────────────── -->
    <div v-else class="charts-grid">
      <div
        v-for="col in selectedCols"
        :key="col"
        class="chart-card"
      >
        <div class="chart-card-title">{{ col }}</div>
        <div class="chart-wrap">
          <component
            :is="chartComponent"
            :data="chartDataMap[col]"
            :options="chartOptionsMap[col]"
          />
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
/**
 * ChartPanel — receives the raw API result object and renders Chart.js charts.
 * Props:
 *   result  — { columns: string[], rows: any[][], row_count: number, ... }
 *
 * When the result contains a "Turbine" column (multi-turbine query), each chart
 * renders one dataset per turbine so all turbines are visible on the same axes.
 */
import { ref, computed, watch } from 'vue'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js'
import { Line, Bar } from 'vue-chartjs'

ChartJS.register(
  CategoryScale, LinearScale, PointElement, LineElement,
  BarElement, Title, Tooltip, Legend, Filler,
)

// ── Props ──────────────────────────────────────────────────────────────────
const props = defineProps({
  result: { type: Object, required: true },
})

// ── Local state ────────────────────────────────────────────────────────────
const selectedCols = ref([])
const chartType    = ref('line')
const pageSize     = ref(50)
const currentPage  = ref(0)

const chartTypes = [
  { value: 'line', label: '📈 Line' },
  { value: 'bar',  label: '📊 Bar'  },
]

// ── Multi-turbine detection ────────────────────────────────────────────────
const isMultiTurbine = computed(() => props.result.columns.includes('Turbine'))
const turbineColIdx  = computed(() => props.result.columns.indexOf('Turbine'))

/** Distinct turbine names present in the full result */
const allTurbines = computed(() => {
  if (!isMultiTurbine.value) return []
  const tIdx = turbineColIdx.value
  return [...new Set(props.result.rows.map(r => r[tIdx]))]
})

// ── Timestamp column ───────────────────────────────────────────────────────
const timeColIdx = computed(() => {
  const cols = props.result.columns
  const idx = cols.findIndex(c => /time|date|timestamp/i.test(c))
  return idx >= 0 ? idx : 0
})

/** Format a raw timestamp cell → short HH:MM label */
function formatTsLabel(raw) {
  if (!raw) return ''
  const s = String(raw)
  const m = s.match(/(\d{2}:\d{2}(:\d{2})?)/)
  return m ? m[1] : s.slice(0, 16)
}

// ── Pagination ─────────────────────────────────────────────────────────────
/**
 * For single-turbine: totalRows = raw row count.
 * For multi-turbine:  totalRows = unique timestamp count (pageSize = timestamps/page).
 */
const allUniqueTs = computed(() => {
  if (!isMultiTurbine.value) return null
  const tIdx = timeColIdx.value
  const seen = new Set()
  const arr  = []
  for (const row of props.result.rows) {
    const v = row[tIdx]
    if (!seen.has(v)) { seen.add(v); arr.push(v) }
  }
  return arr
})

const totalRows  = computed(() => isMultiTurbine.value ? (allUniqueTs.value?.length ?? 0) : props.result.rows.length)
const totalPages = computed(() => Math.max(1, Math.ceil(totalRows.value / pageSize.value)))
const pageStart  = computed(() => currentPage.value * pageSize.value)
const pageEnd    = computed(() => Math.min(pageStart.value + pageSize.value, totalRows.value))

/**
 * Current page's rows.
 * Single-turbine: simple slice.
 * Multi-turbine:  rows whose timestamp falls in the current page's timestamp window.
 */
const pageRows = computed(() => {
  if (!isMultiTurbine.value) {
    return props.result.rows.slice(pageStart.value, pageEnd.value)
  }
  const pageTs = new Set(allUniqueTs.value.slice(pageStart.value, pageEnd.value))
  const tIdx   = timeColIdx.value
  return props.result.rows.filter(r => pageTs.has(r[tIdx]))
})

function jumpToPage(val) {
  const n = parseInt(val, 10)
  if (!isNaN(n)) currentPage.value = Math.max(0, Math.min(totalPages.value - 1, n - 1))
}

watch(() => props.result, () => { currentPage.value = 0 })

// ── X-axis labels ──────────────────────────────────────────────────────────
/** Single-turbine: one label per row. Multi-turbine: unique timestamps only. */
const labels = computed(() => {
  const tIdx = timeColIdx.value
  if (!isMultiTurbine.value) {
    return pageRows.value.map(row => formatTsLabel(row[tIdx]))
  }
  const seen = new Set()
  const arr  = []
  for (const row of pageRows.value) {
    const lbl = formatTsLabel(row[tIdx])
    if (!seen.has(lbl)) { seen.add(lbl); arr.push(lbl) }
  }
  return arr
})

// ── Numeric columns ────────────────────────────────────────────────────────
const numericColumns = computed(() => {
  const { columns, rows } = props.result
  const tIdx     = timeColIdx.value
  const turbIdx  = turbineColIdx.value
  return columns.filter((col, ci) => {
    if (ci === tIdx || ci === turbIdx) return false
    const sample = rows.slice(0, 50)
    return sample.some(row => {
      const v = row[ci]
      return v !== null && v !== undefined && v !== '' && isFinite(Number(v))
    })
  })
})

// ── Chart component ────────────────────────────────────────────────────────
const chartComponent = computed(() => chartType.value === 'bar' ? Bar : Line)

// ── Palette ────────────────────────────────────────────────────────────────
const PALETTE = [
  '#4361ee', '#e63946', '#2ec4b6', '#f4a261', '#8338ec',
  '#06d6a0', '#ef476f', '#ffd166', '#118ab2', '#073b4c',
]

// ── Chart builders ─────────────────────────────────────────────────────────
function parseVal(v) {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return isFinite(n) ? n : null
}

function buildChartData(col) {
  const cols = props.result.columns
  const ci   = cols.indexOf(col)

  if (!isMultiTurbine.value) {
    // ── Single turbine – original behaviour ───────────────────────────────
    const colour = PALETTE[selectedCols.value.indexOf(col) % PALETTE.length]
    const data   = pageRows.value.map(row => parseVal(row[ci]))
    return {
      labels: labels.value,
      datasets: [{
        label: col,
        data,
        borderColor:     colour,
        backgroundColor: chartType.value === 'bar' ? colour + '99' : colour + '22',
        borderWidth:     chartType.value === 'bar' ? 1 : 1.5,
        pointRadius:     chartType.value === 'line' && data.length < 300 ? 2 : 0,
        fill:            chartType.value === 'line',
        tension:         0.3,
        spanGaps:        true,
      }],
    }
  }

  // ── Multi-turbine: one dataset per turbine ────────────────────────────
  const tColIdx  = turbineColIdx.value
  const tsIdx    = timeColIdx.value
  const lbArr    = labels.value   // unique timestamp labels on this page
  const turbines = allTurbines.value

  const datasets = turbines.map((turbine, ti) => {
    const colour = PALETTE[ti % PALETTE.length]
    // Map ts-label → value for this turbine on this page
    const tsMap = {}
    for (const row of pageRows.value) {
      if (row[tColIdx] === turbine) {
        tsMap[formatTsLabel(row[tsIdx])] = parseVal(row[ci])
      }
    }
    const data = lbArr.map(lbl => tsMap[lbl] ?? null)
    return {
      label:           turbine,
      data,
      borderColor:     colour,
      backgroundColor: chartType.value === 'bar' ? colour + '99' : 'transparent',
      borderWidth:     chartType.value === 'bar' ? 1 : 1.5,
      pointRadius:     chartType.value === 'line' && lbArr.length < 200 ? 2 : 0,
      fill:            false,
      tension:         0.3,
      spanGaps:        true,
    }
  })

  return { labels: lbArr, datasets }
}

function buildChartOptions(col) {
  return {
    responsive:          true,
    maintainAspectRatio: false,
    animation:           false,
    plugins: {
      legend:  {
        display:  isMultiTurbine.value,
        position: 'top',
        labels:   { boxWidth: 12, font: { size: 11 } },
      },
      title:   { display: false },
      tooltip: { mode: 'index', intersect: false },
    },
    scales: {
      x: {
        ticks: { maxTicksLimit: 12, maxRotation: 0, font: { size: 11 } },
        grid:  { color: '#e4e7ec' },
      },
      y: {
        ticks: { font: { size: 11 } },
        grid:  { color: '#e4e7ec' },
        title: { display: true, text: col, font: { size: 11 }, color: '#888' },
      },
    },
  }
}

// Memoised maps
const chartDataMap    = computed(() => Object.fromEntries(selectedCols.value.map(col => [col, buildChartData(col)])))
const chartOptionsMap = computed(() => Object.fromEntries(selectedCols.value.map(col => [col, buildChartOptions(col)])))

// ── Auto-select preferred columns ──────────────────────────────────────────
const PREFERRED_COLUMNS = [
  'wind speed', 'wind direction', 'nacelle position',
  'power', 'rotor speed', 'generator rpm',
]

watch(
  () => props.result,
  () => {
    const available = numericColumns.value
    const matched = []
    for (const pref of PREFERRED_COLUMNS) {
      const found = available.find(col => col.toLowerCase().includes(pref.toLowerCase()))
      if (found && !matched.includes(found)) matched.push(found)
    }
    selectedCols.value = matched.length > 0 ? matched : available.slice(0, 5)
  },
  { immediate: true },
)
</script>

<style scoped>
/* ── Layout ───────────────────────────────────────────────────────────── */
.chart-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ── Controls ─────────────────────────────────────────────────────────── */
.chart-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  align-items: flex-start;
  padding: 14px 16px;
  background: #fafbfc;
  border: 1px solid #e4e7ec;
  border-radius: 8px;
}

.chart-control-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chart-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .05em;
  color: #555;
}

/* Column checkbox list */
.chart-col-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  max-height: 160px;
  overflow-y: auto;
  min-width: 260px;
}

.chart-checkbox {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}
.chart-checkbox input { accent-color: #4361ee; cursor: pointer; }

.chart-empty {
  font-size: 13px;
  color: #888;
  font-style: italic;
}

/* Chart type buttons */
.chart-type-btns {
  display: flex;
  gap: 6px;
}

.chart-type-btn {
  padding: 6px 14px;
  border: 1px solid #d0d5dd;
  border-radius: 6px;
  background: #fff;
  font-size: 13px;
  cursor: pointer;
  color: #555;
  transition: background .12s, color .12s, border-color .12s;
}
.chart-type-btn:hover { background: #f0f2f5; }
.chart-type-btn.active {
  background: #4361ee;
  color: #fff;
  border-color: #4361ee;
}

/* Page size select */
.chart-select {
  padding: 6px 10px;
  border: 1px solid #d0d5dd;
  border-radius: 6px;
  font-size: 13px;
  background: #fff;
  cursor: pointer;
}

/* ── Hint ─────────────────────────────────────────────────────────────── */
.chart-hint {
  text-align: center;
  color: #888;
  font-style: italic;
  padding: 32px 0;
  font-size: 14px;
}

/* ── Charts grid ──────────────────────────────────────────────────────── */
.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(520px, 1fr));
  gap: 16px;
}

.chart-card {
  background: #fff;
  border: 1px solid #e4e7ec;
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chart-card-title {
  font-size: 13px;
  font-weight: 600;
  color: #333;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chart-wrap {
  /* Fixed height so charts don't collapse */
  height: 220px;
  position: relative;
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

/* hide number spinner arrows */
.page-jump::-webkit-inner-spin-button,
.page-jump::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }
.page-jump { -moz-appearance: textfield; }
</style>

