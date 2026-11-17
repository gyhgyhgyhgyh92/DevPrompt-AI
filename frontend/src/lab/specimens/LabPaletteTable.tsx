import { useEffect, useRef, useState } from 'react'
import type { LabCopy } from '../labCopy'
import { LAB_PALETTES, type LabPaletteId, type LabStyleId, type LabThemeMode } from '../types'
import { blendOver, contrastRatio, cx, readToken } from '../utils'

/** 五行固定配对：前三行是正文/次级/辅助，第四行强调色（UI 元件 3:1），第五行浅底上的深字。 */
const ROWS: readonly { fg: string; bg: string; min: number }[] = [
  { fg: '--color-text-primary', bg: '--color-surface-base', min: 4.5 },
  { fg: '--color-text-secondary', bg: '--color-surface-base', min: 4.5 },
  { fg: '--color-text-muted', bg: '--color-surface-base', min: 4.5 },
  { fg: '--color-primary-500', bg: '--color-surface-base', min: 3 },
  { fg: '--color-text-primary', bg: '--color-primary-soft', min: 4.5 },
]

interface ProbeProps {
  palette: LabPaletteId
  styleId: LabStyleId
  theme: LabThemeMode
  isActive: boolean
  onSelect: (palette: LabPaletteId) => void
  copy: LabCopy
}

/** 每套配色是一个独立 lab-surface：直接读它自己的计算值，避免在 TS 里复制色值。 */
function PaletteProbe({ palette, styleId, theme, isActive, onSelect, copy }: ProbeProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [ratios, setRatios] = useState<readonly (number | null)[]>([])

  useEffect(() => {
    const node = ref.current
    if (node === null) return
    const canvas = readToken(node, '--color-surface-base')
    setRatios(
      ROWS.map((row) => {
        const rawBg = readToken(node, row.bg)
        const resolvedBg = rawBg.includes('rgba') ? blendOver(rawBg, canvas) : rawBg
        return contrastRatio(readToken(node, row.fg), resolvedBg)
      }),
    )
  }, [palette, styleId, theme])

  return (
    <div
      ref={ref}
      className={cx(
        'lab-surface flex flex-col gap-2 rounded-card border p-2.5',
        isActive ? 'border-accent bg-accent-soft/40' : 'border-line bg-canvas',
      )}
      data-lab-palette={palette}
      data-lab-style={styleId}
      data-theme={theme === 'dark' ? 'dark' : 'light'}
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onSelect(palette)}
          aria-pressed={isActive}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <span
            aria-hidden="true"
            className={cx(
              'inline-block size-2.5 shrink-0 rounded-round border',
              isActive ? 'border-accent bg-accent' : 'border-line-strong bg-surface',
            )}
          />
          <span className="truncate text-meta font-medium text-ink">
            {copy.palettes[palette].name}
          </span>
        </button>
        <span className="flex shrink-0 items-center gap-1">
          {['--color-primary-500', '--color-primary-900', '--color-primary-soft'].map((token) => (
            <span
              key={token}
              aria-hidden="true"
              className="inline-block size-3 rounded-[3px] border border-line"
              style={{ background: `var(${token})` }}
            />
          ))}
        </span>
      </div>
      <p className="text-micro leading-relaxed text-ink-3">{copy.palettes[palette].note}</p>
      <table className="w-full border-collapse">
        <tbody>
          {ROWS.map((row, index) => {
            const ratio = ratios[index] ?? null
            const passes = ratio !== null && ratio >= row.min
            return (
              <tr key={row.fg + row.bg} className="border-t border-line/70">
                <td className="py-1 pr-2 text-micro text-ink-3">{copy.palette.rows[index]}</td>
                <td className="py-1 text-right font-mono text-micro text-ink-2">
                  {ratio === null ? '—' : `${ratio.toFixed(1)}:1`}
                </td>
                <td className="w-6 py-1 pl-2 text-right">
                  <span
                    aria-hidden="true"
                    className={cx(
                      'inline-block size-1.5 rounded-round',
                      passes ? 'bg-ok' : 'bg-warn',
                    )}
                    title={passes ? 'AA' : `< ${row.min}:1`}
                  />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

interface LabPaletteTableProps {
  copy: LabCopy
  styleId: LabStyleId
  theme: LabThemeMode
  activePalette: LabPaletteId
  onSelect: (palette: LabPaletteId) => void
}

/** 06 配色与对比度：三套配色并排，数值是**实测**（读 CSS 变量后算 WCAG 比），不是手写常量。 */
export function LabPaletteTable({
  copy,
  styleId,
  theme,
  activePalette,
  onSelect,
}: LabPaletteTableProps) {
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
        {LAB_PALETTES.map((palette) => (
          <PaletteProbe
            key={palette}
            palette={palette}
            styleId={styleId}
            theme={theme}
            isActive={palette === activePalette}
            onSelect={onSelect}
            copy={copy}
          />
        ))}
      </div>
      <p className="text-micro leading-relaxed text-ink-4">{copy.palette.note}</p>
    </div>
  )
}
