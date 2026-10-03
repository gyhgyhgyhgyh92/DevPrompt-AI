export function ProfilePage() {
  return <main className="profile-page" data-testid="profile-page">个人中心</main>
}

export function SettingsPage({ section = 'general' }: { section?: string }) {
  return <main className="settings-page">设置：{section}</main>
}

export async function requestClient<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init)
  if (!res.ok) {
    throw new Error(`request failed: ${res.status}`)
  }
  return res.json() as Promise<T>
}

export function formatDate(iso: string): string {
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
