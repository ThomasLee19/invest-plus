import IconNewChat from '@/assets/layout/newchat.svg'
import StoreImage from '@/assets/layout/store.svg'
import { useLang } from '@/i18n'
import { Link } from 'react-router-dom'
import './nav.scss'

export function Nav() {
  const { t } = useLang()
  const list = [
    { key: '1', label: t.navNewChat, icon: IconNewChat, href: '/' },
    { key: '2', label: t.navDocs, icon: StoreImage, href: '/repository' },
  ]

  // 注：这里原先还渲染了一个 <Avatar>W</Avatar>。那是前身项目 PokemonRA 的字母
  // 残留，没有任何登录态或用户数据支撑它，却在桌面侧栏与移动底栏每一页可见。
  // 产品没有账号体系，一个孤零零的「W」头像只会引出「这是谁」的疑问。已删除。
  return (
    <div className="base-layout-nav">
      {list.map((item) => (
        <Link
          className="base-layout-nav__item"
          key={item.key}
          title={item.label}
          to={item.href ?? '#'}
        >
          <img src={item.icon} alt={item.label} />
        </Link>
      ))}
    </div>
  )
}
