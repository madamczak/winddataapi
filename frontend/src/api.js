/**
 * api.js — thin wrapper around the Wind Farm Data API.
 *
 * BASE_URL is intentionally empty (relative) so that:
 *  - In Docker:     Nginx on port 80 proxies /wind-farms → backend:8000
 *  - In local dev:  Vite dev server proxies /wind-farms → 127.0.0.1:8000
 *                   (see vite.config.js proxy config)
 *
 * This avoids all CORS issues because the browser always talks to the same
 * origin that served the page.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

/**
 * Fetch the list of available wind farms.
 * @returns {Promise<Array>}  Array of { name, directory, turbine_count, turbines }
 */
export async function fetchWindFarms() {
  const res = await fetch(`${BASE_URL}/wind-farms`)
  if (!res.ok) throw new Error(`Failed to fetch wind farms: ${res.status}`)
  const data = await res.json()
  return data.wind_farms
}

/**
 * Fetch earliest/latest timestamps for each farm.
 * @returns {Promise<Array>}  Array of { farm, earliest, latest, timestamp_column }
 */
export async function fetchTimeRanges() {
  const res = await fetch(`${BASE_URL}/wind-farms/time-ranges`)
  if (!res.ok) throw new Error(`Failed to fetch time ranges: ${res.status}`)
  const data = await res.json()
  return data.time_ranges
}

/**
 * Fetch column names grouped by file type for all farms.
 * @returns {Promise<Array>}  Array of { farm, columns_by_type }
 */
export async function fetchColumns() {
  const res = await fetch(`${BASE_URL}/wind-farms/columns`)
  if (!res.ok) throw new Error(`Failed to fetch columns: ${res.status}`)
  const data = await res.json()
  return data.farms
}

/**
 * Fetch distinct IEC category event types for a farm/turbine.
 * @returns {Promise<string[]>}
 */
export async function fetchEventTypes(farm, turbine) {
  const res = await fetch(`${BASE_URL}/wind-farms/${farm}/${turbine}/event-types`)
  if (!res.ok) throw new Error(`Failed to fetch event types: ${res.status}`)
  const data = await res.json()
  return data.event_types
}

/**
 * Fetch status events for a turbine, filtered by IEC category and/or status.
 * @returns {Promise<{columns: string[], events: object[], count: number}>}
 */
export async function fetchEvents(farm, turbine, iecCategory = null, status = null, limit = 500) {
  const params = new URLSearchParams()
  if (iecCategory) params.set('iec_category', iecCategory)
  if (status) params.set('status', status)
  params.set('limit', limit)
  const res = await fetch(`${BASE_URL}/wind-farms/${farm}/${turbine}/events?${params.toString()}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? `Request failed: ${res.status}`)
  }
  return res.json()
}

/**
 * Fetch data rows for a specific farm, turbine, date range, and file type.
 *
 * @param {string}      farm       Directory name, e.g. "kelmarsh"
 * @param {string}      dateFrom   ISO date string "YYYY-MM-DD" (start)
 * @param {string}      fileType   "data" or "status"
 * @param {string}      turbine    Turbine name, e.g. "turbine_1"
 * @param {string[]}    columns    Empty array = return all columns
 * @param {number|null} hourFrom   Filter from this hour (0–23) on first day, or null
 * @param {number|null} hourTo     Filter up to this hour (0–23) on last day, or null
 * @param {string|null} dateTo     ISO date string "YYYY-MM-DD" (end), or null for single day
 * @returns {Promise<{columns: string[], rows: any[][], row_count: number}>}
 */
export async function fetchDayData(farm, dateFrom, fileType, turbine, columns = [], hourFrom = null, hourTo = null, dateTo = null) {
  const params = new URLSearchParams()
  params.set('file_type', fileType)
  if (turbine) params.set('turbine', turbine)
  for (const col of columns) {
    params.append('columns', col)
  }
  if (hourFrom !== null && hourFrom !== '') params.set('hour_from', hourFrom)
  if (hourTo   !== null && hourTo   !== '') params.set('hour_to',   hourTo)
  if (dateTo && dateTo !== dateFrom)        params.set('date_to',   dateTo)
  const url = `${BASE_URL}/wind-farms/${farm}/data/${dateFrom}?${params.toString()}`
  const res = await fetch(url)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? `Request failed: ${res.status}`)
  }
  return res.json()
}
