/** ISO 时间 → 本地可读时间（纯函数，无副作用）。 */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString()
}

/** 长文本截断用于列表摘要（纯函数）。 */
export function truncate(text: string, maxChars: number): string {
  return text.length > maxChars ? `${text.slice(0, maxChars)}…` : text
}
