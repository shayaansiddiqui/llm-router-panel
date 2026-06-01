import { Loader2 } from 'lucide-react';
import { Badge as UIBadge } from '@/components/ui/badge';
import { Card as UICard, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';

export function Card({ title, description, action, children, className }) {
  return (
    <UICard className={cn('shadow-sm', className)}>
      {(title || description || action) && (
        <CardHeader className="flex flex-row items-start justify-between gap-4 border-b">
          <div className="grid gap-1">
            {title && <CardTitle>{title}</CardTitle>}
            {description && <CardDescription>{description}</CardDescription>}
          </div>
          {action}
        </CardHeader>
      )}
      <CardContent>{children}</CardContent>
    </UICard>
  );
}

export function StatusBadge({ active, label }) {
  return (
    <UIBadge variant={active ? 'secondary' : 'outline'} className={cn('capitalize', active && 'bg-emerald-50 text-emerald-700')}>
      {label || (active ? 'Active' : 'Passive')}
    </UIBadge>
  );
}

export function EmptyState({ children }) {
  return (
    <div className="flex min-h-32 items-center justify-center rounded-md border border-dashed bg-muted/30 px-4 py-8 text-center text-sm text-muted-foreground">
      {children}
    </div>
  );
}

export function ShadSelect({ value, onChange, placeholder, options }) {
  const normalizedValue = value || 'none';
  const selected = options.find((option) => (option.value || 'none') === normalizedValue);

  return (
    <Select value={normalizedValue} onValueChange={(nextValue) => onChange(nextValue === 'none' ? '' : nextValue)}>
      <SelectTrigger className="w-full">
        <span className={cn('truncate text-left', !selected && 'text-muted-foreground')}>{selected?.label || placeholder}</span>
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value || 'empty'} value={option.value || 'none'}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function DataTable({ headers, rows, empty = 'No records.' }) {
  if (!rows.length) return <EmptyState>{empty}</EmptyState>;
  return (
    <div className="overflow-hidden rounded-md border">
      <Table>
        <TableHeader className="bg-muted/60">
          <TableRow>
            {headers.map((header) => (
              <TableHead key={header} className="px-4 text-xs font-semibold uppercase text-muted-foreground">
                {header}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, rowIndex) => (
            <TableRow key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <TableCell key={cellIndex} className="px-4 py-3">
                  {cell}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function Loading({ label }) {
  return (
    <div className="flex min-h-64 items-center justify-center rounded-lg border bg-card text-sm text-muted-foreground">
      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
      {label}
    </div>
  );
}

export function Metric({ icon: Icon, label, value }) {
  return (
    <div className="rounded-lg border bg-card p-5 shadow-soft">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-muted-foreground">{label}</span>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="mt-3 text-3xl font-semibold tracking-tight">{value}</div>
    </div>
  );
}
