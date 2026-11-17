import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router'
import { HistoryPage } from '../pages/HistoryPage'
import { ObservabilityPage } from '../pages/ObservabilityPage'
import { OptimizePage } from '../pages/OptimizePage'

/**
 * Style Lab（样张页）只在开发环境存在：`import.meta.env.DEV` 在生产构建被替换为 false，
 * 分支连同 dynamic import 一起被 DCE 掉，lab 的 JS/CSS 不进产物（验收见 `verify-and-docs`）。
 */
const StyleLab = import.meta.env.DEV ? lazy(() => import('../lab/StyleLab')) : null

/** 路由表（/ 、/history、/observability）；未知路径兜底回优化主页。 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<OptimizePage />} />
      <Route path="/history" element={<HistoryPage />} />
      <Route path="/observability" element={<ObservabilityPage />} />
      {StyleLab !== null ? (
        <Route
          path="/__lab"
          element={
            <Suspense fallback={null}>
              <StyleLab />
            </Suspense>
          }
        />
      ) : null}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
