import { useState } from 'react';
import { Card, ErrorNotice, Loading, ShadSelect } from '@/components/common';
import { LogTable } from '@/components/log-table';
import { useResource } from '@/hooks/use-resource';

export function Requests({ refreshKey }) {
  const { data, loading, error } = useResource('/api/logs', refreshKey);
  const [filter, setFilter] = useState('all');
  if (loading && !data) return <Loading label="Loading upstream attempts" />;
  const visible = (data || []).filter((log) => filter === 'all' || log.status === filter);
  return (
    <section className="grid gap-5">
      <ErrorNotice message={error} />
      <Card title="Request attempts" description="The latest 200 upstream attempts. Retries appear separately; streaming duration includes the full stream." action={<ShadSelect value={filter} onChange={setFilter} options={[{ value: 'all', label: 'All outcomes' }, { value: 'success', label: 'Successful' }, { value: 'failed', label: 'Failed' }, { value: 'cancelled', label: 'Cancelled' }]} />}>
        <LogTable logs={visible} />
      </Card>
    </section>
  );
}
