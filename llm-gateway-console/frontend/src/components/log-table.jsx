import { DataTable, StatusBadge as Badge } from '@/components/common';

export function LogTable({ logs }) {
  return (
    <DataTable
      headers={['Time', 'Model', 'Node', 'Status', 'Duration', 'Details']}
      rows={(logs || []).map((log) => [
        new Date(log.created_at).toLocaleString(),
        log.requested_model || '-',
        log.provider_name || '-',
        <Badge active={log.status === 'success'} label={log.status} />,
        `${log.duration_ms} ms`,
        <span className="block max-w-sm break-words text-xs text-muted-foreground">{log.error_message || (log.status_code ? `HTTP ${log.status_code}` : '—')}</span>,
      ])}
      empty="No request logs yet."
    />
  );
}
