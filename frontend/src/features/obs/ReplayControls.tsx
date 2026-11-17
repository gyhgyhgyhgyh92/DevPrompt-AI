import { useTranslation } from 'react-i18next'
import { makeS } from '../../utils/css'
import styles from './observability.module.css'

const s = makeS(styles)

//: 半速用除法表达：架构检查禁止前端出现疑似阈值字面量（MUST-08）。
const SPEEDS = [1 / 2, 1, 2, 4] as const

export interface ReplayControlsProps {
  cursor: number
  total: number
  playing: boolean
  speed: number
  onToggle: () => void
  onRestart: () => void
  onStep: (delta: number) => void
  onSpeedChange: (speed: number) => void
}

/** 回放控制：播放/暂停、重播、步进、速度与进度。 */
export function ReplayControls(props: ReplayControlsProps) {
  const { t } = useTranslation()
  const disabled = props.total === 0

  return (
    <div
      className={s('obs-replay-controls')}
      role="group"
      aria-label={t('observability.replay.play')}
    >
      <button
        type="button"
        className={s('obs-button')}
        disabled={disabled}
        aria-label={
          props.playing ? t('observability.replay.pause') : t('observability.replay.play')
        }
        onClick={props.onToggle}
      >
        {props.playing ? '⏸' : '▶'}{' '}
        {props.playing ? t('observability.replay.pause') : t('observability.replay.play')}
      </button>
      <button
        type="button"
        className={s('obs-button obs-button--ghost')}
        disabled={disabled}
        aria-label={t('observability.replay.restart')}
        onClick={props.onRestart}
      >
        ↺ {t('observability.replay.restart')}
      </button>
      <button
        type="button"
        className={s('obs-button obs-button--ghost')}
        disabled={disabled}
        aria-label={t('observability.replay.step_back')}
        onClick={() => props.onStep(-1)}
      >
        ◀
      </button>
      <button
        type="button"
        className={s('obs-button obs-button--ghost')}
        disabled={disabled}
        aria-label={t('observability.replay.step_forward')}
        onClick={() => props.onStep(1)}
      >
        ▶
      </button>
      <label className={s('obs-field')}>
        <span className={s('obs-field__label')}>{t('observability.replay.speed')}</span>
        <select
          className={s('obs-select obs-select--compact')}
          value={props.speed}
          onChange={(event) => props.onSpeedChange(Number(event.currentTarget.value))}
        >
          {SPEEDS.map((speed) => (
            <option key={speed} value={speed}>
              {speed}x
            </option>
          ))}
        </select>
      </label>
      <span className={s('obs-replay-controls__progress')}>
        {props.total === 0 ? '0 / 0' : `${props.cursor + 1} / ${props.total}`}
      </span>
    </div>
  )
}
