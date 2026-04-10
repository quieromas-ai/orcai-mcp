export function Input({ label, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-slate-400">{label}</span>
      <input
        className="w-full rounded-md border border-border bg-base px-3 py-2 text-sm text-slate-200 outline-none placeholder:text-slate-700 focus:border-accent focus:ring-1 focus:ring-accent/30"
        {...props}
      />
    </label>
  )
}
