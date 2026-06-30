import IconNewChat from '@/assets/layout/newchat.svg'
import StoreImage from '@/assets/layout/store.svg'
import { useLang } from '@/i18n'
import { Avatar } from 'antd'
import { Link } from 'react-router-dom'
import './nav.scss'

export function Nav() {
  const { t } = useLang()
  const list = [
    { key: '1', label: t.navNewChat, icon: IconNewChat, href: '/' },
    { key: '2', label: t.navDocs, icon: StoreImage, href: '/repository' },
  ]

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

      <Avatar>W</Avatar>
    </div>
  )
}
