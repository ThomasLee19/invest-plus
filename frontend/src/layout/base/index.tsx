import HeaderBar from '@/components/header-bar'
import classNames from 'classnames'
import { useLocation } from 'react-router-dom'
import './index.scss'
import { Nav } from './nav'

export function BaseLayout({ children }: { children?: React.ReactNode }) {
  const { pathname } = useLocation()

  // 移动端底栏默认带一层不透明底色，把从它下方滚过的正文遮住。
  // 首页是例外：内容居中、不存在长文滚动，遮蔽层反而会在页面底部压出一条
  // 与背景同色但边界可见的横带。这里让首页的导航条以圆角浮起条的形态直接坐在
  // 页面背景上，两侧透出内容 —— 对话页与资料库页有滚动正文，仍需遮蔽。
  const transparentNav = pathname === '/'

  return (
    <div
      className={classNames('base-layout', {
        'base-layout--transparent-nav': transparentNav,
      })}
    >
      <HeaderBar className="base-layout__header" />
      <main>
        <div className="base-layout__sidebar">
          <div className="base-layout__sidebar-main scrollbar-style">
            <div className="base-layout__sidebar-main-content">
              <Nav />
            </div>
          </div>
        </div>

        <div className="base-layout__content">{children}</div>
      </main>
    </div>
  )
}
