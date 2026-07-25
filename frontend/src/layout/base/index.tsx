import HeaderBar from '@/components/header-bar'
import classNames from 'classnames'
import { useLocation } from 'react-router-dom'
import './index.scss'
import { Nav } from './nav'

export function BaseLayout({ children }: { children?: React.ReactNode }) {
  const { pathname } = useLocation()

  // 移动端底栏默认透明：导航条以圆角浮起条的形态直接坐在页面背景上，两侧透出内容。
  //
  // 只有对话页例外。那里贴底的输入框本身就是一块不透明区，如果底栏还是透明的，
  // 两者会在 64px 处断开 —— 上面一块实底、下面透出正文，反而更割裂。
  // 所以对话页给底栏补同色底，与输入框合成一整块连续的底区。
  const maskedNav = pathname.startsWith('/chat')

  return (
    <div
      className={classNames('base-layout', {
        'base-layout--masked-nav': maskedNav,
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
