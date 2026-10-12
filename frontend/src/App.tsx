import { Link, MemoryRouter } from 'react-router'
import { AppRoutes } from './router'

/**
 * 根组件 + 路由表。
 * 6B 工程基座阶段页面均为占位态，用 MemoryRouter 包住路由；
 * T6-4 页面落地后切 BrowserRouter，恢复 URL 直达与刷新定位。
 */
export function App() {
  return (
    <MemoryRouter>
      <nav>
        <Link to="/">优化</Link>
        <Link to="/history">历史</Link>
        <Link to="/preference">偏好</Link>
      </nav>
      <AppRoutes />
    </MemoryRouter>
  )
}
