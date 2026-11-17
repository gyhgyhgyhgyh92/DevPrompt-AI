import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useSettingsStore } from '../stores/useSettingsStore'
import { LabSection, PlayControls, Segmented } from './LabSwitcher'
import { useLabCopy } from './labCopy'
import { deriveDemo, useDemoPlayback } from './demoStream'
import { LabChatThread } from './specimens/LabChatThread'
import { LabPaletteTable } from './specimens/LabPaletteTable'
import { LabSidebar } from './specimens/LabSidebar'
import { LabStartPage } from './specimens/LabStartPage'
import { LabStreamDigest } from './specimens/LabStreamDigest'
import { LabStreamRail } from './specimens/LabStreamRail'
import { LabStreamTypewriter } from './specimens/LabStreamTypewriter'
import { LabToolCardSample } from './specimens/LabToolCard'
import {
  LAB_COMPOSITIONS,
  LAB_PALETTES,
  LAB_STYLES,
  LAB_THEMES,
  LAB_VARIANTS,
  type LabPaletteId,
  type LabStartComposition,
  type LabStreamVariant,
  type LabStyleId,
  type LabThemeMode,
} from './types'
import { cx, usePrefersReducedMotion } from './utils'
import './styles/lab.css'

function readParam(key: string): string | null {
  return new URLSearchParams(window.location.search).get(key)
}

function pickParam<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  const value = readParam(key)
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : fallback
}

/** 跟随系统主题：lab 内嵌多面板，必须自己解析 system（根节点的 data-theme 只反映应用级偏好）。 */
function useResolvedTheme(mode: LabThemeMode): 'light' | 'dark' {
  const [isSystemDark, setSystemDark] = useState(
    () =>
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-color-scheme: dark)').matches,
  )

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const handleChange = (): void => setSystemDark(media.matches)
    media.addEventListener?.('change', handleChange)
    return () => media.removeEventListener?.('change', handleChange)
  }, [])

  if (mode !== 'system') return mode
  return isSystemDark ? 'dark' : 'light'
}

interface StylePanelProps {
  styleId: LabStyleId
  index: number
  palette: LabPaletteId
  theme: 'light' | 'dark'
  copy: ReturnType<typeof useLabCopy>
  children: ReactNode
}

/** 一列 = 一套风格：外层挂 data 属性，内部所有 utility 自动取该风格的 token。 */
function StylePanel({ styleId, index, palette, theme, copy, children }: StylePanelProps) {
  const meta = copy.styles[styleId]
  return (
    <div
      className="lab-surface flex flex-col gap-2 rounded-panel border border-line bg-canvas p-2.5 shadow-card"
      data-lab-style={styleId}
      data-lab-palette={palette}
      data-theme={theme}
    >
      <header className="flex flex-col gap-[2px] px-[2px] pb-1">
        <div className="flex items-baseline gap-2">
          <h3 className="text-lead font-semibold text-ink">{meta.name}</h3>
          <span className="ml-auto font-mono text-micro text-ink-4">S{index + 1}</span>
        </div>
        <p className="font-mono text-micro tracking-[0.04em] text-ink-3">{meta.tagline}</p>
        <p className="text-micro text-ink-4">{meta.use}</p>
      </header>
      {children}
    </div>
  )
}

/** 样式样张页（DEV only）：三风格并列 + 三流式变体并列 + 配色对比度实测。 */
export default function StyleLab() {
  const copy = useLabCopy()
  const locale = useSettingsStore((s) => s.appearance.locale)
  const [styleId, setStyleId] = useState<LabStyleId>(() =>
    pickParam('style', LAB_STYLES, 'blueprint'),
  )
  const [palette, setPalette] = useState<LabPaletteId>(() =>
    pickParam('palette', LAB_PALETTES, 'signal'),
  )
  const [themeMode, setThemeMode] = useState<LabThemeMode>(() =>
    pickParam('theme', LAB_THEMES, 'light'),
  )
  const [variant, setVariant] = useState<LabStreamVariant>(() =>
    pickParam('variant', LAB_VARIANTS, 'rail'),
  )
  const [composition, setComposition] = useState<LabStartComposition>(() =>
    pickParam('composition', LAB_COMPOSITIONS, 'centered'),
  )
  const [speed, setSpeed] = useState(1)
  const theme = useResolvedTheme(themeMode)
  const isReduced = usePrefersReducedMotion()
  const playback = useDemoPlayback(speed)
  const view = deriveDemo(playback.applied, locale, playback.isPlaying)

  // 组合写回 URL：方便把某一组样张直接发给别人看（不触发路由跳转）
  useEffect(() => {
    const params = new URLSearchParams({
      style: styleId,
      palette,
      theme: themeMode,
      variant,
      composition,
    })
    window.history.replaceState(null, '', `?${params.toString()}`)
  }, [styleId, palette, themeMode, variant, composition])

  const activeStyle = copy.styles[styleId]
  const summary = [
    activeStyle.name,
    copy.palettes[palette].name,
    copy.themes[themeMode],
    copy.variants[variant].name,
  ].join(' · ')

  const streamProps = {
    view,
    copy,
    applied: playback.applied,
    isPlaying: playback.isPlaying,
    isReduced,
    onPlay: playback.play,
  }

  return (
    <div
      className="lab-root lab-surface min-h-dvh bg-canvas text-ink"
      data-lab-root
      data-lab-style={styleId}
      data-lab-palette={palette}
      data-theme={theme}
    >
      <header className="sticky top-0 z-20 border-b border-line bg-canvas/90 backdrop-blur-sm">
        <div className="mx-auto flex w-full max-w-[1680px] flex-col gap-2 px-4 py-2.5">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="inline-flex items-center gap-2">
              <span aria-hidden="true" className="inline-block size-2 rounded-[2px] bg-accent" />
              <span className="font-mono text-micro tracking-[0.16em] text-ink-2 uppercase">
                {copy.brand}
              </span>
              <span className="font-mono text-micro text-ink-3">/ {copy.name}</span>
            </span>
            <span className="text-micro text-ink-4">{copy.hint}</span>
            <span className="ml-auto font-mono text-micro text-ink-3">{summary}</span>
          </div>
          <p className="max-w-[92ch] text-meta leading-relaxed text-ink-2">{copy.intro}</p>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <Segmented
              label={copy.controls.style}
              value={styleId}
              onChange={setStyleId}
              options={LAB_STYLES.map((id) => ({ id, label: copy.styles[id].name }))}
            />
            <Segmented
              label={copy.controls.palette}
              value={palette}
              onChange={setPalette}
              options={LAB_PALETTES.map((id) => ({ id, label: copy.palettes[id].name }))}
            />
            <Segmented
              label={copy.controls.theme}
              value={themeMode}
              onChange={setThemeMode}
              options={LAB_THEMES.map((id) => ({ id, label: copy.themes[id] }))}
            />
            <Segmented
              label={copy.controls.variant}
              value={variant}
              onChange={setVariant}
              options={LAB_VARIANTS.map((id) => ({ id, label: copy.variants[id].name }))}
            />
            <Segmented
              label={copy.controls.composition}
              value={composition}
              onChange={setComposition}
              options={LAB_COMPOSITIONS.map((id) => ({ id, label: copy.compositions[id] }))}
            />
            <PlayControls
              isPlaying={playback.isPlaying}
              speed={speed}
              playLabel={copy.controls.play}
              pauseLabel={copy.controls.pause}
              replayLabel={copy.controls.replay}
              speedLabel={copy.controls.speed}
              onPlay={playback.play}
              onPause={playback.pause}
              onReplay={playback.replay}
              onSpeed={setSpeed}
            />
          </div>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-[1680px] flex-col gap-7 px-4 py-5">
        <LabSection title={copy.sections.start} hint={copy.sectionHints.start}>
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
            {LAB_STYLES.map((id, index) => (
              <StylePanel
                key={id}
                styleId={id}
                index={index}
                palette={palette}
                theme={theme}
                copy={copy}
              >
                <LabStartPage copy={copy} composition={composition} />
              </StylePanel>
            ))}
          </div>
        </LabSection>

        <LabSection title={copy.sections.thread} hint={copy.sectionHints.thread}>
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
            {LAB_STYLES.map((id, index) => (
              <StylePanel
                key={id}
                styleId={id}
                index={index}
                palette={palette}
                theme={theme}
                copy={copy}
              >
                <LabChatThread copy={copy} />
              </StylePanel>
            ))}
          </div>
        </LabSection>

        <LabSection
          title={copy.sections.stream}
          hint={`${copy.sectionHints.stream} · ${activeStyle.name}`}
        >
          <div
            className="lab-surface grid grid-cols-1 items-start gap-3 rounded-panel border border-line bg-canvas p-2.5 xl:grid-cols-3"
            data-lab-style={styleId}
            data-lab-palette={palette}
            data-theme={theme}
          >
            {/* 顶部「流式变体」用来标记首选：三列始终并列，被选中的那列加一圈强调描边 */}
            <div className={cx('rounded-panel', variant === 'typewriter' && 'ring-1 ring-accent')}>
              <LabStreamTypewriter {...streamProps} />
            </div>
            <div className={cx('rounded-panel', variant === 'rail' && 'ring-1 ring-accent')}>
              <LabStreamRail {...streamProps} />
            </div>
            <div className={cx('rounded-panel', variant === 'digest' && 'ring-1 ring-accent')}>
              <LabStreamDigest {...streamProps} />
            </div>
          </div>
        </LabSection>

        <LabSection title={copy.sections.tools} hint={copy.sectionHints.tools}>
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
            {LAB_STYLES.map((id, index) => (
              <StylePanel
                key={id}
                styleId={id}
                index={index}
                palette={palette}
                theme={theme}
                copy={copy}
              >
                <div className="flex flex-col gap-2">
                  {(['pill', 'card', 'terminal'] as const).map((form) => (
                    <div key={form} className="flex flex-col gap-1">
                      <span className="font-mono text-micro tracking-[0.12em] text-ink-4 uppercase">
                        {copy.tools.forms[form]} · {copy.tools.formHints[form]}
                      </span>
                      <LabToolCardSample form={form} copy={copy} />
                    </div>
                  ))}
                </div>
              </StylePanel>
            ))}
          </div>
        </LabSection>

        <LabSection title={copy.sections.sidebar} hint={copy.sectionHints.sidebar}>
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
            {LAB_STYLES.map((id, index) => (
              <StylePanel
                key={id}
                styleId={id}
                index={index}
                palette={palette}
                theme={theme}
                copy={copy}
              >
                <LabSidebar copy={copy} />
              </StylePanel>
            ))}
          </div>
        </LabSection>

        <LabSection title={copy.sections.palette} hint={copy.sectionHints.palette}>
          <LabPaletteTable
            copy={copy}
            styleId={styleId}
            theme={theme}
            activePalette={palette}
            onSelect={setPalette}
          />
        </LabSection>
      </main>

      <footer className="mx-auto w-full max-w-[1680px] px-4 pb-6">
        <p className={cx('border-t border-line pt-3 text-micro text-ink-4')}>{copy.footer}</p>
      </footer>
    </div>
  )
}
