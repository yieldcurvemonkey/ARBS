import { spawn } from 'child_process'
import path from 'path'

export type SofrCurveNode = { date: string; df: number }

export type SofrCurveResponse = {
  curve_name: string
  source: string
  timestamp: string | null
  reference_date: string | null
  meta: Record<string, any> | null
  nodes: SofrCurveNode[]
}

const CACHE_TTL_MS = 5 * 60 * 1000

let cachedKey: string | null = null
let cachedAt = 0
let cachedValue: SofrCurveResponse | null = null

function buildCacheKey(source: string, curveName: string, timestamp: string | null) {
  return `${source}::${curveName}::${timestamp ?? ''}`
}

export async function getSofrCurve(params?: {
  source?: string
  curveName?: string
  timestamp?: string | null
}): Promise<SofrCurveResponse> {
  const source = params?.source ?? 'ERIS_EOD_LIVE-QL_BASIC'
  const curveName = params?.curveName ?? 'USD-SOFR-1D'
  const timestamp = params?.timestamp ?? null
  const cacheKey = buildCacheKey(source, curveName, timestamp)
  const now = Date.now()

  if (cachedKey === cacheKey && cachedValue && now - cachedAt < CACHE_TTL_MS) {
    return cachedValue
  }

  const dashboardRoot = process.cwd()
  const repoRoot = path.resolve(dashboardRoot, '..', '..')
  const scriptPath = path.resolve(
    repoRoot,
    'MDP',
    'IRSwaps',
    'sofr_curve_endpoint.py'
  )

  const args = [scriptPath, '--source', source, '--curve-name', curveName]
  if (timestamp) {
    args.push('--timestamp', timestamp)
  }

  const pythonCmd = process.env.PYTHON_BIN || 'python'

  const env = {
    ...process.env,
    PYTHONPATH: `${repoRoot}${path.delimiter}${process.env.PYTHONPATH ?? ''}`,
    PYTHONIOENCODING: 'utf-8'
  }

  const output = await new Promise<string>((resolve, reject) => {
    const child = spawn(pythonCmd, args, { env })
    let stdout = ''
    let stderr = ''

    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString()
    })
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString()
    })
    child.on('error', (err) => reject(err))
    child.on('close', (code) => {
      if (code !== 0) {
        reject(new Error(stderr || `Python exited with code ${code}`))
        return
      }
      resolve(stdout)
    })
  })

  const parsed = JSON.parse(output.trim()) as SofrCurveResponse
  cachedKey = cacheKey
  cachedAt = now
  cachedValue = parsed
  return parsed
}
