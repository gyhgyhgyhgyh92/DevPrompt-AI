/** ISO 时间 → 本地可读时间（纯函数，无副作用）。 */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString()
}
