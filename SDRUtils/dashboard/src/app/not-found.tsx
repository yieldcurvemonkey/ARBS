import Link from 'next/link'

export default function NotFound() {
  return (
    <div className="mx-auto max-w-2xl py-16 text-center">
      <h1 className="text-2xl font-semibold text-slate-100">Page not found</h1>
      <p className="mt-3 text-sm text-slate-400">
        The page you requested does not exist.
      </p>
      <Link
        href="/"
        className="mt-6 inline-flex rounded border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"
      >
        Back to home
      </Link>
    </div>
  )
}
