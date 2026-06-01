import { useState } from 'react';
import { Check, ChevronDown, Copy } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export function CopyButton({ value, label = 'Copy', variant = 'ghost', size = 'sm', className }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <Button type="button" variant={variant} size={size} className={className} onClick={copy}>
      {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
      {copied ? 'Copied' : label}
    </Button>
  );
}

export function InlineCode({ children, className }) {
  return (
    <code className={cn('rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-foreground break-words', className)}>
      {children}
    </code>
  );
}

export function CodeBlock({ label, value, className }) {
  return (
    <div className={cn('min-w-0 max-w-full overflow-hidden rounded-lg border bg-background', className)}>
      <div className="flex min-w-0 items-center justify-between gap-3 border-b bg-muted/50 px-3 py-2">
        <span className="min-w-0 truncate text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</span>
        <CopyButton value={value} />
      </div>
      <pre className="max-h-[560px] max-w-full overflow-x-auto overflow-y-auto p-4 text-sm leading-6">
        <code>{value}</code>
      </pre>
    </div>
  );
}

export function DocsSection({ id, eyebrow, title, description, children }) {
  return (
    <section id={id} className="min-w-0 scroll-mt-24">
      <div className="mb-4">
        {eyebrow && <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{eyebrow}</div>}
        <h3 className="text-2xl font-semibold tracking-tight">{title}</h3>
        {description && <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  );
}

export function SectionCard({ children, className }) {
  return (
    <div className={cn('min-w-0 rounded-lg border bg-card p-4 shadow-sm', className)}>
      {children}
    </div>
  );
}

export function Callout({ title, children, className }) {
  return (
    <div className={cn('rounded-lg border bg-muted/30 p-4', className)}>
      <div className="font-medium">{title}</div>
      <div className="mt-1 text-sm leading-6 text-muted-foreground">{children}</div>
    </div>
  );
}

export function MethodPill({ method }) {
  const styles = {
    GET: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    POST: 'border-blue-200 bg-blue-50 text-blue-700',
    DELETE: 'border-red-200 bg-red-50 text-red-700',
  };

  return (
    <span className={cn('inline-flex h-6 items-center rounded border px-2 font-mono text-xs font-semibold', styles[method] || 'border-border bg-muted text-foreground')}>
      {method}
    </span>
  );
}

export function ExpandableEndpoint({ method, path, title, auth = 'Bearer key', description, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="min-w-0 border-b last:border-b-0">
      <button
        type="button"
        className="flex w-full flex-col gap-3 px-4 py-4 text-left transition-colors hover:bg-muted/35 lg:flex-row lg:items-start lg:justify-between"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <MethodPill method={method} />
            <code className="break-all font-mono text-sm font-semibold">{path}</code>
          </div>
          <div className="mt-2 font-medium">{title}</div>
          {description && <div className="mt-1 text-sm leading-6 text-muted-foreground">{description}</div>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="w-fit rounded bg-muted px-2 py-1 text-xs text-muted-foreground">{auth}</span>
          <ChevronDown className={cn('h-4 w-4 text-muted-foreground transition-transform', open && 'rotate-180')} />
        </div>
      </button>
      {open && <div className="min-w-0 border-t bg-muted/20 p-4">{children}</div>}
    </div>
  );
}

export function ReferenceShell({ children, className }) {
  return (
    <div className={cn('min-w-0 max-w-full overflow-hidden rounded-lg border bg-card shadow-sm', className)}>
      {children}
    </div>
  );
}
