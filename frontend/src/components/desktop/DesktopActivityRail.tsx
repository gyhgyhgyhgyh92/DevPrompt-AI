/**
 * 桌面活动栏（2026-11-17）：48px 图标轨。
 *
 * 对标 Trae SOLO / VS Code 工作台的左侧活动栏（`.activitybar`）——纯导航入口，
 * 不含任何业务判定（MUST-08）。三项为路由入口（与 router/index.tsx 的路由表一致），
 * 设置中心不是路由，故为回调。
 *
 * 视觉取 Trae `.solo-icon-btn`：32×32 图标钮、圆角 6、hover 抬一级背景块（而非描边），
 * 激活态沿用本项目既有语言（左侧 2px 靛蓝竖线 + 极浅底）。
 */
import { Activity, History, MessageSquare, Settings } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { NavLink } from 'react-router'
import type { ReactNode } from 'react'
import { Tooltip } from '../ui/Tooltip'
import { makeS } from '../../utils/css'
import styles from './DesktopActivityRail.module.css'

const s = makeS(styles)

export interface DesktopActivityRailProps {
  /** 打开设置中心（设置不是路由，故为回调而非链接）。 */
  onOpenSettings: () => void
}

/** 路由入口三项：path / i18n 键 / 图标。`end` 用于根路由的精确匹配。 */
const ROUTE_ITEMS = [
  { to: '/', labelKey: 'desktop.rail.chat', Icon: MessageSquare, end: true },
  { to: '/history', labelKey: 'desktop.rail.history', Icon: History, end: false },
  { to: '/observability', labelKey: 'desktop.rail.observability', Icon: Activity, end: false },
] as const

export function DesktopActivityRail({ onOpenSettings }: DesktopActivityRailProps): ReactNode {
  const { t } = useTranslation()

  return (
    <nav className={s('app-rail')} aria-label={t('desktop.rail.label')}>
      {ROUTE_ITEMS.map((item) => (
        <Tooltip key={item.to} title={t(item.labelKey)} placement="right">
          <NavLink
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              isActive ? s('app-rail__item app-rail__item--active') : s('app-rail__item')
            }
            aria-label={t(item.labelKey)}
          >
            <item.Icon size={16} strokeWidth={1.5} aria-hidden="true" />
          </NavLink>
        </Tooltip>
      ))}
      <Tooltip title={t('desktop.rail.settings')} placement="right">
        <button
          type="button"
          className={s('app-rail__item app-rail__item--bottom')}
          aria-label={t('desktop.rail.settings')}
          onClick={onOpenSettings}
        >
          <Settings size={16} strokeWidth={1.5} aria-hidden="true" />
        </button>
      </Tooltip>
    </nav>
  )
}
