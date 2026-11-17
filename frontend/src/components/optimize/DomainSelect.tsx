/**
 * 模式选择下拉（2026-11-14 多模态）。
 *
 * 为什么不用原生 `<select>`：原生 option 由系统渲染，页面无法在选项内插入气泡、
 * 也无法监听单个 option 的悬停——「展开菜单逐项预览说明」只能自建 listbox。
 * 交互模式沿用同目录 ModelPicker（点外部/Esc 收起、菜单向下展开）。
 *
 * 每个选项挂 ui/Tooltip：鼠标悬停该选项即在右侧弹出该模式的「作用 + 用法」。
 */

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { DomainIdSchema, type DomainId } from '../../schemas/optimize'
import { makeS } from '../../utils/css'
import { Tooltip } from '../ui/Tooltip'
import styles from './DomainSelect.module.css'

const s = makeS(styles)

export interface DomainSelectProps {
  /** 当前模式；空串 = 自动识别。 */
  value: '' | DomainId
  disabled?: boolean
  /** 选择模式（'' 表示回到自动识别）。 */
  onChange: (value: '' | DomainId) => void
}

interface Option {
  key: string
  id: '' | DomainId
  name: string
  /** 气泡文案键（自动识别对应 auto）。 */
  tipKey: string
}

export function DomainSelect({ value, disabled = false, onChange }: DomainSelectProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  // 悬停的选项 key：气泡由整行悬停驱动（受控），而非仅选项文字
  const [hoveredKey, setHoveredKey] = useState<string | null>(null)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const listRef = useRef<HTMLUListElement | null>(null)

  const options: Option[] = useMemo(
    () => [
      { key: 'auto', id: '', name: t('optimize.domain_auto'), tipKey: 'auto' },
      ...DomainIdSchema.options.map((id) => ({
        key: id,
        id,
        name: t(`domain.${id}.name`, id),
        tipKey: id,
      })),
    ],
    [t],
  )

  // 点空白 / Esc 收起（与 ModelPicker 一致）
  useEffect(() => {
    if (!open) return undefined
    const onDocClick = (event: MouseEvent): void => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: globalThis.KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  // 打开时把高亮落在当前选中项上，并把焦点交给列表（键盘方向键才有效）
  useEffect(() => {
    if (!open) return
    const index = options.findIndex((option) => option.id === value)
    setActiveIndex(index >= 0 ? index : 0)
    listRef.current?.focus()
  }, [open, options, value])

  const select = (option: Option): void => {
    setOpen(false)
    onChange(option.id)
  }

  const onListKeyDown = (event: KeyboardEvent<HTMLUListElement>): void => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveIndex((prev) => Math.min(prev + 1, options.length - 1))
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIndex((prev) => Math.max(prev - 1, 0))
      return
    }
    if (event.key === 'Home') {
      event.preventDefault()
      setActiveIndex(0)
      return
    }
    if (event.key === 'End') {
      event.preventDefault()
      setActiveIndex(options.length - 1)
      return
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      const option = options[activeIndex]
      if (option !== undefined) select(option)
    }
  }

  const current = options.find((option) => option.id === value)
  // 触发器气泡：菜单未展开时说明当前模式；展开后由各选项自身的气泡接管
  const currentTipKey = value === '' ? 'auto' : value

  return (
    <div className={s('domain-select')} ref={rootRef}>
      <Tooltip
        title={t(`tooltip.domain.${currentTipKey}.title`)}
        rows={[
          {
            label: t('tooltip.label_purpose'),
            text: t(`tooltip.domain.${currentTipKey}.purpose`),
          },
          { label: t('tooltip.label_usage'), text: t(`tooltip.domain.${currentTipKey}.usage`) },
        ]}
      >
        <button
          type="button"
          className={s('domain-select__trigger')}
          aria-haspopup="listbox"
          aria-expanded={open}
          disabled={disabled}
          onClick={() => setOpen((prev) => !prev)}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
              event.preventDefault()
              setOpen(true)
            }
          }}
        >
          <span>{current?.name ?? t('optimize.domain_auto')}</span>
          <span className={s('domain-select__caret')} aria-hidden="true">
            ▾
          </span>
        </button>
      </Tooltip>
      {open ? (
        <ul
          ref={listRef}
          className={s('domain-select__menu')}
          role="listbox"
          aria-label={t('optimize.domain_switch')}
          tabIndex={-1}
          onKeyDown={onListKeyDown}
          onMouseLeave={() => setHoveredKey(null)}
        >
          {options.map((option, index) => (
            <li
              key={option.key}
              role="option"
              aria-selected={option.id === value}
              className={s('domain-select__item')}
              data-active={index === activeIndex ? 'true' : 'false'}
              onMouseEnter={() => {
                setActiveIndex(index)
                setHoveredKey(option.key)
              }}
              onClick={() => select(option)}
            >
              <Tooltip
                anchorClassName={s('domain-select__anchor')}
                title={t(`tooltip.domain.${option.tipKey}.title`)}
                rows={[
                  {
                    label: t('tooltip.label_purpose'),
                    text: t(`tooltip.domain.${option.tipKey}.purpose`),
                  },
                  {
                    label: t('tooltip.label_usage'),
                    text: t(`tooltip.domain.${option.tipKey}.usage`),
                  },
                ]}
                placement="right"
                open={hoveredKey === option.key}
              >
                <span className={s('domain-select__option')}>
                  <span>{option.name}</span>
                  {option.id === value ? (
                    <span className={s('domain-select__check')} aria-hidden="true">
                      ✓
                    </span>
                  ) : null}
                </span>
              </Tooltip>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
