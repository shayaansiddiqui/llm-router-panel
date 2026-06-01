import { useState } from 'react';
import { LockKeyhole, Loader2, Workflow } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { api, setAdminToken } from '@/lib/api';

export function Login({ onLogin }) {
  const [form, setForm] = useState({ username: 'admin', password: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError('');
    setLoading(true);
    try {
      const result = await api('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify(form),
      });
      setAdminToken(result.token);
      onLogin(result);
    } catch (loginError) {
      setError(loginError.message || 'Login failed.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-muted/30 px-4 py-10">
      <section className="w-full max-w-md rounded-xl border bg-card shadow-sm">
        <div className="border-b p-6">
          <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Workflow className="h-5 w-5" />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">LLM Gateway</h1>
          <p className="mt-1 text-sm text-muted-foreground">Sign in to manage providers, keys, models, and logs.</p>
        </div>

        <form className="grid gap-4 p-6" onSubmit={submit}>
          <Label className="grid gap-2">
            Username
            <Input
              autoComplete="username"
              value={form.username}
              onChange={(event) => setForm({ ...form, username: event.target.value })}
              required
            />
          </Label>
          <Label className="grid gap-2">
            Password
            <Input
              autoComplete="current-password"
              type="password"
              value={form.password}
              onChange={(event) => setForm({ ...form, password: event.target.value })}
              required
            />
          </Label>

          {error && (
            <div className="rounded-md border border-destructive/20 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          )}

          <Button type="submit" className="h-10" disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <LockKeyhole className="h-4 w-4" />}
            Sign in
          </Button>
        </form>
      </section>
    </main>
  );
}
